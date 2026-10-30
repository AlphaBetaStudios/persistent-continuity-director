"""Node contracts tested at CPU image boundary; actual torch/GPU execution is pending."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class NodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / 'input'
        self.output = self.root / 'output'
        self.input.mkdir()
        self.output.mkdir()
        self.paths = types.SimpleNamespace(get_input_directory=lambda: str(self.input), get_output_directory=lambda: str(self.output))
        path = ROOT / 'nodes.py'
        if not path.exists():
            self.fail('node implementations are not present yet')
        spec = importlib.util.spec_from_file_location('alpha_nodes_test', path)
        self.nodes = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'folder_paths': self.paths}):
            spec.loader.exec_module(self.nodes)

    def test_director_outputs_follow_wiring_contract_and_carry_explicit_values(self):
        Image.new('RGB', (4, 2), 'red').save(self.input / 'first.png')
        Image.new('RGB', (4, 2), 'blue').save(self.input / 'last.png')
        # Only the external torch boundary is replaced. Loading, numeric data,
        # endpoint choice, prompts, naming and returned values are production code.
        torch_boundary = types.SimpleNamespace(from_numpy=lambda value: value)
        with patch.dict(sys.modules, {'torch': torch_boundary}):
            values = self.nodes.AlphaSceneDirector().prepare('{}', 'first.png', 'last.png', 'Norah turns', 'flicker', 37, 81, 16.0, 'job-x', 'attempt-y')
        self.assertEqual(len(values), 11)
        np.testing.assert_array_equal(values[0][0, 0, 0], [1, 0, 0])
        np.testing.assert_array_equal(values[1][0, 0, 0], [0, 0, 1])
        self.assertEqual(values[2:], ('Norah turns', 'flicker', 37, 81, 16.0, 'alpha_scene_director/job-x/attempt-y', 'job-x', 'attempt-y', 5.0625))
        self.assertEqual(self.nodes.AlphaSceneDirector.RETURN_TYPES, ('IMAGE', 'IMAGE', 'STRING', 'STRING', 'INT', 'INT', 'FLOAT', 'STRING', 'STRING', 'STRING', 'FLOAT'))
        self.assertEqual(self.nodes.AlphaSceneDirector.RETURN_NAMES[-1], 'duration_seconds')

    def test_changed_file_invalidates_director_cache(self):
        for name in ('first.png', 'last.png'):
            Image.new('RGB', (4, 2), 'red').save(self.input / name)
        first = self.nodes.AlphaSceneDirector.IS_CHANGED(first_image='first.png', last_image='last.png')
        Image.new('RGB', (4, 2), 'blue').save(self.input / 'last.png')
        second = self.nodes.AlphaSceneDirector.IS_CHANGED(first_image='first.png', last_image='last.png')
        self.assertNotEqual(first, second)

    def test_h3_duration_converter_snaps_to_the_model_frame_grid(self):
        convert = self.nodes.AlphaH3DurationFrames().convert
        self.assertEqual(convert(2.0, 24, 17, 5, 5, 3600), (56,))
        self.assertEqual(convert(5.0, 24, 17, 5, 5, 3600), (124,))
        self.assertEqual(convert(0.1, 24, 17, 5, 5, 3600), (5,))
        with self.assertRaises(ValueError):
            convert(200.0, 24, 17, 5, 5, 3600)

    def test_checkpoint_selects_decoded_last_frame_and_passes_batch_through(self):
        class TensorBoundary:
            def __init__(self, values):
                self.values = np.asarray(values)
                self.shape = self.values.shape
                self.ndim = self.values.ndim
            def __getitem__(self, item):
                return TensorBoundary(self.values[item])
            def detach(self):
                return self
            def float(self):
                return self
            def cpu(self):
                return self
            def numpy(self):
                return self.values
        frames = TensorBoundary(np.stack([np.zeros((2, 4, 3)), np.full((2, 4, 3), 0.5), np.ones((2, 4, 3))]))
        result = self.nodes.AlphaSceneCheckpoint().checkpoint(frames, 'job-x', 'attempt-y')
        self.assertIs(result[0], frames)
        with Image.open(self.input / 'alpha_scene_director/job-x/attempt-y_last.png') as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))


if __name__ == '__main__':
    unittest.main()
