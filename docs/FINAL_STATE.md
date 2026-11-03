# 最终状态（第 40 轮，2026-11-03）

HEAD：`c207b33ef32350a636febfe3910630fdd83e70a6`；工作区 tracked-dirty = 0；
数据回传完成：`runs/v3/states/` 7.0 GB、`runs/v3/generation/cache/` 4.7 GB。

## 结论矩阵

| 工作包 | 状态 | 证据 |
| --- | --- | --- |
| A 控制接口 | **通过** | `v3_selftest_command`：pass、stand_err 0.0087、restore_diff 0.0 |
| B 基础周期 | **通过** | `runs/v3/basic_cycle/*`（8 run，168/168） |
| C 预演保真 | **部分** | `runs/v3/isolation5_r3`：五臂 physical_failure，A-B 第 72 步分叉 |
| D 腿式能力 | **未通过** | CLIMB 未完成；D3 原始 1/2、扰动 2/3；SIDE_LEVEL 未验证 |
| E 主角对照 | **无正例** | 14 例：双方成功 12、仅 FULL 成功 0、选择不同 1 |
| F 连续路线 | **通过** | 20 m：rigid 23.5482/100.26 s；nominal 23.5375/106.6 s |
| G6 交付 | **最小页就绪** | `dist/minimal/index.html`、`docs/G6_DELIVERY.md` |

## 为什么不是“全部完成”

- **D 的 CLIMB 未完成**：两条实现路径都停在四轮保持/下降之前；按 SPEC B6 有限尝试规则停止，
  不再做参数扫描。D3 的“腿式 3/3”在可用初态上不成立。
- **E 没有正例**：14 个已有 FULL/OBS 案例中没有“仅 FULL 成功”的样本；
  按 G5 如实结束研究尝试，展示边界。
- **发布通道阻塞**：无 git-lfs/gh/token；旧 bundle 的构建清单与脚本不兼容，未重建。
- 20 m 路线是纯轮式，不能当作腿式价值证据。

## 可复现入口

```bash
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_selftest_command.py
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_basic_cycle.py --soil nominal --out runs/v3/basic_cycle/nominal_r1
MUJOCO_GL=egl /opt/lunar/bin/python scripts/v3_route.py --soil nominal --out runs/v3/route/nominal_r1
.venv/bin/python scripts/v3_consistency.py
.venv/bin/python scripts/v3_link_check.py
```

## 判定

目标未全部达成：A/B/F 与最小交付页完成；C 部分；**D/E 未达成且已到有限尝试上限**；
发布通道外部阻塞。应按“部分完成 + 明确边界”使用本项目，不得宣称腿式攀越或腿式价值成立。
