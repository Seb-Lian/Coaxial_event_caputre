#!/usr/bin/env bash
set -euo pipefail

if [[ -f "/opt/ros/jazzy/setup.bash" ]]; then
  # shellcheck disable=SC1091
  set +u
  source /opt/ros/jazzy/setup.bash
  set -u
fi

if [[ -f "/workspace/install/setup.bash" ]]; then
  # shellcheck disable=SC1091
  set +u
  source /workspace/install/setup.bash
  set -u
fi

if [[ -f "/opt/basler_ws/install/setup.bash" ]]; then
  # shellcheck disable=SC1091
  set +u
  source /opt/basler_ws/install/setup.bash
  set -u
fi

if [[ -d "/workspace/src" ]]; then
  export PYTHONPATH="/workspace/src:${PYTHONPATH:-}"
fi

exec "$@"
