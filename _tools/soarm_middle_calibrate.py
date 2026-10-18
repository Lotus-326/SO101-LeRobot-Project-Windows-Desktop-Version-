"""SoARM「中位校准」的安全版 —— 与 Seeed_RoboController 的「串口中位校准」等价。

和 Seeed 工具的关系
------------------
Seeed 工具的「中位校准」走的是同一个舵机命令：

        unlock EEPROM  ->  write 1 byte @ 寄存器 40 (Torque_Enable) = 128  ->  lock EEPROM

128 是 Feetech 的特殊命令「把【当前位置】记为中位 2048」。本脚本做的是同一件事。

那为什么还要另写一个？
----------------------
Seeed 的 servo_quick_calibration.py 顺序是：
    失能所有舵机  ->  sleep(1)  ->  逐个写 128
那 1 秒里机械臂是**软的**，手一松就会在重力下垮下去，
于是「当前位置」= 垮下去的姿势，中位就被记歪了 —— 项目文档里记录的那次事故
（docs/11-舵机调试工具.md 的「实测事故记录」）就是这个模式。

本脚本把顺序改成：
    失能  ->  提示你用手摆好姿势  ->  【按回车确认】  ->  立刻写 128
写入发生在你确认姿势之后，中间没有「松手窗口」。

另外它还补了 Seeed 工具没有的两件事：
    · 写之前/之后都打印每个舵机的读数，能直接看出中位是否真的变成 ~2048
    · 全过程写日志到 logs\\middle-calibrate-*.log

用法
    python _tools/soarm_middle_calibrate.py follower            # COM10
    python _tools/soarm_middle_calibrate.py leader              # COM11
    python _tools/soarm_middle_calibrate.py leader --dry-run    # 只看不写
"""

from __future__ import annotations

import argparse
import atexit
import re
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
SDK_PARENT = ROOT / "tools" / "Seeed_RoboController"      # 里面就是 scservo_sdk 包
_ANSI_RE = re.compile(r"\033\[[0-9;]*[A-Za-z]")

sys.path.insert(0, str(SDK_PARENT))

try:
    from scservo_sdk.port_handler import PortHandler
    from scservo_sdk.sms_sts import sms_sts
    from scservo_sdk.scservo_def import COMM_SUCCESS
except ImportError as exc:  # noqa: BLE001
    print(f"[XX] 无法导入 scservo_sdk: {exc}")
    print(f"     期望在: {SDK_PARENT}\\scservo_sdk")
    print("     请先跑: scripts\\12-steering-tool.ps1 -Action setup")
    sys.exit(1)

BAUD_RATE = 1_000_000
REG_TORQUE_ENABLE = 40
REG_OFS_L = 31                    # Homing_Offset，2 字节，符号幅值（符号位 = bit11）
REG_PRESENT_POS_L = 56
CALIBRATE_MIDDLE = 128            # 写进寄存器 40 = 把当前位置设为中位 2048
MIDDLE = 2048

CN = {
    1: "shoulder_pan  底座旋转",
    2: "shoulder_lift 肩部抬升",
    3: "elbow_flex    肘部弯曲",
    4: "wrist_flex    腕部俯仰",
    5: "wrist_roll    腕部自转",
    6: "gripper       夹爪开合",
}
DEFAULTS = {"follower": "COM10", "leader": "COM11"}

_LOG_FH = None
_ORIG_STDOUT = None


class _Tee:
    def __init__(self, stream, fh):
        self.stream, self.fh = stream, fh

    def write(self, s):
        self.stream.write(s)
        self.fh.write(_ANSI_RE.sub("", s))
        return len(s)

    def flush(self):
        self.stream.flush()
        self.fh.flush()

    def isatty(self):
        return bool(getattr(self.stream, "isatty", lambda: False)())


def _close_log():
    global _LOG_FH
    fh, _LOG_FH = _LOG_FH, None
    try:
        if isinstance(sys.stdout, _Tee):
            sys.stdout.flush()
        if _ORIG_STDOUT is not None:
            sys.stdout = _ORIG_STDOUT
        if fh is not None:
            fh.flush()
            fh.close()
    except Exception:  # noqa: BLE001
        pass


def setup_log(arm: str) -> None:
    global _LOG_FH, _ORIG_STDOUT
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        p = LOG_DIR / f"middle-calibrate-{arm}-{time.strftime('%Y%m%d-%H%M%S')}.log"
        fh = open(p, "w", encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        print(f"[!!] 日志创建失败: {exc}")
        return
    _ORIG_STDOUT, _LOG_FH = sys.stdout, fh
    sys.stdout = _Tee(sys.stdout, fh)
    atexit.register(_close_log)
    print(f"[日志] 完整输出写入: {p}")


def decode_sign_magnitude_11(raw: int) -> int:
    mag = raw & 0x7FF
    return -mag if (raw >> 11) & 1 else mag


def scan(handler) -> list[int]:
    found = []
    for sid in range(1, 21):
        _, result, _err = handler.ping(sid)
        if result == COMM_SUCCESS:
            found.append(sid)
    return found


def read_pos(handler, sid) -> int | None:
    pos, result, _err = handler.ReadPos(sid)
    return pos if result == COMM_SUCCESS else None


def read_ofs(handler, sid) -> int | None:
    raw, result, _err = handler.read2ByteTxRx(sid, REG_OFS_L)
    return decode_sign_magnitude_11(raw) if result == COMM_SUCCESS else None


def read_torque(handler, sid) -> int | None:
    val, result, _err = handler.read1ByteTxRx(sid, REG_TORQUE_ENABLE)
    return val if result == COMM_SUCCESS else None


def table(handler, ids, title: str) -> None:
    print()
    print(f"  {title}")
    print(f"    {'ID':>2} | {'关节':<24} | {'位置':>6} | {'Homing_Offset':>13} | {'力矩':>4}")
    print("    " + "-" * 62)
    for sid in ids:
        pos = read_pos(handler, sid)
        ofs = read_ofs(handler, sid)
        tq = read_torque(handler, sid)
        name = CN.get(sid, "（非标准关节）")
        print(f"    {sid:>2} | {name:<24} | "
              f"{'--' if pos is None else pos:>6} | {'--' if ofs is None else ofs:>13} | "
              f"{'--' if tq is None else tq:>4}")


def set_torque(handler, ids, on: bool) -> None:
    for sid in ids:
        handler.write1ByteTxRx(sid, REG_TORQUE_ENABLE, 1 if on else 0)
        time.sleep(0.05)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=["follower", "leader"])
    ap.add_argument("--port", default=None)
    ap.add_argument("--dry-run", action="store_true", help="只读：显示读数，不写任何寄存器")
    args = ap.parse_args()

    port = args.port or DEFAULTS[args.arm]
    label = "从臂 Follower【白色】" if args.arm == "follower" else "主臂 Leader【黑色】"
    arm_key = "F" if args.arm == "follower" else "L"

    setup_log(args.arm)

    print("=" * 70)
    print(f"  SoARM 中位校准（安全版） | {label} | {port}")
    print("=" * 70)
    if args.dry_run:
        print("  ★ dry-run：只读，不会写任何寄存器 ★")

    port_handler = PortHandler(port)
    if not port_handler.openPort():
        print(f"[XX] 无法打开串口 {port}")
        return 1
    if not port_handler.setBaudRate(BAUD_RATE):
        print("[XX] 无法设置波特率 1M")
        port_handler.closePort()
        return 1
    handler = sms_sts(port_handler)

    try:
        print("\n  [1/4] 扫描舵机 ...")
        ids = scan(handler)
        if not ids:
            print("[XX] 总线上没有发现任何舵机，检查接线与供电")
            return 1
        print(f"        发现 ID: {ids}")
        missing = [i for i in range(1, 7) if i not in ids]
        if missing:
            print(f"  [!!] 标准 6 个关节里缺少 ID: {missing}")

        table(handler, ids, "写入前读数：")

        if args.dry_run:
            print("\n  dry-run 结束，未写入任何东西。")
            return 0

        print("\n  [2/4] 失能所有舵机（机械臂会变软，请用手托住）...")
        set_torque(handler, ids, on=False)
        print("        已失能。")
        table(handler, ids, "失能后读数（此时机械臂应由你托住）：")

        print()
        print("  " + "=" * 62)
        print("  [3/4] 把机械臂摆到【官方中位姿势】，然后按回车")
        print("  " + "=" * 62)
        print(f"        官方中位参考图（SO-101）：")
        print(f"          https://files.seeedstudio.com/wiki/robotics/projects/lerobot/so101/cal_{arm_key}1.jpg")
        print(f"          把结尾的 {arm_key}1 依次换成 {arm_key}2~{arm_key}6 即可（{arm_key}6 = 夹爪）")
        print()
        print("        ★ 摆好后【手不要松开】再按回车 ★")
        print("          当前姿势就是即将被记为「中位 2048」的姿势。")
        print()
        try:
            input("  >>> 摆好中位、托住不动，按回车继续... ")
        except (EOFError, KeyboardInterrupt):
            print("\n  已取消。")
            return 130

        table(handler, ids, "确认写入前的实际读数：")
        print()
        print("  接下来会给每个舵机写 128（当前位置 → 中位 2048）。")
        try:
            ans = input("  >>> 确认写入请输入 y 回车，其它键取消: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans != "y":
            print("  已取消，未写入任何东西。")
            return 1

        print("\n  [4/4] 写入中位 ...")
        ok_ids, fail_ids = [], []
        for sid in ids:
            r1, _ = handler.unLockEprom(sid)
            time.sleep(0.05)
            r2, _ = handler.write1ByteTxRx(sid, REG_TORQUE_ENABLE, CALIBRATE_MIDDLE)
            time.sleep(0.05)
            handler.LockEprom(sid)
            (ok_ids if (r1 == COMM_SUCCESS and r2 == COMM_SUCCESS) else fail_ids).append(sid)
            print(f"        ID{sid:<2} {'✅ 已写入中位' if sid in ok_ids else '❌ 写入失败'}")

        # 写 128 之后力矩位可能残留，显式关掉，让机械臂保持软的
        set_torque(handler, ids, on=False)

        table(handler, ids, "写入后读数（位置应接近 2048，Homing_Offset 会变化）：")

        if fail_ids:
            print(f"\n  [!!] 以下舵机写入失败: {fail_ids}")

        print()
        print("  " + "=" * 62)
        print("  中位校准完成。")
        print("  " + "=" * 62)
        print("  注意：这一步只把「中位/零点」对齐到官方参考姿势。")
        print("        它【不会】修正遥操作的幅度 —— 幅度取决于 LeRobot 校准文件里的")
        print("        range_min/range_max 跨度。所以接下来必须再做一次：")
        print()
        print(f"          powershell -ExecutionPolicy Bypass -File scripts\\14-calibrate-arm.ps1 -Arm {args.arm}")
        print()
        print("        第 2 步把每个关节【推到顶住机械限位】，推完按回车结束。")
        return 0
    finally:
        try:
            port_handler.closePort()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
