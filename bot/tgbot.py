#!/usr/bin/env python3
"""OpenStick Telegram control bot - stdlib only."""
import html
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

BOT_DIR = "/etc/tg-bot"
STATE_DIR = "/var/lib/tg-bot"
TOKEN_FILE = os.path.join(BOT_DIR, "token")
CHAT_FILE = os.path.join(BOT_DIR, "chat_id")
COOKIE_FILE = os.path.join(BOT_DIR, "cookie")
OFFSET_FILE = os.path.join(STATE_DIR, "offset")
BLACKLIST_FILE = os.path.join(BOT_DIR, "ip_blacklist")
AUTO_FILE = os.path.join(BOT_DIR, "auto_ghost")
NODES_FILE = os.path.join(BOT_DIR, "nodes")
SSH_KEY = "/root/.ssh/id_master"
EARN_FILE = os.path.join(STATE_DIR, "earnings_daily.json")
PAYOUT_EMAIL_FILE = os.path.join(BOT_DIR, "payout_email")
NOTIF_FILE = os.path.join(BOT_DIR, "daily_notify")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MENU = {"inline_keyboard": [
    [{"text": "\U0001F4CA Status", "callback_data": "status"},
     {"text": "\U0001F4B0 Dashboard", "callback_data": "dash"}],
    [{"text": "\U0001F4C8 Report", "callback_data": "report"},
     {"text": "\U0001F4B8 Tarik Saldo", "callback_data": "wd_menu"}],
    [{"text": "\U0001F504 Reboot", "callback_data": "reboot"},
     {"text": "\U0001F47B Ghost MAC", "callback_data": "ghost"}],
    [{"text": "\u23FB Matikan (poweroff)", "callback_data": "off"}],
]}

CONFIRM_REBOOT = {"inline_keyboard": [[
    {"text": "\u2705 Ya, reboot", "callback_data": "do_reboot"},
    {"text": "\u274C Batal", "callback_data": "cancel"}]]}

CONFIRM_OFF = {"inline_keyboard": [[
    {"text": "\u2705 Ya, matikan", "callback_data": "do_off"},
    {"text": "\u274C Batal", "callback_data": "cancel"}]]}

CONFIRM_GHOST = {"inline_keyboard": [[
    {"text": "\u2705 Ya, ganti MAC + IP", "callback_data": "do_ghost"},
    {"text": "\u274C Batal", "callback_data": "cancel"}]]}


# ---------------------------------------------------------------- utilities
def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def write_file(path, data, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data)
    try:
        os.chmod(path, mode)
    except Exception:
        pass


def sh(cmd, timeout=25):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return out.strip()
    except subprocess.TimeoutExpired:
        return "(timeout)"
    except Exception as exc:  # noqa: BLE001
        return "(error: %s)" % exc


def http_get(url, headers=None, timeout=12):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- telegram
TOKEN = read_file(TOKEN_FILE)


def api(method, timeout=65, **params):
    url = "https://api.telegram.org/bot%s/%s" % (TOKEN, method)
    data = json.dumps(params).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def send(chat_id, text, keyboard=None, reply_to=None):
    kw = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
          "disable_web_page_preview": True}
    if keyboard:
        kw["reply_markup"] = keyboard
    if reply_to:
        kw["reply_to_message_id"] = reply_to
    try:
        api("sendMessage", **kw)
    except Exception as exc:  # noqa: BLE001
        log("send failed:", exc)


def edit(chat_id, message_id, text):
    try:
        api("editMessageText", chat_id=chat_id, message_id=message_id,
            text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001
        log("edit failed:", exc)


def answer_cb(cb_id, text=""):
    try:
        api("answerCallbackQuery", callback_query_id=cb_id, text=text)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- status
def public_ip():
    for url in ("https://api.ipify.org", "https://ifconfig.co/ip",
                "https://ipinfo.io/ip"):
        try:
            _st, body = http_get(url, timeout=8)
            ip = body.strip()
            if re.match(r"^[0-9a-fA-F:.]{6,45}$", ip):
                return ip
        except Exception:  # noqa: BLE001
            continue
    return None


def ip_geo(ip):
    try:
        _st, body = http_get("https://ipinfo.io/%s/json" % ip, timeout=8)
        d = json.loads(body)
        bits = [d.get("city"), d.get("region"), d.get("country")]
        place = ", ".join([b for b in bits if b])
        org = d.get("org") or ""
        return place, org
    except Exception:  # noqa: BLE001
        return "", ""


def earnapp_status():
    raw = sh("/usr/bin/earnapp status 2>&1 | tail -2", timeout=30)
    m = re.search(r"(enabled|disabled|registered|unregistered|not registered)",
                  raw, re.I)
    return m.group(1).lower() if m else (raw.splitlines()[-1] if raw else "?")


def status_text():
    ip = public_ip()
    place, org = ip_geo(ip) if ip else ("", "")
    ssid = sh("nmcli -t -f active,ssid dev wifi 2>/dev/null | "
              "awk -F: '$1==\"yes\"{print $2; exit}'")
    wip = sh("ip -4 -br addr show wlan0 2>/dev/null | awk '{print $3}'")
    mac = read_file("/sys/class/net/wlan0/address")
    ea = earnapp_status()
    ea_svc = sh("systemctl is-active earnapp").strip()
    up = sh("uptime -p").replace("up ", "")
    mem = sh("free -m | awk '/Mem:/{printf \"%d/%d MB\", $3, $2}'")
    disk = sh("df -h / | awk 'NR==2{printf \"%s/%s (%s)\", $3, $2, $5}'")
    load = sh("cut -d' ' -f1-3 /proc/loadavg")
    rx = int(sh("cat /sys/class/net/wlan0/statistics/rx_bytes") or 0)
    tx = int(sh("cat /sys/class/net/wlan0/statistics/tx_bytes") or 0)

    def human(n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return "%.1f %s" % (n, unit)
            n /= 1024.0
        return "%.1f TB" % n

    traffic = "\u2193 %s \u00b7 \u2191 %s" % (human(rx), human(tx))

    ip_line = html.escape(ip) if ip else "\u26A0\uFE0F gagal"
    if org or place:
        ip_line += "\n     <i>%s</i>" % html.escape(" \u00b7 ".join(
            [x for x in (org, place) if x]))

    return (
        "\U0001F4CA <b>STATUS OPENSTICK</b>\n\n"
        "\U0001F310 <b>IP publik</b>: <code>%s</code>\n"
        "\U0001F4F6 <b>Wi-Fi</b>: %s\n"
        "     <code>%s</code> \u00b7 MAC <code>%s</code>\n"
        "\U0001F4B0 <b>EarnApp</b>: <b>%s</b> (service %s)\n"
        "\u23F1 <b>Uptime</b>: %s\n"
        "\U0001F4E1 <b>Traffic Wi-Fi</b>: %s\n"
        "\U0001F9E0 <b>RAM</b>: %s \u00b7 <b>Disk</b>: %s\n"
        "\U0001F4C8 <b>Load</b>: %s"
    ) % (ip_line, html.escape(ssid or "-"), html.escape(wip or "-"),
         html.escape(mac or "-"), html.escape(ea), html.escape(ea_svc),
         html.escape(up or "-"), html.escape(traffic), html.escape(mem),
         html.escape(disk), html.escape(load))


# ---------------------------------------------------------------- dashboard
def cookie_get(name):
    for part in read_file(COOKIE_FILE).split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return ""


def cookie_set(name, value):
    parts = [p.strip() for p in read_file(COOKIE_FILE).split(";") if p.strip()]
    out = []
    found = False
    for p in parts:
        k, _, _v = p.partition("=")
        if k == name:
            out.append("%s=%s" % (name, value))
            found = True
        else:
            out.append(p)
    if not found:
        out.append("%s=%s" % (name, value))
    write_file(COOKIE_FILE, "; ".join(out))


def refresh_xsrf():
    req = urllib.request.Request(
        "https://earnapp.com/dashboard/api/sec/rotate_xsrf",
        headers={"Cookie": read_file(COOKIE_FILE), "User-Agent": UA,
                 "Accept": "application/json",
                 "Referer": "https://earnapp.com/dashboard"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            for sc in r.headers.get_all("Set-Cookie") or []:
                m = re.search(r"xsrf-token=([^;]+)", sc)
                if m:
                    cookie_set("xsrf-token", m.group(1))
                    return True
    except Exception:  # noqa: BLE001
        pass
    return False


def ea_api(path, method="GET", payload=None, _retry=True):
    headers = {"Cookie": read_file(COOKIE_FILE), "User-Agent": UA,
               "Accept": "application/json",
               "Referer": "https://earnapp.com/dashboard",
               "X-Requested-With": "XMLHttpRequest"}
    data = None
    if method != "GET":
        headers["Content-Type"] = "application/json"
        headers["xsrf-token"] = cookie_get("xsrf-token")
        data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        "https://earnapp.com/dashboard" + path, data=data,
        headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:200]
        if _retry and method != "GET" and "CSRF" in body:
            if refresh_xsrf():
                return ea_api(path, method, payload, _retry=False)
        return exc.code, body
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def _pick(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def fmt_money(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if v == 0:
        return "$0"
    if abs(v) < 0.1:
        return "$%.3f" % v
    return "$%.2f" % v


def fmt_uptime(ms):
    try:
        ms = int(ms or 0)
    except (TypeError, ValueError):
        ms = 0
    sec = ms // 1000
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m = sec // 60
    if d:
        return "%dd %dh" % (d, h)
    if h:
        return "%dh %dm" % (h, m)
    return "%dm" % m


# live online state: uuid -> {"uptime", "ts", "online", "data"}
DEV_STATE = {}
LIVE = {}  # uuid -> live session uptime (ms) from POST /api/device_statuses
HEALTH = {"last_uptime": None, "stagnant": 0, "ever_grew": False}
NOTIFIED_BANS = set()
MY_PREV = {"banned": None, "ip": None}
LAST_ROTATE = {"ts": 0.0}


def notify_transition(my):
    """Kabari saat device pulih (unban / IP publik berubah)."""
    chat = read_file(CHAT_FILE)
    if not chat:
        return
    ban = my.get("banned")
    ban = ban if isinstance(ban, dict) else None
    ip = None
    if ban and ban.get("ip"):
        ip = str(ban["ip"])
    elif isinstance(my.get("ips"), list) and my["ips"]:
        ip = str(my["ips"][0])

    prev_banned = MY_PREV.get("banned")
    prev_ip = MY_PREV.get("ip")

    if prev_banned is True and ban is None:
        send(chat,
             "\U0001F7E2 <b>DEVICE PULIH \u2014 BAN LEPAS</b>\n\n"
             "IP publik sekarang: <code>%s</code>\n"
             "Uptime EarnApp mulai dihitung lagi.\n\n"
             "Cek /dash untuk memastikan status hijau." %
             html.escape(ip or "?"))
    elif ban is None and prev_ip and ip and ip != prev_ip:
        send(chat,
             "\U0001F310 <b>IP publik berubah</b>\n\n"
             "<code>%s</code> \u2192 <code>%s</code>\n"
             "Cek /dash apakah device sudah hijau." %
             (html.escape(prev_ip), html.escape(ip)))

    MY_PREV["banned"] = ban is not None
    if ip:
        MY_PREV["ip"] = ip


def read_blacklist():
    return [x.strip() for x in read_file(BLACKLIST_FILE).splitlines() if x.strip()]


def add_blacklist(ip):
    ip = (ip or "").strip()
    if not ip:
        return False
    items = read_blacklist()
    if ip in items:
        return False
    items.append(ip)
    write_file(BLACKLIST_FILE, "\n".join(items) + "\n", 0o644)
    log("blacklist +", ip)
    return True


def load_notified_bans():
    try:
        return set(json.loads(read_file(os.path.join(STATE_DIR, "notified_bans.json")) or "[]"))
    except Exception:  # noqa: BLE001
        return set()


def save_notified_bans():
    try:
        write_file(os.path.join(STATE_DIR, "notified_bans.json"),
                   json.dumps(sorted(NOTIFIED_BANS)), 0o644)
    except Exception:  # noqa: BLE001
        pass


def trigger_ghost(reason_ip=None):
    chat = read_file(CHAT_FILE)
    if reason_ip:
        add_blacklist(reason_ip)
    ok, msg, old_ip, new_ip, mac = rotate_ip(3)
    if ok:
        send(chat,
             "\U0001F47B <b>IP PUBLIK DIGANTI (tanpa reboot)</b>\n\n"
             "%s\nMAC: <code>%s</code>\n\n"
             "Device tidak di-reboot \u2014 uptime tetap terjaga." %
             (html.escape(msg), html.escape(mac)))
        st, dev = ea_api("/api/devices")
        my = None
        if st == 200 and isinstance(dev, list):
            my = next((d for d in dev if isinstance(d, dict) and
                       d.get("uuid") == read_file("/etc/earnapp/uuid")), None)
        if my is not None and not my.get("banned"):
            send(chat, "\U0001F7E2 <b>Status: HIJAU</b> \u2014 ban sudah lepas, "
                       "uptime mulai dihitung.")
    else:
        send(chat,
             "\u26A0\uFE0F <b>Ganti IP gagal</b>\n\n%s\n\n"
             "Auto-rotate berhenti agar tidak loop. Cek Wi-Fi / router." %
             html.escape(msg))
    return ok


def handle_health(my, now):
    """Ban alert + uptime stagnation watchdog."""
    up = int(my.get("uptime") or 0)
    ban = my.get("banned")
    chat = read_file(CHAT_FILE)

    if isinstance(ban, dict) and ban.get("ip"):
        ip = str(ban["ip"])
        reason = str(ban.get("reason") or "banned")
        if ip not in NOTIFIED_BANS:
            NOTIFIED_BANS.add(ip)
            save_notified_bans()
            send(chat,
                 "\U0001F6AB <b>DEVICE DIBLOKIR EARNAPP</b>\n\n"
                 "Device: <b>%s</b>\nAlasan: <code>%s</code>\n"
                 "IP: <code>%s</code>\n\n"
                 "Selama ban aktif, uptime tidak dihitung \u2192 earning berhenti.\n\n"
                 "<b>Yang bisa dilakukan:</b>\n"
                 "\u2022 Tombol <b>Ganti IP sekarang</b> \u2014 MAC diacak + "
                 "reconnect 15 dtk, tanpa reboot\n"
                 "\u2022 Atau restart modem/router\n\n"
                 "IP ini sudah dicatat ke blacklist."
                 "%s"
                 % (html.escape(str(my.get("title") or my.get("uuid"))),
                    html.escape(reason), html.escape(ip),
                    ("\n\n\u2705 Auto-rotate <b>ON</b>: IP akan diganti "
                     "otomatis." if read_file(AUTO_FILE) == "1" else
                     "\n\n\u26A0\uFE0F Auto-rotate OFF. Aktifkan: "
                     "<code>/auto on</code>")),
                 {"inline_keyboard": [[
                     {"text": "\U0001F47B Ganti IP sekarang", "callback_data": "ghost"},
                     {"text": "\U0001F504 Cek lagi", "callback_data": "dash"}]]})
            if read_file(AUTO_FILE) == "1":
                cur = public_ip()
                if cur and cur != ip:
                    log("auto-ghost: IP sudah beda dari ban", cur)
                elif time.time() - LAST_ROTATE["ts"] < 600:
                    log("auto-ghost: cooldown")
                else:
                    LAST_ROTATE["ts"] = time.time()
                    log("auto-ghost for banned ip", ip)
                    trigger_ghost(ip)
        return

    prev = HEALTH.get("last_uptime")
    if prev is not None and up > prev:
        HEALTH["stagnant"] = 0
        HEALTH["ever_grew"] = True
    elif prev is not None:
        HEALTH["stagnant"] += 1
    HEALTH["last_uptime"] = up

    # 15 x 120s = 30 menit uptime tidak bertambah -> restart earnapp
    # (hanya kalau node pernah benar-benar menghasilkan uptime)
    if HEALTH["ever_grew"] and HEALTH["stagnant"] >= 15:
        HEALTH["stagnant"] = 0
        sh("systemctl restart earnapp")
        send(chat, "\u26A0\uFE0F <b>Uptime tidak naik 30 menit</b>\n"
                   "EarnApp di-restart otomatis. Cek /dash beberapa saat lagi.")


def poll_devices():
    global NOTIFIED_BANS
    NOTIFIED_BANS = load_notified_bans()
    my_uuid = read_file("/etc/earnapp/uuid")
    while True:
        try:
            if read_file(COOKIE_FILE):
                st, dev = ea_api("/api/devices")
                if st == 200 and isinstance(dev, list):
                    now = time.time()
                    uuids = [d.get("uuid") for d in dev
                             if isinstance(d, dict) and d.get("uuid")]
                    st2, sts = ea_api(
                        "/api/device_statuses", "POST",
                        {"data": {"devices": uuids}})
                    have_live = st2 == 200 and isinstance(sts, dict)
                    if have_live:
                        LIVE.clear()
                        for u, v in sts.items():
                            try:
                                LIVE[u] = (int(v[1]) if isinstance(v, list)
                                           and len(v) > 1 else 0)
                            except (TypeError, ValueError):
                                LIVE[u] = 0
                    else:
                        log("device_statuses failed", st2, str(sts)[:120])
                    started = False
                    for d in dev:
                        if not isinstance(d, dict):
                            continue
                        b = d.get("banned")
                        if isinstance(b, dict) and b.get("ip"):
                            add_blacklist(b["ip"])
                        u = d.get("uuid")
                        if not u:
                            continue
                        try:
                            up = int(d.get("uptime") or 0)
                        except (TypeError, ValueError):
                            up = 0
                        prev = DEV_STATE.get(u)
                        if have_live:
                            online = u in LIVE
                        else:
                            online = bool(prev is not None and
                                          now - prev["ts"] > 30 and
                                          up > prev["uptime"])
                        if u == my_uuid and prev is not None and \
                                not prev["online"] and online:
                            started = True
                        DEV_STATE[u] = {"uptime": up, "ts": now,
                                        "online": online, "data": d}
                    try:
                        devs = [d for d in dev if isinstance(d, dict)]
                        estate, _erows, etotal = earn_state(devs)
                        daily_notify(read_file(CHAT_FILE), estate, etotal)
                    except Exception as exc:  # noqa: BLE001
                        log("earn track:", exc)
                    my = next((d for d in dev if isinstance(d, dict) and
                               d.get("uuid") == my_uuid), None)
                    if my:
                        handle_health(my, now)
                        notify_transition(my)
                        if started:
                            send(read_file(CHAT_FILE),
                                 "\U0001F7E2 <b>NODE ONLINE \u2014 HIJAU</b>\n\n"
                                 "Live uptime: <b>%s</b>\n"
                                 "Earning berjalan. Biarkan device menyala "
                                 "terus." % fmt_uptime(
                                     LIVE.get(my_uuid) or 0))
        except Exception as exc:  # noqa: BLE001
            log("poll devices:", exc)
        time.sleep(120)


def dash_text():
    if not read_file(COOKIE_FILE):
        return ("\U0001F4B0 <b>Dashboard EarnApp</b>\n\n"
                "Belum ada cookie sesi.\n\n"
                "Cara set:\n"
                "1. Login <code>earnapp.com/dashboard</code> di browser\n"
                "2. F12 \u2192 Network \u2192 klik request <code>/api/session</code>\n"
                "3. Salin header <code>Cookie</code> lengkap\n"
                "4. Kirim ke bot:\n"
                "<code>/setcookie nama=value; nama2=value2</code>")
    st, sess = ea_api("/api/session")
    if st != 200:
        return ("\u26A0\uFE0F Session gagal (HTTP %s).\n"
                "Kirim ulang cookie: <code>/setcookie ...</code>" % st)
    if isinstance(sess, dict) and sess.get("authenticated") is False:
        return ("\u26A0\uFE0F Cookie tidak valid / kadaluarsa.\n"
                "Login ulang di browser lalu kirim <code>/setcookie ...</code>")

    st, dev = ea_api("/api/devices")
    if st != 200 or not isinstance(dev, list):
        return "\u26A0\uFE0F Gagal ambil daftar device (HTTP %s)." % st

    # status online real-time (sumber titik hijau di web)
    uuids = [d.get("uuid") for d in dev
             if isinstance(d, dict) and d.get("uuid")]
    st2, sts = ea_api("/api/device_statuses", "POST",
                      {"data": {"devices": uuids}})
    if st2 == 200 and isinstance(sts, dict):
        LIVE.clear()
        for u, v in sts.items():
            try:
                LIVE[u] = (int(v[1]) if isinstance(v, list) and len(v) > 1
                           else 0)
            except (TypeError, ValueError):
                LIVE[u] = 0

    st, money = ea_api("/api/money")
    money = money if (st == 200 and isinstance(money, dict)) else {}
    st, user = ea_api("/api/user_data")
    user = user if (st == 200 and isinstance(user, dict)) else {}

    my_uuid = read_file("/etc/earnapp/uuid")
    online_n = sum(1 for d in dev if isinstance(d, dict) and
                   d.get("uuid") in LIVE)
    banned_n = sum(1 for d in dev if isinstance(d, dict) and d.get("banned"))

    lines = ["\U0001F4B0 <b>DASHBOARD EARNAPP</b>"]
    if user.get("name") or user.get("email"):
        lines.append("\U0001F464 %s" % html.escape(
            str(user.get("name") or user.get("email"))))
    if money:
        lines.append("\U0001F4B5 Saldo <b>%s</b> \u00b7 total %s" % (
            fmt_money(money.get("balance")),
            fmt_money(money.get("earnings_total"))))

    mine = [d for d in dev if isinstance(d, dict) and d.get("uuid") == my_uuid]
    if mine:
        d = mine[0]
        icon = "\u26D4" if d.get("banned") else (
            "\U0001F7E2" if my_uuid in LIVE else "\u26AA")
        lines.append("\n\U0001F4F1 <b>DEVICE INI</b> \u00b7 %s" % icon)
        lines.append("   %s" % html.escape(str(d.get("title") or my_uuid)))
        if d.get("banned"):
            b = d.get("banned") or {}
            lines.append("   \u26D4 <b>BANNED</b>: %s%s" % (
                html.escape(str(b.get("reason") or "?")),
                (" \u00b7 " + html.escape(str(b.get("ip")))) if b.get("ip") else ""))
        live_up = LIVE.get(my_uuid)
        lines.append("   live %s \u00b7 qualified %s \u00b7 %s (total %s)" % (
            fmt_uptime(live_up) if live_up is not None else "-",
            fmt_uptime(d.get("uptime")), fmt_money(d.get("earned")),
            fmt_money(d.get("earned_total"))))
        if d.get("ips"):
            lines.append("   IP: <code>%s</code>" % html.escape(
                ", ".join(str(x) for x in d["ips"][:3])))
    else:
        lines.append("\n\u26A0\uFE0F Device ini belum tertaut ke akun.")

    lines.append("\n\U0001F4CA <b>%d device</b> \u00b7 \U0001F7E2 %d online "
                 "\u00b7 \u26D4 %d banned" % (len(dev), online_n, banned_n))

    others = [d for d in dev if isinstance(d, dict) and d.get("uuid") != my_uuid]
    others.sort(key=lambda x: float(x.get("earned") or 0), reverse=True)
    for d in others[:10]:
        u = d.get("uuid")
        icon = "\u26D4" if d.get("banned") else (
            "\U0001F7E2" if u in LIVE else "\u26AA")
        extra = ""
        if d.get("banned"):
            extra = " \u00b7 %s" % html.escape(
                str((d.get("banned") or {}).get("reason") or "banned"))
        if u in LIVE:
            up_txt = "live %s" % fmt_uptime(LIVE.get(u))
        else:
            up_txt = fmt_uptime(d.get("uptime"))
        lines.append("%s %s \u00b7 %s \u00b7 %s%s" % (
            icon, html.escape(str(d.get("title") or u)),
            fmt_money(d.get("earned")), up_txt, extra))
    if len(others) > 10:
        lines.append("\u2026 dan %d device lain" % (len(others) - 10))

    if money:
        rd = money.get("redeem_details") or {}
        if rd.get("min_redeem") is not None:
            lines.append("\n\U0001F3AF Min redeem: %s" %
                         fmt_money(rd.get("min_redeem")))
    return "\n".join(lines)


# ---------------------------------------------------------------- actions
OUIS = ["00:1B:63", "00:1E:C2", "00:23:12", "3C:5A:B4", "40:B0:76",
        "54:26:96", "6C:40:08", "7C:7A:91", "84:16:F9", "A4:50:46",
        "B4:6B:FC", "C8:3A:35", "D8:96:95", "E4:5F:01", "F4:8C:50"]


def random_mac():
    oui = random.choice(OUIS)
    return oui + ":%02X:%02X:%02X" % tuple(random.randint(0, 255) for _ in range(3))


def wifi_profile():
    out = sh("nmcli -t -f NAME,TYPE con show --active 2>/dev/null")
    for line in out.splitlines():
        parts = line.rsplit(":", 1)
        if len(parts) == 2 and parts[1] == "802-11-wireless":
            return parts[0]
    out = sh("nmcli -t -f NAME,TYPE con show 2>/dev/null")
    for line in out.splitlines():
        parts = line.rsplit(":", 1)
        if len(parts) == 2 and parts[1] == "802-11-wireless":
            return parts[0]
    return ""


def rotate_ip(attempts=3):
    """Ganti MAC Wi-Fi + reconnect (tanpa reboot) sampai IP publik berubah.

    Return (ok, msg, old_ip, new_ip, mac).
    """
    prof = wifi_profile()
    if not prof:
        return False, "Profil Wi-Fi tidak ditemukan.", None, None, None
    esc = prof.replace('"', '\\"')
    old_mac = read_file("/sys/class/net/wlan0/address") or "?"
    old_cfg = sh('nmcli -g 802-11-wireless.cloned-mac-address con show "%s"'
                 % esc).strip()
    old_ip = public_ip()
    banned = set(read_blacklist())
    last_mac = old_mac
    last_ip = old_ip
    skipped = []

    for n in range(1, attempts + 1):
        mac = random_mac()
        last_mac = mac
        log("rotate try", n, mac, "old_ip", old_ip)
        sh('nmcli con modify "%s" 802-11-wireless.cloned-mac-address %s'
           % (esc, mac))
        sh('nmcli con modify "%s" wifi.cloned-mac-address %s' % (esc, mac))
        sh('nmcli con down "%s"' % esc, timeout=40)
        time.sleep(15)
        sh('nmcli con up "%s"' % esc, timeout=40)
        for _ in range(20):
            time.sleep(3)
            if sh("ip -4 -o addr show wlan0 2>/dev/null | "
                  "awk '{print $4}'").strip():
                break
        time.sleep(3)
        new_ip = public_ip()
        banned = set(read_blacklist())  # refresh: poll lain bisa menambah
        if new_ip:
            last_ip = new_ip
        if new_ip and new_ip != old_ip:
            if new_ip in banned:
                if new_ip not in skipped:
                    skipped.append(new_ip)
                log("rotate: skip blacklisted IP", new_ip)
                continue
            log("rotate ok", old_ip, "->", new_ip)
            return (True, "IP publik: %s \u2192 %s" % (old_ip or "?", new_ip),
                    old_ip, new_ip, mac)
        if not new_ip:
            log("rotate: no internet on attempt", n)

    # Semua percobaan gagal. Jangan pernah kembali ke IP yang ada di
    # blacklist: kalau IP lama banned, pertahankan MAC terakhir.
    if old_ip and old_ip in banned:
        log("rotate: old IP blacklisted, keep last MAC", last_mac)
        sh('nmcli con up "%s"' % esc, timeout=40)
        extra = (" IP blacklist yang dilewati: %s." % ", ".join(skipped)
                 if skipped else "")
        return (False, "IP lama %s ada di blacklist, jadi tidak dikembalikan."
                "%s MAC terakhir dipertahankan \u2014 coba /ghost lagi nanti."
                % (old_ip, extra), old_ip, last_ip, last_mac)

    restore = old_cfg if old_cfg not in ("", "--", "default") else old_mac
    log("rotate restore", restore)
    sh('nmcli con modify "%s" 802-11-wireless.cloned-mac-address %s'
       % (esc, restore))
    sh('nmcli con down "%s"' % esc, timeout=40)
    time.sleep(5)
    sh('nmcli con up "%s"' % esc, timeout=40)
    time.sleep(10)
    cur = public_ip()
    if cur:
        return (False, "IP publik tetap %s setelah %d percobaan. "
                "MAC dikembalikan." % (cur, attempts), old_ip, cur, old_mac)
    return (False, "Tidak dapat internet setelah %d percobaan. "
            "MAC dikembalikan \u2014 cek Wi-Fi/router." % attempts,
            old_ip, None, old_mac)


def do_ghost():
    return rotate_ip(3)


def my_device():
    st, dev = ea_api("/api/devices")
    if st == 200 and isinstance(dev, list):
        u = read_file("/etc/earnapp/uuid")
        return next((d for d in dev if isinstance(d, dict) and
                     d.get("uuid") == u), None)
    return None


def _rotate_job(chat_id, mid):
    ok, msg, old_ip, new_ip, mac = rotate_ip(3)
    if ok:
        text = ("\u2705 <b>IP PUBLIK BERUBAH</b>\n\n%s\n"
                "MAC: <code>%s</code>\n\n" % (html.escape(msg),
                                              html.escape(mac)))
        d = my_device()
        if d is not None and not d.get("banned"):
            text += "\U0001F7E2 <b>Status: HIJAU</b> \u2014 ban lepas, " \
                    "uptime mulai dihitung."
        else:
            text += "\u23F3 Cek /dash beberapa menit lagi untuk status hijau."
        edit(chat_id, mid, text)
    else:
        edit(chat_id, mid, "\u26A0\uFE0F <b>Ganti IP gagal</b>\n\n%s" %
             html.escape(msg))


def reboot_now():
    subprocess.Popen("sync; sleep 1; systemctl reboot", shell=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def poweroff_now():
    # sync dulu supaya eMMC aman, lalu matikan total.
    # Device hanya bisa hidup lagi dengan mencabut/menyambung daya.
    subprocess.Popen("sync; sleep 1; systemctl poweroff", shell=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ------------------------------------------------------------ multi-node
# /etc/tg-bot/nodes: satu node per baris -> "nama ip_tailscale [uuid]"
# Contoh:
#   semut06 100.81.199.122 sdk-node-04eb3a051e2d4d1996240f7d11728a16
NODE_CHECK = ('printf "%s|" "$(hostname)" '
              '"$(curl -s -m 8 https://api.ipify.org)" '
              '"$(systemctl is-active earnapp 2>&1)" '
              '"$(systemctl is-active tg-bot 2>&1)"')


def read_nodes():
    nodes = []
    for line in read_file(NODES_FILE).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = line.split()
        if len(p) >= 2:
            nodes.append({"name": p[0], "ip": p[1],
                          "uuid": p[2] if len(p) > 2 else ""})
    return nodes


def node_by_name(name):
    for n in read_nodes():
        if n["name"].lower() == name.lower():
            return n
    return None


def remote(ip, cmd, timeout=60):
    argv = ["ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=8", "-i", SSH_KEY, "root@" + ip, cmd]
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 1, "", "(timeout)"
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


def run_on(node, cmd, timeout=90):
    if node["name"].lower() == sh("hostname").lower():
        return 0, sh(cmd, timeout=timeout), ""
    return remote(node["ip"], cmd, timeout=timeout)


def all_text():
    nodes = read_nodes()
    if not nodes:
        return ("\U0001F310 <b>Multi-node</b>\n\n"
                "Belum ada daftar node.\n"
                "Isi <code>/etc/tg-bot/nodes</code>:\n"
                "<code>semut06 100.81.199.122 sdk-node-04eb...</code>")

    devs, live = {}, {}
    if read_file(COOKIE_FILE):
        st, dev = ea_api("/api/devices")
        if st == 200 and isinstance(dev, list):
            uuids = [d.get("uuid") for d in dev
                     if isinstance(d, dict) and d.get("uuid")]
            st2, sts = ea_api("/api/device_statuses", "POST",
                              {"data": {"devices": uuids}})
            if st2 == 200 and isinstance(sts, dict):
                for u, v in sts.items():
                    try:
                        live[u] = int(v[1]) if isinstance(v, list) and \
                            len(v) > 1 else 0
                    except (TypeError, ValueError):
                        live[u] = 0
            for d in dev:
                if isinstance(d, dict):
                    devs[d.get("uuid")] = d

    results = {}

    def work(n):
        results[n["name"]] = run_on(n, NODE_CHECK, timeout=35)

    threads = [threading.Thread(target=work, args=(n,), daemon=True)
               for n in nodes]
    for t in threads:
        t.start()
    deadline = time.time() + 40
    for t in threads:
        t.join(max(0.1, deadline - time.time()))

    lines = ["\U0001F310 <b>NODE LIST</b> (%d)\n" % len(nodes)]
    green = 0
    for n in nodes:
        res = results.get(n["name"])
        if not res:
            lines.append("\u26AA <b>%s</b> \u2014 no reply" % n["name"])
            continue
        _, out, err = res
        f = out.strip().split("|")
        host = (f[0].strip() if f and f[0].strip() else n["name"])
        ip = f[1].strip() if len(f) > 1 and f[1].strip() else "?"
        ea = f[2].strip() if len(f) > 2 else ""
        active = ea == "active"
        d = devs.get(n["uuid"]) if n["uuid"] else None
        ban = d.get("banned") if isinstance(d, dict) else None
        live_ms = live.get(n["uuid"], 0) if n["uuid"] else 0
        if not active:
            mark = "\U0001F534"
        elif isinstance(ban, dict):
            mark = "\U0001F6AB"
            green += 0
        else:
            mark = "\U0001F7E2"
            if n["uuid"] and live_ms > 0:
                green += 1
        extra = []
        if n["uuid"]:
            extra.append("hijau %s" % fmt_uptime(live_ms) if live_ms
                         else "belum hijau")
            if isinstance(ban, dict):
                extra.append("BANNED %s" % ban.get("ip", "?"))
        lines.append("%s <b>%s</b> <code>%s</code>\n   ip <code>%s</code>"
                     " \u00b7 %s%s" % (
                         mark, host, n["ip"], ip,
                         "earnapp ok" if active else "earnapp mati",
                         ("\n   " + " \u00b7 ".join(extra)) if extra else ""))
    managed = {n["uuid"] for n in nodes if n["uuid"]}
    if devs:
        others = [d for d in devs.values()
                  if d.get("uuid") not in managed]
        if others:
            lines.append("\n\U0001F4CA <b>Device lain di akun</b> (%d)"
                         % len(others))
            for d in sorted(others, key=lambda x: str(x.get("title"))):
                u = d.get("uuid")
                ban = d.get("banned")
                lv = live.get(u, 0)
                if isinstance(ban, dict):
                    st = "\U0001F6AB banned <code>%s</code>" % \
                        ban.get("ip", "")
                elif lv > 0:
                    st = "\U0001F7E2 hijau %s" % fmt_uptime(lv)
                else:
                    st = "\u26AA idle"
                ips = d.get("ips") or []
                last = ips[-1] if isinstance(ips, list) and ips else "-"
                lines.append("\u00b7 <b>%s</b> \u2014 %s \u00b7 %s" % (
                    html.escape(str(d.get("title") or u)), st, last))
        banned = sum(1 for d in devs.values()
                     if isinstance(d.get("banned"), dict))
        green_all = sum(1 for u in devs if live.get(u, 0) > 0)
        lines.append("\nAkun: <b>%d</b> device \u00b7 \U0001F7E2 %d hijau "
                     "\u00b7 \U0001F6AB %d banned \u00b7 \u26AA %d idle" % (
                         len(devs), green_all, banned,
                         len(devs) - green_all - banned))
    lines.append("\n\U0001F7E2 hijau: <b>%d/%d</b>" % (green, len(nodes)))
    lines.append("Perintah: /ghost &lt;nama&gt; \u00b7 /restart &lt;nama&gt; "
                 "\u00b7 /reboot &lt;nama&gt;")
    text = "\n".join(lines)
    return text[:4000]


def nodes_help():
    names = ", ".join(n["name"] for n in read_nodes()) or "-"
    return "Node: %s" % names


# ------------------------------------------------- pendapatan harian + saldo
WITHDRAW_METHODS = {
    "pp": {"value": "paypal.com", "label": "PayPal", "min": 10.0},
    "az": {"value": "amazon.com (US/Global)", "label": "Amazon US",
           "min": 50.0},
}

# Nama tampilan kalau /etc/tg-bot/nodes tidak ada di node ini.
UUID_NAMES = {
    "sdk-node-4e3b43e982124a65bca569c2a8660be2": "semut13",
    "sdk-node-1a3a2d78ae054cba94b96591f8919e0b": "semut12",
    "sdk-node-666d4bdb574f4d7aaaab56429bccd662": "semut16",
    "sdk-node-225b1c94a6444f018f7e5ef6f12293cd": "semut09",
    "sdk-node-bc38a75beca1436fac64272e9dc38401": "semut04",
    "sdk-node-cec0a0a824784dd488ac82467a98faec": "semut03",
    "sdk-node-ca48d547ab69420b9e9794e9f521d14f": "semut14",
    "sdk-node-04eb3a051e2d4d1996240f7d11728a16": "semut06",
    "sdk-node-facbbc9805fb475f972a5f1b514ee62c": "semut05",
    "sdk-node-b251b4d893534a4aa9b5fa3700a788fa": "semut02",
    "sdk-node-6d01265a9a8348bcbe3f47adaada99fa": "semut11",
    "sdk-node-0273ce2fbbf34f3fa56ed72c3277be10": "semut17",
}


def node_label(uuid, fallback):
    for n in read_nodes():
        if n.get("uuid") == uuid:
            return n["name"]
    return UUID_NAMES.get(uuid) or str(fallback)


def _day_key():
    return time.strftime("%Y-%m-%d", time.localtime())


def _load_json(path):
    try:
        data = json.loads(read_file(path) or "{}")
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_json(path, data):
    try:
        write_file(path, json.dumps(data, sort_keys=True), 0o644)
    except Exception as exc:  # noqa: BLE001
        log("save", path, exc)


def _device_total(d):
    try:
        return float(d.get("earned_total") or 0)
    except (TypeError, ValueError):
        return 0.0


def earn_state(devs):
    """Hitung pendapatan hari ini per device. Return (state, rows, total)."""
    state = _load_json(EARN_FILE)
    day = _day_key()
    base = state.get("base")
    if not isinstance(base, dict):
        base = {}
    if state.get("day") != day:
        try:
            prev = float(state.get("last_total") or 0)
        except (TypeError, ValueError):
            prev = 0.0
        base = {}
        for d in devs:
            u = d.get("uuid")
            if u:
                base[u] = _device_total(d)
        state = {"day": day, "base": base, "last_total": 0.0,
                 "prev_day_total": prev, "notify_total": 0.0,
                 "notify_ts": 0.0, "rolled": 1}

    rows = []
    total = 0.0
    for d in devs:
        u = d.get("uuid")
        if not u:
            continue
        cur = _device_total(d)
        b = base.get(u)
        if b is None or cur < float(b):
            base[u] = cur
            b = cur
        today = cur - float(b)
        if today < 0:
            today = 0.0
        total += today
        rows.append({"uuid": u, "today": today, "total": cur, "dev": d})
    state["base"] = base
    state["last_total"] = total
    _save_json(EARN_FILE, state)
    return state, rows, total


def report_text():
    if not read_file(COOKIE_FILE):
        return ("\u26A0\uFE0F Cookie EarnApp belum diset.\n"
                "Kirim cookie dulu lewat /setcookie.")
    st, dev = ea_api("/api/devices")
    if st != 200 or not isinstance(dev, list):
        return "\u26A0\uFE0F Gagal ambil data EarnApp (status %s)." % st
    devs = [d for d in dev if isinstance(d, dict)]
    state, rows, total = earn_state(devs)

    balance = 0.0
    mst, money = ea_api("/api/money")
    if mst == 200 and isinstance(money, dict):
        try:
            balance = float(money.get("balance") or 0)
        except (TypeError, ValueError):
            balance = 0.0

    rows.sort(key=lambda r: r["today"], reverse=True)
    lines = ["\U0001F4CA <b>REPORT HARI INI</b>",
             "\U0001F552 %s WIB" % time.strftime("%d/%m/%Y %H:%M"),
             "",
             "\U0001F30D <b>Global hari ini: +%s</b>" % fmt_money(total),
             "\U0001F4B0 Saldo akun: <b>%s</b>" % fmt_money(balance),
             ""]
    green = banned = 0
    for r in rows:
        d = r["dev"]
        if isinstance(d.get("banned"), dict):
            mark = "\U0001F6AB"
            banned += 1
        else:
            mark = "\U0001F7E2"
            green += 1
        name = node_label(r["uuid"], d.get("title") or r["uuid"])
        lines.append("%s <b>%s</b> \u2014 hari ini +%s \u00b7 total %s" % (
            mark, html.escape(name), fmt_money(r["today"]),
            fmt_money(r["total"])))
    lines.append("")
    lines.append("Hijau <b>%d</b> \u00b7 banned <b>%d</b> \u00b7 "
                 "device <b>%d</b>" % (green, banned, len(rows)))
    return "\n".join(lines)[:4000]


def fresh_balance():
    st, money = ea_api("/api/money")
    if st == 200 and isinstance(money, dict):
        try:
            return float(money.get("balance") or 0)
        except (TypeError, ValueError):
            return 0.0
    return None


def withdraw_text(balance=None):
    if balance is None:
        balance = fresh_balance()
    if balance is None:
        return "\u26A0\uFE0F Gagal ambil saldo dari EarnApp."
    lines = ["\U0001F4B8 <b>TARIK SALDO</b>", "",
             "Saldo: <b>%s</b>" % fmt_money(balance), "",
             "Minimum: PayPal $10 \u00b7 Amazon US $50", ""]
    ready = [m for m in WITHDRAW_METHODS.values() if balance >= m["min"]]
    if ready:
        lines.append("Siap ditarik: <b>%s</b>" %
                     ", ".join(m["label"] for m in ready))
    else:
        lines.append("Belum mencapai minimum penarikan.")
    email = read_file(PAYOUT_EMAIL_FILE).strip()
    if email:
        lines.append("Email tujuan: <code>%s</code>" % html.escape(email))
    else:
        lines.append("Email tujuan belum diset.")
        lines.append("Set: <code>/tarik pp email@kamu</code>")
    return "\n".join(lines)


def withdraw_keyboard(balance=None):
    if balance is None:
        balance = fresh_balance() or 0.0
    rows = []
    for code, m in WITHDRAW_METHODS.items():
        if balance >= m["min"]:
            rows.append([{
                "text": "\U0001F4B8 %s (%s)" % (m["label"],
                                                fmt_money(balance)),
                "callback_data": "wd:" + code}])
    rows.append([{"text": "\U0001F504 Muat ulang saldo",
                  "callback_data": "wd_menu"}])
    return {"inline_keyboard": rows}


def do_redeem(chat_id, code):
    m = WITHDRAW_METHODS.get(code)
    if not m:
        send(chat_id, "\u26A0\uFE0F Metode tidak dikenal.")
        return
    email = read_file(PAYOUT_EMAIL_FILE).strip()
    if "@" not in email:
        send(chat_id, "\u26A0\uFE0F Email tujuan belum diset.\n"
                      "Format: <code>/tarik %s email@kamu</code>" % code)
        return
    balance = fresh_balance()
    if balance is None:
        send(chat_id, "\u26A0\uFE0F Gagal ambil saldo.")
        return
    if balance < m["min"]:
        send(chat_id, "Saldo <b>%s</b> belum mencapai minimum <b>%s</b> "
                      "untuk %s." % (fmt_money(balance), fmt_money(m["min"]),
                                     m["label"]), MENU)
        return
    st, res = ea_api("/api/redeem", "POST",
                     {"to": email, "payment_method": m["value"]})
    if 200 <= st < 300:
        send(chat_id, "\u2705 <b>Penarikan dikirim</b>\n\n"
                      "Metode: <b>%s</b>\nSaldo ditarik: <b>%s</b>\n"
                      "Tujuan: <code>%s</code>\n\n"
                      "Cek email untuk konfirmasi dari EarnApp." % (
                          m["label"], fmt_money(balance),
                          html.escape(email)), MENU)
    else:
        send(chat_id, "\u26A0\uFE0F <b>Penarikan gagal</b> (status %s)\n"
                      "<pre>%s</pre>" % (st, html.escape(str(res)[:400])),
             MENU)


def daily_notify(chat_id, state, total):
    """Kirim notifikasi saat pendapatan harian bertambah / hari berganti."""
    if not chat_id or read_file(NOTIF_FILE) == "0":
        return
    now = time.time()
    try:
        last_total = float(state.get("notify_total") or 0)
    except (TypeError, ValueError):
        last_total = 0.0
    try:
        last_ts = float(state.get("notify_ts") or 0)
    except (TypeError, ValueError):
        last_ts = 0.0

    if state.get("rolled"):
        try:
            prev = float(state.get("prev_day_total") or 0)
        except (TypeError, ValueError):
            prev = 0.0
        state["rolled"] = 0
        state["notify_ts"] = now
        state["notify_total"] = total
        _save_json(EARN_FILE, state)
        if prev > 0:
            send(chat_id, "\U0001F319 <b>Hari baru</b>\n"
                          "Pendapatan kemarin: <b>+%s</b>\n"
                          "Hitungan hari ini dimulai." % fmt_money(prev))
        return

    naik = total - last_total
    if naik >= 0.01 and now - last_ts >= 1800:
        send(chat_id, "\U0001F4C8 <b>Pendapatan hari ini naik</b>\n\n"
                      "+%s sejak terakhir\n"
                      "Total hari ini: <b>+%s</b>" % (
                          fmt_money(naik), fmt_money(total)))
        state["notify_ts"] = now
        state["notify_total"] = total
        _save_json(EARN_FILE, state)



# ---------------------------------------------------------------- dispatch
def is_authorized(chat_id):
    locked = read_file(CHAT_FILE)
    if not locked:
        write_file(CHAT_FILE, str(chat_id))
        return True
    return locked == str(chat_id)


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    mid = msg["message_id"]

    if not is_authorized(chat_id):
        log("ignoring unauthorized chat", chat_id)
        return

    low = text.lower()
    if low.startswith("cookie:"):
        val = text.split("SESSION:")[0][len("cookie:"):].strip()
        if not val:
            send(chat_id, "\u26A0\uFE0F Cookie kosong. Coba cara manual "
                          "dari tab Application \u2192 Cookies.")
            return
        old = read_file(COOKIE_FILE)
        write_file(COOKIE_FILE, val)
        st, sess = ea_api("/api/session")
        ok = st == 200 and isinstance(sess, dict) and \
            sess.get("authenticated") is not False
        if not ok:
            if old:
                write_file(COOKIE_FILE, old)
            else:
                try:
                    os.remove(COOKIE_FILE)
                except OSError:
                    pass
            send(chat_id,
                 "\u26A0\uFE0F Cookie yang diterima <b>tidak valid</b>.\n\n"
                 "Kemungkinan cookie sesi EarnApp bersifat <i>HttpOnly</i>, "
                 "jadi tidak terbaca lewat <code>document.cookie</code>.\n\n"
                 "Balas <b>lanjut</b> \u2014 saya ambil cookie-nya langsung dari "
                 "Chrome (perlu Chrome ditutup ~30 detik).")
            return
        send(chat_id, "\u2705 Cookie valid & disimpan.", MENU)
        send(chat_id, dash_text(), MENU)
    elif low.startswith("/start") or low.startswith("/menu") or low.startswith("/help"):
        send(chat_id, "\U0001F916 <b>OpenStick Bot</b>\n\n"
                      "Pilih menu di bawah, atau perintah:\n"
                      "/status \u2014 IP publik + EarnApp\n"
                      "/dash \u2014 status dashboard EarnApp\n"
                      "/reboot \u2014 restart device\n"
                      "/off \u2014 matikan device (poweroff)\n"
                      "/ghost \u2014 ganti MAC + IP publik (tanpa reboot)\n"
                      "/setcookie \u2014 simpan cookie dashboard\n"
                      "/report \u2014 pendapatan hari ini per node + global\n"
                      "/tarik \u2014 saldo & tarik ke PayPal/Amazon\n"
                      "/notif on|off \u2014 notifikasi pendapatan naik\n"
                      "/blacklist \u2014 IP yang diblokir EarnApp\n"
                      "/auto on|off \u2014 auto-ghost saat banned\n"
                      "/all \u2014 status semua node\n"
                      "/ghost &lt;nama&gt; \u2014 ghost node lain\n"
                      "/restart &lt;nama&gt; \u2014 restart EarnApp+bot node\n"
                      "/reboot &lt;nama&gt; \u2014 reboot node lain\n"
                      "/sh &lt;nama&gt; &lt;cmd&gt; \u2014 jalankan perintah\n"
                      "/id \u2014 info device", MENU)
    elif low.startswith("/all"):
        send(chat_id, all_text(), MENU)
    elif low.startswith("/sh "):
        rest = text[4:].strip().split(None, 1)
        if len(rest) < 2:
            send(chat_id, "Format: <code>/sh nama perintah</code>\n" +
                 nodes_help())
            return
        node = node_by_name(rest[0])
        if not node:
            send(chat_id, "Node tidak dikenal.\n" + nodes_help())
            return
        rc, out, err = run_on(node, rest[1], timeout=90)
        body = (out or "") + (("\n" + err) if err else "")
        send(chat_id, "<b>%s</b> rc=%s\n<pre>%s</pre>" % (
            node["name"], rc, html.escape(body[-3000:] or "(kosong)")))
    elif low.startswith("/restart"):
        arg = text[len("/restart"):].strip()
        if not arg:
            send(chat_id, "Format: <code>/restart nama</code>\n" +
                 nodes_help())
            return
        node = node_by_name(arg)
        if not node:
            send(chat_id, "Node tidak dikenal.\n" + nodes_help())
            return
        rc, out, err = run_on(
            node, "systemctl restart earnapp tg-bot; sleep 5; "
                  "systemctl is-active earnapp tg-bot | tr '\\n' ' '", 90)
        send(chat_id, "\u267B\uFE0F <b>%s</b> restart: <code>%s</code>" % (
            node["name"], html.escape((out or err or "?")[-500:])), MENU)
    elif low.startswith("/status"):
        send(chat_id, status_text(), MENU)
    elif low.startswith("/dash"):
        send(chat_id, dash_text(), MENU)
    elif low.startswith("/report"):
        send(chat_id, report_text(), MENU)
    elif low.startswith("/tarik") or low.startswith("/withdraw"):
        parts = text.split()
        args = parts[1:]
        if not args:
            bal = fresh_balance()
            send(chat_id, withdraw_text(bal), withdraw_keyboard(bal))
        elif args[0] in WITHDRAW_METHODS and len(args) > 1:
            email = args[1].strip()
            if "@" not in email:
                send(chat_id, "\u26A0\uFE0F Email tidak valid.\n"
                              "Format: <code>/tarik %s email@kamu</code>"
                              % args[0])
                return
            write_file(PAYOUT_EMAIL_FILE, email)
            bal = fresh_balance() or 0.0
            send(chat_id, "\u2705 Email tujuan disimpan: <code>%s</code>\n"
                          "Saldo sekarang: <b>%s</b>\n\n"
                          "Tekan <b>Tarik Saldo</b> untuk melanjutkan." % (
                              html.escape(email), fmt_money(bal)), MENU)
        else:
            send(chat_id, "Format:\n"
                          "<code>/tarik</code> \u2014 lihat saldo\n"
                          "<code>/tarik pp email@kamu</code> \u2014 PayPal\n"
                          "<code>/tarik az email@kamu</code> \u2014 Amazon",
                 MENU)
    elif low.startswith("/notif"):
        arg = text[len("/notif"):].strip().lower()
        if arg in ("on", "off"):
            write_file(NOTIF_FILE, "1" if arg == "on" else "0")
            send(chat_id, "Notifikasi pendapatan harian: <b>%s</b>"
                 % arg.upper(), MENU)
        else:
            cur = "OFF" if read_file(NOTIF_FILE) == "0" else "ON"
            send(chat_id, "Notifikasi pendapatan harian: <b>%s</b>\n"
                          "Ubah: <code>/notif on</code> atau "
                          "<code>/notif off</code>" % cur, MENU)
    elif low.startswith("/reboot"):
        arg = text[len("/reboot"):].strip()
        if arg:
            node = node_by_name(arg)
            if not node:
                send(chat_id, "Node tidak dikenal.\n" + nodes_help())
                return
            send(chat_id, "\U0001F501 Reboot <b>%s</b>..." % node["name"])
            run_on(node, "sync; sleep 1; systemctl reboot", 25)
            send(chat_id, "\u2705 Reboot dikirim ke <b>%s</b>." %
                 node["name"], MENU)
        else:
            send(chat_id, "\u26A0\uFE0F Yakin reboot device sekarang?",
                 CONFIRM_REBOOT, reply_to=mid)
    elif low.startswith("/off") or low.startswith("/shutdown") or \
            low.startswith("/poweroff"):
        send(chat_id, "\u23FB <b>Matikan device?</b>\n\n"
                      "Device akan <b>poweroff total</b> (aman untuk "
                      "pemeliharaan).\n"
                      "\u26A0\uFE0F Setelah mati, bot & EarnApp berhenti. "
                      "Hidupkan lagi dengan mencabut lalu menyambung daya.",
             CONFIRM_OFF, reply_to=mid)
    elif low.startswith("/ghost"):
        arg = text[len("/ghost"):].strip()
        if arg:
            node = node_by_name(arg)
            if not node:
                send(chat_id, "Node tidak dikenal.\n" + nodes_help())
                return
            send(chat_id, "\U0001F47B Ghost <b>%s</b> \u2014 tunggu "
                          "\u00b11\u20137 menit (verifikasi IP ke EarnApp)..." % node["name"])
            rc, out, err = run_on(
                node, "/usr/local/sbin/openstick-ghost 3", timeout=420)
            send(chat_id, "\U0001F47B <b>%s</b>\n<pre>%s</pre>" % (
                node["name"], html.escape((out or err)[-1500:])), MENU)
        else:
            send(chat_id, "\U0001F47B <b>Ganti IP publik</b>\n\n"
                          "MAC Wi-Fi diacak, koneksi diputus 15 detik lalu "
                          "reconnect \u2014 <b>tanpa reboot</b>.\n"
                          "\u26A0\uFE0F Selama proses, device offline "
                          "\u00b120\u201360 detik.", CONFIRM_GHOST,
                 reply_to=mid)
    elif low.startswith("/setcookie"):
        val = text[len("/setcookie"):].strip()
        if not val:
            send(chat_id, "Format: <code>/setcookie nama=value; nama2=value2</code>")
            return
        write_file(COOKIE_FILE, val)
        send(chat_id, "\u2705 Cookie disimpan. Coba /dash.", MENU)
    elif low.startswith("/blacklist"):
        items = read_blacklist()
        if not items:
            send(chat_id, "Blacklist kosong.")
        else:
            send(chat_id, "\U0001F6AB <b>IP blacklist</b> (%d)\n\n%s\n\n"
                          "IP di daftar ini akan <b>dilewati</b> saat ganti IP." % (
                len(items), "\n".join("<code>%s</code>" % html.escape(i)
                                      for i in items[:30])))
    elif low.startswith("/auto"):
        arg = low[len("/auto"):].strip()
        if arg in ("on", "1", "ya", "yes"):
            write_file(AUTO_FILE, "1")
            send(chat_id, "\u2705 Auto-rotate <b>ON</b>\n"
                          "Saat IP masuk blacklist, device otomatis ganti MAC "
                          "+ reconnect 15 dtk (tanpa reboot).")
        elif arg in ("off", "0", "no", "tidak"):
            write_file(AUTO_FILE, "0")
            send(chat_id, "\u2705 Auto-rotate <b>OFF</b>\n"
                          "Ban hanya diberi notifikasi; ganti IP manual via "
                          "tombol /ghost.")
        else:
            send(chat_id, "Auto-rotate: <b>%s</b>\nGunakan <code>/auto on</code> "
                          "atau <code>/auto off</code>." %
                 ("ON" if read_file(AUTO_FILE) == "1" else "OFF"))
    elif low.startswith("/id"):
        send(chat_id, "chat_id: <code>%s</code>\nUUID: <code>%s</code>" % (
            chat_id, html.escape(read_file("/etc/earnapp/uuid") or "-")))
    else:
        send(chat_id, "Gunakan menu:", MENU)


def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    mid = cb["message"]["message_id"]
    data = cb.get("data") or ""
    cb_id = cb["id"]

    if not is_authorized(chat_id):
        answer_cb(cb_id, "Unauthorized")
        return

    if data == "status":
        answer_cb(cb_id, "Mengambil status...")
        edit(chat_id, mid, status_text())
    elif data == "dash":
        answer_cb(cb_id, "Mengambil dashboard...")
        edit(chat_id, mid, dash_text())
    elif data == "report":
        answer_cb(cb_id, "Menghitung report...")
        edit(chat_id, mid, report_text())
    elif data == "wd_menu":
        answer_cb(cb_id, "Mengambil saldo...")
        bal = fresh_balance()
        edit(chat_id, mid, withdraw_text(bal))
        send(chat_id, "Pilih metode penarikan:", withdraw_keyboard(bal))
    elif data.startswith("wd:"):
        code = data[3:]
        m = WITHDRAW_METHODS.get(code)
        if not m:
            answer_cb(cb_id, "Metode tidak dikenal")
            return
        answer_cb(cb_id)
        email = read_file(PAYOUT_EMAIL_FILE).strip()
        if "@" not in email:
            send(chat_id, "\u26A0\uFE0F Email tujuan belum diset.\n"
                          "Kirim: <code>/tarik %s email@kamu</code>" % code)
            return
        send(chat_id, "\u26A0\uFE0F <b>Konfirmasi tarik saldo</b>\n\n"
                      "Metode: <b>%s</b>\nTujuan: <code>%s</code>\n\n"
                      "Saldo akan ditarik seluruhnya. Lanjutkan?" % (
                          m["label"], html.escape(email)),
             {"inline_keyboard": [[
                 {"text": "\u2705 Tarik sekarang",
                  "callback_data": "wdgo:" + code},
                 {"text": "\u274C Batal", "callback_data": "cancel"}]]})
    elif data.startswith("wdgo:"):
        code = data[5:]
        answer_cb(cb_id, "Memproses penarikan...")
        do_redeem(chat_id, code)
    elif data == "reboot":
        answer_cb(cb_id)
        edit(chat_id, mid, "\u26A0\uFE0F Yakin reboot device sekarang?")
        send(chat_id, "Konfirmasi reboot:", CONFIRM_REBOOT)
    elif data == "off":
        answer_cb(cb_id)
        edit(chat_id, mid, "\u23FB Yakin matikan device?")
        send(chat_id, "\u26A0\uFE0F Konfirmasi poweroff:", CONFIRM_OFF)
    elif data == "ghost":
        answer_cb(cb_id)
        edit(chat_id, mid, "\U0001F47B Ganti MAC + IP baru (tanpa reboot).")
        send(chat_id, "\u26A0\uFE0F Konfirmasi ganti IP?",
             CONFIRM_GHOST)
    elif data == "cancel":
        answer_cb(cb_id, "Dibatalkan")
        edit(chat_id, mid, "\u274C Dibatalkan.")
    elif data == "do_reboot":
        answer_cb(cb_id, "Rebooting...")
        edit(chat_id, mid, "\U0001F504 <b>Rebooting device...</b>\n"
                          "Bot akan online lagi dalam ~20 detik.")
        time.sleep(2)
        reboot_now()
    elif data == "do_off":
        answer_cb(cb_id, "Mematikan...")
        edit(chat_id, mid,
             "\u23FB <b>Device dimatikan.</b>\n\n"
             "Aman untuk dicabut / dipindah. Hidupkan lagi dengan "
             "menyambung daya \u2014 semua service auto-start.")
        time.sleep(2)
        poweroff_now()
    elif data == "do_ghost":
        answer_cb(cb_id, "Mengganti MAC + IP...")
        edit(chat_id, mid,
             "\U0001F47B <b>Ganti IP publik</b>\n\n"
             "MAC Wi-Fi diacak, koneksi diputus 15 detik lalu reconnect.\n"
             "Proses \u00b11 menit, <b>tanpa reboot</b>.")
        threading.Thread(target=_rotate_job, args=(chat_id, mid),
                         daemon=True).start()
    else:
        answer_cb(cb_id)


def main():
    if not TOKEN:
        log("no token in", TOKEN_FILE)
        sys.exit(1)
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        offset = int(read_file(OFFSET_FILE) or 0)
    except ValueError:
        offset = 0

    me = None
    for attempt in range(12):
        try:
            me = api("getMe")
            break
        except Exception as exc:  # noqa: BLE001
            log("getMe gagal (%d): %s" % (attempt + 1, exc))
            time.sleep(10)
    if not me:
        log("getMe terus gagal, keluar")
        sys.exit(1)
    log("bot started:", me.get("result", {}).get("username"))

    threading.Thread(target=poll_devices, daemon=True).start()

    backoff = 1
    while True:
        try:
            res = api("getUpdates", offset=offset, timeout=50,
                      allowed_updates=["message", "callback_query"])
            backoff = 1
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                write_file(OFFSET_FILE, str(offset), 0o644)
                try:
                    if "message" in upd:
                        handle_message(upd["message"])
                    elif "callback_query" in upd:
                        handle_callback(upd["callback_query"])
                except Exception as exc:  # noqa: BLE001
                    log("handler error:", exc)
                    try:
                        send(upd.get("message", upd.get("callback_query", {}))
                             .get("chat", {}).get("id"),
                             "\u26A0\uFE0F Error: <code>%s</code>" % html.escape(str(exc)))
                    except Exception:  # noqa: BLE001
                        pass
        except urllib.error.HTTPError as exc:
            log("http error", exc.code, exc.read()[:200])
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        except Exception as exc:  # noqa: BLE001
            log("poll error:", exc)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    main()
