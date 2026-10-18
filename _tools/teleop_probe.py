"""遥操作跟随精度探针 —— 把「准不准」变成数字（不写数据集、不存任何文件）。

为什么需要它
------------
`check_teleop_accuracy.py` 看的是【校准文件里的行程跨度】，是静态的、
只能回答「理论上幅度对不对」。但「现在真的跟得准不准」还要看实际伺服行为：
滞后、稳态偏差、极限处的饱和。这些只能边动边量。

本工具就是边动边量：
    主臂读数(action) -> 下发给从臂 -> 读从臂实际位置(state) -> 统计误差

三个指标
--------
1. **稳态误差**：主臂几乎不动时的 |state - action|。理想 → 0。
   它反映「校准零点/幅度是否真的对齐」，不受滞后干扰。
2. **动态误差**：主臂在动时的误差。必然比稳态大（从臂有 1~2 帧滞后），
   用来看「跟手是否跟得上」。
3. **行程覆盖率**：这次测试里各关节实际走过了校准行程的百分之多少。
   覆盖率太低说明你没把它推到位，这次测试对该关节没有结论。

安全
----
· 开始前有 10 秒倒计时，请扶好主臂；远端工作空间清空。
· 从臂一上力矩就会跟随主臂，若两臂姿势差得多会「啪」地对齐 —— 这是正常的。
· 结束时主动失能力矩，机械臂会变软。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import draccus  # noqa: E402

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
CN = {
    "shoulder_pan": "底座旋转", "shoulder_lift": "肩部抬升", "elbow_flex": "肘部弯曲",
    "wrist_flex": "腕部俯仰", "wrist_roll": "腕部自转", "gripper": "夹爪开合",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--follower-port", default="COM10")
    ap.add_argument("--leader-port", default="COM11")
    ap.add_argument("--follower-id", default="my_awesome_follower_arm")
    ap.add_argument("--leader-id", default="my_awesome_leader_arm")
    ap.add_argument("--seconds", type=float, default=75.0)
    ap.add_argument("--fps", type=float, default=30.0)
    args = ap.parse_args()

    from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
    from lerobot.robots.so_follower.so_follower import SOFollower
    from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig
    from lerobot.teleoperators.so_leader.so_leader import SOLeader

    fol = SOFollower(draccus.parse(config_class=SOFollowerRobotConfig,
                                   args=[f"--port={args.follower_port}", f"--id={args.follower_id}"]))
    lea = SOLeader(draccus.parse(config_class=SOLeaderTeleopConfig,
                                 args=[f"--port={args.leader_port}", f"--id={args.leader_id}"]))

    print("=" * 84)
    print("  遥操作跟随精度探针")
    print("=" * 84)
    print(f"  从臂 {args.follower_port}   主臂 {args.leader_port}   时长 {args.seconds:.0f}s")
    print("  指标：稳态误差（准不准）/ 动态误差（跟手快不快）/ 行程覆盖率（推没推到位）")
    print()

    try:
        fol.connect(calibrate=False)
        lea.connect(calibrate=False)
    except Exception as exc:  # noqa: BLE001
        print(f"  [XX] 连接失败: {type(exc).__name__}: {exc}")
        return 1

    # 记录（★必须在 try 之前初始化★：异常时 finally 之后的报告代码仍会执行，
    # 否则会 NameError —— 把「探针崩了」伪装成「遥操作不准」，误导判断）
    hist_act: dict[str, list[float]] = {j: [] for j in JOINTS}
    hist_err: dict[str, list[float]] = {j: [] for j in JOINTS}
    hist_moved: dict[str, list[float]] = {j: [] for j in JOINTS}

    try:
        # 先看两臂当前姿势差多少 —— 差太多的话，一上力矩会有一次「啪」的对齐
        act0 = lea.get_action()
        obs0 = fol.get_observation()
        gaps = {j: obs0[f"{j}.pos"] - act0[f"{j}.pos"] for j in JOINTS}
        big = {j: v for j, v in gaps.items() if abs(v) > 40}
        if big:
            print("  [!!] 两臂姿势差得比较多，上力矩时从臂会突然对齐到主臂：")
            for j, v in big.items():
                print(f"       {j:<15}（{CN[j]}）差 {v:+.0f}（归一化量程 ±100）")
            print("       请扶好主臂，并确认工作空间已清空。")
            print()

        print("  10 秒后开始 —— 请现在扶好主臂。")
        for k in range(10, 0, -1):
            print(f"\r  倒计时 {k:2d}s ...", end="", flush=True)
            time.sleep(1.0)
        print("\r  开始！请把每个关节【缓慢推满全程】来回 2~3 遍。      ")

        # 记录
        t0 = time.perf_counter()
        # get_action()/get_observation() 的键是 "<motor>.pos"，不是 "<motor>"
        prev_act = {j: act0[f"{j}.pos"] for j in JOINTS}
        last_render = 0.0
        while time.perf_counter() - t0 < args.seconds:
            loop_t = time.perf_counter()
            act = lea.get_action()
            fol.send_action(act)                 # 让从臂跟随主臂
            obs = fol.get_observation()          # 读从臂实际位置

            for j in JOINTS:
                k = f"{j}.pos"
                a = act[k]
                e = obs[k] - a
                hist_act[j].append(a)
                hist_err[j].append(e)
                hist_moved[j].append(abs(a - prev_act[j]))
                prev_act[j] = a

            now = time.perf_counter()
            if now - last_render > 1.0:
                last_render = now
                el = now - t0
                print(f"\r  采集中 {el:5.1f}/{args.seconds:.0f}s ...", end="", flush=True)
            dt = time.perf_counter() - loop_t
            if dt < 1 / args.fps:
                time.sleep(1 / args.fps - dt)

        print("\r  采集结束。                    ")
    finally:
        # 主动失能，让机械臂软下来（不依赖 disconnect 的默认行为，
        # 因为夹爪过载时它可能抛异常）
        for device, name in ((fol, "从臂"),):
            try:
                if device.is_connected:
                    device.bus.disable_torque()
            except Exception as exc:  # noqa: BLE001
                print(f"  [!!] {name} 失能失败（机械臂可能仍是硬的）: {exc}")
        for device in (fol, lea):
            try:
                if device.is_connected:
                    device.bus.disconnect(disable_torque=False)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------- 报告 -------------------------
    if not hist_err[JOINTS[0]]:
        print("  没采集到数据。")
        return 1

    print()
    print("=" * 84)
    print("  结果")
    print("=" * 84)
    print(f"  {'关节':<14} | {'稳态误差':>8} | {'动态误差':>8} | {'行程覆盖':>8} | 判定")
    print("  " + "-" * 76)

    worst_steady = 0.0
    worst_joint = ""
    for j in JOINTS:
        errs = hist_err[j]
        moved = hist_moved[j]
        # 稳态帧 = 主臂这一帧几乎没动
        steady = [e for e, m in zip(errs, moved) if m < 0.5]
        dyn = [e for e, m in zip(errs, moved) if m >= 0.5]

        steady_med = statistics.median([abs(e) for e in steady]) if steady else float("nan")
        dyn_med = statistics.median([abs(e) for e in dyn]) if dyn else float("nan")

        rng = max(hist_act[j]) - min(hist_act[j])
        cover = rng / 200.0 * 100  # 归一化量程 ±100 => 200

        notes = []
        if not steady:
            notes.append("几乎没停过，稳态无法测")
        elif steady_med > 8:
            notes.append("稳态偏差偏大")
        elif steady_med > 4:
            notes.append("稳态略有偏差")
        if cover < 40:
            notes.append(f"只走了 {cover:.0f}% 行程")

        if steady and steady_med == steady_med and steady_med > worst_steady:
            worst_steady, worst_joint = steady_med, j

        s_txt = f"{steady_med:8.1f}" if steady else "     n/a"
        d_txt = f"{dyn_med:8.1f}" if dyn else "     n/a"
        print(f"  {j:<14} | {s_txt} | {d_txt} | {cover:7.0f}% | "
              f"{'；'.join(notes) if notes else 'OK'}")

    print("  " + "-" * 76)
    print("  稳态误差 < 4 = 很准；4~8 = 可接受；> 8 = 有明显偏差")
    print("  动态误差必然大于稳态（从臂有 1~2 帧滞后），只用来判断是否跟得动")
    print()
    if worst_joint and worst_steady > 8:
        print(f"  ⚠ 最大稳态偏差 {worst_steady:.1f} @ {worst_joint}")
        print("    若想改善：重跑 scripts\\14-calibrate-arm.ps1（行程推到顶住限位）")
    else:
        print("  ✅ 稳态跟踪良好 —— 遥操作可以用于采集")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    sys.exit(main())
