"""Behavioral contracts for deterministic scene compilation and graph isolation."""

import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    core = importlib.import_module("director_core")
except ModuleNotFoundError:
    core = None
try:
    from scripts import run_h3_dance_previews as preview_script
except ModuleNotFoundError:
    preview_script = None


def workflow():
    return {
        "1": {"class_type": "AlphaSceneDirector", "inputs": {
            "scene_plan": "{}", "first_image": "start.png", "last_image": "end.png",
            "positive": "fallback", "negative": "", "seed": 1, "frames": 9,
            "fps": 8.0, "run_id": "preview", "clip_id": "clip-001"}},
        "2": {"class_type": "ExistingVideoModel", "inputs": {
            "first": ["1", 0], "last": ["1", 1], "positive": ["1", 2],
            "negative": ["1", 3], "seed": ["1", 4], "frames": ["1", 5], "steps": 20}},
        "3": {"class_type": "AlphaSceneCheckpoint", "inputs": {
            "images": ["2", 0], "run_id": ["1", 8], "clip_id": ["1", 9]}},
        "4": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["3", 0], "frame_rate": ["1", 6],
            "filename_prefix": ["1", 7], "format": "video/h264-mp4"}},
    }


def native_video_workflow():
    """H3-shaped graph: duration input, native VIDEO, decoded checkpoint, re-encode."""
    return {
        "1": {"class_type": "AlphaSceneDirector", "inputs": {
            "scene_plan": "{}", "first_image": "start.png", "last_image": "end.png",
            "positive": "fallback", "negative": "", "seed": 1, "frames": 81,
            "fps": 16.0, "run_id": "preview", "clip_id": "clip-001"}},
        "2": {"class_type": "H3VideoGenerator", "inputs": {
            "first_frame": ["1", 0], "last_frame": ["1", 1], "prompt": ["1", 2],
            "noise_seed": ["1", 4], "duration": ["1", 10]}},
        "5": {"class_type": "GetVideoComponents", "inputs": {"video": ["2", 0]}},
        "3": {"class_type": "AlphaSceneCheckpoint", "inputs": {
            "images": ["5", 0], "run_id": ["1", 8], "clip_id": ["1", 9]}},
        "6": {"class_type": "CreateVideo", "inputs": {
            "images": ["3", 0], "audio": ["5", 1], "fps": ["5", 2]}},
        "4": {"class_type": "SaveVideo", "inputs": {
            "video": ["6", 0], "filename_prefix": ["1", 7], "format": "mp4"}},
    }


def expanded_h3_workflow():
    """Frontend-expanded H3 graph: decoded frames/audio feed CreateVideo directly."""
    return {
        "1": {"class_type": "AlphaSceneDirector", "inputs": {
            "scene_plan": "{}", "first_image": "start.png", "last_image": "end.png",
            "positive": "fallback", "negative": "", "seed": 1, "frames": 48,
            "fps": 24.0, "run_id": "preview", "clip_id": "clip-001"}},
        "2": {"class_type": "ExpandedH3Generator", "inputs": {
            "first_frame": ["1", 0], "last_frame": ["1", 1], "prompt": ["1", 2],
            "noise_seed": ["1", 4], "duration": ["1", 10]}},
        "3": {"class_type": "AlphaSceneCheckpoint", "inputs": {
            "images": ["2", 0], "run_id": ["1", 8], "clip_id": ["1", 9]}},
        "6": {"class_type": "CreateVideo", "inputs": {
            "images": ["3", 0], "audio": ["2", 1], "fps": ["1", 6]}},
        "4": {"class_type": "SaveVideo", "inputs": {
            "video": ["6", 0], "filename_prefix": ["1", 7], "format": "mp4"}},
    }


def plan(clips=1):
    return {"version": 1, "project": "Norah", "global_prompt": "cinematic",
            "negative_prompt": "flicker", "defaults": {
                "first_image": "start.png", "last_image": "end.png",
                "frames": 9, "fps": 8, "seed": 7},
            "scenes": [{"id": "arrival", "title": "Arrival", "prompt": "rain", "clips": clips}]}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(core, "Scene-plan validation has not been implemented")

    def test_expansion_joins_prompts_and_carries_previous_frame(self):
        source = plan([{}, {"prompt": "turns toward camera", "seed": 19}])
        source["scenes"].append({"id": "departure", "title": "Departure", "prompt": "dawn",
                                  "first_image": "bridge.png", "clips": 2})
        before = copy.deepcopy(source)
        clips = core.compile_plan(source)
        self.assertEqual([c["id"] for c in clips], ["s01-c001", "s01-c002", "s02-c001", "s02-c002"])
        self.assertEqual([c["first_image"] for c in clips], ["start.png", "@previous", "bridge.png", "@previous"])
        self.assertEqual(clips[1]["prompt"], "cinematic\n\nrain\n\nturns toward camera")
        self.assertEqual([c["seed"] for c in clips], [7, 19, 7, 7])
        self.assertEqual(source, before)

    def test_widget_fallback_and_clip_override_inheritance(self):
        source = {"version": 1, "scenes": [{"prompt": "walk", "input_overrides": {"2": {"steps": 24}},
                  "clips": [{"input_overrides": {"2": {"steps": 32}}, "frames": 17}]}]}
        clips = core.compile_plan(source, {"first_image": "a.png", "last_image": "b.png",
                "positive": "world", "negative": "blur", "seed": 3, "frames": 9, "fps": 12})
        self.assertEqual(clips[0]["prompt"], "world\n\nwalk")
        self.assertEqual(clips[0]["negative_prompt"], "blur")
        self.assertEqual(clips[0]["frames"], 17)
        self.assertEqual(clips[0]["fps"], 12)
        self.assertEqual(clips[0]["input_overrides"], {"2": {"steps": 32}})

    def test_cinematic_direction_builds_bounded_prompt_terms(self):
        source = plan()
        source["scenes"][0]["direction"] = {
            "shot": "Medium shot",
            "camera": "35mm lens, shallow depth of field",
            "light": "Golden-hour backlight",
            "look": "Natural documentary color",
        }
        clip = core.compile_plan(source)[0]
        self.assertEqual(
            clip["prompt"],
            "cinematic\n\nMedium shot. rain. 35mm lens, shallow depth of field. Golden-hour backlight. Natural documentary color",
        )

        source["scenes"][0]["direction"]["camera"] = "invented camera authority"
        with self.assertRaises(core.PlanError):
            core.compile_plan(source)

    def test_adult_dance_template_is_a_five_minute_full_body_plan(self):
        """The public-safe dance template is an actual paced plan, not a loop label."""
        template = Path(__file__).resolve().parents[1] / "examples" / "alphabeta_dance_template.json"
        plan_data = json.loads(template.read_text(encoding="utf-8"))

        clips = core.compile_plan(plan_data)

        self.assertEqual(plan_data["project"], "AlphaBeta Studios — Full-Body Dance Template")
        self.assertEqual(len(clips), 130)
        self.assertEqual([clip["scene_title"] for clip in clips[::26]], [
            "Arrival", "Foundation", "Travel", "Energy Lift", "Finale",
        ])
        self.assertTrue(all(clip["first_image"] == "@previous" for clip in clips[1:]))
        self.assertTrue(all("full body" in clip["prompt"].lower() for clip in clips))
        self.assertNotIn("norah", json.dumps(plan_data).lower())

    def test_dance_preview_profiles_are_isolated_full_body_four_clip_plans(self):
        self.assertIsNotNone(preview_script, "Headless dance preview launcher has not been implemented")
        plans = preview_script.preview_plans(
            first_image="alpha_original_dance_source_still_v1.png",
            last_image="alpha_original_dance_source_still_v1.png",
        )

        self.assertEqual(set(plans), {"editorial_studio", "color_stage", "low_key_studio"})
        for identifier, plan_data in plans.items():
            with self.subTest(profile=identifier):
                clips = core.compile_plan(plan_data)
                self.assertEqual(len(clips), 4)
                self.assertTrue(all("full body" in clip["prompt"].lower() for clip in clips))
                self.assertTrue(all(clip["first_image"] == "@previous" for clip in clips[1:]))
                self.assertNotIn("norah", json.dumps(plan_data).lower())

    def test_every_clip_requires_a_last_target(self):
        source = plan()
        del source["defaults"]["last_image"]
        with self.assertRaises(core.PlanError):
            core.compile_plan(source)

    def test_blank_scene_targets_inherit_global_target_and_fractional_fps(self):
        source = plan([{}, {"last_image": ""}])
        source["scenes"][0]["last_image"] = ""
        source["defaults"]["fps"] = 0.5
        clips = core.compile_plan(source)
        self.assertEqual([clip["last_image"] for clip in clips], ["end.png", "end.png"])
        self.assertEqual(clips[0]["fps"], 0.5)

    def test_rejects_empty_prompt_and_values_incompatible_with_director_widgets(self):
        cases = []
        source = plan()
        source["global_prompt"] = ""
        source["scenes"][0]["prompt"] = ""
        cases.append(source)
        source = plan()
        source["defaults"]["frames"] = 1
        cases.append(source)
        source = plan()
        source["defaults"]["seed"] = 2 ** 53
        cases.append(source)
        source = plan([{}, {"last_image": "@previous"}])
        cases.append(source)
        for source in cases:
            with self.subTest(source=source), self.assertRaises(core.PlanError):
                core.compile_plan(source)

    def test_previous_cannot_supply_first_clip_endpoint(self):
        for field in ("first_image", "last_image"):
            source = plan()
            source["defaults"][field] = "@previous"
            with self.subTest(field=field), self.assertRaises(core.PlanError):
                core.compile_plan(source)

    def test_rejects_unbounded_and_malformed_plan_values(self):
        sources = []
        for value in (0, 1001, True, "2"):
            sources.append(plan(value))
        source = plan()
        source["scenes"] *= 13
        sources.append(source)
        for name, value in (("frames", 0), ("frames", 9.5), ("fps", 0),
                            ("fps", float("nan")), ("seed", -1), ("seed", True)):
            source = plan()
            source["defaults"][name] = value
            sources.append(source)
        for source in sources:
            with self.subTest(source=source), self.assertRaises(core.PlanError):
                core.compile_plan(source)

    def test_rejects_path_traversal_and_external_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "input"
            root.mkdir()
            for relative in ("../secret.png", "/secret.png", "C:/secret.png", "a\\b.png", "a/../b.png", "a\0.png"):
                with self.subTest(path=relative), self.assertRaises(core.PlanError):
                    core.safe_path(root, relative)
            (root / "outside").symlink_to(Path(directory), target_is_directory=True)
            with self.assertRaises(core.PlanError):
                core.safe_path(root, "outside/secret.png")
            self.assertEqual(core.safe_path(root, "uploads/start.png"), root / "uploads/start.png")

    def test_compilation_rejects_unsafe_image_references(self):
        source = plan()
        source["defaults"]["first_image"] = "../a.png"
        with self.assertRaises(core.PlanError):
            core.compile_plan(source)

    def test_graph_requires_both_endpoint_and_timing_connections(self):
        self.assertEqual(core.validate_workflow(workflow(), "1", "3", "4"), "frames")
        for node, key, replacement in (("2", "last", ["1", 0]), ("2", "frames", 9),
                                       ("2", "positive", "static prompt"), ("2", "seed", 99),
                                       ("4", "frame_rate", 8), ("4", "filename_prefix", "film"),
                                       ("4", "images", ["2", 0]), ("3", "run_id", "preview")):
            graph = workflow()
            graph[node]["inputs"][key] = replacement
            with self.subTest(node=node, key=key), self.assertRaises(core.PlanError):
                core.validate_workflow(graph, "1", "3", "4")

    def test_graph_accepts_duration_control_with_native_video_fps(self):
        self.assertEqual(core.validate_workflow(native_video_workflow(), "1", "3", "4"), "duration")

        for node, key, replacement in (
                ("2", "duration", 5.0625),
                ("6", "fps", 24.0),
                ("4", "filename_prefix", "film")):
            graph = native_video_workflow()
            graph[node]["inputs"][key] = replacement
            with self.subTest(node=node, key=key), self.assertRaises(core.PlanError):
                core.validate_workflow(graph, "1", "3", "4")

    def test_graph_accepts_expanded_h3_with_director_controlled_fps(self):
        self.assertEqual(core.validate_workflow(expanded_h3_workflow(), "1", "3", "4"), "duration")
        graph = expanded_h3_workflow()
        graph["6"]["inputs"]["fps"] = 24.0
        with self.assertRaises(core.PlanError):
            core.validate_workflow(graph, "1", "3", "4")

    def test_graph_rejects_cycles_missing_nodes_and_linked_control_widgets(self):
        cases = []
        graph = workflow()
        graph["2"]["inputs"]["loop"] = ["4", 0]
        cases.append(graph)
        graph = workflow()
        graph["2"]["inputs"]["first"] = ["missing", 0]
        cases.append(graph)
        graph = workflow()
        graph["1"]["inputs"]["seed"] = ["2", 0]
        cases.append(graph)
        for graph in cases:
            with self.subTest(graph=graph), self.assertRaises(core.PlanError):
                core.validate_workflow(graph, "1", "3", "4")

    def test_prompt_isolated_from_workflow_and_resolves_previous_frame(self):
        graph = workflow()
        before = copy.deepcopy(graph)
        clip = core.compile_plan(plan(2))[1]
        clip["input_overrides"] = {"2": {"steps": 31}}
        result = core.build_prompt(graph, clip, "job-123", "attempt-456", "1", "3", "4", "saved/last.png")
        self.assertEqual(result["1"]["inputs"]["first_image"], "saved/last.png")
        self.assertEqual(result["1"]["inputs"]["run_id"], "job-123")
        self.assertEqual(result["1"]["inputs"]["clip_id"], "attempt-456")
        self.assertEqual(result["2"]["inputs"]["steps"], 31)
        self.assertEqual(graph, before)

    def test_overrides_cannot_replace_links_or_control_nodes(self):
        for override in ({"2": {"first": "other.png"}}, {"1": {"seed": 44}},
                         {"3": {"run_id": "another-job"}}, {"unknown": {"steps": 3}},
                         {"2": {"missing": 10}}, {"2": {"steps": ["1", 4]}}):
            source = plan()
            source["scenes"][0]["input_overrides"] = override
            with self.subTest(override=override), self.assertRaises(core.PlanError):
                clip = core.compile_plan(source)[0]
                core.build_prompt(workflow(), clip, "job", "attempt", "1", "3", "4")

    def test_previous_requires_a_real_relative_reference_at_prompt_build(self):
        clip = core.compile_plan(plan(2))[1]
        for previous in (None, "../last.png", "/last.png"):
            with self.subTest(previous=previous), self.assertRaises(core.PlanError):
                core.build_prompt(workflow(), clip, "job", "attempt", "1", "3", "4", previous)

    def test_atomic_json_preserves_a_complete_readable_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job" / "job.json"
            core.atomic_json(path, {"status": "running", "clip": 1})
            core.atomic_json(path, {"status": "completed", "clip": 2})
            self.assertEqual(core.read_json(path), {"status": "completed", "clip": 2})
            self.assertEqual([p.name for p in path.parent.iterdir()], ["job.json"])
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(core.PlanError):
                core.read_json(path)


if __name__ == "__main__":
    unittest.main()
