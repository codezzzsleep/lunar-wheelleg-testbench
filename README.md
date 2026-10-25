# 月球基地轮腿机器人训练场

> Aholo 3D AI 黑客松参赛项目 · 阶段 0 / 第 1 关已完成

用 Lux3D 生成月球基地还不存在的物体（着陆器、货箱、设备、残骸），拆成凸块碰撞体，
放进 MuJoCo 的月面考场，让轮腿机器人去考——**并且用它没见过的物体考它。**

## 现在到哪了

**第 1 关（生死关，原定 10.27）已通过：**

```
$ PYTHONPATH=/tmp/robolib python3 scripts/gate1.py
PASS  ITEM 1 · go2w 月球重力
PASS  ITEM 2 · 碰撞对照 raw vs CoACD
PASS  ITEM 3 · Lux3D 物体进考场并接触
PASS  ITEM 4 · 脚本控制器 5 m 不倒
GATE 1: PASS
```

全流程 8.2 秒（含一次真实 CoACD 拆块）。

| 项 | 实测 |
| --- | --- |
| MuJoCo + go2w | 月球重力 1.62 m/s²，16 执行器（12 腿 + 4 轮），稳定站立 |
| 碰撞对照 | 原始网格：小球停在 **z=0.355**（凸包把孔洞盖上）；CoACD 拆 **12 块**后穿到 **z=0.020** |
| Lux3D 物体 | 货箱 13.0 MB，294 s 生成 → 定尺度 → 拆块 → **3.12 s 被轮子撞上**，机器人被顶翻 |
| 脚本控制器 | 低姿态 12.57 m / 高姿态 12.52 m（要求 5 m），倾角 7.2° / 0.7°，机身 0.384 / 0.466 m 可区分 |


## 结果（已完成部分）

**第 2 关（原定 11.03）的核心内容已跑通**：696 次仿真、553 次有效接触、21 个资产、2 个考生。

- **能力边界**：方块高度低于 0.6 倍轮半径 → 100% 通过；超过 1.1 倍 → 跌破 50%。
- **腿确实有用**：`step` 考生在 1.51 倍轮半径这一档把通过率从 5% 提到 **24%**
  （前腿缩短、后腿伸长，把机头抬起来压上台面）。回放：`demo/step_legs_1p51.gif`。
- **但腿的帮助很窄**：只在 1.51 倍这一档有效，1.76 倍以上两种考生都过不去。
- **同尺寸对照仍测不出形状差异**：宽度统一 0.30 m、高度对齐后，两个考生的全部配对
  95% 置信区间都重叠。

> **"没测出"≠"没影响"。** `step` 是开环的固定动作序列，不会根据障碍物形状调整落脚点。
> 形状真正能发挥作用的——踩进凹槽、绕过悬空、利用斜面——这套状态机触及不到。

- **完整报告**：[`docs/REPORT.md`](docs/REPORT.md)；图在 `docs/figures/`；回放在 `demo/`。

结论只在这些条件下成立：开环脚本考生、静态障碍物、刚性地面、月球重力。

## 环境

无 GPU，4 核 / 7 GB，纯 CPU。MuJoCo 跑 go2w 约 **10 倍实时**（16 s 仿真 ≈ 1.5 s 墙钟）。
强化学习训练是扩展项，不是主线。

Python 依赖装在 `/tmp/robolib`（系统无 venv），运行时加 `PYTHONPATH=/tmp/robolib`：

```bash
python3 -m pip install --target /tmp/robolib mujoco trimesh numpy coacd manifold3d
git clone --depth 1 https://github.com/unitreerobotics/unitree_mujoco vendor/unitree_mujoco
```

## 一键复现

```bash
cd lunar-lab
PYTHONPATH=/tmp/robolib python3 scripts/build_scene.py          # 生成 moon_flat.xml（重力+地面）
PYTHONPATH=/tmp/robolib python3 scripts/gate1.py                # 第 1 关四项
```

单跑某一项：

```bash
python3 scripts/check_collision.py                                   # 碰撞对照
python3 scripts/process_asset.py assets/raw/cargo_crate.glb --height 0.28
python3 scripts/exam.py --asset assets/processed/cargo_crate --stance low
python3 scripts/drive_test.py                                        # 两个脚本考生
```

## 目录

```
scripts/controllers.py  考生：hold（四轮小车）/ step（带腿抬头迈步）
assets/raw/          Lux3D 原始 GLB
assets/processed/    处理后：parts/*.stl + manifest.json（几何量、凸块数、凹度）
scripts/             资产管线 / 场景构建 / 考场 / 考生 / 验收
vendor/unitree_mujoco  go2w 模型（411 MB，未入库）
runs/                每一关的结果 JSON
```

## 踩过的坑（都是实测，不是推测）

1. **MuJoCo 对闭合网格按凸包碰撞。** 圆环的孔洞会被"盖上"，小球停在管子上。
   必须 CoACD 拆块，拆完才穿得过去。这是整个项目存在 CoACD 的唯一理由。
2. **Lux3D 输出的网格不是水密的**（椅子 191,926 面 watertight=False；货箱也是）。
   所以"凹度 = 1 − 网格体积/凸包体积"算不出来，改用 **1 − 凸块体积和/凸包体积**，
   凸包用 `manifold3d`（精确，且不需要 scipy）。
3. **近凸物体不要拆。** 货箱凹度 0.014，原本被拆成 32 块（撞上限），只是白增接触对。
   现在凹度 < 0.05 直接用一个精确凸包顶替，货箱变成 1 块。
4. **轮子不用换成圆柱。** go2w 的轮子碰撞体虽然是 mesh，但轮子本身是凸的，
   凸包 ≈ 圆柱，换成圆柱是优化不是必需。
5. **力矩突变会让机身翘头 60°** 并稳定在这个姿态上跑（不是倒，是轮式"翘头"）。
   把速度指令做成 2 s 斜坡后，倾角降到 1.4°。
6. **出生高度必须高于目标站姿高度**，否则机器人砸下来会翻倒——高姿态第一次失败就是这个原因，
   不是控制器不行。
7. **MuJoCo 是位精确可复现的**：同一条轨迹跑三次，`qpos` 逐位相同（`max|a-b| = 0.0`）。
   所以考场只需存参数 + 种子。

## 下一步（阶段 1）

- [ ] Lux3D 批量生成 ≥ 30 个物体（≥ 8 类；另留 3–4 类只用于封存考场）
- [ ] 程序化障碍生成器，按同一套几何量出题（方块、圆柱、斜坡）
- [ ] 场景编排 + 自动检查（穿模、悬空、出生点、能否静置）
- [ ] 考试运行器：多核并行、写日志、存回放
- [ ] 第 2 关（11.03）：无人值守跑完 20 个场景并自动出报告

## 诚实边界

第一版只做**月球重力下的刚性地面**，不模拟月壤沉陷、不做真实摩擦参数标定。
生成的岩石/货箱是"看起来合理"，不是"物理真实"。所有结论只在这个范围内成立。
