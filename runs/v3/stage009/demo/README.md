# Stage009 demo — five panels

`stage9_demo.mp4` (1280x720, ~3 min) is built only from recorded data of the frozen
`formal_v2` case; no new generation, scene, initial state or control tuning.

| panel | content | source |
| --- | --- | --- |
| 1 SEEING | reconstructed RGB-D at the common S0; shared V feeds both arms | truth_v2/observation |
| 2 SIX IMAGINATIONS | six registered Lux3D candidates (geometry only in this render) | registered/task_*/world.stl |
| 3 TRIALS | BODY_CLEARANCE rehearsal per candidate, x vs t from the real records | formal_v2/record_full_* |
| 4 MAJORITY | FULL votes (BODY 5/6, D2 2/6 -> BODY) and OBS votes (BODY 1) | formal_v2 decisions |
| 5 REVEAL | textured 3D replay of the truth execution, real qpos, no edits | exec_full/TRUTH_FULL |
| skill clip | stance vs +6 cm body lift comparison, separate and labelled | Stage006 reference scene |

Honest notes:
- **Both FULL and OBS choose BODY_CLEARANCE and both executions pass** (114.24 s / 114.40 s,
  zero chassis contacts, reached 2.6 m). The edit does not claim "imagination failed".
- The skill comparison clip is from the earlier reference scene, not from this candidate case;
  it is labelled separately.
- Candidate tiles show registered geometry without re-rendered GLB textures; the textured
  replay uses the truth scanned rock.
- Registration fit is weak (mask IoU 0.49-0.56); one scene, one S0; no generalisation claim.
