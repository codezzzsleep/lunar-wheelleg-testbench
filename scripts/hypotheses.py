"""
假设来源登记表：H1/H2/H3/H4/H5 共用同一清单接口（E2）。

每个来源返回 hypotheses 列表，每项至少：
  hypothesis_id, source_kind, mesh_path, metrics, accepted, reject_reason

  from hypotheses import make_source
  src = make_source('H3', obs_dir=..., case=...)
  hyps = src.build()

H3 的参数**必须真的改变几何**（之前用角度命名固定几何是错的）。
"""
import json
import pathlib
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import twins

ROOT = pathlib.Path(__file__).resolve().parent.parent

# H3 的固定参数集：背深比例（相对可见高）与背面型面
H3_PARAMS = [
    {'id': 'h3_drop', 'kind': 'drop', 'ratio': 0.85},
    {'id': 'h3_ramp25', 'kind': 'ramp_s', 'angle_deg': 25.0},
    {'id': 'h3_ramp12', 'kind': 'ramp_l', 'angle_deg': 12.0},
    {'id': 'h3_ledge', 'kind': 'ledge', 'ratio': 0.60},
    {'id': 'h3_cleft', 'kind': 'cleft', 'angle_deg': 12.0},
]


class HypothesisSource:
    name = 'base'
    source_kind = 'unknown'

    def __init__(self, obs_dir=None, case=None, align_dir=None):
        self.obs_dir = pathlib.Path(obs_dir) if obs_dir else None
        self.case = case or {}
        self.align_dir = pathlib.Path(align_dir) if align_dir else None

    def observation(self):
        if not self.obs_dir:
            raise SystemExit('缺少 --obs')
        return json.loads((self.obs_dir / 'observation.json').read_text())

    def build(self):
        raise NotImplementedError


class H3Procedural(HypothesisSource):
    """程序化多候选：由可见量 + 固定背面型面生成，参数真实改变几何。"""
    name = 'H3'
    source_kind = 'procedural'

    def build(self):
        obs = self.observation()
        vis = obs['visible']
        H = float(vis['H_vis'])
        W = float(vis['W_vis'])
        D = float(self.case.get('obstacle_x', 1.80) - vis['x_front'])
        D = max(D, 0.05)
        out = []
        for p in H3_PARAMS:
            mesh, Lb = twins.twin_solid(p['kind'], H, W, D)
            # 参数必须真的影响几何：drop/ledge 用背深比例，斜坡用角度
            if 'ratio' in p:
                target_L = p['ratio'] * H
                if Lb > 1e-9:
                    s = target_L / Lb
                    mesh.apply_scale([1.0, 1.0, 1.0])
                    v = np.asarray(mesh.vertices).copy()
                    v[:, 0] *= s
                    mesh = trimesh.Trimesh(v, np.asarray(mesh.faces), process=False)
            d = pathlib.Path(self.obs_dir) / 'hyp' / f"{p['id']}.stl"
            d.parent.mkdir(parents=True, exist_ok=True)
            mesh.export(d)
            out.append({'hypothesis_id': p['id'], 'source_kind': self.source_kind,
                        'params': p, 'mesh_path': str(d),
                        'L_back_prior': round(float(Lb), 4),
                        'H': round(H, 4), 'W': round(W, 4),
                        'D_front': round(D, 4), 'accepted': None,
                        'reject_reason': None})
        return out


class AlignedLux3D(HypothesisSource):
    """
    H5：真实 Lux3D 候选；H4 = 按任务创建顺序第一个合格候选（不挑最像真值的）。
    H1/H2 为单假设对照（本文件只提供接口，几何由各自实现决定）。
    """

    def __init__(self, *a, candidates=None, **kw):
        super().__init__(*a, **kw)
        self.candidates = candidates or []

    def build(self):
        out = []
        for i, c in enumerate(self.candidates):
            out.append({'hypothesis_id': c.get('hypothesis_id', f'lux3d_{i}'),
                        'source_kind': c.get('source_kind', 'lux3d'),
                        'params': c.get('params', {}),
                        'mesh_path': c.get('posed_dir') or c.get('mesh_path'),
                        'accepted': c.get('accepted'),
                        'reject_reason': c.get('reject_reason'),
                        'metrics': c.get('metrics'),
                        'task_id': c.get('task_id'),
                        'raw_glb_sha': c.get('raw_glb_sha')})
        return out


class H4FirstAccepted(AlignedLux3D):
    name = 'H4'
    source_kind = 'lux3d_first'

    def build(self):
        hyps = super().build()
        acc = [h for h in hyps if h.get('accepted')]
        return acc[:1]


class H5Multi(AlignedLux3D):
    name = 'H5'
    source_kind = 'lux3d_multi'


def make_source(name, **kw):
    table = {'H3': H3Procedural, 'H4': H4FirstAccepted, 'H5': H5Multi,
             'H1': AlignedLux3D, 'H2': AlignedLux3D}
    if name not in table:
        raise SystemExit(f'未知假设来源 {name}')
    src = table[name](**kw)
    src.name = name
    return src
