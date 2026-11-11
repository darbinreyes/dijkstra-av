# dijkstra-av

Lectures by Edsger W. Dijkstra, kept as local recordings, plus a way to have a local model read text in a voice built from one of them.

The recordings are not in this repository. Git ignores every audio and video file. What is here is the subtitle work, a few short programs, and the voice-clone notes.

## Turn text into audio

This needs an Apple Silicon Mac. The reading runs on the machine. Nothing is uploaded.

One-time setup, from the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install "qwen-tts-cli[mlx]"
swiftc -O -o voice-clone/extract_slice voice-clone/extract_slice.swift
```

Build the reference clip from the 1972 Turing Award lecture. The MP3 stays on disk next to this repo:

```bash
./voice-clone/extract_slice \
  "Turing Award Lecture - The Humble Programmer - 1972/audio/Edsger Dijkstra - Turing Award Speech - 1972.mp3" \
  301.139 5.874 voice-clone/reference.wav
```

Read a sentence:

```bash
.venv/bin/python voice-clone/speak.py \
  --text "Program testing can be used to show the presence of bugs, but never to show their absence." \
  --output voice-clone/out.wav
```

A longer passage should be split into paragraphs with a blank line between them. Each paragraph is spoken on its own and joined with a short pause. That matters: one very long generation can miss its ending and keep talking.

```bash
.venv/bin/python voice-clone/speak.py \
  --text-file passage.txt \
  --output voice-clone/out.wav
```

`voice-clone/out.wav` and `voice-clone/reference.wav` are audio, so git ignores them.

A few spellings need a spoken form or the model slurs them:

* Write the Eindhoven acronym as `T. H. E.` so it is read as letters.
* Write `so far` rather than Dijkstra's `sofar`.
* Write `that is` rather than `i.e.`
* A name dropped in parentheses, such as `(Aron)`, comes out garbled. Put it in a short phrase, for example `a remark due to Aron`.

On this M4 with 32 GB of memory, one reading uses about 7 GB and runs near real time once the model is loaded. Run one reading at a time. Two at once is the most that still fits.

## How the voice clone was created

There is no trained voice file and no account. The clone is a reference clip handed to a zero-shot model each time it speaks.

The model is `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`, the 8-bit MLX build of Qwen3-TTS 1.7B Base. It runs through the `mlx-audio` package. Weights download into the local Hugging Face cache on first use.

The clip is 5.9 seconds from the Turing Award lecture, *The Humble Programmer* (1972), starting at 5:01.139. The words are:

> In retrospect, one can only wonder that those first machines worked at all, at least sometimes.

Those numbers are also in `voice-clone/reference.json`. The clip was chosen because it is one speaker, one complete thought, and under ten seconds. A 21-second excerpt from the same lecture made the model continue for many minutes after the sentence was finished. A reference of about 6 to 9 seconds, plus a token cap inside `voice-clone/speak.py`, is what keeps a reading to the length of the text.

The transcript of the clip is passed in with the audio. The model uses both. Temperature is 0.7.

This is a likeness of the 1972 lecture voice, heard through a muffled public-address recording. It is not a separate clone of the 1990 or 2001 talks. Those are different rooms and an older voice.

## One clip from each other lecture

`voice-clone/by-source/` holds a reading of the same sentence from each remaining lecture MP3, so the voices can be compared. The sentence is: "Program testing can be used to show the presence of bugs, but never to show their absence."

The wav files are gitignored. The json files record the excerpt: which recording, the start time, and the words in the excerpt. Each excerpt is about 6 to 8 seconds of Dijkstra alone. The subtitle clocks do not match every MP3, so the times were checked against the audio.

Left out, on purpose: Discipline in Thought, the Charles Babbage Institute interview, the 2000 retirement banquet, and the Turing lecture. The Turing lecture is the default voice above.

## Subtitles timed to the MP3

Each lecture has a second subtitle file, named `... - MP3.srt`, next to the Remastered 2 file. The wording is the Remastered transcript. The times were matched to that MP3, then snapped against the waveform. Use these files when cutting a reference clip. The Remastered files stay as they were, because several of them belong to a different edit of the video.

`voice-clone/align_mp3.py` does the match. `voice-clone/refine_times.py` snaps the times. Leave the reference clip otherwise untouched. The Dutch color in his English sits in the spectrum of the tape, and a high-pass or loudness filter washes it out.

Early Memories runs about 80 seconds past its old subtitles, and Interplay about three minutes. Those tails are applause and a "thank you," not more of the lecture, so they were left out of the transcript.

## What is tracked

Tracked: subtitle files, the Babbage interview transcript, `srt.py`, `euclid.vii.py`, the small PDFs, and everything under `voice-clone/` except the generated audio.

Not tracked: MP3, WAV, MP4, MOV, and the lecture screenshots. Those files remain in this directory on disk.
