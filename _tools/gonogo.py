"""正式采集前的 GO / NO-GO 自检 —— 一条命令回答「现在能不能开录 50 条」。

为什么需要它
------------
50 条数据要花约 1 小时，而且**中途发现相机歪了 / 校准漂了，前面录的就全废**。
所有能提前查的东西，都必须在开始之前查掉：

    1. 串口在不在、是不是 USB 转串口（不是蓝牙虚拟口）
    2. 两臂校准文件在不在
    3. 舵机里存的校准 与 校准文件 是否一致（不一致会让 record 中途弹重新校准）
    4. 主从臂行程幅度是否对齐（遥操作准不准的客观判据）
    5. 相机能不能开、物块在不在画面里、有没有被裁切
    6. 磁盘剩余空间够不够
    7. 目标数据集是否已存在（已存在就要 -Resume 或先清理，否则会接着录）

任何一项不过就打印 NO-GO 和具体原因，不让人带着问题开录。

用法
    python _tools/gonogo.py
    python _tools/gonogo.py --repo-id seeedstudio123/m1_pick_cube
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import draccus  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_tools"))

HF_HOME = Path.home() / ".cache" / "huggingface" / "lerobot"
CALIB = HF_HOME / "calibration"

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  —— {detail}" if detail else ""))
    return ok


# ---------------------------------------------------------------- 1. 串口
def check_ports(fol_port: str, lea_port: str) -> bool:
    print("\n[1/7] 串口")
    try:
        import winreg
        rk = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
        ports = {}
        i = 0
        while True:
            try:
                dev, val, _ = winreg.EnumValue(rk, i)
            except OSError:
                break
            ports[val] = dev
            i += 1
    except Exception as exc:  # noqa: BLE001
        return record("读取串口列表", False, str(exc))

    ok = True
    for label, port in (("从臂 Follower", fol_port), ("主臂 Leader", lea_port)):
        dev = ports.get(port)
        if dev is None:
            ok = record(f"{label} {port}", False, "端口不存在 —— 检查 USB 线/驱动/是否插好")
        elif "BTH" in dev.upper() or "BthModem" in dev:
            ok = record(f"{label} {port}", False, f"是蓝牙虚拟串口（{dev}），不是机械臂")
        else:
            record(f"{label} {port}", True, dev)
    return ok


# ------------------------------------------------- 2/3. 校准文件 + 一致性
def check_calibration(fol_port: str, lea_port: str, fol_id: str, lea_id: str) -> bool:
    print("\n[2/7] 校准文件")
    ok = True
    for label, sub, rid in (
        ("从臂", Path("robots") / "so_follower", fol_id),
        ("主臂", Path("teleoperators") / "so_leader", lea_id),
    ):
        p = CALIB / sub / f"{rid}.json"
        ok = record(f"{label} 校准文件 {rid}.json", p.exists(),
                    "" if p.exists() else f"缺失：{p}") and ok

    print("\n[3/7] 舵机内校准 与 校准文件 是否一致")
    print("      （不一致时 record/teleoperate 会中途弹 Press ENTER ... or type 'c'）")
    from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
    from lerobot.robots.so_follower.so_follower import SOFollower
    from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig
    from lerobot.teleoperators.so_leader.so_leader import SOLeader

    for label, port, rid, cfg_cls, cls in (
        ("从臂", fol_port, fol_id, SOFollowerRobotConfig, SOFollower),
        ("主臂", lea_port, lea_id, SOLeaderTeleopConfig, SOLeader),
    ):
        try:
            cfg = draccus.parse(config_class=cfg_cls, args=[f"--port={port}", f"--id={rid}"])
            robot = cls(cfg)
            robot.connect(calibrate=False)
            try:
                consistent = robot.is_calibrated
            finally:
                # ★不写 disable_torque=True★，不要动用户的力矩状态
                try:
                    robot.bus.disconnect(disable_torque=False)
                except Exception:  # noqa: BLE001
                    pass
            ok = record(f"{label} 舵机↔文件一致", bool(consistent),
                        "" if consistent else "不一致 —— 重跑 14-calibrate-arm.ps1 可修") and ok
        except Exception as exc:  # noqa: BLE001
            ok = record(f"{label} 一致性检查", False, f"{type(exc).__name__}: {exc}") and ok
    return ok


# ------------------------------------------------------- 4. 遥操作幅度对齐
def check_span(fol_id: str, lea_id: str) -> bool:
    print("\n[4/7] 主从臂行程幅度对齐（遥操作准不准）")
    try:
        from check_teleop_accuracy import TRUE_SPAN
    except Exception as exc:  # noqa: BLE001
        return record("读取参考跨度表", False, str(exc))

    try:
        fol = json.loads((CALIB / "robots" / "so_follower" / f"{fol_id}.json").read_text("utf-8"))
        lea = json.loads((CALIB / "teleoperators" / "so_leader" / f"{lea_id}.json").read_text("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return record("读取校准 JSON", False, str(exc))

    worst = 0.0
    worst_joint = ""
    for joint, (trueL, trueF) in TRUE_SPAN.items():
        spanL = lea[joint]["range_max"] - lea[joint]["range_min"]
        spanF = fol[joint]["range_max"] - fol[joint]["range_min"]
        gain = (spanF / trueF) / (spanL / trueL)
        err = abs(gain - 1.0) * 100
        if err > worst:
            worst, worst_joint = err, joint
        flag = "OK" if err < 8 else ("⚠" if err < 15 else "★")
        print(f"      {flag} {joint:<15} 增益 {gain:.2f}x  偏差 {err:4.1f}%")

    return record("幅度对齐（最大偏差 < 15%）", worst < 15,
                  f"最大偏差 {worst:.1f}% @ {worst_joint}")


# ------------------------------------------------------------ 5. 相机取景
def check_camera(spec: str) -> bool:
    print("\n[5/7] 相机取景")
    if not spec.strip():
        return record("相机", False, "config.ps1 的 Cameras 是空的")

    from lerobot.cameras.utils import make_cameras_from_configs
    from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
    import lerobot.cameras.opencv.configuration_opencv  # noqa: F401
    try:
        import lerobot.cameras.orbbec.configuration_orbbec  # noqa: F401
    except Exception:  # noqa: BLE001
        pass

    try:
        from snapshot import analyze
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        return record("导入取景分析", False, str(exc))

    try:
        cfg = draccus.parse(config_class=SOFollowerRobotConfig,
                            args=["--port=COM0", "--id=gonogo", f"--cameras={spec}"])
        cams = make_cameras_from_configs(cfg.cameras)
    except Exception as exc:  # noqa: BLE001
        return record("解析相机片段", False, str(exc))

    ok = True
    for name, cam in cams.items():
        try:
            cam.connect(warmup=True)
            time.sleep(1.5)
            f = None
            for _ in range(5):
                f = cam.async_read(timeout_ms=3000)
                time.sleep(0.3)
            if f is None:
                ok = record(f"{name} 取帧", False, "读不到帧") and ok
                continue
            # 复用 snapshot.py 的判据（最大红色连通域）
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                analyze(name, f)
            text = buf.getvalue()
            for line in text.strip().splitlines():
                print("      " + line.strip())
            blob_ok = ("没找到红色物块" not in text) and ("贴到画面" not in text)
            size_ok = "物块偏小" not in text
            ok = record(f"{name} 物块可见且未被裁切", blob_ok and size_ok) and ok
        except Exception as exc:  # noqa: BLE001
            ok = record(f"{name} 打开相机", False, f"{type(exc).__name__}: {exc}") and ok
        finally:
            try:
                if cam.is_connected:
                    cam.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return ok


# ---------------------------------------------------------- 6. 磁盘 / 7. 数据集
def check_disk_and_dataset(repo_id: str, num_episodes: int, episode_time_s: float) -> bool:
    print("\n[6/7] 磁盘空间")
    # 实测：640x480@30 的 libsvtav1 视频约 17 MB / 450 帧
    est_mb = num_episodes * (episode_time_s * 30 / 450) * 17
    du = shutil.disk_usage(str(HF_HOME if HF_HOME.exists() else Path.home()))
    free_gb = du.free / 1024**3
    ok = record(f"剩余空间够用（预计 {est_mb:.0f} MB）", free_gb * 1024 > est_mb * 3,
                f"剩余 {free_gb:.1f} GB")

    print("\n[7/7] 目标数据集状态")
    ds = HF_HOME / repo_id
    if ds.exists():
        info = ds / "meta" / "info.json"
        if info.exists():
            try:
                d = json.loads(info.read_text("utf-8"))
                record(f"{repo_id} 已存在", False,
                       f"已有 {d.get('total_episodes')} 条 / {d.get('total_frames')} 帧 —— "
                       f"要接着录请加 -Resume；要重录请先删掉这个目录")
            except Exception:  # noqa: BLE001
                record(f"{repo_id} 已存在", False, "目录已存在")
        else:
            record(f"{repo_id} 已存在", False, "目录已存在但没有 meta/info.json")
        ok = False
    else:
        record(f"{repo_id} 是空的（全新开始）", True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--follower-port", default="COM10")
    ap.add_argument("--leader-port", default="COM11")
    ap.add_argument("--follower-id", default="my_awesome_follower_arm")
    ap.add_argument("--leader-id", default="my_awesome_leader_arm")
    ap.add_argument("--repo-id", default="seeedstudio123/m1_pick_cube")
    ap.add_argument("--num-episodes", type=int, default=50)
    ap.add_argument("--episode-time-s", type=float, default=15.0)
    ap.add_argument("--spec", default="",
                    help="相机片段；不传则跳过相机检查")
    args = ap.parse_args()

    print("=" * 76)
    print("  正式采集前 GO / NO-GO 自检")
    print("=" * 76)
    print(f"  从臂 {args.follower_port}  主臂 {args.leader_port}  数据集 {args.repo_id}")
    print(f"  计划 {args.num_episodes} 条 x {args.episode_time_s:.0f}s")

    check_ports(args.follower_port, args.leader_port)
    check_calibration(args.follower_port, args.leader_port, args.follower_id, args.leader_id)
    check_span(args.follower_id, args.leader_id)
    if args.spec.strip():
        check_camera(args.spec)
    else:
        print("\n[5/7] 相机取景 —— 跳过（未传 --spec）")
    check_disk_and_dataset(args.repo_id, args.num_episodes, args.episode_time_s)

    print()
    print("=" * 76)
    failed = [r for r in RESULTS if not r[1]]
    if not failed:
        print("  ✅ GO —— 全部检查通过，可以开录")
        print()
        print(f"     powershell -ExecutionPolicy Bypass -File scripts\\06-record.ps1")
        print()
        print("  录制收尾三步（按 ESC 之前）：松开主臂扳机让夹爪张开 →")
        print("  把从臂摆到放松姿势 → 再按 ESC。可避免 Overload 报错。")
    else:
        print(f"  ❌ NO-GO —— {len(failed)} 项未通过：")
        for name, _ok, detail in failed:
            print(f"     · {name}" + (f"  ({detail})" if detail else ""))
        print()
        print("  先解决上面这些再开录 —— 50 条中途出问题的代价远大于现在花 1 分钟。")
    print("=" * 76)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
