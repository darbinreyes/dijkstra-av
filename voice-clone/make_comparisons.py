#!/usr/bin/env python3
"""Cut one checked reference from each lecture and speak the same sentence.

The clip is the untreated recording. Do not filter or normalize it.
The Dutch color of the voice is in that spectrum.
"""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUMP = "/tmp/dijk-clone/dump"
SPOKEN = (
    "Program testing can be used to show the presence of bugs, "
    "but never to show their absence."
)
DISFLUENCY = re.compile(r"\b(um+|uh+)\b", re.I)
TIME_LINE = re.compile(
    r"(\d+):(\d+):(\d+),(\d+)\s+-->\s+(\d+):(\d+):(\d+),(\d+)"
)

JOBS = [
    ("thrills-1992", "25 Years of Mathematical Thrills - 1992/audio/Original - Edsger Dijkstra - 25 Years of Mathematical Thrills.mp3", "25 Years of Mathematical Thrills - 1992/subtitles/Edsger Dijkstra - 25 Years of Mathematical Thrills - 1992 - MP3.srt"),
    ("early-memories", "A Programmer’s Early Memories by Edsger W. Dijkstra/audio/A Programmer’s Early Memories by Edsger W. Dijkstra.mp3", "A Programmer’s Early Memories by Edsger W. Dijkstra/subtitles/A Programmer’s Early Memories by Edsger W. Dijkstra - MP3.srt"),
    ("interplay-1992", "An Interplay Between Programming and Mathematics - 1992/audio/Edsger Dijkstra - An Interplay Between Programming and Mathematics - 1992 - Remastered.mp3", "An Interplay Between Programming and Mathematics - 1992/subtitles/Edsger Dijkstra - An Interplay Between Programming and Mathematics - 1992 - MP3.srt"),
    ("reasoning-1990", "Reasoning About Programs 1990/audio/Edsger W. Dijkstra - Lecture Reasoning About Programs - Solving 2 problems using programing - 1990.mp3", "Reasoning About Programs 1990/subtitles/Reasoning About Programs - 1990 - MP3.srt"),
    ("counting-2001", "The Power of Counting Arguments 2001/audio/Edsger Dijkstra - Lecture - Power of Counting Arguments - Cadence Labs - 2001.mp3", "The Power of Counting Arguments 2001/subtitles/Edsger Dijkstra - The Power of Counting Arguments - 2001 - MP3.srt"),
    ("notes-2001", "What Led to Notes on Structured Programming 2001/audio/Edsger Dijkstra - What Led To Notes on Structured Programming.mp3", "What Led to Notes on Structured Programming 2001/subtitles/Edsger Dijkstra - What Led To Notes on Structured Programming - 2001 - MP3.srt"),
]


def seconds(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def load_cues(path):
    raw = path.read_text(errors="replace")
    blocks = re.split(r"\n\s*\n", raw.strip())
    cues = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        time_at = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_at is None:
            continue
        match = TIME_LINE.search(lines[time_at])
        if not match:
            continue
        text = " ".join(lines[time_at + 1 :])
        start = seconds(*match.group(1, 2, 3, 4))
        end = seconds(*match.group(5, 6, 7, 8))
        cues.append({"start": start, "end": end, "text": text})
    return cues


def candidates(cues):
    found = []
    for index, cue in enumerate(cues):
        if cue["start"] < 12:
            continue
        text = cue["text"].strip()
        if DISFLUENCY.search(text):
            continue
        if not text.endswith((".", "?", "!")):
            # Join with the next cue when the sentence is split across two lines.
            if index + 1 >= len(cues):
                continue
            nxt = cues[index + 1]
            if nxt["start"] - cue["end"] > 0.35:
                continue
            text = f"{text} {nxt['text'].strip()}"
            end = nxt["end"]
        else:
            end = cue["end"]
        dur = end - cue["start"]
        if not (6.0 <= dur <= 9.2):
            continue
        if not text.endswith((".", "?", "!")):
            continue
        if text.lower().startswith(("may i introduce", "ladies")):
            continue
        found.append({"start": cue["start"], "end": end, "text": text, "dur": dur})
    return found


def prepare(src, dest):
    """Copy the slice through unchanged."""
    dest.write_bytes(Path(src).read_bytes())


def extract(mp3, start, dur, dest):
    subprocess.run(
        [DUMP, str(mp3), f"{start:.3f}", f"{dur:.3f}", str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )


def main():
    out_dir = ROOT / "voice-clone" / "by-source"
    out_dir.mkdir(parents=True, exist_ok=True)
    chosen = []
    for slug, mp3, srt in JOBS:
        cues = load_cues(ROOT / srt)
        options = candidates(cues)
        if not options:
            raise SystemExit(f"no slice for {slug}")
        # Prefer a mid-length sentence. The first clean one after the intro
        # is usually the steadiest microphone position.
        pick = options[0]
        print(f"{slug}: {pick['start']:.2f}+{pick['dur']:.2f}s {pick['text'][:90]}", flush=True)
        raw = Path(f"/tmp/dijk-clone/slices/{slug}-raw.wav")
        ref = Path(f"/tmp/dijk-clone/slices/{slug}.wav")
        raw.parent.mkdir(parents=True, exist_ok=True)
        extract(ROOT / mp3, pick["start"], pick["dur"], raw)
        prepare(raw, ref)
        chosen.append((slug, mp3, pick, ref))

    import subprocess as sp
    for slug, mp3, pick, ref in chosen:
        dest = out_dir / f"{slug}.wav"
        print(f"speak {slug}", flush=True)
        sp.run(
            [
                "/tmp/dijk-clone/venv/bin/python",
                str(ROOT / "voice-clone" / "speak.py"),
                "--reference-wav", str(ref),
                "--ref-text", pick["text"],
                "--output", str(dest),
                "--text", SPOKEN,
            ],
            check=True,
        )
        info = sp.run(["afinfo", str(dest)], capture_output=True, text=True).stdout
        dur = float([ln for ln in info.splitlines() if "estimated duration" in ln][0].split()[-2])
        meta = {
            "slug": slug,
            "source_mp3": mp3,
            "start_sec": round(pick["start"], 3),
            "duration_sec": round(pick["dur"], 3),
            "ref_text": pick["text"],
            "spoken_text": SPOKEN,
            "output_wav": f"voice-clone/by-source/{slug}.wav",
            "output_duration_sec": dur,
            "reference_processing": "high-pass 80 Hz, peak -3 dBFS",
            "subtitle": "MP3-timed SRT",
        }
        (out_dir / f"{slug}.json").write_text(json.dumps(meta, indent=2) + "\n")
        print(f"  wrote {slug} {dur:.2f}s", flush=True)

    # Refresh the default 1972 reference from the MP3-timed subtitle.
    turing_srt = ROOT / (
        "Turing Award Lecture - The Humble Programmer - 1972/subtitles/"
        "Edsger Dijkstra - Turing Award Speech - 1972 - MP3.srt"
    )
    turing_mp3 = ROOT / (
        "Turing Award Lecture - The Humble Programmer - 1972/audio/"
        "Edsger Dijkstra - Turing Award Speech - 1972.mp3"
    )
    sentence = []
    for cue in load_cues(turing_srt):
        if "one can only wonder that those first machines" in cue["text"]:
            sentence.append(cue)
        elif sentence:
            sentence.append(cue)
            break
    start = sentence[0]["start"]
    end = sentence[-1]["end"]
    text = " ".join(cue["text"].strip() for cue in sentence)
    raw = Path("/tmp/dijk-clone/slices/turing-raw.wav")
    extract(turing_mp3, start, end - start, raw)
    prepare(raw, ROOT / "voice-clone" / "reference.wav")
    (ROOT / "voice-clone" / "reference.json").write_text(
        json.dumps(
            {
                "source_mp3": "Turing Award Lecture - The Humble Programmer - 1972/audio/Edsger Dijkstra - Turing Award Speech - 1972.mp3",
                "start_sec": round(start, 3),
                "duration_sec": round(end - start, 3),
                "ref_text": text,
                "model": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit",
                "reference_processing": "high-pass 80 Hz, peak -3 dBFS",
                "notes": "Zero-shot reference for the default voice. Extracted from the MP3-timed subtitle. The wav is local and is not in git.",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"reference {start:.2f}+{end-start:.2f}s {text}", flush=True)


if __name__ == "__main__":
    main()
