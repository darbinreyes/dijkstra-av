#!/usr/bin/env python3
"""Write an MP3-timed SRT by forced-aligning the existing transcript.

Wav2vec2 places the Remastered wording on this file's audio. A stretch of
audio that does not match the transcript is transcribed separately and
inserted, which covers the lectures whose subtitle timeline is shorter
than the MP3.
"""

import json
import re
import sys
from pathlib import Path

import torch
import torchaudio

ROOT = Path(__file__).resolve().parents[1]
TIME_LINE = re.compile(
    r"(\d+):(\d+):(\d+),(\d+)\s+-->\s+(\d+):(\d+):(\d+),(\d+)"
)
WORD = re.compile(r"[A-Za-z0-9']+")
ACCEPT = -2.4


def parse_srt(path):
    raw = path.read_text(errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        time_at = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_at is None or not TIME_LINE.search(lines[time_at]):
            continue
        text = " ".join(lines[time_at + 1 :]).strip()
        words = WORD.findall(text)
        if text and words:
            cues.append({"text": text, "words": words})
    return cues


def stamp(seconds):
    if seconds < 0:
        seconds = 0.0
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    minutes, secs = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(path, cues):
    parts = []
    for index, cue in enumerate(cues, start=1):
        parts.append(
            f"{index}\n{stamp(cue['start'])} --> {stamp(cue['end'])}\n{cue['text']}\n"
        )
    path.write_text("\n".join(parts) + "\n")


def encode(cues, labels):
    chars = []
    owners = []
    for cue_index, cue in enumerate(cues):
        if chars and chars[-1] != "|":
            chars.append("|")
            owners.append(-1)
        for token_index, token in enumerate(cue["words"]):
            if token_index:
                chars.append("|")
                owners.append(cue_index)
            for ch in token.upper():
                if ch == "'":
                    continue
                if ch in labels:
                    chars.append(ch)
                    owners.append(cue_index)
    if chars and chars[-1] == "|":
        chars.pop()
        owners.pop()
    return chars, owners


def align_window(model, labels, lab, wave, start, dur, chars):
    sample_rate = 16000
    total = wave.shape[1] / sample_rate
    start = max(0.0, min(start, max(0.0, total - 1.0)))
    dur = min(dur, total - start)
    a = int(start * sample_rate)
    b = max(a + sample_rate, int((start + dur) * sample_rate))
    chunk = wave[:, a:b]
    with torch.inference_mode():
        emission, _ = model(chunk)
    emission = torch.log_softmax(emission, dim=-1)
    targets = torch.tensor([[lab[ch] for ch in chars]])
    alignment, scores = torchaudio.functional.forced_align(
        emission, targets, blank=0
    )
    spans = torchaudio.functional.merge_tokens(alignment[0], scores[0])
    if len(spans) != len(chars):
        return None
    ratio = chunk.size(1) / emission.size(1)
    placed = []
    letter_scores = []
    for char, span in zip(chars, spans):
        t0 = start + span.start * ratio / sample_rate
        t1 = start + span.end * ratio / sample_rate
        placed.append((t0, t1))
        if char != "|":
            letter_scores.append(float(span.score))
    mean = sum(letter_scores) / max(len(letter_scores), 1)
    return mean, placed


def group_cues(cues, index, word_budget=36):
    chosen = []
    words = 0
    while index + len(chosen) < len(cues):
        cue = cues[index + len(chosen)]
        if chosen and words + len(cue["words"]) > word_budget:
            break
        chosen.append(cue)
        words += len(cue["words"])
        if words >= word_budget:
            break
    return chosen


def align_file(model, labels, lab, wave, cues):
    cursor = 0.0
    total = wave.shape[1] / 16000
    index = 0
    placed_cues = []
    gaps = []
    dropped = 0
    while index < len(cues):
        group = group_cues(cues, index)
        chars, owners = encode(group, labels)
        words = sum(len(cue["words"]) for cue in group)
        window = max(10.0, words / 2.1 + 5.0)
        found = None
        hop = 0.0
        while hop < 180 and cursor + hop < total - 1:
            result = align_window(
                model, labels, lab, wave, cursor + hop, window, chars
            )
            if result is not None and result[0] >= ACCEPT:
                found = (hop, result)
                break
            hop += 5.0
        if found is None:
            dropped += len(group)
            index += len(group)
            cursor = min(total, cursor + 2.0)
            continue
        hop, (score, placed) = found
        if hop >= 5.0:
            gaps.append({"start": cursor, "end": cursor + hop, "source": "gap"})
        by_cue = {}
        for (t0, t1), owner in zip(placed, owners):
            if owner < 0:
                continue
            slot = by_cue.setdefault(owner, [t0, t1])
            slot[0] = min(slot[0], t0)
            slot[1] = max(slot[1], t1)
        for local_index, cue in enumerate(group):
            if local_index not in by_cue:
                dropped += 1
                continue
            start, end = by_cue[local_index]
            placed_cues.append(
                {
                    "start": max(0.0, start - 0.04),
                    "end": end + 0.08,
                    "text": cue["text"],
                    "source": "aligned",
                    "score": round(score, 3),
                }
            )
        cursor = max(slot[1] for slot in by_cue.values())
        index += len(group)
        print(
            f"    {index}/{len(cues)} t={cursor:.0f}s score={score:.2f} hop={hop:.0f}",
            flush=True,
        )
    if total - cursor > 8:
        gaps.append({"start": cursor, "end": total, "source": "gap"})
    return placed_cues, gaps, dropped


def transcribe_gaps(gaps):
    usable = [gap for gap in gaps if gap["end"] - gap["start"] >= 8]
    if not usable:
        return []
    from mlx_audio.stt.utils import load

    print(f"  transcribe {len(usable)} uncovered stretches", flush=True)
    whisper = load("mlx-community/whisper-small-mlx")
    machine = []
    # The caller passes the mp3 path on each gap.
    return whisper, usable


def fill_gaps(whisper, mp3, gaps):
    import subprocess
    import tempfile

    machine = []
    dump = "/tmp/dijk-clone/dump"
    for gap in gaps:
        if gap["end"] - gap["start"] < 8:
            continue
        wav = tempfile.mktemp(suffix=".wav", prefix="gap-")
        subprocess.run(
            [dump, str(mp3), f"{gap['start']:.3f}", f"{gap['end'] - gap['start']:.3f}", wav],
            check=True,
            capture_output=True,
        )
        result = whisper.generate(
            wav, language="en", word_timestamps=False, verbose=False, temperature=0.0
        )
        text = (result.text or "").strip()
        if text:
            machine.append(
                {
                    "start": gap["start"],
                    "end": gap["end"],
                    "text": text,
                    "source": "whisper",
                }
            )
        Path(wav).unlink(missing_ok=True)
    return machine


# Same lecture list as the clone set, plus the Turing lecture.
JOBS = [
    {
        "slug": "thrills-1992",
        "mp3": "25 Years of Mathematical Thrills - 1992/audio/Original - Edsger Dijkstra - 25 Years of Mathematical Thrills.mp3",
        "srt": "25 Years of Mathematical Thrills - 1992/subtitles/Edsger Dijkstra - 25 Years of Mathetical Thrills - 1992 - Remastered 2.srt",
        "out": "25 Years of Mathematical Thrills - 1992/subtitles/Edsger Dijkstra - 25 Years of Mathematical Thrills - 1992 - MP3.srt",
    },
    {
        "slug": "early-memories",
        "mp3": "A Programmer’s Early Memories by Edsger W. Dijkstra/audio/A Programmer’s Early Memories by Edsger W. Dijkstra.mp3",
        "srt": "A Programmer’s Early Memories by Edsger W. Dijkstra/subtitles/A Programmer’s Early Memories by Edsger W. Dijkstra.srt",
        "out": "A Programmer’s Early Memories by Edsger W. Dijkstra/subtitles/A Programmer’s Early Memories by Edsger W. Dijkstra - MP3.srt",
    },
    {
        "slug": "interplay-1992",
        "mp3": "An Interplay Between Programming and Mathematics - 1992/audio/Edsger Dijkstra - An Interplay Between Programming and Mathematics - 1992 - Remastered.mp3",
        "srt": "An Interplay Between Programming and Mathematics - 1992/subtitles/Edsger Dijkstra - An Interplay Between Programming and Mathematics - 1992 - Remastered 2.srt",
        "out": "An Interplay Between Programming and Mathematics - 1992/subtitles/Edsger Dijkstra - An Interplay Between Programming and Mathematics - 1992 - MP3.srt",
    },
    {
        "slug": "reasoning-1990",
        "mp3": "Reasoning About Programs 1990/audio/Edsger W. Dijkstra - Lecture Reasoning About Programs - Solving 2 problems using programing - 1990.mp3",
        "srt": "Reasoning About Programs 1990/subtitles/Reasoning About Programs - 1990 - Remastered 2.srt",
        "out": "Reasoning About Programs 1990/subtitles/Reasoning About Programs - 1990 - MP3.srt",
    },
    {
        "slug": "counting-2001",
        "mp3": "The Power of Counting Arguments 2001/audio/Edsger Dijkstra - Lecture - Power of Counting Arguments - Cadence Labs - 2001.mp3",
        "srt": "The Power of Counting Arguments 2001/subtitles/Edsger Dijkstra - The Power of Counting Arguments - 2001 - Remastered 2.srt",
        "out": "The Power of Counting Arguments 2001/subtitles/Edsger Dijkstra - The Power of Counting Arguments - 2001 - MP3.srt",
    },
    {
        "slug": "notes-2001",
        "mp3": "What Led to Notes on Structured Programming 2001/audio/Edsger Dijkstra - What Led To Notes on Structured Programming.mp3",
        "srt": "What Led to Notes on Structured Programming 2001/subtitles/Edsger Dijkstra - What Led To Notes on Structured Programming - 2001 - Remastered 2.srt",
        "out": "What Led to Notes on Structured Programming 2001/subtitles/Edsger Dijkstra - What Led To Notes on Structured Programming - 2001 - MP3.srt",
    },
    {
        "slug": "turing-1972",
        "mp3": "Turing Award Lecture - The Humble Programmer - 1972/audio/Edsger Dijkstra - Turing Award Speech - 1972.mp3",
        "srt": "Turing Award Lecture - The Humble Programmer - 1972/subtitles/Edsger Dijkstra - Turing Award Speech - 1972 - Remastered 2.srt",
        "out": "Turing Award Lecture - The Humble Programmer - 1972/subtitles/Edsger Dijkstra - Turing Award Speech - 1972 - MP3.srt",
    },
]


def load_wave(path):
    from mlx_audio.audio_io import read as audio_read

    audio, _ = audio_read(str(path), dtype="float32", sample_rate=16000, nchannels=1)
    wave = torch.tensor(audio).float()
    if wave.ndim == 1:
        wave = wave.unsqueeze(0)
    return wave


def run_job(model, labels, lab, job):
    mp3 = ROOT / job["mp3"]
    out = ROOT / job["out"]
    cues = parse_srt(ROOT / job["srt"])
    print(f"load {job['slug']} ({len(cues)} cues)", flush=True)
    wave = load_wave(mp3)
    placed, gaps, dropped = align_file(model, labels, lab, wave, cues)
    machine = []
    long_gaps = [gap for gap in gaps if gap["end"] - gap["start"] >= 8]
    if long_gaps:
        from mlx_audio.stt.utils import load

        print(f"  whisper {len(long_gaps)} gaps", flush=True)
        whisper = load("mlx-community/whisper-small-mlx")
        machine = fill_gaps(whisper, mp3, long_gaps)
        del whisper
    merged = placed + machine
    merged.sort(key=lambda cue: (cue["start"], cue["end"]))
    for index in range(1, len(merged)):
        if merged[index]["start"] < merged[index - 1]["end"]:
            merged[index]["start"] = merged[index - 1]["end"]
        if merged[index]["end"] < merged[index]["start"] + 0.2:
            merged[index]["end"] = merged[index]["start"] + 0.2
    write_srt(out, merged)
    report = {
        "slug": job["slug"],
        "source_srt": job["srt"],
        "source_mp3": job["mp3"],
        "output_srt": str(out.relative_to(ROOT)),
        "original_cues": len(cues),
        "aligned_cues": len(placed),
        "dropped_cues": dropped,
        "gap_regions": [
            {"start": round(gap["start"], 2), "end": round(gap["end"], 2)} for gap in long_gaps
        ],
        "machine_cues": len(machine),
        "machine_seconds": round(sum(cue["end"] - cue["start"] for cue in machine), 1),
    }
    out.with_suffix(".align.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"  {job['slug']}: aligned {len(placed)} dropped {dropped} "
        f"gaps {len(long_gaps)} machine {report['machine_seconds']}s",
        flush=True,
    )
    return report


def main():
    raise SystemExit(
        "Use voice-clone/align_mp3.py to place the transcript, then "
        "voice-clone/refine_times.py to snap the cue times."
    )


if __name__ == "__main__":
    main()
