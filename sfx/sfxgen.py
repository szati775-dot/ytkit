#!/usr/bin/env python3
"""sfxgen - generate sound effects for OUR OWN Blender renders from text prompts.

Uses Stability AI's stable-audio-tools (code: MIT, https://github.com/Stability-AI/stable-audio-tools)
with the Stable Audio Open Small weights (Stability AI Community License: commercial use is
free while the channel earns under USD 1M a year; you own the generated audio).
MMAudio was considered and rejected: its weights are CC-BY-NC (non-commercial).

Never feed War Thunder footage or game audio into this (Gaijin ToS 4.3.5). Prompts only.

One-time setup (PC with an NVIDIA GPU is fastest; CPU works, slower):
  1. Hugging Face account -> open https://huggingface.co/stabilityai/stable-audio-open-small
     and accept the licence; create a read token at https://huggingface.co/settings/tokens
  2. pip install stable-audio-tools soundfile    (pulls PyTorch)
  3. set HF_TOKEN=hf_...   (or `huggingface-cli login`)

Use:
  python sfxgen.py "tank engine revving, diesel, close" --seconds 4 -o engine.wav --takes 3
  python sfxgen.py --cues cues.json -o sfx/       cues.json: [{"name": "boom", "prompt": "...", "seconds": 3}]
Each take is peak-normalised to -1 dBFS; pick the best by ear (Claude can't hear them).
"""
import argparse
import json
import os
import sys

MODEL = os.environ.get("SFXGEN_MODEL", "stabilityai/stable-audio-open-small")


def load():
    try:
        import torch
        from stable_audio_tools import get_pretrained_model
    except ImportError:
        sys.exit("sfxgen: run  pip install stable-audio-tools soundfile")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, cfg = get_pretrained_model(MODEL)
    return model.to(device), cfg, device


def generate(model, cfg, device, prompt, seconds, seed, steps):
    import numpy as np
    import torch
    from stable_audio_tools.inference.generation import generate_diffusion_cond
    seconds = max(0.5, min(seconds, 11.0))               # the small model makes up to ~11 s
    cond = [{"prompt": prompt, "seconds_total": seconds}]
    small = "small" in MODEL
    out = generate_diffusion_cond(model, steps=steps or (8 if small else 100), cfg_scale=1.0 if small else 7.0,
                                  conditioning=cond, sample_size=cfg["sample_size"], seed=seed, device=device,
                                  **({"sampler_type": "pingpong"} if small else {}))
    audio = out[0].to(torch.float32).cpu().numpy()        # (channels, samples)
    sr = cfg["sample_rate"]
    audio = audio[:, :int(seconds * sr)]
    peak = float(np.abs(audio).max()) or 1.0
    return (audio / peak * 0.891).T, sr                   # -1 dBFS


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("prompt", nargs="?")
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--takes", type=int, default=2)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--steps", type=int)
    p.add_argument("--cues", help="JSON list of {name, prompt, seconds}")
    p.add_argument("-o", "--out", default="sfx.wav", help="file (single prompt) or folder (--cues)")
    a = p.parse_args()
    if not a.prompt and not a.cues:
        p.error("give a prompt or --cues")
    import soundfile as sf
    model, cfg, device = load()
    jobs = json.load(open(a.cues, encoding="utf-8")) if a.cues else [
        {"name": os.path.splitext(os.path.basename(a.out))[0], "prompt": a.prompt, "seconds": a.seconds}]
    folder = a.out if a.cues else (os.path.dirname(a.out) or ".")
    os.makedirs(folder, exist_ok=True)
    for j in jobs:
        for t in range(a.takes):
            audio, sr = generate(model, cfg, device, j["prompt"], float(j.get("seconds", a.seconds)), a.seed + t, a.steps)
            path = os.path.join(folder, "%s_take%d.wav" % (j["name"], t + 1))
            sf.write(path, audio, sr)
            print("wrote %s  (%s)" % (path, j["prompt"]))
    with open(os.path.join(folder, "SFX-LICENCE.txt"), "w", encoding="utf-8") as f:
        f.write("Generated with %s (Stability AI Community License) via stable-audio-tools (MIT).\n" % MODEL)


if __name__ == "__main__":
    main()
