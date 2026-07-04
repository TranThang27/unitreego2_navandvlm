"""NaVILA inference server — chạy trong conda env 'navila' (VILA + torch2.7 Blackwell).

ROS webconsole (env khác) KHÔNG import chung được VILA -> nói chuyện qua HTTP.
Nạp model 1 lần, phục vụ POST /decide {instruction, frames:[jpg-base64]} -> {raw, action}.

Chạy (trong repo NaVILA để import llava):
    cd ~/NaVILA
    CUDA_HOME=$HOME/miniconda3/envs/navila PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
      conda run -n navila --no-capture-output python <path>/navila_server.py \
        --model-path ~/navila-ckpt --load-4bit --port 8100
"""
import io
import os
import time
import base64
import argparse

import torch
import numpy as np
from PIL import Image
from fastapi import FastAPI, Response
from pydantic import BaseModel
import uvicorn

# Lưu lần /decide gần nhất để DEBUG trên GUI/trình duyệt (ảnh đúng cái NaVILA nhận + raw).
_LAST = {"jpg": None, "raw": "", "instruction": "", "latency_s": 0.0, "n_frames": 0}

# Calib camera Go2 (từ /camera/camera_info, plumb_bob) — dùng khi NAVILA_UNDISTORT=1.
_GO2_K = np.array([[864.39938, 0, 639.19798], [0, 863.73849, 373.28118], [0, 0, 1]])
_GO2_D = np.array([-0.35463, 0.102054, -0.001614, -0.001249, 0.0])


class DecideReq(BaseModel):
    instruction: str
    frames: list = []          # list base64 JPEG (RGB), theo thứ tự cũ -> mới
    max_new_tokens: int = 32


def build():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--model-base", default=None)
    ap.add_argument("--conv-mode", default="llama_3")
    ap.add_argument("--num-frames", type=int, default=8)
    ap.add_argument("--load-4bit", action="store_true")
    ap.add_argument("--port", type=int, default=8100)
    args = ap.parse_args()

    from llava.model.builder import load_pretrained_model
    from llava.mm_utils import process_images, tokenizer_image_token, get_model_name_from_path
    from llava.conversation import conv_templates, SeparatorStyle
    from llava.constants import DEFAULT_IMAGE_TOKEN, IMAGE_TOKEN_INDEX
    from llava.mm_utils import KeywordsStoppingCriteria

    name = get_model_name_from_path(args.model_path)
    print(f"[navila-server] nạp {name} (8-bit + eager + mask4D)…", flush=True)
    kw = {"torch_dtype": torch.float16, "load_8bit": True}
    tokenizer, model, image_processor, _ = load_pretrained_model(
        args.model_path, name, args.model_base, **kw)
    print(f"[navila-server] SẴN SÀNG. VRAM {torch.cuda.max_memory_allocated()/1e9:.1f} GB", flush=True)

    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True, "num_frames": args.num_frames}

    @app.get("/last")            # JSON: raw + meta lần suy luận gần nhất (debug)
    def last():
        return {k: v for k, v in _LAST.items() if k != "jpg"}

    @app.get("/last.jpg")        # ẢNH: 8 frame ĐÚNG cái NaVILA nhận (sau crop) — mở trên trình duyệt
    def last_jpg():
        return Response(content=_LAST["jpg"] or b"", media_type="image/jpeg")

    def _preprocess(img):
        """Xử lý ảnh Go2 TRƯỚC khi vào encoder. Chọn bằng NAVILA_PREPROC:
          fov   (KHUYẾN NGHỊ NaVILA) = khử méo + CROP cửa sổ forward (bỏ rìa fisheye + bớt
                 sàn, thiên lên trên) -> kéo về gần góc train R2R (nhìn thẳng, ~vuông, thẳng thớm).
                 Auto bật undistort. Tinh chỉnh: NAVILA_FOV_KEEP_W/KEEP_H/VCENTER (xem dưới).
          pad   = letterbox giữ FULL fisheye FOV, đệm vuông (rộng nhất -> OOD nhất cho NaVILA)
          resize= trả nguyên -> process_images bóp méo về 384 (như config gốc)
          crop  = crop tâm vuông thô (mất ~44% FOV ngang)
        NAVILA_UNDISTORT=1 khử méo fisheye Go2 (K,D calib). Mode 'fov' tự bật (tắt bằng =0).
        Tham số mode 'fov':
          NAVILA_FOV_KEEP_W (1.0)  = giữ bao nhiêu bề NGANG (1.0 = full, tránh mất mục tiêu)
          NAVILA_FOV_KEEP_H (0.72) = giữ bao nhiêu bề DỌC (nhỏ hơn = cắt bớt sàn/trần)
          NAVILA_FOV_VCENTER(0.40) = tâm dọc của cửa sổ (0=trên,1=dưới; <0.5 = nhìn hất lên bù cam thấp)"""
        mode = os.getenv("NAVILA_PREPROC", "pad")
        if os.getenv("NAVILA_UNDISTORT", "1" if mode == "fov" else "0") == "1":
            try:
                import cv2
                a = np.array(img)[:, :, ::-1]                      # RGB->BGR
                a = cv2.undistort(a, _GO2_K, _GO2_D)
                img = Image.fromarray(a[:, :, ::-1])
            except Exception:
                pass
        if mode == "fov":
            w, h = img.size
            cw = max(1, min(w, int(round(w * float(os.getenv("NAVILA_FOV_KEEP_W", "1.0"))))))
            ch = max(1, min(h, int(round(h * float(os.getenv("NAVILA_FOV_KEEP_H", "0.72"))))))
            x0 = (w - cw) // 2                                     # ngang: giữ giữa
            y0 = int(round(h * float(os.getenv("NAVILA_FOV_VCENTER", "0.40")) - ch / 2))
            y0 = max(0, min(h - ch, y0))                           # dọc: thiên lên, bớt sàn
            return img.crop((x0, y0, x0 + cw, y0 + ch))
        if mode == "crop":
            w, h = img.size; s = min(w, h)
            return img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
        if mode == "resize":
            return img
        # pad (letterbox): giữ tỉ lệ, đệm về vuông cạnh max -> resize sau KHÔNG méo, đủ FOV
        w, h = img.size; s = max(w, h)
        canvas = Image.new("RGB", (s, s), (0, 0, 0))
        canvas.paste(img, ((s - w) // 2, (s - h) // 2))
        return canvas

    def _decode(frames_b64):
        imgs = []
        for b in frames_b64:
            imgs.append(_preprocess(Image.open(io.BytesIO(base64.b64decode(b))).convert("RGB")))
        if not imgs:                                   # chưa có frame -> ảnh xám
            imgs = [Image.new("RGB", (384, 384), (127, 127, 127))]
        imgs = imgs[-args.num_frames:]                 # giữ tối đa num_frames mới nhất
        while len(imgs) < args.num_frames:             # thiếu -> lặp frame đầu (đủ khung)
            imgs.insert(0, imgs[0])
        return imgs

    @app.post("/decide")
    def decide(req: DecideReq):
        t0 = time.time()
        imgs = _decode(req.frames)
        interleaved = (DEFAULT_IMAGE_TOKEN + "\n") * (args.num_frames - 1)
        qs = (
            "Imagine you are a robot programmed for navigation tasks. You have been given a video "
            f'of historical observations {interleaved}, and current observation {DEFAULT_IMAGE_TOKEN}\n. '
            f'Your assigned task is: "{req.instruction}" '
            "Analyze this series of images to decide your next action, which could be turning left or right by a specific "
            "degree, moving forward a certain distance, or stop if the task is completed."
        )
        conv = conv_templates[args.conv_mode].copy()
        conv.append_message(conv.roles[0], qs)
        conv.append_message(conv.roles[1], None)
        prompt = conv.get_prompt()
        images_tensor = process_images(imgs, image_processor, model.config).to(
            model.device, dtype=torch.float16)
        input_ids = tokenizer_image_token(
            prompt, tokenizer, IMAGE_TOKEN_INDEX, return_tensors="pt").unsqueeze(0).to(model.device)
        stop_str = conv.sep if conv.sep_style != SeparatorStyle.TWO else conv.sep2
        stopper = KeywordsStoppingCriteria([stop_str], tokenizer, input_ids)
        gen_kwargs = dict(do_sample=False, max_new_tokens=req.max_new_tokens, use_cache=True,
                          pad_token_id=tokenizer.eos_token_id, stopping_criteria=[stopper])
        scores = None
        with torch.inference_mode():
            try:                    # xin logits mỗi bước để đo độ tự tin (model có thể không hỗ trợ)
                gen = model.generate(input_ids, images=images_tensor,
                                     return_dict_in_generate=True, output_scores=True, **gen_kwargs)
                out, scores = gen.sequences, gen.scores
            except TypeError:
                out = model.generate(input_ids, images=images_tensor, **gen_kwargs)
        raw = tokenizer.batch_decode(out, skip_special_tokens=True)[0].strip()

        # ── ĐỘ TỰ TIN + PHÂN VÂN: NaVILA không có chain-of-thought, nên "lý do" trung thực
        # nhất = model chắc chắn tới đâu và đang giằng co giữa những token nào (từ logits). ──
        conf, weak_tok, alts = None, None, []
        if scores:
            try:
                import math
                import torch.nn.functional as F
                gen_ids = out[0][-len(scores):]                 # token MỚI sinh (khớp scores)
                ps = [float(F.softmax(lg[0].float(), -1)[int(tok)])
                      for lg, tok in zip(scores, gen_ids)]
                if ps:
                    conf = round(math.exp(sum(math.log(max(p, 1e-9)) for p in ps) / len(ps)), 3)
                    wi = min(range(len(ps)), key=lambda i: ps[i])   # token model lưỡng lự nhất
                    weak_tok = tokenizer.decode([int(gen_ids[wi])]).strip()
                    tk = torch.topk(F.softmax(scores[wi][0].float(), -1), 3)
                    alts = [[tokenizer.decode([int(i)]).strip(), round(float(v), 2)]
                            for v, i in zip(tk.values, tk.indices)]
            except Exception:
                pass

        dt = round(time.time() - t0, 3)
        conf_s = f" conf={conf}" if conf is not None else ""
        print(f"[decide] instr={req.instruction!r} n={len(imgs)} {dt}s{conf_s} -> {raw!r}", flush=True)
        # DEBUG: ghép 8 frame (đúng cái model nhận, sau crop) thành 1 ảnh xem ở /last.jpg
        try:
            th = [im.resize((192, 192)) for im in imgs]
            mont = Image.new("RGB", (192 * len(th), 192))
            for i, t in enumerate(th):
                mont.paste(t, (i * 192, 0))
            buf = io.BytesIO(); mont.save(buf, "JPEG", quality=80)
            _LAST.update(jpg=buf.getvalue(), raw=raw, instruction=req.instruction,
                         latency_s=dt, n_frames=len(imgs), conf=conf,
                         weak_tok=weak_tok, alts=alts)
        except Exception:
            pass
        return {"raw": raw, "latency_s": dt, "n_frames": len(imgs),
                "conf": conf, "weak_tok": weak_tok, "alts": alts}

    print(f"[navila-server] http://0.0.0.0:{args.port}  (POST /decide)", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    build()
