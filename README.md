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

## Output Artifacts

Capture output directory:

- `*.mcap` and `metadata.yaml` from rosbag2.

Extraction output directory:

- `basler/*.png` or `*.jpg`: Basler frames.
- `event/*.png` or `*.jpg`: Window-rendered event frames.
- `pairs.csv`: Timestamp alignment metadata per pair.
- `raw_events.csv`: Decoded raw event stream export (if enabled).
- `raw_events.h5`: Decoded raw event stream export in HDF5 (if enabled).
- `summary.csv`: High-level extraction counters.

## Profile Notes

- `capture.event_driver_launch`: EVK4 driver launch command.
- `capture.event_renderer_launch`: Renderer launch command.
- `capture.basler_launch`: Basler launch helper command.
- `capture.wait_topics_sec`: Timeout before recording starts.
- `extraction.window_ms`: Event window half-width around each Basler frame timestamp.

## Notes

- This project focuses on deterministic orchestration and offline extraction.
- ROS2 packages for hardware drivers must be available in the container image.
- Event decoding currently supports `evt3` payloads.
