#!/bin/bash
# OpenStick EarnApp Telegram bot installer.
# Run on the device as root.
#
# Quick install (repo already cloned):
#   sudo bash install.sh --token 123456:ABC --cookie-file cookie.txt
#
# Quick install (direct from GitHub):
#   curl -fsSL <RAW>/install.sh -o /tmp/i.sh
#   sudo bash /tmp/i.sh --token 123456:ABC
#
# Options:
#   --token TOKEN          Telegram bot token (required, unique per node)
#   --chat ID              Telegram chat id to lock to (default 5563427435)
#   --cookie-file FILE     file with the EarnApp Cookie header
#   --blacklist-file FILE  file with banned IPs, one per line
#   --auto on|off          auto-rotate on ban (default on)
#   --no-base              skip timezone / powersave / watchdog / LEDs
#   --uninstall            remove the bot (keeps EarnApp)
#   -h, --help             show this help

set -u
RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/OWNER/REPO/main}"

TOKEN=""
CHAT="5563427435"
COOKIE_FILE=""
BLACKLIST_FILE=""
AUTO="1"
BASE="1"
UNINSTALL="0"

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "==> $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --token) TOKEN="${2:-}"; shift 2 ;;
    --chat) CHAT="${2:-}"; shift 2 ;;
    --cookie-file) COOKIE_FILE="${2:-}"; shift 2 ;;
    --blacklist-file) BLACKLIST_FILE="${2:-}"; shift 2 ;;
    --auto) AUTO="${2:-1}"; shift 2 ;;
    --no-base) BASE="0"; shift ;;
    --uninstall) UNINSTALL="1"; shift ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "run as root: sudo bash $0 ..."
command -v python3 >/dev/null || die "python3 not found"

if [ "$UNINSTALL" = "1" ]; then
  say "removing bot"
  systemctl disable --now tg-bot 2>/dev/null
  rm -f /etc/systemd/system/tg-bot.service /usr/local/bin/tg-bot.py
  rm -rf /etc/tg-bot /var/lib/tg-bot
  systemctl daemon-reload
  systemctl reset-failed tg-bot 2>/dev/null
  say "bot removed (EarnApp untouched)"
  exit 0
fi

[ -n "$TOKEN" ] || die "--token is required (create one with @BotFather)"

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/bot"
TMP=""
if [ ! -f "$SRC/tgbot.py" ]; then
  say "bot sources not found locally, downloading from GitHub"
  TMP="$(mktemp -d)"
  SRC="$TMP"
  mkdir -p "$SRC"
  for f in tgbot.py tg-bot.service openstick-wifi-watchdog \
           openstick-wifi-watchdog.service openstick-leds.service; do
    if [ -n "${GITHUB_TOKEN:-}" ]; then
      curl -fsSL -H "Authorization: token $GITHUB_TOKEN" \
        "$RAW_BASE/bot/$f" -o "$SRC/$f" || die "download failed: $f"
    else
      curl -fsSL "$RAW_BASE/bot/$f" -o "$SRC/$f" || die "download failed: $f (private repo? set GITHUB_TOKEN)"
    fi
  done
fi
trap '[ -n "$TMP" ] && rm -rf "$TMP"' EXIT

say "installing bot files"
install -m 755 "$SRC/tgbot.py" /usr/local/bin/tg-bot.py
install -m 644 "$SRC/tg-bot.service" /etc/systemd/system/tg-bot.service
mkdir -p /etc/tg-bot /var/lib/tg-bot

printf '%s\n' "$TOKEN" > /etc/tg-bot/token
printf '%s\n' "$CHAT" > /etc/tg-bot/chat_id
chmod 600 /etc/tg-bot/token /etc/tg-bot/chat_id
case "$AUTO" in
  off|0|no|false) echo 0 > /etc/tg-bot/auto_ghost ;;
  *) echo 1 > /etc/tg-bot/auto_ghost ;;
esac

if [ -n "$COOKIE_FILE" ]; then
  [ -f "$COOKIE_FILE" ] || die "cookie file not found: $COOKIE_FILE"
  install -m 600 "$COOKIE_FILE" /etc/tg-bot/cookie
fi
if [ -n "$BLACKLIST_FILE" ]; then
  [ -f "$BLACKLIST_FILE" ] || die "blacklist file not found: $BLACKLIST_FILE"
  install -m 644 "$BLACKLIST_FILE" /etc/tg-bot/ip_blacklist
fi
touch /etc/tg-bot/ip_blacklist
chmod 644 /etc/tg-bot/ip_blacklist

if [ "$BASE" = "1" ]; then
  say "base setup: timezone, powersave, watchdog, LEDs"
  timedatectl set-timezone Asia/Jakarta 2>/dev/null
  for p in $(nmcli -t -f NAME,TYPE con show 2>/dev/null | grep ':802-11-wireless$' | cut -d: -f1); do
    nmcli con modify "$p" 802-11-wireless.powersave 2 >/dev/null 2>&1
    nmcli con modify "$p" wifi.powersave 2 >/dev/null 2>&1
  done
  iw dev wlan0 set power_save off 2>/dev/null

  install -m 755 "$SRC/openstick-wifi-watchdog" /usr/local/bin/openstick-wifi-watchdog
  install -m 644 "$SRC/openstick-wifi-watchdog.service" \
    /etc/systemd/system/openstick-wifi-watchdog.service
  systemctl daemon-reload
  systemctl enable openstick-wifi-watchdog.service >/dev/null 2>&1
  systemctl restart openstick-wifi-watchdog.service

  if [ -e /sys/class/leds/green:wlan ]; then
    install -m 644 "$SRC/openstick-leds.service" \
      /etc/systemd/system/openstick-leds.service
    systemctl daemon-reload
    systemctl enable --now openstick-leds.service >/dev/null 2>&1
  fi
fi

say "starting bot"
systemctl daemon-reload
systemctl enable tg-bot >/dev/null 2>&1
systemctl restart tg-bot
sleep 6

if ! systemctl is-active --quiet tg-bot; then
  journalctl -u tg-bot -n 20 --no-pager
  die "bot failed to start"
fi

say "done"
python3 - <<'PY'
import importlib.machinery
m = importlib.machinery.SourceFileLoader("tgbot", "/usr/local/bin/tg-bot.py").load_module()
print("uuid   :", m.read_file("/etc/earnapp/uuid") or "-")
print("mac    :", m.read_file("/sys/class/net/wlan0/address") or "-")
print("pub ip :", m.public_ip() or "-")
print("auto   :", m.read_file("/etc/tg-bot/auto_ghost"))
print("cookie :", "yes" if m.read_file("/etc/tg-bot/cookie") else "no")
print("banned :", len(m.read_blacklist()))
PY
echo
echo "Bot aktif. Kirim /status di Telegram untuk tes."
