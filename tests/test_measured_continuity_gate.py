import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from continuity_gate import GatePolicy
from measured_continuity_gate import MeasuredContinuityGate


class Face:
    bbox = [0, 0, 4, 4]
    embedding = [1.0, 0.0]


class Detector:
    def get(self, image):
        return [Face()]


class MeasuredContinuityGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("reference.png", "alpha_scene_director/job/clip_first.png", "alpha_scene_director/job/clip_last.png"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(np.full((8, 8, 3), 100, dtype=np.uint8)).save(path)
        self.receipt = {"first_frame": "alpha_scene_director/job/clip_first.png",
                        "last_frame": "alpha_scene_director/job/clip_last.png"}
        self.policy = GatePolicy(0.8, 0.8, version="test")

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_body_evidence_fails_closed_to_manual_review(self):
        gate = MeasuredContinuityGate(self.root, "reference.png", self.policy, Detector())
        report = gate.evaluate({}, {"attempts": []}, self.receipt, [{"relative_path": "clip.mp4"}])
        self.assertEqual(report["decision"], "manual_review")
        self.assertTrue(report["measurements"]["face_detected"])
        self.assertIn("full_body_framing_failed", report["reasons"])

    def test_measured_faces_and_body_evidence_can_pass(self):
        seen = []
        gate = MeasuredContinuityGate(self.root, "reference.png", self.policy, Detector(), lambda path: seen.append(path) or True)
        report = gate.evaluate({}, {"attempts": []}, self.receipt, [{"relative_path": "clip.mp4"}])
        self.assertEqual(report["decision"], "accepted")
        self.assertEqual(report["measurements"]["face_similarity"], 1.0)
        self.assertEqual(report["measurements"]["boundary_similarity"], 1.0)
        self.assertEqual(seen, ["alpha_scene_director/job/clip_last.png"])


if __name__ == "__main__":
    unittest.main()
