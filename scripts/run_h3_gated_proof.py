"""Run one isolated H3 clip through the explicit continuity gate.

This is a qualification harness, not a normal ComfyUI route. It reuses a
previously accepted graph and writes under a separate output root.
"""
from __future__ import annotations

import asyncio
import argparse
import json
from pathlib import Path

from continuity_gate import GatePolicy
from h3_continuity_gate import create_h3_gate
from runner import JobManager
from server_api import ComfyClient


H3_INPUT = Path("/vault/03_ENGINE/COMFYUI/PERSONAL/input/H3")
H3_OUTPUT = Path("/vault/03_ENGINE/COMFYUI/PERSONAL/output/H3")
SOURCE_JOB = H3_OUTPUT / "alpha_scene_director/7010ae7c203e40628c2217c64dedaa4c/job.json"
POSE_PYTHON = Path("/vault/03_ENGINE/COMFYUI/PERSONAL/home-comfyui-h3/.alpha-scene-director-pose/env/bin/python")
POSE_MODEL = Path("/vault/03_ENGINE/COMFYUI/PERSONAL/home-comfyui-h3/.alpha-scene-director-pose/pose_landmarker_full.task")


async def main(clips: int = 1):
    if not 1 <= clips <= 130:
        raise ValueError("clips must be between 1 and 130")
    source = json.loads(SOURCE_JOB.read_text(encoding="utf-8"))
    first = source["clips"][0]["first_image"]
    last = source["clips"][0]["last_image"]
    request = {
        "plan": {"version": 1, "project": "Gated H3 qualification copy",
                 "defaults": {"first_image": first, "last_image": last, "frames": 48, "fps": 24, "seed": 1},
                 "scenes": [{"id": "proof", "title": "Gated proof", "prompt": source["clips"][0]["prompt"], "clips": clips}]},
        "workflow": source["workflow"], "director_id": source["director_id"],
        "checkpoint_id": source["checkpoint_id"], "video_output_id": source["video_output_id"],
    }
    policy = GatePolicy(.30, .30, max_attempts=2, version="source-domain-v0")
    gate = create_h3_gate(input_root=H3_INPUT, reference_image=first, policy=policy,
                          pose_python=POSE_PYTHON, pose_model=POSE_MODEL,
                          probe_path=Path(__file__).resolve().parents[1] / "pose_probe.py")
    # The installed AlphaSceneCheckpoint uses this fixed ComfyUI receipt root.
    # Job IDs keep this qualification run isolated from every earlier job.
    manager = JobManager(H3_OUTPUT / "alpha_scene_director", H3_INPUT,
                         lambda: ComfyClient("http://127.0.0.1:8189"), gate)
    job = manager.create(request)
    while manager.get(job["job_id"])["status"] in {"running", "pausing"}:
        await asyncio.sleep(2)
    print(json.dumps(manager.get(job["job_id"]), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", type=int, default=1,
                        help="Number of connected gated clips to render (1-130).")
    args = parser.parse_args()
    asyncio.run(main(args.clips))
