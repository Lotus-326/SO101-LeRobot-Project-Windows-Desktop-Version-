# SO-ARM101 × LeRobot 机械臂抓取项目（Windows 落地版）

把 Seeed Studio 官方教程
[《基于 LeRobot 的 SO-ARM100 / SO-ARM101 机械臂入门教程》](https://wiki.seeedstudio.com/cn/lerobot_so100m_new/)
完整落到 **Windows 11 + NVIDIA RTX 4060 Laptop** 上的一套可执行工程：
从环境安装、校准、遥操作、数据采集、ACT 训练到上机评估的全链路脚本、中文文档与排障手册。

> **本机硬件**：SO-ARM101（12 V 5 A 电源 + 独立主从双板）、Orbbec Gemini 2 深度相机
> **软件栈**：Python 3.13.7 + PyTorch 2.7.1+cu128 + LeRobot 0.4.4（Seeed `DepthCameraSupport` 分支）

---

## 目录

- [一、项目成果（先看结论）](#一项目成果先看结论)
- [二、硬件与环境](#二硬件与环境)
- [三、目录结构](#三目录结构)
- [四、完整流程：7 个阶段](#四完整流程7-个阶段)
- [五、专业知识：这套流程背后的原理](#五专业知识这套流程背后的原理)
- [六、踩坑与关键决策记录](#六踩坑与关键决策记录)
- [七、命令速查](#七命令速查)
- [八、录制时的按键](#八录制时的按键)
- [九、排障索引](#九排障索引)
- [十、离线资料与参考链接](#十离线资料与参考链接)

---

## 仓库说明：这里有什么、没什么、怎么重建

本仓库**只提交可复现的源码、文档和证据**。体积极大或可重新下载的东西一律不纳入版本管理。

| 不在仓库里的东西 | 体积 | 怎么重建 |
| --- | --- | --- |
| `.venv\` Python 虚拟环境 | **6.9 GB** | `scripts\setup-env.ps1` |
| `lerobot\` LeRobot 仓库本体 | 675 MB | `scripts\setup-env.ps1` 自动 clone |
| `tools\ffmpeg-*\` | 496 MB | `scripts\setup-env.ps1` 下载 |
| `tools\Seeed_RoboController\` | 0.5 MB | `scripts\12-steering-tool.ps1 -Action setup` |
| 数据集（98 条训练集 + 评估集） | 490 MB | 自行采集，或从 HuggingFace Hub 拉 |
| 模型检查点 `040000` | 591 MB | 用本仓库脚本重新训练（4 万步约 3.7 小时） |

**关键点：对 `lerobot\` 的所有修改都已固化成 `patches\*.patch`。**
重新 clone 后跑一次 `scripts\apply-patches.ps1`，环境和代码就能完整重建 ——
所以排除 `lerobot\` 不会丢失任何本项目的工作。

仓库内保留的证据（`assets\`，共 3.8 MB）：

| 文件 | 内容 |
| --- | --- |
| `train_positions_labeled.png` | 训练时 5 个抓取位置在画面中的位置与各自条数 |
| `untrained_point.png` | 泛化测试用的未训练点（红色十字）位置 |
| `REFERENCE_from_dataset.png` | 训练数据首帧 —— 用来核对相机取景是否变动 |
| `front_mark1~5.png` | 采集期 5 个标记点的历史取景快照 |
| `train-act.log` | 4 万步训练的完整 loss/grdn 曲线日志 |

---

## 一、项目成果（先看结论）

### 官方教程 7 步全部跑通

| 教程步骤 | 完成情况 | 关键证据 |
| --- | --- | --- |
| 1. 安装 LeRobot 环境 | ✅ | LeRobot 0.4.4 + torch 2.7.1+cu128，RTX 4060 8 GB 实算通过 |
| 2. 机械臂组装 | ✅ | COM10 = 白从臂（Follower），COM11 = 黑主臂（Leader） |
| 3. 校准机械臂 | ✅ | 5 关节幅度增益 **0.99 / 1.00 / 0.97 / 0.95 / 1.00x**，舵机 EEPROM ↔ JSON 逐位一致 |
| 4. 遥操作控制 | ✅ | 主从跟随误差与幅度对齐均已量化验收 |
| 5. 采集数据集 | ✅ | **98 条 / 21525 帧 / 298 MB**，5 个位置 |
| 6. 训练 ACT | ✅ | **40 K 步，loss 7.47 → 0.059**，权重 197 MB / 234 张量 |
| 7. 推理 & 自主操控 | ✅ | **固定位置 10/10 = 100%** 自主完成"抓起 → 放入纸箱" |

### 评估成绩（同一把尺子量出来的）

| 测试 | 成功率 | 说明 |
| --- | --- | --- |
| **同一个训练点重复 10 次** | **10/10 = 100%** | 精度与可复现性都合格 |
| **5 个训练点各 2 次** | **6/10 = 60%** | 分布内可用，位置间差异大 |
| **训练点之间（未训练位置）** | **0/10 = 0%** | 完全失效 —— 见 [5.4](#54-模仿学习的泛化边界为什么它只认那几个点) |

逐点表现：`(288,240)` 100% · `(323,203)` 100% · `(348,298)` 0% · `(494,262)` 50% · `(512,231)` 50%

### 一句话结论

> **模型本身是好的**（离线复现示范的误差仅 **0.9%**），在训练位置上 100% 成功；
> 它做不到的是**位置泛化** —— 因为示范只覆盖 4~5 个离散点，模型没有机会学到
> "方块在画面哪儿就往哪儿够"这个**连续关系**。
>
> 这正好是**官方教程的边界**（教程采集 50 条、基本固定一个位置，目标就是单点自主抓取）。
> 本项目的 98 条 / 5 位置 / 100% 已经在数据量和覆盖面上超过了教程目标。

---

## 二、硬件与环境

### 硬件清单

| 部件 | 型号 / 说明 |
| --- | --- |
| 从臂（Follower） | SO-ARM101 白色，12 V 供电，6 舵机（ID 1~6，型号 777 = STS3215） |
| 主臂（Leader） | SO-ARM101 黑色，5 V 供电，同型号舵机 |
| 总线 | 两个独立 USB 串口板 → `COM10` / `COM11` |
| 相机 | Orbbec Gemini 2，序列号 `AY6KC5200FP`，640×480 @30 fps |

> ⚠️ **底盘/舵机不能混用电源**：主臂 5 V、从臂 12 V，接错会烧舵机。

### 舵机 ID 约定（主从一致）

| ID | 关节 | 舵机型号 |
| --- | --- | --- |
| 1 | `shoulder_pan` 底座旋转 | 777 (STS3215) |
| 2 | `shoulder_lift` 肩部抬升 | 777 |
| 3 | `elbow_flex` 肘部弯曲 | 777 |
| 4 | `wrist_flex` 腕部俯仰 | 777 |
| 5 | `wrist_roll` 腕部自转 | 777 |
| 6 | `gripper` 夹爪 | 777 |

### 软件版本（必须对齐）

| 组件 | 版本 | 为什么要这个版本 |
| --- | --- | --- |
| LeRobot | **0.4.4**（Seeed `DepthCameraSupport` 分支） | 官方 `main`(0.6.2) **没有 Orbbec 相机后端** |
| Python | 3.13.7（`D:\python` 建独立 venv） | 分支要求 `>=3.10`，且不污染系统 Python |
| PyTorch | 2.7.1+cu128 | 分支要求 `torch>=2.2.1,<2.8.0`；RTX 4060 (sm_89) 支持 |
| 视频编解码 | PyAV (`av`) | 0.4.4 的 `encode_video_frames()` 直接用 PyAV，不再 shell out 到 ffmpeg |
| ffmpeg | 附带 `libsvtav1` 编码器 | 仅作备用（`tools\ffmpeg-*`） |

---

## 三、目录结构

```
LeRobot\
├─ README.md                  ← 本文件（总览 + 流程 + 原理 + 踩坑）
├─ docs\                      ← 分阶段中文文档
│   ├─ 00-环境安装.md          01-硬件与接线.md        02-整臂校准.md
│   ├─ 03-遥操作.md            04-相机接入.md          05-数据采集.md
│   ├─ 06-数据集检查与回放.md   07-训练-ACT.md          08-上机评估.md
│   ├─ 09-Windows排障FAQ.md    10-数据集工具.md        11-舵机调试工具.md
│   └─ 进度清单.md             ← 全项目打勾清单
├─ scripts\                   ← Windows 一键脚本（全部支持 -? 看用法）
│   ├─ config.ps1             ★ 唯一需要你改的配置文件
│   ├─ _common.ps1            公共函数（PATH、配置导入、日志）
│   ├─ setup-env.ps1          环境安装        apply-patches.ps1   打补丁
│   ├─ 00-check-env.ps1       环境自检        01-find-port.ps1    查串口
│   ├─ 02-setup-motors.ps1    舵机 ID 配置    03-calibrate.ps1    整臂校准
│   ├─ 04-teleoperate.ps1     遥操作          05-find-cameras.ps1 查相机
│   ├─ 06-record.ps1          数据采集        07-replay.ps1       回放
│   ├─ 08-dataset-viz.ps1     数据集可视化    09-train.ps1        训练
│   ├─ 10-eval.ps1            上机评估        11-edit-dataset.ps1 数据集增删改
│   ├─ 12-steering-tool.ps1   舵机调试 GUI    14-calibrate-arm.ps1 强化校准
│   ├─ 15-preflight-calib.ps1 校准体检        16-middle-calibrate.ps1 中位校准
│   ├─ 17-snapshot.ps1        抓样张          18-gonogo.ps1       采集前 GO/NO-GO
│   ├─ 19-marker-check.ps1    逐点取景        20-sync-calib.ps1   校准写回舵机
│   └─ shell.ps1              进入已激活环境的终端
├─ _tools\                    ← Python 辅助工具（被 scripts 调用）
│   ├─ env_report.py          环境自检报告     check_cameras_spec.py 相机片段语法
│   ├─ calibrate_arm.py       强化校准（推满行程）  soarm_middle_calibrate.py 中位校准
│   ├─ preflight_calib.py     校准只读体检     sync_calibration.py 校准写回
│   ├─ check_teleop_accuracy.py 幅度对齐检查   teleop_probe.py     实时跟随探针
│   ├─ snapshot.py            抓帧+红色块度量  marker_check.py     逐点取景
│   ├─ gonogo.py              7 项 GO/NO-GO     dataset_audit.py    数据集体检
│   ├─ eval_score.py          评估成功率打分   servo_diag.py       舵机级诊断
│   └─ to_utf8bom.py          .ps1 编码修复
├─ patches\                   ← 对 Seeed 分支的必要修补（.patch）
├─ lerobot\                   ← LeRobot 仓库（git clone，含本地补丁）
├─ .venv\                     ← Python 虚拟环境
├─ tools\ffmpeg-*\bin\        ← ffmpeg（含 libsvtav1）
├─ tools\Seeed_RoboController\← 舵机调试 GUI（git clone）
├─ assets\                   ← 截图与证据（5 个位置标注图、取景参照、训练曲线）
├─ _wiki\                     ← 官方 Wiki 全文离线快照 + PDF 规格书
└─ outputs\                   ← 工具运行记录
```

数据集、校准文件默认位置：

```
%USERPROFILE%\.cache\huggingface\lerobot\
├─ calibration\
│   ├─ robots\so_follower\<FollowerId>.json           ← 从臂校准
│   └─ teleoperators\so_leader\<LeaderId>.json        ← 主臂校准
└─ <owner>\<repo_id>\                                 ← 数据集本体
```

---

## 四、完整流程：7 个阶段

> ⚠️ **安全第一**：任何会让机械臂动起来的命令之前，请清空 1 米范围内的贵重/易碎物品，
> 固定好机械臂，确认电源与线缆，人员保持安全距离。
> 出现异响 / 异常运动 / 通信中断请**立即 Ctrl+C 并断电**检查。

### 阶段 A：软件环境（不需要接硬件）

```powershell
cd "D:\机电创新实验室\智能装备实验室 m1机械臂抓取\LeRobot"

# A1 安装环境（约 3.3 GB 下载，30~45 分钟，只需一次）
powershell -ExecutionPolicy Bypass -File scripts\setup-env.ps1

# A2 给 Seeed 分支打必要补丁（re-clone 后必须重跑）
powershell -ExecutionPolicy Bypass -File scripts\apply-patches.ps1

# A3 环境自检（CUDA / lerobot 命令 / 依赖 / 串口）
powershell -ExecutionPolicy Bypass -File scripts\00-check-env.ps1

# A4 装舵机调试 GUI（可选，但排障时非常有用）
powershell -ExecutionPolicy Bypass -File scripts\12-steering-tool.ps1 -Action setup
```

**判据**：`A3` 末尾输出「Python 侧全部通过」。

**为什么必须先打补丁**：Seeed 分支的 `cameras/utils.py` 里访问了 `config.copy`，
而 `OpenCVCameraConfig` 没有这个字段 —— **任何带 opencv 相机的遥操作/采集/评估都会直接崩**。
补丁清单见 [第六节](#六踩坑与关键决策记录)。

### 阶段 B：硬件接入与校准

```powershell
# B1 查串口（本机 COM3~COM8 是蓝牙虚拟串口，认准 Kind=USB 那两个）
powershell -ExecutionPolicy Bypass -File scripts\01-find-port.ps1
#    → 把 COM 号填进 scripts\config.ps1 的 FollowerPort / LeaderPort
#    → 也可以用 01-find-port.ps1 -SetFollower COM10 -SetLeader COM11 自动写回

# B2 查相机，拿 Orbbec 的序列号填进 config.ps1 的 Cameras
powershell -ExecutionPolicy Bypass -File scripts\05-find-cameras.ps1 -Backend orbbec

# B3 整臂校准（从臂、主臂各一次）
powershell -ExecutionPolicy Bypass -File scripts\03-calibrate.ps1 -Arm follower
powershell -ExecutionPolicy Bypass -File scripts\03-calibrate.ps1 -Arm leader

# B4 ★ 推荐用强化版校准（必须把每个关节推到顶住机械限位）
powershell -ExecutionPolicy Bypass -File scripts\14-calibrate-arm.ps1 -Arm follower
powershell -ExecutionPolicy Bypass -File scripts\14-calibrate-arm.ps1 -Arm leader

# B5 校准体检（只读）+ 幅度对齐检查
powershell -ExecutionPolicy Bypass -File scripts\15-preflight-calib.ps1
.\.venv\Scripts\python.exe _tools\check_teleop_accuracy.py
```

**判据（B5）**：

| 检查项 | 合格标准 |
| --- | --- |
| 覆盖率 = 录制跨度 / 真实机械全程 | **95% ~ 105%** |
| 从臂/主臂 增益 | **0.95 ~ 1.05x** |
| `robot.is_calibrated` | 两臂都是 `True` |

> 本机实测：`shoulder_pan 0.99x · lift 1.00x · elbow 0.97x · wrist_flex 0.95x · gripper 1.00x`

**为什么校准要推到限位**：见 [5.1](#51-舵机位置与校准的数学) —— 只有行程跨度决定
数据的物理含义，中位点其实会被数学上抵消掉。

### 阶段 C：遥操作验证

```powershell
# 不加相机，先纯看跟随
powershell -ExecutionPolicy Bypass -File scripts\04-teleoperate.ps1 -NoCamera

# 带相机，并做实时跟随精度量化
powershell -ExecutionPolicy Bypass -File scripts\04-teleoperate.ps1
.\.venv\Scripts\python.exe _tools\teleop_probe.py --seconds 60
```

**要确认的四件事**：

1. 白色从臂跟着黑色主臂动（**如果动的是黑臂，说明 COM 口配反了**）
2. 6 个关节方向都正确（没有反向）
3. 幅度一致 —— 主臂推到底，从臂也到接近底
4. 捏主臂扳机 → 从臂夹爪合拢

### 阶段 D：数据采集

```powershell
# D1 采集前自检（7 项 GO/NO-GO，退出码 0 = GO）
powershell -ExecutionPolicy Bypass -File scripts\18-gonogo.ps1

# D2 逐个标记点确认取景（5 次拍照 + 汇总）
powershell -ExecutionPolicy Bypass -File scripts\19-marker-check.ps1 -Points 5

# D3 正式采集
powershell -ExecutionPolicy Bypass -File scripts\06-record.ps1 -NumEpisodes 20
```

**录制时的按键**见 [第八节](#八录制时的按键)。

**采集质量红线**（决定了模型上限）：

| 指标 | 红线 | 检查方式 |
| --- | --- | --- |
| 每条时长 | **≤ 8 秒** | `_tools\dataset_audit.py` |
| 静止帧占比 | **越少越好**（本机 74.7% 偏多，见踩坑） | `_tools\dataset_audit.py` |
| 每条夹爪闭合次数 | **1 次**（抓住就别中途松手） | 逐帧可视化 |
| 起始姿态 | **尽量一致** | 用 `--reset_home_pose` 强制（见下） |
| 抓失败 | **按 `←` 重录**，不要留着 | 录制时 |

**让起始姿态一致的办法**（本项目对 `lerobot-record` 加的补丁）：

```powershell
# reset 阶段自动把从臂平滑开回固定起始姿势，无需人工摆臂
--reset_home_pose="shoulder_pan:-33,shoulder_lift:13,elbow_flex:-15,wrist_flex:88,wrist_roll:-2,gripper:17"
```

### 阶段 E：训练

```powershell
# 先短跑验证链路（5 分钟）
powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1 -Steps 5000 -BatchSize 4

# 正式训练（RTX 4060 8 GB：batch 16 约 3.7 小时跑 4 万步）
powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1 `
  -RepoId seeedstudio123/m1_pick_cube_clean -Steps 40000 -BatchSize 16 -NumWorkers 8
```

**判据**：

| 指标 | 合格 |
| --- | --- |
| `loss` | 单调下降，4 万步时 **< 0.1**（本机 0.059） |
| `grdn` | 几十 ~ 几百，不爆（本机 8.8） |
| `updt_s` | 0.1 ~ 0.4 s/step（本机 0.31） |
| 显存 | batch 16 约 5.2 GB / 8 GB |

**训练到多少步够**：本机 16 K 步 loss 已到 0.098，再跑到 40 K 只降到 0.059 —— 进入平台期。
配合 batch 16，4 万步 ≈ 30 个 epoch，对 98 条数据已经足够。

### 阶段 F：上机评估

```powershell
# 默认配置已经是最稳的组合
powershell -ExecutionPolicy Bypass -File scripts\10-eval.ps1 `
  -PolicyPath lerobot\outputs\train\act_m1_pick_cube\checkpoints\last\pretrained_model `
  -RepoId seeedstudio123/eval_fixed_p1 `
  -NumEpisodes 10 -EpisodeTimeS 30 -ResetTimeS 15

# 打分（务必用这个工具，别自己写判据 —— 见 5.5 的边界帧陷阱）
.\.venv\Scripts\python.exe _tools\eval_score.py eval_fixed_p1 --by-position
```

**评估前必查三件事**：

| 项 | 怎么查 |
| --- | --- |
| 舵机校准 = 训练时的 JSON | `scripts\20-sync-calib.ps1 -Check` |
| 相机取景 = 训练时 | 对比 `assets\REFERENCE_from_dataset.png` |
| 方块摆在训练过的点上 | 对照 `assets\train_positions_labeled.png` |

**评估设计建议**（本项目的经验）：

- 想测「精度」→ **同一个点重复 10 次**
- 想测「分布内覆盖」→ 5 个训练点各 2 次
- 想测「是否真用视觉」→ **一个从未训练过的中间点 10 次**（本项目结论：0/10）

### 阶段 G：演示 / 复现

```powershell
# 只看效果，不建数据集：仍用 10-eval.ps1，但把 NumEpisodes 设小
powershell -ExecutionPolicy Bypass -File scripts\10-eval.ps1 `
  -PolicyPath lerobot\outputs\train\act_m1_pick_cube\checkpoints\last\pretrained_model `
  -RepoId seeedstudio123/eval_demo -NumEpisodes 3 -EpisodeTimeS 30
```

---

## 五、专业知识：这套流程背后的原理

这一节是本项目的"技术档案"，解释**为什么这么设定**，以及**换参数会出什么问题**。

### 5.1 舵机位置与校准的数学

#### 三个量的关系

```
Present_Position = Actual_Position − Homing_Offset
```

- `Actual_Position`：舵机原始编码器读数（0~4095，**11 位**）
- `Homing_Offset`：校准写进 EEPROM 的零位偏移（**11 位有符号，范围 ±2047**）
- `Present_Position`：多圈值（用 bit15 表示符号，可以超出 4095 或为负）

#### 数据集里存的是什么

数据集不存原始编码器值，存的是**归一化值**（-100~100，夹爪 0~100）：

```
norm = (pos − range_min) / (range_max − range_min) × 200 − 100
```

把 `pos = actual − offset` 代进去化简：

```
norm = (actual − actual_min) / (actual_max − actual_min) × 200 − 100
                                        ↑ offset 完全抵消
```

**结论一：`Homing_Offset` 不影响数据含义，只有「行程跨度」（span）影响。**

这有两个重要推论：

1. **中位摆在哪不重要** —— 中位偏了只是让 offset 变大，归一化结果不变
2. **但行程必须推满** —— 如果只推了一半，span 变小，同一个物理角度会映射到不同的
   归一化值 → 数据前后不一致 → 策略学乱

> 本项目的教训：早期从臂 `wrist_flex` 行程只录到 1633（真实 2296），
> 结果遥操作增益变成 **1.41x**（手臂动作放大 41%），数据全废。

#### 推论二：跨人 / 跨电脑共享校准的条件

因为 offset 抵消，**同一台臂**换电脑时可以直接共享 JSON：

```powershell
# 对方把 JSON 放到 %USERPROFILE%\.cache\huggingface\lerobot\calibration\ 对应位置，
# 然后必须把校准写进舵机 EEPROM（只放文件不够！）
powershell -ExecutionPolicy Bypass -File scripts\20-sync-calib.ps1
```

**但如果是另一台物理臂，绝不能套用** —— `Homing_Offset` 取决于每个舵机
**舵盘的安装角度**，每台臂都不一样。用错会让关节转错方向甚至撞限位。

#### `Homing_Offset` 的 11 位陷阱

`Homing_Offset` 只有 ±2047 的范围。如果舵盘安装角度偏了超过约一圈（4096 计数），
校准就**在数学上无解**。

> 本项目的真实事故：主臂 `wrist_flex` 的原始行程全是负值（≈ -2461 … -165），
> 需要的 offset 约 -3360，**超出 ±2047** → LeRobot 校准根本不成立。
> 最后只能靠 Seeed GUI 对单个舵机执行「🎯 中位」（向寄存器 40 写 `128`），
> 把绝对零位整体移动一圈（-1081 → 3011，+4092），才修好。

### 5.2 数据集的一致性：什么会破坏它

| 变更 | 对已有数据的影响 | 原因 |
| --- | --- | --- |
| 重新校准但**行程推满** | ✅ 兼容 | span 一致，归一化结果相同 |
| 重新校准但**行程没推满** | ❌ 不兼容 | span 变了 |
| **拆装舵盘** | ❌ 不兼容 | 编码器与物理角度对应关系变了 |
| **移动相机** | ❌ 不兼容 | 视觉输入分布变了 |
| 舵机 ID 不变、只换端口 | ✅ 兼容 | 与端口无关 |

**验证"新校准是否等价于旧校准"的方法**：跑 `_tools\check_teleop_accuracy.py`，
所有增益都在 0.95~1.05x 且覆盖率 ~100% 才算等价。

### 5.3 ACT 与 Action Chunking

#### 这是什么

ACT（Action Chunking Transformer）是模仿学习策略：
输入当前观测（图像 + 关节角），输出**未来一段动作序列**（一个 chunk）。

```python
chunk_size      = 100   # 一次预测出 100 步动作
n_action_steps  = 100   # 实际执行多少步后重新预测
```

**为什么要"动作块"而不是逐帧预测**：逐帧回归容易在示教者犹豫处产生
"平均动作"（左右都不是），而一次预测一段完整轨迹能让动作连贯。

#### 关键参数：`n_action_steps`

官方配置注释写得很明确：

> `n_action_steps`：每次策略调用执行多少步，不能超过 `chunk_size`。
> 例如 `chunk_size=100` 时，**你可以设为 50** ——
> 即模型预测 100 步、执行 50 步、丢掉另外 50 步。

| `n_action_steps` | 表现 | 适用 |
| --- | --- | --- |
| 100（默认） | 顺滑，但 3.3 秒才修正一次 → **迟钝** | 动作稳定的任务 |
| 50（官方示例） | 折中，1.67 秒修正一次 | 一般推荐 |
| 10 / 20 | **原地小幅摆动**（抖动） | ❌ 不推荐单独使用 |

> **本项目的实测教训**：为了"更灵敏"把 `n_action_steps` 降到 10，
> 结果机械臂**卡在方块上方原地左右快速摇摆**。原因见下一条。

#### Temporal Ensembling：官方解决抖动的手段

`ACTTemporalEnsembler`（`modeling_act.py`）对重叠的 chunk 做**指数加权平均**：

```
权重 wᵢ = exp(−coeff × i)      # w₀ 是最老的动作
```

| `coeff` | 效果 |
| --- | --- |
| 0 | 所有动作等权 |
| **> 0（原始 ACT 论文用 0.01）** | **更看重较早的动作** → 平滑 |
| < 0 | 更看重较新的动作 → 灵敏但抖 |

官方注释还写了（引 LeRobot PR #319 的实验）：**过于激进地偏重新动作会削弱
action chunking 的好处** —— 这正是 `n_action_steps` 太小时会抖的根因。

启用时 `n_action_steps` 必须为 1（因为要**每帧都推理**才能形成叠加）。

```powershell
# 本项目脚本会自动处理这两个参数的依赖关系
scripts\10-eval.ps1 ... -TemporalEnsemble            # coeff 默认 0.01
scripts\10-eval.ps1 ... -TemporalEnsemble -EnsembleCoeff 0.02
```

> ⚠️ 代价：推理次数变成 30 倍/秒。RTX 4060 实测能维持在 30 fps，
> 但换个更小的显卡可能掉帧 —— 掉帧会让动作整体变慢。

#### 动作低通滤波（本项目的补充手段）

temporal ensembling 是"在 chunk 维度平均"，低通是"在时间维度平均"，两者互补：

```python
cmd[t] = cmd[t−1] + α × (target[t] − cmd[t−1])      # α ∈ (0,1)
```

- 截止频率 ≈ `α × fps / (2π)`；α=0.5 时约 2.4 Hz
- α 越小越平滑，但滞后越大（滞后 ≈ `(1−α)/α` 帧）
- **α=0.5 只能压 2.4 Hz 以上的抖动**；要压 1.5 Hz 的摆动得用 α≈0.2

### 5.4 模仿学习的泛化边界：为什么它只认那几个点

#### 行为克隆的本质

ACT 学的是一个条件分布：

```
p(动作 | 当前画面, 当前关节角)
```

**它只在训练数据覆盖到的状态上有效。** 数据里没出现过的画面组合，
模型没有任何训练信号，只能靠插值/外推 —— 而外推在神经网络里几乎不可靠。

#### 判别方法：训练点 vs 未训练点

这是本项目设计的核心实验：

| 测试 | 若成功 → 说明 | 若失败 → 说明 |
| --- | --- | --- |
| 训练点 | 基本功（流程通、模型收敛） | 数据/训练有问题 |
| **未训练中间点** | **模型真的在用视觉** | **它只是记住了那几个位置** |

**本项目的实测结果**：

| 位置 | 成功率 |
| --- | --- |
| 训练点 P1 重复 10 次 | **100%** |
| 5 个训练点各 2 次 | 60% |
| 训练点之间（离最近训练点 33~57 px） | **0%** |

而且失效方式是**可预测的**：在训练点上 `shoulder_lift` 会下探 **17~63 单位**
（够到方块），在训练点之间只动 **2~6 单位** —— **"下探"这个动作根本没被触发**，
手臂只是左右扫、把方块推着走。

#### 想让它泛化，需要什么

**关键不是总条数，而是位置密度。**

假设工作区约 200×150 mm、抓取容差约 15 mm → 大约需要 **13×10 的覆盖网格**。

| 数据方案 | 覆盖 | 评价 |
| --- | --- | --- |
| 5 个固定点 × 20 条 = 100 条 | 4~5 个离散点 | ❌ 只能记住这些点（本项目现状） |
| 5 个固定点 × 40 条 = 200 条 | 还是 4~5 个点 | ❌ **加条数没用** |
| **随机摆放 × 250~300 条** | 连续覆盖 | ✅ 迫使模型学连续映射 |
| 5×5 网格 × 15 条 = 375 条 | 25 个点 | ✅ 效果接近随机 |

**现实预期**：SO-ARM101（无末端力控、夹爪开合仅 1.4 cm）+ ACT，
随机位置抓取做到 **60~80%** 就是正常水平，不要期待 95%+。

#### 数据质量的四个隐形杀手

从本项目 98 条数据的体检结果：

| 问题 | 实测 | 后果 |
| --- | --- | --- |
| **大量停顿** | **74.7% 的帧几乎不动** | 模型被训练得迟钝、倾向原地不动 |
| **位置分布不均** | 38 / 20 / 19 / 11 / 9（**4.2 倍**差） | 模型偏向最常见的那个点 |
| **起始姿态散乱** | 各关节标准差 15~25 单位 | 示范之间互相"打架" |
| **前后风格不一致** | 前 20 条静止帧 82.6%，后 18 条 59.3% | 早期犹豫、后期流畅，模型学到平均值 |

> **结论**：98 条数据里这四个因素叠加，模型只能学出一套"折中的固定动作"。
> 这也解释了为什么它离线误差 0.9%、在线就是夹不住 ——
> 它忠实地学会了一个**本身就不够精确的示范**。

### 5.5 评估方法论：几个必须避开的坑

#### 坑一：帧窗边界帧（本项目踩过，导致结论完全反转）

LeRobot 把连续录制的视频拼在一个文件里，**`ep N` 的 `to_timestamp` 正好等于
`ep N+1` 的 `from_timestamp`**。

如果按 `t <= t1` 取帧，每个回合的"最后一帧"其实是**下一个回合的第一帧** ——
而那一帧里操作者通常已经把方块摆回起点，于是**所有成功都会被判成失败**。

```python
# 正确写法：严格排除边界帧
if t >= t1 - 1e-6:
    break
```

> 本项目曾因此把 **10/10 的成功误判为 1/10**，并得出"策略根本不会做"的错误结论。
> 现在固定用 `_tools\eval_score.py` 打分，避免再犯。

#### 坑二：成功率判据要可解释

本项目的判据（三步同时满足才算成功）：

1. 首帧能看到方块（红色像素 ≥ 400）
2. 末帧看不到方块（红色像素 < 200）
3. 方块最后一次可见的时刻 **早于回合结束 1 秒以上**

第 3 条是为了排除"刚好在最后一帧被抓住"的歧义。

#### 坑三：摆位一致性

同一位置重复测试时，起点应该几乎不动。本项目实测两次对比：

```
eval_fixed_p1（同一点）: x std 5.3 px   y std 3.2 px   跨度 18 px   ✅
eval_base_v2（5 个点） : x std 97.2 px  y std 33.6 px  跨度 250 px  （预期）
```

`eval_score.py` 会在跨度 >60 px 时警告 —— 因为摆偏了会让成功率被稀释，
结果就不能用来判断"是否泛化"。

#### 坑四：训练 loss 低 ≠ 真机能抓

本机 loss 最终 0.059、离线复现误差 0.9%，但在线只有 60%（5 点）。

**离线误差（teacher forcing）和在线成功率是两件事**：
在线时每一步都基于**自己上一步的实际状态**，误差会累积（compounding error）。

#### 坑五：无动作来源的 reset 阶段

`lerobot-record --policy.path=...` 做评估时 teleop 为 None。回合之间的 reset 阶段
**策略和遥操作都没有**，原代码直接 `continue`，同时跳过了：

1. `precise_sleep(...)` → reset 期间满速死循环刷屏
2. `timestamp` 更新 → **`while timestamp < control_time_s` 永远成立，reset 永不结束**

结果：评估最多只能跑完第 1 条。本项目通过补丁修复，并顺带实现
`--reset_home_pose` 自动复位（让每条 episode 的起始姿态完全一致）。

### 5.6 Windows 平台工程坑

#### 符号链接权限（会让训练在 2 万步时崩）

LeRobot 每存一次检查点都会建 `checkpoints/last → ../005000` 的符号链接。
Windows 普通用户**建不了符号链接**：

```
OSError: [WinError 1314] 客户端没有所需的特权
```

`save_freq=20000` 时，正式训练会在**第 2 万步（约 40 分钟）**崩掉，而不是跑完才崩。

**解决方案**：退化到**目录 junction**（`mklink /J`），普通用户即可创建，
对 Python 的 `Path.exists()` / `open()` 完全透明。

```python
try:
    last_checkpoint_dir.symlink_to(relative_target)
except OSError:
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True)
```

> ⚠️ 清理旧链接时**绝不能用 `shutil.rmtree`**：Python 认为 junction 不是符号链接，
> 会递归进去把**目标目录的内容真删掉**。必须用 `os.rmdir()`（只删 junction 本身）。

#### `.ps1` 必须 UTF-8 with BOM

Windows PowerShell 5.1 在**无 BOM** 时按 GBK 解析文件，
中文会乱码甚至直接语法报错（`意外的标记"}"`）。

```powershell
# 改完脚本后统一修复编码
.\.venv\Scripts\python.exe _tools\to_utf8bom.py scripts
```

#### PowerShell 5.1 引用传参陷阱

| 陷阱 | 现象 | 规避 |
| --- | --- | --- |
| 空字符串参数丢失 | `--proxy ""` 被吃成 `--proxy <下一个参数>` | 不传空字符串 |
| JSON 传给 exe 被转义搞坏 | `--config '{"a":[1]}'` 解析失败 | 写临时文件用 `--config_path` |
| 数组变标量 | `ConvertTo-IntList "1"` 返回 `1` 而非 `[1]` | 显式 `[int[]]` / `[string[]]` |
| `2>&1 \| Tee-Object` | 原生 stderr 被当成 ErrorRecord，显示 `NativeCommandError` | 只是显示问题，或用 `Start-Transcript` |

#### 其他

| 项 | 说明 |
| --- | --- |
| 串口 | 官方文档的 `/dev/ttyACM0` 在 Windows 不存在，要用 `COMx` |
| 视频编码 | 0.4.4 用 PyAV 内置 libsvtav1，不再 shell out 到 ffmpeg |
| GitHub 访问 | 直连会被重置，需配代理；但 `download.pytorch.org` **直连更快**（代理反而 SSL EOF） |
| PySide6 | 装 `PySide6-Essentials`（元包会连带几百 MB 的 Addons） |
| `edit-dataset --root` | 该版本语义矛盾（一处当完整目录、一处当父目录），**一律不传 root** |

---

## 六、踩坑与关键决策记录

### 补丁清单（`patches\`，从干净 HEAD 可完整重建）

| 补丁 | 解决的问题 | 不打的后果 |
| --- | --- | --- |
| `0001-fix-opencv-camera-copy-attribute` | 分支访问不存在的 `config.copy` | 任何带 opencv 相机的命令直接崩 |
| `0002-record-pause-and-emergency-stop` | 加 `空格` 暂停 / `x` 急停 | 录制中出错只能 Ctrl+C，丢掉整条 |
| `0003-windows-symlink-junction-fallback` | 符号链接需管理员权限 | **训练第 2 万步必崩** |
| `0004-record-eval-robustness` | reset 空转 / 0 帧保护 / 自动复位 / 动作低通 | 评估只能跑 1 条；起始姿态漂移 |

### 决策与坑（按主题）

| 主题 | 选择 / 现象 | 原因 |
| --- | --- | --- |
| **LeRobot 版本** | Seeed `DepthCameraSupport` 分支 v0.4.4 | 官方 main(0.6.2) 没有 Orbbec 相机后端 |
| **校准方式** | 自己写 `calibrate_arm.py`（推满行程 + ENTER 记录） | 原生校准只提醒"走完全程"，实际常录不满 → 增益 1.41x |
| **校准自动化** | `--reset_home_pose` 自动回起始位 | 人工摆臂偏差 17~65 单位，严重污染评估 |
| **`n_action_steps`** | 保持默认 100，或配合 temporal ensembling | 降到 10/20 会原地抖动（官方注释已说明原理） |
| **评估数据集目录** | 存在同名目录时 LeRobot 报 `FileExistsError` | 脚本提供 `-Resume` / `-Overwrite`，且 DryRun 下不删数据 |
| **成功率判据** | 固定用 `_tools\eval_score.py`（严格边界帧） | 手写判据曾把 10/10 误判成 1/10 |
| **相机位置** | 用数据集首帧做客观比对，不靠记忆 | 曾误判"相机被动过"，实为纸箱被移动 |
| **`wrist_roll` 校准** | range 强制 `0~4095`（全程） | 它是唯一可以整圈旋转的关节 |
| **数据清洗** | 100 条 → 98 条（删 ep2 抓失败、ep62 空演示） | 坏示范会污染策略 |
| **训练步数** | 4 万步停（loss 已进平台期） | 16K→40K 只从 0.098 降到 0.059 |

### 事故记录

| 事故 | 现象 | 定位 | 解决 |
| --- | --- | --- | --- |
| **整圈零位偏移** | 主臂 `wrist_flex` 原始行程全为负值，需 offset -3360（超 ±2047） | 打印 raw 行程区间 | Seeed GUI 单舵机「🎯 中位」写 128，绝对零位 +4092 |
| **舵机 5 无响应** | `Missing motor IDs: - 5`，但 ID 6 正常 | 菊花链通 → 问题在 5 号本身 | 断电重插 5 号两端接头（接头松动） |
| **`Overload error!`** | 收尾时夹爪 ID 6 报过载 | 数据无影响，仅退出码变 1 | 松扳机 → 摆放松姿势 → 再按 ESC |
| **视频编码刷屏** | torchvision 弃用警告淹没日志 | — | `$env:PYTHONWARNINGS="ignore::UserWarning"`（消息正则过滤实测无效） |
| **`FileExistsError`** | 重跑评估时目录已存在 | — | `-Resume` / `-Overwrite` |
| **`PermissionError`** | 打不开 COM10/COM11 | Seeed GUI 仍占用串口 | 关掉 `factory_calibration_tool` |

---

## 七、命令速查

| 目标 | 命令 |
| --- | --- |
| 环境自检 | `scripts\00-check-env.ps1` |
| 查串口 | `scripts\01-find-port.ps1 [-Interactive]` |
| 写回串口配置 | `scripts\01-find-port.ps1 -SetFollower COM10 -SetLeader COM11` |
| 舵机 ID 配置 | `scripts\02-setup-motors.ps1 -Arm follower\|leader` |
| 整臂校准 | `scripts\03-calibrate.ps1 -Arm follower\|leader [-Recalibrate]` |
| **强化校准（推满行程）** | `scripts\14-calibrate-arm.ps1 -Arm follower\|leader` |
| **校准体检（只读）** | `scripts\15-preflight-calib.ps1` |
| **中位校准（安全版）** | `scripts\16-middle-calibrate.ps1 -Arm follower\|leader [-DryRun]` |
| **校准写回舵机** | `scripts\20-sync-calib.ps1 [-Check]` |
| 幅度对齐检查 | `python _tools\check_teleop_accuracy.py` |
| 遥操作 | `scripts\04-teleoperate.ps1 [-NoCamera] [-Seconds 20]` |
| 实时跟随探针 | `python _tools\teleop_probe.py --seconds 60` |
| 查相机 | `scripts\05-find-cameras.ps1 [-Backend opencv\|orbbec]` |
| **抓样张 + 取景判据** | `scripts\17-snapshot.ps1 [-Label pos1] [-Open]` |
| **逐点取景检查** | `scripts\19-marker-check.ps1 [-Points 5]` |
| **采集前 GO/NO-GO** | `scripts\18-gonogo.ps1` |
| 采集数据 | `scripts\06-record.ps1 [-NumEpisodes 20] [-Resume]` |
| 数据回放 | `scripts\07-replay.ps1 -Episode 0` |
| 数据可视化 | `scripts\08-dataset-viz.ps1 -EpisodeIndex 0 [-Save]` |
| 数据集体检 | `python _tools\dataset_audit.py` |
| 数据集列表 / 详情 | `scripts\11-edit-dataset.ps1 -Action list \| info` |
| 删除剧集 | `scripts\11-edit-dataset.ps1 -Action delete-episodes -Episodes "0,2,5" [-NewRepoId x/y]` |
| 训练 | `scripts\09-train.ps1 [-Steps 40000] [-BatchSize 16] [-Resume]` |
| **上机评估** | `scripts\10-eval.ps1 -PolicyPath <权重路径> [-NumEpisodes 10] [-TemporalEnsemble] [-DryRun]` |
| **评估打分** | `python _tools\eval_score.py <数据集名> [--by-position] [--montage]` |
| 舵机调试 GUI | `scripts\12-steering-tool.ps1 -Action gui` |
| 舵机 ID 扫描 | `scripts\12-steering-tool.ps1 -Action scan` |
| 舵机级诊断 | `python _tools\servo_diag.py` |
| 手动执行任意 lerobot 命令 | `scripts\shell.ps1` |

### `10-eval.ps1` 主要参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `-PolicyPath` | 必填 | `...\checkpoints\last\pretrained_model` |
| `-NumEpisodes` | 10 | 回合数 |
| `-EpisodeTimeS` | 30 | 单回合上限（训练数据平均 7.3 秒，30 秒足够） |
| `-ResetTimeS` | 15 | 回合间复位时间（给你摆方块） |
| `-ResetHomePose` | 训练起始姿态均值 | reset 时自动回该姿势；传 `""` 关闭 |
| `-WithTeleop` | 关 | 改成用主臂驱动复位（会引入人为误差，不推荐） |
| `-TemporalEnsemble` | 关 | 启用官方抗抖动机制（自动设 `n_action_steps=1`） |
| `-NActionSteps` | 不覆盖（=100） | 覆盖执行步数；**不建议小于 50** |
| `-ActionSmooth` | 1.0（关） | 动作低通系数；0.5 约减半抖动 |
| `-MaxStep` | 0（不限） | 每帧最大移动量（`max_relative_target`），安全阀 |
| `-ActionLog` | 空 | 逐帧动作日志 CSV（每回合一个文件），用于诊断抖动 |
| `-Resume` / `-Overwrite` | 关 | 同名数据集已存在时：续录 / 删除重跑 |
| `-DryRun` | 关 | 只打印命令不运行，且**不会删除任何数据** |

---

## 八、录制时的按键

原生 LeRobot 只有 `→` / `←` / `ESC`；**空格与 `x` 是本项目通过
`patches\0002-record-pause-and-emergency-stop.patch` 加的**。

| 键 | 作用 |
| --- | --- |
| **→** | 提前结束当前回合 / 复位（**做完立刻按**，别让死帧进数据） |
| **←** | 丢弃当前回合并重录（**抓失败就用它**） |
| **空格** | **暂停 / 继续**：不录新帧，主从跟随继续；暂停时长不计入 episode |
| **`x`** | **急停**：丢弃当前条 + 结束会话 + 收尾释放力矩 |
| **ESC** | 结束会话（会先编码视频，**别直接关窗口**） |

> **收尾三步**（按 ESC 之前）：松开主臂扳机张开夹爪 → 摆放松姿势 → 再按 ESC。
> 可避免夹爪堵转触发的 `Overload error`（那是虚警，但退出码会变成 1）。

> ⚠️ **评估时不要按方向键**：`exit_early` 只是个布尔标志，按键重复时会残留到下一个
> 阶段，让新回合第一轮就 break、录到 0 帧（已加保护，但最好别按）。

---

## 九、排障索引

| 症状 | 去哪查 |
| --- | --- |
| 环境装不上 / CUDA 不可用 | `docs\09-Windows排障FAQ.md` |
| 串口打不开 / `PermissionError` | `docs\01-硬件与接线.md`（关掉 Seeed GUI） |
| 校准报 `ValueError: same min and max` | `docs\02-整臂校准.md`（用 `14-calibrate-arm.ps1`） |
| 遥操作幅度不对 / 增益偏离 | `docs\03-遥操作.md` + `check_teleop_accuracy.py` |
| 相机没画面 / `No Orbbec camera found` | `docs\04-相机接入.md` |
| 录制时 `Overload error` | `docs\05-数据采集.md` §0.5 |
| 训练 `FileExistsError` | `docs\07-训练-ACT.md`（`-Resume` 或不预建目录） |
| 训练存盘崩 `WinError 1314` | 打 `patches\0003`（或跑 `apply-patches.ps1`） |
| 评估跑完 1 条就卡住 | 打 `patches\0004`（reset 空转） |
| 机械臂原地抖动 | `docs\08-上机评估.md` + `analyze_action_log` 思路 |
| 舵机不响应 / 缺 ID | `docs\11-舵机调试工具.md` + `servo_diag.py` |
| 换人/换电脑后校准不一致 | 本文件 §5.1、§5.2 |

---

## 十、离线资料与参考链接

### 离线快照（`_wiki\`）

- `lerobot_so100m_new.md` —— 官方教程全文（含 FAQ、校准参考图）
- `lerobot_steering_gear_debugging_tool.md` —— 舵机调试工具（Seeed_RoboController）
- `lerobot_dataset_tool.md` —— 数据集管理工具
- `pdf\so101_pro_*.pdf` —— 官方规格书

### 在线链接

- 官方教程：<https://wiki.seeedstudio.com/cn/lerobot_so100m_new/>
- 舵机调试工具：<https://wiki.seeedstudio.com/cn/lerobot_steering_gear_debugging_tool/>
- 数据集工具：<https://wiki.seeedstudio.com/cn/lerobot_dataset_tool/>
- Seeed LeRobot 仓库：<https://github.com/Seeed-Projects/lerobot>
- 机械臂开源硬件：<https://github.com/TheRobotStudio/SO-ARM100>
- LeRobot 官方文档：<https://huggingface.co/docs/lerobot/index>
- ACT 论文：<https://huggingface.co/papers/2304.13705>
- SwanLab LeRobot 入门（本项目的训练参考）：<https://docs.swanlab.cn/examples/robot/lerobot-guide.html>
