"""Make the FEL U-Boot scripts for the one-sector build.prop edit (S1.2).

Reads only the verified backup image and frames/<unit>/setting_sector.json.
It does not touch the frame.

    python -I tools/frame/make_sector_scripts.py prepare <unit>
        Save the stock sector and the edited sector to
        backups/<unit>/sector-<n>/ and write manifest.json.

    python -I tools/frame/make_sector_scripts.py script <unit> <check|apply|restore> [--test]
        Make one U-Boot script for one FEL run in diagnostics/sector-run/.
        Each script gets a new run marker. The script puts the result code and
        the marker in the USB serial number, then exposes only the eMMC as a
        read-only UMS disk. --test makes the same script for a sandbox U-Boot
        with a host disk image (tools/frame/test_sector_scripts.sh).

Modes:
    check    read the sector and report STOCK, EDITED or OTHER; no write
    apply    write the edited sector only if the sector is STOCK
    restore  write the stock sector only if the sector is EDITED
"""

import datetime
import hashlib
import json
import secrets
import struct
import sys
import tomllib
import zlib
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
SECTOR = 512
OLD = b"persist.sys.usb.config=mass_storage\n"
NEW = b"persist.sys.usb.config=adb         \n"  # same length; the parser trims the spaces
UPSTREAM_EDITED_SHA = "3e0b232ceeb0600a5710bc5ac1c98d483bfa8ace66e189c5451a15c00179afe4"

# RAM buffers, as offsets from the device base. On the frame the base is 0x44000000
# (U-Boot runs from the top of DRAM; the FEL script is at 0x43100000).
ADDR = {"stock": 0x0000, "edited": 0x1000, "cur": 0x2000, "back": 0x3000, "mbr": 0x4000}

DEVICE = {
    # eMMC is mmc 1 in the pf1007l backup build (mmc 0 is the SD card).
    "frame": {"base": 0x44000000, "dev": "mmc dev 1", "rd": "mmc read", "wr": "mmc write", "ums": "ums 0 mmc 1"},
    "test": {"base": 0x01000000, "dev": "host dev 0", "rd": "read host 0:0", "wr": "write host 0:0", "ums": "echo ums skipped"},
}

MODES = {
    # mode: (serial prefix, from state, to state, payload to write, its sha key)
    "check": ("C", None, None, None, None),
    "apply": ("A", "STOCK", "EDITED", "edited", "edited_sha256"),
    "restore": ("R", "EDITED", "STOCK", "stock", "stock_sha256"),
}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sector_dir(unit: str, sector: int) -> Path:
    return PROJ / "backups" / unit / f"sector-{sector}"


def prepare(unit: str) -> int:
    info = json.loads((PROJ / "frames" / unit / "setting_sector.json").read_text())
    sector = info["setting_sector"]
    at = info["line_offset_in_sector"]
    image = PROJ / info["image"]
    with image.open("rb") as f:
        mbr = f.read(SECTOR)
        f.seek(sector * SECTOR)
        stock = f.read(SECTOR)
    if sha(stock) != info["sector_sha256"]:
        sys.exit("STOP: the image sector does not agree with setting_sector.json")
    if stock[at:at + len(OLD)] != OLD or stock.count(b"persist.sys.usb.config=") != 1:
        sys.exit("STOP: the stock sector does not hold the line at the recorded offset")
    edited = stock[:at] + NEW + stock[at + len(OLD):]
    assert len(edited) == SECTOR and len(NEW) == len(OLD)
    diff = [i for i in range(SECTOR) if stock[i] != edited[i]]

    out = sector_dir(unit, sector)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stock.bin").write_bytes(stock)
    (out / "edited.bin").write_bytes(edited)
    manifest = {
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "unit": unit,
        "sector": sector,
        "line_offset_in_sector": at,
        "image": info["image"],
        "image_sha256": (image.parent / "emmc-full.sha256").read_text().split()[0],
        "mbr_sha256": sha(mbr),
        "stock_sha256": sha(stock),
        "edited_sha256": sha(edited),
        "edited_matches_upstream": sha(edited) == UPSTREAM_EDITED_SHA,
        "changed_bytes": [diff[0], diff[-1], len(diff)],
        "old_line": OLD.decode(),
        "new_line": NEW.decode(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


def script_text(mode: str, man: dict, marker: str, device: dict) -> str:
    prefix, from_state, to_state, payload, to_key = MODES[mode]
    a = {k: f"0x{device['base'] + v:08x}" for k, v in ADDR.items()}
    lines = [
        f"# RAD_PhotoFrame_AI S1.2: {mode} of eMMC sector {man['sector']} (build.prop USB property).",
        f"# Unit {man['unit']}, run marker {marker}. Made by tools/frame/make_sector_scripts.py.",
        "# The result goes into the USB serial number as <mode>-<code>-<marker>.",
    ]
    if mode == "check":
        lines.append("# This script has no write command.")
    else:
        lines.append(f"# The only write is one sector, and only when the sector is {from_state}.")
    lines += [
        f"setenv sec 0x{man['sector']:x}",
        "setenv code NONE",
        "setenv state NONE",
        # clear the work buffers so old RAM data cannot give a false match
        f"mw.b {a['cur']} 0 0x200",
        f"mw.b {a['back']} 0 0x200",
        f"mw.b {a['mbr']} 0 0x200",
        f"if hash -v sha256 {a['stock']} 0x200 {man['stock_sha256']} && hash -v sha256 {a['edited']} 0x200 {man['edited_sha256']}; then",
        f"  if {device['dev']}; then",
        f"    if {device['rd']} {a['mbr']} 0 1 && hash -v sha256 {a['mbr']} 0x200 {man['mbr_sha256']}; then",
        f"      if {device['rd']} {a['cur']} ${{sec}} 1; then",
        f"        if cmp.b {a['cur']} {a['stock']} 0x200; then",
        "          setenv state STOCK",
        f"        elif cmp.b {a['cur']} {a['edited']} 0x200; then",
        "          setenv state EDITED",
        "        else",
        "          setenv state OTHER",
        "        fi",
    ]
    if mode == "check":
        lines.append("        setenv code ${state}")
    else:
        src = a[payload]
        lines += [
            f'        if test "${{state}}" = "{to_state}"; then',
            "          setenv code ALREADY_NO_WRITE",
            f'        elif test "${{state}}" = "{from_state}"; then',
            f"          if {device['wr']} {src} ${{sec}} 1; then",
            f"            if {device['rd']} {a['back']} ${{sec}} 1 && cmp.b {a['back']} {src} 0x200 && hash -v sha256 {a['back']} 0x200 {man[to_key]}; then",
            "              setenv code WRITTEN_VERIFIED",
            "            else",
            "              setenv code FAIL_VERIFY",
            "            fi",
            "          else",
            "            setenv code FAIL_WRITE",
            "          fi",
            "        else",
            "          setenv code REFUSED_OTHER",
            "        fi",
        ]
    lines += [
        "      else",
        "        setenv code FAIL_READ",
        "      fi",
        "    else",
        "      setenv code REFUSED_DISK",
        "    fi",
        "  else",
        "    setenv code FAIL_DEV",
        "  fi",
        "else",
        "  setenv code REFUSED_PAYLOAD",
        "fi",
        f"setenv -f serial# {prefix}-${{code}}-{marker}",
        'echo "result: ${serial#}"',
        f"{device['ums']}",
        "",
    ]
    return "\n".join(lines)


def script_image(text: bytes, stamp: int) -> bytes:
    """Legacy U-Boot script image, the same bytes as mkimage -C none -A arm -T script."""
    data = struct.pack(">II", len(text), 0) + text
    def header(hcrc: int) -> bytes:
        return struct.pack(">IIIIIIIBBBB32s", 0x27051956, hcrc, stamp, len(data), 0, 0,
                           zlib.crc32(data), 5, 2, 6, 0, b"")
    return header(zlib.crc32(header(0))) + data


def make_script(unit: str, mode: str, test: bool) -> int:
    if mode not in MODES:
        sys.exit("STOP: mode must be check, apply or restore")
    sdir = next((PROJ / "backups" / unit).glob("sector-*"), None)
    if sdir is None:
        sys.exit("STOP: run 'prepare' first")
    man = json.loads((sdir / "manifest.json").read_text())
    for name, key in (("stock.bin", "stock_sha256"), ("edited.bin", "edited_sha256")):
        if sha((sdir / name).read_bytes()) != man[key]:
            sys.exit(f"STOP: {name} does not agree with manifest.json")

    marker = secrets.token_hex(4).upper()
    stamp = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    device = DEVICE["test" if test else "frame"]
    text = script_text(mode, man, marker, device)
    run = PROJ / "diagnostics" / "sector-run" / f"{'test-' if test else ''}{mode}-{marker}"
    run.mkdir(parents=True)
    (run / "sector.cmd").write_bytes(text.encode("ascii"))
    (run / "sector.scr").write_bytes(script_image(text.encode("ascii"), stamp))
    plan = {
        "unit": unit,
        "mode": mode,
        "marker": marker,
        "serial_prefix": MODES[mode][0],
        "sector": man["sector"],
        "test": test,
        "script": (run / "sector.scr").relative_to(PROJ).as_posix(),
        "script_sha256": sha((run / "sector.scr").read_bytes()),
        "cmd_sha256": sha(text.encode("ascii")),
        "payloads": {
            "stock": {"path": (sdir / "stock.bin").relative_to(PROJ).as_posix(), "addr": f"0x{device['base'] + ADDR['stock']:08x}", "sha256": man["stock_sha256"]},
            "edited": {"path": (sdir / "edited.bin").relative_to(PROJ).as_posix(), "addr": f"0x{device['base'] + ADDR['edited']:08x}", "sha256": man["edited_sha256"]},
        },
        "mbr_sha256": man["mbr_sha256"],
        "fel_script_addr": "0x43100000",
    }
    bom = tomllib.loads((PROJ / "tools" / "frame" / "bom.toml").read_text())["fel"]
    plan["tools"] = {k: {"file": bom[k]["file"], "sha256": bom[k]["sha256"]} for k in ("sunxi_fel_exe", "u_boot")}
    (run / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(run.relative_to(PROJ).as_posix())
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "prepare":
        sys.exit(prepare(a[1]))
    if len(a) in (3, 4) and a[0] == "script" and (len(a) == 3 or a[3] == "--test"):
        sys.exit(make_script(a[1], a[2], len(a) == 4))
    sys.exit(__doc__)
