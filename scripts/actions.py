"""
动作注册表：正式管线、六方法、开发重验与页面共用**同一份**定义。

  from actions import OPTIONS, applicable_all, ACTIONS

为什么需要它（772bc59 复核）：
  · eval_six 的 OPTIONS 已含 S1/D1/D2，但 unseen_pipeline 默认仍是
    R1,R2,L1,L2,A0 —— 正式 H5 闭环根本选不到本轮唯一可靠通过的 S1；
  · 适用性判定散落在 skills 与各脚本里，容易与最终 runner 执行不一致。

本模块只做两件事：
  1. 唯一的动作清单与顺序；
  2. 唯一的适用性判定（只读公开可见量，不读隐藏背深/类型）。
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import skills

# 唯一动作清单：A0 是回退，不参与"可完成通行"的安全集合
RULE_VERSION = 'actions/applicability/v2'

OPTIONS = ('R1', 'R2', 'L1', 'L2', 'S1', 'D1', 'D2', 'A0')
TRAVERSE = tuple(o for o in OPTIONS if o != 'A0')
FALLBACK = 'A0'

ACTIONS = {o: {'is_fallback': (o == FALLBACK),
               'needs_visible_width': o in ('S1', 'D1', 'D2')} for o in OPTIONS}


def applicable(option, visible, channel_half=1.2):
    """
    返回 (bool, reason)。reason 只在 False 时非空，用于显式记录 not_applicable。
    只使用公开可见量：W_vis / H_vis / x_front / 通道半宽。
    """
    if option == FALLBACK:
        return True, None
    sk = skills.make_skill(option)
    if not hasattr(sk, 'applicable'):
        return True, None
    try:
        if option.startswith('D'):
            ok = bool(sk.applicable(visible, channel_half))
        else:
            ok = bool(sk.applicable(visible))
    except TypeError:
        ok = bool(sk.applicable(visible))
    return ok, (None if ok else 'not_applicable_by_public_visibility')


def applicable_all(visible, channel_half=1.2):
    return {o: applicable(o, visible, channel_half) for o in OPTIONS}


def describe():
    """给页面/报告用的动作说明（含适用性阈值来源）。"""
    s1 = skills.make_skill('S1')
    d = skills.make_skill('D1')
    return {
        'options': list(OPTIONS), 'traverse': list(TRAVERSE), 'fallback': FALLBACK,
        'straddle_threshold_m': round(float(s1.CLR), 4),
        'straddle_formula': 'track - wheel_width - margin',
        'detour_half_width_m': float(d.ROBOT_HALF_W),
        'detour_lateral_need_m': float(d.LATERAL_NEED),
        'note': 'A0 是安全回退，不计任务成功，也不进入可通行安全集合',
    }
