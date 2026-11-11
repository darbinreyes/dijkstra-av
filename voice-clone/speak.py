#!/usr/bin/env python3
"""Speak text with the local Dijkstra reference voice.

The voice is not a saved fine-tune. Qwen3-TTS reads voice-clone/reference.wav
at generation time. See README.md for how that clip was chosen.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent
DEFAULT_REF_JSON = ROOT / "reference.json"
MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"


def load_reference_defaults():
    data = json.loads(DEFAULT_REF_JSON.read_text())
    return ROOT / "reference.wav", data["ref_text"]


def chunks_of(text):
    """Split on blank lines so each paragraph stops on its own."""
    parts = [part.strip() for part in text.split("\n\n")]
    parts = [part for part in parts if part]
    if not parts:
        raise SystemExit("no text to speak")
    return parts


def max_tokens_for(text):
    # About four codec tokens per word on this model. The cap stops a
    # missed end-of-speech token from talking for many minutes.
    words = max(1, len(text.split()))
    return min(800, max(120, words * 8))


def main():
    default_wav, default_ref_text = load_reference_defaults()
    parser = argparse.ArgumentParser(description="Speak text in the Dijkstra reference voice")
    parser.add_argument("--text", help="Text to speak. Separate paragraphs with a blank line.")
    parser.add_argument("--text-file", type=Path, help="Read the text from this file.")
    parser.add_argument("--reference-wav", type=Path, default=default_wav)
    parser.add_argument("--ref-text", default=default_ref_text, help="Transcript of the reference clip.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--temperature", type=float, default=0.7)
    args = parser.parse_args()

    if args.text and args.text_file:
        raise SystemExit("pass only one of --text and --text-file")
    if args.text_file:
        text = args.text_file.read_text()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()
    pieces = chunks_of(text)

    if not args.reference_wav.is_file():
        raise SystemExit(
            f"reference clip not found: {args.reference_wav}\n"
            "Extract it with the command in README.md."
        )

    from mlx_audio.tts.utils import load_model

    print(f"loading {MODEL}", flush=True)
    model = load_model(MODEL)
    rendered = []
    sample_rate = None
    for index, piece in enumerate(pieces):
        print(f"chunk {index}: {piece}", flush=True)
        results = list(
            model.generate(
                text=piece,
                lang_code="en",
                ref_audio=str(args.reference_wav),
                ref_text=args.ref_text,
                max_tokens=max_tokens_for(piece),
                temperature=args.temperature,
                verbose=True,
            )
        )
        for result in results:
            audio = np.array(result.audio, dtype=np.float32).reshape(-1)
            sample_rate = result.sample_rate
            print(
                f"  dur={audio.size / sample_rate:.2f}s peak={np.max(np.abs(audio)):.3f}",
                flush=True,
            )
            rendered.append(audio)

    gap = np.zeros(int(sample_rate * 0.45), dtype=np.float32)
    joined = []
    for index, audio in enumerate(rendered):
        if index:
            joined.append(gap)
        joined.append(audio)
    out = np.concatenate(joined)
    peak = float(np.max(np.abs(out)))
    if peak > 0.98:
        out = out * (0.98 / peak)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output, out, sample_rate)
    print(f"wrote {args.output} dur={out.size / sample_rate:.2f}s", flush=True)


if __name__ == "__main__":
    main()
