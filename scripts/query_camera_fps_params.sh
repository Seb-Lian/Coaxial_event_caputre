#!/usr/bin/env bash
# Diagnose and fix Basler camera FPS while pylon_ros2_camera_node is running.
# Run from a second terminal during an active capture session.

set +u
source /opt/ros/jazzy/setup.bash
source /opt/basler_ws/install/setup.bash 2>/dev/null || true
set -u

PREFIX="/my_camera/pylon_ros2_camera_node"

echo "=== Checking camera node is running ==="
if ! ros2 node list 2>/dev/null | grep -q "pylon_ros2_camera_node"; then
    echo "ERROR: pylon_ros2_camera_node is not running."
    echo "Start a capture session first, then run this script in a second terminal."
    exit 1
fi
echo "Camera node found."

echo ""
echo "=== Grab statistics ==="
for svc in get_statistic_total_buffer_count \
           get_statistic_failed_buffer_count \
           get_statistic_missed_frame_count; do
    T=$(ros2 service type "${PREFIX}/${svc}" 2>/dev/null || echo "")
    if [[ -n "$T" ]]; then
        VAL=$(ros2 service call "${PREFIX}/${svc}" "$T" "{}" 2>/dev/null \
              | grep -oP "(?<=value: )\S+" | head -1)
        printf "  %-45s %s\n" "${svc}:" "${VAL:-(no value)}"
    else
        printf "  %-45s %s\n" "${svc}:" "(not found)"
    fi
done

echo ""
echo "=== Saving full camera PFS to /tmp/camera_params.pfs ==="
ros2 service call "${PREFIX}/save_pfs" \
    pylon_ros2_camera_interfaces/srv/SetStringValue \
    "{value: '/tmp/camera_params.pfs'}" 2>/dev/null | grep -E "success|message" | head -2

if [[ -f /tmp/camera_params.pfs ]]; then
    echo "  Saved. FPS-relevant parameters:"
    grep -iE "FrameRate|ReadoutMode|Throughput|DeviceLink|AcquisitionMode" \
        /tmp/camera_params.pfs | head -30
else
    echo "  File not created — trying get_pfs instead..."
    ros2 service call "${PREFIX}/get_pfs" \
        pylon_ros2_camera_interfaces/srv/GetStringValue \
        "{feature_name: ''}" 2>/dev/null \
        | grep -oP "(?<=value: ).*" | tr '\\n' '\n' \
        | grep -iE "FrameRate|ReadoutMode|Throughput|DeviceLink" | head -30
fi

echo ""
echo "=== Attempting to set acquisition frame rate to 30 FPS ==="
echo "  Step 1: set rate value to 30..."
ros2 service call "${PREFIX}/set_acquisition_frame_rate" \
    pylon_ros2_camera_interfaces/srv/SetFloatValue \
    "{value: 30.0}" 2>/dev/null | grep -E "success|message" | head -2

echo "  Step 2: enable acquisition frame rate control..."
ros2 service call "${PREFIX}/enable_acquisition_frame_rate" \
    std_srvs/srv/SetBool \
    "{data: true}" 2>/dev/null | grep -E "success|message" | head -2

echo ""
echo "=== Actual published image rate after fix (5 second sample) ==="
ros2 topic hz "${PREFIX}/image_raw" --window 30 2>/dev/null &
HZ_PID=$!
sleep 5
kill "$HZ_PID" 2>/dev/null || true

echo ""
echo "If rate is now 30 Hz: add the following to capture.py _configure_basler_chunk_timestamp"
echo "or a new _configure_basler_frame_rate function called at capture start."
