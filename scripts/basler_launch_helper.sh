#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="/workspace/config/basler/my_camera.yaml"
CAMERA_ID="my_camera"
STARTUP_USER_SET="CurrentSetting"
MTU_SIZE="1500"
ENABLE_STATUS_PUBLISHER="false"
ENABLE_CURRENT_PARAMS_PUBLISHER="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-file)
      CONFIG_FILE="$2"
      shift 2
      ;;
    --camera-id)
      CAMERA_ID="$2"
      shift 2
      ;;
    --startup-user-set)
      STARTUP_USER_SET="$2"
      shift 2
      ;;
    --mtu-size)
      MTU_SIZE="$2"
      shift 2
      ;;
    --enable-status-publisher)
      ENABLE_STATUS_PUBLISHER="$2"
      shift 2
      ;;
    --enable-current-params-publisher)
      ENABLE_CURRENT_PARAMS_PUBLISHER="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 2
      ;;
  esac
done

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Basler config file not found: $CONFIG_FILE"
  exit 1
fi

exec ros2 launch pylon_ros2_camera_wrapper pylon_ros2_camera.launch.py \
  config_file:="$CONFIG_FILE" \
  camera_id:="$CAMERA_ID" \
  startup_user_set:="$STARTUP_USER_SET" \
  mtu_size:="$MTU_SIZE" \
  enable_status_publisher:="$ENABLE_STATUS_PUBLISHER" \
  enable_current_params_publisher:="$ENABLE_CURRENT_PARAMS_PUBLISHER"
