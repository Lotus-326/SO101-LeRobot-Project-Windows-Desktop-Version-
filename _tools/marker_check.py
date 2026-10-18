"""引导式「5 个标记点」取景检查 —— 逐点拍照 + 汇总判定。

为什么单独做一个
----------------
采集前必须确认「方块摆在计划里的每个标记点上时都完整在画面内」。
用 `17-snapshot.ps1` 一张张跑要敲 5 次命令、还要自己横向比对数值；
本工具把这件事变成一次连续的引导流程：

    放点1 -> 回车拍照 -> 就地给判据 -> （不合格可 r 重拍）
    放点2 -> ...
    ...
    最后打印汇总表 + 整体 YES/NO

判据沿用 `snapshot.py`：**最大红色连通域**（不是所有红色像素的包围盒），
因为远处几个像素的红色噪点会把包围盒撑到整个画面，让「贴边」判断失效。

用法（一般通过 scripts\\19-marker-check.ps1 调用）
    python _tools/marker_check.py --spec "{ front: {...} }"
    python _tools/marker_check.py --spec "..." --points 5
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import draccus  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_tools"))

from snapshot import _largest_blob  # noqa: E402
import numpy as np  # noqa: E402

OUTDIR = ROOT / "lerobot" / "outputs" / "captured_images"


def measure(f: np.ndarray) -> dict:
    """返回该帧的取景指标。"""
    h, w = f.shape[:2]
    r = f[:, :, 0].astype(np.int16)
    g = f[:, :, 1].astype(np.int16)
    b = f[:, :, 2].astype(np.int16)
    red = (r > 110) & (r - g > 45) & (r - b > 45)
    blob = _largest_blob(red)
    if not blob:
        return {"ok": False, "why": "没找到红色物块（不在画面内/被遮挡/太暗）", "mean": float(f.mean())}

    ys = [p[0] for p in blob]
    xs = [p[1] for p in blob]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    area_pct = len(blob) / (w * h) * 100

    edge = []
    if x0 <= 1:
        edge.append("左")
    if x1 >= w - 2:
        edge.append("右")
    if y0 <= 1:
        edge.append("上")
    if y1 >= h - 2:
        edge.append("下")

    why = ""
    if edge:
        why = f"物块贴到画面{'/'.join(edge)}边缘（被裁切）"
    elif area_pct < 0.15:
        why = f"物块偏小（{area_pct:.2f}% < 0.15%）"

    return {
        "ok": not why,
        "why": why,
        "bbox": f"x{x0}-{x1}({bw}) y{y0}-{y1}({bh})",
        "w": bw, "h": bh,
        "area_pct": area_pct,
        "cx": (x0 + x1) // 2,
        "cy": (y0 + y1) // 2,
        "mean": float(f.mean()),
        "edge": edge,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--points", type=int, default=5)
    args = ap.parse_args()

    from PIL import Image
    from lerobot.cameras.utils import make_cameras_from_configs
    from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
    import lerobot.cameras.opencv.configuration_opencv  # noqa: F401
    try:
        import lerobot.cameras.orbbec.configuration_orbbec  # noqa: F401
    except Exception:  # noqa: BLE001
        pass

    OUTDIR.mkdir(parents=True, exist_ok=True)

    print("=" * 84)
    print(f"  5 个标记点取景检查（共 {args.points} 个点）")
    print("=" * 84)
    print("  ★ 先做这一步：把从臂摆到【录制时真正要用的起始姿势】★")
    print("    不要收在画面外 —— 那样验证的是假场景。")
    print("    录制时手臂一直在工作区里；如果它在起始姿势就挡住方块，")
    print("    策略在每条数据开头就看不到目标位置，学不到「看方块再抓」。")
    print()
    print("  流程：把方块放到标记点上（放平）-> 在终端按【回车】拍照 -> 看判据")
    print("        判据不合格可以输入 r 重拍；输入 q 随时退出")
    print()
    print("  ★ 这一步做完就把相机固定死，之后整个采集过程都不要再碰它 ★")
    print()

    # 打开相机（只开一次，后面每个点复用）
    cfg = draccus.parse(
        config_class=SOFollowerRobotConfig,
        args=["--port=COM0", "--id=marker", f"--cameras={args.spec}"],
    )
    cams = make_cameras_from_configs(cfg.cameras)
    name, cam = next(iter(cams.items()))

    results: list[dict] = []
    try:
        print(f"  正在连接相机 [{name}] ...")
        cam.connect(warmup=True)
        time.sleep(2.0)  # 让自动曝光稳定

        i = 1
        while i <= args.points:
            print()
            print("-" * 84)
            try:
                ans = input(f"  把方块放到【标记点 {i}】，摆平，然后按回车拍照"
                            f"（r=重拍上一个　q=退出）: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  已中断。")
                break

            if ans == "q":
                break
            if ans == "r":
                # 回退到上一个点重拍：必须同时把已记账的结果弹掉，
                # 否则汇总表里会留下旧数据。
                if i > 1:
                    i -= 1
                    if results:
                        results.pop()
                    print(f"  已回退，重新拍标记点 {i}。")
                else:
                    print("  已经是第一个点，直接重拍即可。")
                continue

            # 连拍几帧取最后一帧（自动曝光更稳）
            f = None
            for _ in range(5):
                f = cam.async_read(timeout_ms=3000)
                time.sleep(0.25)
            if f is None:
                print("  [XX] 读不到帧，重试")
                continue

            m = measure(f)
            path = OUTDIR / f"front_mark{i}.png"
            Image.fromarray(f).save(path)

            if m["ok"]:
                print(f"  ✅ 标记点 {i}: {m['bbox']}  占画面 {m['area_pct']:.2f}%  "
                      f"中心 ({m['cx']},{m['cy']})  未贴边")
                print(f"     已保存 -> {path}")
                results.append({"i": i, **m})
                i += 1          # 只有合格才前进
            else:
                print(f"  ❌ 标记点 {i}: {m['why']}")
                if m.get("bbox"):
                    print(f"     bbox {m['bbox']}  占画面 {m['area_pct']:.2f}%")
                print("     -> 调整相机（后移/抬高/俯仰）或把方块摆正，然后按回车重拍同一个点")
    except KeyboardInterrupt:
        print("\n  已退出。")
    finally:
        try:
            if cam.is_connected:
                cam.disconnect()
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 汇总 ----------------
    print()
    print("=" * 84)
    print("  汇总")
    print("=" * 84)
    if not results:
        print("  没有成功的点。")
        return 1

    print(f"  {'点':>3} | {'物块包围盒':<26} | {'占画面':>7} | {'中心':>11} | 判定")
    print("  " + "-" * 76)
    for r in results:
        print(f"  {r['i']:>3} | {r['bbox']:<26} | {r['area_pct']:>6.2f}% | "
              f"({r['cx']:>3},{r['cy']:>3}) | ✅ 未贴边")

    xs = [r["cx"] for r in results]
    areas = [r["area_pct"] for r in results]
    print("  " + "-" * 76)
    print(f"  物块中心横向跨度: {min(xs)} ~ {max(xs)}（铺开 {max(xs)-min(xs)} px / 640）")
    print(f"  物块占比范围    : {min(areas):.2f}% ~ {max(areas):.2f}%")

    complete = len(results) == args.points
    print()
    if complete:
        print(f"  ✅ YES —— {args.points} 个点全部通过：物块完整可见、无裁切、大小可用")
        print()
        print("  接下来：")
        print("    1. 把相机固定死（这一步之后整个采集过程都不要再碰）")
        print("    2. 用胶带/纸片把这 5 个点在桌面上标出来（不要靠眼睛记）")
        print("    3. 跑 scripts\\18-gonogo.ps1 做开录前总检")
        print("    4. 跑 scripts\\06-record.ps1 正式采集")
        print()
        print(f"  样张已存到 {OUTDIR}\\front_mark1..{args.points}.png，随时可回看对比。")
    else:
        print(f"  ⚠️ 只完成了 {len(results)}/{args.points} 个点，未全部通过。")
    print("=" * 84)
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
