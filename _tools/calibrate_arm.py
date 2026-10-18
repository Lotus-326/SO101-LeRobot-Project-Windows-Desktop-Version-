"""更稳的整臂校准器（与 lerobot-calibrate 等价，但行程记录阶段不需要按回车）。

为什么要另写一个：
    官方 lerobot-calibrate 的行程记录靠「按回车停止」。如果操作者提前按了回车，
    就会得到 min==max 的关节，然后报
    `ValueError: Some motors have the same min and max values` 并整轮失败。
    本脚本把行程记录改成【固定时长的自动窗口】+【实时达标提示】+【保存前校验】，
    从机制上消除这个失败模式。

与官方流程的等价性：
    - 同样先 disable_torque()
    - 同样调用 bus.set_half_turn_homings() 得到 homing_offset
    - 同样用 MotorCalibration + bus.write_calibration() + robot._save_calibration()
    - wrist_roll（连续旋转关节）同样固定为 0 / 4095
    → 产出的 JSON 与官方完全同构，后续 lerobot-teleoperate / record 都能直接用。

用法:
    python _tools/calibrate_arm.py follower        # 用 config 里的 FollowerPort
    python _tools/calibrate_arm.py leader
    python _tools/calibrate_arm.py follower --port COM10 --seconds 180
"""

from __future__ import annotations

import argparse
import atexit
import re
import shutil
import sys
import time
from pathlib import Path

import draccus

from lerobot.motors import MotorCalibration
from lerobot.motors.feetech import FeetechMotorsBus
from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig
from lerobot.teleoperators.so_leader.so_leader import SOLeader
from lerobot.robots.so_follower.so_follower import SOFollower

FULL_TURN_MOTOR = "wrist_roll"     # 连续旋转关节：官方固定 range 0~4095

# ---------------------------------------------------------------------------
# 各关节【真实全程】的正常跨度下限（编码器计数）。
#
# 依据：本机两臂各做过一次 300 秒自由扫掠实测（logs\watch-COM10/11.log）：
#   Follower  pan 2572 / lift 2382 / elbow 2212 / wrist 2258 / gripper 1454
#   Leader    pan 2547 / lift 2377 / elbow 2200 / wrist 2296 / gripper 1213
# 两臂结构相同，真实跨度几乎一致 —— 这正是遥操作能对准的前提：
#   归一化是 norm = (pos - min)/(max - min)*200 - 100，
#   LeRobot 只用 JSON 里的 range 做归一化，Homing_Offset 会整体平移并被抵消。
#   所以【决定遥操作幅度准不准的，是 max-min 有没有覆盖到两臂相同的物理全程】。
# 低于下限 = 行程被截断 = 从臂的幅度和主臂对不上（本机 2026-10-16 实测事故）。
# ---------------------------------------------------------------------------
SPAN_FLOOR = {
    "shoulder_pan": 2150,
    "shoulder_lift": 2000,
    "elbow_flex": 1850,
    "wrist_flex": 1900,
    "gripper": 1000,
}
SPAN_TARGET = 1000                 # 兜底默认下限（表里没写的关节用这个）

ROOT = Path(__file__).resolve().parents[1]   # LeRobot 项目根目录
LOG_DIR = ROOT / "logs"
_ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")

# 日志 tee 的全局状态（见 _setup_log / _close_log）
_ORIG_STDOUT = None
_ORIG_STDERR = None
_LOG_FH = None


def _enter_pressed() -> bool:
    """非阻塞检测「回车」（Windows 控制台）。

    行程记录阶段要一边实时刷新读数、一边等用户按回车结束，
    所以不能用阻塞的 input()。msvcrt 不可用时返回 False，
    退化成「只能靠 --seconds 超时结束」。
    """
    try:
        import msvcrt
    except ImportError:
        return False
    pressed = False
    # 把缓冲区里积压的按键全部取走，避免上一次的回车被重复消费
    while msvcrt.kbhit():
        if msvcrt.getch() in (b"\r", b"\n"):
            pressed = True
    return pressed


class _Tee:
    """把 stdout 同时写到终端和日志文件；写文件时剥掉 ANSI 光标控制码。

    这样「实时刷新的表格」在终端里照旧好看，而日志文件是干净可读的 ——
    出问题时把 logs\\calibrate-*.log 发出来就能复现整轮交互。
    """

    def __init__(self, stream, fh) -> None:
        self.stream = stream
        self.fh = fh

    def write(self, s: str):
        self.stream.write(s)
        self.fh.write(_ANSI_RE.sub("", s))
        return len(s)

    def flush(self) -> None:
        self.stream.flush()
        self.fh.flush()

    def isatty(self) -> bool:
        return bool(getattr(self.stream, "isatty", lambda: False)())


def _close_log() -> None:
    """atexit：必须先还原 sys.stdout，再关文件。

    否则解释器退出时要 flush 的 sys.stdout 还指着已关闭的文件句柄，
    会打印 "Exception ignored on flushing sys.stdout" 并以 120 退出。
    """
    global _LOG_FH
    fh, _LOG_FH = _LOG_FH, None
    try:
        if isinstance(sys.stdout, _Tee):
            sys.stdout.flush()
        if _ORIG_STDOUT is not None:
            sys.stdout = _ORIG_STDOUT
        if _ORIG_STDERR is not None:
            sys.stderr = _ORIG_STDERR
        if fh is not None:
            fh.flush()
            fh.close()
    except Exception:  # noqa: BLE001
        pass


def _setup_log(arm: str, log_arg: str | None, no_log: bool):
    """建立 tee 日志。返回日志路径（未启用则 None）。"""
    global _ORIG_STDOUT, _ORIG_STDERR, _LOG_FH
    if no_log:
        return None
    log_path = Path(log_arg) if log_arg else (
        LOG_DIR / f"calibrate-{arm}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    )
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # utf-8-sig：带 BOM，PowerShell 的 Get-Content / 记事本都能正确显示中文
        fh = open(log_path, "w", encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        print(f"[!!] 日志文件创建失败，只输出到终端: {exc}")
        return None
    _ORIG_STDOUT, _ORIG_STDERR = sys.stdout, sys.stderr
    _LOG_FH = fh
    sys.stdout = _Tee(sys.stdout, fh)
    sys.stderr = sys.stdout
    atexit.register(_close_log)
    print(f"[日志] 本次完整输出同时写入: {log_path}")
    return log_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=["follower", "leader"])
    ap.add_argument("--port", default=None)
    ap.add_argument("--id", default=None)
    ap.add_argument("--seconds", type=float, default=240.0, help="行程记录最长时长")
    ap.add_argument("--log", default=None,
                    help="日志路径（默认 logs\\calibrate-<arm>-<时间戳>.log）")
    ap.add_argument("--no-log", action="store_true", help="不写日志文件")
    args = ap.parse_args()

    _setup_log(args.arm, args.log, args.no_log)

    if args.arm == "follower":
        port = args.port or "COM10"
        rid = args.id or "my_awesome_follower_arm"
        cfg = draccus.parse(
            config_class=SOFollowerRobotConfig,
            args=[f"--port={port}", f"--id={rid}"],
        )
        robot = SOFollower(cfg)
        label = "从臂 Follower（白色）"
    else:
        port = args.port or "COM11"
        rid = args.id or "my_awesome_leader_arm"
        cfg = draccus.parse(
            config_class=SOLeaderTeleopConfig,
            args=[f"--port={port}", f"--id={rid}"],
        )
        robot = SOLeader(cfg)
        label = "主臂 Leader（黑色）"

    bus: FeetechMotorsBus = robot.bus
    motors = list(bus.motors)
    record_motors = [m for m in motors if m != FULL_TURN_MOTOR]

    print("=" * 68)
    print(f"  整臂校准 | {label} | {port} | id={rid}")
    print("=" * 68)

    try:
        robot.connect(calibrate=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[XX] 连接失败: {type(exc).__name__}: {exc}")
        return 1

    try:
        bus.disable_torque()
        for m in motors:
            try:
                bus.write("Operating_Mode", m, 0)  # POSITION 模式
            except Exception:  # noqa: BLE001
                pass

        # ------------------------------------------------------------------
        # 第 0 步：中位前置检查
        #
        # Homing_Offset 是【11 位符号幅值】，幅值上限 2047；
        # LeRobot 计算 offset = Present_Position - 2047，
        # 所以要求校准那一刻所有关节的 Present_Position 落在 [0, 4094]。
        #
        # 连续旋转关节（wrist_roll）转过零点后累计值会变成负数（实测 -869），
        # 这时 offset = -2916，直接报
        #   ValueError: Magnitude 2916 exceeds 2047 (max for sign_bit_index=11)
        # 官方 FAQ 的解法是"断电重上电再试"；这里用更可控的办法：
        # 让操作者把该关节用手转一点，读数进入正常区间即可。
        # ------------------------------------------------------------------
        # ------------------------------------------------------------------
        # 注意：只要求 [0,4094] 是不够的 —— 摆中位的过程中关节会微动，
        # 贴着边界（例如 -54）就会再次触发 Magnitude 超限（实测 2101）。
        # 所以这里要求留出安全余量 MARGIN，并且在按下回车后【再兜底检查一次】，
        # 万一还是超范围，就回到第 0 步重新调整，而不是直接崩掉。
        # ------------------------------------------------------------------
        MARGIN = 300
        AIM = 2047          # 摆中位时的目标：各关节原始读数尽量贴近它
        SOFT_TOL = 400      # 偏离超过这个值 = 中位明显没摆准，需要二次确认
        print()
        print(f"  第 0 步：先把 Homing_Offset 归零，检查【原始位置】是否落在 {MARGIN}~{4095 - MARGIN} ...")
        print("           （set_half_turn_homings() 内部也是先归零再读，")
        print("             所以必须按归零后的原始值来判断，而不是当前显示值）")
        # 归零后读到的是舵机原始编码器位置 —— 这才是决定
        # offset = 原始值 - 2047 能否被 11 位符号幅值编码的依据。
        bus.reset_calibration(motors)

        def deviation_table(pos: dict, title: str) -> None:
            """把 6 个关节的读数、偏离中点量、状态打成一张表。"""
            print()
            print(f"  {title}")
            print(f"    {'关节':<15} | {'原始读数':>8} | {'偏离中点':>8} | 状态")
            print("    " + "-" * 58)
            for m in motors:
                dev = pos[m] - AIM
                if not (MARGIN <= pos[m] <= 4095 - MARGIN):
                    st = f"★必须调整★ 目标 {MARGIN}~{4095 - MARGIN}"
                elif abs(dev) > SOFT_TOL:
                    st = "⚠ 建议再往中间靠一点"
                else:
                    st = "OK"
                print(f"    {m:<15} | {pos[m]:>8} | {dev:>+8} | {st}")

        rounds = 0
        while True:
            pos = bus.sync_read("Present_Position", motors, normalize=False)
            bad = {m: pos[m] for m in motors if not (MARGIN <= pos[m] <= 4095 - MARGIN)}
            if not bad:
                deviation_table(pos, f"6 个关节都在可编码窗口内。摆中位的目标：原始读数贴近 {AIM}")
                print()
                print("  第 1 步：把机械臂摆到【各关节活动范围中间】的姿势。")
                print("           各关节「中位」参考图（官方 SO-101）：")
                print("             https://files.seeedstudio.com/wiki/robotics/projects/lerobot/so101/cal_L1.jpg")
                print("             ……把结尾的 L1 依次换成 L2~L6 即可（L6=夹爪）")
                print("           摆好后按回车。机械臂现在是软的，请托住它，")
                print("           按回车时手不要松开（松了会在重力下垮下来，中位就记歪了）。")
                input("  >>> 摆好中位后按回车继续...")

                pos2 = bus.sync_read("Present_Position", motors, normalize=False)
                bad2 = {m: pos2[m] for m in motors if not (0 <= pos2[m] <= 4094)}

                # 可编码 ≠ 摆得准：再拦一道「离中点太远」的软确认。
                # 这正是上一次从臂 shoulder_lift 被记成 2028~4320（中点偏 +1127）的原因。
                off_center = {m: pos2[m] - AIM for m in motors if abs(pos2[m] - AIM) > SOFT_TOL}
                if not bad2 and off_center:
                    deviation_table(pos2, "[!!] 下列关节离中点偏远：仍能编码，但行程会被记成偏心的")
                    print()
                    print("      偏离超过 ±%d 的关节: %s"
                          % (SOFT_TOL, ", ".join(f"{m}({v:+d})" for m, v in off_center.items())))
                    print("      · 直接按回车 = 就这样保存")
                    print("        （夹爪、以及连续旋转的 wrist_roll 偏心是常见且可接受的）")
                    print("      · 按 Ctrl-C 退出，重新摆一次更居中的姿势再来")
                    input("  >>> 确认继续请按回车...")
                    pos2 = bus.sync_read("Present_Position", motors, normalize=False)
                    bad2 = {m: pos2[m] for m in motors if not (0 <= pos2[m] <= 4094)}

                if not bad2:
                    try:
                        homing_offsets = bus.set_half_turn_homings()
                        break
                    except ValueError as exc:
                        print(f"\n  [!!] 中位计算失败: {exc}")
                        bad2 = {m: pos2[m] for m in motors if abs(pos2[m] - 2047) > 2047}
                        if not bad2:
                            bad2 = dict(pos2)
                print()
                print("  [!!] 按回车那一刻，以下关节读数跑出了可编码范围：")
                for m, v in bad2.items():
                    print(f"       {m:<15} 当前 = {v:>6}   偏离中点 {v - AIM:>+7}")
                print("       （它们离中位太远，无法算出合法 Homing_Offset）")
                bad = bad2

            if bad:
                rounds += 1
                print()
                print("  >>> 以下关节需要先用手调整：")
                for m, v in bad.items():
                    print(f"       {m:<15} 当前 = {v:>6}   目标 {MARGIN}~{4095 - MARGIN}")
                print()
                print("  >>> 接下来 15 秒【实时显示】读数。请用手轻轻转动上面的关节，")
                print(f"      让数值进入目标区间，并尽量贴近中点 {AIM}。不用按任何键。")

                t0 = time.perf_counter()
                last = 0.0
                while time.perf_counter() - t0 < 15.0:
                    p = bus.sync_read("Present_Position", motors, normalize=False)
                    now = time.perf_counter()
                    if now - last > 0.4:
                        last = now
                        print(f"\n   剩余 {15.0 - (now - t0):5.1f}s   目标：原始读数贴近 {AIM}")
                        for m in motors:
                            ok = MARGIN <= p[m] <= 4095 - MARGIN
                            print(f"     {m:<15} {p[m]:>7}  偏离 {p[m] - AIM:>+7}"
                                  f"{'' if ok else '   <== 需要调整'}")
                        sys.stdout.write(f"\033[{len(motors) + 2}A")
                        sys.stdout.flush()
                print("\n")
                print("  --- 重新检查 ---")

                # 防止「够不到窗口」时无限打转：3 轮后交给用户决定
                if rounds >= 3:
                    print()
                    print("  [!!] 已经调整 3 轮，仍有读数在可编码窗口外。常见原因：")
                    print("       · 该关节机械行程够不到窗口中点 —— 装配时舵机盘没对准；")
                    print("       · wrist_roll 是连续旋转关节，转过零点后累计值会跑到很外面，")
                    print("         用手朝一个方向多转一两圈就能绕回来；")
                    print("       · 三针线松动 / 供电不足导致读数跳变。")
                    ans = input("  >>> 输入 y 回车 = 再试一轮；直接回车 = 退出（不保存任何东西）... ")
                    if ans.strip().lower() != "y":
                        print("  已退出，未写入任何校准。")
                        return 1
                    rounds = 0

        print(f"\n  [OK] 中位已记录（homing_offset 已写入）")
        for m in motors:
            print(f"       {m:<15} offset = {homing_offsets[m]}")

        time.sleep(0.3)
        start = bus.sync_read("Present_Position", motors, normalize=False)
        mins = dict(start)
        maxes = dict(start)

        floors = {m: SPAN_FLOOR.get(m, SPAN_TARGET) for m in record_motors}

        print()
        print("=" * 68)
        print("  第 2 步：依次把每个关节推到【顶住机械限位】为止（来回 2~3 遍）。")
        print("           ★关键★ 要推到推不动为止，不要只看「够了下限」就松手 ——")
        print("           行程记少了，遥操作时从臂的幅度就会和主臂对不上。")
        print("           推完所有关节后，按【回车】结束记录。")
        print("           wrist_roll 会被自动设为全行程，不用特别推。")
        print("=" * 68)
        print("  关节对照：1 底座旋转 / 2 肩部抬升 / 3 肘部弯曲")
        print("            4 腕部俯仰 / 5 腕部自转 / 6 夹爪开合")
        print("=" * 68)

        t0 = time.perf_counter()
        last_render = 0.0
        force = False
        while True:
            elapsed = time.perf_counter() - t0

            pos = bus.sync_read("Present_Position", motors, normalize=False)
            for m in motors:
                mins[m] = min(mins[m], pos[m])
                maxes[m] = max(maxes[m], pos[m])

            spans = {m: maxes[m] - mins[m] for m in record_motors}
            short = {m: spans[m] for m in record_motors if spans[m] < floors[m]}

            if _enter_pressed():
                if not short or force:
                    if short:
                        print("  [!!] 仍有关节未推满，按你的确认强制保存。")
                    break
                print()
                print("  [!!] 下面这些关节还没推满，先别结束：")
                for m, v in short.items():
                    print(f"       {m:<15} 当前行程 {v:>6}   建议 ≥ {floors[m]}")
                print("       → 继续把它们推到顶住限位；")
                print("       → 确实推不动了，就【再按一次回车】强制保存。")
                force = True

            if elapsed >= args.seconds:
                print(f"\n  [!!] 到达时间上限 {args.seconds:.0f}s，按当前行程保存。")
                break

            now = time.perf_counter()
            if now - last_render > 0.4:
                last_render = now
                print(f"\n  已用时 {elapsed:5.1f}s   已推满 {len(record_motors) - len(short)}/{len(record_motors)}"
                      f"   （推到顶住限位后按回车结束）")
                print(f"  {'关节':<15} | {'当前':>6} | {'行程':>6} | {'建议':>6} | 状态")
                print("  " + "-" * 56)
                for m in record_motors:
                    ok = spans[m] >= floors[m]
                    print(f"  {m:<15} | {pos[m]:>6} | {spans[m]:>6} | {floors[m]:>6} | "
                          f"{'✅ 够了，继续推到顶' if ok else '... 继续推'}")
                print("  " + "-" * 56)
                sys.stdout.write(f"\033[{len(record_motors) + 5}A")
                sys.stdout.flush()

        print("\n\n" + "=" * 68)
        print("  行程汇总")
        print("=" * 68)
        bad: list[str] = []
        for m in motors:
            span = maxes[m] - mins[m]
            if m == FULL_TURN_MOTOR:
                print(f"  {m:<15} min={mins[m]:>6} max={maxes[m]:>6} span={span:>6}   （连续旋转，固定 0~4095）")
                continue
            ok = span >= floors[m]
            if not ok:
                bad.append(m)
            print(f"  {m:<15} min={mins[m]:>6} max={maxes[m]:>6} span={span:>6} "
                  f"（建议≥{floors[m]}）   {'✅' if ok else '❌ 行程不足'}")
        print("=" * 68)

        if any(maxes[m] == mins[m] for m in record_motors):
            print("[XX] 有铰关节 min==max，无法生成校准。请重跑并确认每个关节都推了。")
            return 1
        if bad:
            print(f"[!!] 以下关节行程偏小: {bad}")
            print("     仍会保存，但遥操作时这些关节的幅度会和主臂对不上。")
            print("     强烈建议重跑一次，把这些关节推到顶住限位。")

        # ------------------------------------------------------------------
        # 行程已经量出来了。如果某个关节的行程跑出了编码器 0~4095，
        # 说明「摆中位」那一刻它离行程中心太远（本次记录里某个方向超过 2048）。
        # 自动把该关节的坐标系平移，让行程重新以 2047 为中心：
        #     shift           = 行程中点 - 2047
        #     homing_offset  += shift
        #     range_min/max  -= shift
        #
        # 物理上什么都没动。数学上遥操作映射也【不变】——
        # Homing_Offset 在归一化里的贡献会被完全抵消（见本文件顶部说明）。
        # 但行程重新落回 0~4095，不会再被舵机限位截断，
        # 也就不会出现「从臂在最高处够不到主臂」那种精度损失。
        # ------------------------------------------------------------------
        recentered: list[str] = []
        for m in record_motors:
            lo, hi = int(mins[m]), int(maxes[m])
            if 0 <= lo and hi <= 4095:
                continue
            shift = int(round((lo + hi) / 2 - 2047))
            new_off = int(homing_offsets[m]) + shift
            if abs(new_off) > 2047:
                # 平移后 Homing_Offset 无法用 11 位符号幅值编码，交给下面的钳位逻辑
                continue
            homing_offsets[m] = new_off
            mins[m], maxes[m] = lo - shift, hi - shift
            recentered.append(f"{m:<15} {lo}~{hi} -> {mins[m]}~{maxes[m]}  (offset {new_off})")

        if recentered:
            print()
            print("  [FIX] 以下关节的行程跑出了编码器 0~4095，已自动重新居中：")
            for n in recentered:
                print(f"        {n}")
            print("        物理上没有任何移动；只是平移坐标系，使行程以 2047 为中心。")
            print("        遥操作映射不受影响，但行程不会再被舵机限位截断。")
            print("        （根因：摆中位时该关节离行程中心太远 —— 下次照中位参考图摆正即可）")

        calibration = {}
        for m, motor in bus.motors.items():
            if m == FULL_TURN_MOTOR:
                rmin, rmax = 0, 4095
            else:
                rmin, rmax = int(mins[m]), int(maxes[m])
            calibration[m] = MotorCalibration(
                id=motor.id,
                drive_mode=0,
                homing_offset=int(homing_offsets[m]),
                range_min=rmin,
                range_max=rmax,
            )

        # ------------------------------------------------------------------
        # 写入顺序很关键。
        #
        # 官方 bus.write_calibration() 是「逐电机」写 Homing_Offset + Min + Max，
        # 而 Min/Max_Position_Limit 是【无符号 2 字节】，一旦某个关节的
        # range_min < 0 就抛
        #     ValueError: Negative values are not allowed: -495
        # 而且此时前面几个电机已经写了一半，后面全没写，JSON 也没保存 —— 白跑一轮。
        #
        # 这里改成：
        #   1) 先写所有 Homing_Offset（这是校准的关键，值已保证在 ±2047 内）
        #   2) 再写限位，负值/超范围一律【钳位】到 [0,4095]
        #      （限位只是舵机侧的额外保护；LeRobot 归一化用的是 JSON 里的 range）
        #   3) 最后存 JSON —— JSON 里保留【真实】range（含负值），保证归一化正确
        # ------------------------------------------------------------------
        out_of_range = {
            m: (c.range_min, c.range_max)
            for m, c in calibration.items()
            if c.range_min < 0 or c.range_max > 4095
        }

        for m, c in calibration.items():
            bus.write("Homing_Offset", m, c.homing_offset, normalize=False)
        print("\n  [OK] Homing_Offset 已写入全部 6 个舵机")

        clamped_note = []
        for m, c in calibration.items():
            lo = max(0, min(4095, c.range_min))
            hi = max(0, min(4095, c.range_max))
            if (lo, hi) != (c.range_min, c.range_max):
                clamped_note.append(f"{m}({c.range_min}~{c.range_max} -> {lo}~{hi})")
            bus.write("Min_Position_Limit", m, lo, normalize=False)
            bus.write("Max_Position_Limit", m, hi, normalize=False)
        if clamped_note:
            print("  [!!] 以下关节的限位超出舵机可写范围，已钳位后写入：")
            for n in clamped_note:
                print(f"       {n}")
        else:
            print("  [OK] 限位已写入全部 6 个舵机")

        # 覆盖前先备份旧校准文件：万一这轮结果更差，可以随时退回去。
        fpath = robot.calibration_fpath
        if fpath.exists():
            bak = fpath.with_suffix(f".{time.strftime('%Y%m%d-%H%M%S')}.bak.json")
            try:
                shutil.copy2(fpath, bak)
                print(f"\n  [OK] 旧校准已备份: {bak}")
            except Exception as exc:  # noqa: BLE001
                print(f"\n  [!!] 旧校准备份失败（继续保存）: {exc}")

        robot.calibration = calibration
        robot._save_calibration()
        print(f"\n  [OK] 校准已保存: {robot.calibration_fpath}")

        if out_of_range:
            print()
            print("  [!!] 注意：以下关节测出的行程超出了编码器 0~4095：")
            for m, (lo, hi) in out_of_range.items():
                print(f"       {m:<15} {lo} ~ {hi}")
            print("       说明摆中位时该关节没有真正落在行程中间（偏上或偏下）。")
            print("       校准仍然可用（LeRobot 按 JSON 里的真实 range 归一化），")
            print("       但如果想要更规整的结果，可以重跑一次并把中位摆得更居中。")
        print("       可随时用 lerobot-teleoperate / lerobot-record 直接使用。")
        return 0
    except KeyboardInterrupt:
        print("\n[!!] 用户中断，未保存")
        return 130
    finally:
        try:
            robot.disconnect()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
