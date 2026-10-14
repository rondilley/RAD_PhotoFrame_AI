"""Shared USB ADB helpers for the frame tools (S1.3 and later).

    python -I tools/frame/frame_adb.py identity <unit>   compare the frame with identity.json
    python -I tools/frame/frame_adb.py record <unit>     add the Android identity to identity.json
                                                         (only when it has none)

The frame adbd is Android 6: `adb shell` does not return the exit code of the
command, so sh() adds an exit-code marker to each command.
"""

import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
PROPS = ("ro.product.model", "ro.build.fingerprint", "ro.build.display.id", "ro.product.cpu.abi", "ro.build.version.sdk")
MARK = "__RAD_RC="


class Frame:
    def __init__(self, unit: str):
        self.unit = unit
        self.dir = PROJ / "frames" / unit
        self.identity = json.loads((self.dir / "identity.json").read_text())
        self.serial = self.identity["usb"]["serial"].lower()
        self.adb_exe = shutil.which("adb")
        if not self.adb_exe:
            sys.exit("STOP: adb is not on the PATH")

    def adb(self, *args: str, timeout: int = 600) -> str:
        r = subprocess.run([self.adb_exe, "-s", self.serial, *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
        return r.stdout.replace("\r", "")

    def sh(self, cmd: str, timeout: int = 600) -> tuple[int, str]:
        out = self.adb("shell", f"{cmd}; echo {MARK}$?", timeout=timeout)
        body, _, rc = out.rpartition(MARK)
        return int(rc.strip() or 255), body.rstrip("\n")

    def must(self, cmd: str, timeout: int = 600) -> str:
        rc, out = self.sh(cmd, timeout)
        if rc != 0:
            raise RuntimeError(f"frame command failed ({rc}): {cmd}\n{out}")
        return out

    def prop(self, name: str) -> str:
        return self.adb("shell", f"getprop {name}").strip()

    def props(self) -> dict:
        return {p: self.prop(p) for p in PROPS}

    def check_identity(self) -> None:
        state = subprocess.run([self.adb_exe, "-s", self.serial, "get-state"], capture_output=True, text=True)
        if state.stdout.strip() != "device":
            sys.exit(f"STOP: frame {self.serial} is not an ADB device ({state.stderr.strip() or state.stdout.strip()})")
        want = self.identity.get("android")
        if not want:
            sys.exit(f"STOP: identity.json has no android section; run: frame_adb.py record {self.unit}")
        now = self.props()
        bad = [f"{k}: {now[k]!r} != {want[k]!r}" for k in PROPS if now[k] != want[k]]
        if bad:
            sys.exit("STOP: the frame identity changed:\n  " + "\n  ".join(bad))
        if self.prop("sys.boot_completed") != "1":
            sys.exit("STOP: Android has not completed the boot")
        if self.must("id -u").strip() != "0":
            sys.exit("STOP: adb shell is not root")

    def log(self, entry: dict) -> None:
        line = {"time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        line.update(entry)
        with (self.dir / "changes.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("identity", "record"):
        sys.exit(__doc__)
    fr = Frame(argv[1])
    if argv[0] == "record":
        if fr.identity.get("android"):
            sys.exit("STOP: identity.json already has an android section")
        android = fr.props()
        android["adb_serial"] = fr.serial
        android["recorded"] = datetime.date.today().isoformat()
        fr.identity["android"] = android
        (fr.dir / "identity.json").write_text(json.dumps(fr.identity, indent=2) + "\n")
        print(json.dumps(android, indent=2))
        return 0
    fr.check_identity()
    print(f"identity ok: {fr.serial}, {fr.prop('ro.build.fingerprint')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
