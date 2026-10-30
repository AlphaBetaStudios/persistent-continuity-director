# Initial scorer calibration

Status: local, provisional. This profile is evidence for the included full-body
demo only. It is not a general identity threshold.

## Evidence set

- Positive domain: the accepted 15-second full-body source and its 30-second
  continuation, sampled at matching motion times.
- Negative controls: two separately generated fictional adult portraits with
  visibly different identities, stored under `calibration_assets/`.
- Scorer: local InsightFace `buffalo_l` embeddings through
  `continuity_scorer.py`.

## Observed separation

The 30-second continuation's source-domain frame similarities ranged from
0.459 to 0.846. The accepted source's first-frame face scored -0.036 and 0.023
against the two negative controls. A provisional source-domain identity floor
of **0.30** separates these samples with margin.

The weakest measured boundary similarity in the 30-second continuation was
0.307. A provisional boundary floor of **0.30** is therefore suitable only for
flagging obvious seam failures during the next iteration; it needs more scenes,
poses, and deliberate failure cases before it may auto-accept a submission.

## Current rule

The Director may use this profile to rank and reject clearly bad candidate
clips. A human visual check is still required for full-body framing, motion, and
final submission qualification.

## Framing evidence

The local pose helper was checked against the accepted full-body reference and
against samples from the earlier rejected close-crop run. It uses a visible
nose plus at least three of four heel/foot landmarks. That accommodates one
fast-motion foot occlusion but rejects frames where the lower body is absent.
The helper lives in a separate local environment and does not alter ComfyUI's
own Python installation.

## Deployment boundary

The combined H3 face-and-pose gate has passed an isolated known-good frame
check. It remains opt-in and has not been activated in the live ComfyUI service.
The next qualification is a gated render using a copied workflow, followed by
manual review of the produced motion and gate report.
