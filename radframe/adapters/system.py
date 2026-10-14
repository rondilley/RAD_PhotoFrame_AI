"""Workstation vitals: CPU, memory, disks, GPU. A sampler thread keeps 30 minutes of history."""

import collections
import threading
import time

import psutil

try:
    import pynvml
except ImportError:  # no NVIDIA library
    pynvml = None

HISTORY_S = 30 * 60
STEP_S = 5


class SystemSampler:
    def __init__(self, disks: tuple[str, ...]):
        self.disks = disks
        self.lock = threading.Lock()
        n = HISTORY_S // STEP_S
        self.cpu = collections.deque(maxlen=n)
        self.gpu = collections.deque(maxlen=n)
        self.mem = collections.deque(maxlen=n)
        self.latest: dict = {}
        self.gpu_handle = None
        self.gpu_name = ""
        if pynvml is not None:
            try:
                pynvml.nvmlInit()
                self.gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                name = pynvml.nvmlDeviceGetName(self.gpu_handle)
                self.gpu_name = name.decode() if isinstance(name, bytes) else name
            except Exception:
                self.gpu_handle = None
        psutil.cpu_percent(None)
        threading.Thread(target=self._run, name="system-sampler", daemon=True).start()

    def _gpu(self) -> dict:
        if self.gpu_handle is None:
            return {}
        h = self.gpu_handle
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        return {
            "name": self.gpu_name.replace("NVIDIA GeForce ", ""),
            "util": util.gpu,
            "mem_used": mem.used,
            "mem_total": mem.total,
            "temp": pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU),
            "power_w": pynvml.nvmlDeviceGetPowerUsage(h) / 1000,
        }

    def _run(self) -> None:
        while True:
            try:
                cpu = psutil.cpu_percent(None)
                vm = psutil.virtual_memory()
                gpu = self._gpu()
                disks = []
                for d in self.disks:
                    try:
                        u = psutil.disk_usage(d)
                        disks.append({"name": d.rstrip("\\"), "used": u.used, "total": u.total, "pct": u.percent})
                    except OSError:
                        pass
                with self.lock:
                    self.cpu.append(cpu)
                    self.mem.append(vm.percent)
                    self.gpu.append(gpu.get("util", 0))
                    self.latest = {
                        "time": time.time(),
                        "cpu": cpu,
                        "cores": psutil.cpu_count(),
                        "freq_ghz": (psutil.cpu_freq().current / 1000) if psutil.cpu_freq() else None,
                        "mem_used": vm.used,
                        "mem_total": vm.total,
                        "mem_pct": vm.percent,
                        "gpu": gpu,
                        "disks": disks,
                        "uptime_s": time.time() - psutil.boot_time(),
                        "procs": len(psutil.pids()),
                    }
            except Exception as e:  # keep sampling; the page shows the data age
                with self.lock:
                    self.latest["error"] = str(e)
            time.sleep(STEP_S)

    def snapshot(self) -> dict:
        with self.lock:
            return {**self.latest, "cpu_hist": list(self.cpu), "gpu_hist": list(self.gpu), "mem_hist": list(self.mem)}
