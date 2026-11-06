# REVIEW_V6_R1 补充：素材包必须带"实际仿真用的模型"

- 复核基线：`5117ce6f5`
- 请原文保存为 `docs/v6/REVIEW_R1_ADD.md`，与 REVIEW_R1 一起执行。

## 1. 负责人用 7 个 WP7 单元实际渲染，发现场景与轨迹对不上

| 单元 | 问题 |
| --- | --- |
| `A2_gravel` | `scene_spec.objects` 为空，碎石只存在于 `scene/coll/manifest.json`（44 个 box），场景描述里没有引用。用包里的场景重放，地面上没有碎石。 |
| `B1_boulder_detour` | `scene_spec.objects` 为空。包里同时有三样东西，彼此对不上：<ul><li>`assets/body_world.stl`：moon_rock_05，pose.json 写平移 0.5 m，放下后正好压在机器人路径上；</li><li>`coll/coll_wp7_boulder`：两个 0.5 × 0.5 × 0.32 m 的方块，位于 y = ±0.3–0.8，构成一道门；</li><li>`cache_invalidated.json`：说明缓存已失效。</li></ul>轨迹在 x ≈ 2.7 处横向偏到 y = −0.52，可那里没有任何障碍。这个包到底仿真的是哪个场景，无法判断。 |

所以 §4 重放检查"最大穿透 0 mm"的通过是空洞的：场景里本来就没有障碍物，穿透当然为 0。

## 2. 要求：每个包都带编译后的真实模型

1. 构造 `WheelLegEnv` 后立即调用 `mujoco.mj_saveLastXML`，或把 `env._xml` 写成 `scene/compiled/model.xml`。
   - 把它引用的全部资产（mesh、hfield PNG、box 部件）复制到 `scene/compiled/` 下，路径改成相对路径；
   - 这一份就是仿真实际用的模型，其他场景描述都只作参考。
2. 重放检查改为直接加载 `scene/compiled/model.xml`。同时：
   - 报告 `ngeom`，以及障碍物 geom 的数量和名单；
   - 报告整条轨迹上"机器人与每个障碍物的最小距离"；
   - 场景名或报告里提到障碍（碎石、巨石、坑、岩石）而 `model.xml` 里没有对应 geom 的，判不通过；
   - 绕行类场景，横向偏移最大处的前后 1 m 内必须有障碍物，否则判不通过并写原因。
3. 岩石的贴图模型另放在 `scene/visual/<rock_id>/`：`body_vis.obj` + `texture.png` + 世界变换（4×4），与 `compiled` 里的碰撞几何对应。没有贴图的物体写明"无贴图"。
4. 7 个 WP7 单元和 M3 全部按此重新打包、重新检查。B1 必须先查清实际仿真的是哪个场景，再决定保留还是重跑。

## 3. 渲染端已确认可用

负责人已经用 MuJoCo 加载 go2w、仓库的地形生成器和 Poly Haven 扫描岩石贴图，渲染出这几个单元的真实帧。

所以素材包只要满足以上要求，就能直接进成片，不需要别的格式。
