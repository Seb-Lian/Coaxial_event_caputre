#!/usr/bin/env bash
set -euo pipefail

SRC_ROOT="${1:-/opt/basler_ws/src/pylon_ros2_camera}"
IMPL_FILE="$SRC_ROOT/pylon_ros2_camera_component/include/internal/pylon_ros2_camera_impl.hpp"
CPP_FILE="$SRC_ROOT/pylon_ros2_camera_component/src/pylon_ros2_camera.cpp"

if [[ ! -f "$IMPL_FILE" || ! -f "$CPP_FILE" ]]; then
  echo "Basler source tree not found at: $SRC_ROOT"
  exit 1
fi

echo "Applying Basler compatibility patches in $SRC_ROOT"

PATCHED_ANY=0

if ! grep -q "PYLON_ROS2_HAS_BLAZE" "$IMPL_FILE"; then
  perl -0777 -i -pe 's@#include "internal/impl/pylon_ros2_camera_blaze\.hpp"@#if __has_include(<pylon/BlazeInstantCamera.h>)\n#include "internal/impl/pylon_ros2_camera_blaze.hpp"\n#define PYLON_ROS2_HAS_BLAZE 1\n#else\n#define PYLON_ROS2_HAS_BLAZE 0\n#endif@g' "$IMPL_FILE"

  perl -0777 -i -pe 's@\n\s*BLAZE\s*=\s*5,\n@\n#if PYLON_ROS2_HAS_BLAZE\n    BLAZE = 5,\n#endif\n@g' "$CPP_FILE"

  perl -0777 -i -pe 's@(\n\s*else if \(device_class == "BaslerGTC/Basler/GenTL_Producer_for_Basler_blaze_101_cameras"\)\n\s*\{\n(?:.|\n)*?\n\s*return BLAZE;\n\s*\})@\n#if PYLON_ROS2_HAS_BLAZE$1\n#else\n        else if (device_class == "BaslerGTC/Basler/GenTL_Producer_for_Basler_blaze_101_cameras")\n        {\n            RCLCPP_WARN_STREAM(LOGGER, "Blaze camera detected, but blaze support was disabled at build time (missing pylon Blaze headers).");\n            return UNKNOWN;\n        }\n#endif@g' "$CPP_FILE"

  perl -0777 -i -pe 's@(\n\s*case BLAZE:\n\s*return std::make_unique<PylonROS2BlazeCamera>\(device\);\n)@\n#if PYLON_ROS2_HAS_BLAZE$1#endif\n@g' "$CPP_FILE"

  echo "Applied no-blaze compile guard patch."
  PATCHED_ANY=1
else
  echo "No-blaze compile guard patch already present."
fi

if ! grep -q "Trying GigE transport fallback" "$CPP_FILE"; then
  if ! grep -q "GigETransportLayer.h" "$CPP_FILE"; then
    perl -0777 -i -pe 's@#include "internal/pylon_ros2_camera_impl\.hpp"\n\n#include <string>@#include "internal/pylon_ros2_camera_impl.hpp"\n\n#include <pylon/gige/BaslerGigECamera.h>\n#include <pylon/gige/GigETransportLayer.h>\n#include <string>@g' "$CPP_FILE"
  fi

  perl -0777 -i -pe 's@if \(0 == tl_factory\.EnumerateDevices\(device_list\)\)\n\s*\{\n\s*Pylon::PylonTerminate\(\);\n\s*RCLCPP_ERROR_ONCE\(LOGGER, "No available camera device"\);\n\s*return nullptr;\n\s*\}\n\s*else@if (0 == tl_factory.EnumerateDevices(device_list))\n        {\n            RCLCPP_WARN_ONCE(LOGGER, "CTlFactory::EnumerateDevices() returned no devices. Trying GigE transport fallback.");\n\n            Pylon::ITransportLayer * const gige_transport = tl_factory.CreateTl(Pylon::CBaslerGigECamera::DeviceClass());\n            Pylon::IGigETransportLayer *gige_tl = dynamic_cast<Pylon::IGigETransportLayer*>(gige_transport);\n            if (gige_tl)\n            {\n                gige_tl->EnumerateAllDevices(device_list);\n            }\n\n            if (device_list.empty())\n            {\n                Pylon::PylonTerminate();\n                RCLCPP_ERROR_ONCE(LOGGER, "No available camera device");\n                return nullptr;\n            }\n        }\n\n@g' "$CPP_FILE"

  echo "Applied GigE enumeration fallback patch."
  PATCHED_ANY=1
else
  echo "GigE enumeration fallback patch already present."
fi

if [[ "$PATCHED_ANY" -eq 0 ]]; then
  echo "All compatibility patches already present."
fi
