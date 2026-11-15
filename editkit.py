#!/usr/bin/env python3
"""editkit - editing helpers for the Grinder channel.

Classical signal processing only (no AI models), so it is safe to run on
War Thunder footage. Built on these open-source projects (see THIRD_PARTY.md):
  librosa        (ISC)          beat / onset / loudness analysis of music
  PySceneDetect  (BSD-3-Clause) cut detection in raw gameplay
  auto-editor    (Unlicense)    dead-time trimming, Resolve timeline export

Install once:  pip install -r requirements-editkit.txt   (ffmpeg on PATH)

Commands (add -h for options):
  beats MUSIC                 tempo, beat grid, big hits; Resolve marker EDL
  scenes VIDEO                cuts + action score per shot; marker EDL
  plan --music M --video V    snap the best shots to the beat grid -> EDL
                              (and an optional low-res ffmpeg preview)
  trim VIDEO                  cut silence / dead time (auto-editor)
  loudness FILE               integrated LUFS + true peak vs the -14 target
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

VERSION = "0.1.0"
TARGET_LUFS = -14.0


# ----------------------------------------------------------------- helpers
def die(msg):
    print("editkit: " + msg, file=sys.stderr)
    sys.exit(2)


def need(mod, pip_name=None):
    try:
        return __import__(mod)
    except ImportError:
        die("missing '%s'. Run: pip install -r requirements-editkit.txt" % (pip_name or mod))


def ffmpeg_bin():
    exe = shutil.which("ffmpeg")
    if not exe:
        die("ffmpeg not found on PATH")
    return exe


def out_json(obj, path=None):
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("wrote " + path)
    else:
        print(text)


def tc(seconds, fps, hour=1):
    """seconds -> HH:MM:SS:FF timecode (Resolve timelines start at 01:00:00:00)."""
    fps_i = int(round(fps))
    total = int(round(seconds * fps)) + hour * 3600 * fps_i
    ff = total % fps_i
    s = total // fps_i
    return "%02d:%02d:%02d:%02d" % (s // 3600, (s // 60) % 60, s % 60, ff)


def write_marker_edl(path, title, markers, fps):
    """markers: list of (seconds, name, color). Import in Resolve with
    Timeline > Import > Timeline Markers from EDL."""
    lines = ["TITLE: " + title, "FCM: NON-DROP FRAME", ""]
    for i, (t, name, color) in enumerate(markers, 1):
        a, b = tc(t, fps), tc(t + 1.0 / fps, fps)
        lines.append("%03d  001      V     C        %s %s %s %s  " % (i, a, b, a, b))
        lines.append(" |C:ResolveColor%s |M:%s |D:1" % (color, name))
        lines.append("")
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines))
    print("wrote %s (%d markers)" % (path, len(markers)))


def write_cut_edl(path, title, events, fps):
    """events: list of (reel_file, src_in, src_out). CMX3600 cut list that
    Resolve imports as a timeline (File > Import > Timeline)."""
    lines = ["TITLE: " + title, "FCM: NON-DROP FRAME", ""]
    rec = 0.0
    for i, (src, a, b) in enumerate(events, 1):
        dur = b - a
        lines.append("%03d  AX       AA/V  C        %s %s %s %s" % (
            i, tc(a, fps, 0), tc(b, fps, 0), tc(rec, fps), tc(rec + dur, fps)))
        lines.append("* FROM CLIP NAME: " + os.path.basename(src))
        lines.append("")
        rec += dur
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines))
    print("wrote %s (%d cuts, %.1f s)" % (path, len(events), rec))


def extract_audio(video, sr=22050):
    """Mono float audio from any media file, via ffmpeg (librosa can't read mp4)."""
    np = need("numpy")
    cmd = [ffmpeg_bin(), "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", str(sr),
           "-f", "f32le", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").copy(), sr


def video_fps(video):
    cv2 = need("cv2", "opencv-python-headless")
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    cap.release()
    return fps, (n / fps if fps else 0.0)


# ------------------------------------------------------------------ beats
def analyse_beats(path, hits=12):
    librosa = need("librosa")
    np = need("numpy")
    y, sr = extract_audio(path)
    if not len(y):
        die("no audio in " + path)
    hop = 512
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    tempo, frames = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=hop)
    tempo = float(np.atleast_1d(tempo)[0])
    beats = librosa.frames_to_time(frames, sr=sr, hop_length=hop)
    # downbeat phase: the beat offset (0-3) whose beats carry the most onset energy
    phase = 0
    if len(frames) >= 8:
        energy = [float(onset[frames[p::4]].mean()) for p in range(4)]
        phase = int(np.argmax(energy))
    downbeats = beats[phase::4]
    # big hits: strongest onset peaks, at least 1 s apart (drops, impacts)
    peaks = librosa.util.peak_pick(onset, pre_max=10, post_max=10, pre_avg=40,
                                   post_avg=40, delta=float(onset.std()), wait=int(sr / hop))
    peaks = sorted(peaks, key=lambda f: -onset[f])[:hits]
    hit_t = sorted(float(librosa.frames_to_time(f, sr=sr, hop_length=hop)) for f in peaks)
    # loudness curve in 1 s steps, to find the quiet part before a drop
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=sr)[0]
    db = librosa.amplitude_to_db(rms + 1e-9, ref=np.max)
    return {
        "file": os.path.basename(path),
        "duration_s": round(len(y) / sr, 2),
        "tempo_bpm": round(tempo, 1),
        "beat_s": round(60.0 / tempo, 4) if tempo else None,
        "beats": [round(float(t), 3) for t in beats],
        "downbeats": [round(float(t), 3) for t in downbeats],
        "hits": [round(t, 3) for t in hit_t],
        "loudness_db_per_s": [round(float(v), 1) for v in db],
    }


def cmd_beats(a):
    r = analyse_beats(a.music, a.hits)
    print("%s: %.1f BPM, %d beats, %d downbeats, %.1f s" % (
        r["file"], r["tempo_bpm"], len(r["beats"]), len(r["downbeats"]), r["duration_s"]))
    print("big hits at: " + ", ".join("%.2f" % t for t in r["hits"]))
    base = a.out or os.path.splitext(a.music)[0] + "_beats"
    out_json(r, base + ".json")
    marks = [(t, "Bar %d" % (i + 1), "Blue") for i, t in enumerate(r["downbeats"])]
    marks += [(t, "HIT", "Red") for t in r["hits"]]
    write_marker_edl(base + "_markers.edl", r["file"] + " beats", sorted(marks), a.fps)


# ----------------------------------------------------------------- scenes
def analyse_scenes(video, threshold=27.0, min_len=0.4):
    scenedetect = need("scenedetect")
    np = need("numpy")
    from scenedetect import ContentDetector, detect
    fps, dur = video_fps(video)
    found = detect(video, ContentDetector(threshold=threshold, min_scene_len=max(1, int(min_len * fps))))
    sec = lambda t: t.seconds if hasattr(type(t), "seconds") else t.get_seconds()
    shots = [(sec(s), sec(e)) for s, e in found] or [(0.0, dur)]
    # audio action score: loudness and onset density per shot (explosions, hits, gunfire)
    y, sr = extract_audio(video)
    librosa = need("librosa")
    hop = 512
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop) if len(y) else np.zeros(1)
    rms = librosa.feature.rms(y=y, hop_length=hop)[0] if len(y) else np.zeros(1)
    ref = float(np.percentile(rms, 95)) or 1.0
    oref = float(np.percentile(onset, 95)) or 1.0
    # every strong audio moment (bang, hit, kill sound), at least 0.75 s apart
    pk = librosa.util.peak_pick(onset, pre_max=8, post_max=8, pre_avg=30, post_avg=30,
                                delta=float(onset.std()), wait=int(0.75 * sr / hop)) if len(y) else []
    moments = [(float(f) * hop / sr, float(onset[f] / oref)) for f in pk]
    rows = []
    for i, (s, e) in enumerate(shots, 1):
        a, b = int(s * sr / hop), max(int(s * sr / hop) + 1, int(e * sr / hop))
        seg_r, seg_o = rms[a:b], onset[a:b]
        if len(seg_r):
            loud = float(seg_r.mean() / ref)
            punch = float(seg_o.max() / oref)
            peak_t = s + float(np.argmax(seg_o)) * hop / sr
        else:
            loud = punch = 0.0
            peak_t = s
        score = round(100 * (0.4 * min(loud, 1.5) + 0.6 * min(punch, 2.0)) / 1.8, 1)
        mom = sorted(((t, v) for t, v in moments if s <= t < e), key=lambda m: -m[1])[:12]
        rows.append({"shot": i, "start": round(s, 3), "end": round(e, 3),
                     "len": round(e - s, 2), "peak": round(peak_t, 3), "action": score,
                     "moments": [[round(t, 3), round(min(v, 3.0), 2)] for t, v in mom]})
    return {"file": os.path.basename(video), "path": os.path.abspath(video), "fps": fps,
            "duration_s": round(dur, 2), "shots": rows}


def cmd_scenes(a):
    r = analyse_scenes(a.video, a.threshold, a.min_len)
    top = sorted(r["shots"], key=lambda x: -x["action"])[:a.top]
    print("%s: %d shots in %.1f s. Top %d by action:" % (r["file"], len(r["shots"]), r["duration_s"], len(top)))
    for s in top:
        print("  shot %3d  %7.2f-%7.2f  (%5.2fs)  peak %7.2f  action %5.1f" % (
            s["shot"], s["start"], s["end"], s["len"], s["peak"], s["action"]))
    base = a.out or os.path.splitext(a.video)[0] + "_scenes"
    out_json(r, base + ".json")
    topset = {s["shot"] for s in top}
    marks = [(s["start"], "Shot %d (%.0f)" % (s["shot"], s["action"]),
              "Red" if s["shot"] in topset else "Cyan") for s in r["shots"]]
    write_marker_edl(base + "_markers.edl", r["file"] + " shots", marks, r["fps"])


# ------------------------------------------------------------------- plan
def build_plan(music, scenes_list, beats_per_cut=2, length=None, start=None):
    """Fill the music's beat grid with the highest-action shots, each clip
    centred on its loudest moment. Returns list of (src, in, out)."""
    beats = music["beats"]
    if len(beats) < beats_per_cut + 1:
        die("not enough beats in the music")
    t0 = start if start is not None else (music["downbeats"][0] if music["downbeats"] else beats[0])
    grid = [b for b in beats if b >= t0 - 1e-6]
    if length:
        grid = [b for b in grid if b <= t0 + length + 1e-6]
    slots = [(grid[i], grid[i + beats_per_cut]) for i in range(0, len(grid) - beats_per_cut, beats_per_cut)]
    # candidates: every loud moment of every shot (a long shot can give several clips)
    pool = []
    for sc in scenes_list:
        for s in sc["shots"]:
            moms = s.get("moments") or [[s["peak"], 1.0]]
            for t, v in moms:
                pool.append((s["action"] * (0.5 + 0.5 * min(v, 2.0)), sc["path"], s, t))
    pool.sort(key=lambda x: -x[0])
    events, taken = [], []
    for a, b in slots:
        need_len = b - a
        pick = None
        for k, (_, src, s, t) in enumerate(pool):
            cin = t - need_len * 0.35          # the bang lands just after the cut
            cin = max(s["start"], min(cin, s["end"] - need_len), 0.0)
            cout = cin + need_len
            if any(src == q and cin < qo and cout > qi for q, qi, qo in taken):
                continue                        # never show the same footage twice
            pick = k
            break
        if pick is None:
            break
        _, src, s, t = pool.pop(pick)
        taken.append((src, cin, cout))
        events.append((src, round(cin, 3), round(cout, 3)))
    return t0, events


def render_preview(events, music_path, music_start, out, height=640):
    ff = ffmpeg_bin()
    with tempfile.TemporaryDirectory() as td:
        parts = []
        for i, (src, a, b) in enumerate(events):
            p = os.path.join(td, "c%04d.mp4" % i)
            subprocess.run([ff, "-v", "error", "-y", "-ss", "%.3f" % a, "-i", src, "-t", "%.3f" % (b - a),
                            "-vf", "scale=-2:%d,fps=30,format=yuv420p" % height, "-an",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", p], check=True)
            parts.append(p)
        lst = os.path.join(td, "list.txt")
        with open(lst, "w") as f:
            f.write("".join("file '%s'\n" % p for p in parts))
        total = sum(b - a for _, a, b in events)
        subprocess.run([ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-ss", "%.3f" % music_start, "-t", "%.3f" % total, "-i", music_path,
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                        "-shortest", out], check=True)
    print("wrote preview " + out)


def cmd_plan(a):
    music = analyse_beats(a.music)
    scenes = [analyse_scenes(v, a.threshold) for v in a.video]
    t0, events = build_plan(music, scenes, a.beats_per_cut, a.length, a.start)
    if not events:
        die("no shots to place")
    base = a.out or os.path.splitext(a.music)[0] + "_plan"
    out_json({"music": music["file"], "music_start": t0, "tempo_bpm": music["tempo_bpm"],
              "beats_per_cut": a.beats_per_cut,
              "cuts": [{"src": s, "in": i, "out": o} for s, i, o in events]}, base + ".json")
    fps = scenes[0]["fps"] or 60
    write_cut_edl(base + ".edl", "beat plan", events, fps)
    if a.preview:
        render_preview(events, a.music, t0, base + "_preview.mp4")


# ------------------------------------------------------------------- trim
def auto_editor_bin():
    exe = shutil.which("auto-editor")
    if not exe:
        die("auto-editor not found. Run: pip install -r requirements-editkit.txt")
    return exe


def cmd_trim(a):
    edit = ("motion:threshold=%s" % a.motion) if a.motion else ("audio:threshold=%s" % a.threshold)
    cmd = [auto_editor_bin(), a.video, "--edit", edit, "--margin", a.margin, "--no-open"]
    stem = os.path.splitext(a.video)[0]
    if a.stats:
        cmd.append("--stats")
    elif a.resolve:
        cmd += ["--export", "resolve", "-o", a.output or stem + "_trimmed.fcpxml"]
    else:
        cmd += ["-o", a.output or stem + "_trimmed.mp4"]
    if a.silent_speed:
        cmd += ["--when-silent", "speed:%s" % a.silent_speed]
    print("running: " + " ".join(cmd))
    sys.exit(subprocess.call(cmd))


# --------------------------------------------------------------- loudness
def measure_loudness(path):
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostats", "-i", path, "-vn",
           "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"]
    err = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True).stderr
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        die("could not measure loudness of " + path)
    d = json.loads(m.group(0))
    return {"file": os.path.basename(path), "lufs": float(d["input_i"]),
            "true_peak_db": float(d["input_tp"]), "lra": float(d["input_lra"])}


def cmd_loudness(a):
    for p in a.files:
        r = measure_loudness(p)
        diff = r["lufs"] - TARGET_LUFS
        verdict = "OK" if abs(diff) <= 1.0 and r["true_peak_db"] <= -1.0 else (
            "too loud" if diff > 1.0 else "too quiet" if diff < -1.0 else "peaks too hot")
        print("%-40s %6.1f LUFS  peak %5.1f dBTP  LRA %4.1f  -> %s" % (
            r["file"][:40], r["lufs"], r["true_peak_db"], r["lra"], verdict))


# ------------------------------------------------------------------- main
def build_parser():
    p = argparse.ArgumentParser(prog="editkit", description=__doc__.split("\n")[0])
    p.add_argument("--version", action="version", version="editkit " + VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("beats", help="tempo, beat grid and big hits of a music track")
    s.add_argument("music")
    s.add_argument("--hits", type=int, default=12, help="how many big hits to list")
    s.add_argument("--fps", type=float, default=60, help="timeline fps for the marker EDL")
    s.add_argument("--out", help="output path stem (default: next to the music)")
    s.set_defaults(fn=cmd_beats)

    s = sub.add_parser("scenes", help="cut detection + action score per shot")
    s.add_argument("video")
    s.add_argument("--threshold", type=float, default=27.0, help="PySceneDetect content threshold")
    s.add_argument("--min-len", type=float, default=0.4, help="shortest shot in seconds")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--out", help="output path stem")
    s.set_defaults(fn=cmd_scenes)

    s = sub.add_parser("plan", help="put the best shots on the music's beat grid")
    s.add_argument("--music", required=True)
    s.add_argument("--video", required=True, nargs="+", help="one or more source recordings")
    s.add_argument("--beats-per-cut", type=int, default=2)
    s.add_argument("--length", type=float, help="seconds of music to fill (default: all)")
    s.add_argument("--start", type=float, help="music start in s (default: first downbeat)")
    s.add_argument("--threshold", type=float, default=27.0)
    s.add_argument("--preview", action="store_true", help="also render a low-res preview mp4")
    s.add_argument("--out", help="output path stem")
    s.set_defaults(fn=cmd_plan)

    s = sub.add_parser("trim", help="cut silence/dead time (auto-editor)")
    s.add_argument("video")
    s.add_argument("--threshold", default="4%", help="audio level counted as silence")
    s.add_argument("--motion", help="use motion instead of audio, e.g. 0.02")
    s.add_argument("--margin", default="0.3s", help="padding kept around loud parts")
    s.add_argument("--silent-speed", help="speed silent parts up instead of cutting, e.g. 8")
    s.add_argument("--resolve", action="store_true", help="export a DaVinci Resolve timeline, no render")
    s.add_argument("--stats", action="store_true", help="only show how much would be cut")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_trim)

    s = sub.add_parser("loudness", help="LUFS / true peak vs the -14 LUFS target")
    s.add_argument("files", nargs="+")
    s.set_defaults(fn=cmd_loudness)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
