"""Render short, isolated, full-body dance-look comparisons through H3.

This launcher is deliberately narrow: it uses a single adult fictional reference,
keeps the framing gate active, and produces three four-clip previews.  It does
not claim motion-transfer support or turn a prompt-only lighting request into a
guaranteed new set or camera move.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

H3_INPUT = Path("/vault/03_ENGINE/COMFYUI/PERSONAL/input/H3")
H3_OUTPUT = Path("/vault/03_ENGINE/COMFYUI/PERSONAL/output/H3")
SOURCE_JOB = H3_OUTPUT / "alpha_scene_director/7da788fb2d16457fbb905043fefb0365/job.json"
POSE_PYTHON = Path("/vault/03_ENGINE/COMFYUI/PERSONAL/home-comfyui-h3/.alpha-scene-director-pose/env/bin/python")
POSE_MODEL = Path("/vault/03_ENGINE/COMFYUI/PERSONAL/home-comfyui-h3/.alpha-scene-director-pose/pose_landmarker_full.task")

_COMMON = (
    "Original fictional adult woman in a cobalt-blue athletic jacket, black relaxed trousers, "
    "and white trainers. Full body from head to shoes remains visible in the same clean studio. "
    "Stable recognizable face, natural adult proportions, natural hands and feet, stable costume, "
    "non-sexual contemporary dance performance, no text or logos."
)
_NEGATIVE = (
    "cropped feet, cropped head, close-up, duplicate person, identity change, face morphing, "
    "costume change, flicker, text, logo, watermark, sexualized pose"
)
_PROFILES = {
    "editorial_studio": (
        "Clean editorial studio: soft warm key light and natural documentary color. "
        "A restrained contemporary groove with measured side steps, shoulder rolls, then a controlled return to center."
    ),
    "color_stage": (
        "Contemporary color-stage treatment within the same studio: controlled cobalt and muted magenta practical light, "
        "without changing the room geometry. A confident step-touch phrase, compact turn, and arm accents."
    ),
    "low_key_studio": (
        "Minimal low-key studio treatment: focused soft spotlight, restrained edge light, grounded shadow detail. "
        "A deliberate slow-build phrase with weight shifts, clear arm lines, and a calm final stance."
    ),
}


def preview_plans(first_image: str, last_image: str) -> dict[str, dict]:
    """Return independently runnable four-clip plans for a fair look comparison."""
    plans = {}
    for index, (identifier, treatment) in enumerate(_PROFILES.items(), 1):
        plans[identifier] = {
            "version": 1,
            "project": f"AlphaBeta Studios — Dance Look Preview — {identifier}",
            "global_prompt": _COMMON,
            "negative_prompt": _NEGATIVE,
            "defaults": {
                "first_image": first_image,
                "last_image": last_image,
                "frames": 48,
                "fps": 24,
                "seed": 202610290 + index,
            },
            "scenes": [{
                "id": identifier,
                "title": identifier.replace("_", " ").title(),
                "prompt": treatment,
                "direction": {
                    "shot": "Wide establishing shot",
                    "camera": "Wide-angle lens, deep focus",
                    "light": "Soft window light",
                    "look": "Natural documentary color",
                },
                "clips": [
                    {"prompt": "Begin settled, then establish the first two beats."},
                    {"prompt": "Continue the phrase with the same performer and full-body frame."},
                    {"prompt": "Add the stated movement accent without a camera cut or crop."},
                    {"prompt": "Resolve smoothly into a balanced final stance."},
                ],
            }],
        }
    return plans


async def render_profiles(source_job: Path, first_image: str, last_image: str, selected: list[str]) -> dict[str, dict]:
    # Keep plan inspection importable without the GPU image-analysis extras.
    from continuity_gate import GatePolicy
    from h3_continuity_gate import create_h3_gate
    from runner import JobManager
    from server_api import ComfyClient

    source = json.loads(source_job.read_text(encoding="utf-8"))
    gate = create_h3_gate(
        input_root=H3_INPUT,
        reference_image=first_image,
        policy=GatePolicy(.30, .30, max_attempts=2, version="source-domain-v0"),
        pose_python=POSE_PYTHON,
        pose_model=POSE_MODEL,
        probe_path=Path(__file__).resolve().parents[1] / "pose_probe.py",
    )
    manager = JobManager(H3_OUTPUT / "alpha_scene_director", H3_INPUT,
                         lambda: ComfyClient("http://127.0.0.1:8189"), gate)
    results = {}
    for identifier in selected:
        plan = preview_plans(first_image, last_image)[identifier]
        request = {
            "plan": plan,
            "workflow": source["workflow"],
            "director_id": source["director_id"],
            "checkpoint_id": source["checkpoint_id"],
            "video_output_id": source["video_output_id"],
        }
        job = manager.create(request)
        while manager.get(job["job_id"])["status"] in {"running", "pausing"}:
            await asyncio.sleep(2)
        results[identifier] = manager.get(job["job_id"])
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-job", type=Path, default=SOURCE_JOB)
    parser.add_argument("--first-image", default="alpha_original_dance_source_still_v1.png")
    parser.add_argument("--last-image", default="alpha_original_dance_source_still_v1.png")
    parser.add_argument("--profile", action="append", choices=sorted(_PROFILES), help="Render one profile; repeatable.")
    args = parser.parse_args()
    selected = args.profile or list(_PROFILES)
    print(json.dumps(asyncio.run(render_profiles(args.source_job, args.first_image, args.last_image, selected)), indent=2))


if __name__ == "__main__":
    main()
