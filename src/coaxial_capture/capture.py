from __future__ import annotations

import datetime as dt
import shlex
import subprocess
import time
from pathlib import Path

from .process import SessionState, launch_process, process_alive, read_state, terminate_process_group, write_state
from .profile import Profile, ensure_profile_dirs


def _run_ros_command(profile: Profile, command: str) -> str:
    shell_cmd = f"source {shlex.quote(str(profile.ros.setup))} && {command}"
    completed = subprocess.run(  # noqa: S603
        ["bash", "-lc", shell_cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"Command failed: {command}")
    return completed.stdout


def _wait_for_topics(profile: Profile, topics: list[str], timeout_sec: int) -> None:
    if timeout_sec <= 0:
        return

    deadline = time.monotonic() + float(timeout_sec)
    while time.monotonic() < deadline:
        topic_list = _run_ros_command(profile, "ros2 topic list")
        visible = {line.strip() for line in topic_list.splitlines() if line.strip()}
        missing = [topic for topic in topics if topic not in visible]
        if not missing:
            return
        time.sleep(0.5)

    missing_text = ", ".join(missing)
    raise RuntimeError(f"Timed out waiting for topics: {missing_text}")


def _state_path(profile: Profile) -> Path:
    return profile.paths.state_dir / "capture_session.json"


def start_capture(profile: Profile, output_dir: Path | None = None) -> Path:
    ensure_profile_dirs(profile)
    state_path = _state_path(profile)
    if state_path.exists():
        existing = read_state(state_path)
        active = [proc for proc in existing.processes if process_alive(proc.pid)]
        if active:
            pids = ", ".join(str(proc.pid) for proc in active)
            raise RuntimeError(f"Capture already running with PIDs: {pids}")
        state_path.unlink()

    if output_dir is None:
        stamp = dt.datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
        output_dir = profile.paths.bags_dir / f"sync_{stamp}"

    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir = profile.paths.logs_dir / output_dir.name
    log_dir.mkdir(parents=True, exist_ok=True)

    records = []

    try:
        records.append(launch_process("event_driver", profile.ros.setup, profile.capture.event_driver_launch, log_dir))

        if profile.capture.launch_renderer:
            records.append(launch_process("event_renderer", profile.ros.setup, profile.capture.event_renderer_launch, log_dir))

        if profile.capture.launch_basler:
            records.append(launch_process("basler_driver", profile.ros.setup, profile.capture.basler_launch, log_dir))

        topics = [
            profile.topics.event_packets,
            profile.topics.basler_image,
            profile.topics.basler_info,
        ]
        if profile.capture.include_renderer_topic:
            topics.append(profile.topics.event_image)

        _wait_for_topics(profile, topics, profile.capture.wait_topics_sec)

        bag_topics = [profile.topics.event_packets, profile.topics.basler_image, profile.topics.basler_info]
        if profile.capture.include_renderer_topic:
            bag_topics.append(profile.topics.event_image)

        topics_arg = " ".join(shlex.quote(topic) for topic in bag_topics)
        record_cmd = (
            f"ros2 bag record --storage {shlex.quote(profile.capture.storage_id)} "
            f"-o {shlex.quote(str(output_dir))} --topics {topics_arg}"
        )
        records.append(launch_process("bag_record", profile.ros.setup, record_cmd, log_dir))

        state = SessionState(
            profile_name=profile.name,
            bag_dir=str(output_dir),
            processes=records,
        )
        write_state(state_path, state)
        latest_link = profile.paths.bags_dir / "latest"
        if latest_link.is_symlink() or latest_link.exists():
            latest_link.unlink()
        latest_link.symlink_to(output_dir, target_is_directory=True)

        return output_dir
    except Exception:
        for proc in reversed(records):
            terminate_process_group(proc.pid)
        raise


def stop_capture(profile: Profile) -> Path:
    state_path = _state_path(profile)
    if not state_path.exists():
        raise RuntimeError("No running capture session state found.")

    state = read_state(state_path)

    for proc in reversed(state.processes):
        terminate_process_group(proc.pid)

    state_path.unlink(missing_ok=True)
    return Path(state.bag_dir)


def capture_status(profile: Profile) -> tuple[str, list[tuple[str, int, bool]], Path | None]:
    state_path = _state_path(profile)
    if not state_path.exists():
        return "stopped", [], None

    state = read_state(state_path)
    process_rows = [(proc.name, proc.pid, process_alive(proc.pid)) for proc in state.processes]
    status = "running" if any(alive for _, _, alive in process_rows) else "stopped"
    return status, process_rows, Path(state.bag_dir)
