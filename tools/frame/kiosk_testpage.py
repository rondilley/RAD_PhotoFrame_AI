"""Test page for the kiosk on the frame (S1.3: TC-06 WebView gate, TC-36 origin pin).

    python -I tools/frame/kiosk_testpage.py [--port 8765]

The frame reaches it through USB with `adb reverse tcp:8765 tcp:8765`, so the
frame stays off the network. The kiosk host URL is http://127.0.0.1:8765/frame.

The page:
  - shows a clock, the WebView version and the token state (cookie rf_token),
  - checks Chromium 106 features and sends the result to /result,
  - tries five ways to reach a different origin, http://localhost:8765
    (the same server through the same USB tunnel, but a different origin):
    an image, a fetch, an iframe, window.open and, after 8 s, a navigation.
    It also has a link for a finger test.
The kiosk must refuse all of them. Each request that arrives with the Host
localhost:8765 is a pin failure. This page has no CSP header on purpose, so
that only the kiosk origin pin can stop these requests.

The log is diagnostics/kiosk/testpage.jsonl. The test token is in
diagnostics/kiosk/test-token.txt (made on the first start).
"""

import datetime
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
DIAG = PROJ / "diagnostics" / "kiosk"
LOG = DIAG / "testpage.jsonl"
TOKEN_FILE = DIAG / "test-token.txt"
PIN_HOST = "127.0.0.1"
OFF = "http://localhost:{port}"

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=1280, initial-scale=1">
<title>RAD Frame test</title>
<style>
  :root { --bg: #0d1117; --fg: #e6edf3; --ok: #3fb950; --bad: #f85149; --dim: #8b949e; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg);
    font-family: sans-serif; overflow: hidden; }
  .wrap { display: grid; grid-template-rows: 64px 1fr 24px; height: 800px; width: 1280px; }
  header { display: flex; align-items: center; justify-content: space-between; padding: 0 24px;
    font-size: 24px; border-bottom: 1px solid #30363d; }
  main { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; padding: 24px; }
  .clock { font-size: 120px; font-weight: 700; letter-spacing: 2px; }
  .box { border: 1px solid #30363d; border-radius: 12px; padding: 16px 20px; font-size: 20px; }
  .row { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; }
  .ok { color: var(--ok); } .bad { color: var(--bad); }
  footer { font-size: 18px; color: var(--dim); padding: 0 24px; }
  a.off { color: #58a6ff; font-size: 28px; }
  .hidden { width: 1px; height: 1px; border: 0; }
</style></head>
<body><div class="wrap">
<header><span>RAD Frame test page</span><span id="ua"></span><span>TOKEN_STATE</span></header>
<main>
  <div>
    <div class="clock" id="clock">--:--:--</div>
    <div class="box" style="aspect-ratio: 4 / 1">
      <div>Hold one finger still in the top-left corner for 3 s for the kiosk menu.</div>
      <p><a class="off" href="OFF/off-link">Off-origin link (TC-36 finger test)</a></p>
    </div>
  </div>
  <div class="box" id="checks"></div>
</main>
<footer id="foot">Results go to the host each 10 s.</footer>
</div>
<img class="hidden" src="OFF/off-img.png" alt="">
<iframe class="hidden" src="OFF/off-iframe"></iframe>
<script>
"use strict";
const results = {};
function check(name, fn) {
  let ok = false;
  try { ok = !!fn(); } catch (e) { ok = false; }
  results[name] = ok;
}
const m = navigator.userAgent.match(/Chrome\\/([0-9.]+)/);
document.getElementById("ua").textContent = "Chrome " + (m ? m[1] : "unknown");
results.chrome = m ? m[1] : "unknown";
check("css_grid_gap", () => CSS.supports("gap", "1px"));
check("css_aspect_ratio", () => CSS.supports("aspect-ratio", "1 / 1"));
check("css_is_selector", () => CSS.supports("selector(:is(a, b))"));
check("css_custom_properties", () => CSS.supports("--x", "1"));
check("js_optional_chaining", () => new Function("const o = {}; return o?.a?.b === undefined;")());
check("js_nullish", () => new Function("return (null ?? 2) === 2;")());
check("js_structured_clone", () => typeof structuredClone === "function");
check("js_resize_observer", () => typeof ResizeObserver === "function");
check("intl_format_to_parts", () => new Intl.DateTimeFormat("en-US").formatToParts(new Date()).length > 0);
check("fetch_abort", () => typeof AbortController === "function");

const box = document.getElementById("checks");
for (const [k, v] of Object.entries(results)) {
  const row = document.createElement("div");
  row.className = "row";
  const ok = v === true || (k === "chrome" && v.startsWith("106."));
  row.innerHTML = "<span>" + k + "</span><span class='" + (ok ? "ok" : "bad") + "'>" + v + "</span>";
  box.appendChild(row);
}

function tick() {
  const d = new Date();
  document.getElementById("clock").textContent = d.toLocaleTimeString("en-US", { hour12: false });
}
tick(); setInterval(tick, 1000);

// Off-origin attempts. The kiosk must refuse each one.
try { fetch("OFF/off-fetch").then(() => { results.fetch_reply = "answered"; }, () => { results.fetch_reply = "refused"; }); } catch (e) { results.fetch_reply = "error"; }
try { const w = window.open("OFF/off-window"); results.window_open = w ? "object" : "null"; } catch (e) { results.window_open = "error"; }

let posts = 0;
function post(stage) {
  results.stage = stage;
  results.location = location.href;
  fetch("/result", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(results) })
    .then(() => { document.getElementById("foot").textContent = "Results sent (" + (++posts) + "), stage " + stage + "."; });
}
setTimeout(() => post("loaded"), 2000);
setTimeout(() => { location.href = "OFF/off-nav"; }, 8000);
setTimeout(() => post("after_navigation_attempt"), 12000);
setInterval(() => post("periodic"), 10000);
</script></body></html>
"""

OFF_PAGE = """<!doctype html><html><body style="background:#b00;color:#fff;font:48px sans-serif">
<p>OFF-ORIGIN PAGE LOADED. The origin pin failed.</p></body></html>"""


def log(entry: dict) -> None:
    entry = {"time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), **entry}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps(entry), flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "RadFrameTest/0.1"

    def log_message(self, fmt, *args):  # one JSON line per request instead
        pass

    def host(self) -> str:
        return (self.headers.get("Host") or "").split(":")[0]

    def token_state(self) -> str:
        want = TOKEN_FILE.read_text().strip()
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "rf_token":
                return "token ok" if secrets.compare_digest(value, want) else "token wrong"
        return "token missing"

    def send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        off = self.host() != PIN_HOST
        log({"method": "GET", "host": self.headers.get("Host"), "path": self.path.split("?")[0],
             "pin_failure": off, "token": self.token_state()})
        if off:
            self.send(200, OFF_PAGE.encode(), "text/html; charset=utf-8")
        elif self.path.split("?")[0] == "/frame":
            page = PAGE.replace("OFF", OFF.format(port=self.server.server_port)).replace("TOKEN_STATE", self.token_state())
            self.send(200, page.encode(), "text/html; charset=utf-8")
        else:
            self.send(404, b"not found", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(min(length, 65536))
        try:
            data = json.loads(body)
        except ValueError:
            data = {"raw": body[:200].decode("ascii", "replace")}
        off = self.host() != PIN_HOST
        log({"method": "POST", "host": self.headers.get("Host"), "path": self.path, "pin_failure": off,
             "token": self.token_state(), "result": data})
        self.send(204, b"", "text/plain")


def main(argv: list[str]) -> int:
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8765
    DIAG.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32) + "\n")
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"test page on http://127.0.0.1:{port}/frame (log {LOG.relative_to(PROJ)})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
