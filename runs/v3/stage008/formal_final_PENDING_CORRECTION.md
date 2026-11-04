# formal_final.json — SUPERSEDED / PENDING CORRECTION

**Status: SUPERSEDED by `runs/v3/stage008/formal_v2/` (Stage009 release, baseline 8c1054ac5).**

The numbers in `formal_final.json` are kept unchanged but must not be used as the formal
FULL/OBS result. Its headline "decision difference 5/7" is **retracted**:

- the FULL arm's truth execution ran on each candidate's own fused scene (the truth defaulted
  to the candidate) instead of one fixed real execution scene;
- the OBS arm's truth execution was only partially corrected later, so the comparison mixed
  per-candidate rehearsal geometry with per-arm truth scenes.

Authoritative corrected run: `runs/v3/stage008/formal_v2/result.json` and
`formal_table_v2.json` — one truth scene (sha 0f8706f4...), one common S0 (8c287b84...),
truth execution on that scene. There, FULL and OBS both choose BODY_CLEARANCE and both pass;
no decision or outcome difference was found in this single case.

Naming used from here on:
- **FULL / complete-geometry reference** = V ∪ (P ∩ U)
- **OBS_ONLY** = V
- **truth reference** = the fixed real execution scene (real scanned rock + walls + ground)
