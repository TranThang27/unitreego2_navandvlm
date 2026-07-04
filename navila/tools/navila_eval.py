"""EVAL + VISUALIZE: NaVILA vs GROUND-TRUTH trên NaVILA-Dataset (R2R) — "matches paper".

Mỗi mẫu = (instruction q, frames history, GT action a). Lấy 8 frame, cho model suy luận,
so action model vs GT -> action-accuracy (forward/turn/stop). Xuất ảnh montage vào result/.

    cd ~/NaVILA
    CUDA_HOME=$HOME/miniconda3/envs/navila PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
      conda run -n navila --no-capture-output python ~/ros2_vlm/src/navila/navila_eval.py \
        --model-path ~/navila-ckpt --load-4bit \
        --annotations ~/navila-dataset/R2R/annotations.json \
        --frames-root ~/navila-dataset/R2R/train  --n-per-type 6
"""
import os, re, json, glob, argparse, random
import numpy as np, torch
from PIL import Image, ImageDraw, ImageFont


def act_type(text):
    t = (text or "").lower()
    if re.search(r"\bstop\b|completed|finished", t):
        return "stop"
    m = re.search(r"turn\s+(left|right)", t)
    if m:
        return f"turn_{m.group(1)}"
    if re.search(r"\bforward\b|\bahead\b", t):
        return "forward"
    return "other"


def act_value(text):
    m = re.search(r"([-+]?\d*\.?\d+)\s*(cm|m|deg|degree|°)", (text or "").lower())
    return (float(m.group(1)), m.group(2)) if m else (None, None)


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
    ap.add_argument("--annotations", required=True)
    ap.add_argument("--frames-root", required=True, help="thư mục chứa các folder scan (vd .../914/frame_0.jpg)")
    ap.add_argument("--num-frames", type=int, default=8)
    ap.add_argument("--n-per-type", type=int, default=6, help="số mẫu mỗi loại action để test")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    _RESULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "result", "eval_samples")
    os.makedirs(_RESULT, exist_ok=True)

    from llava.model.builder import load_pretrained_model
    from llava.mm_utils import process_images, tokenizer_image_token, get_model_name_from_path
    from llava.conversation import conv_templates
    from llava.constants import DEFAULT_IMAGE_TOKEN, IMAGE_TOKEN_INDEX

    print("Đọc annotations…", flush=True)
    data = json.load(open(args.annotations))
    # gom mẫu theo loại action GT, chọn n-per-type mỗi loại (ưu tiên có frame trên đĩa)
    random.seed(args.seed); random.shuffle(data)
    buckets = {"forward": [], "turn_left": [], "turn_right": [], "stop": []}
    for s in data:
        ty = act_type(s.get("a", ""))
        if ty in buckets and len(buckets[ty]) < args.n_per_type * 4:
            fp = os.path.join(args.frames_root, s["frames"][0])
            if os.path.exists(fp):
                buckets[ty].append(s)
        if all(len(v) >= args.n_per_type * 4 for v in buckets.values()):
            break
    picked = []
    for ty, lst in buckets.items():
        picked += lst[:args.n_per_type]
    print("Chọn:", {k: min(len(v), args.n_per_type) for k, v in buckets.items()}, "=", len(picked), "mẫu", flush=True)

    name = get_model_name_from_path(args.model_path)
    kw = {"torch_dtype": torch.float16, "load_8bit": True}
    tok, model, imgproc, _ = load_pretrained_model(args.model_path, name, None, **kw)

    def load8(frames):
        idx = np.linspace(0, len(frames) - 1, args.num_frames).astype(int)
        imgs = []
        for i in idx:
            imgs.append(Image.open(os.path.join(args.frames_root, frames[i])).convert("RGB"))
        return imgs

    def ask(imgs, instr):
        N = args.num_frames
        inter = (DEFAULT_IMAGE_TOKEN + "\n") * (N - 1)
        qs = ("Imagine you are a robot programmed for navigation tasks. You have been given a video "
              f"of historical observations {inter}, and current observation {DEFAULT_IMAGE_TOKEN}\n. "
              f'Your assigned task is: "{instr}" Analyze this series of images to decide your next action, which could be '
              "turning left or right by a specific degree, moving forward a certain distance, or stop if the task is completed.")
        conv = conv_templates["llama_3"].copy()
        conv.append_message(conv.roles[0], qs); conv.append_message(conv.roles[1], None)
        it = process_images(imgs, imgproc, model.config).to(model.device, dtype=torch.float16)
        ids = tokenizer_image_token(conv.get_prompt(), tok, IMAGE_TOKEN_INDEX, return_tensors="pt").unsqueeze(0).to(model.device)
        with torch.inference_mode():
            out = model.generate(ids, images=it, do_sample=False, max_new_tokens=32,
                                 use_cache=True, pad_token_id=tok.eos_token_id)
        return tok.batch_decode(out, skip_special_tokens=True)[0].strip()

    font = load_font(20); fsm = load_font(15)
    n_ok = n_val = 0
    per = {}
    print(f"\n{'GT action':<34}{'MODEL action':<34}{'type✓'}")
    print("-" * 80)
    for k, s in enumerate(picked):
        imgs = load8(s["frames"])
        raw = ask(imgs, s["q"])
        gt, md = s["a"], raw
        gty, mty = act_type(gt), act_type(md)
        ok = (gty == mty)
        n_ok += ok
        d = per.setdefault(gty, [0, 0]); d[0] += ok; d[1] += 1
        # value match (nếu cùng type + có số)
        gv, gu = act_value(gt); mv, mu = act_value(md)
        if gv is not None and mv is not None:
            n_val += (ok and abs(gv - mv) <= (10 if gu and gu.startswith(("cm", "m")) else 5))
        print(f"{gt[:33]:<34}{md[:33]:<34}{'✓' if ok else '✗'}")
        # visualize montage 8 frame + caption
        th = [im.resize((160, 160)) for im in imgs]
        W = 160 * len(th)
        canvas = Image.new("RGB", (W, 160 + 78), (18, 18, 18))
        for i, t in enumerate(th):
            canvas.paste(t, (i * 160, 0))
        dr = ImageDraw.Draw(canvas)
        dr.text((6, 162), f"INSTRUCTION: {s['q'][:90]}", font=fsm, fill=(180, 210, 255))
        dr.text((6, 184), f"GT   : {gt}", font=font, fill=(120, 255, 120))
        dr.text((6, 208), f"MODEL: {md[:60]}", font=font, fill=(120, 255, 120) if ok else (255, 140, 120))
        canvas.save(os.path.join(_RESULT, f"{gty}_{k:02d}_{'ok' if ok else 'MISS'}.png"))

    print("-" * 80)
    print(f"ACTION-TYPE ACCURACY: {n_ok}/{len(picked)} = {100*n_ok/max(1,len(picked)):.0f}%")
    for ty, (o, n) in per.items():
        print(f"   {ty:<12}: {o}/{n}")
    print(f"(value khớp trong sai số: {n_val}/{len(picked)})")
    print(f"Ảnh minh hoạ -> {_RESULT}/  (mở xem GT vs MODEL từng mẫu)")


if __name__ == "__main__":
    main()
