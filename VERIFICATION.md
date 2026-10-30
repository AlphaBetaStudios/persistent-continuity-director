# Candidate verification — 2026-10-30

- Fresh isolated package Python suite: **66 tests passed** in the existing WS1 H3 Python 3.14 environment. Command: `python -m unittest discover -s tests -p 'test_*.py' -q`.
- Fresh Windows frontend suite: **28 tests passed**. Command: `node --test tests/test_frontend.mjs`.
- `npm run check`: three JavaScript modules passed syntax checking.
- Demo: H.264, 1280x720, 24 fps, 67 seconds. Full strict FFmpeg decode passed; no audio is included.
- Original-adult job: 0920da0d455d409eb9fc5c6f78fe8a95. Three clips passed configured endpoint checks; clip four reached manual review after the bounded retry. See docs/demo-job-evidence.json.
- The installed H3 node states a trained length range starting at124 frames; the shipped plan defaults use124. The demonstrated earlier run requested48 and rendered56 frames per clip. A successful124-frame identity run is not claimed.

The local system Python lacks NumPy/aiohttp, so it could not run the full suite. No dependencies were installed; the full suite passed in the existing H3 environment. Fresh checks do not establish visual acceptance of the editor or whole-video identity. The video is a captioned architecture/output/evidence demo, not an editor screen recording. Prior five-minute output is outside this release's media set.
