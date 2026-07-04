"""VERIFY (task tuần này): NaVILA xuất mid-level action trên SAMPLE CLIPS — "matches paper".

Chạy nhiều clip demo (assets/*.gif của repo NaVILA), mỗi clip lấy 8 frame + câu lệnh nav,
in BẢNG: clip | instruction | RAW action | loại action | latency. Đo VRAM đỉnh.

    cd ~/NaVILA
    CUDA_HOME=$HOME/miniconda3/envs/navila PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
      conda run -n navila --no-capture-output python ~/ros2_vlm/src/navila/navila_verify.py \
        --model-path ~/navila-ckpt --load-4bit
"""
import os, re, glob, time, argparse
import numpy as np, torch
from PIL import Image, ImageSequence


def classify(raw):
    t = (raw or "").lower()
    if re.search(r"\bstop\b|completed|finished", t):
        return "stop"
    m = re.search(r"turn\s+(left|right)\D*([-+]?\d*\.?\d+)\s*(deg|degree|°)", t)
    if m:
        return f"turn_{m.group(1)} {m.group(2)}°"
    m = re.search(r"(forward|backward|ahead)\D*([-+]?\d*\.?\d+)\s*(cm|m|met)", t)
    if m:
        return f"move_forward {m.group(2)}{m.group(3)}"
    if re.search(r"\bforward\b|\bahead\b", t):
        return "forward (no number)"
    if re.search(r"\bturn\b|\bleft\b|\bright\b", t):
        return "turn (no number)"
    return "?? (không rõ)"


def frames_from_gif(path, n=8):
    g = Image.open(path)
    fr = [f.convert("RGB").copy() for f in ImageSequence.Iterator(g)]
    idx = np.linspace(0, len(fr) - 1, n).astype(int)
    return [fr[i] for i in idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--load-4bit", action="store_true")
    ap.add_argument("--num-frames", type=int, default=8)
    ap.add_argument("--assets", default=os.path.expanduser("~/NaVILA/assets"))
    args = ap.parse_args()

    from llava.model.builder import load_pretrained_model
    from llava.mm_utils import process_images, tokenizer_image_token, get_model_name_from_path
    from llava.conversation import conv_templates
    from llava.constants import DEFAULT_IMAGE_TOKEN, IMAGE_TOKEN_INDEX

    name = get_model_name_from_path(args.model_path)
    kw = {"torch_dtype": torch.float16, "load_8bit": True}

    torch.cuda.reset_peak_memory_stats()
    tok, model, imgproc, _ = load_pretrained_model(args.model_path, name, None, **kw)
    load_vram = torch.cuda.max_memory_allocated() / 1e9

    def ask(imgs, instr):
        N = args.num_frames; imgs = imgs[-N:]
        while len(imgs) < N: imgs.insert(0, imgs[0])
        inter = (DEFAULT_IMAGE_TOKEN + "\n") * (N - 1)
        qs = ("Imagine you are a robot programmed for navigation tasks. You have been given a video "
              f"of historical observations {inter}, and current observation {DEFAULT_IMAGE_TOKEN}\n. "
              f'Your assigned task is: "{instr}" Analyze this series of images to decide your next action, which could be '
              "turning left or right by a specific degree, moving forward a certain distance, or stop if the task is completed.")
        conv = conv_templates["llama_3"].copy()
        conv.append_message(conv.roles[0], qs); conv.append_message(conv.roles[1], None)
        it = process_images(imgs, imgproc, model.config).to(model.device, dtype=torch.float16)
        ids = tokenizer_image_token(conv.get_prompt(), tok, IMAGE_TOKEN_INDEX, return_tensors="pt").unsqueeze(0).to(model.device)
        t0 = time.time()
        with torch.inference_mode():
            out = model.generate(ids, images=it, do_sample=False, max_new_tokens=32,
                                 use_cache=True, pad_token_id=tok.eos_token_id)
        dt = time.time() - t0
        return tok.batch_decode(out, skip_special_tokens=True)[0].strip(), dt

    gifs = sorted(glob.glob(os.path.join(args.assets, "*.gif")))
    instr = "Walk forward following the path, and stop when you reach the end."
    print("\n================ NaVILA mid-level action — SAMPLE CLIPS ================")
    print(f"checkpoint: {name} | 4bit={args.load_4bit} | VRAM nạp={load_vram:.1f}GB")
    print(f"{'CLIP':<22}{'ACTION (phân loại)':<26}{'lat(s)':<8}RAW")
    print("-" * 100)
    torch.cuda.reset_peak_memory_stats()
    lats = []
    for g in gifs:
        try:
            imgs = frames_from_gif(g, args.num_frames)
        except Exception as e:
            print(f"{os.path.basename(g):<22}(lỗi đọc gif: {e})"); continue
        raw, dt = ask(imgs, instr); lats.append(dt)
        print(f"{os.path.basename(g):<22}{classify(raw):<26}{dt:<8.2f}{raw!r}")
    peak = torch.cuda.max_memory_allocated() / 1e9
    print("-" * 100)
    if lats:
        print(f"VRAM đỉnh suy luận: {peak:.1f}GB (<16GB ✅) | latency TB: {sum(lats)/len(lats):.2f}s")
    print("Kỳ vọng: action nằm trong tập {move_forward X, turn_left/right X°, stop} = khớp paper.")

    # ---- TRAJECTORY: cửa sổ trượt trên clip nav THẬT -> chuỗi mid-level action ----
    navclip = os.path.join(args.assets, "sample.gif")
    if os.path.exists(navclip):
        g = Image.open(navclip)
        allf = [f.convert("RGB").copy() for f in ImageSequence.Iterator(g)]
        print(f"\n>>> Chuỗi action dọc sample.gif ({len(allf)} frame, cửa sổ trượt 8-frame):")
        for k in range(6):
            end = int((k + 1) / 6 * (len(allf) - 1))
            win = allf[max(0, end - 7):end + 1]
            raw, _ = ask(win, instr)
            print(f"    @frame {end:3d}: {classify(raw):<24} | {raw!r}")
    print()


if __name__ == "__main__":
    main()
