# 07 · 训练策略（先从 ACT 开始）

> 训练策略就是让神经网络学会「看到画面 + 当前关节状态 → 输出下一步动作」。

---

## 1. 开始训练

```powershell
powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1
```

默认参数（来自 `config.ps1`）：

```powershell
PolicyType = "act"
TrainSteps = 300000
BatchSize  = 8          # RTX 4060 8GB
OutputDir  = "outputs/train/act_m1_pick_cube"
```

覆盖示例：

```powershell
# 先跑个短的验证链路
powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1 -Steps 5000 -BatchSize 4

# 显存不够
powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1 -BatchSize 4

# 续训（从 last 检查点）
powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1 -Resume
```

---

## 2. 参数怎么理解

| 参数 | 含义 | 建议 |
| --- | --- | --- |
| `--policy.type` | 策略类型：`act` / `diffusion` / `vqbet` / `tdmpc` / `smolvla` … | **先用 `act`** |
| `--steps` | 训练步数，算法默认 800000 | 难任务调高；不确定就调高，反正有检查点 |
| `--batch_size` | 批大小 | 8GB 显存从 8 起，OOM 就降到 4 |
| `--policy.device` | `cuda` / `cpu` / `mps` | RTX 4060 用 `cuda` |
| `--save_freq` | 检查点保存间隔 | 20000 |
| `--wandb.enable` | 是否上 Weights & Biases | 本地跑建议 `false` |
| `--policy.push_to_hub` | 是否把模型推到 Hub | 本地用 `false` |

策略会**自动适配**你数据集里的电机状态、电机动作和相机数量 —— 这正是
「相机键名/机器人 ID 必须前后一致」如此重要的原因。

---

## 3. 训练时长参考

| 硬件 | 数据量 | 耗时 |
| --- | --- | --- |
| RTX 3060 8GB 笔记本 | 50 episodes | ≈ 6 小时 |
| RTX 4090 / A100 | 50 episodes | ≈ 2~3 小时 |
| **RTX 4060 Laptop 8GB（本机）** | 50 episodes | **≈ 4~7 小时（预期）** |

实际受 batch size、显卡、数据集大小、视频读取速度影响。

---

## 4. 产物

```
lerobot\outputs\train\act_m1_pick_cube\
├─ checkpoints\
│   ├─ 020000\pretrained_model\
│   ├─ 040000\pretrained_model\
│   ├─ ...
│   └─ last\pretrained_model\        ← 评估用这个
│       ├─ model.safetensors
│       ├─ config.json
│       └─ train_config.json         ← -Resume 用这个
└─ ...
```

---

## 5. 可视化训练曲线

```powershell
powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1 -Wandb
```

需要先登录：`.venv\Scripts\wandb.exe login`。
不想联网就用 `lerobot` 自带的日志（终端会滚动打印 loss）。

---

## 6. 换用更大的基础模型

### SmolVLA（轻量 VLA，可用自己的数据微调）

```powershell
.venv\Scripts\pip.exe install -e ".[smolvla]"

powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1 `
  -PolicyType smolvla -PolicyPath lerobot/smolvla_base `
  -Steps 20000 -BatchSize 8 -OutputDir outputs/train/smolvla_m1
```

- 建议 **≥ 50 episodes**（25 个往往不够）。
- 官方参考：A100 上 20k steps ≈ 4 小时。8GB 显存务必把 `batch_size` 调小。

### Pi0 / Pi0.5

```powershell
.venv\Scripts\pip.exe install -e ".[pi]"
```

`--policy.type=pi0` / `pi05`，配 `--policy.pretrained_path=lerobot/pi0_base` /
`lerobot/pi05_base`，并开 `gradient_checkpointing` / `dtype=bfloat16` 省显存。
**8GB 显存跑 Pi0 系列非常勉强**，建议先跑通 ACT。

### GR00T N1.5

需要 `flash-attn` + CUDA，环境要求高。**建议 ACT / Pi0 都跑通后再试。**

---

## 7. 训练常见报错

| 报错 | 处理 |
| --- | --- |
| `CUDA out of memory` | `-BatchSize 4`（或 2）；关掉其它占显存的程序 |
| `mean is infinity. You should either ...` | 数据集 stats 缺失，或训练时相机键名与采集时不一致 |
| `TypeError: stack(): argument 'tensors' ... not Column` | 降级 datasets：`.venv\Scripts\pip install datasets==2.19` |
| `No valid stream found in input file` | 视频解码异常；改用 `-VCodec h264` 重录数据 |
| 训练很慢 | 确认 `--policy.device=cuda`；`nvidia-smi` 看 GPU 是否真的在用 |

---

## 8. 下一步

→ [08-上机评估.md](08-上机评估.md)
