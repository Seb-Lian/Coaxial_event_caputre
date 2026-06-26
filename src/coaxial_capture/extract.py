from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Optional

import cv2
import h5py
import numpy as np
from event_camera_msgs.msg import EventPacket
from rclpy.serialization import deserialize_message
from rosbag2_py import ConverterOptions, SequentialReader, StorageOptions
from sensor_msgs.msg import Image

from .profile import Profile


def stamp_to_ns(msg: Image) -> int:
    return int(msg.header.stamp.sec) * 1_000_000_000 + int(msg.header.stamp.nanosec)


def choose_time_ns(preferred_ns: int, fallback_ns: int) -> int:
    # Returns preferred_ns when positive, otherwise falls back to fallback_ns.
    return int(preferred_ns) if int(preferred_ns) > 0 else int(fallback_ns)


def image_msg_to_cv2(msg: Image) -> np.ndarray:
    encoding = msg.encoding.lower().strip()
    if not encoding:
        raise RuntimeError("Image message has empty encoding")

    # Common encodings used by Basler and ROS image pipelines.
    if encoding in {"mono8", "8uc1"}:
        dtype = np.uint8
        channels = 1
    elif encoding in {"mono16", "16uc1", "16sc1"}:
        dtype = np.uint16
        channels = 1
    elif encoding in {"bgr8", "rgb8", "8uc3"}:
        dtype = np.uint8
        channels = 3
    elif encoding in {"bgra8", "rgba8", "8uc4"}:
        dtype = np.uint8
        channels = 4
    elif encoding in {"bayer_rggb8", "bayer_bggr8", "bayer_gbrg8", "bayer_grbg8"}:
        dtype = np.uint8
        channels = 1
    else:
        raise RuntimeError(f"Unsupported image encoding: {msg.encoding}")

    itemsize = np.dtype(dtype).itemsize
    expected_row_bytes = int(msg.width) * channels * itemsize
    if int(msg.step) < expected_row_bytes:
        raise RuntimeError(
            f"Invalid image step {msg.step} for encoding {msg.encoding}; expected at least {expected_row_bytes}"
        )

    data = np.frombuffer(msg.data, dtype=dtype)
    total_values_per_row = int(msg.step) // itemsize
    needed_values = int(msg.height) * total_values_per_row
    if data.size < needed_values:
        raise RuntimeError(
            f"Image data too short for shape ({msg.height}, {total_values_per_row}); got {data.size} values"
        )

    img = data[:needed_values].reshape((int(msg.height), total_values_per_row))
    img = img[:, : int(msg.width) * channels]

    if channels == 1:
        out = img
    else:
        out = img.reshape((int(msg.height), int(msg.width), channels))

    if msg.is_bigendian and out.dtype.itemsize > 1:
        out = out.byteswap().newbyteorder()

    # cv2.imwrite expects BGR/BGRA ordering for color images.
    if encoding == "rgb8":
        out = cv2.cvtColor(out, cv2.COLOR_RGB2BGR)
    elif encoding == "rgba8":
        out = cv2.cvtColor(out, cv2.COLOR_RGBA2BGRA)
    elif encoding == "bayer_rggb8":
        out = cv2.cvtColor(out, cv2.COLOR_BayerRG2BGR)
    elif encoding == "bayer_bggr8":
        out = cv2.cvtColor(out, cv2.COLOR_BayerRG2BGR)
    elif encoding == "bayer_gbrg8":
        out = cv2.cvtColor(out, cv2.COLOR_BayerGB2BGR)
    elif encoding == "bayer_grbg8":
        out = cv2.cvtColor(out, cv2.COLOR_BayerGR2BGR)

    return out


def crop_image_with_offset(
    image: np.ndarray,
    crop_width: int,
    crop_height: int,
    offset_x_px: int,
    offset_y_px: int,
) -> np.ndarray:
    image_height, image_width = image.shape[:2]
    crop_width = max(1, min(int(crop_width), image_width))
    crop_height = max(1, min(int(crop_height), image_height))

    center_x = (image_width / 2.0) + float(offset_x_px)
    center_y = (image_height / 2.0) + float(offset_y_px)

    left = int(round(center_x - (crop_width / 2.0)))
    top = int(round(center_y - (crop_height / 2.0)))

    left = max(0, min(left, image_width - crop_width))
    top = max(0, min(top, image_height - crop_height))
    return image[top : top + crop_height, left : left + crop_width]


@dataclass
class EventChunk:
    t_ns: np.ndarray
    x: np.ndarray
    y: np.ndarray
    p: np.ndarray
    t_min_ns: int
    t_max_ns: int


class Evt3DecoderState:
    ADDR_Y = 0
    ADDR_X = 2
    VECT_BASE_X = 3
    VECT_12 = 4
    VECT_8 = 5
    TIME_LOW = 6
    TIME_HIGH = 8

    def __init__(self, width: int, height: int) -> None:
        self.ey = 0
        self.time_low = 0
        self.time_high = 0
        self.current_polarity = 0
        self.current_base_x = 0
        self.has_valid_time = False
        self.time_mult_ns = 1000
        self.width = width
        self.height = height

    @staticmethod
    def _update_high_time(t: int, current_high: int) -> int:
        last_high = (current_high >> 12) & ((1 << 12) - 1)
        if t < last_high and (last_high - t) > 10:
            current_high += 1 << 24
        current_high = (current_high & (~((1 << 24) - 1))) | (int(t) << 12)
        return current_high

    def _make_time_ns(self) -> int:
        return int((self.time_high | self.time_low) * self.time_mult_ns)

    def decode_packet(self, msg: EventPacket) -> Optional[EventChunk]:
        encoding = msg.encoding.lower().strip()
        if encoding != "evt3":
            raise RuntimeError(f"Unsupported event encoding '{msg.encoding}'. Only evt3 is supported.")

        if msg.width > 0:
            self.width = int(msg.width)
        if msg.height > 0:
            self.height = int(msg.height)

        payload = bytes(msg.events)
        n_words = len(payload) // 2
        if n_words == 0:
            return None

        t_list: list[int] = []
        x_list: list[int] = []
        y_list: list[int] = []
        p_list: list[int] = []

        idx = 0
        if not self.has_valid_time:
            has_valid_high_time = False
            while idx < n_words and not self.has_valid_time:
                word = payload[2 * idx] | (payload[2 * idx + 1] << 8)
                code = (word >> 12) & 0xF
                rest = word & 0x0FFF
                if code == self.TIME_LOW:
                    self.time_low = rest
                    if has_valid_high_time:
                        self.has_valid_time = True
                elif code == self.TIME_HIGH:
                    self.time_high = self._update_high_time(rest, self.time_high)
                    has_valid_high_time = True
                idx += 1

        for i in range(idx, n_words):
            word = payload[2 * i] | (payload[2 * i + 1] << 8)
            code = (word >> 12) & 0xF
            rest = word & 0x0FFF

            if code == self.ADDR_X:
                x = rest & 0x07FF
                pol = (rest >> 11) & 0x1
                if x < self.width and self.ey < self.height and self.has_valid_time:
                    t_list.append(self._make_time_ns())
                    x_list.append(x)
                    y_list.append(self.ey)
                    p_list.append(pol)
            elif code == self.ADDR_Y:
                self.ey = rest & 0x07FF
            elif code == self.TIME_LOW:
                self.time_low = rest
            elif code == self.TIME_HIGH:
                self.time_high = self._update_high_time(rest, self.time_high)
            elif code == self.VECT_BASE_X:
                self.current_base_x = rest & 0x07FF
                self.current_polarity = (rest >> 11) & 0x1
            elif code == self.VECT_8:
                valid = rest & 0x00FF
                if self.has_valid_time:
                    ts = self._make_time_ns()
                    for bit in range(8):
                        if valid & (1 << bit):
                            x = self.current_base_x + bit
                            if x < self.width and self.ey < self.height:
                                t_list.append(ts)
                                x_list.append(x)
                                y_list.append(self.ey)
                                p_list.append(self.current_polarity)
                self.current_base_x += 8
            elif code == self.VECT_12:
                valid = rest & 0x0FFF
                if self.has_valid_time:
                    ts = self._make_time_ns()
                    for bit in range(12):
                        if valid & (1 << bit):
                            x = self.current_base_x + bit
                            if x < self.width and self.ey < self.height:
                                t_list.append(ts)
                                x_list.append(x)
                                y_list.append(self.ey)
                                p_list.append(self.current_polarity)
                self.current_base_x += 12

        if not t_list:
            return None

        t_ns = np.asarray(t_list, dtype=np.int64)
        x = np.asarray(x_list, dtype=np.int32)
        y = np.asarray(y_list, dtype=np.int32)
        p = np.asarray(p_list, dtype=np.uint8)
        return EventChunk(
            t_ns=t_ns,
            x=x,
            y=y,
            p=p,
            t_min_ns=int(t_ns.min()),
            t_max_ns=int(t_ns.max()),
        )


class RawEventWriters:
    def __init__(self, output_dir: Path, write_csv: bool, write_hdf5: bool) -> None:
        self.csv_file = None
        self.csv_writer = None
        self.h5_file = None
        self.h5_t = None
        self.h5_x = None
        self.h5_y = None
        self.h5_p = None
        self.h5_len = 0

        if write_csv:
            csv_path = output_dir / "raw_events.csv"
            self.csv_file = csv_path.open("w", newline="", encoding="utf-8")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(["t_ns", "x", "y", "p"])

        if write_hdf5:
            h5_path = output_dir / "raw_events.h5"
            self.h5_file = h5py.File(h5_path, "w")
            self.h5_t = self.h5_file.create_dataset("t_ns", shape=(0,), maxshape=(None,), dtype="i8")
            self.h5_x = self.h5_file.create_dataset("x", shape=(0,), maxshape=(None,), dtype="i4")
            self.h5_y = self.h5_file.create_dataset("y", shape=(0,), maxshape=(None,), dtype="i4")
            self.h5_p = self.h5_file.create_dataset("p", shape=(0,), maxshape=(None,), dtype="u1")

    def append(self, t_ns: np.ndarray, x: np.ndarray, y: np.ndarray, p: np.ndarray) -> None:
        if t_ns.size == 0:
            return

        if self.csv_writer is not None:
            for i in range(t_ns.size):
                self.csv_writer.writerow([int(t_ns[i]), int(x[i]), int(y[i]), int(p[i])])

        if self.h5_file is not None and self.h5_t is not None and self.h5_x is not None and self.h5_y is not None and self.h5_p is not None:
            count = t_ns.size
            new_len = self.h5_len + count
            self.h5_t.resize((new_len,))
            self.h5_x.resize((new_len,))
            self.h5_y.resize((new_len,))
            self.h5_p.resize((new_len,))
            self.h5_t[self.h5_len:new_len] = t_ns
            self.h5_x[self.h5_len:new_len] = x
            self.h5_y[self.h5_len:new_len] = y
            self.h5_p[self.h5_len:new_len] = p
            self.h5_len = new_len

    def close(self) -> None:
        if self.csv_file is not None:
            self.csv_file.flush()
            self.csv_file.close()
        if self.h5_file is not None:
            self.h5_file.flush()
            self.h5_file.close()


class OfflineExtractor:
    def __init__(
        self,
        profile: Profile,
        bag_path: Path,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
        total_pairs_target: int | None = None,
    ) -> None:
        self.profile = profile
        self.bag_path = bag_path
        self.output_dir = output_dir
        self.progress_callback = progress_callback
        self.total_pairs_target = total_pairs_target

        self.basler_dir = self.output_dir / "basler"
        self.basler_raw_dir = self.output_dir / "basler_raw"
        self.event_dir = self.output_dir / "event"
        self.basler_dir.mkdir(parents=True, exist_ok=True)
        self.basler_raw_dir.mkdir(parents=True, exist_ok=True)
        self.event_dir.mkdir(parents=True, exist_ok=True)

        self.window_ns = int(profile.extraction.window_ms * 1_000_000.0)
        self.image_ext = profile.extraction.image_ext.lower().strip(".")
        self.color_mode = profile.extraction.color_mode
        self.mirror_basler_image = profile.extraction.mirror_basler_image
        self.mirror_event_image = profile.extraction.mirror_event_image
        self.crop_basler_image = profile.extraction.crop_basler_image
        self.transparent_bg = profile.extraction.transparent_bg
        self.skip_empty = profile.extraction.skip_empty_windows
        self.drop_leading_empty_windows = profile.extraction.drop_leading_empty_windows
        self.max_pairs = profile.extraction.max_pairs
        self.event_output_width = int(profile.extraction.event_resolution.width)
        self.event_output_height = int(profile.extraction.event_resolution.height)
        self.basler_crop_offset_x_px = int(profile.extraction.basler_crop_offset_x_px)
        self.basler_crop_offset_y_px = int(profile.extraction.basler_crop_offset_y_px)
        self.basler_timestamp_offset_ns = int(profile.extraction.basler_timestamp_offset_ns)

        self.basler_crop_width: int | None = None
        self.basler_crop_height: int | None = None
        if self.crop_basler_image:
            missing_fields = [
                name
                for name, value in {
                    "basler_pixel_pitch_um": profile.extraction.basler_pixel_pitch_um,
                    "event_pixel_pitch_um": profile.extraction.event_pixel_pitch_um,
                }.items()
                if value is None
            ]
            if missing_fields:
                raise ValueError(
                    "crop_basler_image requires basler_pixel_pitch_um and event_pixel_pitch_um"
                )

            basler_pitch_um = float(profile.extraction.basler_pixel_pitch_um)
            event_pitch_um = float(profile.extraction.event_pixel_pitch_um)
            if basler_pitch_um <= 0.0 or event_pitch_um <= 0.0:
                raise ValueError("basler_pixel_pitch_um and event_pixel_pitch_um must be positive")
            self.basler_crop_width = int(round(float(self.event_output_width) * event_pitch_um / basler_pitch_um))
            self.basler_crop_height = int(round(float(self.event_output_height) * event_pitch_um / basler_pitch_um))

        if self.image_ext not in {"png", "jpg", "jpeg"}:
            raise ValueError("image_ext must be png, jpg, or jpeg")

        self.decoder = Evt3DecoderState(
            width=self.event_output_width,
            height=self.event_output_height,
        )

        self.event_chunks: Deque[EventChunk] = deque()
        self.pending_basler: Deque[tuple[Image, int]] = deque()
        self.latest_event_ns: Optional[int] = None

        self.pair_count = 0
        self.basler_seen = 0
        self.event_packets_seen = 0
        self.empty_windows = 0
        self.leading_empty_windows = 0

        self.pairs_csv_path = self.output_dir / "pairs.csv"
        self.pairs_csv_file = self.pairs_csv_path.open("w", newline="", encoding="utf-8")
        self.pairs_writer = csv.writer(self.pairs_csv_file)
        self.pairs_writer.writerow(
            [
                "pair_index",
                "basler_stamp_ns",
                "event_ref_stamp_ns",
                "delta_us",
                "event_count",
                "window_start_ns",
                "window_end_ns",
                "basler_path",
                "event_path",
            ]
        )

        self.raw_writer = RawEventWriters(
            output_dir=self.output_dir,
            write_csv=profile.extraction.raw_events_csv,
            write_hdf5=profile.extraction.raw_events_hdf5,
        )

    def add_event_packet(self, msg: EventPacket, bag_ts_ns: int) -> None:
        self.event_packets_seen += 1
        chunk = self.decoder.decode_packet(msg)
        if chunk is None:
            self.process_pending(flush=False)
            self.prune_chunks()
            return

        header_ns = stamp_to_ns(msg)
        # Prefer the driver's header timestamp over the recorder's bag timestamp.
        # Under CPU throttling the recorder receives messages with variable DDS
        # transport delay that differs per packet, which corrupts the anchor and
        # causes chunks to land at wrong (and potentially out-of-order) absolute
        # times.  The driver sets header.stamp much closer to event-hardware time
        # and is not affected by recorder-side scheduling jitter.
        # packet_anchor_ns = choose_time_ns(bag_ts_ns, header_ns)
        packet_offset_ns = header_ns - chunk.t_max_ns
        chunk.t_ns = chunk.t_ns + packet_offset_ns
        chunk.t_min_ns += packet_offset_ns
        chunk.t_max_ns += packet_offset_ns

        self.raw_writer.append(chunk.t_ns, chunk.x, chunk.y, chunk.p)

        self.event_chunks.append(chunk)
        # Track the highest timestamp seen, not just the most-recently-processed
        # chunk.  If a jittered chunk arrives with a lower t_max_ns than the
        # previous one, process_pending's guard must not regress.
        self.latest_event_ns = max(self.latest_event_ns or 0, chunk.t_max_ns)

        self.process_pending(flush=False)
        self.prune_chunks()

    def add_basler_image(self, msg: Image, bag_ts_ns: int) -> None:
        header_ns = stamp_to_ns(msg)
        # Prefer driver/hardware header timestamp for the same reason as event
        # packets: recorder-side jitter is higher under CPU throttling.
        # ts_ns = choose_time_ns(bag_ts_ns, header_ns)
        # basler_timestamp_offset_ns compensates for GigE transfer latency: the
        # host stamps frames at receipt, which lags behind actual exposure end by
        # roughly frame_size / link_bandwidth. Set to a negative value (e.g.
        # -18000000 for -18 ms) measured from the median delta_us in pairs.csv.
        ts_ns = header_ns + self.basler_timestamp_offset_ns
        self.pending_basler.append((msg, ts_ns))
        self.basler_seen += 1

        self.process_pending(flush=False)
        self.prune_chunks()

    def prune_chunks(self) -> None:
        if not self.event_chunks:
            return

        if self.pending_basler:
            keep_from_ns = self.pending_basler[0][1] - self.window_ns
        elif self.latest_event_ns is not None:
            keep_from_ns = self.latest_event_ns - max(5 * self.window_ns, 5_000_000_000)
        else:
            return

        while self.event_chunks and self.event_chunks[0].t_max_ns < keep_from_ns:
            self.event_chunks.popleft()

    def process_pending(self, flush: bool) -> None:
        while self.pending_basler:
            basler_msg, basler_ns = self.pending_basler[0]
            window_end_ns = basler_ns + self.window_ns

            if not flush:
                if self.latest_event_ns is None or self.latest_event_ns < window_end_ns:
                    break

            # Skip until event stream has caught up to Basler
            if self.latest_event_ns is not None:
                startup_diff_ms = (basler_ns - self.latest_event_ns) / 1_000_000
                if startup_diff_ms > 100:  # more than 100ms behind
                    self.pending_basler.popleft()
                    self.leading_empty_windows += 1
                    continue

            self.pending_basler.popleft()
            self.save_pair(basler_msg, basler_ns)

            if self.max_pairs > 0 and self.pair_count >= self.max_pairs:
                return

    def collect_window_events(self, start_ns: int, end_ns: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        t_parts: list[np.ndarray] = []
        x_parts: list[np.ndarray] = []
        y_parts: list[np.ndarray] = []
        p_parts: list[np.ndarray] = []

        for chunk in self.event_chunks:
            if chunk.t_max_ns < start_ns:
                continue
            # Use continue rather than break: under CPU throttling chunks may
            # arrive slightly out of temporal order, so a chunk with
            # t_min_ns > end_ns does not guarantee all later chunks are also
            # outside the window.
            if chunk.t_min_ns > end_ns:
                continue

            mask = (chunk.t_ns >= start_ns) & (chunk.t_ns <= end_ns)
            if np.any(mask):
                t_parts.append(chunk.t_ns[mask])
                x_parts.append(chunk.x[mask])
                y_parts.append(chunk.y[mask])
                p_parts.append(chunk.p[mask])

        if not t_parts:
            empty_i64 = np.asarray([], dtype=np.int64)
            empty_i32 = np.asarray([], dtype=np.int32)
            empty_u8 = np.asarray([], dtype=np.uint8)
            return empty_i64, empty_i32, empty_i32, empty_u8

        t_all = np.concatenate(t_parts)
        x_all = np.concatenate(x_parts)
        y_all = np.concatenate(y_parts)
        p_all = np.concatenate(p_parts)

        # Sort by timestamp so the output is always temporally ordered
        # regardless of what order chunks were inserted.
        order = np.argsort(t_all, kind="stable")
        return t_all[order], x_all[order], y_all[order], p_all[order]

    def render_event_image(self, x: np.ndarray, y: np.ndarray, p: np.ndarray) -> np.ndarray:
        width = max(1, self.decoder.width)
        height = max(1, self.decoder.height)

        if self.transparent_bg:
            img = np.zeros((height, width, 4), dtype=np.uint8)
        elif self.color_mode == "blue-red":
            img = np.zeros((height, width, 3), dtype=np.uint8)
        else:
            img = np.full((height, width), 127, dtype=np.uint8)

        if x.size == 0:
            return img

        x = np.clip(x, 0, width - 1)
        y = np.clip(y, 0, height - 1)

        if self.transparent_bg:
            on_mask = p.astype(bool)
            off_mask = ~on_mask
            img[y[on_mask], x[on_mask], :3] = (0, 255, 0)
            img[y[off_mask], x[off_mask], :3] = (0, 0, 255)
            img[y, x, 3] = 255
            return img

        if self.color_mode == "blue-red":
            on_mask = p.astype(bool)
            off_mask = ~on_mask
            img[y[on_mask], x[on_mask], :] = (0, 255, 0)
            img[y[off_mask], x[off_mask], :] = (0, 0, 255)
            return img

        on_mask = p.astype(bool)
        off_mask = ~on_mask
        img[y[on_mask], x[on_mask]] = 255
        img[y[off_mask], x[off_mask]] = 0
        return img

    def save_pair(self, basler_msg: Image, basler_ns: int) -> None:
        if self.max_pairs > 0 and self.pair_count >= self.max_pairs:
            return

        window_start_ns = basler_ns - self.window_ns
        window_end_ns = basler_ns + self.window_ns

        t_ns, x, y, p = self.collect_window_events(window_start_ns, window_end_ns)
        event_count = int(t_ns.size)

        if event_count == 0 and self.drop_leading_empty_windows and self.pair_count == 0:
            self.leading_empty_windows += 1
            return

        if event_count == 0 and self.skip_empty:
            self.empty_windows += 1
            return

        try:
            basler_img = image_msg_to_cv2(basler_msg)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to convert Basler image: {exc}") from exc

        basler_img_raw = basler_img.copy()

        if self.mirror_basler_image:
            basler_img = cv2.flip(basler_img, 1)
        if self.crop_basler_image and self.basler_crop_width is not None and self.basler_crop_height is not None:
            basler_img = crop_image_with_offset(
                basler_img,
                self.basler_crop_width,
                self.basler_crop_height,
                self.basler_crop_offset_x_px,
                self.basler_crop_offset_y_px,
            )
            if basler_img.shape[1] != self.event_output_width or basler_img.shape[0] != self.event_output_height:
                basler_img = cv2.resize(
                    basler_img,
                    (self.event_output_width, self.event_output_height),
                    interpolation=cv2.INTER_LINEAR,
                )

        event_img = self.render_event_image(x, y, p)
        if self.mirror_event_image:
            event_img = cv2.flip(event_img, 1)

        ref_ns = int(np.median(t_ns)) if event_count > 0 else basler_ns
        delta_us = (ref_ns - basler_ns) / 1000.0

        stem = f"pair_{self.pair_count:06d}_{basler_ns}"
        basler_raw_name = f"{stem}_basler_raw.{self.image_ext}"
        basler_name = f"{stem}_basler.{self.image_ext}"
        event_name = f"{stem}_event.{self.image_ext}"

        basler_raw_path = self.basler_raw_dir / basler_raw_name
        basler_path = self.basler_dir / basler_name
        event_path = self.event_dir / event_name

                # In save_pair, add temporarily at the top:
        if self.pair_count < 0:
            print(f"pair {self.pair_count}:")
            print(f"  basler_ns:    {basler_ns}")
            print(f"  window_start: {basler_ns - self.window_ns}")
            print(f"  window_end:   {basler_ns + self.window_ns}")
            if event_count > 0:
                print(f"  t_ns min:     {t_ns.min()}")
                print(f"  t_ns max:     {t_ns.max()}")
                print(f"  t_ns median:  {int(np.median(t_ns))}")

        if not cv2.imwrite(str(basler_raw_path), basler_img_raw):
            raise RuntimeError(f"Failed writing {basler_raw_path}")
        if not cv2.imwrite(str(basler_path), basler_img):
            raise RuntimeError(f"Failed writing {basler_path}")
        if not cv2.imwrite(str(event_path), event_img):
            raise RuntimeError(f"Failed writing {event_path}")

        self.pairs_writer.writerow(
            [
                self.pair_count,
                basler_ns,
                ref_ns,
                f"{delta_us:.3f}",
                event_count,
                window_start_ns,
                window_end_ns,
                str(Path("basler") / basler_name),
                str(Path("event") / event_name),
            ]
        )

        self.pair_count += 1
        if self.progress_callback is not None and self.total_pairs_target is not None and self.total_pairs_target > 0:
            self.progress_callback(self.pair_count, self.total_pairs_target)
        if self.pair_count % 50 == 0:
            self.pairs_csv_file.flush()

    def run(self) -> None:
        reader = SequentialReader()
        storage_options = StorageOptions(uri=str(self.bag_path), storage_id=self.profile.capture.storage_id)
        converter_options = ConverterOptions("", "")
        reader.open(storage_options, converter_options)

        topic_type = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
        basler_topic = self.profile.topics.basler_image
        event_topic = self.profile.topics.event_packets

        if basler_topic not in topic_type:
            raise RuntimeError(f"Missing Basler topic in bag: {basler_topic}")
        if event_topic not in topic_type:
            raise RuntimeError(f"Missing event topic in bag: {event_topic}")

        while reader.has_next():
            topic, serialized_data, bag_ts_ns = reader.read_next()
            if topic == event_topic:
                msg = deserialize_message(serialized_data, EventPacket)
                self.add_event_packet(msg, bag_ts_ns)
            elif topic == basler_topic:
                msg = deserialize_message(serialized_data, Image)
                self.add_basler_image(msg, bag_ts_ns)

            if self.max_pairs > 0 and self.pair_count >= self.max_pairs:
                break

        self.process_pending(flush=True)

    def close(self) -> dict[str, int]:
        self.pairs_csv_file.flush()
        self.pairs_csv_file.close()
        self.raw_writer.close()

        summary = {
            "pairs_saved": self.pair_count,
            "basler_frames_seen": self.basler_seen,
            "event_packets_seen": self.event_packets_seen,
            "empty_windows_skipped": self.empty_windows,
            "leading_empty_windows_skipped": self.leading_empty_windows,
        }

        summary_path = self.output_dir / "summary.csv"
        with summary_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["metric", "value"])
            for key, value in summary.items():
                writer.writerow([key, value])

        return summary


def _count_topic_messages(profile: Profile, bag_path: Path, topic_name: str) -> int:
    reader = SequentialReader()
    storage_options = StorageOptions(uri=str(bag_path), storage_id=profile.capture.storage_id)
    converter_options = ConverterOptions("", "")
    reader.open(storage_options, converter_options)

    count = 0
    while reader.has_next():
        topic, _, _ = reader.read_next()
        if topic == topic_name:
            count += 1
    return count


def run_extraction(
    profile: Profile,
    bag_path: Path,
    output_dir: Path | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[Path, dict[str, int]]:
    bag_path = bag_path.expanduser().resolve()
    if not (bag_path / "metadata.yaml").exists():
        raise RuntimeError(f"Bag path is missing metadata.yaml: {bag_path}")

    if output_dir is None:
        output_dir = profile.paths.outputs_dir / f"{profile.extraction.window_ms}_{profile.extraction.output_subdir}_{bag_path.name}"
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    total_basler_frames = _count_topic_messages(profile, bag_path, profile.topics.basler_image)
    total_pairs_target = total_basler_frames
    if profile.extraction.max_pairs > 0:
        total_pairs_target = min(total_pairs_target, profile.extraction.max_pairs)

    extractor = OfflineExtractor(
        profile=profile,
        bag_path=bag_path,
        output_dir=output_dir,
        progress_callback=progress_callback,
        total_pairs_target=total_pairs_target,
    )
    try:
        extractor.run()
    finally:
        summary = extractor.close()

    return output_dir, summary
