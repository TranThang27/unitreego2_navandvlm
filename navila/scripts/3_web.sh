#!/usr/bin/env bash
# ══ WEB GUI — RIÊNG (building block) ════════════════════════════════════════
# Bật web :8001 (não = NaVILA :8100). ⚠️ Thường KHÔNG cần — ./scripts/run.sh đã gộp.
# Dùng riêng khi driver + não đã chạy sẵn và chỉ muốn restart mỗi web.
#
# Mở trên admin1:  http://localhost:8001   (hoặc http://192.168.1.29:8001)
# Ví dụ lệnh:      Walk forward down the hallway and stop near the chair.
#
# Chỉnh nhanh (đặt trước lệnh):
#   MOTION_LIN_SPEED=0.6 ./scripts/3_web.sh   # đi nhanh hơn (mặc định 0.4, an toàn)
#   VLA_MAX_TURN_DEG=45  ./scripts/3_web.sh   # cho xoay gắt hơn
set -e

pkill -f agent_server 2>/dev/null || true
sleep 1

cd ~/ros2_vlm/src

echo "▶ Web GUI :8001 — não = NaVILA (:8100). Đợi 'Uvicorn running'. Ctrl-C để dừng."
VLA_BRAIN=navila \
VLA_CONTROL=vlm \
USE_YOLO=0 \
VLA_NAVILA_URL="${VLA_NAVILA_URL:-http://127.0.0.1:8100}" \
VLA_NAVILA_FRAMES="${VLA_NAVILA_FRAMES:-8}" \
VLA_MAX_TURN_DEG="${VLA_MAX_TURN_DEG:-30}" \
NAVILA_FALLBACK="${NAVILA_FALLBACK:-stop}" \
MOTION_LIN_SPEED="${MOTION_LIN_SPEED:-0.4}" \
MOTION_ANG_SPEED="${MOTION_ANG_SPEED:-0.7}" \
MOTION_ANG_MAX_DEG="${MOTION_ANG_MAX_DEG:-45}" \
  exec ./vlm/scripts/run_demo1.sh
