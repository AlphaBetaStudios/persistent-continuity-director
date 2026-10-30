# Continuity gate design

Status: proposed implementation contract. This document does not claim that automatic drift repair is complete.

## Purpose

The Director must decide whether a generated clip is good enough to become the source frame for the next clip. A successful ComfyUI queue result alone is not acceptance.

## Inputs

For each rendered clip, the gate receives:

- the decoded first and last frames saved by `AlphaSceneCheckpoint`;
- the configured character reference image(s);
- the previous accepted clip's last frame, when the clip continues a scene;
- the generated video artifact and its frame count.

## First implementation

The first implementation should produce a persisted report with these independent checks:

1. **Artifact integrity** — receipt images and encoded video exist, decode, and match expected dimensions.
2. **Boundary continuity** — compare the first generated frame against the previous accepted final frame after a small alignment tolerance.
3. **Face presence** — a detector must find one intended face in sampled frames, or the clip is flagged for manual review rather than silently accepted.
4. **Reference similarity** — an embedding scorer compares sampled detected faces against the selected face reference. Thresholds are project-configurable and must be calibrated from held-out renders, not guessed.
5. **Full-body framing** — for a full-body job, head-to-shoes framing must remain present in sampled frames. A close-up is not acceptable merely because the face still matches.
6. **Visual degradation** — flag abnormal blur or exposure changes relative to the preceding accepted frame; this is a warning until calibrated.

`continuity_scorer.py` now provides the local face-embedding adapter used to
produce reference and boundary measurements. Thresholds still require a
calibration set; the scorer itself never turns a raw similarity number into an
acceptance decision.

`measured_continuity_gate.py` now connects saved checkpoint images to the
deterministic policy. It is intentionally not enabled by default: an actual
full-body evidence callback must be present before a clip can be automatically
accepted. Without one, the gate fails closed to manual review.

The server accepts a gate only when the deployment explicitly supplies one.
That keeps normal installs in manual-review mode until their score profile,
full-body detector, and model licenses have been independently qualified.

The provided pose helper checks for the nose plus at least three of the four
heel/foot landmarks with confidence and within-frame bounds. Allowing one
lower-landmark miss prevents a fast-motion occlusion from looking like a crop;
two missing feet still fail. It runs in a separate local Python environment,
never inside ComfyUI's shared Python environment. This is a framing signal,
not an identity signal; the face scorer remains independent.

## Source-domain identity calibration

For full-body motion, a tiny face in a generated frame can score poorly against
a high-resolution still even when the performer is visually stable. The scorer
therefore records both measurements:

- **still-reference similarity** — useful for detecting a clear identity swap;
- **source-domain similarity** — candidate frames compared with the accepted
  source video at the matching motion time, useful for measuring continuity at
  the same resolution and pose range.

Automatic acceptance requires a calibrated positive/negative set for the
chosen model and camera distance. Until then, the Director preserves scores and
uses manual review rather than inventing a threshold.

The report records raw measurements, thresholds, score version, and a decision: `accepted`, `repair_required`, or `manual_review`.

## Repair policy

- A rejected clip never replaces the prior accepted checkpoint.
- The repair attempt has a new attempt ID and preserves the original artifact.
- A repair can change only declared repair controls: reference strength, face reference, seed, prompt correction, or a face-only repair stage.
- A repair is re-scored before acceptance.
- After a bounded number of failed attempts, the job pauses for review. It never loops forever.

## Qualification target

For the submission demo, show two connected original-motion clips where the gate detects a deliberately weakened result, preserves the good previous clip, repairs or reruns only the weak clip, and resumes the timeline with receipts.
