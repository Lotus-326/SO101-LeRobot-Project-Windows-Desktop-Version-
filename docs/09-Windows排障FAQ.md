# 09 · Windows 排障 FAQ

官方 FAQ 见 `_wiki\lerobot_so100m_new.md` 的「FAQ」章节（串口/舵机/ffmpeg/数据集/相机/训练）。
本文件收录**官方 FAQ 的结论** + **Windows 原生环境特有的坑**。

---

## A. 环境与安装

### A1. `git clone` 报 `Recv failure: Connection was reset`

GitHub 直连被重置。本机已配置代理：

```powershell
git config --global http.proxy http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897
```

代理端口变了就改 `scripts\config.ps1` 的 `Proxy` 并同步上面两条。

### A2. 下载 PyTorch 时 `SSLEOFError` / 卡住 / 极慢

本机实测（2026-10）：

| 源 | 速度 |
| --- | --- |
| `download.pytorch.org` **直连** | ≈ 2.1 MB/s ✅ |
| `download.pytorch.org` **经 Clash 代理** | SSL EOF / 卡死 ❌ |
| `mirror.sjtu.edu.cn/pytorch-wheels` | ≈ 0.8 MB/s（备用） |
| `mirrors.aliyun.com/pytorch-wheels` | ≈ 0.33 MB/s ❌ |

**结论：装 PyTorch 时不要走代理。** `setup-env.ps1` 默认就是直连。

手工安装（直连）：

```powershell
$env:HTTP_PROXY=""; $env:HTTPS_PROXY=""; $env:NO_PROXY="*"
.venv\Scripts\pip.exe install torch==2.7.1 torchvision==0.22.1 `
  --index-url https://download.pytorch.org/whl/cu128 `
  --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

直连不通时再加 `-UseProxy` 跑 `setup-env.ps1`。

### A2b. pip 报 `You must give at least one requirement to install`

说明命令行里出现了**空字符串参数**。PowerShell 5.1 会把 `""` 直接丢掉，
于是 `--proxy ""` 变成 `--proxy <下一个参数>`，把真正的包名吃掉了。

**规则：不要给原生命令传空字符串参数**，用环境变量代替。

### A3. `.ps1` 里的中文变成乱码 / 报奇怪的语法错误

**Windows PowerShell 5.1 没有 UTF-8 BOM 就按 GBK 解析脚本。** 修复：

```powershell
python _tools\to_utf8bom.py scripts
```

改完任何 `.ps1` 都要跑一次。

### A4. `无法加载文件 ... 因为在此系统上禁止运行脚本`

```powershell
powershell -ExecutionPolicy Bypass -File scripts\xxx.ps1
```

或永久放开（当前用户）：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### A5. `import torch` 报 DLL 初始化失败

- 确认装的是 CUDA 版：`.venv\Scripts\python.exe -c "import torch;print(torch.version.cuda)"`
  应输出 `12.8`，若是 `None` 说明装成了 CPU 版。
- 装过 Visual C++ 运行库（PyTorch 依赖 `vcruntime140`）。
- 极少数情况是杀软拦截，把 `.venv` 目录加白名单。

---

## B. 串口与舵机

### B1. `Could not connect on port "COMx"`

Windows 下不是权限问题（官方文档里的 `sudo chmod 666 /dev/ttyACM*` 只适用于 Linux）。
排查顺序：

1. `scripts\01-find-port.ps1` 确认 COM 号有没有变（插拔不同 USB 口会变号）；
2. 是否被其它程序占用（串口助手、Arduino IDE、另一个没关掉的 lerobot 进程）；
3. 驱动板是否上电。

### B2. 端口号每次插拔都变

在设备管理器里给 CH340 固定端口号：
**设备管理器 → 端口 → USB-SERIAL CH340 → 属性 → 端口设置 → 高级 → COM 端口号**。
建议 Follower 固定成 COM4、Leader 固定成 COM5，与 `config.ps1` 一致。

### B3. `Motor 'gripper' was not found`

6 号舵机三针线没接好，或电源没到总线上。

### B4. `ConnectionError: Failed to sync read 'Present_Position' on ids=[...] no status packet!`

供电不足或某段三针线松动。**哪个舵机灯不亮，就优先查它前面那根线。**

### B5. `Magnitude 30841 exceeds 2047 (max for sign_bit_index=11)`

断电重上电再校准；仍不行就用 Seeed 的 GUI 工具
（`Seeed_RoboController`）重写中位值（把当前位置写成 2048）和舵机 ID。
详见 `_wiki\lerobot_steering_gear_debugging_tool.md`。

### B6. 校准完，遥操作时某个关节方向反了

Leader 前三个关节减速比与 SO100 不同，多半是校准起始姿势不标准。重新校准该臂。

---

## C. 相机

### C0. `AttributeError: 'OpenCVCameraConfig' object has no attribute 'copy'`

**这是 Seeed `DepthCameraSupport` 分支自带的 bug**，本项目已修好（`patches\0001-*.patch`）。

现象：只要 `--robot.cameras` 里用了 `type: opencv`，遥操作 / 采集 / 评估都会在
构造机器人时直接崩：

```
File "lerobot/cameras/utils.py", line 31, in _resolve_opencv_copy_source
    if camera_config.copy is False:
AttributeError: 'OpenCVCameraConfig' object has no attribute 'copy'
```

原因：该分支的相机栈是从上游更新快照拼过来的，`_resolve_opencv_copy_source()`
用了新版的 `copy` 字段，但 `OpenCVCameraConfig` 并没有这个字段，
且 `OpenCVCamera.__init__` 也不接受 `source_camera` / `source_key` ——
也就是说「多路逻辑相机共享一路物理流」这个特性在该分支其实没实现。

修法（已应用）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\apply-patches.ps1
```

**重新 clone `lerobot` 仓库之后一定要跑一次这个脚本。**

> 注：`lerobot-find-cameras opencv` 不受影响（它直接构造 `OpenCVCamera`，
> 不走 `make_cameras_from_configs()`），所以「能查相机但一遥操作就崩」是典型症状。

### C0b. 满屏 `cv::obsensor::getStreamChannelGroup Camera index out of range`

OpenCV 4.12 自带的 obsensor 后端在枚举相机索引时的噪声日志。
本项目访问 Orbbec 走的是 `pyorbbecsdk`，不依赖 OpenCV obsensor，已在
`scripts\_common.ps1` 里设置 `OPENCV_VIDEOIO_PRIORITY_OBSENSOR=0` 关掉它。
手工调用时如果又出现，自己设置这个环境变量即可。

### C1. `No Orbbec camera found for 'XXXX'`

序列号写错。重跑 `scripts\05-find-cameras.ps1 -Backend orbbec` 拿正确 serial。

### C2. `TimeoutError: Timed out waiting for frame`

官方在 Linux 下的解法是调大 USBFS 缓存（`/sys/module/usbcore/parameters/usbfs_memory_mb`），
**Windows 没有这个参数**。Windows 上的等效处理：

1. 拔插相机；
2. 换 USB 3.0 口，**直连主板，不要 Hub**；
3. 降分辨率（640×480）和 FPS（30 → 15）；
4. 关掉其它占 USB 带宽的设备（另一个相机、采集卡）。

### C3. `mean is infinity. You should either initialize with stats ...`

**相机键名与采集数据时不一致**。训练/评估时 `Cameras` 里的 `front` / `side` /
`orbbec_color` 必须与采集时逐字一致（包括顺序和数量）。

### C4. USB 相机读不出图

不要接在 Hub 上；不要接 USB 2.0 口；换 `fourcc: 'MJPG'`。

### C5. Orbbec 被 OpenCV 识别成好几个设备

正常现象。**最后插普通 USB 相机**，让它排到编号末尾。
单 Orbbec + 普通相机的组合参考 [04-相机接入.md](04-相机接入.md)。

---

## D. 数据采集

### D1. 方向键 / ESC 没反应

点击终端窗口获取焦点；无效则降级：

```powershell
.venv\Scripts\pip.exe install pynput==1.6.8
```

### D2. `No valid stream found in input file. Is -1 of the desired media type?`

官方 Linux 解法是 `conda install ffmpeg=7.1.1`。本项目的等价处理：

1. 本机 PyAV 自带 FFmpeg 库，先确认 `libsvtav1` 可用：
   `.venv\Scripts\python.exe -c "import av;print('libsvtav1' in av.codecs_available)"`
2. 若为 `False`，改用 h264 录制：`scripts\06-record.ps1 -VCodec h264`
3. 已内置 `tools\ffmpeg-master-latest-win64-gpl\bin`（含 libsvtav1）供命令行排查。

### D3. 采集 fps 很低、机械臂卡顿

相机分辨率/FPS 降下来；`-VCodec h264`；相机直连 USB 3.0；关掉预览（`-NoDisplay`）。

### D4. 采集可以中途暂停吗？

不建议。`num_episodes` 要一次录够，因为**统计量在录制结束后统一计算**。
真中断了用 `-Resume` 续录，此时 `num_episodes` 填**还要再录几个**。

---

## E. 训练与评估

### E1. `File exists: '.../eval_xxxx'`

删掉 `eval_` 开头的目录再跑。

### E2. `TypeError: stack(): argument 'tensors' (position 1) must be tuple of Tensors, not Column`

```powershell
.venv\Scripts\pip.exe install datasets==2.19 --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### E3. `CUDA out of memory`

```powershell
scripts\09-train.ps1 -BatchSize 4
```

同时关掉浏览器/其它吃显存的程序。8GB 显存不建议直接上 Pi0 / GR00T。

### E4. 训练要多久？

官方参考：3060 8GB 笔记本 + 50 episodes ≈ 6 小时；4090/A100 ≈ 2~3 小时。
本机 RTX 4060 Laptop 8GB 预计 4~7 小时。

### E5. 数据采集有哪些稳定性要求？

摄像头位置/角度/光照稳定，画面里减少不稳定背景和行人。
**部署环境变化过大时，机械臂可能抓不到。**

---

## G. PowerShell 5.1 陷阱（本项目的踩坑记录）

这几个坑在本机都真实发生过，脚本已经绕开，手敲命令时请注意。

| 坑 | 现象 | 规避 |
| --- | --- | --- |
| **空字符串参数被丢弃** | `pip install --proxy "" torch` 报 `You must give at least one requirement`（`torch` 被 `--proxy` 吃掉了） | 不给原生命令传 `""`；用环境变量 |
| **`.ps1` 必须有 UTF-8 BOM** | 中文注释变乱码，甚至报「字符串缺少终止符」 | 改完脚本跑 `python _tools\to_utf8bom.py scripts` |
| **多行字符串传给 exe 会坏** | `python -c @"..."@` 报奇怪的 SyntaxError | 把代码写成 `.py` 文件再调用（见 `_tools\env_report.py`） |
| **`\| Out-Null` 会吞掉子进程输出** | `lerobot-find-cameras` 的相机列表、`lerobot-record` 的进度全不见 | 函数不返回值，退出码放 `$script:LastLerobotExit` |
| **`Win32_PnPEntity -Filter "Name LIKE ..."` 极慢** | 查串口卡 44 秒 | 读注册表 `HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM`（0.2 秒） |
| **`Start-Process -ArgumentList <数组>` 会按空格拆参数** | `--robot.cameras={ front: {...} }` 被拆碎 | 用 `ConvertTo-ArgLine` 自己加引号 |
| **原生程序的 stderr 会中断脚本** | OpenCV/ffmpeg 的无害告警让脚本直接退出 | `Invoke-Lerobot` 内部临时把 `$ErrorActionPreference` 放宽 |
| **代理会影响国内流量** | pip 走 Clash 下载 PyTorch 卡死 | 国内镜像走 `NO_PROXY`；装 torch 时干脆直连 |

---

## H. 数据集工具（lerobot-edit-dataset）

> 完整说明见 [10-数据集工具.md](10-数据集工具.md)。

### H1. `--root` 传了反而读不到数据集，还去连 HuggingFace

本版本里 `root` 的语义**自相矛盾**：

| 代码位置 | 对 `root` 的理解 |
| --- | --- |
| `LeRobotDatasetMetadata.__init__` | `root` = 数据集**完整目录** |
| `lerobot_edit_dataset.get_output_path` | `root` = **父目录**（再拼 `repo_id`） |

传了就一定有一边错。`scripts\11-edit-dataset.ps1` 的做法是**完全不传 root**，
走默认的 `%USERPROFILE%\.cache\huggingface\lerobot\<repo_id>`。
想换存放位置用 `-LerobotHome D:\lerobot-data`（设 `HF_LEROBOT_HOME`，读写两端同步）。

### H2. `ConnectTimeout` / `401 RepositoryNotFoundError`（repo_id ... /refs）

`LeRobotDataset` 在本地找不到 `meta/info.json` 时会 `pull_from_repo()` 去 Hub 拉。

- 数据集确实不在本地 → 先采集数据；
- 数据集在本地但路径不对 → 用 `-Action list` 确认能看到它；
- 只是没开代理 → 检查 `config.ps1` 的 `UseProxy`。

### H3. `Could not decode the value into any of the given types: list[int]`

PowerShell 把单元素数组「解包」成了标量，JSON 里写成了 `"episode_indices": 1`
而不是 `[1]`。脚本已用 `[int[]]` / `[string[]]` 强制转换修好。

### H4. 拆分后 `Split 'val' has no episodes, skipping...`

episode 太少（例如 3 个）时按比例算会算出 0。属于正常现象，数据量 ≥20 个就好了。

### H5. 操作卡住不动 / 只有进度条

官方 FAQ 说明：新版数据集是压缩存储，编辑操作比较耗时，进度条走完即可。
如果完全卡住，**按一下回车**刷新终端。

### H6. `PySide6` 装不上（`No matching distribution found`）

清华 PyPI 镜像没有 PySide6。改用官方源 + 代理：

```powershell
$env:HTTPS_PROXY='http://127.0.0.1:7897'
.venv\Scripts\pip.exe install PySide6-Essentials --index-url https://pypi.org/simple
```

装 `PySide6-Essentials` 就够（本项目工具只用 QtCore/QtGui/QtWidgets），
不需要完整的 `PySide6` + `PySide6-Addons`（多几百 MB）。

---

## I. 维护

### I1. 如何重新校准？

见 [02-整臂校准.md](02-整臂校准.md) 第 5 节。
一句话：`scripts\03-calibrate.ps1 -Arm follower -Recalibrate`。

### I2. 换零件/换舵机后？

必须删掉对应校准文件重新校准：

```
%USERPROFILE%\.cache\huggingface\lerobot\calibration\robots\<ID>.json
%USERPROFILE%\.cache\huggingface\lerobot\calibration\teleoperators\<ID>.json
```

否则会沿用旧校准导致报错或运动异常。

### I3. 别的地方找帮助

- 官方 FAQ：`_wiki\lerobot_so100m_new.md` 末尾
- 数据集工具：<https://wiki.seeedstudio.com/cn/lerobot_dataset_tool/>
- 舵机调试工具：<https://wiki.seeedstudio.com/cn/lerobot_steering_gear_debugging_tool/>
- LeRobot GitHub：<https://github.com/huggingface/lerobot>
- LeRobot Discord：<https://discord.gg/8TnwDdjFGU>
- Seeed 论坛：<https://forum.seeedstudio.com/>
