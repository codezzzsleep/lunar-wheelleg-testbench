# REVIEW_V7_R3：E1 动作不一致的原因与 V7 收尾

- 下达：项目负责人
- 复核对象：`main` 提交 `f550ad35f`
- 地位：SPEC_V7、REVIEW_V7_R1、REVIEW_V7_R2 的补充，冲突时以本文为准。
- 随本文附补丁包 `v7_3_patch.tar.gz`。

---

## 0. 复核结论

### 0.1 你的执行与停下回报都正确

- 补丁安装、真值检查、重新决策、数据拉回与校验都符合要求；
- 发现动作不一致后按 R2 §2.2 停下，没有改代码、没有重跑路线，处理正确。

### 0.2 原因：预演用的平地不是同一张

两次计算都是对的，而且各自都能逐位复现。差别来自预演场景的地面。

**地面从哪来：**

- 预演场景的平地是一张高度场；
- 场景 spec 里没写边长时，它的半边长取模块全局变量 `terrain.SPAN`。

**两次运行里这个值不同：**

| 运行 | 进程 | `terrain.SPAN` | 高度场网格 |
| --- | --- | --- | --- |
| `route_full_r2` | 路线进程：`v7_route.route_spec` 先把它设成了 32 | 32 m | 1 m 一格 |
| `route_full_r2_v72` | 单独运行 `v7_redecide`，没有改它 | 默认 4 m | 0.125 m 一格 |

**为什么结局会不同：**

- 两张地面都是平的，但网格尺寸不同，接触计算在 10⁻¹² 量级上不一样；
- E1 的直行（R1）要压过 22 cm 的石头，轮子和小腿都会擦到，是临界动作；
- 对这种动作，物理过程是混沌的，微小差异会被放大成不同结局。

**责任：** 负责人写的 `v7_redecide` 没有复现路线进程里的这个设置。与你的执行无关。

### 0.3 证据（负责人本机复现）

对象：OBS_CONS 实心几何上的 R1 预演，三种扰动。表中是每种扰动第一段轨迹的哈希（前 10 位）。

| 来源 | `terrain.SPAN` | 扰动 0 | 扰动 1 | 扰动 2 |
| --- | --- | --- | --- | --- |
| `route_full_r2`（路线进程） | 32 | `eb0ea28f66` 成功 | `c1c8e91bae` 成功 | `f13b006e07` 成功 |
| 负责人本机 | 32 | `eb0ea28f66` 成功 | `c1c8e91bae` 成功 | `f13b006e07` 成功 |
| `route_full_r2_v72`（沙箱单独运行） | 4 | `51393b5aed` 卡住 | `ba6c466f99` 成功 | `939aa7d89d` 成功 |
| 负责人本机，连跑两次 | 4 | `51393b5aed` 卡住 | `ba6c466f99` 成功 | `939aa7d89d` 成功 |

- 同一个 `SPAN` 下，沙箱与负责人本机逐位相同，同一台机器连跑两次也逐位相同；
- 碰撞几何（`coll_obs_solid/manifest.json`）与初始状态在两次运行里逐位相同；
- `SPAN` 4 与 32 两条轨迹从第 25 帧开始出现 10⁻¹² 级差异：
  - 32 m 地面上越过石头，7 秒到终点；
  - 4 m 地面上卡住，120 秒超时。

### 0.4 对 E1 结论的影响

| 预演地面 | 准入候选 | 直行 R1 在几份里安全 | 多数规则选中 | 最坏规则 | OBS_CONS |
| --- | --- | --- | --- | --- | --- |
| 32 m（与路线相同） | B1、B2、C1 | 2/3（B1、C1） | **R1** | R2 | R2 |
| 4 m（`route_full_r2_v72`） | B1、B2、C1 | 1/3（C1） | D2 | D2 | D2 |

- 在路线自己的预演条件下，v7.2 的决策是 R1，与实际执行相同，也与 R2 §0.3 一致；
- 但 R1 的"安全"判定会被一个与物理无关的数值设置翻转，这个判定**不稳健**；
- 这条结论如实写进 STATUS。

### 0.5 V7 收尾

- 不重跑路线；
- V7 的叙事已由 V8 取代，R2 §4 的成片入库取消；
- `route_full_r2_v72` 保留，作为 4 m 地面下的计算记录。

---

## 1. 安装补丁

1. 把 `v7_3_patch.tar.gz` 解到仓库根目录，按包内 `PATCH_SHA256.txt` 校验。包内文件：

   ```
   scripts/v7/v7_redecide.py      新增 --span（默认 32，与路线进程相同），summary 记 rehearsal_ground_span_m
   scripts/v7/v7_determinism.py   新增：同一预演重跑若干次，逐帧对比，并与已有运行的记录对比
   docs/v7/REVIEW_V7_R3.md        本文
   ```

2. `python3 -m py_compile scripts/v7/*.py`
3. 提交并推送：`v7.3: redecide reproduces the route's rehearsal ground (terrain.SPAN=32)`。

---

## 2. 在沙箱上运行（不调用 Lux3D）

一个一个跑，每跑完一步就拉回、校验、推送，`SANDBOX_LOG.md` 各记一行。

### 2.1 可复现性检查（两次，各约 5 分钟）

```
MUJOCO_GL=egl python3 scripts/v7/v7_determinism.py --obs runs/v7/route_full_r2/E1/look1 \
    --out runs/v7/determinism_e1_span32 --span 32 --repeat 2 \
    --ref runs/v7/route_full_r2/E1/decide_look1/OBS_CONS/solid \
    --ref runs/v7/route_full_r2_v72/E1/decide_look1/OBS_CONS/solid

MUJOCO_GL=egl python3 scripts/v7/v7_determinism.py --obs runs/v7/route_full_r2/E1/look1 \
    --out runs/v7/determinism_e1_span4 --span 4 --repeat 2 \
    --ref runs/v7/route_full_r2/E1/decide_look1/OBS_CONS/solid \
    --ref runs/v7/route_full_r2_v72/E1/decide_look1/OBS_CONS/solid
```

预期（看 `summary.json` 的 `compare`）：

| 运行 | rep0 与 rep1 | 与 ref0（`route_full_r2`） | 与 ref1（`route_full_r2_v72`） |
| --- | --- | --- | --- |
| `--span 32` | 三种扰动都相同 | 三种扰动都相同 | 扰动 0 不同 |
| `--span 4` | 三种扰动都相同 | 扰动 0 不同 | 三种扰动都相同 |

### 2.2 按路线条件重新决策（约 1–1.5 小时）

```
MUJOCO_GL=egl python3 scripts/v7/v7_redecide.py --run runs/v7/route_full_r2 --out runs/v7/route_full_r2_v73
```

预期：

- 退出码 0，`all_same: true`；
- `summary.json` 里 `rehearsal_ground_span_m: 32.0`；
- E1：采纳 3/6，`full_chosen = R1`，`worst_rule = R2`，`obs_chosen = R2`；
- E2：look1 拒绝 0/4，look2 采纳 1/3（M2），`full_chosen = R1`。

### 2.3 影子实验重新评估

按 R2 §2.3 运行，不涉及物理预演：

```
python3 scripts/v7/v7_shadow_exp.py --evaluate --out runs/v7/shadow_exp
```

---

## 3. 回报

在 `docs/v7/STATUS.md` 追加：

- 补丁提交号；
- §2.1 两份 `summary.json` 的 `platform` 与 `compare`；
- `route_full_r2_v73/summary.json` 的 `compare`，以及 E1 的 `votes`；
- 影子实验新的 `summary.json` 原文；
- 一段结论，照抄如下：

  > E1 直行（R1）的预演判定依赖预演地面的高度场尺寸：路线条件（32 m）下 R1 在 2/3 份准入候选里安全，决策为 R1，与实际执行相同；4 m 地面下只在 1/3 份里安全，决策为 D2。两种地面都是平的，差别只在数值层面，说明这个临界动作的安全判定不稳健。V7 到此收尾，不重跑路线。

数字与 §2 的预期不一致时如实写出，不要改代码。

---

## 4. 规则

- 不改 `scripts/v7/`（本补丁除外）、不改门槛；
- 不重跑路线，不调用 Lux3D；
- 遇到与本文不一致的情况，停下回报。
