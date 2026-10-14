#!/system/bin/sh
# RAD frame boot hook. install-recovery.sh (service flash_recovery, root, each
# boot) ends with one line that runs this file. Same as the upstream
# frame-boot-hook.sh (0c0defb), plus rad-firewall.sh.
# init kills the service process group when the main process exits, so this
# file ends with an exec of frame-fixmac.sh, which never exits.
CONF=/data/local/frame-boot.conf
[ -r $CONF ] && . $CONF
B=/system/bin

[ "$POWER_FIX" = 1 ] && $B/sh $B/frame-powerfix.sh &

if [ "$WIFI_DEFER" = 1 ] && [ -n "$WIFI_DRIVER" ] && [ -e "$WIFI_DRIVER" ]; then
    : > /data/local/frame-empty.ko
    mount -o bind /data/local/frame-empty.ko "$WIFI_DRIVER"
fi
$B/sh $B/frame-wifidefer.sh &
$B/sh $B/frame-timesync.sh &
$B/sh $B/rad-firewall.sh &
exec $B/sh $B/frame-fixmac.sh
