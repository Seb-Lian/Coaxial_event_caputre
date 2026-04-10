# Basler Throughput Tuning Timeline

This document records the throughput tuning work done to move Basler capture from roughly 34 to 35 FPS up to approximately 47.6 FPS at full resolution.

## Target

- Camera: Basler acA1300-60gmNIR
- Operating mode: full resolution, mono8, binning 1x1
- Target FPS: 48

## Baseline Symptom

- Capture repeatedly landed around 34 to 35 FPS even when recording was stable.
- Example run:
  - Bag: bags/sync_2026_04_10-10_07_49
  - Measured image rate: 35.40 to 35.46 Hz
- Recorder health looked normal, so the bottleneck was upstream of rosbag write.

## Timeline Of Changes

### 1) Confirmed where the bottleneck was

What changed:
- Compared MCAP topic rates and rosbag recorder logs.

Why it helps:
- Distinguishes camera publication limits from recording/storage limits.
- Prevents spending time optimizing the wrong layer.

Evidence:
- image_raw was ~35 Hz while rosbag recorder showed clean topic subscription and stop/flush behavior.

---

### 2) Raised Basler frame-rate cap in camera config

What changed:
- Updated frame_rate from 40.0 to 48.0.
- File: config/basler/my_camera.yaml

Why it helps:
- Removed an explicit software cap at 40 FPS.
- Necessary precondition to reach 48 FPS.

---

### 3) Explicitly tuned GigE transport timing

What changed:
- Added:
  - inter_pkg_delay: 0
  - frame_transmission_delay: 0
- File: config/basler/my_camera.yaml

Why it helps:
- Reduces camera-side transport pacing and avoids unnecessary spacing between Ethernet packets for a single-camera setup.
- Helps maximize effective wire utilization when link quality is good.

Tradeoff:
- If packet loss appears on weaker links, inter_pkg_delay may need to be increased from 0.

---

### 4) Disabled unnecessary renderer load during capture

What changed:
- Set launch_renderer to false in default profile.
- File: config/profiles/default.yaml

Why it helps:
- Removes extra runtime CPU/GPU overhead that was not needed for recording.
- Frees compute headroom for camera and transport pipeline.

---

### 5) Forced Basler startup from clean user set

What changed:
- Switched startup_user_set from CurrentSetting to Default in basler launch command.
- File: config/profiles/default.yaml

Why it helps:
- Avoids hidden persisted camera-side limits from previously saved user settings.
- Ensures reproducible startup behavior.

---

### 6) Reduced wrapper-side optional publisher overhead

What changed:
- Added launch helper support for:
  - --enable-status-publisher
  - --enable-current-params-publisher
- Passed both as false in default basler launch command.
- Files:
  - scripts/basler_launch_helper.sh
  - config/profiles/default.yaml

Why it helps:
- Reduces non-essential publishing work in the wrapper node.
- Keeps more resources available for the main image stream.

---

### 7) Verified host-side network prerequisites

What changed:
- Kept jumbo-frame launch parameter (mtu-size 8192) and documented host MTU alignment requirements.
- File: README.md

Why it helps:
- Prevents frame transport inefficiency and packet fragmentation issues.
- Ensures camera and NIC operate with matching packet size assumptions.

## Final Result

- Example latest run:
  - Bag: bags/sync_2026_04_10-10_14_22
  - Measured image rate: 47.64 to 47.67 Hz
- This is effectively on target for 48 FPS.

## Final Throughput-Relevant Settings Snapshot

### config/basler/my_camera.yaml

- binning_x: 1
- binning_y: 1
- frame_rate: 48.0
- exposure: 4000.0
- gain: 0.0
- inter_pkg_delay: 0
- frame_transmission_delay: 0
- image_encoding: mono8

### config/profiles/default.yaml (capture section)

- launch_renderer: false
- basler_launch includes:
  - --startup-user-set Default
  - --mtu-size 8192
  - --enable-status-publisher false
  - --enable-current-params-publisher false

## Validation Commands Used

- mcap info <bag_file.mcap>
- Review logs:
  - logs/<sync_run>/basler_driver.log
  - logs/<sync_run>/bag_record.log

## Notes For Future Tuning

- If FPS drops again while target remains 48, first verify:
  - Basler startup log reports 48 Hz target
  - MCAP image topic rate
  - Host NIC MTU and link state
- If packet issues appear, increase inter_pkg_delay gradually from 0 until stable.
