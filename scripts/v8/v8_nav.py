"""V8 导航：观测 -> 地图 -> 三种策略的占据图 -> 路线规划（转向点图）-> 执行与碰撞判定。

地图（5 cm 一格）每格一个状态：
  FREE      亮处看到的地面
  ROCK      亮处看到的石头表面（离地 ≥ 4 cm）
  DARK      在视野里、但落在黑影中——被动相机测不出深度（太阳的影子）
  HIDDEN    在视野里、被更近的东西挡住（视线的影子，也就是盲区）
  UNSEEN    不在视野里
  NOGO      轨道图上的禁行区（月溪、右侧大石堆）
三种策略只在"看不见的格子怎么算"上不同：
  保守   DARK / HIDDEN / UNSEEN 都当障碍
  乐观   都当空地
  想象   通过自检的想象石块所占的格子当障碍，其余当空地
"""
import heapq
import json
import pathlib
import sys

import numpy as np
from scipy import ndimage

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import v8_scene as S  # noqa: E402

FREE, ROCK, DARK, HIDDEN, UNSEEN, NOGO = 0, 1, 2, 3, 4, 5
NAMES = ['FREE', 'ROCK', 'DARK', 'HIDDEN', 'UNSEEN', 'NOGO']
RES = 0.05
X0, X1, Y0, Y1 = -1.0, 13.0, -2.0, 2.5
NX, NY = int(round((X1 - X0) / RES)), int(round((Y1 - Y0) / RES))
XS = X0 + (np.arange(NX) + 0.5) * RES
YS = Y0 + (np.arange(NY) + 0.5) * RES
GX, GY = np.meshgrid(XS, YS, indexing='ij')          # [ix, iy]
R_DRIVE = S.ROBOT['half_wid'] + 0.07                  # 直行：半车宽 + 7 cm
R_TURN = S.ROBOT['turn_radius'] + 0.07                # 原地转向：外接圆 + 7 cm
ROCK_Z = 0.04


def cell_of(x, y):
    return int((x - X0) / RES), int((y - Y0) / RES)


def prior_nogo():
    """轨道图：月溪（右沿往左 5 cm 起）与右侧大石堆（y < 墙内沿）。"""
    edge = S.rille_edge(GX)
    return (GY > edge - 0.05) | (GY < S.WALL['y_inner'])


# ---------------------------------------------------------------- 观测
def unproject(depth, cam_pos, cam_mat, fovy_deg):
    H, W = depth.shape
    f = (H / 2) / np.tan(np.radians(fovy_deg) / 2)
    u, v = np.meshgrid(np.arange(W) + 0.5, np.arange(H) + 0.5)
    xc = (u - W / 2) / f * depth; yc = -(v - H / 2) / f * depth; zc = -depth
    P = np.stack([xc, yc, zc], -1) @ np.asarray(cam_mat).reshape(3, 3).T + np.asarray(cam_pos)
    return P


def observe(vm, env, cam='front_cam', dark_thr=0.10, max_range=9.0):
    """一次观测：返回本次的格子状态、相机位姿、图像（用于成片与 Lux3D）。"""
    import v8_vis as VZ
    vm.sync(env.data.qpos)
    rgb, depth = VZ.camera_rgbd(vm, cam)
    dark = VZ.dark_mask(rgb, dark_thr)
    cid = vm.mj.mj_name2id(vm.m, vm.mj.mjtObj.mjOBJ_CAMERA, cam)
    cam_pos = vm.d.cam_xpos[cid].copy(); cam_mat = vm.d.cam_xmat[cid].copy(); fovy = float(vm.m.cam_fovy[cid])
    P = unproject(depth, cam_pos, cam_mat, fovy)
    rng = np.linalg.norm(P - cam_pos, axis=-1)
    valid = ~dark & (rng < max_range)
    pts = P[valid]
    st = np.full((NX, NY), UNSEEN, np.int8)
    zmax = np.full((NX, NY), -np.inf)
    ix = ((pts[:, 0] - X0) / RES).astype(int); iy = ((pts[:, 1] - Y0) / RES).astype(int)
    ok = (ix >= 0) & (ix < NX) & (iy >= 0) & (iy < NY)
    ix, iy, z = ix[ok], iy[ok], pts[ok, 2]
    np.maximum.at(zmax, (ix, iy), z)
    seen = np.zeros((NX, NY), bool); seen[ix, iy] = True
    # 视野内但没有有效点的格子：判断是黑影还是被挡
    Hh, Ww = depth.shape
    f = (Hh / 2) / np.tan(np.radians(fovy) / 2)
    Rm = cam_mat.reshape(3, 3)
    pc = (np.stack([GX, GY, np.zeros_like(GX)], -1) - cam_pos) @ Rm          # 世界 -> 相机
    zc = -pc[..., 2]
    with np.errstate(divide='ignore', invalid='ignore'):
        uu = pc[..., 0] / zc * f + Ww / 2; vv = -pc[..., 1] / zc * f + Hh / 2
    inview = (zc > 0.05) & (uu >= 0) & (uu < Ww) & (vv >= 0) & (vv < Hh)
    ui = np.clip(uu.astype(int), 0, Ww - 1); vi = np.clip(vv.astype(int), 0, Hh - 1)
    pix_dark = dark[vi, ui]
    pix_depth = depth[vi, ui]
    hidden = inview & ~pix_dark & (pix_depth < zc - 0.10)
    darkc = inview & pix_dark
    st[inview] = HIDDEN
    st[darkc] = DARK
    st[hidden] = HIDDEN
    st[seen] = np.where(zmax[seen] >= ROCK_Z, ROCK, FREE)
    st[seen & (zmax < -0.08)] = NOGO                    # 看到的地面明显低于路面：溪沿以下
    return {'state': st, 'zmax': zmax, 'rgb': rgb, 'depth': depth, 'dark': dark,
            'cam_pos': cam_pos.tolist(), 'cam_mat': cam_mat.tolist(), 'fovy': fovy}


def fuse(maps):
    """多次观测合成：石头优先；亮处看到的地面其次；其余取"最好的未知类型"。"""
    out = np.full((NX, NY), UNSEEN, np.int8)
    stack = np.stack(maps)
    rock = (stack == ROCK).any(0); free = (stack == FREE).any(0)
    nogo = (stack == NOGO).any(0)
    dark = (stack == DARK).any(0); hid = (stack == HIDDEN).any(0)
    out[hid] = HIDDEN; out[dark] = DARK
    out[free] = FREE; out[nogo] = NOGO; out[rock] = ROCK
    return out


# ---------------------------------------------------------------- 策略占据图
def swept(xy, r=0.42):
    """机器人开过的地方（车身扫过的格子）：车已经在上面走过，确定是空地。"""
    m = np.zeros((NX, NY), bool)
    for x, y in xy:
        i, j = cell_of(x, y); k = int(r / RES) + 1
        sl = (slice(max(i - k, 0), min(i + k + 1, NX)), slice(max(j - k, 0), min(j + k + 1, NY)))
        m[sl] |= (GX[sl] - x) ** 2 + (GY[sl] - y) ** 2 <= r * r
    return m


def occupancy(state, policy, imagined=None, known_free=None):
    """返回 True = 不可通行。imagined: 想象石块所占格子；known_free: 车身开过的格子。"""
    occ = (state == ROCK) | (state == NOGO) | prior_nogo()
    unknown = (state == DARK) | (state == HIDDEN) | (state == UNSEEN)
    if known_free is not None:
        unknown &= ~known_free
    if policy == 'conservative':
        occ |= unknown
    elif policy == 'imagination':
        if imagined is not None:
            occ |= imagined
    elif policy != 'optimistic':
        raise ValueError(policy)
    return occ


def clearance(occ):
    return ndimage.distance_transform_edt(~occ) * RES


# ---------------------------------------------------------------- 规划：转向点图
def plan(occ, start, goal, step=0.10, max_edge=2.6, known_start=True):
    """start: (x, y)；goal: (x, y)。节点是能原地转向的点（离障碍 ≥ R_TURN），边是直行段（沿途离障碍 ≥ R_DRIVE）。
    返回路点列表（不含起点），找不到返回 None。"""
    clr = clearance(occ)
    def c_at(x, y):
        i, j = cell_of(x, y)
        if i < 0 or i >= NX or j < 0 or j >= NY:
            return 0.0
        return clr[i, j]
    xs = np.arange(X0 + 0.5, X1 - 0.5, step); ys = np.arange(Y0 + 0.3, Y1 - 0.3, step)
    nodes = [(x, y) for x in xs for y in ys if c_at(x, y) >= R_TURN]
    nodes = [tuple(start)] + nodes + [tuple(goal)]
    P = np.array(nodes)
    n = len(P)
    # 起点即使转不开也允许出发（车已经在那里）；终点要求能停下
    def seg_ok(a, b):
        L = float(np.hypot(*(P[b] - P[a])))
        k = max(2, int(L / 0.04))
        t = np.linspace(0, 1, k)
        pts = P[a][None] + t[:, None] * (P[b] - P[a])[None]
        i = ((pts[:, 0] - X0) / RES).astype(int); j = ((pts[:, 1] - Y0) / RES).astype(int)
        if (i < 0).any() or (i >= NX).any() or (j < 0).any() or (j >= NY).any():
            return False
        return bool((clr[i, j] >= R_DRIVE).all())
    dist = np.full(n, np.inf); prev = np.full(n, -1); dist[0] = 0.0
    pq = [(0.0, 0)]
    done = np.zeros(n, bool)
    while pq:
        d0, a = heapq.heappop(pq)
        if done[a]:
            continue
        done[a] = True
        if a == n - 1:
            break
        dd = np.hypot(P[:, 0] - P[a, 0], P[:, 1] - P[a, 1])
        cand = np.nonzero((dd <= max_edge) & (dd > 1e-6) & ~done)[0]
        for b in cand:
            nd = d0 + dd[b] + 0.35                        # 每多一段加 0.35 m 等效代价（少转向）
            if nd < dist[b] and seg_ok(a, b):
                dist[b] = nd; prev[b] = a; heapq.heappush(pq, (nd, b))
    if not np.isfinite(dist[n - 1]):
        return None
    path = []; k = n - 1
    while k > 0:
        path.append(tuple(P[k])); k = prev[k]
    path.reverse()
    return simplify(path, P[0], clr)


def simplify(path, start, clr):
    """去掉可以直接跳过的中间点（跳过后的直行段仍满足 R_DRIVE）。"""
    pts = [tuple(start)] + list(path)
    def ok(a, b):
        a, b = np.array(a), np.array(b); L = float(np.hypot(*(b - a))); k = max(2, int(L / 0.04))
        t = np.linspace(0, 1, k); q = a[None] + t[:, None] * (b - a)[None]
        i = ((q[:, 0] - X0) / RES).astype(int); j = ((q[:, 1] - Y0) / RES).astype(int)
        return bool((clr[i, j] >= R_DRIVE).all())
    out = [pts[0]]; i = 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not ok(pts[i], pts[j]):
            j -= 1
        out.append(pts[j]); i = j
    return [tuple(map(float, p)) for p in out[1:]]


def path_clearance(path, start, field):
    """沿路线（含转向点）到某个占据集合的最小距离：直行段用中心线，转向点用转向外接圆。"""
    pts = [tuple(start)] + list(path)
    worst_drive, worst_turn = np.inf, np.inf
    for a, b in zip(pts[:-1], pts[1:]):
        a, b = np.array(a), np.array(b); L = float(np.hypot(*(b - a))); k = max(2, int(L / 0.03))
        q = a[None] + np.linspace(0, 1, k)[:, None] * (b - a)[None]
        i = ((q[:, 0] - X0) / RES).astype(int); j = ((q[:, 1] - Y0) / RES).astype(int)
        worst_drive = min(worst_drive, float(field[i, j].min()) - S.ROBOT['half_wid'])
    for p in pts[1:-1]:
        i, j = cell_of(*p); worst_turn = min(worst_turn, float(field[i, j]) - S.ROBOT['turn_radius'])
    return {'drive_margin_m': round(worst_drive, 3), 'turn_margin_m': round(worst_turn, 3) if np.isfinite(worst_turn) else None}


# ---------------------------------------------------------------- 执行与碰撞
def robot_geoms(env):
    import mujoco
    m = env.model
    base = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'base_link')
    root = m.body_rootid[base]
    return {g for g in range(m.ngeom) if m.body_rootid[m.geom_bodyid[g]] == root}


def contact_watch(env, obstacle_bodies):
    """返回一个函数：每步调用，若机器人任何部位碰到给定的障碍 body，返回 (True, 碰撞信息)。"""
    import mujoco
    m = env.model
    rg = robot_geoms(env)
    ob = {mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, b): b for b in obstacle_bodies}
    def check(env):
        d = env.data
        for c in range(d.ncon):
            con = d.contact[c]; g1, g2 = int(con.geom1), int(con.geom2)
            for a, b in ((g1, g2), (g2, g1)):
                if a in rg and m.geom_bodyid[b] in ob:
                    return True, {'body': ob[m.geom_bodyid[b]], 'robot_geom': mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, a),
                                  'pos': [round(float(v), 3) for v in con.pos], 't': round(float(env.t), 3)}
        return False, None
    return check


def save_map_png(state, path, paths=(), marks=(), imagined=None, scale=6):
    """俯视地图（x 向右、y 向上），用于自查。"""
    from PIL import Image, ImageDraw
    col = np.array([[92, 92, 96], [210, 210, 205], [18, 18, 30], [70, 40, 110], [40, 40, 44], [120, 60, 40]], np.uint8)
    img = col[state.T[::-1]]
    if imagined is not None:
        m = imagined.T[::-1]; img[m] = (img[m] * 0.4 + np.array([60, 210, 255]) * 0.6).astype(np.uint8)
    im = Image.fromarray(img).resize((NX * scale // 2, NY * scale // 2), Image.NEAREST)
    dr = ImageDraw.Draw(im)
    k = scale / 2 / RES
    def px(x, y):
        return ((x - X0) * k, (Y1 - y) * k)
    for pts, color in paths:
        if pts and len(pts) > 1:
            dr.line([px(*p) for p in pts], fill=color, width=3)
    for (x, y), color in marks:
        a, b = px(x, y); dr.ellipse([a - 5, b - 5, a + 5, b + 5], outline=color, width=2)
    im.save(path)


# ---------------------------------------------------------------- 第二眼：选一个能看到更多"未知"的位置
def visible_cells(state, cam_xy, yaw, cells, hfov_deg=86.0, max_range=8.0):
    """二维估算：从 cam_xy 朝 yaw 看，cells（[(ix, iy)]）里有多少格不被已知石头挡住、且在视野内。
    只用已经看到的石头（ROCK）当遮挡物——黑影能不能看清，要真的看了才知道。"""
    occl = (state == ROCK)
    n = 0
    cx, cy = cam_xy
    for ix, iy in cells:
        x, y = XS[ix], YS[iy]
        dx, dy = x - cx, y - cy; r = np.hypot(dx, dy)
        if r > max_range or r < 0.3:
            continue
        a = np.degrees(np.arctan2(dy, dx) - yaw); a = (a + 180) % 360 - 180
        if abs(a) > hfov_deg / 2:
            continue
        k = int(r / (RES * 0.7)); t = np.linspace(0, 1, k, endpoint=False)[1:]
        qi = ((cx + t * dx - X0) / RES).astype(int); qj = ((cy + t * dy - Y0) / RES).astype(int)
        if not occl[qi, qj].any():
            n += 1
    return n


def choose_second_look(state, pose_xy, need_mask, policy_occ, reach=3.2, step=0.2, cam_ahead=0.42):
    """need_mask：规划需要、但现在还不知道的格子（例如目标石块背后那片地）。
    候选：在当前策略下能安全开到、能原地转向的点；朝向：对准 need_mask 的重心。返回 (x, y, yaw, 预计新看到的格数)。"""
    clr = clearance(policy_occ)
    cells = list(zip(*np.nonzero(need_mask)))
    if len(cells) > 600:
        idx = np.random.default_rng(0).choice(len(cells), 600, replace=False); cells = [cells[i] for i in idx]
    cxy = np.array([[XS[i], YS[j]] for i, j in cells]).mean(0)
    cands = []
    for x in np.arange(pose_xy[0] - 0.4, pose_xy[0] + reach, step):
        for y in np.arange(Y0 + 0.4, Y1 - 0.4, step):
            i, j = cell_of(x, y)
            if clr[i, j] < R_TURN or np.hypot(x - pose_xy[0], y - pose_xy[1]) > reach:
                continue
            yaw = float(np.arctan2(cxy[1] - y, cxy[0] - x))
            cam = (x + cam_ahead * np.cos(yaw), y + cam_ahead * np.sin(yaw))
            n = visible_cells(state, cam, yaw, cells)
            score = n - 3.0 * np.hypot(x - pose_xy[0], y - pose_xy[1])     # 看得多、走得少
            cands.append((float(x), float(y), yaw, score, n))
    cands.sort(key=lambda c: -c[3])
    return cands                                         # 按得分排序；调用方取第一个开得过去的
