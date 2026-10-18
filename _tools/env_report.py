#!/usr/bin/env python
"""环境自检报告（供 scripts\\00-check-env.ps1 调用）。

只做只读检查，不连接任何硬件。全部关键项通过时退出码为 0。

用法:
    python _tools/env_report.py
"""

from __future__ import annotations

import platform
import sys

FAILED: list[str] = []


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def bad(msg: str) -> None:
    print(f"  [XX] {msg}")
    FAILED.append(msg)


def warn(msg: str) -> None:
    print(f"  [!!] {msg}")


def main() -> int:
    print("  ---------- Python ----------")
    print(f"  解释器: {sys.executable}")
    print(f"  版本  : {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        bad(f"Python 版本过低（{platform.python_version()}），需要 >= 3.10")
    else:
        ok(f"Python {platform.python_version()}")

    print("\n  ---------- 深度学习栈 ----------")
    try:
        import torch

        ok(f"torch {torch.__version__}")
        if torch.cuda.is_available():
            n = torch.cuda.device_count()
            name = torch.cuda.get_device_name(0)
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            ok(f"CUDA 可用：{n} 个 GPU，device0 = {name}（{total:.1f} GB）")
            try:
                x = torch.zeros(8, device="cuda")
                ok(f"GPU 实算通过（{float(x.sum())}）")
            except Exception as exc:  # noqa: BLE001
                bad(f"GPU 实算失败: {exc}")
        else:
            bad("torch.cuda.is_available() = False（训练会在 CPU 上跑，极慢）")
            print("       若驱动正常，可能是装成了 CPU 版 torch")
    except Exception as exc:  # noqa: BLE001
        bad(f"import torch 失败: {exc}")

    try:
        import torchvision

        ok(f"torchvision {torchvision.__version__}")
    except Exception as exc:  # noqa: BLE001
        bad(f"import torchvision 失败: {exc}")

    print("\n  ---------- LeRobot ----------")
    try:
        import lerobot

        ver = getattr(lerobot, "__version__", "unknown")
        ok(f"lerobot {ver}  ({lerobot.__file__})")
    except Exception as exc:  # noqa: BLE001
        bad(f"import lerobot 失败: {exc}")

    for mod, why in (
        ("draccus", "配置解析"),
        ("av", "视频编解码（pyav）"),
        ("pandas", "数据集元数据"),
        ("numpy", "数值计算"),
        ("safetensors", "权重读写"),
    ):
        try:
            m = __import__(mod)
            ok(f"{mod} {getattr(m, '__version__', '')} （{why}）")
        except Exception as exc:  # noqa: BLE001
            bad(f"import {mod} 失败: {exc}")

    print("\n  ---------- 关键子模块 ----------")
    for mod, why in (
        ("lerobot.robots.so_follower", "从臂"),
        ("lerobot.teleoperators.so_leader", "主臂"),
        ("lerobot.policies.act.modeling_act", "ACT 策略"),
        ("lerobot.datasets.lerobot_dataset", "数据集"),
        ("lerobot.motors.feetech", "Feetech 总线"),
    ):
        try:
            __import__(mod)
            ok(f"{mod} （{why}）")
        except Exception as exc:  # noqa: BLE001
            bad(f"import {mod} 失败: {exc}")

    print("\n  ---------- 相机后端 ----------")
    for mod, why in (
        ("lerobot.cameras.opencv.configuration_opencv", "OpenCV 相机"),
        ("lerobot.cameras.orbbec.configuration_orbbec", "Orbbec 相机"),
    ):
        try:
            __import__(mod)
            ok(f"{mod} （{why}）")
        except Exception as exc:  # noqa: BLE001
            warn(f"{mod} 不可用（{why}）: {type(exc).__name__} — 只在该相机类型下才必需")

    print("\n  ---------- 汇总 ----------")
    if FAILED:
        print(f"  有 {len(FAILED)} 项未通过：")
        for f in FAILED:
            print(f"    - {f}")
        return 1
    print("  全部关键项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
