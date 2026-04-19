from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description() -> LaunchDescription:
    camera_name = LaunchConfiguration("camera_name")
    serial = LaunchConfiguration("serial")
    bias_file = LaunchConfiguration("bias_file")
    erc_mode = LaunchConfiguration("erc_mode")
    erc_rate = LaunchConfiguration("erc_rate")

    return LaunchDescription(
        [
            DeclareLaunchArgument("camera_name", default_value="event_camera"),
            DeclareLaunchArgument("serial", default_value="00051466"),
            DeclareLaunchArgument("bias_file", default_value="/workspace/config/event_camera/my_camera.bias"),
            DeclareLaunchArgument("erc_mode", default_value="na"),
            DeclareLaunchArgument("erc_rate", default_value="100000000"),
            ComposableNodeContainer(
                name="metavision_driver_container",
                namespace="",
                package="rclcpp_components",
                executable="component_container_isolated",
                output="screen",
                composable_node_descriptions=[
                    ComposableNode(
                        package="metavision_driver",
                        plugin="metavision_driver::DriverROS2",
                        name=camera_name,
                        parameters=[
                            {
                                "serial": ParameterValue(serial, value_type=str),
                                "bias_file": ParameterValue(bias_file, value_type=str),
                                "use_multithreading": True,
                                "event_message_time_threshold": 1.0e-3,
                                "erc_mode": ParameterValue(erc_mode, value_type=str),
                                "erc_rate": ParameterValue(erc_rate, value_type=int),
                            }
                        ],
                        extra_arguments=[{"use_intra_process_comms": True}],
                    )
                ],
            ),
        ]
    )
