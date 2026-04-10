from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class ProcessRecord:
    name: str
    pid: int
    command: str
    log_path: str


@dataclass
class SessionState:
    profile_name: str
    bag_dir: str
    processes: list[ProcessRecord]


def _compose_ros_shell_command(ros_setup: Path, command: str) -> str:
    setup_candidates = [
        ros_setup,
        Path("/opt/basler_ws/install/setup.bash"),
        Path("/workspace/install/setup.bash"),
    ]

    setup_steps: list[str] = []
    for setup_file in setup_candidates:
        safe_setup = shlex.quote(str(setup_file))
        setup_steps.append(f"if [[ -f {safe_setup} ]]; then source {safe_setup}; fi")

    return f"{' && '.join(setup_steps)} && {command}"


def launch_process(name: str, ros_setup: Path, command: str, log_dir: Path) -> ProcessRecord:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{name}.log"
    shell_cmd = _compose_ros_shell_command(ros_setup, command)

    with log_path.open("ab") as log_handle:
        proc = subprocess.Popen(  # noqa: S603
            ["bash", "-lc", shell_cmd],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    return ProcessRecord(
        name=name,
        pid=proc.pid,
        command=command,
        log_path=str(log_path),
    )


def terminate_process_group(pid: int, gentle_timeout_sec: float = 8.0) -> None:
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return

    try:
        os.killpg(pgid, signal.SIGINT)
    except ProcessLookupError:
        return

    deadline = gentle_timeout_sec
    step = 0.2
    elapsed = 0.0
    while elapsed < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(step)
        elapsed += step

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def write_state(path: Path, state: SessionState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "profile_name": state.profile_name,
        "bag_dir": state.bag_dir,
        "processes": [asdict(p) for p in state.processes],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_state(path: Path) -> SessionState:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SessionState(
        profile_name=str(payload["profile_name"]),
        bag_dir=str(payload["bag_dir"]),
        processes=[ProcessRecord(**proc) for proc in payload.get("processes", [])],
    )
