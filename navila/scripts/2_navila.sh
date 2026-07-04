#!/usr/bin/env bash
# ══ NÃO NaVILA — SERVER RIÊNG (building block) ══════════════════════════════
# Chỉ nạp model + phục vụ HTTP :8100. KHÔNG bật driver, KHÔNG bật web.
#
# ⚠️ Thường KHÔNG cần dùng trực tiếp — ./scripts/run.sh đã gộp cả driver+não+web.
#    Dùng script này khi muốn chạy/soi riêng phần não (đo latency, debug output).
#
# Nạp 8-bit + eager + mask4D (VRAM ~11.7GB). Đợi "SẴN SÀNG". Test: curl :8100/health
set -e

NAVILA_DIR="${NAVILA_DIR:-$HOME/NaVILA}"
CKPT_DIR="${CKPT_DIR:-$HOME/navila-ckpt}"
ENV_NAME="${ENV_NAME:-navila}"
SERVER_PY="$HOME/ros2_vlm/src/navila/navila_server.py"

echo "▶ NaVILA server :8100  (model=$CKPT_DIR)  — 8-bit. Ctrl-C để dừng."
cd "$NAVILA_DIR"
exec env \
  CUDA_HOME="$HOME/miniconda3/envs/$ENV_NAME" \
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  conda run -n "$ENV_NAME" --no-capture-output \
    python "$SERVER_PY" --model-path "$CKPT_DIR" --port 8100
