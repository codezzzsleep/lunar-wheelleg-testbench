# G6 交付状态（2026-11-03）

## 结论矩阵

| 工作包 | 状态 | 关键证据 |
| --- | --- | --- |
| A 控制接口 | **通过** | `v3_selftest_command`：25 控制步=250 物理步、t≈0.5 s、coast ctrl=0、restore diff 0 |
| B 基础周期 | **通过** | 8 个 run、168/168 检查；HOLD tilt 1.36–1.54°，margin 11.6–16.7 mm |
| C 预演保真 | **部分** | 五臂对照、A/B 第 72 步分叉、B/盒 第 92 步；残差已解释；`revalidation.json` 早于最终批次 |
| D 腿式能力 | **未通过** | CLIMB 停在 `RR_hold`/`RL_shift`；D3：原始初态 1/2、扰动初态 2/3；SIDE_LEVEL 未评估 |
| E 主角对照 | **无正例** | 14 例：双方成功 12、仅 FULL 成功 0、选择不同 1；按 G5 展示边界 |
| F 连续路线 | **通过** | 20 m（3×5 cm 台阶）：rigid x=23.5482/100.26 s；nominal x=23.5375/106.6 s |

## 证据索引与边界

- 自动索引：`docs/EVIDENCE_INDEX.md`（57 个主要 run，run → 结果 → 指标）。
- 能力边界：`docs/BOUNDARY.md`（D 未通过、E 无正例的诚实结论）。

## 关键修正

- 机器人重力分母：`base_link` 子树质量 19.1264 kg / 30.985 N（不含静态台块）。
- 接触法向：MuJoCo `contact.frame` 行主序，法向在第一行。
- 长路线：hfield span 12.5→25 m，`field_x_max` 26；此前 12.77 m 翻倒是驶出地形边缘。
- 阶段前置：失败即停（`blocked_at`），不继续硬抬。

## 复现命令

```bash
# A
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_selftest_command.py
# B
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_basic_cycle.py --soil nominal --out runs/v3/basic_cycle/nominal_r1
# F
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_route.py --soil nominal --out runs/v3/route/nominal_r1
# 岩石动作库
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_rock_actions.py --state runs/v3/states/moon_rock_04_h2v0 --actions R1,R2,D1,D2,S1
```

## 已知缺陷 / 边界

- CLIMB 未完成：最后一条腿的支撑/落地仍是缺口；D3 的 3/3 不成立。
- E 没有“背面使 FULL 成功而 OBS 失败”的正例；现有 14 例几乎退化。
- 动作结束后接触表不可靠；落地判据用轮心高度（≤0.12 m）代替。
- `dist/v3_bundle` 仍是旧批次（12:29 构建），与当前证据（19:xx）不一致；
  重建需要 `build_delivery_v5.py --manifest` 的页面/媒体清单，未在本轮重跑；
  发布通道受限于无 git-lfs/gh/token，标 `blocked_on_release_channel`。
- `revalidation.json` 早于最终批次，不能据此标“已复验”。
