"""校准前置体检（★严格只读，不写任何 EEPROM★）。

为什么需要它
------------
`_tools/calibrate_arm.py` 是要人手扶着机械臂、按回车、再推满行程的交互流程。
如果这条代码路径上有 import / draccus 解析 / 连接 / 寄存器读的问题，
最坏的情况是「用户已经摆好中位、按下回车」之后才崩 —— 白折腾一轮，
而且 calibrate_arm.py 内部会先 reset_calibration()，崩在半路等于把旧校准清掉了。

本脚本把同一条路径上的【所有非写入步骤】提前走一遍，并预测：
    · 6 个关节当前读数是否落在可编码窗口内（决定你要不要动手调姿势）
    · 已存在的校准文件是否有「行程超出编码器 0~4095」这类隐患
    · 每个关节的行程中点离 2047 有多远（衡量上次摆中位准不准）

只读保证（代码可核对）
    · connect(calibrate=False)  —— 不触发自动校准
    · 只调用 sync_read / read，全程没有 bus.write
    · 不调用 disable_torque()（它会写 Torque_Enable/Lock）
    · disconnect(disable_torque=False) —— 不动用户机械臂的力矩状态

用法
    python _tools/preflight_calib.py              # 两臂都查
    python _tools/preflight_calib.py follower
    python _tools/preflight_calib.py leader
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows 控制台默认走 cp936，中文会被下游按 UTF-8 解码成 U+FFFD。
# 强制 UTF-8 输出，保证日志可读。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import draccus  # noqa: E402

from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig  # noqa: E402
from lerobot.robots.so_follower.so_follower import SOFollower  # noqa: E402
from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig  # noqa: E402
from lerobot.teleoperators.so_leader.so_leader import SOLeader  # noqa: E402
from lerobot.utils.constants import HF_LEROBOT_HOME  # noqa: E402

# 与 calibrate_arm.py 保持一致
MARGIN = 300            # 摆中位时要求的原始读数安全余量
HOMING_MAX = 2047       # Homing_Offset 是 11 位符号幅值
ENCODER_FULL = 4095     # 12 位编码器满量程
SPAN_TARGET = 1000      # calibrate_arm.py 认为「推够了」的行程阈值

CN = {
    "shoulder_pan": "底座旋转",
    "shoulder_lift": "肩部抬升",
    "elbow_flex": "肘部弯曲",
    "wrist_flex": "腕部俯仰",
    "wrist_roll": "腕部自转",
    "gripper": "夹爪开合",
}
FULL_TURN = "wrist_roll"

DEFAULTS = {
    "follower": {"port": "COM10", "id": "my_awesome_follower_arm"},
    "leader": {"port": "COM11", "id": "my_awesome_leader_arm"},
}
CALIB_SUBDIR = {
    "follower": Path("robots") / "so_follower",
    "leader": Path("teleoperators") / "so_leader",
}


def s16(v: int) -> int:
    """把可能已经被解成 16 位的读数规整一下（符号幅值经库解码后已是 int）。"""
    return v


def calib_path(arm: str, rid: str) -> Path:
    return HF_LEROBOT_HOME / "calibration" / CALIB_SUBDIR[arm] / f"{rid}.json"


def build(arm: str, port: str, rid: str):
    """★复刻 calibrate_arm.py 的构造方式★ 这一步就是最容易因 API 变动而崩的地方。"""
    if arm == "follower":
        cfg = draccus.parse(
            config_class=SOFollowerRobotConfig,
            args=[f"--port={port}", f"--id={rid}"],
        )
        return SOFollower(cfg), "从臂 Follower【白色】"
    cfg = draccus.parse(
        config_class=SOLeaderTeleopConfig,
        args=[f"--port={port}", f"--id={rid}"],
    )
    return SOLeader(cfg), "主臂 Leader【黑色】"


def check_arm(arm: str, port: str, rid: str) -> bool:
    ok = True
    label = "从臂 Follower【白色】" if arm == "follower" else "主臂 Leader【黑色】"

    print("=" * 96)
    print(f"  {label} | {port} | id={rid}")
    print("=" * 96)

    # ---- 步骤 1：import / draccus / 构造（这一步过了，说明 API 没变） ----
    try:
        robot, label = build(arm, port, rid)
    except Exception as exc:  # noqa: BLE001
        print(f"  [XX] 构造失败: {type(exc).__name__}: {exc}")
        return False
    print(f"  [OK] 1/5 import + draccus 解析 + {type(robot).__name__} 构造通过")

    # ---- 步骤 2：连接（calibrate=False，不会触发自动校准） ----
    try:
        robot.connect(calibrate=False)
    except Exception as exc:  # noqa: BLE001
        print(f"  [XX] 连接 {port} 失败: {type(exc).__name__}: {exc}")
        return False
    print("  [OK] 2/5 连接通过（calibrate=False）")

    # 舵机里存的校准 与 校准文件 是否一致？
    # 不一致时 lerobot-teleoperate / lerobot-record 会在连接时弹
    # "Press ENTER to use provided calibration file ... or type 'c'"，
    # 提前告诉用户，免得现场被问懵。
    try:
        consistent = robot.is_calibrated
    except Exception as exc:  # noqa: BLE001
        consistent = None
        print(f"  [!!] is_calibrated 检查失败: {type(exc).__name__}: {exc}")
    if consistent is True:
        print("       → 舵机内校准与校准文件【一致】，遥操作/采集不会弹重新校准提示")
    elif consistent is False:
        print("  [!!] 舵机内校准与校准文件【不一致】！")
        print("       → 跑遥操作/采集时会问 Press ENTER to use provided calibration file ...")
        print("         按回车 = 用 JSON 覆盖舵机；输入 c = 重新校准。")
        print("         想让它们一致，重跑一次 calibrate_arm.py 即可。")

    bus = robot.bus
    motors = list(bus.motors)

    try:
        # ---- 步骤 3：读寄存器（★只读★） ----
        present = bus.sync_read("Present_Position", motors, normalize=False)
        torque = bus.sync_read("Torque_Enable", motors, normalize=False)
        homing = {m: bus.read("Homing_Offset", m, normalize=False) for m in motors}
        lo = {m: bus.read("Min_Position_Limit", m, normalize=False) for m in motors}
        hi = {m: bus.read("Max_Position_Limit", m, normalize=False) for m in motors}
        print("  [OK] 3/5 寄存器读取通过（Present_Position / Torque_Enable / "
              "Homing_Offset / Min|Max_Position_Limit）")

        # ---- 步骤 4：预测 reset 之后的原始读数，并检查可编码窗口 ----
        #  servo 语义: Present_Position = Actual_Position - Homing_Offset
        #  → reset_calibration 把 offset 写 0 后，读数就是 Actual
        #  → Actual = 当前 Present_Position + 当前 Homing_Offset
        print()
        print("  步骤 4/5：预测 reset 之后摆中位时的原始读数")
        print("            （calibrate_arm.py 要求落在 "
              f"{MARGIN}~{ENCODER_FULL - MARGIN}，否则无法算出合法 Homing_Offset）")
        print()
        print(f"  {'关节':<14} | {'ID':>2} | {'当前读数':>8} | {'当前Offset':>10} | "
              f"{'reset后原始值':>12} | {'力矩':>4} | 判定")
        print("  " + "-" * 88)

        need_adjust: list[tuple[str, int, int]] = []
        for m in motors:
            raw = present[m] + homing[m]
            in_win = MARGIN <= raw <= ENCODER_FULL - MARGIN
            if not in_win:
                need_adjust.append((m, raw, m))
            print(f"  {m:<14} | {bus.motors[m].id:>2} | {present[m]:>8} | "
                  f"{homing[m]:>10} | {raw:>12} | {torque[m]:>4} | "
                  f"{'OK' if in_win else '★需要用手调到窗口中★'}")

        # ---- 步骤 5：体检已有校准文件 ----
        print()
        print("  步骤 5/5：已有校准文件体检")
        p = calib_path(arm, rid)
        if not p.exists():
            print(f"    （无校准文件：{p}）")
            print("    → 该臂尚未校准，必须完整走一遍 calibrate_arm.py")
        else:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                print(f"    [XX] JSON 解析失败: {exc}")
                return False

            print(f"    文件: {p}")
            print()
            print(f"    {'关节':<14} | {'range_min':>9} | {'range_max':>9} | {'行程':>6} | "
                  f"{'中点':>6} | {'中点偏移':>8} | 判定")
            print("    " + "-" * 84)
            for m in motors:
                c = data.get(m)
                if not c:
                    print(f"    {m:<14} | 校准文件里缺这个关节")
                    ok = False
                    continue
                rmin, rmax = c["range_min"], c["range_max"]
                span = rmax - rmin
                mid = (rmin + rmax) / 2
                off_c = mid - HOMING_MAX

                notes = []
                if rmin < 0 or rmax > ENCODER_FULL:
                    notes.append(f"★超出编码器 0~{ENCODER_FULL}★")
                if span < SPAN_TARGET and m != FULL_TURN:
                    notes.append("行程偏小")
                if abs(c["homing_offset"]) > HOMING_MAX:
                    notes.append("Offset 无法编码")
                if m != FULL_TURN and abs(off_c) > 400:
                    notes.append(f"中位偏了≈{abs(off_c):.0f}")
                print(f"    {m:<14} | {rmin:>9} | {rmax:>9} | {span:>6} | {mid:>6.0f} | "
                      f"{off_c:>+8.0f} | {'; '.join(notes) if notes else 'OK'}")
            print()
            print("    说明：「中点偏移」= 行程中点 - 2047。摆中位摆得准的话应该在 0 附近；")
            print("          |偏移| 大说明上次「活动范围中间」那个姿势没摆到真正的中点。")
            print("          ★注意★ 夹爪(gripper)天然会偏 —— 人手很难把夹爪停在正好一半，")
            print("          官方示例里夹爪也偏 658，所以夹爪偏不算问题。")

        if need_adjust:
            print()
            print("  【结论】跑 calibrate_arm.py 之前，请先用手把下列关节调到窗口内：")
            for m, raw, _ in need_adjust:
                print(f"    · {m:<14}（{CN[m]}）当前 reset 后原始值 = {raw:>6}，"
                      f"目标 {MARGIN}~{ENCODER_FULL - MARGIN}")
            print("    （按回车之前，界面里会实时显示这几个数，照着调即可）")
        else:
            print()
            print("  【结论】6 个关节的 reset 后原始值全部落在可编码窗口内，"
                  "直接跑 calibrate_arm.py 即可。")

        if any(torque[m] != 0 for m in motors):
            print()
            print("  [!!] 注意：有舵机当前 Torque_Enable != 0（力矩是开的）。")
            print("       calibrate_arm.py 会先 disable_torque()，那一下机械臂会突然变软 ——")
            print("       请先用手托住机械臂再继续。")

        return ok
    finally:
        # ★关键★ 不能写 disable_torque=True，否则会在用户不知情时把机械臂弄软
        try:
            robot.disconnect()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", nargs="?", choices=["follower", "leader", "both"], default="both")
    ap.add_argument("--follower-port", default=DEFAULTS["follower"]["port"])
    ap.add_argument("--leader-port", default=DEFAULTS["leader"]["port"])
    ap.add_argument("--follower-id", default=DEFAULTS["follower"]["id"])
    ap.add_argument("--leader-id", default=DEFAULTS["leader"]["id"])
    args = ap.parse_args()

    targets = []
    if args.arm in ("follower", "both"):
        targets.append(("follower", args.follower_port, args.follower_id))
    if args.arm in ("leader", "both"):
        targets.append(("leader", args.leader_port, args.leader_id))

    for arm, port, rid in targets:
        try:
            check_arm(arm, port, rid)
        except Exception as exc:  # noqa: BLE001
            print(f"[XX] {arm} 体检异常: {type(exc).__name__}: {exc}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
