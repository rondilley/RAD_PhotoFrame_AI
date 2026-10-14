"""Frame boot fixes for Wi-Fi (S1.5, ARCHITECTURE 14.4). A Windows port of the
upstream scripts/pf1007l-boot/install.sh (0c0defb), with the same device
scripts, plus our firewall (tools/frame/device/rad-firewall.sh).

    python -I tools/frame/boot_fixes.py check     <unit>   read only
    python -I tools/frame/boot_fixes.py apply     <unit>   backup, install, check the files
    python -I tools/frame/boot_fixes.py verify    <unit>   after a restart: what each fix did
    python -I tools/frame/boot_fixes.py uninstall <unit>   put back install-recovery.sh and wpa_supplicant

The frame config (/data/local/frame-boot.conf) holds the pinned MAC, so it is
made here and not kept in git. Backups: backups/<unit>/boot-fixes/<time>/.
"""

import datetime as dt
import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frame_adb import PROJ, Frame  # noqa: E402

UP = PROJ / "background" / "photo-frame-dashboard" / "scripts" / "pf1007l-boot" / "device"
OURS = PROJ / "tools" / "frame" / "device"
UP_SCRIPTS = ["frame-fixmac.sh", "frame-powerfix.sh", "frame-timesync.sh", "frame-wifidefer.sh"]
OUR_SCRIPTS = ["rad-boot-hook.sh", "rad-firewall.sh"]
HOOK_LINE = "exec /system/bin/sh /system/bin/rad-boot-hook.sh"
TMP = "/data/local/tmp/rad-boot"
CONF = "/data/local/frame-boot.conf"
BB = "/sbin/busybox"
WIFI_DRIVER = "/system/vendor/modules/aic8800_fdrv.ko"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sources() -> dict[str, bytes]:
    # git on Windows checks the upstream files out with CRLF; the frame shell needs LF
    files = {s: (UP / s).read_bytes().replace(b"\r\n", b"\n") for s in UP_SCRIPTS}
    files["wpa_supplicant-wrapper.sh"] = (UP / "wpa_supplicant-wrapper.sh").read_bytes().replace(b"\r\n", b"\n")
    files.update({s: (OURS / s).read_bytes() for s in OUR_SCRIPTS})
    for name, b in files.items():
        if b"\r\n" in b:
            sys.exit(f"STOP: {name} has CRLF line ends")
    return files


def dev_sha(fr: Frame, path: str) -> str:
    rc, out = fr.sh(f"{BB} sha256sum {path}")
    return out.split()[0] if rc == 0 and out else ""


def root_script(fr: Frame, body: str) -> str:
    with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".sh") as f:
        f.write(body.replace("\r\n", "\n").encode())
        local = f.name
    fr.adb("push", local, f"{TMP}/step.sh")
    Path(local).unlink()
    return fr.must(f"sh {TMP}/step.sh", timeout=120)


def mac_from_serial(fr: Frame) -> str:
    h = sha(fr.prop("ro.serialno").encode())[:10]
    return "02:" + ":".join(h[i:i + 2] for i in range(0, 10, 2))


def check(fr: Frame) -> dict:
    fr.check_identity()
    if fr.prop("ro.product.device") != "astar-m86_8723cs" or fr.prop("ro.build.version.release") != "6.0.1":
        sys.exit("STOP: not the PF1007L astar-m86_8723cs on Android 6.0.1")
    state = {}
    for p in ("/system/bin/install-recovery.sh", "/system/bin/wpa_supplicant", WIFI_DRIVER, BB):
        state[p] = fr.sh(f"[ -e {p} ]")[0] == 0
        if not state[p]:
            sys.exit(f"STOP: {p} not found")
    state["installed"] = fr.sh(f"grep -qx '{HOOK_LINE}' /system/bin/install-recovery.sh")[0] == 0
    state["wrapped"] = fr.sh("[ -e /system/bin/wpa_supplicant.real ]")[0] == 0
    state["upstream_hook"] = fr.sh("grep -q frame-boot-hook /system/bin/install-recovery.sh")[0] == 0
    state["aic8800_loaded"] = "aic8800_fdrv" in fr.must("lsmod")
    print("  ok  PF1007L, Android 6.0.1, root, busybox, install-recovery.sh, AIC8800 driver file")
    for k in ("installed", "wrapped", "upstream_hook", "aic8800_loaded"):
        print(f"  {k}: {state[k]}")
    return state


def backup(fr: Frame) -> Path:
    out = PROJ / "backups" / fr.unit / "boot-fixes" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    for p in ("/system/bin/install-recovery.sh", "/system/bin/wpa_supplicant", "/system/bin/wpa_supplicant.real",
              "/system/bin/install-recovery.sh.bak", CONF):
        if fr.sh(f"[ -f {p} ]")[0] != 0:
            continue
        dest = out / Path(p).name
        fr.adb("pull", p, str(dest))
        if sha(dest.read_bytes()) != dev_sha(fr, p):
            sys.exit(f"STOP: the copy of {p} does not agree with the frame")
        print(f"  ok  backup {p}")
    return out


def apply(fr: Frame) -> int:
    st = check(fr)
    if st["upstream_hook"]:
        sys.exit("STOP: the upstream hook is installed; uninstall it first")
    files = sources()
    bdir = backup(fr)
    mac = mac_from_serial(fr)
    conf = "\n".join([
        "# RAD frame boot fixes (tools/frame/boot_fixes.py). Private: holds the MAC.",
        # NTP: time.google.com by address. The IoT gateway has no NTP server, and the
        # frame nc (/system/xbin/nc) does not resolve names.
        f"MAC={mac}", "NTP_SERVER=216.239.35.0", "WIFI_DEFER=1", f"WIFI_DRIVER={WIFI_DRIVER}", "POWER_FIX=0",
        "ADB_ALLOW=", "IGNORE_IPV6_RA=0", "KIOSK=rad.photoframe.kiosk/.MainActivity", ""])
    (bdir / "frame-boot.conf").write_text(conf, newline="\n")
    fr.must(f"rm -rf {TMP} && mkdir -p {TMP}")
    for name, b in files.items():
        p = bdir / name
        p.write_bytes(b)
        fr.adb("push", str(p), f"{TMP}/{name}")
        if dev_sha(fr, f"{TMP}/{name}") != sha(b):
            sys.exit(f"STOP: {name} did not arrive intact")
    fr.adb("push", str(bdir / "frame-boot.conf"), f"{TMP}/frame-boot.conf")
    print(f"  ok  files pushed; MAC {mac}")

    fr.log({"step": "S1.5", "class": "write-start",
            "action": "boot_fixes.py apply: install-recovery.sh hook, wpa_supplicant wrapper, frame-*.sh (upstream 0c0defb), rad-boot-hook.sh, rad-firewall.sh, /data/local/frame-boot.conf",
            "undo": "boot_fixes.py uninstall <unit>", "backup": str(bdir.relative_to(PROJ))})
    scripts = " ".join(UP_SCRIPTS + OUR_SCRIPTS)
    out = root_script(fr, f"""set -e
T={TMP}
B=/system/bin
grep -v -x '{HOOK_LINE}' $B/install-recovery.sh > $T/install-recovery.new
if grep -q 'frame-\\|rad-' $T/install-recovery.new; then echo "FAIL: install-recovery.sh has other changes"; exit 1; fi
echo '{HOOK_LINE}' >> $T/install-recovery.new
mount -o remount,rw /system
[ -e $B/install-recovery.sh.bak ] || cp -p $B/install-recovery.sh $B/install-recovery.sh.bak
if [ ! -e $B/wpa_supplicant.real ]; then
    [ "$(dd if=$B/wpa_supplicant bs=4 count=1 2>/dev/null | od -An -c | tr -d ' ')" = '177ELF' ]
    mv $B/wpa_supplicant $B/wpa_supplicant.real
fi
cp $T/wpa_supplicant-wrapper.sh $B/wpa_supplicant
chown root:shell $B/wpa_supplicant
chmod 0755 $B/wpa_supplicant
for s in {scripts}; do
    cp $T/$s $B/$s
    chown root:shell $B/$s
    chmod 0750 $B/$s
done
cat $T/install-recovery.new > $B/install-recovery.sh
sync
mount -o remount,ro /system || echo "note: /system stays read-write until the next reboot"
cp $T/frame-boot.conf {CONF}
chown root:root {CONF}
chmod 0600 {CONF}
rm -rf $T
echo "installed"
""")
    print("  " + out.strip().replace("\n", "\n  "))
    bad = [s for s in UP_SCRIPTS + OUR_SCRIPTS if dev_sha(fr, f"/system/bin/{s}") != sha(files[s])]
    if dev_sha(fr, "/system/bin/wpa_supplicant") != sha(files["wpa_supplicant-wrapper.sh"]):
        bad.append("wpa_supplicant wrapper")
    if fr.must("tail -n 1 /system/bin/install-recovery.sh").strip() != HOOK_LINE:
        bad.append("install-recovery.sh hook line")
    ok = not bad
    fr.log({"step": "S1.5", "class": "write", "action": "boot_fixes.py apply",
            "result": ("OK: files and hook agree" if ok else f"FAIL: {bad}") + f"; MAC {mac}"})
    print("PASS: installed; restart the frame, then run verify" if ok else f"FAIL: {bad}")
    return 0 if ok else 1


def verify(fr: Frame) -> int:
    check(fr)
    conf_mac = fr.must(f"grep '^MAC=' {CONF}").split("=", 1)[1].strip()
    mac = fr.must("cat /sys/class/net/wlan0/address").strip()
    print(f"  wlan0 MAC {mac} ({'pinned' if mac == conf_mac else 'NOT the pinned ' + conf_mac})")
    print(f"  clock {fr.must('date').strip()}")
    print(f"  IPv4 {fr.sh('ip -4 addr show wlan0 | grep inet')[1].strip() or 'none (no Wi-Fi network yet)'}")
    print(f"  focus {fr.must('dumpsys window windows | grep mCurrentFocus').strip()}")
    fw4 = fr.must("iptables -S rad_in; iptables -S INPUT | head -3")
    fw6 = fr.must("ip6tables -S rad_in")
    print("  " + fw4.replace("\n", "\n  "))
    print(f"  IPv6 DROP rules: {fw6.count('-j DROP')}")
    listen = [l for l in fr.must("netstat -an").splitlines() if l.startswith("tcp") and "LISTEN" in l]
    print("  TCP LISTEN: " + "; ".join(" ".join(l.split()[3:4]) for l in listen))
    logs = fr.adb("logcat", "-d", "-v", "time", "-s", "frame-wifidefer", "frame-timesync", "frame-fixmac", "rad-firewall")
    for l in logs.splitlines():
        if l and not l.startswith("-"):
            print("  log " + l)
    ok = mac == conf_mac and fw4.count("-j DROP") >= 2 and "rad_in" in fw4 and \
        all(l.split()[3].startswith(("127.", "::1")) for l in listen)
    fr.log({"step": "S1.5", "class": "read", "action": "boot_fixes.py verify",
            "result": f"{'OK' if ok else 'FAIL'}: MAC pinned {mac == conf_mac}, firewall rules present, TCP listen {len(listen)} (loopback only {ok})"})
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def uninstall(fr: Frame) -> int:
    check(fr)
    bdir = backup(fr)
    fr.log({"step": "S1.5", "class": "write-start", "action": "boot_fixes.py uninstall", "backup": str(bdir.relative_to(PROJ))})
    scripts = " ".join(UP_SCRIPTS + OUR_SCRIPTS)
    out = root_script(fr, f"""set -e
B=/system/bin
[ -e $B/install-recovery.sh.bak ] || {{ echo "FAIL: no install-recovery.sh.bak"; exit 1; }}
mount -o remount,rw /system
want=$({BB} sha256sum $B/install-recovery.sh.bak | cut -d' ' -f1)
cp -p $B/install-recovery.sh.bak $B/install-recovery.sh
[ "$({BB} sha256sum $B/install-recovery.sh | cut -d' ' -f1)" = "$want" ]
rm $B/install-recovery.sh.bak
if [ -e $B/wpa_supplicant.real ]; then
    [ "$(dd if=$B/wpa_supplicant.real bs=4 count=1 2>/dev/null | od -An -c | tr -d ' ')" = '177ELF' ]
    mv $B/wpa_supplicant.real $B/wpa_supplicant
fi
for s in {scripts}; do rm -f $B/$s; done
sync
mount -o remount,ro /system || echo "note: /system stays read-write until the next reboot"
rm -f {CONF} /data/local/frame-lasttime /data/local/frame-nowifi /data/local/frame-empty.ko /data/local/frame-ntpreq /data/local/frame-ntpresp
echo "removed; restart the frame"
""")
    print("  " + out.strip())
    fr.log({"step": "S1.5", "class": "write", "action": "boot_fixes.py uninstall", "result": out.strip()[-120:]})
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("check", "apply", "verify", "uninstall"):
        sys.exit(__doc__)
    fr = Frame(argv[1])
    fr.must(f"mkdir -p {TMP}")
    return {"check": lambda: (check(fr), 0)[1], "apply": lambda: apply(fr),
            "verify": lambda: verify(fr), "uninstall": lambda: uninstall(fr)}[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
