#!/usr/bin/env bash
# ══ DRIVER ROBOT (chạy RIÊNG) ═══════════════════════════════════════════════
# Camera + odom (KHÔNG Nav2/SLAM). Chỉ cần chạy: ./scripts/1_robot.sh
#
# ⚠️ Chạy NaVILA thì KHÔNG cần script này — 2_navila.sh đã tự bật driver.
#    Dùng cái này khi chỉ muốn driver (lái tay keyboard_teleop / demo VLM Qwen).
#
# Robot IP/token lấy mặc định từ go2_navigation/config/robot.yaml.
# Muốn đổi 1 lần:  ROBOT_IP=192.168.1.7 ./scripts/1_robot.sh
# Muốn bật lidar:  DECODE_LIDAR=true    ./scripts/1_robot.sh   (mặc định tắt cho nhẹ)
set -e

pkill -9 -f "go2_driver|robot.launch|agent_server|navila_server" 2>/dev/null || true
sleep 2

source /opt/ros/jazzy/setup.bash
source ~/ros2_vlm/install/setup.bash

export DECODE_LIDAR="${DECODE_LIDAR:-false}"

echo "▶ Driver Go2 — camera + odom (teleop_mux ON). Ctrl-C để dừng."
exec ros2 launch go2_navigation bringup.launch.py teleop:=true
