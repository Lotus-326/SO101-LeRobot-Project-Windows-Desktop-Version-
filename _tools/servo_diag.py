"""单舵机链路诊断：跳过 LeRobot 的总线自检，直接判断「舵机坏了」还是「链路间歇性丢包」。

背景
----
`lerobot-record` / `lerobot-teleoperate` 在 `robot.connect()` 里会跑
`_assert_motors_exist()`（对所有 ID 做一次同步读）。只要有一个舵机在那一次
同步读里没应答，整台机器人就拒绝启动：

    RuntimeError: FeetechMotorsBus motor check failed on port 'COM10':
    Missing motor IDs: - 5 (expected model: 777)

这看不出根因：可能是舵机真坏了，也可能是接头松动导致偶尔丢包。
本脚本用 `connect(handshake=False)` 跳过那道自检，然后分三层取证：

  1. 反复 ping：每次拿到哪些 ID -> 量化掉包率（10 次里挂几次）
  2. 单点读寄存器：Model / ID / 位置 / 电压 / 温度 / 力矩
  3. 小幅度驱动：力矩使能 + 目标位置 ±delta，采样「位置是否真的跟着走」

判读
----
  · ping 几乎不掉 + 能动      -> 舵机没坏，是同步读的时序/接头问题（先压接头）
  · ping 掉一半 + 能动        -> 链路接触不良（换线/压接头）
  · ping 能通 + 不动/不动且电流高 -> 齿箱堵转或该舵机内部故障
  · ping 全掉                 -> 该舵机断电或线断

用法
----
    python _tools/servo_diag.py COM10 --id 5
    python _tools/servo_diag.py COM10 --id 5 --pings 20 --delta 80
    python _tools/servo_diag.py COM11 --leader --id 5      # 主臂对照
"""

from __future__ import annotations

import argparse
import sys
import time

from lerobot.motors import Motor, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus

MOTORS = {
    "shoulder_pan": Motor(1, "sts3215", MotorNormMode.RANGE_M100_100),
    "shoulder_lift": Motor(2, "sts3215", MotorNormMode.RANGE_M100_100),
    "elbow_flex": Motor(3, "sts3215", MotorNormMode.RANGE_M100_100),
    "wrist_flex": Motor(4, "sts3215", MotorNormMode.RANGE_M100_100),
    "wrist_roll": Motor(5, "sts3215", MotorNormMode.RANGE_M100_100),
    "gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
}

MA_PER_LSB = 6.5


def signed(raw: int) -> int:
    return raw - 65536 if raw > 32767 else raw


def snap(bus: FeetechMotorsBus, name: str) -> dict:
    return {
        "pos": bus.read("Present_Position", name, normalize=False),
        "moving": bus.read("Moving", name, normalize=False),
        "temp": bus.read("Present_Temperature", name, normalize=False),
        "volt": bus.read("Present_Voltage", name, normalize=False) / 10,
        "cur": abs(signed(bus.read("Present_Current", name, normalize=False))) * MA_PER_LSB,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("--leader", action="store_true")
    ap.add_argument("--id", type=int, default=5)
    ap.add_argument("--pings", type=int, default=10, help="ping 次数（默认 10）")
    ap.add_argument("--delta", type=int, default=60, help="驱动幅度 tick（默认 60 ≈ 5°）")
    ap.add_argument("--velocity", type=int, default=120)
    ap.add_argument("--timeout", type=float, default=4.0)
    ap.add_argument("--no-move", action="store_true", help="只读不驱动（更保守）")
    args = ap.parse_args()

    target = next((n for n, m in MOTORS.items() if m.id == args.id), None)
    if target is None:
        print(f"[XX] 本表里没有 ID={args.id}")
        return 2

    role = "Leader 主臂" if args.leader else "Follower 从臂"
    print(f"== 单舵机诊断 | {role} @ {args.port} | ID{args.id} ({target}) ==")

    bus = FeetechMotorsBus(port=args.port, motors=dict(MOTORS))
    try:
        bus.connect(handshake=False)  # ← 关键：跳过会拦住我们的自检
    except Exception as exc:  # noqa: BLE001
        print(f"[XX] 串口打不开: {type(exc).__name__}: {exc}")
        return 1

    torque_before = None
    try:
        # ---------- 1. ping 掉包率 ----------
        print(f"\n【1/3】连续 ping {args.pings} 次（看有哪些 ID 应答）")
        hits: dict[int, int] = {}
        for i in range(args.pings):
            try:
                found = bus.broadcast_ping() or {}
            except Exception as exc:  # noqa: BLE001
                print(f"   #{i + 1:>2}: 异常 {type(exc).__name__}: {exc}")
                continue
            ids = sorted(found)
            for k in ids:
                hits[k] = hits.get(k, 0) + 1
            mark = "OK " if args.id in found else "MISS"
            print(f"   #{i + 1:>2}: {mark} ids={ids}")
        print("\n   应答率：")
        for k in sorted(hits):
            print(f"     ID{k}: {hits[k]}/{args.pings} ({100 * hits[k] / args.pings:.0f}%)")
        if args.id not in hits:
            print(f"     ID{args.id}: 0/{args.pings}  ← 完全不应答")

        # ---------- 2. 单点读寄存器 ----------
        print(f"\n【2/3】单点读 ID{args.id} 寄存器")
        try:
            model = bus.read("Model_Number", target, normalize=False)
            sid = bus.read("ID", target, normalize=False)
            baud = bus.read("Baud_Rate", target, normalize=False)
            s0 = snap(bus, target)
            torque_before = bus.read("Torque_Enable", target, normalize=False)
            print(f"   Model={model}  ID={sid}  Baud={baud}")
            print(
                f"   位置 {s0['pos']}  Moving={s0['moving']}  Torque={torque_before}  "
                f"{s0['volt']:.1f}V  {s0['temp']}℃  {s0['cur']:.0f}mA"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"   [XX] 读寄存器失败: {type(exc).__name__}: {exc}")
            print("   -> 该舵机链路不通，先查线/接头再谈是否损坏")
            return 1

        if args.no_move:
            print("\n【3/3】--no-move，跳过驱动测试")
            return 0

        # ---------- 3. 小幅度驱动 ----------
        print(f"\n【3/3】驱动测试：{s0['pos']} -> ±{args.delta}（±{args.delta / 4096 * 360:.1f}°）")
        print("   ⚠️ 确认该关节活动范围内无异物、无人手")
        goal = s0["pos"] + args.delta if s0["pos"] + args.delta < 4000 else s0["pos"] - args.delta
        bus.write("Acceleration", target, 10, normalize=False)
        bus.write("Goal_Velocity", target, args.velocity, normalize=False)
        bus.write("Torque_Enable", target, 1, normalize=False)
        time.sleep(0.2)
        bus.write("Goal_Position", target, goal, normalize=False)

        peak_cur, peak_temp = 0.0, 0
        t_start = time.perf_counter()
        last = s0
        while time.perf_counter() - t_start < args.timeout:
            last = snap(bus, target)
            peak_cur = max(peak_cur, last["cur"])
            peak_temp = max(peak_temp, last["temp"])
            if last["moving"] == 0 and time.perf_counter() - t_start > 0.4:
                break
            time.sleep(0.1)

        moved = last["pos"] - s0["pos"]
        print(f"   终点 {last['pos']}（位移 {moved:+d} / 目标 {goal - s0['pos']:+d}）")
        print(f"   Moving={last['moving']}  峰值电流 {peak_cur:.0f}mA  峰值温度 {peak_temp}℃")
        ok = abs(moved) >= max(15, abs(goal - s0["pos"]) // 3)
        print("   [OK] 舵机能动，闭环正常" if ok else "   [XX] 基本没动：堵转 / 力矩没生效 / 供电不足")

        # 回原位
        bus.write("Goal_Position", target, s0["pos"], normalize=False)
        t_start = time.perf_counter()
        while time.perf_counter() - t_start < args.timeout:
            s = snap(bus, target)
            if s["moving"] == 0 and time.perf_counter() - t_start > 0.4:
                break
            time.sleep(0.1)
        print(f"   已回原位 {snap(bus, target)['pos']}（起点 {s0['pos']}）")
        return 0 if ok else 1

    except Exception as exc:  # noqa: BLE001
        print(f"[XX] 诊断异常: {type(exc).__name__}: {exc}")
        return 1
    finally:
        try:
            if torque_before is not None:
                bus.write("Torque_Enable", target, torque_before, normalize=False)
                print(f"\n【已恢复】Torque_Enable = {torque_before}")
        except Exception:  # noqa: BLE001
            pass
        try:
            bus.disconnect(disable_torque=False)
        except TypeError:
            try:
                bus.disconnect()
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
