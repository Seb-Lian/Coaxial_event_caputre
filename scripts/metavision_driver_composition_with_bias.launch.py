from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    serial = LaunchConfiguration("serial")
    bias_file = LaunchConfiguration("bias_file")

    return LaunchDescription(
        [
            DeclareLaunchArgument("serial", default_value="00000000"),
            DeclareLaunchArgument("bias_file", default_value="/workspace/config/event_camera/my_camera.bias"),
            Node(
                package="metavision_driver",
                executable="metavision_ros_driver_node",
                name="event_camera_driver",
                output="screen",
                parameters=[{"serial": serial, "bias_file": bias_file}],
            ),
        ]
    )
