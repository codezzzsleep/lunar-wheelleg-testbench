# Pack asset list (Stage009 release)

| path | content | provenance |
| --- | --- | --- |
| `data/truth/scene_spec.json`, `truth_coll/`, `truth_occ.npz`, `truth_manifest.json` | single truth scene (real scanned rock + walls + ground), frozen sha 0f8706f4... | truth reference |
| `data/truth/state_snapshot.json` | common S0, sha 8c287b84... | truth reference |
| `data/fusion/V.npz`, `fusion_summary.json` | shared V, per-candidate FULL occ, plans | reconstructed observation + generated |
| `data/decisions/cache/*.jsonl` + `cache_identity.json` | identity-bound matrices (S0/geometry/plan/protocol/applicability) | rehearsal records |
| `data/decisions/decision_FULL.json`, `decision_OBS.json` | cached decisions (sha recorded) | decision files |
| `data/exec/full_record/TRUTH_FULL`, `obs_record/TRUTH_OBS` | recorded 50 Hz truth executions | truth execution |
| `scripts/`, `configs/`, `plans/` | code and protocol | repo snapshot |
| `vendor/.../go2w` | robot model | vendored |
| `run_offline.py` | 3 s smoke: sim (raise) + replay | offline |
| `run_case_offline.py` | full cached case: identity caches -> aggregate -> decision manifest -> truth executions | offline |
| `traceability.json` | external links to index/decision/truth/plan shas, post-hoc flags | Stage009 |
| `cache_verification.json` | first vs cached aggregation equality, mismatch refusal | Stage009 |

Full originals (six GLBs, candidate assets, old packs) are on the cnb archive branch
`archive/stage008` (see the release report for commit ids); they are not in this pack.
