# Bringup launch - driver trần cho Go2 (camera + odom + /scan + twist_mux),
# KHÔNG SLAM/Nav2/RViz. Dùng trực tiếp cho demo1 (vòng lặp VLM), và được
# navigation.launch.py / mapping.launch.py include lại làm base.
#
# Env:
#   ROBOT_IP, ROBOT_TOKEN (rỗng cho Go2 LAN trực tiếp), CONN_TYPE (webrtc)
#   DECODE_LIDAR=false  -> tắt giải mã lidar (chế độ NaVILA nhẹ, mất /scan)
#   MAP_NAME, MAP_SAVE  -> chỉ dùng cho lidar_to_pointcloud ở multi mode
#
# Args:
#   teleop:=true|false     joystick + teleop_twist_joy + twist_mux

import os
import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument


def load_robot_conn(pkg_dir):
    """Đọc config/robot.yaml (robot_ip/conn_type/robot_token). Env override nếu được đặt.

    Trả về (robot_ip, robot_ip_list, conn_type, robot_token).
    """
    cfg = {}
    try:
        with open(os.path.join(pkg_dir, 'config', 'robot.yaml')) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        pass
    robot_ip = os.getenv('ROBOT_IP') or cfg.get('robot_ip', '') or ''
    conn_type = os.getenv('CONN_TYPE') or cfg.get('conn_type', 'webrtc') or 'webrtc'
    robot_token = os.environ.get('ROBOT_TOKEN', cfg.get('robot_token', '') or '')
    robot_ip_list = robot_ip.replace(" ", "").split(",") if robot_ip else []
    return robot_ip, robot_ip_list, conn_type, robot_token


def generate_launch_description():
    """Base bringup: driver + lidar->scan + teleop."""

    # --- Paths ---
    pkg_dir = get_package_share_directory('go2_navigation')      # config
    sdk_dir = get_package_share_directory('go2_robot_sdk')    # urdf

    # --- Kết nối robot: config/robot.yaml (env override) ---
    robot_ip, robot_ip_list, conn_type, robot_token = load_robot_conn(pkg_dir)
    decode_lidar = os.getenv('DECODE_LIDAR', 'true').lower() not in ('0', 'false', 'no')
    map_name = os.getenv('MAP_NAME', 'my_map')
    map_save = os.getenv('MAP_SAVE', 'false')

    conn_mode = "single" if len(robot_ip_list) == 1 and conn_type != "cyclonedds" else "multi"
    urdf_file = 'go2.urdf' if conn_mode == 'single' else 'multi_go2.urdf'

    config_paths = {
        'joystick': os.path.join(pkg_dir, 'config', 'joystick.yaml'),
        'twist_mux': os.path.join(pkg_dir, 'config', 'twist_mux.yaml'),
        'urdf': os.path.join(sdk_dir, 'urdf', urdf_file),
    }

    print("🐕 Go2 Bringup:")
    print(f"   Robot IPs: {robot_ip_list}")
    print(f"   Connection: {conn_type} ({conn_mode})   decode_lidar={decode_lidar}")

    with open(config_paths['urdf'], 'r') as file:
        robot_desc = file.read()

    # --- Launch args ---
    use_sim_time = LaunchConfiguration('use_sim_time', default='false')
    with_teleop = LaunchConfiguration('teleop', default='true')

    launch_args = [
        DeclareLaunchArgument('teleop', default_value='true',
                              description='Launch joystick/teleop/twist_mux'),
    ]

    # --- Core nodes ---
    core_nodes = [
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='go2_robot_state_publisher',
            output='screen',
            parameters=[{
                'use_sim_time': use_sim_time,
                'robot_description': robot_desc,
            }],
        ),
        Node(
            package='go2_robot_sdk',
            executable='go2_driver_node',
            name='go2_driver_node',
            output='screen',
            parameters=[{
                'robot_ip': robot_ip,
                'token': robot_token,
                'conn_type': conn_type,
                'enable_video': True,
                'decode_lidar': decode_lidar,
                'lidar_publish_rate': 15.0,   # chặn firehose LiDAR (robot bắn ~1000Hz)
                'lidar_voxel_size': 0.06,     # voxel 6cm ở driver -> nhẹ CPU/băng thông
            }],
        ),
    ]

    # LiDAR -> /scan. Chỉ chạy khi decode_lidar (nếu tắt, driver không publish
    # /point_cloud2 nên các node này vô nghĩa). Single mode: driver đã publish
    # /point_cloud2 trực tiếp; MULTI mode cần lidar_to_pointcloud gộp trước.
    if decode_lidar:
        core_nodes.append(Node(
            package='go2_navigation',
            executable='pointcloud_aggregator_node',
            name='pointcloud_aggregator',
            remappings=[('cloud_in', '/point_cloud2')],
            parameters=[{
                'max_range': 10.0,
                'min_range': 0.30,
                'height_filter_min': 0.2,   # lát 0.2-0.4m -> khớp map đã quét (AMCL)
                'height_filter_max': 0.4,
                'downsample_rate': 1,
                'publish_rate': 20.0,
                'voxel_leaf_size': 0.0,     # driver đã voxel 0.06m
                # SOR (StatisticalOutlierRemoval) là bộ lọc NẶNG NHẤT (KD-tree),
                # thời gian xử lý biến thiên -> /scan tụt 7.7->5.3Hz + giật.
                # TẮT để scan bám sát nhịp lidar (~7.7Hz) & đều hơn. ROR (rẻ) gánh
                # việc lọc điểm ma cho costmap Nav2. min_neighbors=4: đủ dẹp nhiễu lẻ
                # loi (sạch hơn bản gốc 3) NHƯNG không gọt mất chân NGƯỜI đứng (2 ống
                # chân mảnh, điểm thưa) như mức 5. Cân bằng: bớt phantom mà vẫn thấy người.
                'sor_enable': False,
                'sor_mean_k': 16,
                'sor_std_dev': 0.9,
                'ror_enable': True,
                'ror_radius': 0.25,
                'ror_min_neighbors': 4,
            }],
        ))
        core_nodes.append(Node(
            package='pointcloud_to_laserscan',
            executable='pointcloud_to_laserscan_node',
            name='go2_pointcloud_to_laserscan',
            remappings=[('cloud_in', '/pointcloud/filtered'), ('scan', '/scan')],
            parameters=[{
                'target_frame': 'base_link',
                'max_height': 2.0,
                'min_height': -1.0,
                'angle_min': -3.14159,
                'angle_max': 3.14159,
                'angle_increment': 0.00872665,
                'scan_time': 0.1,
                'range_min': 0.35,   # loại chân/thân robot
                'range_max': 10.0,
                'use_inf': True,
                'concurrency_level': 2,
            }],
            output='screen',
        ))
        if conn_mode != 'single':
            core_nodes.append(Node(
                package='go2_navigation',
                executable='lidar_to_pointcloud_node',
                name='lidar_to_pointcloud',
                parameters=[{
                    'robot_ip_lst': robot_ip_list,
                    'map_name': map_name,
                    'map_save': map_save,
                }],
            ))

    # --- Teleop ---
    teleop_nodes = [
        Node(
            package='joy',
            executable='joy_node',
            condition=IfCondition(with_teleop),
            parameters=[config_paths['joystick']],
        ),
        Node(
            package='teleop_twist_joy',
            executable='teleop_node',
            name='go2_teleop_node',
            condition=IfCondition(with_teleop),
            parameters=[config_paths['twist_mux']],
        ),
        Node(
            package='twist_mux',
            executable='twist_mux',
            output='screen',
            condition=IfCondition(with_teleop),
            parameters=[{'use_sim_time': use_sim_time}, config_paths['twist_mux']],
        ),
    ]

    return LaunchDescription(launch_args + core_nodes + teleop_nodes)
