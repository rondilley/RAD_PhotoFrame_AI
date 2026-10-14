"""Restore the gzip backup into a disk image file on the host and hash it (BC-02).

Reads only the saved files. It does not touch the frame.

    python -I tools/frame/restore_check.py pf1007l-01

Writes backups/<unit>/restore-check.img, compares its SHA-256 with
emmc-full.sha256, then deletes the restored file (use --keep to keep it).
Appends the result to frames/<unit>/backups.json.
"""

import datetime
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
MIB = 1 << 20


def main(unit: str, keep: bool) -> int:
    bdir = PROJ / "backups" / unit
    gz = bdir / "emmc-full.img.gz"
    saved = (bdir / "emmc-full.sha256").read_text().split()[0]
    target = bdir / "restore-check.img"
    if target.exists():
        sys.exit(f"STOP: {target} exists; remove it first")

    with gzip.open(gz, "rb") as src, target.open("wb") as dst:
        while block := src.read(4 * MIB):
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())

    # hash the file as written on disk, not the stream
    h = hashlib.sha256()
    with target.open("rb") as f:
        while block := f.read(4 * MIB):
            h.update(block)
    size = target.stat().st_size
    ok = h.hexdigest() == saved
    if not keep:
        target.unlink()

    record = {
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "unit": unit,
        "check": "BC-02 restore into a disk image file",
        "source": str(gz.relative_to(PROJ)),
        "restored_bytes": size,
        "restored_sha256": h.hexdigest(),
        "saved_sha256": saved,
        "kept": keep,
        "result": "pass" if ok else "fail",
    }
    out = PROJ / "frames" / unit / "backups.json"
    history = json.loads(out.read_text()) if out.exists() else []
    history.append(record)
    out.write_text(json.dumps(history, indent=2) + "\n")
    print(f"{'PASS' if ok else 'FAIL'}: restored {size} bytes, sha256 {h.hexdigest()}; recorded in {out.relative_to(PROJ)}")
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--keep"]
    if len(args) != 1:
        sys.exit("usage: restore_check.py <unit> [--keep]")
    sys.exit(main(args[0], "--keep" in sys.argv[1:]))
