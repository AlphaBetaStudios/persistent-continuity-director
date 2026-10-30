"""Filesystem-backed runner tests with a controlled public ComfyUI API boundary."""

import asyncio
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    runner = importlib.import_module("runner")
except ModuleNotFoundError:
    runner = None
from test_core import native_video_workflow, plan, workflow


class Rejected(RuntimeError):
    definitive = True


class PublicAPIFixture:
    """Models the public queue/history boundary; all receipts and artifacts are real files."""

    def __init__(self, root, input_root):
        self.root = root
        self.input_root = input_root
        self.submissions = []
        self.histories = {}
        self.queued = set()
        self.mode = "auto"
        self.saved_before_post = []
        self.video_bucket = "gifs"
        self.bad_artifact = None

    async def submit(self, prompt, prompt_id):
        inputs = prompt["1"]["inputs"]
        manifest = json.loads((self.root / inputs["run_id"] / "job.json").read_text())
        self.saved_before_post.append(any(c.get("prompt_id") == prompt_id for c in manifest["clips"]))
        self.submissions.append((prompt_id, copy.deepcopy(prompt)))
        if self.mode == "rejected":
            raise Rejected("Invalid model input")
        if self.mode == "lost":
            raise OSError("connection lost after write")
        self.queued.add(prompt_id)
        if self.mode == "error":
            self.histories[prompt_id] = {"outputs": {}, "status": {"completed": False,
                "status_str": "error", "messages": [["execution_error", {"exception_message": "out of memory"}]]}}
            self.queued.discard(prompt_id)
        elif self.mode == "auto":
            self.complete(prompt_id)
        elif self.mode == "accepted_timeout":
            raise OSError("response lost after acceptance")
        return {"prompt_id": prompt_id, "number": len(self.submissions), "node_errors": {}}

    async def history(self, prompt_id):
        return {prompt_id: copy.deepcopy(self.histories[prompt_id])} if prompt_id in self.histories else {}

    async def queue_ids(self):
        return set(self.queued)

    def complete(self, prompt_id):
        prompt = next(p for ident, p in self.submissions if ident == prompt_id)
        fields = prompt["1"]["inputs"]
        job_id, attempt = fields["run_id"], fields["clip_id"]
        first = f"alpha_scene_director/{job_id}/{attempt}_first.png"
        last = f"alpha_scene_director/{job_id}/{attempt}_last.png"
        for relative in (first, last):
            path = self.input_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (4, 3), (34, 56, 78)).save(path, format="PNG")
        receipt = {"job_id": job_id, "attempt_id": attempt, "first_frame": first,
                   "last_frame": last, "frame_count": fields["frames"], "width": 4, "height": 3}
        if self.bad_artifact == "wrong_count":
            receipt["frame_count"] = fields["frames"] - 1
        if self.bad_artifact == "native_count":
            receipt["frame_count"] = 121
        if self.bad_artifact == "fake_png":
            Image.new("RGB", (4, 3)).save(self.input_root / last, format="JPEG")
        receipt_path = self.root / job_id / f"{attempt}.receipt.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        video = self.root / job_id / f"{attempt}_00001.mp4"
        video.write_bytes(b"fixture video bytes")
        entry = {"filename": video.name, "subfolder": f"alpha_scene_director/{job_id}", "type": "output"}
        if self.bad_artifact == "no_video":
            video.unlink()
        if self.bad_artifact == "png_only":
            entry["filename"] = f"{attempt}.png"
            Image.new("RGB", (4, 3)).save(video.parent / entry["filename"])
        if self.bad_artifact == "traversal":
            entry["subfolder"] = "../"
        if self.bad_artifact == "stale_video":
            entry["filename"] = "old_render_00001.mp4"
            (video.parent / entry["filename"]).write_bytes(b"unrelated old render")
        self.histories[prompt_id] = {"outputs": {"4": {self.video_bucket: [entry]}},
            "status": {"completed": True, "status_str": "success", "messages": []}}
        self.queued.discard(prompt_id)


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(runner, "Durable scene runner has not been implemented")
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / "output" / "alpha_scene_director"
        self.input_root = base / "input"
        self.input_root.mkdir()
        for filename in ("start.png", "end.png"):
            Image.new("RGB", (4, 3)).save(self.input_root / filename)
        self.api = PublicAPIFixture(self.root, self.input_root)
        self.managers = []
        self.manager = self.new_manager()

    def new_manager(self, continuity_gate=None):
        manager = runner.JobManager(self.root, self.input_root, lambda: self.api, continuity_gate)
        manager.poll_interval = 0.001
        self.managers.append(manager)
        return manager

    async def asyncTearDown(self):
        for manager in getattr(self, "managers", []):
            tasks = list(manager._tasks.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def request(self, clips=2):
        return {"plan": plan(clips), "workflow": workflow(), "director_id": "1", "checkpoint_id": "3", "video_output_id": "4"}

    def native_request(self, clips=1):
        return {"plan": plan(clips), "workflow": native_video_workflow(), "director_id": "1", "checkpoint_id": "3", "video_output_id": "4"}

    async def until(self, predicate):
        async def wait():
            while not predicate():
                await asyncio.sleep(0.001)
        await asyncio.wait_for(wait(), timeout=2)

    async def settled(self, job_id, manager=None):
        manager = manager or self.manager
        await self.until(lambda: manager.get(job_id)["status"] not in ("running", "pausing"))
        return manager.get(job_id)

    async def test_validates_later_images_before_creating_gpu_work(self):
        request = self.request()
        request["plan"]["scenes"].append({"prompt": "later", "last_image": "missing.png", "clips": 1})
        with self.assertRaises(ValueError):
            self.manager.create(request)
        self.assertEqual(self.api.submissions, [])
        self.assertEqual(self.manager.list_jobs(), [])

    async def test_rejects_corrupt_static_image_before_queueing(self):
        (self.input_root / "end.png").write_text("not an image")
        with self.assertRaises(ValueError):
            self.manager.validate(self.request())
        self.assertEqual(self.api.submissions, [])

    async def test_serial_generation_persists_ids_and_uses_actual_last_frame(self):
        request = self.request()
        job = self.manager.create(request)
        request["plan"]["global_prompt"] = "edited after Start"
        request["workflow"]["2"]["inputs"]["steps"] = 999
        result = await self.settled(job["job_id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["completed"], result["total"]), (2, 2))
        self.assertEqual(self.api.saved_before_post, [True, True])
        second = self.api.submissions[1][1]
        self.assertEqual(second["1"]["inputs"]["first_image"], result["clips"][0]["receipt"]["last_frame"])
        self.assertEqual(second["1"]["inputs"]["positive"], "cinematic\n\nrain")
        self.assertEqual(second["2"]["inputs"]["steps"], 20)
        public = self.manager.get(job["job_id"])
        public["clips"][0]["status"] = "pending"
        self.assertEqual(self.manager.get(job["job_id"])["completed"], 2)

    async def test_continuity_gate_pauses_before_handoff(self):
        class ReviewGate:
            def evaluate(self, job, clip, receipt, videos):
                return {"decision": "manual_review", "reason": "identity score needs review"}

        manager = self.new_manager(ReviewGate())
        job = manager.create(self.request())
        result = await self.settled(job["job_id"], manager)
        self.assertEqual(result["status"], "paused")
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["clips"][0]["status"], "manual_review")
        self.assertEqual(result["clips"][0]["gate_report"]["decision"], "manual_review")
        self.assertEqual(len(self.api.submissions), 1)

    async def test_repair_required_retries_the_same_clip_before_handoff(self):
        class RepairThenAcceptGate:
            def __init__(self):
                self.calls = 0

            def evaluate(self, job, clip, receipt, videos):
                self.calls += 1
                return {"decision": "repair_required" if self.calls == 1 else "accepted"}

        gate = RepairThenAcceptGate()
        manager = self.new_manager(gate)
        job = manager.create(self.request(clips=2))
        result = await self.settled(job["job_id"], manager)
        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["completed"], result["total"]), (2, 2))
        self.assertEqual(gate.calls, 3)
        self.assertEqual(len(self.api.submissions), 3)
        attempts = manager._require_job(job["job_id"])["clips"][0]["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["status"], "repair_required")
        self.assertEqual(self.api.submissions[2][1]["1"]["inputs"]["first_image"], result["clips"][0]["receipt"]["last_frame"])

    async def test_duration_workflow_records_actual_native_frame_count(self):
        self.api.bad_artifact = "native_count"
        job = self.manager.create(self.native_request())
        result = await self.settled(job["job_id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["clips"][0]["receipt"]["frame_count"], 121)

    async def test_duplicate_start_is_rejected_while_a_clip_is_active(self):
        self.api.mode = "manual"
        job = self.manager.create(self.request())
        await self.until(lambda: bool(self.api.submissions))
        with self.assertRaises(ValueError):
            self.manager.create(self.request())
        self.assertEqual(self.manager.get(job["job_id"])["status"], "running")
        self.assertEqual(len(self.api.submissions), 1)

    async def test_execution_error_is_terminal_even_when_completed_is_false(self):
        self.api.mode = "error"
        job = self.manager.create(self.request())
        result = await self.settled(job["job_id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("out of memory", result["error"])
        self.assertEqual(result["completed"], 0)
        self.assertEqual(len(self.api.submissions), 1)

    async def test_checkpoint_receipt_alone_cannot_confirm_video_completion(self):
        self.api.bad_artifact = "no_video"
        job = self.manager.create(self.request())
        result = await self.settled(job["job_id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["completed"], 0)
        self.assertEqual(len(self.api.submissions), 1)

    async def test_savevideo_images_bucket_is_accepted_only_for_video_files(self):
        self.api.video_bucket = "images"
        job = self.manager.create(self.request(1))
        self.assertEqual((await self.settled(job["job_id"]))["status"], "completed")
        self.api.bad_artifact = "png_only"
        next_job = self.manager.create(self.request(1))
        self.assertEqual((await self.settled(next_job["job_id"]))["status"], "failed")

    async def test_timeout_after_queue_acceptance_is_reconciled_without_resubmit(self):
        self.api.mode = "accepted_timeout"
        job = self.manager.create(self.request(1))
        await self.until(lambda: bool(self.api.submissions))
        await asyncio.sleep(0.01)
        self.assertEqual(self.manager.get(job["job_id"])["status"], "running")
        self.api.complete(self.api.submissions[0][0])
        self.assertEqual((await self.settled(job["job_id"]))["status"], "completed")
        self.assertEqual(len(self.api.submissions), 1)

    async def test_unlocatable_submission_stops_until_explicit_resume(self):
        self.api.mode = "lost"
        job = self.manager.create(self.request(1))
        interrupted = await self.settled(job["job_id"])
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertIsNotNone(interrupted["clips"][0]["prompt_id"])
        await asyncio.sleep(0.01)
        self.assertEqual(len(self.api.submissions), 1)
        self.api.mode = "auto"
        self.manager.resume(job["job_id"])
        # A timed-out POST may still be validating before it enters the queue.
        # Same-session absence is not evidence of a completed server restart.
        result = await self.settled(job["job_id"])
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(len(self.api.submissions), 1)
        replacement = self.new_manager()
        replacement.resume(job["job_id"])
        result = await self.settled(job["job_id"], replacement)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.api.submissions), 2)
        self.assertNotEqual(self.api.submissions[0][0], self.api.submissions[1][0])
        self.assertNotEqual(self.api.submissions[0][1]["1"]["inputs"]["clip_id"], self.api.submissions[1][1]["1"]["inputs"]["clip_id"])

    async def test_create_captures_adapter_before_another_request_changes_context(self):
        other_api = PublicAPIFixture(self.root, self.input_root)
        current = {"client": self.api}
        self.manager.client_factory = lambda: current["client"]
        job = self.manager.create(self.request(1))
        current["client"] = other_api
        self.assertEqual((await self.settled(job["job_id"]))["status"], "completed")
        self.assertEqual(len(self.api.submissions), 1)
        self.assertEqual(other_api.submissions, [])

    async def test_pause_finishes_current_clip_then_resume_starts_only_next(self):
        self.api.mode = "manual"
        job = self.manager.create(self.request())
        await self.until(lambda: bool(self.api.submissions))
        self.assertEqual(self.manager.pause(job["job_id"])["status"], "pausing")
        self.api.complete(self.api.submissions[0][0])
        paused = await self.settled(job["job_id"])
        self.assertEqual((paused["status"], paused["completed"]), ("paused", 1))
        self.assertEqual(len(self.api.submissions), 1)
        self.api.mode = "auto"
        self.manager.resume(job["job_id"])
        self.assertEqual((await self.settled(job["job_id"]))["completed"], 2)
        self.assertEqual(len(self.api.submissions), 2)

    async def test_restart_reconciles_existing_inflight_prompt_without_duplication(self):
        self.api.mode = "manual"
        job = self.manager.create(self.request(1))
        await self.until(lambda: bool(self.api.submissions))
        tasks = list(self.manager._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        replacement = self.new_manager()
        self.assertEqual(replacement.get(job["job_id"])["status"], "interrupted")
        replacement.resume(job["job_id"])
        replacement.resume(job["job_id"])
        await asyncio.sleep(0.01)
        self.assertEqual(len(self.api.submissions), 1)
        self.api.complete(self.api.submissions[0][0])
        result = await self.settled(job["job_id"], replacement)
        self.assertEqual(result["status"], "completed")

    async def test_restart_with_cleared_history_rerenders_only_unconfirmed_clip(self):
        self.api.mode = "manual"
        job = self.manager.create(self.request())
        await self.until(lambda: len(self.api.submissions) == 1)
        self.api.complete(self.api.submissions[0][0])
        await self.until(lambda: len(self.api.submissions) == 2)
        tasks = list(self.manager._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.api.histories.clear()
        self.api.queued.clear()
        self.api.mode = "auto"
        replacement = self.new_manager()
        replacement.resume(job["job_id"])
        result = await self.settled(job["job_id"], replacement)
        self.assertEqual((result["status"], result["completed"]), ("completed", 2))
        self.assertEqual(len(self.api.submissions), 3)
        self.assertEqual(self.api.submissions[-1][1]["1"]["inputs"]["first_image"], result["clips"][0]["receipt"]["last_frame"])

    async def test_resume_refuses_missing_completed_video(self):
        self.api.mode = "manual"
        job = self.manager.create(self.request())
        await self.until(lambda: bool(self.api.submissions))
        self.manager.pause(job["job_id"])
        self.api.complete(self.api.submissions[0][0])
        await self.settled(job["job_id"])
        video = next((self.root / job["job_id"]).glob("*.mp4"))
        video.unlink()
        with self.assertRaises(ValueError):
            self.manager.resume(job["job_id"])
        self.assertEqual(len(self.api.submissions), 1)

    async def test_bad_receipt_or_unsafe_artifact_cannot_be_completed(self):
        for failure in ("fake_png", "wrong_count", "traversal", "stale_video"):
            self.api.bad_artifact = failure
            job = self.manager.create(self.request(1))
            with self.subTest(failure=failure):
                result = await self.settled(job["job_id"])
                self.assertEqual((result["status"], result["completed"]), ("failed", 0))

    async def test_definitive_prompt_rejection_fails_without_ambiguous_resume_state(self):
        self.api.mode = "rejected"
        job = self.manager.create(self.request(1))
        result = await self.settled(job["job_id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("Invalid model input", result["error"])
        self.assertEqual(len(self.api.submissions), 1)


if __name__ == "__main__":
    unittest.main()
