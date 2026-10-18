# 校准文件备份（SO-ARM101）

这两份 JSON 是**这台机械臂**的校准参数，与任务无关（抓什么、放哪里都不影响）。
原路径在 `%USERPROFILE%\.cache\huggingface\lerobot\calibration\`，本地已删除，此处为备份。

## 内容

| 文件 | 对应 | 说明 |
| --- | --- | --- |
| `robots\so_follower\my_awesome_follower_arm.json` | 白色从臂（COM10） | 6 个关节的 `homing_offset` 与 `range_min/max` |
| `teleoperators\so_leader\my_awesome_leader_arm.json` | 黑色主臂（COM11） | 同上 |

## 关键事实

- **与任务无关**：换任何抓取任务都能直接复用
- **只对这台臂有效**：`homing_offset` 取决于每个舵机舵盘的安装角度，换一台臂必须重校
- **机械臂拆装过就必须重校**：动过舵盘/换过舵机后 offset 失效
- **不要手工编辑**：格式为 `{关节名: {homing_offset, drive_mode, start_pos, end_pos, range_min, range_max}}`

## 还原方法

```powershell
$src = "D:\LeRobot\assets\calibration_backup"
$dst = "$env:USERPROFILE\.cache\huggingface\lerobot\calibration"
New-Item -ItemType Directory -Force "$dst\robots\so_follower"     | Out-Null
New-Item -ItemType Directory -Force "$dst\teleoperators\so_leader" | Out-Null
Copy-Item "$src\robots\so_follower\my_awesome_follower_arm.json"     "$dst\robots\so_follower\"     -Force
Copy-Item "$src\teleoperators\so_leader\my_awesome_leader_arm.json"  "$dst\teleoperators\so_leader\" -Force
```

还原后建议先跑一次只读检查，确认舵机 EEPROM 与 JSON 一致：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\15-preflight-calib.ps1
powershell -ExecutionPolicy Bypass -File scripts\20-sync-calib.ps1 -Check
```

> 如果 `-Check` 报不一致，说明舵机 EEPROM 里的 offset 与这份 JSON 不同
> （例如舵机被重新校准过），这时应当以舵机为准重新校准，而不是强行写回旧 JSON：
> `scripts\16-middle-calibrate.ps1` → `scripts\14-calibrate-arm.ps1`

## 原始数值（供人工核对）

见两个 JSON 文件本体。从臂与主臂各 6 个关节：
`shoulder_pan` / `shoulder_lift` / `elbow_flex` / `wrist_flex` / `wrist_roll` / `gripper`