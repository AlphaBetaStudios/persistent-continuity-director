# Persistent Continuity Director

By AlphaBeta Studios. ComfyUI custom nodes and a Cinematic Studio workspace for resumable multi-clip video generation.

Plan scenes, prompts and endpoint images, then render clips in order. Each accepted clip hands its actual decoded last frame to the next clip. Project records persist prompts, seeds, frame counts, attempts and output paths. Pause finishes the current clip; Resume checks saved artifacts before continuing. The browser may close while the ComfyUI server continues working.

## Install and run locally

1. Copy `comfyui_alpha_scene_director` into your active `ComfyUI/custom_nodes/` directory, with `__init__.py` directly inside that folder.
2. Use that ComfyUI installation's Python environment. Install `requirements.txt` only if its dependencies are missing. Do not replace torch. FFmpeg and FFprobe must be on PATH for video endpoint extraction.
3. Restart ComfyUI and refresh its frontend. Add **Alpha Scene Director** and **Alpha Scene Checkpoint**, under **AlphaBeta Studios / Scene Director**. The package also supplies **Alpha H3 Duration to Frames**.
4. Open the Scene Director editor. Use your working first/last-frame video graph, select the director/checkpoint/video output nodes, upload your own original or licensed endpoint images, then validate the plan before Run.
5. Start with two clips. Check the generated files and saved endpoint receipts. Pause and Resume use the frozen graph and plan stored for that job.

`examples/h3-api-workflow.json` is a request wrapper containing the API graph under `workflow` plus the director/checkpoint/video output selectors. Extract its `workflow` object for API graph import. It is a graph for the existing MiniMax H3 node pack, not a bundled model or a portable installer. Match loader names to your installed model files. Copy the included original fictional-adult reference into ComfyUI input/H3, or upload your own reference and update the plan. No weights are included. The example template is a written scene plan, not a finished movie.

## What makes this different

The application treats a long video as a persistent sequence of independently recorded clips. It reconciles uncertain API responses before retrying, preserves the actual rendered handoff frame, and supports bounded same-clip continuity retries. A rejected clip pauses for review instead of being silently promoted. The continuity gate is optional and requires a configured scorer; installing the UI alone does not establish identity preservation.

## Evidence and limits

See `VERIFICATION.md` for fresh package checks. Prior local H3 proof records include a 129-clip sequence; that history is distinct from the new fictional-adult dance demo. The new short dance run accepted three clips at its configured endpoint gate, then rejected clip four. It is a failure-handling demonstration, not a fully qualified dance or an automatic repair success. Endpoint checks do not prove whole-video identity, choreography, blur quality or universal continuity.

The five-minute output is not included because its source media is outside this original-adult submission set. No private personal photographs, calibration images, model weights or credentials are included.

## Tests

Run in your existing ComfyUI Python environment:

    python -m unittest discover -s tests -p 'test_*.py' -q
    node --test tests/test_frontend.mjs
    npm run check

Python dependencies: see requirements.txt. Node >=20 is declared in package.json. Tests can also run on Node18 with the included test-only shim.

## License

MIT for the application code; see LICENSE. Third-party notices remain in THIRD_PARTY_NOTICES.md. Model and media terms are separate.

## Demo

[67-second captioned demo](demo/Persistent-Continuity-Director-Demo.mp4). Silent; all explanations are on screen. The video shows actual rendered clips and the recorded review stop. It does not include a screen recording of the editor.
