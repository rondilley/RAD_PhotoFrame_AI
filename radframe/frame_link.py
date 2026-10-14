"""Keeps the USB link to the frame: `adb reverse tcp:PORT tcp:PORT` (lost when the frame restarts)."""

import shutil
import subprocess
import threading
import time

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FrameLink:
    def __init__(self, serial: str | None, port: int, every_s: int = 20):
        self.serial, self.port, self.every_s = serial, port, every_s
        self.adb = shutil.which("adb")
        self.state = "no frame serial" if not serial else ("no adb" if not self.adb else "starting")
        self.last_ok = 0.0
        if serial and self.adb:
            threading.Thread(target=self._run, name="frame-link", daemon=True).start()

    def _adb(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.adb, "-s", self.serial, *args], capture_output=True, text=True,
                              timeout=20, creationflags=NO_WINDOW)

    def _run(self) -> None:
        want = f"tcp:{self.port} tcp:{self.port}"
        while True:
            try:
                if self._adb("get-state").stdout.strip() != "device":
                    self.state = "frame not on USB"
                elif want in self._adb("reverse", "--list").stdout:
                    self.state, self.last_ok = "ok", time.time()
                elif self._adb("reverse", f"tcp:{self.port}", f"tcp:{self.port}").returncode == 0:
                    self.state, self.last_ok = "ok (mapping made again)", time.time()
                else:
                    self.state = "adb reverse failed"
            except Exception as e:
                self.state = f"error {type(e).__name__}"
            time.sleep(self.every_s)
