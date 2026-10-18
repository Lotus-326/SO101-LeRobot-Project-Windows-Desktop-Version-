#!/usr/bin/env python
"""相机配置片段语法检查（供 scripts\\00-check-env.ps1 调用）。

**不接硬件、不打开相机** —— 只用 draccus 解析配置字符串，
验证 type 是否已注册、字段名是否合法。这样在相机还没插上时
就能确认 scripts\\config.ps1 里的 Cameras 片段没写错。

用法:
    python _tools/check_cameras_spec.py "{ front: {type: orbbec_color, ...} }"

退出码 0 = 语法通过。
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("  用法: python _tools/check_cameras_spec.py \"{ front: {...} }\"")
        return 2
    spec = sys.argv[1].strip()
    if not spec:
        print("  [XX] 相机片段为空")
        return 1

    print(f"  输入片段: {spec}")

    # 需要先把相机后端注册进 draccus 的 choice registry，
    # 否则 type=orbbec_color 会被判为「未知类型」。
    try:
        import draccus

        from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig

        import lerobot.cameras.opencv.configuration_opencv  # noqa: F401
        import lerobot.cameras.orbbec.configuration_orbbec  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"  [XX] 导入失败: {type(exc).__name__}: {exc}")
        return 1

    class _Probe(SOFollowerRobotConfig):
        pass

    try:
        cfg = draccus.parse(
            config_class=SOFollowerRobotConfig,
            args=["--port=COM0", "--id=_spec_check", f"--cameras={spec}"],
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [XX] 解析失败: {type(exc).__name__}")
        for line in str(exc).splitlines():
            print(f"       {line}")
        return 1

    cams = cfg.cameras or {}
    if not cams:
        print("  [!!] 解析成功，但没有任何相机条目")
        return 0

    print(f"  [OK] 解析成功，共 {len(cams)} 个相机：")
    for name, cam in cams.items():
        ctype = getattr(cam, "type", "?")
        w = getattr(cam, "width", "?")
        h = getattr(cam, "height", "?")
        fps = getattr(cam, "fps", "?")
        print(f"      {name}: type={ctype}  {w}x{h} @{fps}fps")
        extra = {
            k: v
            for k, v in vars(cam).items()
            if k not in ("type", "width", "height", "fps", "rotation", "color_mode", "warmup_s")
        }
        if extra:
            print(f"          其他字段: {extra}")
    print("\n  说明：本检查只验语法，不验证设备是否存在。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
