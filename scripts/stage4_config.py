"""Stage004 协议权威配置：动作集、预算、判据只从这里读。"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT = ROOT / 'configs/stage4_protocol.json'


def load(path=None):
    return json.loads(pathlib.Path(path or DEFAULT).read_text())


def actions(cfg=None):
    cfg = cfg or load()
    return list(cfg['actions'])


def traverse_actions(cfg=None):
    cfg = cfg or load()
    return list(cfg['traverse_actions'])


def budget(cfg=None):
    cfg = cfg or load()
    return float(cfg['budget_s'])


def climb_cfg(cfg=None):
    cfg = cfg or load()
    return dict(cfg['climb'])
