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

### 已通过的真实展示单元（9 个）

| 单元 | 帧数 | 最大穿透 | 渲染 | 结果 |
| --- | --- | --- | --- | --- |
| A1_cruise_10m | 756 | 0.000 mm | true | ok |
| A2_gravel | 442 | 0.741 mm | true | ok |
| A3_slope8 | 449 | 0.000 mm | true | ok |
| B1_boulder_detour | 327 | 0.000 mm | true | ok |
| B2_pit_side | 335 | 0.000 mm | true | ok |
| A4_R1 | 441 | 0.000 mm | true | ok |
| A4_BODY | 936 | 0.000 mm | true | ok |
| M3_route_full | 3119 | 0.000 mm | true | ok |
| M3_route_obs | 3119 | 0.000 mm | true | ok |

- 9/9 通过 §4（穿透 ≤5 mm、渲染成功、manifest sha 全对）。
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

## R1 复核整改：编译模型重打包

### 做法

- 每个包现在带 `scene/compiled/model.xml`：由 `mujoco.mj_saveLastXML` 从 `WheelLegEnv.model` 直接导出，
  资产复制到 `scene/compiled/assets/` 并改为相对路径；
- 重放检查 v2（`scripts/v6_replay_check2.py`）直接加载该 XML，报告 `ngeom`、障碍 geom 数量、逐障碍最小距离；
- 渲染改为跟随机器人相机，首/中/末帧机器人占画面约 1/3。

### 七个 WP7 单元（v6r1）

| 单元 | ngeom | 障碍 geom | 最大穿透 | 渲染 | ok |
| --- | --- | --- | --- | --- | --- |
| A1_cruise_10m | 53 | 0 | 0.000 mm | true | true |
| A2_gravel | 97 | 44 | 2.882 mm | true | true |
| A3_slope8 | 53 | 0 | 0.000 mm | true | true |
| A4_R1 | 53 | 0 | 0.000 mm | true | true |
| A4_BODY | 53 | 0 | 0.000 mm | true | true |
| B1_boulder_detour | 55 | 2 | 0.000 mm | true | true |
| B2_pit_side | 53 | 0 | 0.000 mm | true | true |

### A2 / B1 查清结果

- **A2**：场景描述里的 `posed_dir` 在包内被改成了错误的相对路径，导致重放时 `objects` 为空、地上没有碎石；
  修正为 `scene/objects/obj_0` 后，编译模型里有 **44 个 obstacle geom**，位置与轨迹重叠，最小距离 0.0009 m。
- **B1**：真实仿真是 `resample_walls` 生成的 **2 个 0.5×0.5×0.32 m 方块**（coll manifest），
  `assets/body_world.stl` 只是可视参考；修正路径后编译模型含这 2 个 geom，全程最小距离 0.0009/0.0024 m，
  轨迹最大横移 0.555 m 正贴石块，场景与轨迹一致。

### 新资产名

- `v6r1__units__<unit>.tar.gz`（7 个），旧 `v6__units__*` 保留不覆盖。
