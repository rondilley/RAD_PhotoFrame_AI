"""One-time account setup for the health dashboard. Run it yourself:

    python -m radframe.accounts

It opens a setup page at http://127.0.0.1:8767/ in your browser. Type the Garmin login
(and the MFA code) and the Strava app ID and secret there. The page shows the progress
and the exact error. The server listens on loopback only; stop it with Ctrl+C.

Tokens go to %LOCALAPPDATA%\\RAD_PhotoFrame\\ (garmin_tokens\\, strava.json). They stay on
the workstation and never go to the frame. Undo: delete those files.
"""

import html
import logging
import http.server
import json
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser

import httpx

from .config import DATA_DIR

GARMIN_DIR = DATA_DIR / "garmin_tokens"
STRAVA_FILE = DATA_DIR / "strava.json"
PORT = 8767
ORIGIN = f"http://127.0.0.1:{PORT}"
STRAVA_REDIRECT = f"{ORIGIN}/strava/callback"

FORM_KEY = secrets.token_urlsafe(16)  # per run; stops other sites posting to this page

# Mobile routes get 429 here, and the widget route sends the email code but misses the
# code page, so it drops the session. The portal route handles the MFA code correctly.
GARMIN_SKIP = {"mobile+cffi", "mobile+requests", "widget+cffi"}


class _Steps(logging.Handler):
    """Last login steps from garminconnect, in memory only, for the error text."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines = (self.lines + [record.getMessage()[:200]])[-8:]


STEPS = _Steps()
_glog = logging.getLogger("garminconnect")
_glog.setLevel(logging.DEBUG)
_glog.addHandler(STEPS)


def garmin_ok() -> bool:
    return (GARMIN_DIR / "garmin_tokens.json").exists()


class GarminLogin:
    """Login runs in a thread: Garmin rate-limits the fast routes, and the web route
    waits 15 s or more before it sends the password."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = "idle"  # idle, working, mfa, ok, error
        self.msg = ""
        self.started = 0.0
        self.g = None

    def start(self, email: str, password: str) -> None:
        with self.lock:
            if self.state == "working":
                return
            self.state, self.msg, self.started = "working", "", time.time()
        threading.Thread(target=self._login, args=(email, password), daemon=True).start()

    def _finish(self) -> None:
        GARMIN_DIR.mkdir(parents=True, exist_ok=True)
        self.g.client.dump(str(GARMIN_DIR))
        name = self.g.get_full_name() or "connected"
        with self.lock:
            self.state, self.msg = "ok", f"Garmin connected ({name})."

    def _fail(self, e: Exception) -> None:
        steps = "\n".join(STEPS.lines)
        with self.lock:
            self.state, self.msg = "error", f"{type(e).__name__}: {e}\n\nSteps:\n{steps}"

    def _login(self, email: str, password: str) -> None:
        from garminconnect import Garmin

        try:
            STEPS.lines = []
            self.g = Garmin(email, password, return_on_mfa=True)
            self.g.client.skip_strategies = set(GARMIN_SKIP)
            status, _ = self.g.login()
            if status == "needs_mfa":
                with self.lock:
                    self.state = "mfa"
                return
            self._finish()
        except Exception as e:
            self._fail(e)

    def mfa(self, code: str) -> None:
        with self.lock:
            if self.state != "mfa":
                return
            self.state, self.msg = "working", ""

        def run():
            try:
                self.g.resume_login(None, code)
                self._finish()
            except Exception as e:
                with self.lock:  # a wrong code keeps the MFA session; let Ron try again
                    self.state, self.msg = "mfa", f"{type(e).__name__}: {e}"

        threading.Thread(target=run, daemon=True).start()

    def view(self) -> tuple[str, str, float]:
        with self.lock:
            return self.state, self.msg, self.started


GARMIN = GarminLogin()
STRAVA = {"client_id": "", "secret": "", "state": "", "msg": ""}

CSS = """body{font:16px system-ui,sans-serif;background:#111;color:#ddd;max-width:720px;margin:32px auto;padding:0 16px}
h1{font-size:22px}h2{font-size:18px;margin-top:28px}section{background:#1c1c1c;border-radius:10px;padding:16px 20px;margin:16px 0}
input{font:inherit;padding:6px 8px;width:100%;box-sizing:border-box;margin:4px 0 10px;background:#000;color:#fff;border:1px solid #444;border-radius:6px}
button{font:inherit;padding:8px 18px;border:0;border-radius:6px;background:#3a7bd5;color:#fff;cursor:pointer}
.ok{color:#3ddc97}.err{color:#ff6b6b;white-space:pre-wrap}.dim{color:#888;font-size:14px}code{color:#ffd166}a{color:#4cc9f0}"""


def page(refresh: bool) -> str:
    gs, gmsg, gstart = GARMIN.view()
    k = f'<input type="hidden" name="k" value="{FORM_KEY}">'
    if gs == "working":
        g = (f"<p>Logging in to Garmin... {int(time.time() - gstart)} s.</p>"
             '<p class="dim">Garmin slows down logins. This can take 1 to 2 minutes. The page updates itself.</p>')
    elif gs == "mfa":
        g = ((f'<p class="err">{html.escape(gmsg)}</p>' if gmsg else "")
             + f'<p>Garmin sent you a new verification code. Use the newest email; an older code does not work.</p><form method="post" action="/garmin/mfa">{k}'
             '<label>Code<input name="code" autocomplete="one-time-code" autofocus></label><button>Send code</button></form>')
    else:
        head = (f'<p class="ok">{html.escape(gmsg)}</p>' if gs == "ok" else
                f'<p class="err">{html.escape(gmsg)}</p>' if gs == "error" else
                '<p class="ok">Connected (token saved).</p>' if garmin_ok() else "<p>Not connected.</p>")
        g = head + (f'<form method="post" action="/garmin">{k}'
                    '<label>Garmin Connect email<input name="email" autocomplete="username"></label>'
                    '<label>Password<input name="password" type="password" autocomplete="current-password"></label>'
                    f'<button>{"Log in again" if garmin_ok() else "Log in"}</button></form>')
    if STRAVA["state"] == "ok":
        s = f'<p class="ok">{html.escape(STRAVA["msg"])}</p>'
    else:
        s = ((f'<p class="err">{html.escape(STRAVA["msg"])}</p>' if STRAVA["state"] == "error" else "")
             + ('<p class="ok">Connected (token saved).</p>' if STRAVA_FILE.exists() else "<p>Not connected.</p>")
             + '<ol class="dim"><li>Open <a href="https://www.strava.com/settings/api" target="_blank">strava.com/settings/api</a> '
             "and make an app (any name; website <code>http://127.0.0.1</code>).</li>"
             "<li>Set <b>Authorization Callback Domain</b> to <code>127.0.0.1</code>.</li>"
             "<li>Copy the Client ID and the Client Secret into the fields here.</li></ol>"
             f'<form method="post" action="/strava">{k}<label>Client ID (a number)<input name="client_id" inputmode="numeric" autocomplete="off"></label>'
             '<label>Client Secret (40 letters and digits)<input name="secret" type="password" autocomplete="new-password"></label><button>Connect Strava</button></form>')
    meta = '<meta http-equiv="refresh" content="2">' if refresh else ""
    return (f'<!doctype html><html><head><meta charset="utf-8">{meta}<title>RAD Frame accounts</title>'
            f"<style>{CSS}</style></head><body><h1>RAD Frame: health accounts</h1>"
            f"<section><h2>Garmin Connect</h2>{g}</section><section><h2>Strava</h2>{s}</section>"
            '<p class="dim">Tokens stay in %LOCALAPPDATA%\\RAD_PhotoFrame. When both show connected, '
            "close this tab and stop the command with Ctrl+C. The frame shows data within 15 minutes.</p></body></html>")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        """No request log: queries and forms hold codes and secrets."""
        return

    def _send(self, body: str, code: int = 200) -> None:
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _redirect(self, to: str) -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def _host_ok(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{PORT}"

    def do_GET(self):
        if not self._host_ok():
            return self._send("wrong host", 400)
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            return self._send(page(GARMIN.view()[0] == "working"))
        if u.path == "/strava/callback":
            q = {a: b[0] for a, b in urllib.parse.parse_qs(u.query).items()}
            if q.get("state") != FORM_KEY or "code" not in q:
                STRAVA.update(state="error", msg=f"Strava did not give a code ({q.get('error', 'state mismatch')}).")
                return self._redirect("/")
            try:
                r = httpx.post("https://www.strava.com/oauth/token", timeout=30, data={
                    "client_id": STRAVA["client_id"], "client_secret": STRAVA["secret"],
                    "code": q["code"], "grant_type": "authorization_code"})
                if r.status_code != 200:
                    raise RuntimeError(f"token exchange HTTP {r.status_code}: {r.text[:300]}")
                tok = r.json()
                scope = q.get("scope", "")
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                STRAVA_FILE.write_text(json.dumps({"client_id": STRAVA["client_id"], "client_secret": STRAVA["secret"],
                                                   "refresh_token": tok["refresh_token"], "scope": scope}))
                who = tok.get("athlete") or {}
                note = "" if "activity:read" in scope else " Warning: activity access was not granted; tick it on the Strava page."
                STRAVA.update(state="ok", msg=f"Strava connected ({who.get('firstname', '')} {who.get('lastname', '')}).{note}")
            except Exception as e:
                STRAVA.update(state="error", msg=f"{type(e).__name__}: {e}")
            return self._redirect("/")
        self._send("not found", 404)

    def do_POST(self):
        if not self._host_ok() or self.headers.get("Origin") not in (ORIGIN, None):
            return self._send("wrong origin", 403)
        n = int(self.headers.get("Content-Length") or 0)
        f = {a: b[0].strip() for a, b in urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}
        if f.get("k") != FORM_KEY:
            return self._send("stale form: reload the page", 403)
        if self.path == "/garmin" and f.get("email") and f.get("password"):
            GARMIN.start(f["email"], f["password"])
        elif self.path == "/garmin/mfa" and f.get("code"):
            GARMIN.mfa(f["code"])
        elif self.path == "/strava" and not (f.get("client_id", "").isdigit() and len(f.get("secret", "")) == 40):
            STRAVA.update(state="error", msg=(
                "Client ID must be only digits and Client Secret must be 40 characters. Copy both from "
                "strava.com/settings/api (click 'Show' for the secret). A browser can fill these fields "
                f"with a saved login: check them. You gave an ID of {len(f.get('client_id', ''))} characters"
                f"{' with an @' if '@' in f.get('client_id', '') else ''} and a secret of {len(f.get('secret', ''))}."))
        elif self.path == "/strava":
            STRAVA.update(client_id=f["client_id"], secret=f["secret"], state="", msg="")
            return self._redirect("https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode({
                "client_id": f["client_id"], "response_type": "code", "approval_prompt": "force",
                "redirect_uri": STRAVA_REDIRECT, "scope": "read,activity:read_all", "state": FORM_KEY}))
        self._redirect("/")


def main() -> int:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Setup page: {ORIGIN}/   (Ctrl+C to stop)")
    webbrowser.open(f"{ORIGIN}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()
    print(f"Garmin: {'connected' if garmin_ok() else 'not connected'}   "
          f"Strava: {'connected' if STRAVA_FILE.exists() else 'not connected'}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] and sys.argv[1] not in ("garmin", "strava"):
        print(__doc__)
        sys.exit(2)
    sys.exit(main())
