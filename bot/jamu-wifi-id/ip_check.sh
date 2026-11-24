#!/bin/bash
# #JAMU WIFI ID — filter IP wifi.id dengan whitelist + blacklist untuk EarnApp.
#
# Alur:
#   1. IP publik dicek ke blacklist lokal -> ghost (MAC + reconnect, tanpa reboot).
#   2. Kalau ada di whitelist lokal -> IP dikunci (tidak dirotate).
#   3. IP baru: tunggu SYNC_WAIT detik supaya EarnApp check-in, lalu cek status.
#   4. RED  -> IP dicatat ke blacklist (dengan timestamp), MAC dirotate.
#      GREEN -> IP dicatat ke whitelist, koneksi dikunci.
#
# Default TANPA reboot (uptime EarnApp tetap jalan). Set REBOOT_ON_BAN=1 kalau
# ingin perilaku instalasi lama yang reboot setelah mengacak MAC.
set -u

IF="${IF:-wlan0}"
WL="${WL:-/etc/ip_whitelist.txt}"
BL="${BL:-/etc/ip_blacklist.txt}"
COOKIE="${COOKIE:-/etc/tg-bot/cookie}"
SYNC_WAIT="${SYNC_WAIT:-60}"
MAX_ROTATE="${MAX_ROTATE:-10}"
REBOOT_ON_BAN="${REBOOT_ON_BAN:-0}"

log() {
    printf '%s %s\n' "$(date '+%F %T')" "$*"
    logger -t jamu-wifi-id "$*" 2>/dev/null || true
}

pubip() { curl -4 -s -m 10 https://api.ipify.org 2>/dev/null | tr -d '[:space:]'; }
valid_ip() { [[ "${1:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; }
in_file() { grep -qF -- "${1:-}" "$2" 2>/dev/null; }
add_exact() {
    touch "$2" 2>/dev/null || return 1
    grep -qxF -- "$1" "$2" 2>/dev/null || printf '%s\n' "$1" >> "$2"
}

# 0 = green, 1 = banned, 2 = belum pasti
ban_check() {
    python3 - "$1" "$COOKIE" <<'PY'
import json
import re
import sys
import urllib.request

ip = sys.argv[1]
cookie_path = sys.argv[2]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

try:
    cookie = open(cookie_path, encoding="utf-8").read().strip()
    uuid = open("/etc/earnapp/uuid", encoding="utf-8").read().strip()
except OSError:
    cookie = ""
    uuid = ""

headers = {"User-Agent": UA, "Accept": "application/json",
           "Referer": "https://earnapp.com/dashboard",
           "X-Requested-With": "XMLHttpRequest"}
if cookie:
    headers["Cookie"] = cookie

try:
    if cookie and uuid:
        req = urllib.request.Request(
            "https://earnapp.com/dashboard/api/devices", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            devices = json.loads(resp.read().decode("utf-8", "replace"))
        me = next((d for d in devices
                   if isinstance(d, dict) and d.get("uuid") == uuid), None)
        if me is None:
            print("pending (device tidak ada di akun)")
            sys.exit(2)
        ban = me.get("banned")
        if isinstance(ban, dict):
            print("banned %s (%s)" % (ban.get("ip") or "?",
                                      ban.get("reason") or "earnapp"))
            sys.exit(1)
        print("green %s" % ip)
        sys.exit(0)

    # Tanpa cookie: pakai halaman publik seperti instalasi #JAMU lama.
    req = urllib.request.Request("https://earnapp.com",
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=12) as resp:
        body = resp.read().decode("utf-8", "replace")
    if re.search(r'"allowed"\s*:\s*false', body, re.I) or re.search(
            r"\bblocked\b", body, re.I):
        print("banned (public page)")
        sys.exit(1)
    print("green (public page, akurasi rendah — isi cookie dianjurkan)")
    sys.exit(0)
except Exception as exc:  # noqa: BLE001
    print("pending (%s)" % exc)
    sys.exit(2)
PY
}

prof() {
    local p
    p=$(nmcli -t -f NAME,TYPE con show --active 2>/dev/null | grep ':802-11-wireless$' | head -1 | cut -d: -f1)
    [ -z "$p" ] && p=$(nmcli -t -f NAME,TYPE con show 2>/dev/null | grep ':802-11-wireless$' | head -1 | cut -d: -f1)
    printf '%s' "$p"
}

random_mac() {
    python3 -c "import random;print('02:%02x:%02x:%02x:%02x:%02x' % tuple(random.randrange(256) for _ in range(5)))"
}

wait_ip() {
    local left="$1" ip=""
    while [ "$left" -gt 0 ]; do
        ip=$(pubip)
        [ -n "$ip" ] && { printf '%s' "$ip"; return 0; }
        sleep 3
        left=$((left - 3))
    done
    return 1
}

rotate() {
    local old_ip="$1" p attempt=1 ip out verdict waited mac old_clone
    p=$(prof)
    [ -n "$p" ] || { log "ERROR: profil Wi-Fi tidak ditemukan"; return 1; }
    old_clone=$(nmcli -g wifi.cloned-mac-address con show "$p" 2>/dev/null)

    restore() {
        if [ -n "$old_clone" ]; then
            nmcli con modify "$p" wifi.cloned-mac-address "$old_clone" >/dev/null 2>&1
        else
            nmcli con modify "$p" wifi.cloned-mac-address "" >/dev/null 2>&1
        fi
        nmcli con down "$p" >/dev/null 2>&1
        sleep 2
        nmcli con up "$p" >/dev/null 2>&1
    }
    trap 'restore; exit 143' TERM INT HUP

    while [ "$attempt" -le "$MAX_ROTATE" ]; do
        mac=$(random_mac)
        nmcli con modify "$p" wifi.cloned-mac-address "$mac" >/dev/null 2>&1
        nmcli con down "$p" >/dev/null 2>&1
        sleep 3
        nmcli con up "$p" >/dev/null 2>&1

        ip=$(wait_ip 35) || ip=""
        if [ -z "$ip" ]; then
            log "attempt $attempt: tidak ada internet, retry"
        elif in_file "$ip" "$BL"; then
            log "attempt $attempt: $ip masuk blacklist lokal, retry"
        else
            verdict=2
            waited=0
            while [ "$waited" -lt 60 ]; do
                out=$(ban_check "$ip")
                verdict=$?
                [ "$verdict" -ne 2 ] && break
                sleep 10
                waited=$((waited + 10))
            done
            if [ "$verdict" -eq 1 ]; then
                log "attempt $attempt: $ip banned EarnApp ($out), blacklist + retry"
                printf '[%s] - %s - BLOCKED\n' "$(date '+%F %T')" "$ip" >> "$BL"
            else
                log "ghost OK: $old_ip -> $ip (MAC $mac, profil $p, $out)"
                trap - TERM INT HUP
                return 0
            fi
        fi
        attempt=$((attempt + 1))
    done

    log "WARN: $MAX_ROTATE percobaan gagal, MAC lama dikembalikan"
    restore
    trap - TERM INT HUP
    return 1
}

reboot_cycle() {
    local p mac
    p=$(prof)
    [ -n "$p" ] || return 1
    mac=$(random_mac)
    nmcli con modify "$p" wifi.cloned-mac-address "$mac" >/dev/null 2>&1
    log "REBOOT_ON_BAN=1: MAC diacak ke $mac, reboot dalam 60 detik"
    sleep 60
    sync
    systemctl reboot
}

log "=== start jamu-wifi-id (if=$IF wl=$WL bl=$BL sync=${SYNC_WAIT}s) ==="
mkdir -p "$(dirname "$WL")" "$(dirname "$BL")" 2>/dev/null || true
touch "$WL" "$BL" 2>/dev/null || true

while :; do
    ip=""
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        ip=$(pubip)
        valid_ip "$ip" && break
        sleep 5
    done
    if ! valid_ip "$ip"; then
        log "belum ada internet/IP publik, tunggu 30s"
        sleep 30
        continue
    fi

    if in_file "$ip" "$BL"; then
        log "IP $ip ada di BLACKLIST lokal"
        if [ "$REBOOT_ON_BAN" = "1" ]; then
            reboot_cycle
        else
            rotate "$ip" || log "rotate gagal, ulangi siklus"
        fi
        continue
    fi

    if in_file "$ip" "$WL"; then
        log "IP $ip ada di WHITELIST lokal — dikunci"
        sleep 300
        continue
    fi

    log "IP baru $ip — tunggu ${SYNC_WAIT}s agar EarnApp check-in"
    sleep "$SYNC_WAIT"
    now=$(pubip)
    valid_ip "$now" && ip="$now"

    out=$(ban_check "$ip")
    verdict=$?
    case "$verdict" in
        0)
            add_exact "$ip" "$WL"
            log "GREEN: $ip ($out) — masuk whitelist, IP dikunci"
            sleep 300
            ;;
        1)
            printf '[%s] - %s - BLOCKED\n' "$(date '+%F %T')" "$ip" >> "$BL"
            log "RED: $ip ($out) — masuk blacklist"
            if [ "$REBOOT_ON_BAN" = "1" ]; then
                reboot_cycle
            else
                rotate "$ip" || log "rotate gagal, ulangi siklus"
            fi
            ;;
        *)
            log "status belum pasti ($out) — cek lagi 60s"
            sleep 60
            ;;
    esac
done
