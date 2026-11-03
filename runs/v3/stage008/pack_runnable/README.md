# Stage008 runnable pack (offline, no API, no keys)

## What runs here

- `run_offline.py sim` — builds the cached narrow-passage scene from the collision asset and
  raises the body by 6 cm with per-leg 3-joint control for N seconds; prints base/chassis
  heights. No network, no API.
- `run_offline.py replay` — renders an MP4 from the cached 50 Hz trajectory of a real
  `BODY_CLEARANCE` run on that scene. The trajectory is the recorded truth run, not
  re-simulated.

## Commands

```bash
python run_offline.py sim --seconds 3
python run_offline.py replay --seconds 5 --out out/replay.mp4
```

Requires Python 3.12, numpy, mujoco 3.17, trimesh, Pillow; ffmpeg for replay.
The robot model is vendored under `vendor/unitree_mujoco/unitree_robots/go2w`.

## Provenance labels

- **Reconstructed observation**: the shared V in the formal chain was re-rendered from the
  frozen layout at the fixed S0/camera; it is not an original field capture.
- **Generated candidates**: six Lux3D G1-Turbo GLBs, created earlier; this pack contains
  cached geometry only, never calls the API.
- **Truth reference**: the complete-geometry scene used for independent execution.
- **Old diagnostic**: `stage7_candidates` numbers are a raw geometry-adaptation diagnostic,
  not a formal FULL/OBS comparison.

## Scene

Narrow passage: 0.30 m target rock at (1.0, 0) between background walls at y = +/-0.55
(inner faces +/-0.30 m). Task endpoint 2.6 m, budget 120 s, nominal soil. The cached
collision asset is the same one used in the recorded run.
