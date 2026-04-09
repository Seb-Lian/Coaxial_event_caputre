from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PathsConfig:
    workspace_root: Path
    bags_dir: Path
    logs_dir: Path
    outputs_dir: Path
    state_dir: Path


@dataclass(frozen=True)
class CaptureConfig:
    storage_id: str
    wait_topics_sec: int
    include_renderer_topic: bool
    launch_renderer: bool
    launch_basler: bool
    event_driver_launch: str
    event_renderer_launch: str
    basler_launch: str


@dataclass(frozen=True)
class TopicsConfig:
    event_packets: str
    event_image: str
    basler_image: str
    basler_info: str


@dataclass(frozen=True)
class EventResolution:
    width: int
    height: int


@dataclass(frozen=True)
class ExtractionConfig:
    window_ms: float
    image_ext: str
    color_mode: str
    transparent_bg: bool
    skip_empty_windows: bool
    max_pairs: int
    output_subdir: str
    raw_events_csv: bool
    raw_events_hdf5: bool
    event_resolution: EventResolution


@dataclass(frozen=True)
class RosConfig:
    setup: Path
    domain_id: int
    middleware: str


@dataclass(frozen=True)
class Profile:
    name: str
    ros: RosConfig
    paths: PathsConfig
    capture: CaptureConfig
    topics: TopicsConfig
    extraction: ExtractionConfig


def _to_path(value: str | Path) -> Path:
    return Path(str(value)).expanduser()


def _required(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def load_profile(profile_path: str | Path) -> Profile:
    path = _to_path(profile_path)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    ros = _required(data, "ros")
    paths = _required(data, "paths")
    capture = _required(data, "capture")
    topics = _required(data, "topics")
    extraction = _required(data, "extraction")

    resolution = _required(extraction, "event_resolution")

    profile = Profile(
        name=str(_required(data, "name")),
        ros=RosConfig(
            setup=_to_path(_required(ros, "setup")),
            domain_id=int(_required(ros, "domain_id")),
            middleware=str(_required(ros, "middleware")),
        ),
        paths=PathsConfig(
            workspace_root=_to_path(_required(paths, "workspace_root")),
            bags_dir=_to_path(_required(paths, "bags_dir")),
            logs_dir=_to_path(_required(paths, "logs_dir")),
            outputs_dir=_to_path(_required(paths, "outputs_dir")),
            state_dir=_to_path(_required(paths, "state_dir")),
        ),
        capture=CaptureConfig(
            storage_id=str(_required(capture, "storage_id")),
            wait_topics_sec=int(_required(capture, "wait_topics_sec")),
            include_renderer_topic=bool(_required(capture, "include_renderer_topic")),
            launch_renderer=bool(_required(capture, "launch_renderer")),
            launch_basler=bool(_required(capture, "launch_basler")),
            event_driver_launch=str(_required(capture, "event_driver_launch")),
            event_renderer_launch=str(_required(capture, "event_renderer_launch")),
            basler_launch=str(_required(capture, "basler_launch")),
        ),
        topics=TopicsConfig(
            event_packets=str(_required(topics, "event_packets")),
            event_image=str(_required(topics, "event_image")),
            basler_image=str(_required(topics, "basler_image")),
            basler_info=str(_required(topics, "basler_info")),
        ),
        extraction=ExtractionConfig(
            window_ms=float(_required(extraction, "window_ms")),
            image_ext=str(_required(extraction, "image_ext")),
            color_mode=str(_required(extraction, "color_mode")),
            transparent_bg=bool(_required(extraction, "transparent_bg")),
            skip_empty_windows=bool(_required(extraction, "skip_empty_windows")),
            max_pairs=int(_required(extraction, "max_pairs")),
            output_subdir=str(_required(extraction, "output_subdir")),
            raw_events_csv=bool(_required(extraction, "raw_events_csv")),
            raw_events_hdf5=bool(_required(extraction, "raw_events_hdf5")),
            event_resolution=EventResolution(
                width=int(_required(resolution, "width")),
                height=int(_required(resolution, "height")),
            ),
        ),
    )

    return profile


def ensure_profile_dirs(profile: Profile) -> None:
    profile.paths.bags_dir.mkdir(parents=True, exist_ok=True)
    profile.paths.logs_dir.mkdir(parents=True, exist_ok=True)
    profile.paths.outputs_dir.mkdir(parents=True, exist_ok=True)
    profile.paths.state_dir.mkdir(parents=True, exist_ok=True)
