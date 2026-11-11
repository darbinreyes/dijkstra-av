# dijkstra-av

See `.claude/CLAUDE.md` for the project rules. Short version:

* Audio and video stay on disk and are gitignored. Do not force-add them.
* Read text with `voice-clone/speak.py`. The default reference clip is `voice-clone/reference.json`.
* Keep a voice reference between 6 and 9 seconds, one speaker.
* Run one voice generation at a time on a 32 GB Mac.
* Commit messages follow Conventional Commits.
