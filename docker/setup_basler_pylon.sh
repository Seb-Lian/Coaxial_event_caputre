#!/usr/bin/env bash
set -euo pipefail

INSTALLER_DIR="${1:-/installers/basler}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script must run as root inside the container."
  echo "Try: docker exec -it -u 0 ros2_jazzy_coaxial_capture bash"
  exit 1
fi

if [[ ! -d "$INSTALLER_DIR" ]]; then
  echo "Installer directory not found: $INSTALLER_DIR"
  exit 1
fi

mapfile -t DEBS < <(find "$INSTALLER_DIR" -maxdepth 1 -type f -name '*.deb' | sort)
if [[ "${#DEBS[@]}" -eq 0 ]]; then
  echo "No .deb files found in $INSTALLER_DIR"
  echo "Download Basler pylon Linux Debian installer(s) and place them there."
  exit 1
fi

echo "Installing Basler pylon SDK from: $INSTALLER_DIR"
apt-get update
if ! apt-get install -y --no-install-recommends "${DEBS[@]}"; then
  echo "Initial install failed, retrying after dependency fix."
  apt-get -f install -y
  apt-get install -y --no-install-recommends "${DEBS[@]}"
fi
rm -rf /var/lib/apt/lists/*

if [[ ! -f /opt/pylon/include/pylon/PylonIncludes.h ]]; then
  echo "Basler pylon headers not found under /opt/pylon after install."
  echo "Check that your .deb is the correct pylon package and retry."
  exit 1
fi

echo "Building Basler ROS2 wrapper in /opt/basler_ws"
source /opt/ros/jazzy/setup.bash

if [[ ! -f /opt/pylon/include/pylon/BlazeInstantCamera.h ]]; then
  echo "Blaze headers not found; applying no-blaze compatibility patch."
  /usr/local/bin/patch_basler_no_blaze.sh /opt/basler_ws/src/pylon_ros2_camera
fi

cd /opt/basler_ws
rosdep install --from-paths src --ignore-src -r -y || true
colcon build --symlink-install

echo
echo "Basler ROS2 driver is built. Use:"
echo "  source /opt/ros/jazzy/setup.bash"
echo "  source /opt/basler_ws/install/setup.bash"
echo "  ros2 launch pylon_ros2_camera_wrapper pylon_ros2_camera.launch.py"
