#!/usr/bin/env python3
"""Align an existing subtitle file to the lecture MP3 and write a new SRT.

The Remastered transcripts keep their wording. Only the times change, and
only where the words can be found in a Whisper pass over that MP3. Speech
in the MP3 that the old subtitles never cover is appended from Whisper.
"""

import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path("/tmp/dijk-clone/whisper-align")
WORD = re.compile(r"[A-Za-z0-9']+")
TIME_LINE = re.compile(
    r"(\d+):(\d+):(\d+),(\d+)\s+-->\s+(\d+):(\d+):(\d+),(\d+)"
)
HALLUCINATION = re.compile(
    r"thanks for watching|subscribe|subtitles by|copyright|www\.",
    re.I,
)


def norm(token):
    found = WORD.findall(token.lower().replace("’", "'").replace("‘", "'"))
    return found[0].replace("'", "") if found else ""


def tokenize(text):
    return [norm(tok) for tok in WORD.findall(text)]


def parse_srt(path):
    raw = path.read_text(errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_at = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_at is None:
            continue
        match = TIME_LINE.search(lines[time_at])
        if not match:
            continue
        text = " ".join(lines[time_at + 1 :]).strip()
        if not text:
            continue
        cues.append({"text": text, "words": tokenize(text)})
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n")


def load_whisper_words(model, mp3, cache_path):
    if cache_path.is_file():
        return clean_words(json.loads(cache_path.read_text()))
    result = model.generate(
        str(mp3),
        language="en",
        word_timestamps=True,
        verbose=False,
        condition_on_previous_text=False,
        temperature=0.0,
    )
    words = []
    for segment in result.segments:
        for word in segment.get("words") or []:
            token = norm(word["word"])
            if not token:
                continue
            words.append(
                {
                    "norm": token,
                    "raw": word["word"].strip(),
                    "start": float(word["start"]),
                    "end": float(word["end"]),
                    "probability": float(word.get("probability") or 0),
                }
            )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(words))
    return clean_words(words)


def clean_words(words):
    cleaned = []
    for word in words:
        token = norm(word.get("raw") or word.get("norm") or "")
        if not token:
            continue
        word["norm"] = token
        cleaned.append(word)
    return cleaned


def align_words(srt_tokens, whisper_words):
    whisper_tokens = [word["norm"] for word in whisper_words]
    matcher = difflib.SequenceMatcher(
        a=srt_tokens, b=whisper_tokens, autojunk=False
    )
    srt_hit = [None] * len(srt_tokens)
    whisper_used = [False] * len(whisper_tokens)

    def take_equal(i1, i2, j1):
        for offset in range(i2 - i1):
            srt_hit[i1 + offset] = j1 + offset
            whisper_used[j1 + offset] = True

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            take_equal(i1, i2, j1)
            continue
        if tag != "replace":
            continue
        if i2 - i1 > 40 or j2 - j1 > 40:
            continue
        local = difflib.SequenceMatcher(
            a=srt_tokens[i1:i2], b=whisper_tokens[j1:j2], autojunk=False
        )
        if local.ratio() < 0.55:
            continue
        for local_tag, a1, a2, b1, b2 in local.get_opcodes():
            if local_tag == "equal":
                take_equal(i1 + a1, i1 + a2, j1 + b1)
    return srt_hit, whisper_used


def cues_from_alignment(cues, whisper_words, srt_hit, whisper_used):
    # Flat word list points back at its cue.
    owners = []
    for cue_index, cue in enumerate(cues):
        owners.extend([cue_index] * len(cue["words"]))

    kept = []
    dropped = 0
    cursor = 0
    for cue_index, cue in enumerate(cues):
        count = len(cue["words"])
        hits = [
            srt_hit[cursor + offset]
            for offset in range(count)
            if srt_hit[cursor + offset] is not None
        ]
        cursor += count
        if not hits or len(hits) / max(count, 1) < 0.45:
            dropped += 1
            continue
        start = whisper_words[hits[0]]["start"]
        end = whisper_words[hits[-1]]["end"]
        if end - start < 0.25:
            dropped += 1
            continue
        kept.append(
            {
                "start": max(0.0, start - 0.05),
                "end": end + 0.12,
                "text": cue["text"],
                "source": "aligned",
            }
        )

    gaps = []
    bucket = []

    def flush():
        nonlocal bucket
        if not bucket:
            return
        text = " ".join(word["raw"] for word in bucket).strip()
        probs = [word["probability"] for word in bucket]
        mean_prob = sum(probs) / len(probs)
        duration = bucket[-1]["end"] - bucket[0]["start"]
        if (
            len(bucket) >= 4
            and duration >= 1.2
            and mean_prob >= 0.35
            and not HALLUCINATION.search(text)
        ):
            gaps.append(
                {
                    "start": max(0.0, bucket[0]["start"] - 0.05),
                    "end": bucket[-1]["end"] + 0.12,
                    "text": text[:1].upper() + text[1:] if text else text,
                    "source": "whisper",
                }
            )
        bucket = []

    for index, word in enumerate(whisper_words):
        if whisper_used[index]:
            flush()
            continue
        if bucket and word["start"] - bucket[-1]["end"] > 1.0:
            flush()
        bucket.append(word)
        if word["raw"].endswith((".", "?", "!")) and (
            word["end"] - bucket[0]["start"]
        ) > 8:
            flush()
    flush()

    merged = kept + gaps
    merged.sort(key=lambda cue: (cue["start"], cue["end"]))
    # Keep cues from crossing each other after the padding.
    for index in range(1, len(merged)):
        if merged[index]["start"] < merged[index - 1]["end"]:
            merged[index]["start"] = merged[index - 1]["end"]
        if merged[index]["end"] <= merged[index]["start"]:
            merged[index]["end"] = merged[index]["start"] + 0.3
    return merged, dropped


def align_one(model, job):
    mp3 = ROOT / job["mp3"]
    srt_path = ROOT / job["srt"]
    out_path = ROOT / job["out"]
    report_path = out_path.with_suffix(".align.json")
    cache_path = CACHE / f"{job['slug']}.json"
    print(f"transcribe {job['slug']}", flush=True)
    whisper_words = load_whisper_words(model, mp3, cache_path)
    cues = parse_srt(srt_path)
    srt_tokens = [token for cue in cues for token in cue["words"]]
    print(
        f"  align {len(cues)} cues, {len(srt_tokens)} srt words, {len(whisper_words)} heard words",
        flush=True,
    )
    srt_hit, whisper_used = align_words(srt_tokens, whisper_words)
    merged, dropped = cues_from_alignment(cues, whisper_words, srt_hit, whisper_used)
    write_srt(out_path, merged)
    machine = [cue for cue in merged if cue["source"] == "whisper"]
    report = {
        "slug": job["slug"],
        "source_srt": job["srt"],
        "source_mp3": job["mp3"],
        "output_srt": job["out"],
        "original_cues": len(cues),
        "written_cues": len(merged),
        "aligned_cues": sum(cue["source"] == "aligned" for cue in merged),
        "dropped_cues": dropped,
        "machine_cues": len(machine),
        "machine_seconds": round(sum(cue["end"] - cue["start"] for cue in machine), 1),
        "matched_srt_words": sum(hit is not None for hit in srt_hit),
        "srt_words": len(srt_tokens),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"  wrote {out_path.name}: aligned {report['aligned_cues']}, "
        f"dropped {dropped}, machine {len(machine)} cues / {report['machine_seconds']}s",
        flush=True,
    )
    return report


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


def main():
    from mlx_audio.stt.utils import load

    selected = sys.argv[1:]
    jobs = [job for job in JOBS if not selected or job["slug"] in selected]
    print("loading whisper", flush=True)
    model = load("mlx-community/whisper-small-mlx")
    reports = [align_one(model, job) for job in jobs]
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
