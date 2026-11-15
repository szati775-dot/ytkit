"""Offline test for editkit (needs requirements-editkit.txt + ffmpeg). Synthetic media only.
Run:  python tests/test_editkit.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
try:
    import numpy as np
    import editkit
    import librosa  # noqa: F401
    import scenedetect  # noqa: F401
except ImportError as e:
    print("SKIP editkit tests: %s (pip install -r requirements-editkit.txt)" % e)
    sys.exit(0)
if not shutil.which("ffmpeg"):
    print("SKIP editkit tests: ffmpeg not on PATH")
    sys.exit(0)

T = tempfile.mkdtemp()
PASS, FAIL = [], []


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  -> %s" % (info,)))


def wav(path, y, sr=44100):
    y = (y / np.abs(y).max() * 0.8 * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(y.tobytes())


sr, d, bpm = 44100, 16, 120
y = np.zeros(sr * d)
for i, bt in enumerate(np.arange(0.5, d, 60 / bpm)):
    n, L = int(bt * sr), int(0.08 * sr)
    seg = y[n:n + L]
    seg += (1.0 if i % 4 == 0 else 0.5) * np.exp(-np.arange(len(seg)) / (0.015 * sr)) * np.sin(
        2 * np.pi * 150 * np.arange(len(seg)) / sr)
music = os.path.join(T, "music.wav")
wav(music, y + 0.01 * np.random.randn(len(y)))
g = 0.02 * np.random.randn(sr * d)
for bt in (2.0, 6.0, 10.0, 13.5):
    n = int(bt * sr)
    g[n:n + sr // 2] += np.random.randn(sr // 2) * np.exp(-np.arange(sr // 2) / (0.08 * sr))
game_wav = os.path.join(T, "game.wav")
wav(game_wav, g)
game = os.path.join(T, "game.mp4")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=320x180:r=30:d=4",
                "-f", "lavfi", "-i", "color=blue:s=320x180:r=30:d=4", "-f", "lavfi", "-i", "color=yellow:s=320x180:r=30:d=4",
                "-f", "lavfi", "-i", "color=green:s=320x180:r=30:d=4", "-i", game_wav, "-filter_complex",
                "[0][1][2][3]concat=n=4:v=1[v]", "-map", "[v]", "-map", "4:a", "-c:v", "libx264", "-c:a", "aac",
                "-shortest", game], check=True)

r = editkit.analyse_beats(music)
check("beats: tempo ~120", 115 <= r["tempo_bpm"] <= 125, r["tempo_bpm"])
gaps = np.diff(r["beats"])
check("beats: steady grid", abs(float(np.median(gaps)) - 0.5) < 0.03, gaps[:5])
check("beats: downbeats every 4", len(r["downbeats"]) in range(len(r["beats"]) // 4, len(r["beats"]) // 4 + 2))

s = editkit.analyse_scenes(game)
check("scenes: 4 shots found", len(s["shots"]) == 4, [(x["start"], x["end"]) for x in s["shots"]])
peaks = sorted(m[0] for x in s["shots"] for m in x["moments"][:1])
check("scenes: loud moments found near the bangs", all(any(abs(p - b) < 0.3 for p in peaks) for b in (2.0, 6.0, 10.0, 13.5)), peaks)

t0, ev = editkit.build_plan(r, [s], beats_per_cut=2, length=6)
check("plan: cuts fill the beat slots", len(ev) >= 5 and all(abs((b - a) - 1.0) < 0.06 for _, a, b in ev), ev)
check("plan: no footage reused", all(not (a1 < b2 and a2 < b1) for i, (_, a1, b1) in enumerate(ev)
                                     for _, a2, b2 in ev[i + 1:]), ev)
edl = os.path.join(T, "plan.edl")
editkit.write_cut_edl(edl, "t", ev, 30)
txt = open(edl).read()
check("plan: EDL written", txt.startswith("TITLE: t") and txt.count("FROM CLIP NAME: game.mp4") == len(ev))
mk = os.path.join(T, "m.edl")
editkit.write_marker_edl(mk, "m", [(1.0, "HIT", "Red")], 60)
check("marker EDL for Resolve", "|C:ResolveColorRed |M:HIT |D:1" in open(mk).read() and "01:00:01:00" in open(mk).read())
check("timecode maths", editkit.tc(61.5, 30, 0) == "00:01:01:15")
lu = editkit.measure_loudness(music)
check("loudness measured", -40 < lu["lufs"] < 0 and lu["true_peak_db"] <= 0.5, lu)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
