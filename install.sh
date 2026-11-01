#!/bin/bash
# OpenStick EarnApp Telegram bot installer.
# Run on the device as root.
#
# Quick install (repo already cloned):
#   sudo bash install.sh
#
# Quick install (direct from GitHub):
#   curl -fsSL <RAW>/install.sh -o /tmp/i.sh
#   sudo bash /tmp/i.sh
#
# Tanpa argumen, installer menanyakan token bot (wajib) dan cookie EarnApp.
# Setiap device HARUS punya token bot sendiri (buat di @BotFather).
#
# Options:
#   --token TOKEN          Telegram bot token (unique per node; asked if omitted)
#   --chat ID              lock bot to one chat (default: auto-lock ke chat pertama)
#   --cookie-file FILE     file with the EarnApp Cookie header
#   --blacklist-file FILE  file with banned IPs, one per line
#   --auto on|off          auto-rotate on ban (default on)
#   --no-base              skip timezone / powersave / watchdog / LEDs
#   --uninstall            remove the bot (keeps EarnApp)
#   -h, --help             show this help

set -u
RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/lukmandroidxxx/openstick-earnapp-bot/main}"

TOKEN=""
CHAT=""
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

# --- token bot: wajib, unik per device --------------------------------
prompt_read() {  # $1 = prompt; jawaban di $REPLY (bisa lewat /dev/tty)
  if [ -t 0 ]; then
    printf '%s' "$1"
    IFS= read -r REPLY
  elif [ -r /dev/tty ]; then
    printf '%s' "$1" > /dev/tty
    IFS= read -r REPLY < /dev/tty
  else
    return 1
  fi
}

valid_token() {
  # format: <bot_id>:<secret>  ->  bot_id harus angka, secret [A-Za-z0-9_-]+
  case "$1" in
    *:*) ;;
    *) return 1 ;;
  esac
  case "${1%%:*}" in
    ''|*[!0-9]*) return 1 ;;
  esac
  case "${1#*:}" in
    ''|*[!A-Za-z0-9_-]*) return 1 ;;
  esac
  return 0
}

trim_token() {
  # buang spasi/newline sisa paste
  printf '%s' "$1" | tr -d '[:space:]'
}

if [ -z "$TOKEN" ]; then
  echo
  echo "Setiap device butuh token bot Telegram sendiri."
  echo "Buat bot baru di @BotFather (/newbot), lalu tempel token-nya di sini."
  while :; do
    prompt_read "Bot token: " || die "--token is required (create one with @BotFather)"
    TOKEN="$REPLY"
    [ -n "$TOKEN" ] && break
    echo "Token tidak boleh kosong."
  done
fi

[ -n "$TOKEN" ] || die "--token is required (create one with @BotFather)"

TOKEN="$(trim_token "$TOKEN")"

if ! valid_token "$TOKEN"; then
  die "format token tidak valid: '$(printf '%s' "$TOKEN" | cut -c1-16)...' (contoh: 123456789:AAH...)"
fi

if [ -t 1 ]; then
  ME="$(curl -fsS --max-time 12 "https://api.telegram.org/bot$TOKEN/getMe" 2>/dev/null || true)"
  case "$ME" in
    *'"ok":true'*)
      BOT_USER="$(printf '%s' "$ME" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
      say "token valid: @${BOT_USER:-bot}"
      ;;
    *'"ok":false'*)
      die "token ditolak Telegram (401). Cek lagi token dari @BotFather."
      ;;
    *)
      echo "WARN: tidak bisa verifikasi token (offline?). Lanjut install."
      ;;
  esac
fi

# --- cookie EarnApp: opsional, boleh sama untuk semua node ------------
if [ -z "$COOKIE_FILE" ] && [ ! -s /etc/tg-bot/cookie ]; then
  echo
  echo "Cookie EarnApp (header 'Cookie' dari dashboard), kosongkan untuk lewati:"
  if prompt_read "Cookie: "; then
    COOKIE_LINE="$REPLY"
    if [ -n "$COOKIE_LINE" ]; then
      printf '%s\n' "$COOKIE_LINE" > /tmp/tg-cookie-prompt
      COOKIE_FILE="/tmp/tg-cookie-prompt"
    fi
  fi
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/bot"
TMP=""
if [ ! -f "$SRC/tgbot.py" ]; then
  say "bot sources not found locally, downloading from GitHub"
  TMP="$(mktemp -d)"
  SRC="$TMP"
  mkdir -p "$SRC"
  for f in tgbot.py tg-bot.service openstick-wifi-watchdog \
           openstick-wifi-watchdog.service openstick-leds.service \
           openstick-usbnet openstick-usbnet.service \
           openstick-nm-unmanaged.conf; do
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
if [ -n "$CHAT" ]; then
  printf '%s\n' "$CHAT" > /etc/tg-bot/chat_id
fi
chmod 600 /etc/tg-bot/token
[ -f /etc/tg-bot/chat_id ] && chmod 600 /etc/tg-bot/chat_id
case "$AUTO" in
  off|0|no|false) echo 0 > /etc/tg-bot/auto_ghost ;;
  *) echo 1 > /etc/tg-bot/auto_ghost ;;
esac

if [ -n "$COOKIE_FILE" ]; then
  [ -f "$COOKIE_FILE" ] || die "cookie file not found: $COOKIE_FILE"
  install -m 600 "$COOKIE_FILE" /etc/tg-bot/cookie
fi
rm -f /tmp/tg-cookie-prompt
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

  # USB RNDIS -> br0 192.168.100.1 (boot race + self-healing)
  if [ -f "$SRC/openstick-usbnet" ]; then
    install -m 755 "$SRC/openstick-usbnet" /usr/local/sbin/openstick-usbnet
    install -m 644 "$SRC/openstick-usbnet.service" \
      /etc/systemd/system/openstick-usbnet.service
    if [ -f "$SRC/openstick-nm-unmanaged.conf" ]; then
      mkdir -p /etc/NetworkManager/conf.d
      install -m 644 "$SRC/openstick-nm-unmanaged.conf" \
        /etc/NetworkManager/conf.d/99-openstick-unmanaged.conf
    fi
    systemctl daemon-reload
    systemctl enable openstick-usbnet.service >/dev/null 2>&1
    systemctl restart openstick-usbnet.service >/dev/null 2>&1
    systemctl reload-or-restart NetworkManager >/dev/null 2>&1 || true
  fi

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
print("chat   :", m.read_file("/etc/tg-bot/chat_id") or "auto-lock (kirim /start pertama kali)")
print("banned :", len(m.read_blacklist()))
PY
echo
echo "Bot aktif. Kirim /status di Telegram untuk tes."
