# 月球基地轮腿机器人训练场

用 Aholo Lux3D 生成月球基地还不存在的物体，把它们转成可碰撞的障碍，放进月球重力下的
MuJoCo 场景，让 Go2W 轮腿机器人跑测试，并留下可复核的配置、结果、失败证据和回放。

**核心表述**：用生成模型扩展机器人测试场景，把生成物体转成可碰撞、可重复测试的障碍，
记录机器人在哪些条件下失败。

**本轮不做**：不训练强化学习、不接 Isaac、不模拟月壤、不做真实机器人迁移、不建服务端。

---

## 环境要求

| 项 | 要求 |
| --- | --- |
| Python | 3.12（实测 3.12.3） |
| CPU | 4 核可用（实测环境 4 核 / 7 GB，**无 GPU**） |
| 磁盘 | 约 1.5 GB（含机器人模型 411 MB） |
| 系统 | Linux；基础仿真**不需要** OpenGL |

依赖版本锁定在 `requirements.txt`（mujoco 3.17.0 / numpy 2.5.4 / trimesh 5.2.0 /
coacd 1.0.14 / manifold3d 3.5.4 / pillow 13.0.0）。只锁真实跑通的组合。

## 干净安装

```bash
git clone https://github.com/codezzzsleep/lunar-wheelleg-testbench
cd lunar-wheelleg-testbench
./setup.sh          # 建 venv、装锁定依赖、拉取固定提交的机器人模型、跑第 1 关验收
```

`setup.sh` 会把 `vendor/unitree_mujoco` 切到固定提交
`1eb6642e3f3fdfb7fb13a9794fd6a2dd93ea0e7d`。模型已存在则复用，不会重复下载。

手动安装：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
git clone https://github.com/unitreerobotics/unitree_mujoco vendor/unitree_mujoco
git -C vendor/unitree_mujoco checkout 1eb6642e3f3fdfb7fb13a9794fd6a2dd93ea0e7d
```

## 快速测试（第 1 关验收）

```bash
.venv/bin/python scripts/gate1.py --out runs/gate1
```

四项：模型加载与重力冒烟、几何碰撞对照（凸包 vs CoACD）、Lux3D 资产进入考场并接触、
平地驱动（两种站姿越过终点）。全部用函数返回值判定，**不读任何历史文件**；退出码非零即失败。

回归测试：

```bash
.venv/bin/python -m unittest discover -s tests -v      # 35 项，约 20 秒
```

## 一场演示 / 一次正式批跑

```bash
# 冒烟：20 个 trial，约 6 秒
.venv/bin/python scripts/demo.py --suite smoke --out runs/smoke_$(date +%s)

# 正式：2520 个 trial（35 个**选中**资产 × 2 站姿 × 3 控制器 × 12 横向偏移）
.venv/bin/python scripts/demo.py --suite canonical --out runs/canonical_r2

# 续跑（只补缺失任务，校验身份；不要用它重跑已有记录）
.venv/bin/python scripts/demo.py --suite canonical --out runs/canonical_r2 --resume

# 分析（只读显式指定的结果文件）
.venv/bin/python scripts/analyze.py --input runs/canonical_r2/results.jsonl --out runs/canonical_r2
```

运行目录结构：

```
runs/<run_id>/
  config.json       本批配置与 trial 清单
  environment.json  代码提交、模型提交、包版本、CPU、是否含未提交修改
  results.jsonl     逐 trial 原始记录（唯一事实来源）
  summary.json      分组汇总
  report.md         分析产出
  figures/  replays/  logs/
```

**实测成本**（4 核 / 7 GB / 无 GPU）：canonical 2520 个 trial，3 个 worker，
约 **672 秒**。目录里 49 个可用资产中实际选中 35 个，`config.json` 分别记录
`available_asset_count` 与 `selected_asset_count`，不要把 49 写成参与资产数。

批次隔离：新运行只接受空目录；续跑必须 `--resume` 且校验 suite、完整任务集合与
运行身份（控制参数 / 资产指纹 / 模型 / 仿真源码）。想重跑就换新目录，工具不会覆盖证据。

## 回放

```bash
apt-get install -y libosmesa6          # 仅渲染需要
export MUJOCO_GL=osmesa

python scripts/replay.py --run runs/canonical --trial <trial_id>
```

回放是**重演**（re-simulation），不是轨迹回放：它走与考试完全相同的控制路径
（`exam.run` 的同一份代码），并校验 `final_x` / `max_tilt_deg` 与记录一致；
不一致会以非零退出码报错，不会把近似结果当成原轨迹。

## 三个考生的真实能力

| 考生 | 做什么 | 实测边界 |
| --- | --- | --- |
| `hold` | 锁死站姿 + 轮速伺服，本质是四轮小车 | 障碍低于 0.6 倍轮半径几乎必过；越过 1.1 倍后大量倾覆 |
| `step` | 被挡住时执行一次固定序列：前腿缩短、后腿伸长，把机头抬起来 | 在 1.51 倍这一档明显优于 hold；1.76 倍以上基本无效 |
| `adapt` | 只用**机体前进速度 + 机体倾角**（不读轮速）在"抬腿 / 加大力矩"之间二选一 | 与 step 同级；**不会**按形状调整落脚点 |

三者都是**手工控制器**，不是学出来的技能。`adapt` 的"自适应"仅指上述二选一，
不能读作"学会了越障"。

## 当前支持的物理条件与不支持的

**支持**：月球重力 1.62 m/s²、刚性平面地面、静态刚性障碍（CoACD 凸块分解）、
两种站姿、确定性横向偏移网格。

**不支持**：月壤沉陷 / 可变形地面、摩擦参数标定、动态或可翻倒的残骸、
真实深度传感器噪声、任意非凸凹槽（MuJoCo 对闭合网格按凸包碰撞，必须先拆凸块）。

## 常见错误

| 现象 | 原因 / 处理 |
| --- | --- |
| `找不到 go2w 模型` | 未拉取模型。运行 `./setup.sh` 或按上文手动 clone |
| `MUJOCO_GL` 相关报错 | 只有渲染需要；`export MUJOCO_GL=osmesa` 并安装 `libosmesa6` |
| 报告中文字体变方块 | 设置 `RLL_FONT=/path/to/font.ttc`；找不到字体时图内标签自动降级为英文并在报告里提示 |
| `precheck_failed` | 资产不合格（缺 parts / manifest pass=false / 尺寸异常），**不是**机器人的失败，计数与 outcome 分开统计 |
| `trial_id 重复` | 配置相同被当成不同任务；检查 suite 生成逻辑 |

## 已知局限

- 横向偏移是**确定性网格**，不是随机采样；完成率只描述这张网格，不能外推。
- 同一资产的多个偏移不是多个独立形状家族；未做家族留出，**不能**声称泛化能力。
- 障碍物是静态刚性体，不滚动、不翻倒。
- 完成判据是「机体中心越过障碍后方 0.25 m 净空」，不等于整机完全通过。
  「完成数」是终点任务完成数，含未接触障碍物的场景，不等于「越障成功数」。
- box 与 mesh 匹配的是**相对高度与横向宽度**，前后长度未必相同；不写"尺寸完全相同"。
- 同高度对照的条目来自少量几何对在不同考生与站姿下的重复比较，**不是独立形状样本**，
  不做显著性推断。
- 分层 L3 含多个高度，「同属 L3」不等于「同高度」；引用斜坡/方块的差异时要给精确高度。
- **包围盒尺寸不足以单独刻画越障表现**：在本批固定场景网格中，不同几何体呈现不同完成
  分布。这是一项有限观察，不是机制已验证，也不是新的通用难度指标。

## 目录

```
scripts/
  构建：build_scene.py / procedural.py / process_asset.py / build_library.py
  运行：exam.py / controllers.py / demo.py / runio.py / analyze.py / replay.py
  验收：gate1.py / check_collision.py
assets/raw/        7 个 Lux3D 原始 GLB
assets/processed/  处理后资产（parts/*.stl + manifest.json）
runs/canonical/    本次正式运行的完整记录与报告
docs/              执行清单、状态说明
tests/             关键回归测试
```

## 来源与许可

- 机器人模型：[unitreerobotics/unitree_mujoco](https://github.com/unitreerobotics/unitree_mujoco)
  （固定提交），按其仓库许可使用。
- 3D 生成：[Aholo Lux3D](https://www.aholo3d.cn)，资产由本项目生成。
- 凸块分解：[CoACD](https://github.com/sarahweiii/CoACD)（MIT）。
