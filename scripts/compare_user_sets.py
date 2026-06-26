#!/usr/bin/env python3
"""
Compare Basler camera parameters between two user sets to find what causes FPS differences.

Run inside the Docker container where pylon/pypylon is available:
    python3 /workspace/scripts/compare_user_sets.py

The script loads each user set, reads all accessible parameters, then prints
a diff showing what is different between them.
"""
from __future__ import annotations

import sys
from typing import Any

try:
    from pypylon import pylon, genicam
except ImportError:
    sys.exit("pypylon not found. Run this script inside the Docker container.")


def read_all_params(camera: pylon.InstantCamera) -> dict[str, Any]:
    """Read every readable, non-unavailable parameter from the camera nodemap."""
    nodemap = camera.GetNodeMap()
    params: dict[str, Any] = {}

    for node in nodemap.GetNodes():
        name = node.GetName()
        if not genicam.IsReadable(node):
            continue
        if node.GetVisibility() == genicam.Invisible:
            continue

        node_type = type(node).__name__

        try:
            if isinstance(node, genicam.IInteger):
                params[name] = node.GetValue()
            elif isinstance(node, genicam.IFloat):
                params[name] = node.GetValue()
            elif isinstance(node, genicam.IBoolean):
                params[name] = node.GetValue()
            elif isinstance(node, genicam.IEnumeration):
                params[name] = node.GetCurrentEntry().GetSymbolic()
            elif isinstance(node, genicam.IString):
                params[name] = node.GetValue()
            # Skip ICommand and ICategory nodes
        except genicam.GenericException:
            pass

    return params


def load_user_set(camera: pylon.InstantCamera, user_set: str) -> dict[str, Any]:
    nodemap = camera.GetNodeMap()
    selector = nodemap.GetNode("UserSetSelector")
    if not genicam.IsWritable(selector):
        sys.exit("UserSetSelector is not writable — is the camera in the right state?")

    selector.FromString(user_set)

    load_cmd = nodemap.GetNode("UserSetLoad")
    if not genicam.IsWritable(load_cmd):
        sys.exit(f"UserSetLoad command is not writable for user set '{user_set}'.")

    load_cmd.Execute()
    print(f"  Loaded user set: {user_set}")
    return read_all_params(camera)


def main() -> None:
    tl_factory = pylon.TlFactory.GetInstance()
    devices = tl_factory.EnumerateDevices()
    if not devices:
        sys.exit("No Basler cameras found.")

    print(f"Found {len(devices)} camera(s). Using first: {devices[0].GetFriendlyName()}")

    camera = pylon.InstantCamera(tl_factory.CreateDevice(devices[0]))
    camera.Open()

    try:
        print("\nReading 'Default' user set parameters...")
        default_params = load_user_set(camera, "Default")

        print("Reading 'UserSet1' (CurrentSetting equivalent — adjust name if needed)...")
        # Basler cameras don't have a literal "CurrentSetting" user set you can load;
        # CurrentSetting in the ROS driver means "don't load any user set, use current state".
        # To compare, we load the user set that was saved as "current" — typically UserSet1.
        # Change "UserSet1" below to whichever slot you've saved your current settings into.
        current_params = load_user_set(camera, "UserSet1")

    finally:
        camera.Close()

    # Diff
    all_keys = sorted(set(default_params) | set(current_params))
    differences: list[tuple[str, Any, Any]] = []

    for key in all_keys:
        d_val = default_params.get(key, "<missing>")
        c_val = current_params.get(key, "<missing>")
        if d_val != c_val:
            differences.append((key, d_val, c_val))

    if not differences:
        print("\nNo differences found between the two user sets.")
        return

    print(f"\n{'='*72}")
    print(f"{'Parameter':<45} {'Default':<20} {'UserSet1 (Current)'}")
    print(f"{'='*72}")

    # Highlight FPS-relevant parameters first
    fps_keywords = {
        "FrameRate", "Throughput", "Limit", "Exposure", "Acquisition",
        "Bandwidth", "PacketSize", "InterPacketDelay", "TransmissionDelay",
        "AutoFunction", "Auto", "Trigger",
    }

    fps_related = [(k, d, c) for k, d, c in differences if any(kw.lower() in k.lower() for kw in fps_keywords)]
    other = [(k, d, c) for k, d, c in differences if (k, d, c) not in fps_related]

    if fps_related:
        print("\n--- FPS-RELEVANT PARAMETERS ---")
        for key, d_val, c_val in fps_related:
            print(f"  {key:<43} {str(d_val):<20} {c_val}")

    if other:
        print("\n--- OTHER DIFFERENCES ---")
        for key, d_val, c_val in other:
            print(f"  {key:<43} {str(d_val):<20} {c_val}")

    print(f"\nTotal differences: {len(differences)}")
    print("\nFocus on: AcquisitionFrameRateEnable, DeviceLinkThroughputLimitMode,")
    print("          DeviceLinkThroughputLimit, AutoFunctionROI*, ExposureAuto")


if __name__ == "__main__":
    main()
