# ============================================================================
#  LeRobot / SO-ARM101 项目配置
#  只改这一个文件即可，其它脚本都从这里读取参数。
#  （文件必须以 UTF-8 BOM 保存，否则 Windows PowerShell 5.1 会读成乱码；
#    改完文件后运行：python _tools\to_utf8bom.py scripts）
# ============================================================================

$Cfg = @{

    # ------------------------------------------------------------------
    # 1. 串口（Windows 下是 COMx）  ★必须改★
    #    运行 scripts\01-find-port.ps1 查询；插拔顺序：先 Follower 后 Leader
    #
    #    ！！注意：本机 COM3~COM8 全是【蓝牙虚拟串口】，不是机械臂！
    #    下面 COM4 / COM5 只是占位值。插上机械臂后 01 脚本会把 USB 转串口
    #    （Kind=USB）单独列出来，填那一组。
    # ------------------------------------------------------------------
    FollowerPort = "COM10"
    LeaderPort   = "COM11"

    # ------------------------------------------------------------------
    # 2. 机器人 ID
    #    校准文件按 ID 保存（见 %USERPROFILE%\.cache\huggingface\lerobot\calibration）
    #    校准 / 遥操作 / 采集 / 评估 必须使用同一个 ID
    # ------------------------------------------------------------------
    FollowerId = "my_awesome_follower_arm"
    LeaderId   = "my_awesome_leader_arm"

    # ------------------------------------------------------------------
    # 3. 相机   ★键名必须与录制/训练/评估三处完全一致★
    #    Cameras 是一段 draccus(YAML) 片段：内层值一律用【单引号】，
    #    这样 PowerShell 整段传给 exe 时才不会被转义规则搞坏。
    #
    #    本机实测：Orbbec Gemini 2，序列号 AY6KC5200FP，USB3.0
    #      640x480@30 -> 实测 30.4 fps，零超时，画面正常
    #
    #    ★重要★ 键名用 front（"前视相机"，是【角色名】不是设备名）。
    #      官方 wiki 示例里写作 orbbec_color，两者【不能混用】——
    #      键名会写进数据集 features，混用会直接报
    #      `mean is infinity`。采集用 front，训练评估就必须还是 front。
    #
    #    (a) 本机当前配置：Orbbec Gemini 2 彩色（ACT 用彩色就够，数据量小一半）
    #    (b) 想加深度（RGB-D / 点云用）就改成：
    #        "{ front: {type: orbbec_color, serial_number_or_name: 'AY6KC5200FP', width: 640, height: 480, fps: 30, color_mode: rgb, warmup_s: 1}, depth: {type: orbbec_depth, serial_number_or_name: 'AY6KC5200FP', width: 640, height: 400, fps: 30, depth_alpha: 0.2, warmup_s: 5} }"
    #    (c) 普通 USB / UVC 相机（先用 05-find-cameras.ps1 查 index_or_path）：
    #        "{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30, fourcc: 'MJPG'} }"
    #    (d) 无相机（只跑通机械臂链路时留空字符串）
    # ------------------------------------------------------------------
    Cameras = "{ front: {type: orbbec_color, serial_number_or_name: 'AY6KC5200FP', width: 640, height: 480, fps: 30, color_mode: rgb, warmup_s: 1} }"

    # 采集/评估时是否弹出相机预览窗口
    DisplayData = $true

    # ------------------------------------------------------------------
    # 4. 任务与数据集
    #
    #    Task 会写进数据集的 task 字段。ACT 训练用不到它，但以后上 SmolVLA
    #    （SwanLab 教程那条 VLA 路线）它就是语言输入 —— 所以 50 条必须一致，
    #    而且要和实际物体对得上（当前实际抓的是【红色】方块）。
    # ------------------------------------------------------------------
    Task          = "Grab the red cube and put it into the box"
    DatasetRepoId = "seeedstudio123/m1_pick_cube"

    # 采集计划：方块摆 5 个固定点 × 每个位置 20 次 = 100 条
    #
    # 为什么不是固定 1 个位置：
    #   ACT 学的是 π(动作 | 图像, 关节状态)，方块位置的信息本来就在图像里。
    #   固定位置会让模型走捷径「反正方块永远在那儿，照轨迹回放就行」，
    #   于是方块挪 5cm 就废 —— 那不是抓取策略，只是轨迹回放。
    #   位置变化不是「摊薄」数据，而是逼模型真的用上视觉。
    #   而且参数共享：位置 A 的 20 条也在教位置 B 同样的技能。
    #
    # 为什么是 5 x 20 而不是 5 x 10：
    #   瓶颈从来不是「每个位置的条数」，而是「技能被演示了多少次」= 总条数。
    #   100 条比 50 条在同样 5 种视觉情境下多一倍演示，可靠性明显更好。
    #   时间紧张时退回 5 x 10（=50 条）也能跑通，那是保底方案。
    # 试水时用命令行覆盖：-NumEpisodes 3
    #
    # EpisodeTimeS = 20 的来历：
    #   任务实际约 8~12s 完成，这个值只是【安全上限】—— 做完就该按 → 提前结束。
    #   设 20s：万一忘了按 →，最多浪费 8s 死帧；设 30s 则最多浪费 18s。
    #   （实测教训：有一条 30s 的回合里 97% 的帧是静止的，那种数据会教模型「别动」）
    NumEpisodes   = 100
    EpisodeTimeS  = 20
    ResetTimeS    = 30
    PushToHub     = $false

    # ------------------------------------------------------------------
    # 5. 训练
    # ------------------------------------------------------------------
    PolicyType = "act"
    TrainSteps = 300000
    BatchSize  = 8          # RTX 4060 8GB 建议 8；显存不够就降到 4
    OutputDir  = "outputs/train/act_m1_pick_cube"
    JobName    = "act_m1_pick_cube"
    Wandb      = $false
    SaveFreq   = 20000
    LogFreq    = 200

    # ------------------------------------------------------------------
    # 6. 网络（国内环境）
    #    - Proxy：本机 Clash/Mihomo 之类，用于访问 huggingface.co / github.com
    #    - UseHfMirror：如果直连 huggingface.co 很慢，改用 hf-mirror.com 镜像
    # ------------------------------------------------------------------
    Proxy       = "http://127.0.0.1:7897"
    UseProxy    = $true
    HfMirror    = "https://hf-mirror.com"
    UseHfMirror = $false
}
