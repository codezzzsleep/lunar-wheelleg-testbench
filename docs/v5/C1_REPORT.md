# C1 价值筛选（REVIEW_R1 修正后）

## 本步问题

按补充 2/3 的规则重跑隐藏敏感状态：每状态自己的可见尺寸、OBS_CONS 双几何安全集交集、
3/3 扰动预演、接触/能耗核算；开阔场价值为 0 时，按 C1.3 加窄道布置。

## 命令

- `python3 scripts/v5_c1.py --limit 22`（开阔场，20/22 完成）
- `python3 scripts/v5_c1_narrow.py --states moon_rock_05_h2v1,rock_07_h0v0 --channel 0.35`
- `python3 scripts/v5_c1_narrow.py --states moon_rock_05_h2v1,rock_07_h0v0 --channel 0.475`

## 结果表

### 开阔场（20 个状态）

| 类型 | 数量 |
| --- | --- |
| I 类 | **0** |
| II 类 | **0** |

- 所有已完成状态 PERFECT 预演–执行一致率均为 true（`moon_rock_06_h2v1` 为 false：
  R1 预演安全但真值翻车，属“预演对初态敏感”，已记录）。
- `rock_07_h1v0`、`rock_07_h1v1` 两状态未完成（观察文件缺失，进程挂起），不冒充结果。

### 窄道布置（channel half 0.35，净宽 0.70 m）

| 状态 | PERFECT | OBS_CONS | 类型 |
| --- | --- | --- | --- |
| rock_07_h0v0 | **L2 pass 6.74 s** | D2 physical_failure 5.96 s | **I 类** |
| moon_rock_05_h2v1 | A0 safe_stop | A0 | 无 |

### 窄道布置（channel half 0.475，净宽 0.95 m）

| 状态 | PERFECT | OBS_CONS | 类型 |
| --- | --- | --- | --- |
| rock_07_h0v0 | R1 pass 6.66 s | R1 pass | 无 |
| moon_rock_05_h2v1 | A0 safe_stop | A0 | 无 |

- 窄道布置用“收窄通道半宽 + 原有真实岩石”近似；尚未搭出 SPEC 的左坑/右乱石几何，
  不能算完整 C1.3 布置。
- 但 0.35 宽度下出现 1 个真实 I 类：PERFECT 左绕通过，OBS_CONS 右绕翻车。

## 未做到

- 开阔场 22 个只完成 20 个。
- 窄道仅 2 个状态、2 个宽度；左坑沿/右乱石几何未搭。
- 各状态 `rehearsal_3of3.json` 已写，但未逐动作汇总进表。

## 根因

- 开阔场价值为 0：修正 OBS_CONS 后，R1 直行在未知区被正确判为不安全，PERFECT 与 OBS 都退回
  A0 或同一绕行；旧的 2 个 I 类来自“保守机器人直接开进未知区”的错误，已被修正消除。
- 两状态挂起：观察目录未同步，加载/恢复阶段阻塞；不是价值判定问题。

## 证据

- `runs/v5/c1/value_table.csv`、`value_rows.json`
- `runs/v5/c1_narrow035/narrow_table.csv`
- `runs/v5/c1_narrow0475/narrow_table.csv`
- 每状态每臂：`runs/v5/c1/<state>/<arm>/rehearsal_3of3.json`、`p{0,1,2}/`、`exec/`

## 下一步

C2：在窄道 0.35 的 `rock_07_h0v0` 上补候选（曝光归一化后生成），跑完整闭环；
若仍然零准入，按合同回退并保留分母。
