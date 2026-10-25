"""
重演一个 trial：用**和考试完全相同的控制路径**重新跑一遍，同时抓帧出 GIF。

  python scripts/replay.py --run runs/canonical --trial <trial_id> [--fps 30]

重要：这是**重演(re-simulation)**，不是轨迹回放。
     因此脚本会校验重演出来的关键指标是否与记录一致，不一致就明确报错，
     不能把近似结果当成原轨迹。

需要软件渲染：
  export LD_LIBRARY_PATH=<osmesa 所在目录>:$LD_LIBRARY_PATH
  export MUJOCO_GL=osmesa
"""
import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
os.environ.setdefault('MUJOCO_GL', 'osmesa')

import numpy as np
import mujoco
from PIL import Image

import exam
import runio

ROOT = pathlib.Path(__file__).resolve().parent.parent
W, H = 960, 540
TOL = {'final_x': 5e-3, 'max_tilt_deg': 0.5}


class Recorder:
    def __init__(self, out_dir, fps):
        self.out = pathlib.Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.fps = fps
        self.frames = []

    def __call__(self, t, m, d):
        if not hasattr(self, '_r'):
            m.vis.global_.offwidth = W
            m.vis.global_.offheight = H
            self._r = mujoco.Renderer(m, H, W)
            self._cam = mujoco.MjvCamera()
            mujoco.mjv_defaultCamera(self._cam)
            self._cam.distance, self._cam.elevation, self._cam.azimuth = 3.2, -18, 105
        self._cam.lookat[:] = [float(d.qpos[0]) + 0.6, 0.35, 0.0]
        self._r.update_scene(d, camera=self._cam)
        self.frames.append(np.ascontiguousarray(self._r.render()))

    def finish(self, gif_path, thumb=480):
        if not self.frames:
            return None
        ims = [Image.fromarray(f).resize((thumb, int(thumb * H / W))) for f in self.frames]
        ims[0].save(gif_path, save_all=True, append_images=ims[1:],
                    duration=int(1000 / max(1, self.fps / 2)), loop=0)
        return gif_path


def find_trial(run_dir, trial_id):
    rows, _ = runio.load_results(pathlib.Path(run_dir) / 'results.jsonl')
    for r in rows:
        if r.get('trial_id') == trial_id:
            return r
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--trial', required=True)
    ap.add_argument('--fps', type=int, default=30)
    a = ap.parse_args()

    rec = find_trial(a.run, a.trial)
    if rec is None:
        raise SystemExit(f'在 {a.run}/results.jsonl 里找不到 trial {a.trial}')
    if rec.get('status') != 'ok':
        raise SystemExit(f'该 trial 状态为 {rec.get("status")}，无法重演')

    man_path = pathlib.Path(a.run) / 'manifest.json'
    if not man_path.exists():
        raise SystemExit(f'拒绝重演：{a.run} 下没有 manifest.json，无法校验身份')
    manifest = json.loads(man_path.read_text())
    ctx = manifest.get('context') or {}

    # ---- 身份校验：源码、模型、资产都必须与本批一致 ----
    problems = []
    cur_src = runio.source_identity()['content_sha']
    cur_mdl = runio.model_identity().get('go2w_xml_sha')
    if ctx.get('source_sha') and cur_src != ctx['source_sha']:
        problems.append(f'仿真源码已变化（记录 {ctx["source_sha"]}，当前 {cur_src}）')
    if ctx.get('model_sha') and cur_mdl != ctx['model_sha']:
        problems.append(f'模型已变化（记录 {ctx["model_sha"]}，当前 {cur_mdl}）')

    p = rec['planned']
    asset_dir = None if p.get('asset') in (None, 'flat') else str(ROOT / 'assets/processed' / p['asset'])
    if asset_dir:
        cur_fp = runio.asset_fingerprint(asset_dir)['collision_sha']
        if rec.get('collision_sha') and cur_fp != rec['collision_sha']:
            problems.append(f'碰撞资产已变化（记录 {rec["collision_sha"]}，当前 {cur_fp}）')
    if problems:
        print(json.dumps({'trial_id': a.trial, 'consistent': False,
                          'identity_problems': problems}, indent=2, ensure_ascii=False))
        raise SystemExit(2)
    out = pathlib.Path(a.run) / 'replays' / a.trial
    rec_path = Recorder(out, a.fps)

    again = exam.run(asset_dir, stance=p['stance'], controller=p['controller'],
                     y_offset=p['y_offset'], obstacle_x=rec.get('obstacle_x', 2.0),
                     seconds=rec.get('time_limit_s', 18.0),
                     gravity=rec.get('gravity', 1.62),
                     friction=rec.get('friction', exam.DEFAULT_FRICTION),
                     on_frame=rec_path, frame_fps=a.fps)

    diffs = {k: abs(float(again[k]) - float(rec[k]))
             for k in TOL if again.get(k) is not None and rec.get(k) is not None}
    mismatched = {k: v for k, v in diffs.items() if v > TOL[k]}
    gif = rec_path.finish(out / 'replay.gif')

    verdict = {
        'trial_id': a.trial,
        'identity_ok': True,
        'recorded': {k: rec.get(k) for k in ('outcome', 'final_x', 'max_tilt_deg')},
        'replayed': {k: again.get(k) for k in ('outcome', 'final_x', 'max_tilt_deg')},
        'tolerance': TOL,
        'diffs': {k: round(v, 6) for k, v in diffs.items()},
        'consistent': (not mismatched) and again.get('outcome') == rec.get('outcome'),
        'mismatched': mismatched,
        'frames': len(rec_path.frames),
        'gif': str(gif) if gif else None,
    }
    (out / 'replay.json').write_text(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    return 0 if verdict['consistent'] else 2


if __name__ == '__main__':
    sys.exit(main())
