# OpenStick EarnApp Bot

Bot Telegram untuk mengelola node **EarnApp** di OpenStick / UZ801 (Debian ARM64):
status real-time, dashboard, ganti IP (ghost), blacklist IP, auto-rotate, reboot, dan poweroff.

Dirancang untuk node yang dinyalakan 24/7: semua service auto-start saat boot,
watchdog Wi-Fi, dan tidak ada reboot terjadwal.

---

## Fitur

| Fitur | Keterangan |
|---|---|
| `/status` | IP publik, MAC, status EarnApp, uptime |
| `/dash` | Dashboard EarnApp — **sama dengan web** (hijau/putih real-time) |
| `/ghost` | Ganti MAC + reconnect 15 dtk → IP publik baru, **tanpa reboot** |
| `/blacklist` | Daftar IP banned yang tidak akan dipakai lagi |
| `/auto on\|off` | Auto-rotate saat IP kena ban |
| `/reboot` | Reboot device |
| `/off` | Poweroff aman (untuk pemeliharaan) |
| `/setcookie` | Simpan cookie dashboard EarnApp |
| `/id` | chat id + UUID node |

**Status hijau** diambil dari `POST /api/device_statuses` (endpoint yang sama
dipakai web EarnApp), bukan dari field `uptime` yang di-update batch.

**Blacklist**: IP yang pernah banned tidak akan dipakai ulang. Saat ghost,
setiap IP baru dicek; kalau masuk blacklist → skip dan coba lagi. Tidak ada
rollback ke IP lama yang banned.

---

## Persyaratan

- OpenStick / UZ801 sudah terpasang **Debian** dan bisa SSH
  (default `user@192.168.100.1` atau `user@192.168.200.1`, password `1`)
- **EarnApp** sudah terpasang & terdaftar (`/etc/earnapp/uuid` ada)
- Wi-Fi sudah terhubung (profil NetworkManager ada)
- Python 3 (sudah ada di Debian)
- **Token bot Telegram** — buat baru di [@BotFather](https://t.me/BotFather)
  (`/newbot`). **Satu token untuk satu node** — Telegram hanya mengizinkan
  satu poller per token.

---

## Instalasi di device

### 1. Clone repo

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/lukmandroidxxx/openstick-earnapp-bot.git
cd openstick-earnapp-bot
```

### 2. Jalankan installer

```bash
sudo bash install.sh
```

Installer akan menanyakan:

1. **Bot token** — wajib, **satu token untuk satu device**
   (buat di [@BotFather](https://t.me/BotFather) → `/newbot`).
   Token diverifikasi ke Telegram sebelum dipakai.
2. **Cookie EarnApp** — tempel header `Cookie` dari dashboard
   (F12 → Network → request `/api/session` → copy header `Cookie`).
   Cookie bersifat **satu akun** dan **boleh sama** untuk semua node.
   Kosongkan kalau belum ada; nanti bisa kirim `/setcookie` ke bot.

Setelah bot jalan, kirim `/start` sekali dari Telegram. Kalau `--chat`
tidak diisi, bot otomatis mengunci ke chat pertama yang mengirim perintah.

### 3. Tes

Kirim `/status` atau `/dash` ke bot. Kalau device hijau di web, di bot juga
harus hijau.

### Instalasi langsung tanpa clone

```bash
curl -fsSL https://raw.githubusercontent.com/lukmandroidxxx/openstick-earnapp-bot/main/install.sh -o /tmp/i.sh
sudo bash /tmp/i.sh
```

### Opsi installer

```
--token TOKEN          token bot (unik per node; ditanyakan kalau kosong)
--chat ID              kunci bot ke satu chat id (default: auto-lock)
--cookie-file FILE     file cookie EarnApp
--blacklist-file FILE  file IP banned
--auto on|off          auto-rotate (default on)
--no-base              lewati timezone/powersave/watchdog/LED
--uninstall            hapus bot (EarnApp tidak disentuh)
```

---

## Deploy ke banyak node dari PC (Windows/Linux)

`deploy_node.py` mengerjakan semuanya lewat SSH: bersihkan bot lama,
install bot baru, set token/cookie/blacklist, base setup, lalu verifikasi.

```powershell
python deploy_node.py --host 192.168.100.1
# token ditanyakan di terminal (satu token per node)
```

Atau langsung:

```powershell
python deploy_node.py --host 192.168.100.1 ^
  --token 123456:TOKEN_NODE_INI ^
  --cookie-file ea_cookie.txt ^
  --blacklist-file blacklist.txt
```

Yang dilakukan:

1. Backup + hapus bot/otomasi lama (`telegram-remote`, `ghoster`,
   `filter_ip`, watchdog lama, cron reboot 05:00, dll) ke
   `/root/old-bot-backup/`
2. Install bot + systemd unit + token + cookie + blacklist
3. Timezone `Asia/Jakarta`, Wi-Fi powersave off, watchdog, LED
4. Enable + start + verifikasi (uuid, MAC, IP publik, service)

Gunakan `--no-clean` untuk mempertahankan file lama, `--no-base` untuk
melewati langkah 3, `--chat ID` kalau ingin langsung mengunci chat.

> **Satu node = satu token bot.** Buat bot baru di @BotFather untuk tiap
> OpenStick. Kalau `--chat` tidak diisi, tiap bot mengunci sendiri ke chat
> pertama yang mengirim `/start`.

---

## Perintah bot

```
/status        IP publik + status EarnApp
/dash          dashboard (hijau = online, real-time)
/ghost         ganti MAC + IP (tanpa reboot)
/reboot        restart device
/off           poweroff aman
/setcookie     simpan cookie dashboard
/blacklist     IP banned yang dilewati
/auto on|off   auto-rotate saat ban
/all           status semua node (multi-node)
/ghost NAMA    ghost node lain lewat Tailscale
/restart NAMA  restart EarnApp + bot node lain
/reboot NAMA   reboot node lain
/sh NAMA CMD   jalankan perintah di node lain
/id            chat id + UUID
```

Tombol inline tersedia untuk semua perintah utama.

---

## Kontrol semua node dari satu bot (multi-node, Tailscale)

Node OpenStick biasanya di belakang CGNAT dan Wi-Fi-nya bisa memakai
*client isolation*, jadi IP LAN berubah dan node tidak bisa saling akses.
Solusinya Tailscale (mesh VPN, gratis): tiap node dapat IP tetap `100.x.y.z`.

1. Buat auth key di <https://login.tailscale.com/admin/settings/keys>
   (centang *Reusable* dan *No expiry*).
2. Di tiap node:

```bash
sudo modprobe tun
sudo mkdir -p /dev/net
sudo mknod /dev/net/tun c 10 200 2>/dev/null
echo tun | sudo tee /etc/modules-load.d/tun.conf
curl -fsSL https://tailscale.com/install.sh | sudo sh
sudo tailscale up --authkey=tskey-auth-... --accept-dns=false --accept-routes=false
tailscale ip -4
```

3. Buat SSH key di node yang jadi **master** (yang botnya dipakai sehari-hari):

```bash
sudo ssh-keygen -t ed25519 -N '' -f /root/.ssh/id_master
sudo cat /root/.ssh/id_master.pub
```

Tambahkan public key itu ke `/root/.ssh/authorized_keys` node lain, dan
pastikan `PermitRootLogin prohibit-password` aktif.

4. Isi daftar node di master, satu baris per node:

```
# /etc/tg-bot/nodes
# nama  ip_tailscale     uuid_earnapp (opsional)
semut06 100.81.199.122   sdk-node-04eb3a051e2d4d1996240f7d11728a16
semut05 100.114.73.122   sdk-node-facbbc9805fb475f972a5f1b514ee62c
semut02 100.110.139.13   sdk-node-b251b4d893534a4aa9b5fa3700a788fa
```

5. Restart bot, lalu kirim `/all` di Telegram. Contoh hasil:

```
🌐 NODE LIST (3)
🟢 semut06  100.81.199.122
   ip 114.12.19.119 · earnapp ok · hijau 43m
🟢 semut02  100.110.139.13
   ip 110.136.89.211 · earnapp ok · hijau 19m
🟢 hijau: 3/3
```

Node yang UUID-nya tidak diisi tetap dicek (online/offline + IP publik),
hanya status hijau dashboard yang tidak muncul.


---

## Cara kerja singkat

- **Green status** — `POST /api/device_statuses` + header `xsrf-token`
  (auto-refresh token kalau kedaluwarsa).
- **Ghost** — MAC acak → `nmcli con down` 15 dtk → `up` → cek IP publik.
  Kalau IP baru ada di blacklist → skip, ulangi. Tidak pernah kembali ke IP
  lama yang banned.
- **Auto-rotate** — saat `/api/devices` melaporkan `banned`, IP dicatat ke
  blacklist lalu ghost otomatis (cooldown 600 dtk, maks 3 percobaan).
- **Health** — kalau uptime live tidak naik 30 menit (setelah pernah naik),
  `earnapp` di-restart otomatis.
- **Watchdog Wi-Fi** — reconnect kalau link/IP/internet hilang > 90 dtk
  (toleran terhadap ghost yang memutus 15–30 dtk).

---

## Keamanan

**Jangan commit** file berikut (sudah masuk `.gitignore`):

- `cookie.txt` / `ea_cookie.txt` — kredensial akun EarnApp
- `token` / token bot
- `blacklist.txt` asli (opsional)

Token & cookie disimpan di device dengan permission `600`:
`/etc/tg-bot/token`, `/etc/tg-bot/cookie`.

---

## Troubleshooting

| Masalah | Cek |
|---|---|
| Bot tidak membalas | `systemctl status tg-bot` · `journalctl -u tg-bot -n 50` |
| Dashboard kosong | cookie salah/kedaluwarsa → `/setcookie` ulang |
| Tidak ada hijau | `curl` ke `api.ipify.org`; cek `journalctl -u earnapp` |
| IP terus banned | `/blacklist`, lalu `/ghost`; pastikan auto on |
| Wi-Fi putus | `journalctl -u openstick-wifi-watchdog -n 30` |
| Token bentrok | satu token dipakai 2 node → buat bot baru |

---

## Uninstall

```bash
sudo bash install.sh --uninstall
```

Menghapus bot + config, **tidak** menyentuh EarnApp.

---

## Lisensi

MIT
