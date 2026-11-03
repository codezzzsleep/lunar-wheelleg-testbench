# G6 最小可复现交付页

本页不依赖旧的 `dist/v3_bundle`（其构建清单与当前 build 脚本不兼容，见下）。

## 1. 状态矩阵

| 工作包 | 状态 | 证据 |
| --- | --- | --- |
| A 控制接口 | **通过** | `v3_selftest_command` 复跑：pass、stand_err 0.0087、substep_ok、restore_diff 0.0 |
| B 基础周期 | **通过** | `runs/v3/basic_cycle/*`（8 run，168/168） |
| C 预演保真 | **部分** | `runs/v3/isolation5_r3`：五臂均 physical_failure（final_x 2.109/2.109/1.957/1.602/1.630）；A-B 第 72 步分叉；残差已解释 |
| D 腿式能力 | **未通过** | `runs/v3/climb/CLIMB_failure_report.json`；D3 原始 1/2、扰动 2/3 |
| E 主角对照 | **无正例** | `docs/E_CASES.md`、`runs/v3/e_cases/index.json` |
| F 连续路线 | **通过** | `runs/v3/route/rigid_r2`、`runs/v3/route/nominal_r1` |

## 2. 证据入口

- 自动索引（57 run）：`docs/EVIDENCE_INDEX.md`、`runs/v3/evidence_index.json`。
- 能力边界：`docs/BOUNDARY.md`。
- CLIMB 最小失败报告：`docs/D_FAILURE_REPORT.md`。
- E 三案例：`docs/E_CASES.md`。

## 3. 复现命令

```bash
# A 控制接口自检
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_selftest_command.py
# B 基础周期（nominal）
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_basic_cycle.py --soil nominal --out runs/v3/basic_cycle/nominal_r1
# F 20 m 路线（nominal，沙箱）
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_route.py --soil nominal --out runs/v3/route/nominal_r1
# 真实岩石动作库
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_rock_actions.py --state runs/v3/states/moon_rock_04_h2v0 --actions R1,R2,D1,D2,S1
```

## 4. 已知缺陷 / 阻塞

- CLIMB 未完成；D3 只有 1/2 初态；S1 是跨骑，不是搭腿攀越。
- E 没有“FULL 成功而 OBS 失败”的正例；14 例几乎退化。
- 动作结束后接触表不可靠；落地用轮心高度（≤0.12 m）。
- `dist/v3_bundle` 仍是 12:29 旧批次；`build_delivery_v5.py` 读
  `plans/unseen_delivery_v5.json` 时在 `work_packages`（字符串 vs 字典）处失败，
  **当前清单无法直接重建**；`dist/publish` 也无可用发布通道（无 git-lfs/gh/token）。
- `revalidation.json` 早于最终批次，不能标“已复验”。

## 5. 结论口径

- 可以对外说：A/B/F 通过；C 部分；D 未通过；E 无正例、展示边界。
- 不可以说：腿式攀越完成、腿式相对轮式有价值、20 m 路线证明腿式能力。

## 6. 一致性检查

- `docs/CONSISTENCY.md`：12/12 通过（route 的 rigid/nominal 数值、basic_cycle 8 run、
  CLIMB failure 状态、E 的 14/12/0/1、证据索引存在）。
- `dist/publish/PUBLISH_STATUS.json` 的 `code_sha` 是旧提交（9bd2b4c），但
  `blocked_on_release_channel` 的原因仍成立：LFS 客户端 segfault、无 gh/token。
