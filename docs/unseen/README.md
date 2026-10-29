# 看不见的那一面 · 执行进度（历史阶段页）

> ⚠️ **本页是 2026-10-27 早期阶段的进度快照，已被后续批次取代，不是当前状态中心。**
> 当前状态请跳转：
> - `docs/UNSEEN_STATUS_V6_1.md`（V6.1 在途，最新）
> - `docs/UNSEEN_STATUS_V6.md`（V6 已完成批次）
> - 表内「未开始 / 未通过」是**当时**的状态，后续已被 V5/V6 改写（见 `docs/PROJECT_JOURNEY.md`）。

| 阶段 | 当时的状态 | 证据 | 后来如何 |
| --- | --- | --- | --- |
| S0 观测与动作基础 | **部分完成**（尺寸/刹停已完成，观测未做） | `docs/unseen/PHASE_0.md`、`runs/unseen/prep/r1/robot_dims.json` | 观测链路后来打通（`ac99035` 观察位 10/10） |
| Gate P 物理门 | **未通过**（双胞胎网格非流形 → 凸包替换抹平背面差异） | `docs/unseen/PHASE_P.md`、`runs/unseen/gate_p/r2/` | 改为观测约束融合路线（V6） |
| Gate L 生成门 | 未开始 | — | 已接入真实图生（`35d2261`） |
| E 单例闭环 | 未开始 | — | 已跑通（`pipeline_H5_R03`） |
| V 固定评测 | 未开始 | — | V5 六方法 30 s 协议、V6 匹配比较 |
| D 作品页面 | 未开始 | — | 五步只读页面 + 连续回放（V5/V6） |

诚实结论（当时）：本轮只完成了测量与几何构造的**诊断**，"先想后走"闭环尚未成立，
也没有任何 Lux3D 图生新数据。

## 研究资料与项目历程入口

- 项目历程与决策证据（每个阶段：想解决什么、怎么做的、哪条判断被修正、证据等级）：
  `docs/PROJECT_JOURNEY.md`
- 外部资料来源登记：`docs/sources/lux3d/README.md`
  （机器可读：`docs/sources/lux3d/source_manifest.json`）
- 场景适配分析（官方说明 / 项目实测 / 项目推断三类分开）：`docs/research/LUX3D_SCENE_FIT.md`
- 当前能力状态：`docs/UNSEEN_STATUS_V6_1.md`（在途）→ `docs/UNSEEN_STATUS_V6.md`（上一批完成）

> 资料只记录「当时参考了什么、资料说了什么、没有证明什么」；原文与素材未归档。
