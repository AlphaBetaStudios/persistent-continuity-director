import unittest

from continuity_scorer import ScoringUnavailable, cosine_similarity, largest_face_embedding


class Face:
    def __init__(self, bbox, embedding):
        self.bbox = bbox
        self.embedding = embedding


class Detector:
    def __init__(self, faces):
        self.faces = faces

    def get(self, image):
        return self.faces


class ContinuityScorerTests(unittest.TestCase):
    def test_largest_face_is_selected(self):
        detector = Detector([Face([0, 0, 1, 1], [1, 0]), Face([0, 0, 3, 2], [0, 1])])
        self.assertEqual(largest_face_embedding(detector, object()), [0.0, 1.0])

    def test_missing_face_fails_closed(self):
        with self.assertRaises(ScoringUnavailable):
            largest_face_embedding(Detector([]), object())

    def test_cosine_similarity_is_bounded(self):
        self.assertEqual(cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertEqual(cosine_similarity([1, 0], [-1, 0]), -1.0)

    def test_incompatible_embeddings_fail_closed(self):
        with self.assertRaises(ScoringUnavailable):
            cosine_similarity([1], [1, 0])
