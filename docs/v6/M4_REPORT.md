# M4 素材包与重放检查（部分）

## 本步问题

实现 §4 重放检查，并把展示单元打成可上传包。

## 命令

- `python3 scripts/v6_pkg_selftest.py`
- `MUJOCO_GL=egl python3 scripts/v6_replay_check.py runs/v6/m4/selftest`

## 结果表

### 重放检查器

`scripts/v6_replay_check.py` 已实现：

1. 校验 `manifest.json` 全部文件 sha256；
2. 用 `scene/scene_spec.json` 重建 `WheelLegEnv`；
3. 逐帧写入 `traj.npz` 的 qpos 并 `mj_forward`，统计最大穿透；
4. `MUJOCO_GL=egl` 渲染首/中/末三帧到 `check/`；
5. 写 `check/replay_check.json`。

### 自测包（非展示单元）

| 项 | 结果 |
| --- | --- |
| sha 校验 | 0 个坏文件 |
| 帧数 | 120 |
| 最大穿透 | **0.000 mm**（≤5 mm） |
| 末帧一致 | true |
| 渲染 | true（沙箱 EGL） |
| 总体 | **ok=true** |

- 主机没有 EGL，渲染会失败；沙箱上通过，说明检查器本身可用。

### 展示单元

- **0 个**。M1/M2/M3 的展示单元都缺场景资产、原始轨迹或 6 份 GLB 全集，无法按 §3 打包。
- Release `v6-showcase` 目前只有 M0 的 75 份 GLB、`assets/v3` 压缩包、WP7 现有场景包，均不是通过重放检查的素材包。

## 未做到

- 没有任何展示单元通过 §4 并上传。
- `v6_replay_check.py` 尚未在真实展示包上运行。

## 根因

- 打包所需的场景资产与逐帧轨迹在旧沙箱；主机只有部分 JSON/STL，没有完整 `traj.npz` 与岩石 GLB。
- M1/M2/M3 的展示单元本身也未完成，M4 没有可打包对象。

## 证据

- `scripts/v6_replay_check.py`
- `runs/v6/m4/selftest/check/replay_check.json`（ok=true）
- 沙箱运行记录（本次输出）

## 下一步

先补 M0/M1/M3；每完成一个展示单元，立即用 `v6_replay_check.py` 检查并上传。
