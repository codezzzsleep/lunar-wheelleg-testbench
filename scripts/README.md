# 脚本导航

`scripts/` 磁盘上 437 个 `.py`（入库 431 个），其中 410 个平铺在根目录（入库 405）；没有 `__init__.py`，靠 `sys.path.insert` + 裸名字 import 互相调用。

## 按代次分组

| 分组 | 个数 | 当年解决的问题 | 现在还用吗 |
|---|---|---|---|
| `v3_*` | 58 | 单状态岩石、fusion/align、G6 交付页 | 否，只是 v3 证据来源 |
| `v4_*` | 28 | 展示场景与资产 WP | 否 |
| `v5_*` | 20 | V5 核心规范、六方法对照 | 否 |
| `v6_*` | 58 | Lux3D 接入、碰撞保真、路由包 | 否，个别函数被复用 |
| `v7_*` | 64 | 路线、遭遇、shadow 实验 | 部分，V7 收尾对照 |
| `scripts/v7/` | 12 | V7 规范实现 | 是，对照用 |
| `scripts/v8/` | 10（另有 1 个未入库的新脚本，磁盘上共 11 个） | 当前主线 | 是 |
| `scripts/legacy/` | 4 | 早期批跑与渲染 | 否 |
| 无前缀公共模块 | 168 | 地形、环境、规划、客户端、卫生检查 | 是 |

## 现行入口

| 脚本 | 一句话用途 | 典型命令 |
|---|---|---|
| `scripts/v8/v8_run.py` | V8 主程序：三车同场景 | `MUJOCO_GL=egl python3 scripts/v8/v8_run.py --policy conservative --out runs/v8/test` |
| `scripts/v8/v8_eval.py` | 赛后复盘，拿真值比 | `python3 scripts/v8/v8_eval.py --run runs/v8/main` |
| `scripts/v8/v8_replay_diff.py` | 重放与原始观测差异取证 | `python3 scripts/v8/v8_replay_diff.py runs/v8/main/imagination/looks/look2` |
| `scripts/common_planner.py` | 预演与决策唯一实现 | 被 import，无 CLI |
| `scripts/eval_six.py` | 六方法评测 | `python3 scripts/eval_six.py --protocol plans/unseen_v2_protocol.json --out runs/unseen/recovery_r3/six` |
| `scripts/terrain.py` | 地形/场景高度场 | 库 |
| `scripts/wheelleg_env.py` | 轮腿物理环境 | 库 |
| `scripts/lux3d_client.py` | Lux3D，密钥只走 `AHOLO_API_KEY` | `python3 scripts/lux3d_client.py --status <taskId>` |
| `scripts/check_repo_hygiene.py` | 仓库卫生自检（只读） | `python3 scripts/check_repo_hygiene.py --strict` |

## 已知坑

1. 无 `__init__.py`，靠裸名字 import：**重命名任何脚本即断链**。
2. `terrain.SPAN` 是模块级全局，运行期会被 `scripts/v7/v7_route.py:42`、`scripts/v7/v7_redecide.py:39`、`scripts/v8/v8_scene.py:71,156` 改写，**它会改变物理结局**——跑预演必须在产物里记下它。
3. 部分脚本在顶层 import 期就读 `runs/` 产物，缺文件即 import 失败。
4. 有脚本硬编码 `/workspace/lunar-lab`（历史沙箱），换机器要注意。

## 判断某脚本是否还在用

```
rg -n "<脚本名>" scripts docs | grep -v "^scripts/<脚本名>"
```

5. **跑测试会重写 `scenes/*.json`**（`tests/test_pipeline.py` 以仓库根为 cwd 跑 `pipeline.py --demo`，
   第一步 `make_pg_scenes.py` 会把场景集写回 `scenes/`）。2026-11-11 起夹具已与生成器同步
   （唯一历史差异是 `terrain.span` 字段），生成是幂等的：跑完 `git status` 应当干净。
   若不干净，说明生成器改了而夹具没跟着提交 —— 补一次 `python3 scripts/make_pg_scenes.py` 再提交即可。
