#!/usr/bin/env python3
"""Snap each MP3 subtitle cue to the audio with a local forced alignment.

The cue text stays as written. A cue keeps its current times when the
acoustic match is weak, so a bad snap cannot walk off into another sentence.
"""

import re
import sys
from pathlib import Path

import torch
import torchaudio

from align_forced import (
    ACCEPT,
    JOBS,
    align_window,
    encode,
    load_wave,
    parse_srt,
    write_srt,
)

ROOT = Path(__file__).resolve().parents[1]


def refine_job(model, labels, lab, job):
    srt_path = ROOT / job["out"]
    cues = parse_srt(srt_path)
    # parse_srt drops times. Re-read them.
    raw = srt_path.read_text(errors="replace")
    times = []
    for match in re.finditer(
        r"(\d+):(\d+):(\d+),(\d+)\s+-->\s+(\d+):(\d+):(\d+),(\d+)", raw
    ):
        def sec(h, m, s, ms):
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

        h1, m1, s1, ms1, h2, m2, s2, ms2 = match.groups()
        times.append((sec(h1, m1, s1, ms1), sec(h2, m2, s2, ms2)))
    if len(times) != len(cues):
        raise SystemExit(f"{job['slug']}: {len(times)} times, {len(cues)} cues")
    print(f"refine {job['slug']} ({len(cues)} cues)", flush=True)
    wave = load_wave(ROOT / job["mp3"])
    snapped = 0
    for cue, (start, end) in zip(cues, times):
        cue["start"] = start
        cue["end"] = end
        words = len(cue["words"])
        pad_before = 2.5
        pad_after = 2.5
        window_start = max(0.0, start - pad_before)
        window_dur = max(6.0, (end - start) + pad_before + pad_after, words / 2.2 + 2)
        chars, _owners = encode([cue], labels)
        if not chars:
            continue
        result = align_window(
            model, labels, lab, wave, window_start, window_dur, chars
        )
        if result is None or result[0] < ACCEPT:
            continue
        _score, placed = result
        letter_times = [span for span in placed]
        cue["start"] = max(0.0, letter_times[0][0] - 0.04)
        cue["end"] = letter_times[-1][1] + 0.08
        snapped += 1
    # Keep the file in order and stop cues from crossing.
    cues.sort(key=lambda cue: (cue["start"], cue["end"]))
    for index in range(1, len(cues)):
        if cues[index]["start"] < cues[index - 1]["end"]:
            cues[index]["start"] = cues[index - 1]["end"]
        if cues[index]["end"] < cues[index]["start"] + 0.2:
            cues[index]["end"] = cues[index]["start"] + 0.2
    write_srt(srt_path, cues)
    print(f"  snapped {snapped}/{len(cues)}", flush=True)


def main():
    bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    model = bundle.get_model().cpu().eval()
    labels = bundle.get_labels()
    lab = {label: index for index, label in enumerate(labels)}
    selected = sys.argv[1:]
    jobs = [job for job in JOBS if not selected or job["slug"] in selected]
    for job in jobs:
        refine_job(model, labels, lab, job)


if __name__ == "__main__":
    main()
