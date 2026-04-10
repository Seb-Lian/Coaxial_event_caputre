from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path

from .capture import capture_status, start_capture, stop_capture
from .profile import ensure_profile_dirs, load_profile


def _profile_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        required=True,
        help="Path to profile YAML.",
    )


def _capture_start(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    ensure_profile_dirs(profile)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
    bag_dir = start_capture(profile, output_dir=output_dir)
    print(f"Capture started. Bag output: {bag_dir}")
    return 0


def _capture_stop(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    bag_dir = stop_capture(profile)
    print(f"Capture stopped. Bag output: {bag_dir}")
    return 0


def _capture_status(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    status, rows, bag_dir = capture_status(profile)
    print(f"status={status}")
    if bag_dir is not None:
        print(f"bag_dir={bag_dir}")
    for name, pid, alive in rows:
        print(f"- {name}: pid={pid} alive={alive}")
    return 0


def _extract_run(args: argparse.Namespace) -> int:
    from .extract import run_extraction

    profile = load_profile(args.profile)
    bag_path = Path(args.bag_path).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None

    def _on_progress(done_pairs: int, total_pairs: int) -> None:
        pct = 100.0 * float(done_pairs) / float(total_pairs) if total_pairs > 0 else 100.0
        print(f"pair_created={done_pairs}/{total_pairs} ({pct:.1f}%)")

    out_path, summary = run_extraction(
        profile,
        bag_path=bag_path,
        output_dir=output_dir,
        progress_callback=_on_progress,
    )
    print(f"Extraction output: {out_path}")
    for key, value in summary.items():
        print(f"{key}={value}")
    return 0


def _print_mcap_info(bag_dir: Path, ros_setup: Path) -> None:
    mcap_files = sorted(bag_dir.glob("*.mcap"))
    if not mcap_files:
        print(f"No MCAP files found in {bag_dir}")
        return

    for mcap_file in mcap_files:
        print(f"mcap info: {mcap_file}")
        try:
            completed = subprocess.run(  # noqa: S603
                ["mcap", "info", str(mcap_file)],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            print("Unable to run 'mcap info': mcap CLI not found in PATH")
            print(f"ros2 bag info: {bag_dir}")
            ros_cmd = (
                f"source {shlex.quote(str(ros_setup))} && "
                f"ros2 bag info {shlex.quote(str(bag_dir))}"
            )
            fallback = subprocess.run(  # noqa: S603
                ["bash", "-lc", ros_cmd],
                capture_output=True,
                text=True,
                check=False,
            )
            if fallback.returncode == 0:
                output = fallback.stdout.strip()
                if output:
                    print(output)
            else:
                error_text = fallback.stderr.strip() or fallback.stdout.strip() or "unknown error"
                print(f"Unable to run 'ros2 bag info' for {bag_dir}: {error_text}")
            return

        if completed.returncode == 0:
            output = completed.stdout.strip()
            if output:
                print(output)
        else:
            error_text = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            print(f"Unable to read MCAP metadata for {mcap_file}: {error_text}")


def _ui_run(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)

    menu = (
        "\nCoaxial Capture TUI\n"
        "  1) Start capture\n"
        "  2) Stop capture\n"
        "  3) Status\n"
        "  4) Extract from bag\n"
        "  q) Quit\n"
    )

    while True:
        print(menu)
        choice = input("Select action: ").strip().lower()

        try:
            if choice == "1":
                bag_dir = start_capture(profile)
                print(f"Capture started. Bag output: {bag_dir}")
            elif choice == "2":
                bag_dir = stop_capture(profile)
                print(f"Capture stopped. Bag output: {bag_dir}")
                _print_mcap_info(bag_dir, profile.ros.setup)
            elif choice == "3":
                status, rows, bag_dir = capture_status(profile)
                print(f"status={status}")
                if bag_dir is not None:
                    print(f"bag_dir={bag_dir}")
                for name, pid, alive in rows:
                    print(f"- {name}: pid={pid} alive={alive}")
            elif choice == "4":
                from .extract import run_extraction

                bag_input = input("Bag path: ").strip()
                out_input = input("Output dir (optional): ").strip()
                out_dir = Path(out_input).expanduser().resolve() if out_input else None

                def _on_progress(done_pairs: int, total_pairs: int) -> None:
                    pct = 100.0 * float(done_pairs) / float(total_pairs) if total_pairs > 0 else 100.0
                    print(f"pair_created={done_pairs}/{total_pairs} ({pct:.1f}%)")

                out_path, summary = run_extraction(
                    profile,
                    bag_path=Path(bag_input).expanduser().resolve(),
                    output_dir=out_dir,
                    progress_callback=_on_progress,
                )
                print(f"Extraction output: {out_path}")
                for key, value in summary.items():
                    print(f"{key}={value}")
            elif choice == "q":
                return 0
            else:
                print("Unknown selection")
        except Exception as exc:  # noqa: BLE001
            print(f"Error: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coaxial capture command line interface")

    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture", help="Capture lifecycle commands")
    capture_sub = capture_parser.add_subparsers(dest="capture_cmd", required=True)

    capture_start = capture_sub.add_parser("start", help="Start camera nodes and MCAP recording")
    _profile_arg(capture_start)
    capture_start.add_argument("--output-dir", help="Optional explicit bag output directory")
    capture_start.set_defaults(func=_capture_start)

    capture_stop = capture_sub.add_parser("stop", help="Stop active capture session")
    _profile_arg(capture_stop)
    capture_stop.set_defaults(func=_capture_stop)

    capture_stat = capture_sub.add_parser("status", help="Show capture process status")
    _profile_arg(capture_stat)
    capture_stat.set_defaults(func=_capture_status)

    extract_parser = subparsers.add_parser("extract", help="Offline extraction commands")
    extract_sub = extract_parser.add_subparsers(dest="extract_cmd", required=True)

    extract_run = extract_sub.add_parser("run", help="Extract synchronized outputs from bag")
    _profile_arg(extract_run)
    extract_run.add_argument("--bag-path", required=True, help="Path to bag directory")
    extract_run.add_argument("--output-dir", help="Optional explicit output directory")
    extract_run.set_defaults(func=_extract_run)

    ui_parser = subparsers.add_parser("ui", help="Interactive terminal UI")
    ui_sub = ui_parser.add_subparsers(dest="ui_cmd", required=True)
    ui_run = ui_sub.add_parser("run", help="Start interactive terminal UI")
    _profile_arg(ui_run)
    ui_run.set_defaults(func=_ui_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
