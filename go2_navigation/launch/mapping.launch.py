# Mapping launch - SLAM Toolbox để quét bản đồ.
# Base (driver + lidar->scan + teleop) lấy từ bringup.launch.py.
# Usage: MAP_NAME=my_map MAP_SAVE=true ros2 launch go2_navigation mapping.launch.py

import os
import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    """Mapping: bringup + SLAM Toolbox + RViz."""
    pkg_dir = get_package_share_directory('go2_navigation')

    # Kết nối robot từ config/robot.yaml (env override) — dùng để chọn rviz single/multi
    _cfg = {}
    try:
        with open(os.path.join(pkg_dir, 'config', 'robot.yaml')) as f:
            _cfg = yaml.safe_load(f) or {}
    except Exception:
        pass
    robot_ip = os.getenv('ROBOT_IP') or _cfg.get('robot_ip', '') or ''
    conn_type = os.getenv('CONN_TYPE') or _cfg.get('conn_type', 'webrtc') or 'webrtc'
    robot_ip_list = robot_ip.replace(" ", "").split(",") if robot_ip else []
    conn_mode = "single" if len(robot_ip_list) == 1 and conn_type != "cyclonedds" else "multi"

    slam_params = os.path.join(pkg_dir, 'config', 'mapper_params_online_async.yaml')
    rviz_config = 'single_robot_conf.rviz' if conn_mode == 'single' else 'multi_robot_conf.rviz'
    rviz_path = os.path.join(pkg_dir, 'config', rviz_config)

    use_sim_time = LaunchConfiguration('use_sim_time', default='false')
    with_rviz = LaunchConfiguration('rviz', default='true')

    print("🗺️  Go2 Mapping Mode:")
    print(f"   Robot IPs: {robot_ip_list}   Map name: {os.getenv('MAP_NAME', 'my_map')}")

    bringup = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(pkg_dir, 'launch', 'bringup.launch.py')),
    )

    rviz = Node(
        package='rviz2',
        executable='rviz2',
        name='go2_rviz2',
        output='screen',
        condition=IfCondition(with_rviz),
        arguments=['-d', rviz_path],
        parameters=[{'use_sim_time': False}],
    )

    slam = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('slam_toolbox'),
                         'launch', 'online_async_launch.py')),
        launch_arguments={
            'slam_params_file': slam_params,
            'use_sim_time': use_sim_time,
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument('rviz', default_value='true', description='Launch RViz2'),
        bringup, rviz, slam,
    ])
