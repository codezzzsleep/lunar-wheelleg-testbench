# formal_final.json — PENDING CORRECTION (superseded by formal_v2)

The numbers in `formal_final.json` are kept unchanged but must not be used as the formal
FULL/OBS result:

- the FULL arm's truth execution was run on each candidate's own fused scene (`--truth-fusion`
  defaulted to the candidate), instead of one fixed real execution scene;
- the OBS arm's truth execution was also only corrected in a later pass, and the comparison
  therefore mixed per-candidate rehearsal geometry with per-arm truth scenes.

Corrected run: `runs/v3/stage008/formal_v2/result.json` + `formal_table_v2.json`
(single truth scene sha 0f8706f4..., common S0 8c287b84..., truth execution on that scene).
