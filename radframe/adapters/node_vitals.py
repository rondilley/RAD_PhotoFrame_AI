"""Inference node vitals over SSH (read only): CPU, GPU, VRAM, RAM, NPU.

One long SSH session per node runs a small shell loop that reads /proc and
sysfs and prints one line each 5 s. Nothing is installed or written on the
nodes. The GPU busy percent and the NPU power state are sampled each second
and averaged over the 5 s step, because one read of gpu_busy_percent is noisy.
The amdxdna NPU has no busy counter: "npu" is the part of the step that the
NPU was runtime-active (not suspended).
GPU processes: without root there is no busy time per process, so they are
ranked by VRAM. ROCm processes of all users come from /sys/class/kfd (world
readable); Vulkan processes of the SSH user come from DRM fdinfo.
If the host process stops, ssh cannot write its stdout and exits.
"""

import collections
import subprocess
import sys
import threading
import time

STEP_S = 5
HISTORY_S = 60 * 60
RETRY_S = 30
STALE_S = 3 * STEP_S

REMOTE = r"""
D=$(ls -d /sys/class/drm/card*/device 2>/dev/null | while read d; do [ -e $d/gpu_busy_percent ] && echo $d; done | head -1)
H=$(ls -d $D/hwmon/hwmon* 2>/dev/null | head -1)
N=$(ls -d /sys/class/accel/accel*/device/power 2>/dev/null | head -1)
while :; do
  g=0; a=0; k=0
  while [ $k -lt 5 ]; do
    g=$((g + $(cat $D/gpu_busy_percent 2>/dev/null || echo 0)))
    [ "$(cat $N/runtime_status 2>/dev/null)" = active ] && a=$((a + 1))
    k=$((k + 1)); sleep 1
  done
  for d in /sys/class/kfd/kfd/proc/*; do
    [ -d "$d" ] || continue; p=${d##*/}; v=0
    for f in $d/vram_*; do v=$((v + $(cat $f 2>/dev/null || echo 0))); done
    echo "P $p $(stat -c %U /proc/$p 2>/dev/null || echo -) $v $(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | cut -c1-200)"
  done
  for p in $(find /proc -maxdepth 1 -user $(id -u) -name '[0-9]*' -printf '%f\n' 2>/dev/null); do
    [ -d /sys/class/kfd/kfd/proc/$p ] && continue
    v=$(grep -h '^drm-total-vram' /proc/$p/fdinfo/* 2>/dev/null | awk '{s+=$2} END{printf "%d", s*1024}')
    [ "${v:-0}" -gt 0 ] && echo "P $p $(id -un) $v $(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | cut -c1-200)"
  done
  read -r _ u n s i w q sq st _ < /proc/stat
  m=$(awk '/^MemTotal:/{t=$2} /^MemAvailable:/{v=$2} END{print t "," v}' /proc/meminfo)
  echo "V cpu=$u,$n,$s,$i,$w,$q,$sq,$st mem=$m gpu=$((g / 5)) npu=$((a * 20)) vram=$(cat $D/mem_info_vram_used 2>/dev/null || echo 0),$(cat $D/mem_info_vram_total 2>/dev/null || echo 0) gtt=$(cat $D/mem_info_gtt_used 2>/dev/null || echo 0) temp=$(cat $H/temp1_input 2>/dev/null || echo 0) pw=$(cat $H/power1_average 2>/dev/null || echo 0)"
done
"""


INTERPRETERS = ("python", "node", "bun", "deno", "java", "uv", "ruby", "perl")


def proc_label(cmd: str) -> str:
    """A short name for a command line: the script for interpreters, the model alias for llama.cpp."""
    a = cmd.split()
    if not a:
        return "?"
    exe = a[0].rsplit("/", 1)[-1]
    if exe.startswith(INTERPRETERS):
        for i, x in enumerate(a[1:], 1):
            if x == "-m" and i + 1 < len(a):
                return a[i + 1]
            if not x.startswith("-"):
                return x.rsplit("/", 1)[-1]
        return exe
    for flag in ("--alias", "-a", "-m", "--model"):
        if flag in a[:-1]:
            m = a[a.index(flag) + 1].rsplit("/", 1)[-1].replace(".gguf", "")
            return f"{'llama' if exe.startswith('llama') else exe} {m}"
    return exe


class NodeVitals:
    def __init__(self, name: str, target: str):
        self.name, self.target = name, target
        n = HISTORY_S // STEP_S
        self.hist = {k: collections.deque(maxlen=n) for k in ("cpu", "gpu", "npu")}
        self.last: dict = {}
        self.prev_cpu: list[int] | None = None
        self.pending: list[dict] = []
        self.seen_at = 0.0
        self.error: str | None = None
        threading.Thread(target=self._run, name=f"vitals-{name}", daemon=True).start()

    def _run(self) -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        while True:
            self.prev_cpu = None
            try:
                p = subprocess.Popen(
                    ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                     "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2", self.target, "sh", "-s"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=flags)
                p.stdin.write(REMOTE.encode())  # bytes: text mode on Windows would send CRLF to sh
                p.stdin.close()
                for raw in p.stdout:
                    line = raw.decode(errors="replace")
                    if line.startswith("P "):
                        self._proc(line)
                    elif line.startswith("V "):
                        self._take(line)
                err = p.stderr.read().decode(errors="replace").strip().splitlines()
                p.wait()
                self.error = (err[-1] if err else f"ssh exit {p.returncode}")[:80]
            except Exception as e:
                self.error = type(e).__name__
            time.sleep(RETRY_S)

    def _proc(self, line: str) -> None:
        f = line.rstrip().split(" ", 4)
        if len(f) >= 4 and f[3].isdigit():
            self.pending.append({"pid": int(f[1]), "user": f[2], "vram": int(f[3]),
                                 "name": proc_label(f[4] if len(f) > 4 else "")})

    def _take(self, line: str) -> None:
        f = dict(kv.split("=", 1) for kv in line.split()[1:] if "=" in kv)
        cpu = [int(x) for x in f["cpu"].split(",")]
        busy_pct = None
        if self.prev_cpu:
            d = [a - b for a, b in zip(cpu, self.prev_cpu)]
            total = sum(d)
            idle = d[3] + d[4]
            busy_pct = 100.0 * (total - idle) / total if total > 0 else 0.0
        self.prev_cpu = cpu
        mt, ma = (int(x) for x in f["mem"].split(","))
        vu, vt = (int(x) for x in f["vram"].split(","))
        v = {
            "cpu": busy_pct, "gpu": int(f["gpu"]), "npu": int(f["npu"]),
            "ram": 100.0 * (mt - ma) / mt if mt else 0.0, "ram_used": (mt - ma) * 1024, "ram_total": mt * 1024,
            "vram": 100.0 * vu / vt if vt else 0.0, "vram_used": vu, "vram_total": vt, "gtt_used": int(f["gtt"]),
            "temp": int(f["temp"]) / 1000, "power_w": int(f["pw"]) / 1e6,
            "procs": sorted(self.pending, key=lambda x: -x["vram"]),
        }
        self.pending = []
        self.last, self.seen_at, self.error = v, time.time(), None
        if busy_pct is not None:
            self.hist["cpu"].append(busy_pct)
        self.hist["gpu"].append(v["gpu"])
        self.hist["npu"].append(v["npu"])

    def snapshot(self) -> dict | None:
        if not self.last or time.time() - self.seen_at > STALE_S:
            return {"ok": False, "error": self.error or "no data"}
        npu_min = list(self.hist["npu"])[-12:]
        return {
            "ok": True, **self.last,
            "cpu": self.last["cpu"] or 0.0,
            "npu_min": sum(npu_min) / len(npu_min) if npu_min else 0.0,
            "gpu_hist": list(self.hist["gpu"])[-120:], "cpu_hist": list(self.hist["cpu"])[-120:],
        }


class VitalsReader:
    def __init__(self, nodes: list[tuple[str, str]]):
        self.nodes = [NodeVitals(n, t) for n, t in nodes]

    def snapshot(self) -> dict:
        return {n.name: n.snapshot() for n in self.nodes}
