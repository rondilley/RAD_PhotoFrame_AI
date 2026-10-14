#!/system/bin/sh
# RAD frame firewall (ARCHITECTURE 14.4): no new inbound connection on Wi-Fi.
# Allows loopback, replies to the frame's own connections, DHCP, and IPv6
# neighbor discovery. Network ADB stays off. Runs after boot and checks the
# rules each 60 s (Android can rebuild its own chains, not ours).
log -t rad-firewall "start"
t=0
until [ "$(getprop sys.boot_completed)" = 1 ] || [ $t -ge 120 ]; do
    sleep 1
    t=$((t + 1))
done

apply4() {
    iptables -N rad_in 2> /dev/null
    iptables -F rad_in
    iptables -A rad_in -i lo -j RETURN
    iptables -A rad_in -m state --state ESTABLISHED,RELATED -j RETURN
    iptables -A rad_in -p udp --sport 67 --dport 68 -j RETURN
    iptables -A rad_in -i wlan0 -j DROP
    iptables -A rad_in -i p2p0 -j DROP
    iptables -C INPUT -j rad_in 2> /dev/null || iptables -I INPUT 1 -j rad_in
}
apply6() {
    ip6tables -N rad_in 2> /dev/null
    ip6tables -F rad_in
    ip6tables -A rad_in -i lo -j RETURN
    ip6tables -A rad_in -m state --state ESTABLISHED,RELATED -j RETURN
    ip6tables -A rad_in -p icmpv6 -j RETURN
    ip6tables -A rad_in -i wlan0 -j DROP
    ip6tables -A rad_in -i p2p0 -j DROP
    ip6tables -C INPUT -j rad_in 2> /dev/null || ip6tables -I INPUT 1 -j rad_in
}

while true; do
    if ! iptables -C INPUT -j rad_in 2> /dev/null || [ "$(iptables -S rad_in 2> /dev/null | grep -c DROP)" -lt 2 ]; then
        apply4 && log -t rad-firewall "IPv4 rules applied"
    fi
    if ! ip6tables -C INPUT -j rad_in 2> /dev/null || [ "$(ip6tables -S rad_in 2> /dev/null | grep -c DROP)" -lt 2 ]; then
        apply6 && log -t rad-firewall "IPv6 rules applied"
    fi
    if [ -n "$(getprop service.adb.tcp.port)" ] || [ -n "$(getprop persist.adb.tcp.port)" ]; then
        setprop persist.adb.tcp.port ""
        setprop service.adb.tcp.port ""
        log -t rad-firewall "network ADB port property cleared"
    fi
    sleep 60
done
