# M0 架构（一页）

## 主线

```
参考包 / 任务描述 ──► scene_spec ──► 环境（heightfield + 生成资产）──► 策略训练 ──► 留出场景评估
   references/          JSON            wheelleg_env.py                train.py        eval.jsonl
```

## 各层职责与产物

| 层 | 文件 | 输入 | 输出 | 是否已验证 |
| --- | --- | --- | --- | --- |
| 参考与描述 | `references/pack_A/`、`scripts/reference_to_scene.py` | 图片 + 任务文本 + meta.json | `scene_spec.json` | 是（见 `runs/ref_scene/`） |
| 地形 | `scripts/terrain.py` | spec 的 terrain 字段 | 65×65 heightfield PNG | 是（flat / slope / bumpy 均可加载） |
| 场景编排 | `scripts/wheelleg_env.py::_compose` | spec 的 objects 字段 | MuJoCo XML（hfield + Lux3D 碰撞体） | 是 |
| 环境接口 | `scripts/wheelleg_env.py` | action(3) | obs(39), reward, terminated/truncated | 是 |
| 学习算法 | `scripts/ppo.py` | rollout | 更新后的参数 | 是（参数校验和变化、checkpoint 可加载） |
| 训练入口 | `scripts/train.py` | config + scenes | checkpoint、日志、评估 | 是 |
| 场景集 | `scripts/make_scenes.py` | — | `scenes/*.json`（划分写死） | 是 |

## 数据流的关键约定

- **地形用 heightfield，不用 mesh**。MuJoCo 对 mesh 按凸包碰撞，起伏会被填平。
- 资产解析、路径、指纹统一走 `runio.resolve_asset`，与考场流程同一套规则。
- 场景身份 = spec 的规范化哈希（`terrain.scene_identity`），与目录名无关。

## 动作与观测

- **动作 3 维残差**：前腿 thigh 目标偏移、后腿 thigh 目标偏移、轮速倍率。
  底层 PD 与轮速伺服**固定不变**，所有组共用。
  → 这是"学习高层残差"，**不是**从零学 16 个电机的全身控制。
- **观测 39 维**：机体坐标系重力方向(3)、角速度(3)、前进速度(1)、12 关节角、
  12 关节角速度、4 轮速、上一动作(3)、目标速度(1)。
  → 全部来自仿真真值的本体感觉，**不含像素视觉**，也不是真实相机感知。

## 训练与评估

- 控制 50 Hz / 物理 0.002 s（每控制步 10 个物理步）。
- 留出场景：G 组按 **GLB 家族**划分（训练 4 个家族，验证 3 个家族，不重叠）。
- 评估分两种口径：
  - `deterministic`：用策略均值动作；
  - `stochastic`：用与训练相同的随机采样，反映优化器实际在改的行为分布。

## 明确没有做的

- 没有 SpatialGen 世界导入器（其输出是否为 MuJoCo 可用碰撞几何尚未验证）。
- 没有像素视觉策略、没有模仿学习（没有专家轨迹）。
- 没有真实地形数据：参考图为**合成渲染**，不是照片重建。
- 没有声明泛化：仅按家族划分留出，样本量小。
