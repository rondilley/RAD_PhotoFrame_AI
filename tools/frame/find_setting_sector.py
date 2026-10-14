"""Find the eMMC sector that holds persist.sys.usb.config in /system/build.prop (S1.2 prep).

Reads only the verified backup image. It does not touch the frame.
Run in the RAD_PhotoFrame_Build WSL distribution (needs debugfs and e2fsck):

    python3 -I /mnt/g/git/RAD_PhotoFrame_AI/tools/frame/find_setting_sector.py pf1007l-01

Steps:
    1. Parse the MBR and the EBR chain of the image; list the partitions.
    2. Find the ext4 partition with the volume name "system".
    3. Copy it to ~/rad/<unit>-system.img and check it with e2fsck -n (read-only).
    4. With debugfs -c (read-only), find /build.prop, its block map, and the byte
       offset of the property line.
    5. Compute the eMMC sector, read it from the image, and compare its SHA-256
       with the stock sector of the upstream reports.

Writes frames/<unit>/setting_sector.json.
"""

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
SECTOR = 512
LINE = b"persist.sys.usb.config=mass_storage\n"
UPSTREAM = {
    "sector": 399221,
    "stock_sha256": "f78d2d4e3924d752a5fdcca7722a4fa76aeff700ce09fd6076d5dea064e2a9c4",
    "source": "pf1007l-windows-20260113-usb-adb-report.md, pf1007l-sector-edit-sdcard.md",
}


def run(*cmd: str) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"STOP: {' '.join(cmd)} failed ({r.returncode}): {r.stderr.strip()}")
    return r.stdout


def entries(sector: bytes):
    if sector[510:512] != b"\x55\xaa":
        sys.exit("STOP: no 55aa signature")
    for i in range(4):
        e = sector[446 + 16 * i: 446 + 16 * (i + 1)]
        ptype = e[4]
        start, count = struct.unpack_from("<II", e, 8)
        if ptype:
            yield ptype, start, count


def partitions(img):
    img.seek(0)
    out = []
    ext_base = None
    for ptype, start, count in entries(img.read(SECTOR)):
        if ptype in (0x05, 0x0F):
            ext_base = start
        else:
            out.append({"type": f"0x{ptype:02x}", "start": start, "sectors": count})
    ebr = ext_base
    seen = set()
    while ebr is not None and ebr not in seen:
        seen.add(ebr)
        img.seek(ebr * SECTOR)
        nxt = None
        for ptype, start, count in entries(img.read(SECTOR)):
            if ptype in (0x05, 0x0F):
                nxt = ext_base + start
            else:
                out.append({"type": f"0x{ptype:02x}", "start": ebr + start, "sectors": count})
        ebr = nxt
    return sorted(out, key=lambda p: p["start"])


def volume_name(img, start: int) -> str:
    img.seek(start * SECTOR + 1024)
    sb = img.read(1024)
    if struct.unpack_from("<H", sb, 0x38)[0] != 0xEF53:
        return ""
    return sb[0x78:0x88].split(b"\0")[0].decode("ascii", "replace")


def main(unit: str) -> int:
    image = PROJ / "backups" / unit / "emmc-full.img"
    work = Path.home() / "rad"
    work.mkdir(exist_ok=True)
    with image.open("rb") as img:
        parts = partitions(img)
        for p in parts:
            p["ext4_name"] = volume_name(img, p["start"])
            print(f"  {p['type']} start {p['start']:>9} sectors {p['sectors']:>9} {p['ext4_name']}")
        system = [p for p in parts if p["ext4_name"] == "system"]
        if len(system) != 1:
            sys.exit(f"STOP: expected one ext4 'system' partition, found {len(system)}")
        sysp = system[0]

        copy = work / f"{unit}-system.img"
        img.seek(sysp["start"] * SECTOR)
        left = sysp["sectors"] * SECTOR
        with copy.open("wb") as f:
            while left:
                block = img.read(min(left, 4 << 20))
                if not block:
                    sys.exit("STOP: image ends inside the system partition")
                f.write(block)
                left -= len(block)

    fsck = subprocess.run(["e2fsck", "-n", "-f", str(copy)], capture_output=True, text=True)
    print("  e2fsck -n:", fsck.stdout.strip().splitlines()[-1] if fsck.stdout.strip() else fsck.stderr.strip())
    stats = run("dumpe2fs", "-h", str(copy))
    bsize = int(next(l.split(":")[1] for l in stats.splitlines() if l.startswith("Block size:")))
    features = next(l.split(":", 1)[1].strip() for l in stats.splitlines() if l.startswith("Filesystem features:"))
    state = next(l.split(":", 1)[1].strip() for l in stats.splitlines() if l.startswith("Filesystem state:"))

    dumped = work / f"{unit}-build.prop"
    run("debugfs", "-c", "-R", f"dump /build.prop {dumped}", str(copy))
    data = dumped.read_bytes()
    if data.count(LINE) != 1:
        sys.exit(f"STOP: the line {LINE!r} occurs {data.count(LINE)} times in build.prop")
    offset = data.index(LINE)
    inode = run("debugfs", "-c", "-R", "stat /build.prop", str(copy))
    lblock = offset // bsize
    pblock = int(run("debugfs", "-c", "-R", f"bmap /build.prop {lblock}", str(copy)).strip().splitlines()[-1])
    per = bsize // SECTOR
    sector = sysp["start"] + pblock * per + (offset % bsize) // SECTOR
    in_sector = offset % SECTOR
    if in_sector + len(LINE) > SECTOR:
        sys.exit("STOP: the line crosses a sector boundary; a one-sector edit does not fit")

    with image.open("rb") as img:
        img.seek(sector * SECTOR)
        raw = img.read(SECTOR)
    if raw[in_sector:in_sector + len(LINE)] != LINE:
        sys.exit("STOP: the computed sector does not hold the line")
    sha = hashlib.sha256(raw).hexdigest()

    record = {
        "unit": unit,
        "image": str(image.relative_to(PROJ)),
        "partitions": parts,
        "system": {"start": sysp["start"], "sectors": sysp["sectors"], "block_size": bsize,
                   "features": features, "state": state, "e2fsck_n_exit": fsck.returncode},
        "build_prop": {"bytes": len(data), "line_offset": offset, "logical_block": lblock,
                       "physical_block": pblock,
                       "stat": [l.strip() for l in inode.splitlines() if l.strip().startswith(("Inode:", "Size:", "EXTENTS", "("))]},
        "setting_sector": sector,
        "line_offset_in_sector": in_sector,
        "sector_sha256": sha,
        "upstream": UPSTREAM,
        "matches_upstream_sector": sector == UPSTREAM["sector"],
        "matches_upstream_hash": sha == UPSTREAM["stock_sha256"],
    }
    out = PROJ / "frames" / unit / "setting_sector.json"
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(f"  system: start {sysp['start']}, block size {bsize}, state {state}")
    print(f"  build.prop: {len(data)} bytes, line at byte {offset}, logical block {lblock}, physical block {pblock}")
    print(f"  setting sector {sector}, line at byte {in_sector} of the sector, SHA-256 {sha}")
    print(f"  upstream sector {UPSTREAM['sector']}: same sector {record['matches_upstream_sector']}, same hash {record['matches_upstream_hash']}")
    print(f"recorded in {out.relative_to(PROJ)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: find_setting_sector.py <unit>")
    sys.exit(main(sys.argv[1]))
