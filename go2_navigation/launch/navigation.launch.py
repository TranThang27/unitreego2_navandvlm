# Navigation launch - AMCL localization + Nav2 trên map đã lưu.
# Base (driver + lidar->scan + teleop) lấy từ bringup.launch.py.
# Usage: ros2 launch go2_navigation navigation.launch.py map:=/path/to/map.yaml

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
    """Navigation: bringup + AMCL + Nav2 + RViz."""
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

    # `or` thay default arg: xử lý cả khi MAP_FILE được set thành rỗng
    map_file = os.getenv('MAP_FILE') or os.path.join(pkg_dir, 'map', 'cty.yaml')
    nav2_params = os.path.join(pkg_dir, 'config', 'nav2_params.yaml')
    rviz_config = 'single_robot_conf.rviz' if conn_mode == 'single' else 'multi_robot_conf.rviz'
    rviz_path = os.path.join(pkg_dir, 'config', rviz_config)

    use_sim_time = LaunchConfiguration('use_sim_time', default='false')
    with_rviz = LaunchConfiguration('rviz', default='true')

    print("🧭 Go2 Navigation Mode:")
    print(f"   Robot IPs: {robot_ip_list}   Map: {map_file}")

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

    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('nav2_bringup'),
                         'launch', 'localization_launch.py')),
        launch_arguments={
            'map': map_file,
            'params_file': nav2_params,
            'use_sim_time': use_sim_time,
        }.items(),
    )
    navigation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('nav2_bringup'),
                         'launch', 'navigation_launch.py')),
        launch_arguments={
            'params_file': nav2_params,
            'use_sim_time': use_sim_time,
        }.items(),
    )

    return LaunchDescription([
        DeclareLaunchArgument('map', default_value=map_file,
                              description='Full path to map yaml file'),
        DeclareLaunchArgument('rviz', default_value='true', description='Launch RViz2'),
        bringup, rviz, localization, navigation,
    ])
