#!/usr/bin/env bash
# ══ NaVILA · CHẠY TẤT CẢ TRONG 1 LỆNH ═══════════════════════════════════════
# driver robot + não NaVILA :8100 + web GUI :8001 — 1 terminal duy nhất.
#   cd ~/ros2_vlm/src/navila && ./scripts/run.sh
# Rồi mở:  http://localhost:8001  (gõ nhiệm vụ tiếng Anh)
# Ctrl-C = tắt SẠCH cả 3 (không còn tiến trình mồ côi).
#
# Log 2 phần chạy nền (terminal này chỉ hiện log web cho gọn):
#   tail -f ~/ros2_vlm/log/navila_driver.log     # driver robot
#   tail -f ~/ros2_vlm/log/navila_brain.log      # não NaVILA
#
# Override (đặt trước lệnh), vd:
#   MOTION_LIN_SPEED=0.6 ./scripts/run.sh   # đi nhanh hơn (mặc định 0.4)
#   DECODE_LIDAR=true    ./scripts/run.sh   # bật lidar (có /scan auto-né vật cản)
#   ROBOT_IP=192.168.1.7 ./scripts/run.sh   # đổi IP robot 1 lần
set -e

WS="$HOME/ros2_vlm"
LOG_DIR="$WS/log"; mkdir -p "$LOG_DIR"
DRIVER_LOG="$LOG_DIR/navila_driver.log"
BRAIN_LOG="$LOG_DIR/navila_brain.log"

NAVILA_DIR="${NAVILA_DIR:-$HOME/NaVILA}"
CKPT_DIR="${CKPT_DIR:-$HOME/navila-ckpt}"
ENV_NAME="${ENV_NAME:-navila}"
SERVER_PY="$WS/src/navila/navila_server.py"

pkill -9 -f "go2_driver|robot.launch|agent_server|navila_server" 2>/dev/null || true
sleep 2

PIDS=()
cleanup() {
  echo; echo "⏹ Dừng tất cả (driver + não + web)…"
  kill "${PIDS[@]}" 2>/dev/null || true
  pkill -9 -f "go2_driver|navila_server|agent_server" 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

# ── [1/3] Driver robot (background, env ROS) ─────────────────────────────────
echo "▶ [1/3] Driver robot (camera+odom) → $DRIVER_LOG"
(
  source /opt/ros/jazzy/setup.bash
  source "$WS/install/setup.bash"
  export DECODE_LIDAR="${DECODE_LIDAR:-false}"
  export ROBOT_IP="${ROBOT_IP:-}"
  exec ros2 launch go2_navigation bringup.launch.py teleop:=true
) >"$DRIVER_LOG" 2>&1 &
PIDS+=($!)

# ── [2/3] Não NaVILA (background, env conda navila, 8-bit) ────────────────────
echo "▶ [2/3] Não NaVILA :8100 (8-bit) → $BRAIN_LOG"
(
  cd "$NAVILA_DIR"
  exec env \
    CUDA_HOME="$HOME/miniconda3/envs/$ENV_NAME" \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    conda run -n "$ENV_NAME" --no-capture-output \
      python "$SERVER_PY" --model-path "$CKPT_DIR" --port 8100
) >"$BRAIN_LOG" 2>&1 &
PIDS+=($!)
BRAIN_PID=$!

# Đợi model nạp xong (health OK) mới bật web — tránh web hỏi khi não chưa sẵn sàng.
echo -n "⏳ Đợi NaVILA nạp model (~30-60s)"
READY=0
for _ in $(seq 1 150); do          # tối đa ~5 phút
  if curl -sf http://127.0.0.1:8100/health >/dev/null 2>&1; then
    READY=1; echo " — SẴN SÀNG ✅"; break
  fi
  if ! kill -0 "$BRAIN_PID" 2>/dev/null; then
    echo; echo "❌ Não NaVILA chết khi nạp. Xem: cat $BRAIN_LOG" >&2; cleanup
  fi
  echo -n "."; sleep 2
done
[ "$READY" = 1 ] || echo " — (quá lâu, vẫn bật web; kiểm $BRAIN_LOG nếu web báo lỗi não)"

# ── [3/3] Web GUI (foreground, env ROS) ──────────────────────────────────────
echo "▶ [3/3] Web GUI :8001 — mở http://localhost:8001 . Ctrl-C = tắt TẤT CẢ."
cd "$WS/src"
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
  ./vlm/scripts/run_demo1.sh

# Web thoát bình thường → hạ nốt driver + não.
cleanup
