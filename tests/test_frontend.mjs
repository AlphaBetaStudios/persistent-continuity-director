import test from "node:test";
import assert from "node:assert/strict";
import {
  createDefaultPlan, parsePlan, serializePlan, inspectPlan,
  sceneAdvancedJSON, editScene, buildSubmission, workflowChoices,
  uploadedImagePath, imagePreviewRoute, jobRoute, formatDuration, activeJobsRemain, serializeDraftForNode,
} from "../web/director_data.js";
import { createDirectorClient, uniqueUploadToken } from "../web/director_client.js";

function readyPlan() {
  return {
    version: 1, project: "Film", global_prompt: "Consistent light", negative_prompt: "flicker",
    defaults: { first_image: "start.png", last_image: "end.png", frames: 81, fps: 16, seed: 1 },
    scenes: [{ id: "one", title: "Arrival", prompt: "A woman enters", clips: 2 }],
  };
}

test("default draft expands to sixty clips but refuses missing prompts and endpoints", () => {
  const plan = createDefaultPlan();
  assert.equal(plan.scenes.length, 10);
  const report = inspectPlan(plan);
  assert.equal(report.totalClips, 60);
  assert.equal(report.estimatedSeconds, 303.75);
  assert.ok(report.errors.some((error) => /prompt/i.test(error)));
  assert.ok(report.errors.some((error) => /first image/i.test(error)));
  assert.ok(report.errors.some((error) => /last image/i.test(error)));
});

test("import and export retain per-clip prompts, targets and scalar model overrides", () => {
  const plan = readyPlan();
  plan.custom_note = "Keep this annotation";
  plan.scenes[0].input_overrides = { "88": { cfg: 4.5, enabled: true } };
  plan.scenes[0].clips = [
    { prompt: "She turns", last_image: "turn.png", frames: 49, seed: 14 },
    { prompt: "She pauses", first_image: "@previous", input_overrides: { "88": { shift: 3 } } },
  ];
  const serialized = serializePlan(plan);
  const parsed = parsePlan(serialized);
  assert.deepEqual(parsed, plan);
  parsed.scenes[0].clips[0].prompt = "Changed draft";
  assert.equal(plan.scenes[0].clips[0].prompt, "She turns");
});

test("malformed JSON and unsupported schema versions fail clearly", () => {
  assert.throws(() => parsePlan("{"), /JSON/i);
  assert.throws(() => parsePlan('{"version":2,"scenes":[]}'), /version/i);
  assert.throws(() => parsePlan("[]"), /object/i);
});

test("preflight resolves scene starts only on their first clip, then uses the actual previous frame", () => {
  const plan = readyPlan();
  plan.scenes.push({ id: "two", title: "Exit", prompt: "She leaves", first_image: "door.png", last_image: "outside.png", clips: 2 });
  const report = inspectPlan(plan);
  assert.deepEqual(report.errors, []);
  assert.deepEqual(report.clips.map((clip) => [clip.first_image, clip.last_image]), [
    ["start.png", "end.png"], ["@previous", "end.png"],
    ["door.png", "outside.png"], ["@previous", "outside.png"],
  ]);
  assert.equal(report.estimatedSeconds, 20.25);
});

test("clip-specific settings override inherited endpoints and contribute to duration", () => {
  const plan = readyPlan();
  plan.scenes[0].frames = 33;
  plan.scenes[0].clips = [
    { prompt: "At the door", first_image: "detail.png", last_image: "door.png", fps: 24, frames: 49 },
    { prompt: "Inside", fps: 12 },
  ];
  const report = inspectPlan(plan);
  assert.deepEqual(report.errors, []);
  assert.equal(report.clips[0].prompt, "Consistent light\n\nA woman enters\n\nAt the door");
  assert.equal(report.clips[0].first_image, "detail.png");
  assert.equal(report.clips[0].last_image, "door.png");
  assert.equal(report.estimatedSeconds, 49 / 24 + 33 / 12);
});

test("cinematic direction is preserved by basic edits and validated before submission", () => {
  const plan = readyPlan();
  plan.scenes[0].direction = {
    shot: "Medium shot",
    camera: "35mm lens, shallow depth of field",
    light: "Golden-hour backlight",
    look: "Natural documentary color",
  };
  let report = inspectPlan(plan);
  assert.deepEqual(report.errors, []);
  assert.equal(report.clips[0].prompt, "Consistent light\n\nMedium shot. A woman enters. 35mm lens, shallow depth of field. Golden-hour backlight. Natural documentary color");

  const updated = editScene(plan.scenes[0], {
    title: "Arrival", prompt: "A woman enters", first_image: "", last_image: "",
    clipCount: 2, direction: plan.scenes[0].direction, advancedJSON: sceneAdvancedJSON(plan.scenes[0]),
  });
  assert.deepEqual(updated.direction, plan.scenes[0].direction);

  plan.scenes[0].direction.camera = "Camera claim outside the approved choices";
  report = inspectPlan(plan);
  assert.ok(report.errors.some((error) => /camera/i.test(error)));
});

test("preflight requires a combined prompt for every clip", () => {
  const plan = readyPlan();
  plan.global_prompt = "  ";
  plan.scenes[0].prompt = "";
  plan.scenes[0].clips = [{ prompt: "A valid beat" }, { prompt: " " }];
  const report = inspectPlan(plan);
  assert.equal(report.errors.filter((error) => /prompt/i.test(error)).length, 1);
  assert.match(report.errors.find((error) => /prompt/i.test(error)), /clip 2/i);
});

test("preflight enforces one to twelve scenes and at most one thousand clips", () => {
  const empty = readyPlan();
  empty.scenes = [];
  assert.ok(inspectPlan(empty).errors.some((error) => /1.*12.*scene/i.test(error)));
  const tooManyScenes = readyPlan();
  tooManyScenes.scenes = Array.from({ length: 13 }, () => ({ prompt: "A beat", clips: 1 }));
  assert.ok(inspectPlan(tooManyScenes).errors.some((error) => /1.*12.*scene/i.test(error)));
  const tooManyClips = readyPlan();
  tooManyClips.scenes[0].clips = 1001;
  assert.ok(inspectPlan(tooManyClips).errors.some((error) => /1000/i.test(error)));
  const single = createDefaultPlan(1);
  assert.equal(single.scenes.length, 1);
});

test("preflight rejects unsafe or missing endpoint paths before queueing", () => {
  for (const path of ["../outside.png", "/tmp/a.png", "C:\\a.png", "https://example.com/a.png", "folder/../a.png", "a\u0000.png"]) {
    const plan = readyPlan();
    plan.defaults.last_image = path;
    assert.ok(inspectPlan(plan).errors.length > 0, path);
  }
  const plan = readyPlan();
  plan.defaults.first_image = "@previous";
  assert.ok(inspectPlan(plan).errors.some((error) => /previous/i.test(error)));
  plan.defaults.first_image = "start.png";
  plan.defaults.last_image = "@previous";
  assert.ok(inspectPlan(plan).errors.some((error) => /last image/i.test(error)));
});

test("preflight enforces frame, fps and safe integer seed bounds", () => {
  for (const [field, bad] of [["frames", 1], ["frames", 4098], ["frames", 2.5], ["fps", 0], ["fps", 0.001], ["fps", 241], ["fps", Infinity], ["seed", -1], ["seed", Number.MAX_SAFE_INTEGER + 1]]) {
    const plan = readyPlan();
    plan.defaults[field] = bad;
    assert.ok(inspectPlan(plan).errors.some((error) => error.includes(field)), `${field}=${bad}`);
  }
  const plan = readyPlan();
  plan.defaults.frames = 2;
  plan.defaults.fps = 240;
  plan.defaults.seed = Number.MAX_SAFE_INTEGER;
  assert.deepEqual(inspectPlan(plan).errors, []);
  plan.defaults.fps = 0.01;
  assert.deepEqual(inspectPlan(plan).errors, []);
});

test("model input overrides accept scalar inputs and reject link-shaped arrays", () => {
  const plan = readyPlan();
  plan.scenes[0].input_overrides = { "42": { shift: 3.25, mode: "normal", enabled: true, optional: null } };
  assert.deepEqual(inspectPlan(plan).errors, []);
  plan.scenes[0].input_overrides["42"].images = ["7", 0];
  assert.ok(inspectPlan(plan).errors.some((error) => /scalar/i.test(error)));
});

test("basic scene edits preserve explicit per-clip plans and model overrides", () => {
  const source = readyPlan().scenes[0];
  source.frames = 49;
  source.input_overrides = { "18": { cfg: 5 } };
  source.clips = [{ prompt: "A new beat", last_image: "beat.png" }, { prompt: "Another beat" }];
  const updated = editScene(source, {
    title: "Changed title", prompt: "Changed prompt", first_image: "", last_image: "target.png",
    clipCount: 99, advancedJSON: sceneAdvancedJSON(source),
  });
  assert.equal(updated.id, "one");
  assert.equal(updated.title, "Changed title");
  assert.equal(updated.last_image, "target.png");
  assert.deepEqual(updated.clips, [{ prompt: "A new beat", last_image: "beat.png" }, { prompt: "Another beat" }]);
  assert.deepEqual(updated.input_overrides, { "18": { cfg: 5 } });
  assert.equal(updated.frames, 49);
  assert.equal(source.title, "Arrival");
});

test("clearing advanced JSON removes overrides and restores editable repeat count", () => {
  const source = { ...readyPlan().scenes[0], frames: 49, clips: [{ prompt: "A beat" }], input_overrides: { "18": { cfg: 5 } } };
  const updated = editScene(source, {
    title: "Scene", prompt: "A beat", first_image: "", last_image: "", clipCount: 3, advancedJSON: "{}",
  });
  assert.equal(updated.clips, 3);
  assert.equal(Object.hasOwn(updated, "input_overrides"), false);
  assert.equal(Object.hasOwn(updated, "frames"), false);
  assert.equal(Object.hasOwn(updated, "first_image"), false);
});

test("invalid advanced JSON and attempts to redefine basic scene fields are rejected", () => {
  const edits = { title: "Scene", prompt: "A beat", clipCount: 2, advancedJSON: "{" };
  assert.throws(() => editScene(readyPlan().scenes[0], edits), /JSON/i);
  assert.throws(() => editScene(readyPlan().scenes[0], { ...edits, advancedJSON: '{"title":"Hidden replacement"}' }), /title/i);
  assert.throws(() => editScene(readyPlan().scenes[0], { ...edits, advancedJSON: '{"clips":5}' }), /array/i);
});

test("submission freezes the API output graph and draft into detached data", () => {
  const plan = readyPlan();
  const graph = { output: { "7": { class_type: "AlphaSceneDirector", inputs: {} }, "9": { class_type: "SaveVideo", inputs: { fps: 16 } } }, workflow: { nodes: [{ id: 7 }], links: [] } };
  const request = buildSubmission({ plan, graph, directorId: 7, checkpointId: "8", videoOutputId: 9 });
  assert.deepEqual(request, { plan, workflow: graph.output, director_id: "7", checkpoint_id: "8", video_output_id: "9" });
  graph.output["9"].inputs.fps = 24;
  plan.scenes[0].prompt = "Edited after submission";
  assert.equal(request.workflow["9"].inputs.fps, 16);
  assert.equal(request.plan.scenes[0].prompt, "A woman enters");
  assert.equal(Object.hasOwn(request.workflow, "nodes"), false);
});

test("submission rejects incomplete plans, missing selectors and UI-only workflow objects", () => {
  const options = { plan: readyPlan(), graph: { output: { "1": { class_type: "AlphaSceneDirector", inputs: {} } } }, directorId: 1, checkpointId: 2, videoOutputId: 3 };
  assert.throws(() => buildSubmission({ ...options, plan: createDefaultPlan() }), /prompt|image/i);
  assert.throws(() => buildSubmission({ ...options, checkpointId: "" }), /checkpoint/i);
  assert.throws(() => buildSubmission({ ...options, videoOutputId: "" }), /video/i);
  assert.throws(() => buildSubmission({ ...options, graph: { workflow: { nodes: [] } } }), /API.*graph|output/i);
});

test("workflow selectors expose only explicit checkpoint and recognized video nodes", () => {
  const choices = workflowChoices({
    "3": { class_type: "AlphaSceneCheckpoint", _meta: { title: "Frames receipt" }, inputs: {} },
    "4": { class_type: "SaveVideo", inputs: {} },
    "5": { class_type: "VHS_VideoCombine", inputs: {} },
    "6": { class_type: "SomeCustomVideoOutput", inputs: {} },
  });
  assert.deepEqual(choices.checkpoints, [{ id: "3", title: "Frames receipt", type: "AlphaSceneCheckpoint" }]);
  assert.deepEqual(choices.videos.map((choice) => choice.id), ["4", "5"]);
});

test("upload responses become safe relative input paths and never accept output files", () => {
  assert.equal(uploadedImagePath({ name: "A frame.png", subfolder: "alpha_scene_director/uploads/unique", type: "input" }), "alpha_scene_director/uploads/unique/A frame.png");
  assert.equal(uploadedImagePath({ name: "a.png", subfolder: "", type: "input" }), "a.png");
  assert.throws(() => uploadedImagePath({ name: "../escape.png", type: "input" }), /path|filename/i);
  assert.throws(() => uploadedImagePath({ name: "frame.png", type: "output" }), /input/i);
});

test("thumbnail routes encode image names without allowing a remote URL", () => {
  assert.equal(imagePreviewRoute("alpha_scene_director/uploads/a frame#1.png"), "/view?filename=a+frame%231.png&subfolder=alpha_scene_director%2Fuploads&type=input");
  assert.equal(imagePreviewRoute("@previous"), null);
  assert.equal(imagePreviewRoute(""), null);
  assert.throws(() => imagePreviewRoute("https://example.com/image.png"), /path/i);
});

test("job IDs stay within relative server routes", () => {
  assert.equal(jobRoute(), "/alpha_scene_director/jobs");
  assert.equal(jobRoute("abc-123", "pause"), "/alpha_scene_director/jobs/abc-123/pause");
  assert.throws(() => jobRoute("../../prompt"), /job ID/i);
  assert.throws(() => jobRoute("abc", "delete"), /action/i);
});

test("film duration rounds summed frame durations for a readable estimate", () => {
  assert.equal(formatDuration(303.75), "5:04");
  assert.equal(formatDuration(3661), "1:01:01");
  assert.equal(formatDuration(null), "—");
});

test("client uploads distinct input subfolders without overwriting existing images", async () => {
  const calls = [];
  const client = createDirectorClient(async (route, options) => {
    calls.push({ route, options });
    return Response.json({ name: "frame.png", subfolder: options.body.get("subfolder"), type: "input" });
  });
  const file = new File(["image bytes"], "frame.png", { type: "image/png" });
  const first = await client.upload(file);
  const second = await client.upload(file);
  assert.notEqual(first, second);
  assert.match(first, /^alpha_scene_director\/uploads\/[a-z0-9-]+\/frame\.png$/);
  assert.equal(calls[0].route, "/upload/image");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.body.get("type"), "input");
  assert.equal(calls[0].options.body.get("overwrite"), "false");
  assert.equal(calls[0].options.body.get("image").name, "frame.png");
});

test("client uses documented relative job routes and JSON request bodies", async () => {
  const requests = [];
  const client = createDirectorClient(async (route, options) => {
    requests.push({ route, options });
    return Response.json({ job_id: "job-123", status: "running", completed: 0, total: 2, current: null, error: null, estimated_seconds: null, clips: [] });
  });
  const request = { plan: readyPlan(), workflow: { "7": { inputs: {}, class_type: "AlphaSceneDirector" } }, director_id: "7", checkpoint_id: "8", video_output_id: "9" };
  await client.validate(request);
  await client.start(request);
  await client.get("job-123");
  await client.pause("job-123");
  await client.resume("job-123");
  assert.deepEqual(requests.map((entry) => entry.route), [
    "/alpha_scene_director/validate", "/alpha_scene_director/jobs", "/alpha_scene_director/jobs/job-123",
    "/alpha_scene_director/jobs/job-123/pause", "/alpha_scene_director/jobs/job-123/resume",
  ]);
  assert.deepEqual(JSON.parse(requests[1].options.body), request);
  assert.equal(requests[1].options.headers["Content-Type"], "application/json");
  assert.equal(requests[2].options?.method || "GET", "GET");
  assert.equal(requests[3].options.method, "POST");
});

test("client does not retry an uncertain Start and exposes server validation errors", async () => {
  let starts = 0;
  const uncertain = createDirectorClient(async () => {
    starts += 1;
    throw new Error("Connection lost after acceptance");
  });
  await assert.rejects(uncertain.start({}), /Connection lost/);
  assert.equal(starts, 1);
  const invalid = createDirectorClient(async () => Response.json({ error: "Checkpoint is not connected" }, { status: 400 }));
  await assert.rejects(invalid.validate({}), /Checkpoint is not connected/);
});

test("client lists persisted jobs and fetches previews through ComfyUI's image route", async () => {
  const calls = [];
  const client = createDirectorClient(async (route) => {
    calls.push(route);
    if (route.startsWith("/view?")) return new Response(new Blob(["image bytes"], { type: "image/png" }));
    return Response.json([{ job_id: "saved-id", status: "paused", completed: 1, total: 2, current: null, error: null, estimated_seconds: null, clips: [] }]);
  });
  assert.equal((await client.list())[0].job_id, "saved-id");
  const preview = await client.preview("shots/frame.png");
  assert.equal(await preview.text(), "image bytes");
  assert.deepEqual(calls, ["/alpha_scene_director/jobs", "/view?filename=frame.png&subfolder=shots&type=input"]);
});

test("unique upload IDs work on HTTP LAN origins without crypto.randomUUID", () => {
  const cryptoSource = { getRandomValues(bytes) { for (let index = 0; index < bytes.length; index++) bytes[index] = index; return bytes; } };
  assert.equal(uniqueUploadToken(cryptoSource), "000102030405060708090a0b0c0d0e0f");
});

test("a completed polling result clears the stale active status in the saved-job list", () => {
  assert.equal(activeJobsRemain([{ job_id: "a", status: "running" }], { job_id: "a", status: "completed" }), false);
  assert.equal(activeJobsRemain([{ job_id: "a", status: "running" }], { job_id: "b", status: "paused" }), true);
  assert.equal(activeJobsRemain([], { job_id: "b", status: "running" }), true);
});

test("an unreadable existing node plan is preserved until an explicit Save draft or import", () => {
  const draft = readyPlan();
  assert.equal(serializeDraftForNode(draft, { protectExisting: true }), null);
  const saved = serializeDraftForNode(draft, { protectExisting: true, explicitSave: true });
  assert.equal(JSON.parse(saved).scenes[0].prompt, "A woman enters");
});
