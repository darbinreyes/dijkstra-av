# dijkstra-av

Local archive of Edsger W. Dijkstra lectures, with a zero-shot voice reading on top. The public git repo is `darbinreyes/dijkstra-av`.

## Files

Audio and video are gitignored on purpose. Do not `git add -f` an mp3, wav, mp4, or mov. Do not commit lecture screenshots.

The recordings are in the working tree beside the text. Subtitles (`*.srt`, `*.vtt`, `*.sbv`), the Babbage transcript, `srt.py`, `euclid.vii.py`, and the small PDFs are tracked.

Generated readings go under `voice-clone/` as wav files. They are ignored. A json note of which slice was used may be committed.

## Reading text aloud

Use `voice-clone/speak.py`. The default voice is the clip described in `voice-clone/reference.json`, extracted to `voice-clone/reference.wav`. The README has the setup and the extract command.

Pass `--reference-wav` and `--ref-text` to try a different lecture. Keep the reference to one speaker and about 6 to 9 seconds. A reference near 20 seconds makes Qwen3-TTS miss the end of the sentence and keep generating.

Split a long passage on blank lines. The script speaks each paragraph separately. On a 32 GB Mac, run one `speak.py` at a time. Two concurrent model loads is the upper limit.

The model id is `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`.

## Writing

Commit messages follow Conventional Commits. Do not reformat subtitles or the existing Python scripts unless that was the task. Number new lists from 0.
