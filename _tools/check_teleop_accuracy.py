"""量化「主从臂遥操作准不准」——只读校准文件，不碰硬件。

为什么需要它
------------
遥操作走的是【归一化】这一步：

    leader   : n   = (pos_L - min_L) / (max_L - min_L) * 200 - 100     ( clamp 到 ±100 )
    follower : pos_F = (n + 100) / 200 * (max_F - min_F) + min_F

把这个代进两臂各自的「编码器 → 物理角度」线性关系 θ = a·pos + b，可以证明：

    ★ Homing_Offset 会同时平移 pos 和 min/max，代入后【完全抵消】★

也就是说 —— **中位值（中位校准）写多少，对遥操作的跟随精度没有任何影响**。
真正决定精度的是 `max - min`（行程跨度）有没有覆盖到【两臂相同的物理全程】。

只要有一臂没有把关节推到顶住机械限位，跨度就被截断，于是：
  · 幅度错：从臂走得比主臂多/少（增益误差）
  · 相位错：两臂的「中位姿势」对应到行程的不同位置（偏移误差）
两者叠加就是肉眼看到的「遥操作不准」，而且**每个关节的错法还不一样**。

用法
    python _tools/check_teleop_accuracy.py
    python _tools/check_teleop_accuracy.py --follower-id X --leader-id Y
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

CALIB_ROOT = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"
FULL_TURN = "wrist_roll"

# 本机两臂各做一次 300 秒自由扫掠实测得到的【真实机械全程】跨度
# （logs\watch-COM10.log / watch-COM11.log，2026-10-16）
# ★顺序是 (主臂 Leader, 从臂 Follower)★ —— 与下面 trueL, trueF 的解包一致
TRUE_SPAN = {
    "shoulder_pan":  (2547, 2572),
    "shoulder_lift": (2377, 2382),
    "elbow_flex":    (2200, 2212),
    "wrist_flex":    (2296, 2258),
    "gripper":       (1213, 1454),
}
CN = {
    "shoulder_pan": "底座旋转",
    "shoulder_lift": "肩部抬升",
    "elbow_flex": "肘部弯曲",
    "wrist_flex": "腕部俯仰",
    "wrist_roll": "腕部自转",
    "gripper": "夹爪开合",
}


def load(arm: str, rid: str) -> dict | None:
    sub = Path("robots") / "so_follower" if arm == "follower" else Path("teleoperators") / "so_leader"
    p = CALIB_ROOT / sub / f"{rid}.json"
    if not p.exists():
        print(f"[XX] 缺少 {arm} 校准文件: {p}")
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--follower-id", default="my_awesome_follower_arm")
    ap.add_argument("--leader-id", default="my_awesome_leader_arm")
    args = ap.parse_args()

    fol = load("follower", args.follower_id)
    lea = load("leader", args.leader_id)
    if fol is None or lea is None:
        return 1

    print("=" * 104)
    print("  遥操作精度评估（只读，不改任何东西）")
    print("=" * 104)
    print(f"  从臂 Follower: {args.follower_id}")
    print(f"  主臂 Leader  : {args.leader_id}")
    print()
    print(f"  {'关节':<14} | {'主臂跨度':>8} | {'从臂跨度':>8} | {'主臂覆盖率':>9} | "
          f"{'从臂覆盖率':>9} | {'从臂/主臂增益':>12} | 判定")
    print("  " + "-" * 100)

    worst = 0.0
    for joint in ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "gripper"):
        cL, cF = lea[joint], fol[joint]
        spanL = cL["range_max"] - cL["range_min"]
        spanF = cF["range_max"] - cF["range_min"]
        trueL, trueF = TRUE_SPAN[joint]
        covL = spanL / trueL
        covF = spanF / trueF
        gain = covF / covL if covL else float("nan")

        err = abs(gain - 1.0) * 100
        worst = max(worst, err)
        if err < 5:
            verdict = "OK"
        elif err < 15:
            verdict = f"⚠ 幅度偏差 {err:.0f}%"
        else:
            verdict = f"★ 幅度偏差 {err:.0f}% ★"
        if covL < 0.9 or covF < 0.9:
            verdict += " | 有臂没推满"
        print(f"  {joint:<14} | {spanL:>8} | {spanF:>8} | {covL:>8.0%} | "
              f"{covF:>8.0%} | {gain:>11.2f}x | {verdict}")

    print("  " + "-" * 100)
    print()
    print("  读法：")
    print("    · 覆盖率 = 本次记录的跨度 / 真实机械全程。理想是 100%。")
    print("    · 「从臂/主臂增益」= 从臂覆盖率 / 主臂覆盖率。理想是 1.00x。")
    print("      > 1 = 主臂动一点、从臂动过头；< 1 = 从臂跟不上（幅度偏小）。")
    print("    · 每个关节的误差都不一样 —— 这就是手感上「不准」而不是「整体偏一点」的原因。")
    print()

    # ---- 中位摆位分析（解释性，不影响精度结论） ----
    print("  另外：各关节「中位姿势」在记录行程中的位置")
    print(f"  {'关节':<14} | {'主臂 min~2047~max':>24} | {'从臂 min~2047~max':>24} | 说明")
    print("  " + "-" * 100)
    for joint in ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "gripper"):
        cL, cF = lea[joint], fol[joint]
        aL, bL = 2047 - cL["range_min"], cL["range_max"] - 2047
        aF, bF = 2047 - cF["range_min"], cF["range_max"] - 2047
        note = "中位大致居中" if min(aL, bL) > 0.35 * (aL + bL) and min(aF, bF) > 0.35 * (aF + bF) \
            else "中位偏向一端"
        print(f"  {joint:<14} | {cL['range_min']:>7} ~2047~ {cL['range_max']:<6} | "
              f"{cF['range_min']:>7} ~2047~ {cF['range_max']:<6} | {note}")
    print("  " + "-" * 100)
    print()
    print("  ★重要★ 中位摆得偏不偏【不影响】遥操作精度（数学上被完全抵消，见本文件开头）。")
    print("          它只影响两件事：能不能算出合法 Homing_Offset、行程会不会溢出编码器。")
    print()

    if worst > 15:
        print("  【结论】幅度偏差最大 %.0f%% —— 这就是「遥操作不准」的原因。" % worst)
        print("          修法：两臂都重跑一次 scripts\\14-calibrate-arm.ps1，")
        print("                第 2 步把每个关节【推到顶住机械限位】，推完按回车结束。")
    elif worst > 5:
        print("  【结论】幅度偏差最大 %.0f%%，能感觉到但不算严重。" % worst)
        print("          想要更准，建议重跑校准并把每个关节推到顶住限位。")
    else:
        print("  【结论】各关节幅度偏差都在 5% 以内，遥操作映射正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
