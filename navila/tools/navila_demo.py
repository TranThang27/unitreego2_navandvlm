"""DEMO trực quan: chạy NaVILA trên 1 clip -> render GIF có CHÚ THÍCH action lên video gốc.

    cd ~/NaVILA
    CUDA_HOME=$HOME/miniconda3/envs/navila PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
      conda run -n navila --no-capture-output python ~/ros2_vlm/src/navila/navila_demo.py \
        --model-path ~/navila-ckpt --load-4bit \
        --clip ~/NaVILA/assets/sample.gif --out ~/navila_demo.gif
Mở kết quả: file:///home/dsc-labs/navila_demo.gif (kéo vào trình duyệt / image viewer).
"""
import os, argparse, time
import numpy as np, torch
from PIL import Image, ImageSequence, ImageDraw, ImageFont


def load_font(sz):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--load-4bit", action="store_true")
    ap.add_argument("--clip", default=os.path.expanduser("~/NaVILA/assets/sample.gif"))
    # MẶC ĐỊNH ghi vào src/navila/result/ (cạnh script) — KHÔNG để ra ~/home.
    _RESULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "result")
    os.makedirs(_RESULT, exist_ok=True)
    ap.add_argument("--out", default=os.path.join(_RESULT, "navila_demo.gif"))
    ap.add_argument("--instruction", default="Walk forward following the path, and stop at the end.")
    ap.add_argument("--num-frames", type=int, default=8)
    ap.add_argument("--windows", type=int, default=8)
    args = ap.parse_args()

    from llava.model.builder import load_pretrained_model
    from llava.mm_utils import process_images, tokenizer_image_token, get_model_name_from_path
    from llava.conversation import conv_templates
    from llava.constants import DEFAULT_IMAGE_TOKEN, IMAGE_TOKEN_INDEX

    name = get_model_name_from_path(args.model_path)
    kw = {"torch_dtype": torch.float16, "load_8bit": True}
    tok, model, imgproc, _ = load_pretrained_model(args.model_path, name, None, **kw)

    def ask(imgs):
        N = args.num_frames; imgs = imgs[-N:]
        while len(imgs) < N: imgs.insert(0, imgs[0])
        inter = (DEFAULT_IMAGE_TOKEN + "\n") * (N - 1)
        qs = ("Imagine you are a robot programmed for navigation tasks. You have been given a video "
              f"of historical observations {inter}, and current observation {DEFAULT_IMAGE_TOKEN}\n. "
              f'Your assigned task is: "{args.instruction}" Analyze this series of images to decide your next action, which could be '
              "turning left or right by a specific degree, moving forward a certain distance, or stop if the task is completed.")
        conv = conv_templates["llama_3"].copy()
        conv.append_message(conv.roles[0], qs); conv.append_message(conv.roles[1], None)
        it = process_images(imgs, imgproc, model.config).to(model.device, dtype=torch.float16)
        ids = tokenizer_image_token(conv.get_prompt(), tok, IMAGE_TOKEN_INDEX, return_tensors="pt").unsqueeze(0).to(model.device)
        with torch.inference_mode():
            out = model.generate(ids, images=it, do_sample=False, max_new_tokens=32,
                                 use_cache=True, pad_token_id=tok.eos_token_id)
        return tok.batch_decode(out, skip_special_tokens=True)[0].strip()

    g = Image.open(args.clip)
    frames = [f.convert("RGB").copy() for f in ImageSequence.Iterator(g)]
    n = len(frames)
    print(f"clip {args.clip}: {n} frame")

    # Tính action cho từng đoạn (cửa sổ), gán action cho mọi frame trong đoạn.
    bounds = [int((k + 1) / args.windows * (n - 1)) for k in range(args.windows)]
    seg_action = []
    for k, end in enumerate(bounds):
        win = frames[max(0, end - args.num_frames + 1):end + 1]
        raw = ask(win)
        seg_action.append((end, raw))
        print(f"  đoạn {k} @frame {end:3d} -> {raw!r}", flush=True)

    def action_for(i):
        for end, raw in seg_action:
            if i <= end:
                return raw
        return seg_action[-1][1]

    # Render: phóng to 2x cho dễ nhìn + thanh chú thích trên/dưới.
    W, H = frames[0].size
    scale = max(1, 640 // W)
    fw, fh = W * scale, H * scale
    fbig = load_font(max(14, fh // 22)); fsmall = load_font(max(12, fh // 30))
    out_frames = []
    for i, fr in enumerate(frames):
        canvas = Image.new("RGB", (fw, fh + 70), (20, 20, 20))
        canvas.paste(fr.resize((fw, fh)), (0, 0))
        d = ImageDraw.Draw(canvas)
        d.text((8, 4), f'TASK: {args.instruction}', font=fsmall, fill=(180, 220, 255))
        raw = action_for(i)
        d.rectangle([0, fh, fw, fh + 70], fill=(0, 0, 0))
        d.text((8, fh + 8), "NaVILA ->", font=fsmall, fill=(150, 255, 150))
        d.text((8, fh + 30), raw[:70], font=fbig, fill=(120, 255, 120))
        out_frames.append(canvas)

    out_frames[0].save(args.out, save_all=True, append_images=out_frames[1:],
                       duration=120, loop=0)
    print(f"\n✅ Đã ghi GIF chú thích: {args.out}")
    print(f"   Mở: file://{args.out}  (kéo vào Chrome / image viewer)")


if __name__ == "__main__":
    main()
