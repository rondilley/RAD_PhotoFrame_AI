"""Command line:
    python -m radframe serve    the host service in this process
    python -m radframe run      supervisor for the Windows logon start: one copy only,
                                log file, restarts `serve` when it stops
    python -m radframe token    print the path of the frame token file
"""

import datetime as dt
import logging
import logging.handlers
import os
import subprocess
import sys
import time

from .config import DATA_DIR, Config

LOG_DIR = DATA_DIR / "logs"


def _log(name: str) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.TimedRotatingFileHandler(LOG_DIR / f"{name}.log", when="midnight", backupCount=14,
                                                  encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    log.addHandler(h)
    return log


def serve(cfg: Config) -> int:
    import uvicorn

    from .app import create_app

    if sys.stdout is None:  # pythonw: no console
        f = open(LOG_DIR / "serve.out.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f
    uvicorn.run(create_app(cfg), host=cfg.bind, port=cfg.port, log_level="warning")
    return 0


def run() -> int:
    import msvcrt

    log = _log("supervisor")
    lock = open(DATA_DIR / "host.lock", "a+")
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        log.info("another supervisor runs; exit")
        return 0
    exe = sys.executable  # pythonw.exe from the logon shortcut, so no console windows
    log.info("start, pid %s, %s", os.getpid(), exe)
    fails = 0
    while True:
        t0 = time.time()
        p = subprocess.Popen([exe, "-m", "radframe", "serve"], cwd=str(Config.load().calendars_file.parent),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log.info("serve started, pid %s", p.pid)
        code = p.wait()
        ran = time.time() - t0
        fails = fails + 1 if ran < 60 else 0
        wait = min(300, 10 * (2 ** min(fails, 5)))
        log.warning("serve stopped, code %s after %.0f s; restart in %s s", code, ran, wait)
        time.sleep(wait)


def main(argv: list[str]) -> int:
    cfg = Config.load()
    if argv[:1] == ["serve"]:
        return serve(cfg)
    if argv[:1] == ["run"]:
        return run()
    if argv[:1] == ["token"]:
        print(cfg.token_file)  # the path only; the token stays in the file
        cfg.token()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
