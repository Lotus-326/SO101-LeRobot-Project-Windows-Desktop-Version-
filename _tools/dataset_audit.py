"""数据集体检 —— 逐条判「抓成功了没」，揪出要删的 episode（只读，不改数据）。

为什么不能用「夹爪开合幅度」判断成败
------------------------------------
最初我用 `st[:,5].max()-min()`（夹爪归一化行程）当判据，结果 100 条里报了 33 条
「夹爪没开合」。但抽视频帧一看：**这 33 条里绝大多数结束时方块都不在垫子上了，
也就是都抓成功了。**

原因：主臂夹爪是**扳机**，每次捏的深度本来就不一样；而且方块小，有时夹爪
只需要动一点点就能夹住。所以「夹爪动了多少」**不能代表成败**。

真正的判据：**看画面里方块还在不在**
------------------------------------
- **首帧**红色像素数 → 开头方块是否可见（太小说明被夹爪挡住了）
- **末帧**红色像素数 → 已抓走则 ≈ 0；**还留在垫子上 = 这一条抓取失败**

本工具直接从数据集视频里解出这两个帧来算，是「结果导向」的判据。

用法
    python _tools/dataset_audit.py
    python _tools/dataset_audit.py --no-video        # 跳过视频分析（快）
    python _tools/dataset_audit.py --montage         # 把失败条目的首/末帧拼图导出
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HF = Path.home() / ".cache" / "huggingface" / "lerobot"
CAM = "observation.images.front"

MIN_SECONDS = 3.0
MAX_STILL_PCT = 70.0
MAX_TRACK_ERR = 10.0
RED_PRESENT = 400     # 首帧红色 >= 这个数才算「方块清楚可见」
RED_LEFT = 200        # 末帧红色 > 这个数 = 方块还在垫子上 = 抓取失败


def red_area(img: np.ndarray) -> int:
    r = img[:, :, 0].astype(np.int16)
    g = img[:, :, 1].astype(np.int16)
    b = img[:, :, 2].astype(np.int16)
    return int(((r > 110) & (r - g > 45) & (r - b > 45)).sum())


class VideoProbe:
    """按 episode 取首/末帧。同一视频文件复用解码器，避免反复 seek 拖慢。"""

    def __init__(self, ds: Path, meta: pd.DataFrame):
        self.ds = ds
        self.meta = meta
        self._cur_path = None
        self._cur_cont = None

    def _open(self, path: Path):
        import av
        if self._cur_path != path:
            self.close()
            self._cur_cont = av.open(str(path))
            self._cur_path = path
        return self._cur_cont

    def close(self):
        if self._cur_cont is not None:
            try:
                self._cur_cont.close()
            except Exception:  # noqa: BLE001
                pass
        self._cur_cont = None
        self._cur_path = None

    def frame_at(self, ep: int, t: float) -> np.ndarray:
        r = self.meta[self.meta.episode_index == ep].iloc[0]
        ci = int(r[f"videos/{CAM}/chunk_index"])
        fi = int(r[f"videos/{CAM}/file_index"])
        path = self.ds / "videos" / CAM / f"chunk-{ci:03d}" / f"file-{fi:03d}.mp4"
        cont = self._open(path)
        s = cont.streams.video[0]
        fps = float(s.average_rate)
        cont.seek(int(t * fps), stream=s)
        best = None
        for f in cont.decode(s):
            ts = float(f.pts * s.time_base) if f.pts is not None else 0.0
            best = f
            if ts >= t:
                break
        return best.to_ndarray(format="rgb24")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-id", default="seeedstudio123/m1_pick_cube")
    ap.add_argument("--no-video", action="store_true", help="跳过视频分析")
    ap.add_argument("--montage", action="store_true", help="导出失败条目的首/末帧拼图")
    args = ap.parse_args()

    ds = HF / args.repo_id
    info_p = ds / "meta" / "info.json"
    if not info_p.exists():
        print(f"[XX] 找不到数据集: {ds}")
        return 1
    info = json.loads(info_p.read_text("utf-8"))
    fps = info.get("fps", 30)

    print("=" * 100)
    print(f"  数据集体检：{args.repo_id}")
    print("=" * 100)
    print(f"  episodes {info.get('total_episodes')}   frames {info.get('total_frames')}   fps {fps}"
          f"   总时长 {info.get('total_frames', 0) / fps / 60:.1f} 分钟")

    vids = sorted((ds / "videos").rglob("*.mp4")) if (ds / "videos").exists() else []
    print(f"  视频 {len(vids)} 个，{sum(v.stat().st_size for v in vids) / 1024**2:.0f} MB")

    df = pd.concat([pd.read_parquet(p) for p in sorted((ds / "data").rglob("*.parquet"))],
                   ignore_index=True)
    meta = pd.concat([pd.read_parquet(p) for p in sorted((ds / "meta" / "episodes").rglob("*.parquet"))],
                     ignore_index=True)

    rows = []
    for ep, g in df.groupby("episode_index"):
        st = np.stack(g["observation.state"].apply(lambda v: np.asarray(v, float)).values)
        ac = np.stack(g["action"].apply(lambda v: np.asarray(v, float)).values)
        n = len(st)
        d = np.linalg.norm(np.diff(st, axis=0), axis=1) if n > 1 else np.array([0.0])
        rows.append({
            "ep": int(ep), "frames": n, "sec": n / fps,
            "still": float((d < 0.5).mean() * 100),
            "grip": float(st[:, 5].max() - st[:, 5].min()),
            "track": float(np.abs(ac - st).mean()),
            "red0": -1, "red1": -1,
        })
    r = pd.DataFrame(rows).sort_values("ep").reset_index(drop=True)

    probe = None
    if not args.no_video:
        print("\n  正在从视频里抽首/末帧判断抓取成败 ...")
        probe = VideoProbe(ds, meta)
        for i, row in r.iterrows():
            ep = int(row.ep)
            m = meta[meta.episode_index == ep].iloc[0]
            t0 = float(m[f"videos/{CAM}/from_timestamp"]) + 0.15
            t1 = float(m[f"videos/{CAM}/to_timestamp"]) - 0.25
            try:
                r.at[i, "red0"] = red_area(probe.frame_at(ep, t0))
                r.at[i, "red1"] = red_area(probe.frame_at(ep, t1))
            except Exception as exc:  # noqa: BLE001
                print(f"    [!!] ep{ep} 取帧失败: {exc}")
            if (i + 1) % 20 == 0:
                print(f"    ... {i + 1}/{len(r)}")
        probe.close()

    print()
    print(f"  {'指标':<18} | {'最小':>9} | {'中位':>9} | {'最大':>9}")
    print("  " + "-" * 54)
    cols = [("sec", "时长(s)"), ("still", "静止帧占比%"), ("grip", "夹爪开合"),
            ("track", "跟随误差")]
    if not args.no_video:
        cols += [("red0", "首帧红色px"), ("red1", "末帧红色px")]
    for col, name in cols:
        if col in r and (r[col] >= 0).any():
            print(f"  {name:<18} | {r[col].min():>9.1f} | {r[col].median():>9.1f} | {r[col].max():>9.1f}")

    def issues(row) -> list[str]:
        out = []
        if row.sec < MIN_SECONDS:
            out.append(f"太短{row.sec:.1f}s")
        if row.still > MAX_STILL_PCT:
            out.append(f"静止{row.still:.0f}%")
        if row.track > MAX_TRACK_ERR:
            out.append(f"跟随差{row.track:.0f}")
        if row.red1 > RED_LEFT:
            out.append(f"★抓取失败(末帧红{int(row.red1)})")
        if 0 <= row.red0 < RED_PRESENT:
            out.append(f"开头遮挡(红{int(row.red0)})")
        return out

    r["issues"] = r.apply(issues, axis=1)
    bad = r[r["issues"].apply(len) > 0].sort_values("ep")
    failed = r[r["red1"] > RED_LEFT] if not args.no_video else r.iloc[0:0]

    print()
    print("=" * 100)
    print(f"  结果：{len(r) - len(bad)}/{len(r)} 条合格"
          + ("" if not args.no_video else "（未做视频分析）")
          + (f"，抓取失败 {len(failed)} 条" if not args.no_video else ""))
    print("=" * 100)

    if not bad.empty:
        print(f"  {'ep':>4} | {'时长':>6} | {'静止%':>6} | {'夹爪':>5} | {'跟随':>5} | {'首红':>6} | {'末红':>6} | 问题")
        print("  " + "-" * 88)
        for _, row in bad.iterrows():
            print(f"  {row.ep:>4} | {row.sec:>6.1f} | {row.still:>6.1f} | {row.grip:>5.1f} | "
                  f"{row.track:>5.1f} | {int(row.red0):>6} | {int(row.red1):>6} | {'；'.join(row.issues)}")
        ids = ",".join(str(int(x)) for x in bad["ep"].tolist())
        print()
        print("  剔除这些条目（另存新数据集，原数据集不动）：")
        print(f'    powershell -ExecutionPolicy Bypass -File scripts\\11-edit-dataset.ps1 '
              f'-Action delete-episodes -Episodes "{ids}" -NewRepoId {args.repo_id}_clean')

    if args.montage and not failed.empty:
        from PIL import Image, ImageDraw
        probe = VideoProbe(ds, meta)
        tiles = []
        for ep in failed["ep"].tolist()[:6]:
            m = meta[meta.episode_index == ep].iloc[0]
            for tag, t in (("首", float(m[f"videos/{CAM}/from_timestamp"]) + 0.15),
                           ("末", float(m[f"videos/{CAM}/to_timestamp"]) - 0.25)):
                im = Image.fromarray(probe.frame_at(int(ep), t)).resize((320, 240))
                ImageDraw.Draw(im).text((4, 3), f"ep{ep} {tag}", fill=(255, 255, 0))
                tiles.append(im)
        probe.close()
        W, H = 320, 240
        n = max(1, len(tiles) // 2)
        sheet = Image.new("RGB", (W * 2, H * n), (20, 20, 20))
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % 2) * W, (i // 2) * H))
        out = ds / ".." / f"{ds.name}_failed_montage.png"
        sheet.save(out)
        print(f"\n  失败条目拼图 -> {out.resolve()}")

    # 每 20 条一组的趋势
    if len(r) >= 20:
        print()
        print("  每 20 条一组（看录制过程中是否越录越松）：")
        r2 = r.copy()
        r2["grp"] = r2["ep"] // 20
        for gid, gg in r2.groupby("grp"):
            extra = "" if args.no_video else f"  抓失败 {int((gg.red1 > RED_LEFT).sum())} 条"
            print(f"    第 {gid + 1} 组（ep {gg.ep.min()}~{gg.ep.max()}）: "
                  f"时长中位 {gg.sec.median():.1f}s  静止中位 {gg.still.median():.1f}%{extra}")

    print("=" * 100)
    return 0 if failed.empty and bad.empty else 2


if __name__ == "__main__":
    sys.exit(main())
