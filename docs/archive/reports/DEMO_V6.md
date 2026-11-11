# DEMO_V6 · 观测约束融合与连续回放（2–3 分钟）

录制前启动静态页：

```bash
cd /var/lib/deepseek-harness/lunar-lab
.venv/bin/python -m http.server 8093 --directory runs/unseen/delivery_v6/v6_20261029/media/replay
# 浏览器打开 http://127.0.0.1:8093/
```

本页只读已落盘真实产物；打开页面不触发 API。

## 0:00–0:20 看见

画面：首视角 RGB / mask / 公开可见量（x_front 1.6357 m、W_vis 0.1558、H_vis 0.3319）。

口播：机器人只能看见障碍正面；深度只用于可见面分割与位置/尺度，隐藏真值不进入规划器。

## 0:20–1:00 生成与融合

画面：raw H5 face12k、H5-F 5 mm、B3-F 5 mm 三张对照。

口播：
- raw H5 strict fail（P95 11.0 mm、freespace 0.5106）；
- H5-F 把可见面约束到 RGB-D，再保留父候选 generated_hidden；
- B3-F 用镜像先验 + 同一融合器；
- H5-F 5 mm 可见几何 IoU 0.9475、P95 2.82 mm、freespace 0.0376，过 strict；
- **但这是构造的可见面，不是 Lux3D 自己重建准确的证明**。

## 1:00–1:40 试走 vs 真值

画面：候选上 L2 成功 GIF → 真值 L2 超时 GIF → 真值 S1 成功 GIF。

口播：
- 候选预测 L2 3/3、均值 6.10 s；真值 L2 2/3，seed0 30.02 s 超时；
- 一个 false safe；
- 同初态真值 S1 3/3；预测把 L2 排在 S1 前 0.3 s，这个优势不成立。

## 1:40–2:10 碰撞保真与同条件比较

画面：碰撞表 / matched 表。

口播：
- H5-F CoACD 32 部件占据 IoU 0.284；64 部件 0.286，仍不可靠；
- 因此 H5-F 在同条件表里选 S1 3/3 + 验证 5/5，只能算**诊断**，不能归因于隐藏几何；
- raw H5 2/3、B0 0/3、B3-F A0；benefit=NOT_ESTABLISHED。

## 2:10–2:30 第二观察与月壤

画面：真实触发记录；月壤静载表。

口播：
- H5-F S1 vs B3-F A0 触发第二观察；第二视角两者都保留（no_rejection）；worst-case 选 A0，真值 A0 abort；
- 月壤改为 brake_step 真正静态：稳定、12 个接触；公式 9.75 mm，实测轮底 −0.893 mm；整机几何下陷未实现。

## 收尾字幕（固定）

输入是仿真 RGB-D；执行是独立仿真，不是真实机器人；H5-F 可见面由构造得到；B3-F 不是 Lux3D；fixture 不计收益；benefit=NOT_ESTABLISHED。
