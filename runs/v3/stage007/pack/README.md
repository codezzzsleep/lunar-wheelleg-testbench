# Stage007 pack — narrow-passage BODY_CLEARANCE, reference scene vs Lux3D candidates

## What this shows

A narrow passage: a 0.30 m CC0 rock (moon_rock_05) at (1.0, 0) between two background walls
(y = ±0.55, inner faces ±0.30 m). The task endpoint is 2.6 m, budget 120 s, stable exit required.

- Reference scene, truth geometry: only BODY_CLEARANCE passes cleanly (30.06 s, 0 chassis
  contacts). All wheel actions fail because the walls remove the detour. Watch
  `reference_body_vs_stance.mp4`: top = stance (chassis contact), bottom = +6 cm body lift;
  raise visible around 10 s, lowered and past the rock around 28 s. The stance side is frozen
  at its real completion after 7.9 s.
- Six real G1-Turbo candidates were generated from the textured target image of this layout
  and screened with FULL (complete geometry reference) and OBS (front 0.10 m only) arms.
  None reproduces the clean BODY pass: the body run stalls in `drive_to_lower` for 120 s on
  every candidate in both arms, with zero chassis contacts (the wheels are blocked by the
  generated rock, not the belly).

## Files

| file | content |
| --- | --- |
| `reference_body_vs_stance.mp4` | reference scene replay, stance vs BODY_CLEARANCE, 30.07 s |
| `textured_scene.png` | textured render of the frozen layout (rock + walls) |
| `textured_target.png` | textured target rock, the Lux3D input |
| `summary.json` | layout, candidates, boundary conclusion, timing split |
| `candidate_table.json` | per-candidate FULL/OBS rows |

## Timing (kept separate)

- API: ~2–5 min submit-to-download per task (wall clock); the batch ledger has no per-task
  timestamps, so no authoritative API seconds are claimed.
- Screening wall time: ~8 min on the 8-core sandbox for 6 candidates × 2 arms × 3 actions.
- Physics time: BODY runs are 120.022 s each on 12/12 arms (all stalled); wheel rows 8–60 s.

## Honest limits

- The reference rock is a narrow geometric window (≈0.28 m wide at wheel height, 0.30 m tall).
  The generated candidates are wider at wheel height, so the wheels block before body lift can
  matter; this is a candidate/geometry transfer failure, not a new skill result.
- The replay shows the real collision representation (box union), not the textured mesh; the
  textured renders are separate stills at the same pose.
- Project benefit of 3D imagination remains NOT_ESTABLISHED.

## Reproduce / commits

- `07ca39200` frozen layout + reference matrix
- `0b1ea1096` textured renders + six Lux3D candidates
- key runs: `runs/v3/stage007/layout2`, `runs/v3/stage007/lux3d`, `runs/v3/stage007/cand_small`,
  `runs/v3/stage006/replay_fix`, `runs/v3/stage006/fix`
