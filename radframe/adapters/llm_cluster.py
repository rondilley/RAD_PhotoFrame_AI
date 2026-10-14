"""Local inference cluster: llama.cpp servers with an OpenAI API (read only).

Each node is polled each 5 s: /health, /slots (busy slots, task counter, decoded
tokens), and /props each 60 s (model, slot count). /metrics is off on these
servers, so the token rate is an estimate from the slot counters: a short task
that starts and ends between two polls is not seen.
"""

import collections
import threading
import time

import httpx

STEP_S = 5
HISTORY_S = 60 * 60
PROPS_EVERY_S = 60


class Node:
    def __init__(self, name: str, url: str):
        self.name, self.url = name, url.rstrip("/")
        n = HISTORY_S // STEP_S
        self.busy = collections.deque(maxlen=n)      # busy slots per poll
        self.tasks = collections.deque(maxlen=n)     # (time, tasks finished since the last poll)
        self.tokens = collections.deque(maxlen=n)    # (time, decoded tokens since the last poll)
        self.last_task: int | None = None
        self.slot_seen: dict[int, tuple[int, int]] = {}  # slot id -> (task id, n_decoded)
        self.props: dict = {}
        self.props_at = 0.0
        self.ok = False
        self.latency_ms: float | None = None
        self.error: str | None = None
        self.slots_total = 0
        self.busy_now = 0
        self.seen_at = 0.0

    def poll(self, client: httpx.Client) -> None:
        now = time.time()
        try:
            t0 = time.perf_counter()
            h = client.get(self.url + "/health", timeout=3)
            self.latency_ms = (time.perf_counter() - t0) * 1000
            slots = client.get(self.url + "/slots", timeout=3).json()
            if now - self.props_at > PROPS_EVERY_S:
                self.props = client.get(self.url + "/props", timeout=3).json()
                self.props_at = now
        except Exception as e:
            self.ok, self.error = False, type(e).__name__
            self.busy.append(0)
            self.tasks.append((now, 0))
            self.tokens.append((now, 0))
            return
        self.ok, self.error, self.seen_at = h.status_code == 200, None, now
        self.slots_total = len(slots)
        self.busy_now = sum(1 for s in slots if s.get("is_processing"))
        top = max((s.get("id_task", -1) for s in slots), default=-1)
        done = 0 if self.last_task is None or top < self.last_task else top - self.last_task
        self.last_task = top
        decoded = 0
        for s in slots:
            nt = s.get("next_token") or [{}]
            n = nt[0].get("n_decoded", 0) if isinstance(nt, list) and nt else 0
            task = s.get("id_task", -1)
            prev = self.slot_seen.get(s.get("id"))
            if prev is None:
                pass
            elif prev[0] == task:
                decoded += max(0, n - prev[1])
            else:
                decoded += n
            self.slot_seen[s.get("id")] = (task, n)
        self.busy.append(self.busy_now)
        self.tasks.append((now, done))
        self.tokens.append((now, decoded))

    def snapshot(self) -> dict:
        now = time.time()
        model = self.props.get("model_alias") or (self.props.get("model_path") or "").rsplit("/", 1)[-1]
        short = model.split("/")[-1].replace("-GGUF", "").replace(".gguf", "")

        def window(series, secs):
            return sum(v for t, v in series if now - t <= secs)

        per5 = []
        for k in range(12, 0, -1):  # tasks per 5 minutes, last hour
            per5.append(sum(v for t, v in self.tasks if now - k * 300 < t <= now - (k - 1) * 300))
        return {
            "name": self.name, "ok": self.ok, "error": self.error, "model": short,
            "slots": self.slots_total, "busy": self.busy_now, "sleeping": bool(self.props.get("is_sleeping")),
            "latency_ms": self.latency_ms, "busy_hist": list(self.busy)[-360:],
            "req_min": window(self.tasks, 60), "req_hour": window(self.tasks, 3600),
            "tok_s": window(self.tokens, 60) / 60, "tok_hour": window(self.tokens, 3600), "per5": per5,
            "ctx": (self.props.get("default_generation_settings") or {}).get("n_ctx"),
        }


class ClusterReader:
    def __init__(self, nodes: list[tuple[str, str]]):
        self.nodes = [Node(n, u) for n, u in nodes]
        self.lock = threading.Lock()
        if self.nodes:
            threading.Thread(target=self._run, name="llm-cluster", daemon=True).start()

    def _run(self) -> None:
        with httpx.Client() as client:
            while True:
                t0 = time.time()
                for n in self.nodes:
                    with self.lock:
                        n.poll(client)
                time.sleep(max(0.5, STEP_S - (time.time() - t0)))

    def snapshot(self) -> dict:
        with self.lock:
            nodes = [n.snapshot() for n in self.nodes]
        up = [n for n in nodes if n["ok"]]
        per5 = [sum(n["per5"][i] for n in nodes) for i in range(12)]
        return {
            "nodes": nodes, "up": len(up), "total": len(nodes),
            "busy": sum(n["busy"] for n in up), "slots": sum(n["slots"] for n in up),
            "req_hour": sum(n["req_hour"] for n in nodes), "req_min": sum(n["req_min"] for n in nodes),
            "tok_s": sum(n["tok_s"] for n in nodes), "tok_hour": sum(n["tok_hour"] for n in nodes), "per5": per5,
        }
