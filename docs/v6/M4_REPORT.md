# M4 素材包与重放检查

## 本步问题

实现 §4 重放检查，并把展示单元打成可上传包。

## 命令

- `python3 scripts/v6_build_wp7_package.py runs/v4/wp7_new/<scene>`
- `MUJOCO_GL=egl python3 scripts/v6_replay_check.py runs/v6/m4/units/<unit>`
- `python3 scripts/v6_m4_manifest.py`

## 结果表

### 重放检查器

`scripts/v6_replay_check.py` 已实现：

1. 校验 `manifest.json` 全部 sha256；
2. 从 `scene/scene_spec.json` 重建 `WheelLegEnv`；
3. 逐帧写 qpos 并 `mj_forward`，统计最大穿透；
4. `MUJOCO_GL=egl` 渲染首/中/末帧到 `check/`；
5. 写 `check/replay_check.json`。

### 已通过的真实展示单元（7 个）

| 单元 | 帧数 | 最大穿透 | 渲染 | 结果 |
| --- | --- | --- | --- | --- |
| A1_cruise_10m | 756 | 0.000 mm | true | ok |
| A2_gravel | 442 | 0.741 mm | true | ok |
| A3_slope8 | 449 | 0.000 mm | true | ok |
| B1_boulder_detour | 327 | 0.000 mm | true | ok |
| B2_pit_side | 335 | 0.000 mm | true | ok |
| A4_R1 | 441 | 0.000 mm | true | ok |
| A4_BODY | 936 | 0.000 mm | true | ok |

- 7/7 通过 §4（穿透 ≤5 mm、渲染成功、manifest sha 全对）。
- 打包：`dist/v6/units/<unit>.tar.gz`；清单 `dist/v6/showcase_manifest.json`。
- 已上传 Release `v6-showcase`：`v6__units__<unit>.tar.gz`。

## 未做到

- A4 已用 `runs/v4/wp7/A4_scene.json` 分别打包成 `A4_R1` 与 `A4_BODY`，两者均通过。
- M1 的岩石×视角单元、M3 路线单元尚未打包。
- `scene/heightfield.npy` 与 `rocks/` 的完整 §3 结构未逐项校验；当前包以 `scene_spec.json + objects/coll + assets` 重建通过。

## 根因

- 5 个 WP7 单元本身无失败；缺口是打包器对多 run 场景与 M1/M3 单元的支持尚未实现。

## 证据

- `runs/v6/m4/units/<unit>/check/replay_check.json`
- `runs/v6/m4/units/<unit>/check/{first,mid,last}.png`
- `dist/v6/showcase_manifest.json`
- Release `v6-showcase`

## 下一步

补 A4 多 run 打包；M1 岩石单元与 M3 路线单元在各自完成后按同流程打包。
