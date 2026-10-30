import types
import unittest

from pose_probe import visible_full_body


def point(x, y, visibility=0.9, presence=0.9):
    return types.SimpleNamespace(x=x, y=y, visibility=visibility, presence=presence)


class PoseProbeTests(unittest.TestCase):
    def pose(self, lower):
        items = [point(.5, .1)] + [point(.5, .5) for _ in range(32)]
        for index, value in zip((29, 30, 31, 32), lower):
            items[index] = value
        return types.SimpleNamespace(pose_landmarks=[items])

    def test_accepts_one_fast_motion_occlusion(self):
        visible, _ = visible_full_body(self.pose([
            point(.4, .8, .39), point(.6, .8), point(.4, .9), point(.6, .9),
        ]))
        self.assertTrue(visible)

    def test_rejects_close_crop_with_missing_feet(self):
        visible, _ = visible_full_body(self.pose([
            point(.4, 1.8, .01, .01), point(.6, 1.8, .01, .01),
            point(.4, 1.9, .01, .01), point(.6, 1.9, .01, .01),
        ]))
        self.assertFalse(visible)
