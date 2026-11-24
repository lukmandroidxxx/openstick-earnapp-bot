#!/bin/bash
# #JAMU WIFI ID — installer standalone (tanpa token Telegram).
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/lukmandroidxxx/openstick-earnapp-bot/main/bot/jamu-wifi-id/install.sh | sudo bash
#
# Opsi:
#   --interface IF         interface Wi-Fi (default wlan0)
#   --cookie-file FILE     cookie dashboard EarnApp (opsional, dianjurkan)
#   --whitelist-file FILE  import whitelist awal
#   --blacklist-file FILE  import blacklist awal
#   --sync-wait DETIK      tunggu check-in EarnApp sebelum cek status (default 60)
#   --max-rotate N         percobaan MAC/IP sebelum menyerah (default 10)
#   --reboot-on-ban        pakai perilaku lama: reboot setelah mengacak MAC
#   --uninstall            hapus service/script/config (database IP dipertahankan)
set -u

RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/lukmandroidxxx/openstick-earnapp-bot/main/bot/jamu-wifi-id}"
IF="wlan0"
WL="/etc/ip_whitelist.txt"
BL="/etc/ip_blacklist.txt"
COOKIE_FILE=""
SYNC_WAIT="60"
MAX_ROTATE="10"
REBOOT_ON_BAN="0"
UNINSTALL="0"

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "==> $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --interface) IF="${2:-}"; shift 2 ;;
    --cookie-file) COOKIE_FILE="${2:-}"; shift 2 ;;
    --whitelist-file) WL_SRC="${2:-}"; shift 2 ;;
    --blacklist-file) BL_SRC="${2:-}"; shift 2 ;;
    --sync-wait) SYNC_WAIT="${2:-}"; shift 2 ;;
    --max-rotate) MAX_ROTATE="${2:-}"; shift 2 ;;
    --reboot-on-ban) REBOOT_ON_BAN="1"; shift ;;
    --uninstall) UNINSTALL="1"; shift ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) die "opsi tidak dikenal: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "jalankan sebagai root: sudo bash $0 ..."

if [ "$UNINSTALL" = "1" ]; then
  say "menghapus jamu-wifi-id"
  systemctl disable --now jamu-wifi-id >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/jamu-wifi-id.service /usr/local/sbin/jamu-wifi-id \
        /etc/default/jamu-wifi-id
  rmdir /etc/jamu-wifi-id 2>/dev/null || true
  systemctl daemon-reload
  systemctl reset-failed jamu-wifi-id 2>/dev/null || true
  say "selesai. /etc/ip_whitelist.txt dan /etc/ip_blacklist.txt sengaja dipertahankan."
  exit 0
fi

for c in curl python3 nmcli; do
  command -v "$c" >/dev/null || die "$c tidak ditemukan (install paket pendukung dulu)"
done

HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo .)"
SRC="$HERE"
TMP=""
if [ ! -f "$SRC/ip_check.sh" ] || [ ! -f "$SRC/jamu-wifi-id.service" ]; then
  say "sumber lokal tidak ada, unduh dari GitHub"
  TMP="$(mktemp -d)"
  for f in ip_check.sh jamu-wifi-id.service; do
    curl -fsSL "$RAW_BASE/$f" -o "$TMP/$f" || die "gagal mengunduh $f"
  done
  SRC="$TMP"
fi
trap '[ -n "$TMP" ] && rm -rf "$TMP"' EXIT

mkdir -p /etc/jamu-wifi-id
chmod 755 /etc/jamu-wifi-id

# Cookie: dianjurkan supaya deteksi ban akurat. Tidak pernah disimpan di repo.
prompt_read() {
  if [ -t 0 ]; then
    printf '%s' "$1"; IFS= read -r REPLY
  elif [ -r /dev/tty ]; then
    printf '%s' "$1" > /dev/tty; IFS= read -r REPLY < /dev/tty
  else
    return 1
  fi
}

COOKIE_PATH="/etc/tg-bot/cookie"
if [ -n "$COOKIE_FILE" ]; then
  [ -f "$COOKIE_FILE" ] || die "cookie file tidak ditemukan: $COOKIE_FILE"
  install -m 600 "$COOKIE_FILE" /etc/jamu-wifi-id/cookie
  COOKIE_PATH="/etc/jamu-wifi-id/cookie"
elif [ ! -s "$COOKIE_PATH" ]; then
  echo
  echo "Cookie dashboard EarnApp (opsional, tapi dianjurkan)."
  echo "Ambil dari F12 -> Network -> /api/session -> header Cookie."
  echo "Kosongkan kalau belum ada; filter tetap jalan dengan akurasi lebih rendah."
  if prompt_read "Cookie EarnApp: "; then
    if [ -n "$REPLY" ]; then
      printf '%s\n' "$REPLY" > /etc/jamu-wifi-id/cookie
      chmod 600 /etc/jamu-wifi-id/cookie
      COOKIE_PATH="/etc/jamu-wifi-id/cookie"
    fi
  fi
fi

# Database IP: jangan pernah menimpa yang sudah ada kecuali user import.
if [ -n "${WL_SRC:-}" ]; then
  [ -f "$WL_SRC" ] || die "whitelist file tidak ditemukan: $WL_SRC"
  install -m 644 "$WL_SRC" "$WL"
else
  [ -f "$WL" ] || { : > "$WL"; chmod 644 "$WL"; }
fi
if [ -n "${BL_SRC:-}" ]; then
  [ -f "$BL_SRC" ] || die "blacklist file tidak ditemukan: $BL_SRC"
  install -m 644 "$BL_SRC" "$BL"
else
  [ -f "$BL" ] || { : > "$BL"; chmod 644 "$BL"; }
fi

say "memasang script dan service"
install -m 755 "$SRC/ip_check.sh" /usr/local/sbin/jamu-wifi-id
install -m 644 "$SRC/jamu-wifi-id.service" /etc/systemd/system/jamu-wifi-id.service
cat > /etc/default/jamu-wifi-id <<EOF
IF="$IF"
WL="$WL"
BL="$BL"
COOKIE="$COOKIE_PATH"
SYNC_WAIT="$SYNC_WAIT"
MAX_ROTATE="$MAX_ROTATE"
REBOOT_ON_BAN="$REBOOT_ON_BAN"
EOF
chmod 644 /etc/default/jamu-wifi-id

systemctl daemon-reload
systemctl enable jamu-wifi-id >/dev/null 2>&1 || true
systemctl restart jamu-wifi-id

sleep 3
if ! systemctl is-active --quiet jamu-wifi-id; then
  journalctl -u jamu-wifi-id -n 20 --no-pager || true
  die "service gagal start"
fi

say "selesai"
echo "interface : $IF"
echo "whitelist : $WL ($(grep -c . "$WL" 2>/dev/null || echo 0) baris)"
echo "blacklist : $BL ($(grep -c . "$BL" 2>/dev/null || echo 0) baris)"
echo "cookie    : $([ -s "$COOKIE_PATH" ] && echo ada || echo tidak ada)"
echo "ip publik : $(curl -4 -s -m 8 https://api.ipify.org || echo '-')"
echo
echo "Pantau: journalctl -u jamu-wifi-id -f -n 50"
