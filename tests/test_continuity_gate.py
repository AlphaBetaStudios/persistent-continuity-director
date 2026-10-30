import unittest

from continuity_gate import GatePolicy, evaluate


class ContinuityGateTests(unittest.TestCase):
    def setUp(self):
        self.policy = GatePolicy(0.8, 0.75, max_blur=0.2, max_attempts=2)

    def test_accepts_only_complete_good_measurements(self):
        report = evaluate({"artifact_ok": True, "face_detected": True, "face_similarity": 0.9,
                           "boundary_similarity": 0.9, "full_body_visible": True, "blur": 0.1}, self.policy, 1)
        self.assertEqual(report["decision"], "accepted")
        self.assertEqual(report["reasons"], [])

    def test_repairs_a_measured_first_failure(self):
        report = evaluate({"artifact_ok": True, "face_detected": True, "face_similarity": 0.6,
                           "boundary_similarity": 0.9, "full_body_visible": True, "blur": 0.1}, self.policy, 1)
        self.assertEqual(report["decision"], "repair_required")
        self.assertIn("face_similarity_below_threshold", report["reasons"])

    def test_stops_automatic_repair_at_the_attempt_limit(self):
        report = evaluate({"artifact_ok": True, "face_detected": True, "face_similarity": 0.6,
                           "boundary_similarity": 0.9, "full_body_visible": True, "blur": 0.1}, self.policy, 2)
        self.assertEqual(report["decision"], "manual_review")

    def test_missing_measurement_requires_review(self):
        report = evaluate({"artifact_ok": True, "face_detected": False,
                           "boundary_similarity": 0.9, "full_body_visible": True}, self.policy, 1)
        self.assertEqual(report["decision"], "manual_review")

    def test_requires_full_body_framing(self):
        report = evaluate({"artifact_ok": True, "face_detected": True, "face_similarity": 0.9,
                           "boundary_similarity": 0.9, "full_body_visible": False, "blur": 0.1}, self.policy, 1)
        self.assertEqual(report["decision"], "manual_review")
        self.assertIn("full_body_framing_failed", report["reasons"])


if __name__ == "__main__":
    unittest.main()
