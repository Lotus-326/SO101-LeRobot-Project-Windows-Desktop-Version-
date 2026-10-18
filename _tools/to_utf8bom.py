"""Convert text files to UTF-8 with BOM so Windows PowerShell 5.1 parses them correctly.

Windows PowerShell 5.1 reads .ps1 files as ANSI/GBK unless they carry a UTF-8 BOM.
Without the BOM, non-ASCII (Chinese) comments and strings become mojibake and can
even break parsing.

Usage:  python _tools/to_utf8bom.py <path> [<path> ...]
        (directories are walked recursively for *.ps1 / *.bat / *.cmd)
"""

import sys
from pathlib import Path

EXTS = {".ps1", ".psm1", ".bat", ".cmd"}
BOM = b"\xef\xbb\xbf"


def fix(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(BOM):
        return f"  ok   {path}"
    text = raw.decode("utf-8")  # fails loudly if the file is not valid UTF-8
    path.write_bytes(BOM + text.encode("utf-8"))
    return f"  BOM+ {path}"


def main(argv: list[str]) -> int:
    targets: list[Path] = []
    for a in argv:
        p = Path(a)
        if p.is_dir():
            targets.extend(sorted(q for q in p.rglob("*") if q.suffix.lower() in EXTS))
        elif p.is_file():
            targets.append(p)
        else:
            print(f"  skip (not found): {p}")
    for t in targets:
        print(fix(t))
    print(f"done: {len(targets)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
