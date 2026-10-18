"""抓一张相机样张，用于确认取景（不碰机械臂、不写任何 EEPROM）。

为什么单独做一个
----------------
采集前最值得花时间的一件事，是**把物体摆到计划里的每个位置、各拍一张**，
确认它们全都在画面内、而且足够大。
这一条命令就是干这个的 —— 比开采集脚本试录一条快得多。

用法（一般通过 scripts\\17-snapshot.ps1 调用，它会自动读 config.ps1）
    python _tools/snapshot.py --spec "{ front: {type: orbbec_color, ...} }"
    python _tools/snapshot.py --spec "..." --label pos1 --frames 5
    python _tools/snapshot.py --spec "..." --out lerobot/outputs/captured_images/x.png
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import draccus
import numpy as np

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

import lerobot.cameras.opencv.configuration_opencv  # noqa: F401
from lerobot.cameras.utils import make_cameras_from_configs  # noqa: E402
from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig  # noqa: E402

try:
    import lerobot.cameras.orbbec.configuration_orbbec  # noqa: F401
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[1]


def _largest_blob(mask: np.ndarray):
    """返回最大连通域的坐标列表（8 邻域）。只对红色掩码跑，像素很少，够快。

    为什么必须要连通域、不能直接用所有红色像素的包围盒：
    画面里常有几个像素的红色噪点（远处反光、背景里的红色物件），
    它们会把包围盒撑到整个画面 —— 于是「有没有贴边」的判断完全失效，
    还会误报「物块被裁切」。实测就踩到了这个坑（噪点把 bbox 从 75px 撑到 430px）。
    """
    from collections import deque

    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best: list[tuple[int, int]] = []
    for sy in range(h):
        for sx in np.nonzero(mask[sy] & ~seen[sy])[0]:
            if seen[sy, sx]:
                continue
            q = deque([(int(sy), int(sx))])
            seen[sy, sx] = True
            pts: list[tuple[int, int]] = []
            while q:
                y, x = q.popleft()
                pts.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            q.append((ny, nx))
            if len(pts) > len(best):
                best = pts
    return best


def analyze(name: str, f: np.ndarray) -> None:
    """给一点客观提示，帮助判断取景是否适合训练。"""
    h, w = f.shape[:2]
    print(f"[OK] {name}: shape={f.shape} dtype={f.dtype} "
          f"mean={f.mean():.1f} min={f.min()} max={f.max()}")

    if f.mean() < 1:
        print("     [!!] 画面几乎全黑 —— 检查镜头盖 / 曝光 / 是否被遮住")
        return
    if f.mean() > 245:
        print("     [!!] 画面几乎全白 —— 严重过曝，降低环境光或调曝光")

    # 高饱和度的红色像素 —— 本项目的目标物是红色方块。
    r = f[:, :, 0].astype(np.int16)
    g = f[:, :, 1].astype(np.int16)
    b = f[:, :, 2].astype(np.int16)
    red = (r > 110) & (r - g > 45) & (r - b > 45)
    total_ratio = red.mean() * 100
    print(f"     画面尺寸 {w}x{h}；红色像素共 {int(red.sum())} 个（{total_ratio:.2f}%）")

    blob = _largest_blob(red)
    if not blob:
        print("     [!!] 没找到红色物块 —— 物块不在画面内 / 被遮挡 / 光照太暗")
        return

    ys = [p[0] for p in blob]
    xs = [p[1] for p in blob]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    area_pct = len(blob) / (w * h) * 100
    print(f"     最大红色连通域（=物块）: x {x0}~{x1} ({bw}px)  y {y0}~{y1} ({bh}px)  "
          f"面积 {len(blob)}px（占画面 {area_pct:.2f}%）")

    if len(blob) < red.sum() * 0.5:
        print(f"     [注] 另有 {int(red.sum()) - len(blob)} 个零星红色噪点，已忽略")

    edge = []
    if x0 <= 1:
        edge.append("左")
    if x1 >= w - 2:
        edge.append("右")
    if y0 <= 1:
        edge.append("上")
    if y1 >= h - 2:
        edge.append("下")
    if edge:
        print(f"     [!!] 物块贴到画面{'/'.join(edge)}边缘 —— 被裁切了，把相机后移/抬高一点")
    else:
        print("     物块没有贴边（未被裁切）✓")

    if area_pct < 0.15:
        print(f"     [!!] 物块偏小（{area_pct:.2f}% < 0.15%）—— 建议相机靠近一些")
    elif area_pct > 12:
        print(f"     [注] 物块占比很大（{area_pct:.2f}%），确认没有过曝或误检")
    else:
        print(f"     物块大小合理（{area_pct:.2f}%）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="相机片段，与 config.ps1 的 Cameras 一致")
    ap.add_argument("--out", default=None, help="输出 png 路径")
    ap.add_argument("--label", default="now", help="输出文件名标签（默认 now）")
    ap.add_argument("--frames", type=int, default=5, help="丢弃前 N 帧让自动曝光稳定")
    args = ap.parse_args()

    cfg = draccus.parse(
        config_class=SOFollowerRobotConfig,
        args=["--port=COM0", "--id=snapshot", f"--cameras={args.spec}"],
    )
    cams = make_cameras_from_configs(cfg.cameras)

    outdir = ROOT / "lerobot" / "outputs" / "captured_images"
    outdir.mkdir(parents=True, exist_ok=True)

    from PIL import Image  # 延后导入，失败时报错更清楚

    rc = 0
    for name, cam in cams.items():
        try:
            cam.connect(warmup=True)
            time.sleep(1.5)
            f = None
            for _ in range(max(1, args.frames)):
                f = cam.async_read(timeout_ms=3000)
                time.sleep(0.3)
            if f is None:
                print(f"[XX] {name}: 没读到帧")
                rc = 1
                continue

            path = Path(args.out) if args.out else outdir / f"{name}_{args.label}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(f).save(path)
            analyze(name, f)
            print(f"     -> {path.resolve()}")
        except Exception as exc:  # noqa: BLE001
            print(f"[XX] {name} 失败: {type(exc).__name__}: {exc}")
            rc = 1
        finally:
            try:
                if cam.is_connected:
                    cam.disconnect()
            except Exception:  # noqa: BLE001
                pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
