"""Stage004：局部几何 -> 技能参数（场景创建与技能执行分离）。

技能执行只接收本模块的 `params`，不读取场景真值、物体包围盒或配置。
所有参数带来源；未知项显式标记，绝不默认补成零高度。
"""

WHEEL_R = 0.086

# 技能自身的控制偏移（不是场景几何，固定合同的一部分）
BRAKE_OFFSET = 0.35      # 刹停点 = 前缘 - 0.35 m
ASSIST_OFFSET = 0.07     # 轮式助爬目标 = 前缘 + 0.07 m
PLACE_OFFSET = 0.07      # 后轮落点目标 = 前缘 + 0.07 m
LIFT_CLEARANCE = 0.025   # 抬腿中心 = 台面 + 轮半径 + 0.025 m
DESCENT_MARGIN = 0.30    # 下降目标 = 后缘 + 0.30 m
STABILITY_MARGIN = 0.25  # 终态越过后缘的余量


def derive_skill_params(obs):
    """obs: 观测/融合给出的局部几何。返回 params/sources/unknowns/valid。

    obs 必需: face_FR, face_FL, top_z；可选: far_x, landing, source, provenance。
    far_x 未知时 descent=None，技能必须安全停下而不是猜一个后缘。
    """
    src = obs.get('source', 'unknown')
    face_fr = obs.get('face_FR')
    face_fl = obs.get('face_FL')
    top_z = obs.get('top_z')
    far_x = obs.get('far_x')
    landing = obs.get('landing')
    params, sources, unknowns = {}, {}, []

    for name, val, required in (('face_FR', face_fr, True),
                                ('face_FL', face_fl, True),
                                ('top_z', top_z, True)):
        if val is None:
            if required:
                unknowns.append(name)
            params[name] = None
            sources[name] = 'unknown'
        else:
            params[name] = float(val)
            sources[name] = src

    if params['face_FR'] is not None:
        params['brake_x'] = float(params['face_FR']) - BRAKE_OFFSET
        params['place_RR_x'] = float(params['face_FR']) + PLACE_OFFSET
    else:
        params['brake_x'] = params['place_RR_x'] = None
    if params['face_FL'] is not None:
        params['assist_FL_x'] = float(params['face_FL']) + ASSIST_OFFSET
    else:
        params['assist_FL_x'] = None
    if params['top_z'] is not None:
        params['lift_center_z'] = float(params['top_z']) + WHEEL_R + LIFT_CLEARANCE
    else:
        params['lift_center_z'] = None

    if far_x is None:
        params['far_x'] = None
        sources['far_x'] = 'unknown'
        params['descent'] = None
        unknowns.append('far_x')
    else:
        params['far_x'] = float(far_x)
        sources['far_x'] = src
        params['descent'] = {'mode': 'forward_drop',
                             'target_x': float(far_x) + DESCENT_MARGIN}
        sources['descent'] = 'derived_from_far_x'

    if landing is None:
        params['landing'] = None
        sources['landing'] = 'unknown'
        unknowns.append('landing')
    else:
        params['landing'] = [float(landing[0]), float(landing[1])]
        sources['landing'] = src

    valid = True
    reasons = []
    if params['face_FR'] is None or params['face_FL'] is None or params['top_z'] is None:
        valid = False
        reasons.append('missing_required_face_or_height')
    if params['top_z'] is not None and params['top_z'] <= 0.0:
        valid = False
        reasons.append('non_positive_top_z')
    if (params['face_FR'] is not None and params['far_x'] is not None
            and params['far_x'] <= params['face_FR']):
        valid = False
        reasons.append('far_x_not_after_face')

    return {'params': params, 'sources': sources, 'unknowns': unknowns,
            'valid': bool(valid), 'invalid_reasons': reasons,
            'control_offsets': {'brake': BRAKE_OFFSET, 'assist': ASSIST_OFFSET,
                                'place': PLACE_OFFSET, 'lift_clearance': LIFT_CLEARANCE,
                                'descent_margin': DESCENT_MARGIN,
                                'stability_margin': STABILITY_MARGIN},
            'obs_source': src}


def truth_geometry_from_scene(scene):
    """开发/回归专用：从场景真值构造观测几何（source=truth_dev）。

    Stage004 的正式 FULL/OBS_ONLY 分支必须用观测/融合产物，不用本函数。
    """
    ledges = scene.get('ledges') or []
    if len(ledges) < 2:
        raise ValueError('dev scene needs at least two ledges')
    by_y = sorted(ledges, key=lambda x: x['center_y'])
    # 约定：center_y 较小的一侧为 FR（右），较大为 FL（左），与开发场景一致
    lower = by_y[0]
    upper = by_y[-1]
    face_fr = float(lower['face_x'])
    face_fl = float(upper['face_x'])
    far = min(float(l['face_x']) + float(l['length']) for l in ledges)
    return {'face_FR': face_fr, 'face_FL': face_fl,
            'top_z': float(lower['top_z']), 'far_x': far,
            'landing': None, 'source': 'truth_dev',
            'provenance': {'scene': scene.get('name'),
                           'note': 'development regression only'}}
