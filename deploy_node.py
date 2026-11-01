#!/usr/bin/env python3
"""Provision an OpenStick node with the EarnApp Telegram bot.

What it does (idempotent, safe to re-run):
  1. Removes the OLD bot / automation (telegram-remote, ghoster, filter_ip,
     earnapp-watchdog, 05:00 reboot cron, ...) after backing it up to
     /root/old-bot-backup/.
  2. Installs the bot + systemd unit, token, chat id, cookie, blacklist.
  3. Base hardening: timezone Asia/Jakarta, Wi-Fi powersave off,
     Wi-Fi watchdog, status LEDs (if present).
  4. Enables + starts everything and verifies.

Usage (from Windows):
  python deploy_node.py --host 192.168.200.1 --token 123456:ABC-DEF ^
      --cookie-file ea_cookie.txt --blacklist-file blacklist.txt

Notes:
  * Every node needs its OWN bot token (@BotFather). One poller per token.
  * The EarnApp dashboard cookie is account-wide and may be shared.
  * Use --no-clean to keep existing files, --no-base to skip step 3.
"""

import argparse
import io
import os
import sys

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))
BOT_SRC = os.path.join(HERE, "bot", "tgbot.py")
if not os.path.exists(BOT_SRC):
    BOT_SRC = os.path.join(HERE, "tgbot.py")
USB_SRC = os.path.join(HERE, "bot", "openstick-usbnet")
USB_UNIT_SRC = os.path.join(HERE, "bot", "openstick-usbnet.service")
NM_CONF_SRC = os.path.join(HERE, "bot", "openstick-nm-unmanaged.conf")

UNIT = """[Unit]
Description=OpenStick Telegram bot
Wants=network-online.target
After=network-online.target
ConditionPathExists=/etc/tg-bot/token

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/tg-bot.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=no

[Install]
WantedBy=multi-user.target
"""

WATCHDOG = r"""#!/bin/bash
# OpenStick Wi-Fi watchdog: reconnect wlan0 when it loses IP/internet.
IF=wlan0
LOG=/var/log/openstick-wifi-watchdog.log
FAILS=0

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }
[ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 1048576 ] && : > "$LOG"

while true; do
    sleep 30
    # a MAC rotation intentionally drops the link for ~15-30 s; tolerate it
    if ip -4 -o addr show "$IF" 2>/dev/null | grep -q 'inet '; then
        if curl -s --max-time 8 -o /dev/null https://api.ipify.org; then
            FAILS=0
            continue
        fi
    fi
    FAILS=$((FAILS + 1))
    log "no connectivity (fails=$FAILS)"
    if [ "$FAILS" -eq 3 ]; then
        PROF=$(nmcli -t -f NAME,TYPE con show --active 2>/dev/null | grep ':802-11-wireless$' | head -1 | cut -d: -f1)
        [ -z "$PROF" ] && PROF=$(nmcli -t -f NAME,TYPE con show 2>/dev/null | grep ':802-11-wireless$' | head -1 | cut -d: -f1)
        if [ -n "$PROF" ]; then
            log "bringing up '$PROF'"
            nmcli con up "$PROF" >/dev/null 2>&1
        fi
    elif [ "$FAILS" -ge 6 ]; then
        log "restarting NetworkManager"
        systemctl restart NetworkManager
        FAILS=0
    fi
done
"""

WATCHDOG_UNIT = """[Unit]
Description=OpenStick Wi-Fi watchdog
After=NetworkManager.service network-online.target
Wants=NetworkManager.service

[Service]
Type=simple
ExecStart=/usr/local/bin/openstick-wifi-watchdog
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""

LED_UNIT = """[Unit]
Description=OpenStick status LED triggers
After=network.target
Wants=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'i=0; while [ $i -lt 60 ]; do grep -q phy0tx /sys/class/leds/green:wlan/trigger 2>/dev/null && break; i=$((i+1)); sleep 1; done; echo phy0tx > /sys/class/leds/green:wlan/trigger 2>/dev/null; echo phy0rx > /sys/class/leds/blue:wan/trigger 2>/dev/null; echo default-on > /sys/class/leds/red:power/trigger 2>/dev/null; true'

[Install]
WantedBy=multi-user.target
"""

CLEAN_SH = r"""
set +e
TS=$(date +%Y%m%d-%H%M%S)
mkdir -p /root/old-bot-backup
tar czf /root/old-bot-backup/old-files-$TS.tar.gz \
  /root/telegrambotnyil /root/tgbot /root/ghoster /root/tenangyakan001 \
  /root/earnapp-watchdog.sh /root/filter_ip.sh /root/system-optimize.sh \
  /root/earnapp-node.sh /root/earnapp_guardian.log \
  /root/semut-auto.sh /root/semut-final.sh /root/semut-setup.sh \
  /root/auto-install.sh /root/auto-install.sh.1 \
  /root/remove-telegram-bot.sh /root/remove-telegram-bot.sh.1 \
  /root/remove-telegram-bot.sh.2 /root/remove-telegram-bot.sh.3 \
  /root/remove-telegram-bot.sh.4 /root/remove-telegram-bot.sh.5 \
  /root/ip_blacklist.txt /root/blacklist.txt /root/ip_whitelist.txt \
  /root/earnapp_watchdog.log /root/ip_filter_debug.log \
  /etc/systemd/system/telegram-remote.service \
  /etc/systemd/system/telegrambotnyil.service \
  /etc/systemd/system/earnapp-bot.service \
  /etc/systemd/system/botserver.service \
  /etc/systemd/system/traffic-checker.service \
  2>/dev/null

for u in telegram-remote telegrambotnyil earnapp-bot botserver traffic-checker; do
  systemctl disable --now "$u.service" 2>/dev/null
  rm -f "/etc/systemd/system/$u.service"
done
systemctl disable --now traffic-cleaner.timer 2>/dev/null
rm -f /etc/systemd/system/traffic-cleaner.timer
systemctl daemon-reload
for u in telegram-remote telegrambotnyil earnapp-bot botserver traffic-checker; do
  systemctl reset-failed "$u.service" 2>/dev/null
done

rm -rf /root/telegrambotnyil /root/tgbot /root/ghoster /root/tenangyakan001
rm -f /root/earnapp-watchdog.sh /root/filter_ip.sh /root/system-optimize.sh
rm -f /root/earnapp-node.sh /root/earnapp_guardian.log
rm -f /root/semut-auto.sh /root/semut-final.sh /root/semut-setup.sh
rm -f /root/auto-install.sh /root/auto-install.sh.1
rm -f /root/remove-telegram-bot.sh /root/remove-telegram-bot.sh.*
rm -f /root/ip_blacklist.txt /root/blacklist.txt /root/ip_whitelist.txt
rm -f /root/earnapp_watchdog.log /root/ip_filter_debug.log

# buang cron berbahaya / usang (reboot harian, filter ip lama, optimize lama)
crontab -l 2>/dev/null \
  | grep -vE 'filter_ip\.sh|system-optimize\.sh|^[[:space:]]*0[[:space:]]+5[[:space:]]+\*[[:space:]]+\*[[:space:]]+\*[[:space:]]+reboot' \
  | crontab - 2>/dev/null

# log lama
journalctl --vacuum-size=32M >/dev/null 2>&1
find /etc/earnapp -maxdepth 1 -name '2026*-brd_sdk3.log' -delete 2>/dev/null
find /etc/earnapp -maxdepth 1 -name 'upgrade_err.log.*' -delete 2>/dev/null
: > /etc/earnapp/upgrade_err.log 2>/dev/null

echo "CLEAN_DONE"
"""

BASE_SH = r"""
set +e
# timezone
timedatectl set-timezone Asia/Jakarta

# Wi-Fi powersave off (semua profil wifi)
for p in $(nmcli -t -f NAME,TYPE con show 2>/dev/null | grep ':802-11-wireless$' | cut -d: -f1); do
  nmcli con modify "$p" 802-11-wireless.powersave 2 >/dev/null 2>&1
  nmcli con modify "$p" wifi.powersave 2 >/dev/null 2>&1
done
iw dev wlan0 set power_save off 2>/dev/null

# watchdog
install -m 755 /tmp/wd /usr/local/bin/openstick-wifi-watchdog
install -m 644 /tmp/wd.service /etc/systemd/system/openstick-wifi-watchdog.service
systemctl daemon-reload
systemctl enable openstick-wifi-watchdog.service >/dev/null 2>&1
systemctl restart openstick-wifi-watchdog.service

# USB RNDIS -> br0 192.168.100.1 (boot race fix + self-healing)
if [ -f /tmp/usbnet ]; then
  install -m 755 /tmp/usbnet /usr/local/sbin/openstick-usbnet
  install -m 644 /tmp/usbnet.service /etc/systemd/system/openstick-usbnet.service
  if [ -f /tmp/nm-unmanaged.conf ]; then
    mkdir -p /etc/NetworkManager/conf.d
    install -m 644 /tmp/nm-unmanaged.conf /etc/NetworkManager/conf.d/99-openstick-unmanaged.conf
  fi
  systemctl daemon-reload
  systemctl enable openstick-usbnet.service >/dev/null 2>&1
  systemctl restart openstick-usbnet.service >/dev/null 2>&1
  systemctl reload-or-restart NetworkManager >/dev/null 2>&1 || true
fi

# LEDs (hanya kalau hardware-nya ada)
if [ -e /sys/class/leds/green:wlan ]; then
  install -m 644 /tmp/led.service /etc/systemd/system/openstick-leds.service
  systemctl daemon-reload
  systemctl enable --now openstick-leds.service >/dev/null 2>&1
fi
echo "BASE_DONE"
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True, help="node IP (e.g. 192.168.200.1)")
    ap.add_argument("--token",
                    help="Telegram bot token (unique per node; asked if omitted)")
    ap.add_argument("--chat", default="",
                    help="lock bot to one chat id (default: auto-lock to first /start)")
    ap.add_argument("--cookie-file",
                    help="file containing the EarnApp Cookie header")
    ap.add_argument("--blacklist-file",
                    help="file with one banned IP per line")
    ap.add_argument("--user", default="user")
    ap.add_argument("--password", default="1")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--no-auto", action="store_true",
                    help="disable auto-rotate (default: on)")
    ap.add_argument("--no-clean", action="store_true",
                    help="do not remove the old bot / old files")
    ap.add_argument("--no-base", action="store_true",
                    help="skip timezone / powersave / watchdog / LEDs")
    a = ap.parse_args()

    token = (a.token or "").strip()
    if not token:
        print("Setiap node butuh token bot sendiri (buat di @BotFather).")
        while not token:
            token = input("Bot token: ").strip()
    if ":" not in token or not token.split(":", 1)[0].isdigit():
        sys.exit("format token tidak valid (contoh: 123456789:AAH...)")
    a.token = token

    if not os.path.exists(BOT_SRC):
        sys.exit("tgbot.py not found next to this script")

    cookie = ""
    if a.cookie_file:
        with open(a.cookie_file, "r", encoding="utf-8") as fh:
            cookie = fh.read().strip()

    blacklist = ""
    if a.blacklist_file:
        with open(a.blacklist_file, "r", encoding="utf-8") as fh:
            blacklist = fh.read().strip()

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(a.host, port=a.port, username=a.user, password=a.password,
                timeout=20, look_for_keys=False, allow_agent=False)
    sftp = cli.open_sftp()
    sftp.put(BOT_SRC, "/tmp/tgbot.py")
    sftp.putfo(io.StringIO(UNIT), "/tmp/tg-bot.service")
    sftp.putfo(io.StringIO(a.token.strip() + "\n"), "/tmp/tg-token")
    sftp.putfo(io.StringIO(WATCHDOG), "/tmp/wd")
    sftp.putfo(io.StringIO(WATCHDOG_UNIT), "/tmp/wd.service")
    sftp.putfo(io.StringIO(LED_UNIT), "/tmp/led.service")
    if os.path.exists(USB_SRC) and os.path.exists(USB_UNIT_SRC):
        sftp.put(USB_SRC, "/tmp/usbnet")
        sftp.put(USB_UNIT_SRC, "/tmp/usbnet.service")
    if os.path.exists(NM_CONF_SRC):
        sftp.put(NM_CONF_SRC, "/tmp/nm-unmanaged.conf")
    if cookie:
        sftp.putfo(io.StringIO(cookie + "\n"), "/tmp/tg-cookie")
    if blacklist:
        sftp.putfo(io.StringIO(blacklist + "\n"), "/tmp/tg-blacklist")
    sftp.close()

    steps = []
    if not a.no_clean:
        steps.append(CLEAN_SH)
    steps += [
        "install -m 755 /tmp/tgbot.py /usr/local/bin/tg-bot.py",
        "install -m 644 /tmp/tg-bot.service /etc/systemd/system/tg-bot.service",
        "mkdir -p /etc/tg-bot /var/lib/tg-bot",
        "install -m 600 /tmp/tg-token /etc/tg-bot/token",
    ]
    if a.chat:
        steps += [
            "printf '%s\\n' '%s' > /etc/tg-bot/chat_id" % ("%s", a.chat),
            "chmod 600 /etc/tg-bot/chat_id",
        ]
    steps += [
        "echo %d > /etc/tg-bot/auto_ghost" % (0 if a.no_auto else 1),
    ]
    if cookie:
        steps.append("install -m 600 /tmp/tg-cookie /etc/tg-bot/cookie")
    if blacklist:
        steps.append("install -m 644 /tmp/tg-blacklist /etc/tg-bot/ip_blacklist")
    else:
        steps.append("touch /etc/tg-bot/ip_blacklist && chmod 644 /etc/tg-bot/ip_blacklist")
    if not a.no_base:
        steps.append(BASE_SH)
    steps += [
        "rm -f /tmp/tgbot.py /tmp/tg-bot.service /tmp/tg-token /tmp/tg-cookie "
        "/tmp/tg-blacklist /tmp/wd /tmp/wd.service /tmp/led.service "
        "/tmp/usbnet /tmp/usbnet.service",
        "systemctl daemon-reload",
        "systemctl enable tg-bot >/dev/null 2>&1",
        "systemctl restart tg-bot",
        "sleep 6",
        "echo '--- service ---'",
        "systemctl is-active tg-bot",
        "echo '--- verify ---'",
        "python3 - <<'PY'\n"
        "import importlib.machinery\n"
        "m = importlib.machinery.SourceFileLoader("
        "'tgbot', '/usr/local/bin/tg-bot.py').load_module()\n"
        "print('uuid   :', m.read_file('/etc/earnapp/uuid'))\n"
        "print('mac    :', m.read_file('/sys/class/net/wlan0/address'))\n"
        "print('pub    :', m.public_ip())\n"
        "print('auto   :', m.read_file('/etc/tg-bot/auto_ghost'))\n"
        "print('cookie :', 'yes' if m.read_file('/etc/tg-bot/cookie') else 'no')\n"
        "print('banned :', len(m.read_blacklist()))\n"
        "PY",
        "echo '--- units ---'",
        "systemctl is-enabled tg-bot openstick-wifi-watchdog.service 2>/dev/null",
        "echo '--- old bot gone? ---'",
        "systemctl is-active telegram-remote.service 2>&1 | head -1",
        "echo '--- cron ---'",
        "crontab -l 2>/dev/null | head -10",
    ]

    script = "set +e\n" + "\n".join(steps) + "\n"
    stdin, stdout, stderr = cli.exec_command("sudo -S -p '' bash -s",
                                             timeout=600)
    stdin.channel.send(a.password + "\n")
    stdin.channel.sendall(script)
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    cli.close()
    print((out + err).encode("ascii", "replace").decode())
    if not any(line.strip() == "active" for line in out.splitlines()):
        sys.exit("deploy failed: tg-bot not active")


if __name__ == "__main__":
    main()
