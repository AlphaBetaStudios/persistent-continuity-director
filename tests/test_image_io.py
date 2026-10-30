"""Real image/filesystem checks: checkpoint loss, wrong endpoints and unsafe paths."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ImageIOTests(unittest.TestCase):
    def setUp(self):
        try:
            self.io = importlib.import_module('image_io')
        except ImportError:
            self.fail('image_io implementation is not present yet')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'input'
        self.outputs = self.root / 'output' / 'alpha_scene_director'
        self.inputs.mkdir()

    def test_checkpoint_preserves_first_and_actual_last_pixels(self):
        first = np.zeros((2, 4, 3), dtype=np.float32)
        last = np.ones((2, 4, 3), dtype=np.float32)
        last[0, 0] = [1, 0, 0]
        receipt = self.io.save_endpoints(self.inputs, self.outputs, 'job-a', 'attempt-a', first, last, 81)
        saved = json.loads((self.outputs / 'job-a' / 'attempt-a.receipt.json').read_text())
        self.assertEqual(saved, receipt)
        self.assertEqual(saved['frame_count'], 81)
        self.assertEqual((saved['width'], saved['height']), (4, 2))
        with Image.open(self.inputs / saved['first_frame']) as image:
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
        with Image.open(self.inputs / saved['last_frame']) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(image.getpixel((1, 0)), (255, 255, 255))

    def test_loader_returns_rgb_batch_and_fingerprint_changes_with_file(self):
        path = self.inputs / 'face.png'
        Image.new('RGBA', (4, 2), (255, 0, 0, 0)).save(path)
        loaded = self.io.load_image_array(self.inputs, 'face.png')
        self.assertEqual(loaded.shape, (1, 2, 4, 3))
        np.testing.assert_array_equal(loaded[0, 0, 0], [1, 0, 0])
        old = self.io.image_fingerprint(self.inputs, 'face.png')
        Image.new('RGB', (4, 2), 'blue').save(path)
        self.assertNotEqual(old, self.io.image_fingerprint(self.inputs, 'face.png'))

    def test_invalid_frame_and_unsafe_identifier_create_no_receipt(self):
        good = np.zeros((2, 4, 3), dtype=np.float32)
        for job_id, last in [('../outside', good), ('job-a', np.full((2, 4, 3), np.nan)), ('job-a', np.zeros((1, 1, 3)))]:
            with self.subTest(job_id=job_id, shape=last.shape), self.assertRaises(ValueError):
                self.io.save_endpoints(self.inputs, self.outputs, job_id, 'attempt-a', good, last, 81)
        self.assertFalse(list(self.root.rglob('*.receipt.json')))

    def test_loader_refuses_absolute_and_parent_paths(self):
        outside = self.root / 'secret.png'
        Image.new('RGB', (2, 2)).save(outside)
        for name in ['../secret.png', str(outside), 'folder/../../secret.png']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.io.load_image_array(self.inputs, name)


if __name__ == '__main__':
    unittest.main()
