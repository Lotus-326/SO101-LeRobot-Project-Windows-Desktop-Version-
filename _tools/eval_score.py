#!/usr/bin/env python
"""评估结果打分器：从 LeRobot 评估数据集里统计抓放成功率。

判定标准（可解释、可复现）：
  成功 = 首帧能看到方块(红色像素 >= --present)
         且 末帧看不到方块(红色像素 < --left)
         且 方块最后一次可见的时刻 早于回合结束 1 秒以上

【重要】帧窗边界
  LeRobot 把连续录制的视频拼在一个文件里，`ep N` 的 `to_timestamp`
  正好等于 `ep N+1` 的 `from_timestamp`。如果按 `t <= t1` 取帧，
  每个回合的"最后一帧"其实是**下一个回合的第一帧** —— 那一帧里
  操作者通常已经把方块摆回起点，于是会把成功全判成失败。
  本工具用 `t >= t1 - 1e-6: break` 严格排除边界帧。

用法:
    python _tools/eval_score.py eval_fixed_p1
    python _tools/eval_score.py eval_base_v2 --montage
    python _tools/eval_score.py eval_r1b_training_points --by-position
"""

from __future__ import annotations

import argparse
from pathlib import Path

import av
import numpy as np
import pandas as pd

CAM = "observation.images.front"
ROOT = Path.home() / ".cache" / "huggingface" / "lerobot" / "seeedstudio123"


def red_metrics(img: np.ndarray) -> tuple[int, tuple[float, float] | None]:
    a = img.astype(np.float32)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    m = (R > 90) & (R > G * 1.55) & (R > B * 1.55)
    n = int(m.sum())
    if n < 50:
        return n, None
    ys, xs = np.nonzero(m)
    return n, (float(xs.mean()), float(ys.mean()))


def load_episode(ds: Path, meta: pd.DataFrame, ep: int):
    """按严格边界（t < t1）取出一个回合的所有帧。"""
    r = meta[meta.episode_index == ep].iloc[0]
    ci, fi = int(r[f"videos/{CAM}/chunk_index"]), int(r[f"videos/{CAM}/file_index"])
    vid = ds / "videos" / CAM / f"chunk-{ci:03d}" / f"file-{fi:03d}.mp4"
    t0 = float(r[f"videos/{CAM}/from_timestamp"])
    t1 = float(r[f"videos/{CAM}/to_timestamp"])
    buf = []
    with av.open(str(vid)) as c:
        s = c.streams.video[0]
        c.seek(0, stream=s)
        for fr in c.decode(s):
            t = float(fr.pts * s.time_base)
            if t < t0 - 1e-6:
                continue
            if t >= t1 - 1e-6:
                break
            buf.append(fr.to_ndarray(format="rgb24"))
    return buf


def main() -> None:
    ap = argparse.ArgumentParser(description="评估数据集抓放成功率打分")
    ap.add_argument("dataset", help="数据集名（seeedstudio123/ 下的目录名）或用 --path 指定")
    ap.add_argument("--path", type=Path, default=None, help="数据集的绝对路径")
    ap.add_argument("--present", type=int, default=400, help="首帧判定「方块在」的红色像素阈值")
    ap.add_argument("--left", type=int, default=200, help="末帧判定「方块不见」的红色像素阈值")
    ap.add_argument("--by-position", action="store_true", help="按方块起始位置分组统计")
    ap.add_argument("--montage", action="store_true", help="输出末帧拼图")
    args = ap.parse_args()

    ds = args.path or (ROOT / args.dataset)
    if not (ds / "meta" / "info.json").is_file():
        raise SystemExit(f"找不到数据集: {ds}")

    meta = pd.concat(
        [pd.read_parquet(p) for p in sorted((ds / "meta" / "episodes").rglob("*.parquet"))],
        ignore_index=True,
    )
    eps = sorted(meta.episode_index.tolist())
    print(f"  数据集: {ds.name}   {len(eps)} 条\n")
    print(f"  {'ep':>3} | {'帧数':>5} | {'首帧红':>6} | {'末帧红':>6} | {'最后可见':>9} | {'起点位置':>13} | 判定")
    print("  " + "-" * 88)

    rows, lasts = [], []
    for ep in eps:
        buf = load_episode(ds, meta, ep)
        if len(buf) < 10:
            print(f"  {ep:>3} | {len(buf):>5} | 帧数太少，跳过")
            continue
        n0, c0 = red_metrics(buf[min(5, len(buf) - 1)])
        nL, cL = red_metrics(buf[-1])
        last_vis = -1.0
        for i, im in enumerate(buf):
            if red_metrics(im)[0] >= args.left:
                last_vis = i / 30.0
        dur = len(buf) / 30.0
        ok = (n0 >= args.present) and (nL < args.left) and (last_vis < dur - 1.0)
        p0 = f"({c0[0]:.0f},{c0[1]:.0f})" if c0 else "-"
        tag = "✅ 成功" if ok else ("❌ 方块一直在" if nL >= args.left else "⚠ 起点无方块")
        print(f"  {ep:>3} | {len(buf):>5} | {n0:>6} | {nL:>6} | {last_vis:>8.1f}s | {p0:>13} | {tag}")
        rows.append({"ep": ep, "ok": ok, "x": c0[0] if c0 else np.nan, "y": c0[1] if c0 else np.nan,
                     "n0": n0, "nL": nL, "last_vis": last_vis, "dur": dur})
        lasts.append((ep, buf[-1]))

    R = pd.DataFrame(rows)
    ok_n = int(R.ok.sum())
    print(f"\n  >>> 成功 {ok_n}/{len(R)} = {ok_n/max(1,len(R))*100:.0f}%")

    # 摆位一致性：做「同一点重复」时起点应几乎不动；分散太大说明摆偏了，成功率会被误读
    V0 = R.dropna(subset=["x"])
    if len(V0) >= 2:
        sx, sy = float(V0.x.std()), float(V0.y.std())
        span = float(np.hypot(V0.x.max() - V0.x.min(), V0.y.max() - V0.y.min()))
        print(f"\n  摆位一致性: x std {sx:.1f}px  y std {sy:.1f}px  最大跨度 {span:.0f}px")
        if span > 60:
            print("    ⚠ 起点分散较大 —— 若本意是「同一位置重复」，说明摆位有偏差，")
            print("      成功率会被稀释。逐条起点见上表最后一列。")

    if args.by_position and R.x.notna().any():
        V = R.dropna(subset=["x"]).copy()
        groups = []
        for _, r in V.iterrows():
            for g in groups:
                if np.hypot(g[0]["x"] - r.x, g[0]["y"] - r.y) < 35:
                    g.append(r)
                    break
            else:
                groups.append([r])
        print(f"\n  按起始位置分组（共 {len(groups)} 个位置）：")
        print(f"    {'位置':>14} | {'次数':>4} | {'成功':>4} | 成功率")
        print("    " + "-" * 44)
        for g in sorted(groups, key=lambda g: g[0].x):
            xs = np.mean([r.x for r in g])
            ys = np.mean([r.y for r in g])
            k = int(sum(r.ok for r in g))
            print(f"    ({xs:4.0f},{ys:3.0f}) | {len(g):>4} | {k:>4} | {k/len(g)*100:>5.0f}%")

    if args.montage and lasts:
        from PIL import Image, ImageDraw

        cols = 5
        rws = (len(lasts) + cols - 1) // cols
        tw, th = 320, 240
        sheet = Image.new("RGB", (cols * tw, rws * (th + 20) + 26), (16, 16, 16))
        dr = ImageDraw.Draw(sheet)
        dr.text((6, 6), f"{ds.name}: 末帧（方块应已不见）", fill=(255, 255, 0))
        for i, (ep, img) in enumerate(lasts):
            rr, cc = divmod(i, cols)
            y = 26 + rr * (th + 20)
            sheet.paste(Image.fromarray(img).resize((tw, th)), (cc * tw, y))
            dr.text((cc * tw + 6, y + 4), f"ep{ep}", fill=(120, 255, 120))
        out = Path(f"lerobot/outputs/captured_images/score_{ds.name}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out)
        print(f"\n[OK] 末帧拼图 -> {out.resolve()}")


if __name__ == "__main__":
    main()
