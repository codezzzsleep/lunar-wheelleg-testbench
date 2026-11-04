# Stage008 runnable pack v2 (offline, no API, no keys)

## Boot test (3 s)

```bash
python run_offline.py sim --seconds 3
python run_offline.py replay --seconds 3 --out out/replay.mp4
```

## Full cached case (offline)

```bash
python run_case_offline.py --out out/case
```

This reads the cached FULL/OBS matrices, re-aggregates with the majority rule, checks that
the chosen actions match the cached decisions, restores the cached common S0 in the single
truth scene, executes the FULL and OBS chosen plans there, and writes `out/case/offline_case.json`.
It does not call any API.

## Data included

- `data/truth/`: the single truth scene (spec, common S0 snapshot, collision asset, occupancy,
  manifest with the frozen truth SHA).
- `data/fusion/`: shared V, per-candidate `occ_full` (FULL = V | (P & U)), plans.
- `data/decisions/`: cached matrices and decision files for FULL and OBS.
- `data/exec/`: recorded truth executions (50 Hz) used for replay.

## Provenance

- **Truth reference**: complete geometry (real scanned rock + walls) used for every execution.
- **Generated**: six Lux3D G1-Turbo GLBs, registered with the existing observation ICP entry.
- **Reconstructed observation**: the shared V comes from a re-rendered RGB-D at the common S0,
  not an original field capture.
- **Old diagnostic**: Stage007 candidate numbers are a raw geometry-adaptation diagnostic.
