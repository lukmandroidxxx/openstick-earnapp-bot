# #JAMU WIFI ID — filter IP whitelist/blacklist

Versi standalone, publik, dan bisa dipasang di banyak device. Tidak perlu token
Telegram. Asalnya dari arsip `#JAMU WIFI ID` (`lukmandroidxxx/jamu-wifi.id`) yang
pernah dipakai di node semut, sekarang digabung ke repo ini supaya mudah
di-install.

## Cara kerja

1. Ambil IP publik (`api.ipify.org`).
2. Kalau IP ada di `/etc/ip_blacklist.txt` → ganti MAC + reconnect Wi-Fi
   (**tanpa reboot**), cari IP bersih. Tidak pernah memakai ulang IP banned.
3. Kalau IP ada di `/etc/ip_whitelist.txt` → IP dikunci, tidak dirotate.
4. IP baru dibiarkan online `SYNC_WAIT` detik (default 60) agar EarnApp
   check-in, lalu status dicek:
   - **GREEN** → IP masuk whitelist dan dikunci.
   - **RED** → IP masuk blacklist (dengan timestamp) lalu MAC dirotate.

Deteksi status memakai cookie dashboard EarnApp bila tersedia. Tanpa cookie,
script memakai halaman publik seperti instalasi lama (akurasinya lebih rendah).

## Install (satu perintah)

```bash
curl -fsSL https://raw.githubusercontent.com/lukmandroidxxx/openstick-earnapp-bot/main/bot/jamu-wifi-id/install.sh | sudo bash
```

Installer akan menanyakan **cookie EarnApp** (opsional, dianjurkan). Cookie
disimpan di `/etc/jamu-wifi-id/cookie` dengan permission `600` dan **tidak**
disimpan di GitHub. Kalau node sudah punya `/etc/tg-bot/cookie`, file itu dipakai
otomatis.

Kalau repo sudah di-clone:

```bash
sudo bash bot/jamu-wifi-id/install.sh
```

## Opsi

```
--interface IF         interface Wi-Fi (default wlan0)
--cookie-file FILE     import cookie EarnApp
--whitelist-file FILE  import whitelist awal
--blacklist-file FILE  import blacklist awal
--sync-wait DETIK      tunggu check-in sebelum cek status (default 60)
--max-rotate N         jumlah percobaan MAC/IP (default 10)
--reboot-on-ban        perilaku lama: reboot setelah mengacak MAC
--uninstall            hapus service/script/config, database IP dipertahankan
```

Contoh import daftar awal:

```bash
sudo bash bot/jamu-wifi-id/install.sh \
  --whitelist-file bot/jamu-wifi-id/examples/whitelist.txt \
  --blacklist-file bot/jamu-wifi-id/examples/blacklist.txt
```

## operasi

```bash
systemctl status jamu-wifi-id
journalctl -u jamu-wifi-id -f -n 50
cat /etc/ip_whitelist.txt
cat /etc/ip_blacklist.txt
```

Reset total database (hati-hati: IP banned bisa terpakai lagi):

```bash
sudo truncate -s 0 /etc/ip_whitelist.txt
sudo truncate -s 0 /etc/ip_blacklist.txt
sudo systemctl restart jamu-wifi-id
```

Uninstall:

```bash
sudo bash bot/jamu-wifi-id/install.sh --uninstall
```

File `/etc/ip_whitelist.txt` dan `/etc/ip_blacklist.txt` sengaja **tidak**
dihapus saat uninstall supaya riwayat ban tidak hilang.
