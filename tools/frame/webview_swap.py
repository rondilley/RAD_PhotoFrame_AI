"""Swap the stock WebView 44 for WebView 106 in /system (S1.3, FR-08, TC-06).

    python -I tools/frame/webview_swap.py check   <unit>
    python -I tools/frame/webview_swap.py apply   <unit> --approve-write
    python -I tools/frame/webview_swap.py restore <unit> --approve-write

check    read only. Reports STOCK, SWAPPED or OTHER, the package version, and the
         free space in /system.
apply    only from STOCK. Follows upstream docs/allwinner-a33-pf1007l.md section 6:
         stage the APK and all three native libraries in /data/local/tmp, copy them
         to /system/rad-new-webview, check each file on the frame by SHA-256, then
         move the stock tree to /system/rad-stock-webview and the new tree to
         /system/app/webview. Then /system goes back to read-only, the frame
         restarts, and the tool checks the package version and the log for
         library errors.
restore  only from SWAPPED. Moves the stock tree back to /system/app/webview,
         checks it against the backup hashes, removes the new tree, restarts the
         frame and checks for version 44.

--approve-write is Ron's approval for one apply or restore run.
The stock file hashes come from the verified backup image (system partition).
"""

import sys
import time
import tomllib
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frame_adb import PROJ, Frame  # noqa: E402

LIVE = "/system/app/webview"
NEW = "/system/rad-new-webview"
SAVED = "/system/rad-stock-webview"
OLDNEW = "/system/rad-removed-webview"
STAGE = "/data/local/tmp/rad-webview"
BB = "/sbin/busybox"
MIN_FREE_KIB = 300000

# From backups/pf1007l-01/emmc-full.img, system partition, debugfs dump (2026-10-14).
STOCK = {
    "webview.apk": ("e8334af7dbff490dc016167f6182829fded15c7f5592afe170a140e4516c3cc3", 38439481),
    "oat/arm/webview.odex": ("7825e578c0db34c34295c96d20b2bffe77604980b7426035bc8e19218b208f9c", 2920940),
}
STOCK_VERSION = "44.0.2403.119"


def new_files() -> dict:
    """Relative path -> (sha256, host path) for the WebView 106 tree, from bom.toml."""
    pin = tomllib.loads((PROJ / "tools" / "frame" / "bom.toml").read_text())["frame"]["webview"]
    files = {"webview.apk": (pin["sha256"], PROJ / pin["file"])}
    libdir = (PROJ / pin["file"]).parent / "lib" / "arm"
    for entry in pin["libs"]:
        name, digest = entry.split()
        files[f"lib/arm/{name}"] = (digest, libdir / name)
    return files


def host_check(files: dict) -> None:
    for rel, (digest, path) in files.items():
        if not path.exists():
            sys.exit(f"STOP: {path} not found")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            sys.exit(f"STOP: {path} does not agree with bom.toml")
        print(f"  ok  host {rel} {digest[:16]}")


def tree_hashes(fr: Frame, root: str) -> dict:
    """Relative path -> sha256 for each file under root on the frame; {} if root is absent."""
    rc, out = fr.sh(f"[ -d {root} ] && cd {root} && {BB} find . -type f -exec {BB} sha256sum {{}} \\;")
    if rc != 0:
        return {}
    result = {}
    for line in out.splitlines():
        digest, _, path = line.partition("  ")
        if path:
            result[path[2:] if path.startswith("./") else path] = digest
    return result


def modes(fr: Frame, root: str) -> list[str]:
    out = fr.must(f"cd {root} && {BB} find . -exec stat -c '%a %u %g %n' {{}} \\;")
    return [l for l in out.splitlines() if l]


def state(fr: Frame, files: dict) -> str:
    live = tree_hashes(fr, LIVE)
    stock = {k: v[0] for k, v in STOCK.items()}
    new = {k: v[0] for k, v in files.items()}
    if live == stock and not fr.sh(f"[ -e {SAVED} ]")[0] == 0:
        return "STOCK"
    if live == new and tree_hashes(fr, SAVED) == stock:
        return "SWAPPED"
    return "OTHER"


def version(fr: Frame) -> str:
    out = fr.must("dumpsys package com.android.webview")
    for line in out.splitlines():
        if "versionName=" in line:
            return line.split("versionName=")[1].strip()
    return "none"


def free_kib(fr: Frame) -> int:
    out = fr.must("toybox df -k /system").splitlines()[-1].split()
    return int(out[3])


def system_mode(fr: Frame) -> str:
    for line in fr.must("cat /proc/mounts").splitlines():
        f = line.split()
        if len(f) > 3 and f[1] == "/system":
            return f[3].split(",")[0]
    return "none"


def remount(fr: Frame, mode: str) -> None:
    fr.must(f"mount -o remount,{mode} /system")
    if system_mode(fr) != mode:
        raise RuntimeError(f"/system is not {mode} after remount")


def report(fr: Frame, files: dict) -> str:
    st = state(fr, files)
    print(f"  state {st}; package version {version(fr)}; /system {system_mode(fr)}, {free_kib(fr)} KiB free")
    for p in (NEW, SAVED, OLDNEW, STAGE):
        if fr.sh(f"[ -e {p} ]")[0] == 0:
            print(f"  present: {p}")
    return st


def reboot_and_wait(fr: Frame) -> None:
    fr.adb("reboot")
    time.sleep(10)
    fr.adb("wait-for-device", timeout=300)
    for _ in range(90):
        if fr.prop("sys.boot_completed") == "1":
            time.sleep(15)  # let the package scan and dexopt finish
            return
        time.sleep(2)
    raise RuntimeError("Android did not complete the boot in 180 s")


def lib_errors(fr: Frame) -> list[str]:
    out = fr.adb("logcat", "-d")
    keys = ("dlopen failed", "Failed to load library", "UnsatisfiedLinkError", "MissingWebViewPackage")
    stock_noise = ("libemoji.so",)  # stock firmware, each boot, with WebView 44 too
    return [l for l in out.splitlines() if any(k in l for k in keys) and not any(n in l for n in stock_noise)]


def apply(fr: Frame, files: dict) -> int:
    if report(fr, files) != "STOCK":
        sys.exit("STOP: apply needs state STOCK")
    for p in (NEW, SAVED, OLDNEW):
        if fr.sh(f"[ -e {p} ]")[0] == 0:
            sys.exit(f"STOP: {p} exists")
    if free_kib(fr) < MIN_FREE_KIB:
        sys.exit(f"STOP: /system has less than {MIN_FREE_KIB} KiB free")
    if system_mode(fr) != "ro":
        sys.exit("STOP: /system is not read-only at the start")

    # Stage in /data and check on the frame
    fr.must(f"rm -rf {STAGE} && mkdir -p {STAGE}/lib/arm")
    for rel, (_, path) in files.items():
        fr.adb("push", str(path), f"{STAGE}/{rel}")
    if tree_hashes(fr, STAGE) != {k: v[0] for k, v in files.items()}:
        sys.exit("STOP: the staged files in /data do not agree with the host files")
    print("  ok  staged in /data and checked on the frame")

    fr.log({"step": "S1.3", "class": "write-start", "action": f"webview_swap.py apply: {LIVE} 44 -> 106, stock tree to {SAVED}, approved by Ron (--approve-write)",
            "undo": "webview_swap.py restore <unit> --approve-write"})
    moved = False
    try:
        remount(fr, "rw")
        fr.must(f"mkdir -p {NEW}/lib/arm")
        for rel in files:
            fr.must(f"cp {STAGE}/{rel} {NEW}/{rel}")
        fr.must(f"chown -R 0:0 {NEW} && {BB} find {NEW} -type d -exec chmod 0755 {{}} \\; && {BB} find {NEW} -type f -exec chmod 0644 {{}} \\;")
        if tree_hashes(fr, NEW) != {k: v[0] for k, v in files.items()}:
            raise RuntimeError(f"{NEW} does not agree with the host files")
        print(f"  ok  {NEW} checked")
        fr.must(f"mv {LIVE} {SAVED}")
        moved = True
        fr.must(f"mv {NEW} {LIVE}")
        moved = False
        if tree_hashes(fr, LIVE) != {k: v[0] for k, v in files.items()}:
            raise RuntimeError(f"{LIVE} does not agree with the host files after the move")
        if tree_hashes(fr, SAVED) != {k: v[0] for k, v in STOCK.items()}:
            raise RuntimeError(f"{SAVED} does not agree with the stock hashes")
        bad = [m for m in modes(fr, LIVE) if not (m.startswith("755 0 0 ") or m.startswith("644 0 0 "))]
        if bad:
            raise RuntimeError(f"unexpected owner or mode: {bad}")
        fr.must("sync")
        remount(fr, "ro")
    except Exception as e:
        if moved:
            fr.sh(f"mv {SAVED} {LIVE}")
        fr.sh("sync; mount -o remount,ro /system")
        fr.log({"step": "S1.3", "class": "result", "action": "webview_swap.py apply", "result": f"FAILED before restart: {e}; /system {system_mode(fr)}; run check"})
        print(f"FAIL: {e}")
        report(fr, files)
        return 1
    fr.must(f"rm -rf {STAGE}")
    print("  ok  live tree is WebView 106, stock tree saved, /system read-only; restarting")
    return after_reboot(fr, files, "apply", "SWAPPED", "106.0.5249.126")


def restore(fr: Frame, files: dict) -> int:
    if report(fr, files) != "SWAPPED":
        sys.exit("STOP: restore needs state SWAPPED")
    if fr.sh(f"[ -e {OLDNEW} ]")[0] == 0:
        sys.exit(f"STOP: {OLDNEW} exists")
    fr.log({"step": "S1.3", "class": "write-start", "action": f"webview_swap.py restore: {SAVED} back to {LIVE}, approved by Ron (--approve-write)",
            "undo": "webview_swap.py apply <unit> --approve-write"})
    try:
        remount(fr, "rw")
        fr.must(f"mv {LIVE} {OLDNEW} && mv {SAVED} {LIVE}")
        if tree_hashes(fr, LIVE) != {k: v[0] for k, v in STOCK.items()}:
            raise RuntimeError(f"{LIVE} does not agree with the stock hashes")
        fr.must(f"rm -rf {OLDNEW} && sync")
        remount(fr, "ro")
    except Exception as e:
        fr.sh("sync; mount -o remount,ro /system")
        fr.log({"step": "S1.3", "class": "result", "action": "webview_swap.py restore", "result": f"FAILED before restart: {e}; run check"})
        print(f"FAIL: {e}")
        report(fr, files)
        return 1
    print("  ok  stock tree is live again, /system read-only; restarting")
    return after_reboot(fr, files, "restore", "STOCK", STOCK_VERSION)


def after_reboot(fr: Frame, files: dict, mode: str, want_state: str, want_version: str) -> int:
    fr.adb("logcat", "-c")
    reboot_and_wait(fr)
    fr.check_identity()
    st = report(fr, files)
    ver = version(fr)
    errors = lib_errors(fr)
    for e in errors[:10]:
        print(f"  log: {e}")
    ok = st == want_state and ver == want_version and system_mode(fr) == "ro" and not errors
    fr.log({"step": "S1.3", "class": "write", "action": f"webview_swap.py {mode}",
            "result": f"{'OK' if ok else 'FAIL'}: state {st}, versionName {ver}, /system {system_mode(fr)}, library errors in log {len(errors)}"})
    print(f"{'PASS' if ok else 'FAIL'}: state {st}, versionName {ver}, library errors {len(errors)}")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("check", "apply", "restore"):
        sys.exit(__doc__)
    mode, unit = argv[0], argv[1]
    if mode != "check" and argv[2:] != ["--approve-write"]:
        sys.exit(f"STOP: {mode} writes to /system; it needs --approve-write (Ron's approval for this run)")
    fr = Frame(unit)
    fr.check_identity()
    files = new_files()
    host_check(files)
    if mode == "check":
        report(fr, files)
        errors = lib_errors(fr)
        print(f"  library errors in the current log: {len(errors)}")
        return 0
    return apply(fr, files) if mode == "apply" else restore(fr, files)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
