"""把【校准文件 JSON】写回【舵机 EEPROM】—— 等价于 lerobot-record 提示里的「按回车」。

为什么要这个工具
----------------
`robot.is_calibrated` 会把「舵机里存的 Homing_Offset / Min / Max_Position_Limit」
和校准文件逐字段对比。任何一次中途被打断的校准（`set_half_turn_homings()` 已经把
Homing_Offset 改了、但行程还没写回）都会让它变成 False。

结果：录制的第一秒会弹

    Press ENTER to use provided calibration file associated with the id ..., or type 'c' ...

对两臂各弹一次。按回车其实就等于执行本工具做的事（`bus.write_calibration()`），
但现场被打断很容易按错 —— 按成 'c' 就会重新校准，把已验证好的校准覆盖掉。

这个工具把这一步提前、显式、可核对地做完。

安全性
------
· 写 `Homing_Offset` 会改变舵机上报的位置。**必须先失能力矩**，否则舵机会
  突然朝旧目标冲过去。本工具会强制先 disable_torque()。
· 写完后保持力矩关闭，机械臂是软的 —— 请用手托住。
· 只写校准相关寄存器，不动 ID / 波特率 / PID。

用法
    python _tools/sync_calibration.py            # 两臂都同步
    python _tools/sync_calibration.py follower
    python _tools/sync_calibration.py --check    # 只对比，不写（干跑）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import draccus  # noqa: E402

DEFAULTS = {"follower": "COM10", "leader": "COM11"}
IDS = {"follower": "my_awesome_follower_arm", "leader": "my_awesome_leader_arm"}


def build(arm: str, port: str, rid: str):
    if arm == "follower":
        from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
        from lerobot.robots.so_follower.so_follower import SOFollower
        cls, cfg_cls = SOFollower, SOFollowerRobotConfig
    else:
        from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig
        from lerobot.teleoperators.so_leader.so_leader import SOLeader
        cls, cfg_cls = SOLeader, SOLeaderTeleopConfig
    cfg = draccus.parse(config_class=cfg_cls, args=[f"--port={port}", f"--id={rid}"])
    return cls(cfg)


def sync_arm(arm: str, port: str, rid: str, check_only: bool) -> bool:
    label = "从臂 Follower【白色】" if arm == "follower" else "主臂 Leader【黑色】"
    print("=" * 84)
    print(f"  {label} | {port} | id={rid}")
    print("=" * 84)

    try:
        robot = build(arm, port, rid)
        robot.connect(calibrate=False)
    except Exception as exc:  # noqa: BLE001
        print(f"  [XX] 连接失败: {type(exc).__name__}: {exc}")
        return False

    try:
        want = robot.calibration
        if not want:
            print("  [XX] 校准文件为空 / 未加载，无法同步")
            return False

        if robot.is_calibrated:
            print("  ✅ 舵机内校准已与校准文件一致，无需写入")
            return True

        got = robot.bus.read_calibration()

        print()
        print(f"  {'关节':<15} | {'字段':<13} | {'文件':>7} | {'舵机内':>7} | 差异")
        print("  " + "-" * 80)
        diffs = 0
        for m in robot.bus.motors:
            for f in ("homing_offset", "range_min", "range_max"):
                a = getattr(want[m], f)
                b = getattr(got[m], f)
                if a != b:
                    diffs += 1
                    print(f"  {m:<15} | {f:<13} | {a:>7} | {b:>7} | ★ {b - a:+d}")
        print("  " + "-" * 80)
        print(f"  共 {diffs} 处不一致")

        if check_only:
            print("\n  --check：只对比，未写入。")
            return False

        print()
        print("  写入前先失能力矩（避免 Homing_Offset 一变舵机就冲出去）...")
        robot.bus.disable_torque()

        # 这正是 lerobot-record 里「按回车」走的那一步
        robot.bus.write_calibration(want)
        print("  已写入 Homing_Offset + Min/Max_Position_Limit")

        if robot.is_calibrated:
            print("  ✅ 校验通过：舵机内校准已与校准文件一致")
            return True

        print("  [!!] 写完仍然不一致，请重跑一次；仍不行用 14-calibrate-arm.ps1 重新校准")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  [XX] 同步失败: {type(exc).__name__}: {exc}")
        return False
    finally:
        # 只关串口，不要再碰力矩状态（上面已显式失能过）
        try:
            robot.bus.disconnect(disable_torque=False)
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", nargs="?", choices=["follower", "leader", "both"], default="both")
    ap.add_argument("--check", action="store_true", help="只对比不写入")
    ap.add_argument("--follower-port", default=DEFAULTS["follower"])
    ap.add_argument("--leader-port", default=DEFAULTS["leader"])
    ap.add_argument("--follower-id", default=IDS["follower"])
    ap.add_argument("--leader-id", default=IDS["leader"])
    args = ap.parse_args()

    targets = []
    if args.arm in ("follower", "both"):
        targets.append(("follower", args.follower_port, args.follower_id))
    if args.arm in ("leader", "both"):
        targets.append(("leader", args.leader_port, args.leader_id))

    print()
    print("  ⚠ 写 Homing_Offset 会改变舵机上报位置；本工具会先失能力矩。")
    print("    写完后机械臂是软的，请用手托住。")
    print()

    ok = True
    for arm, port, rid in targets:
        ok = sync_arm(arm, port, rid, args.check) and ok
        print()

    print("=" * 84)
    if ok:
        print("  ✅ 全部一致 —— 可以开始录制")
    elif args.check:
        print("  ⚠ 存在不一致（--check 模式，未写入）")
    else:
        print("  ❌ 仍有不一致，先解决再录")
    print("=" * 84)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
