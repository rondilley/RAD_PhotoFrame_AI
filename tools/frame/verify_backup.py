"""Check a saved eMMC backup and record the result (ARCHITECTURE 14.2, FR-02, TC-04).

Reads only the saved files. It does not touch the frame.

    python -I tools/frame/verify_backup.py pf1007l-01

Inputs, from tools/frame/emmc_backup.ps1:
    backups/<unit>/emmc-full.img, emmc-full.img.gz, emmc-full.sha256,
    emmc-resume.done.json (per-segment SHA-256 of the two disk reads)
and the eMMC size from frames/<unit>/identity.json.

Checks:
    1. The image byte count equals the eMMC size from the device.
    2. Two full disk reads agreed: emmc_backup.ps1 compared both reads of each
       1 GiB segment and saved the hash. This tool hashes each image segment again
       and requires the saved hash, and requires the whole-image hash in
       emmc-full.sha256.
    3. The gzip readback gives the same SHA-256.
    4. No aligned 1 MiB area of the image is only 0xCC filler.

Writes frames/<unit>/backups.json. Exit code 0 only when all checks pass.
"""

import datetime
import gzip
import hashlib
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
SEGMENT = 1 << 30
MIB = 1 << 20
FILLER = b"\xcc" * MIB


def main(unit: str) -> int:
    bdir = PROJ / "backups" / unit
    fdir = PROJ / "frames" / unit
    image = bdir / "emmc-full.img"
    gz = bdir / "emmc-full.img.gz"
    sha_file = bdir / "emmc-full.sha256"
    state_file = bdir / "emmc-resume.done.json"

    identity = json.loads((fdir / "identity.json").read_text())
    device_bytes = int(identity["emmc_bytes"])
    state = json.loads(state_file.read_text())
    saved_whole = sha_file.read_text().split()[0]

    checks = {}
    size = image.stat().st_size
    checks["1_size"] = {
        "pass": size == device_bytes and int(state["size"]) == device_bytes,
        "image_bytes": size,
        "device_bytes": device_bytes,
    }

    whole = hashlib.sha256()
    seg_bad = []
    filler_mib = []
    with image.open("rb") as f:
        index = 0
        while True:
            seg = hashlib.sha256()
            got = 0
            while got < SEGMENT:
                block = f.read(MIB)
                if not block:
                    break
                if block == FILLER:
                    filler_mib.append((index * SEGMENT + got) // MIB)
                seg.update(block)
                whole.update(block)
                got += len(block)
            if not got:
                break
            if state["done"].get(str(index)) != seg.hexdigest():
                seg_bad.append(index)
            index += 1
            print(f"\r  image segment {index}", end="", flush=True)
    print()
    whole_hex = whole.hexdigest()
    checks["2_two_reads"] = {
        "pass": not seg_bad and len(state["done"]) == index and whole_hex == saved_whole,
        "segments": index,
        "segments_not_matching_saved_hash": seg_bad,
        "image_sha256": whole_hex,
        "saved_sha256": saved_whole,
    }

    gz_hash = hashlib.sha256()
    with gzip.open(gz, "rb") as f:
        while block := f.read(4 * MIB):
            gz_hash.update(block)
    checks["3_gzip_readback"] = {
        "pass": gz_hash.hexdigest() == whole_hex,
        "gzip_bytes": gz.stat().st_size,
        "readback_sha256": gz_hash.hexdigest(),
    }

    checks["4_no_cc_filler"] = {"pass": not filler_mib, "filler_mib_offsets": filler_mib[:20]}

    ok = all(c["pass"] for c in checks.values())
    record = {
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "unit": unit,
        "image": str(image.relative_to(PROJ)),
        "sha256": whole_hex,
        "result": "pass" if ok else "fail",
        "checks": checks,
    }
    out = fdir / "backups.json"
    history = json.loads(out.read_text()) if out.exists() else []
    history.append(record)
    out.write_text(json.dumps(history, indent=2) + "\n")

    for name, c in checks.items():
        print(f"  {name}: {'pass' if c['pass'] else 'FAIL'}")
    print(f"{'PASS' if ok else 'FAIL'}: {image.name} sha256 {whole_hex}; recorded in {out.relative_to(PROJ)}")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: verify_backup.py <unit>")
    sys.exit(main(sys.argv[1]))
