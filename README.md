# Coaxial Event Capture

Maintainable ROS2 Jazzy pipeline to:

1. Run Basler + EVK4 in Docker.
2. Record synchronized topics to MCAP.
3. Extract event-frame pairs aligned to Basler frames.
4. Export decoded raw events to CSV and HDF5.

## Repository Layout

- `src/coaxial_capture`: Python package for capture, extraction, and UI commands.
- `config/profiles/default.yaml`: Single profile for ROS, topics, launch commands, and extraction settings.
- `config/basler`: Basler camera configuration files.
- `config/event_camera`: Event camera bias/config placeholders.
- `scripts`: Launch helper scripts.
- `docker`: Container image and runtime entrypoint.

## Quick Start

1. Put Basler pylon SDK .deb files in `installers/basler/` (optional for build-time install).
2. Update `config/profiles/default.yaml` with camera serials/topics.
3. Build and start container:

```bash
xhost +local:root
docker compose up -d --build
```

4. Enter container:

```bash
docker exec -it ros2_jazzy_coaxial_capture bash
source /opt/ros/jazzy/setup.bash
export PYTHONPATH=/workspace/src:${PYTHONPATH:-}
```

5. Run capture CLI:

```bash
python3 -m coaxial_capture.cli capture start --profile /workspace/config/profiles/default.yaml
```

Check status:

```bash
python3 -m coaxial_capture.cli capture status --profile /workspace/config/profiles/default.yaml
```

6. Stop capture:

```bash
python3 -m coaxial_capture.cli capture stop --profile /workspace/config/profiles/default.yaml
```

7. Extract synchronized pairs + raw event exports:

```bash
python3 -m coaxial_capture.cli extract run \
  --profile /workspace/config/profiles/default.yaml \
  --bag-path /workspace/bags/latest
```

8. Optional interactive mode:

```bash
python3 -m coaxial_capture.cli ui run --profile /workspace/config/profiles/default.yaml
```

## Host Network Setup

The Basler camera path expects jumbo frames on the host interface that is connected to the camera. In this setup that interface is `eno1`.

Set it for the current boot:

```bash
sudo ip link set dev eno1 down
sudo ip link set dev eno1 mtu 8192
sudo ip link set dev eno1 up
ifconfig
```

If you use NetworkManager and want the setting to survive reboots, find the active connection name first and then update its MTU:

```bash
nmcli connection show --active
sudo nmcli connection modify "<connection-name>" 802-3-ethernet.mtu 8192
sudo nmcli connection up "<connection-name>"
```

After changing the host MTU, restart the capture container so the camera driver reconnects cleanly.

## Output Artifacts

Capture output directory:

- `*.mcap` and `metadata.yaml` from rosbag2.

Extraction output directory:

- `basler/*.png` or `*.jpg`: Basler frames.
- `basler_raw/*.png` or `*.jpg`: Original Basler frames before mirror/crop/resize.
- `event/*.png` or `*.jpg`: Window-rendered event frames.
- `pairs.csv`: Timestamp alignment metadata per pair.
- `raw_events.csv`: Decoded raw event stream export (if enabled).
- `raw_events.h5`: Decoded raw event stream export in HDF5 (if enabled).
- `summary.csv`: High-level extraction counters.

## Profile Notes

- `capture.event_driver_launch`: EVK4 driver launch command.
- `capture.event_renderer_launch`: Renderer launch command.
- `capture.basler_launch`: Basler launch helper command.
- `capture.basler_enable_chunk_timestamp`: If true, capture startup calls Basler chunk services so `image_raw.header.stamp` uses acquisition timestamp (when camera supports chunk timestamp).
- `capture.wait_topics_sec`: Timeout before recording starts.
- `capture.startup_message_check_sec`: After recording starts, probes key topics for a first message and warns if one feed is silent.
- `config/basler/my_camera.yaml` transport knobs:
  `inter_pkg_delay` (lower for higher FPS), `frame_transmission_delay` (keep at 0 for single camera), and launch `--mtu-size` should match host NIC MTU.
- `--startup-user-set Default` is best for reproducible throughput. If alignment regresses, keep `Default` and enable `capture.basler_enable_chunk_timestamp: true` rather than switching back to `CurrentSetting`.
- In `basler_launch_helper.sh`, `--enable-status-publisher false` and `--enable-current-params-publisher false` reduce wrapper overhead.
- Default capture records raw event packets only (`capture.launch_renderer: false`, `capture.include_renderer_topic: false`).
- `extraction.mirror_basler_image`: Mirror Basler frames horizontally before saving during offline extraction.
- `extraction.mirror_event_image`: Mirror rendered event frames horizontally before saving during offline extraction.
- `extraction.crop_basler_image`: Crop Basler frames before saving during offline extraction.
- If cropping is enabled, set `basler_pixel_pitch_um` and `event_pixel_pitch_um` to the effective pixel pitches after any binning. The crop is computed as $w_c = \mathrm{round}(R_e^w \cdot p_e / p_b)$ and $h_c = \mathrm{round}(R_e^h \cdot p_e / p_b)$, where $R_e$ is the event sensor resolution and $p$ is pixel pitch in micrometers.
- `extraction.basler_crop_offset_x_px` and `extraction.basler_crop_offset_y_px`: Horizontal and vertical crop-center offsets in Basler pixels. Positive $x$ shifts right; positive $y$ shifts down.
- After cropping, Basler frames are resized to `extraction.event_resolution` so output Basler/event image pairs share the same resolution.
- `extraction.drop_leading_empty_windows`: Drops startup Basler frames that have zero events so extraction begins at the first event-supported pair.
- `extraction.window_ms`: Event window half-width around each Basler frame timestamp.

## Notes

- This project focuses on deterministic orchestration and offline extraction.
- ROS2 packages for hardware drivers must be available in the container image.
- Event decoding currently supports `evt3` payloads.
