# M-Group Cashier — Tutorial Instalasi & Wiring

Panduan ini mengikuti pin yang saat ini dipakai oleh `MGroupCashier.ino` dan helper di folder ini. Periksa tabel sebelum menyalakan perangkat.

## 1. Komponen

- ESP32 DevKit yang menyediakan GPIO pada tabel.
- OLED I2C 0,96 inci 128x64 berbasis SSD1306 (alamat default firmware `0x3C`). Jika modul Anda berbasis SH1106 atau memakai alamat berbeda, driver/alamat perlu disesuaikan sebelum build.
- Keypad matriks 4x4.
- Salah satu reader: PN532 (I2C) atau RC522 (SPI). Firmware mencoba PN532 dahulu, lalu RC522.
- Kabel jumper dan catu daya USB yang stabil.

## 2. Wiring ESP32 ke OLED I2C

| OLED I2C | ESP32 |
|---|---:|
| VCC | Sesuai spesifikasi modul; utamakan 3.3 V jika kompatibel |
| GND | GND |
| SDA | GPIO 21 |
| SCL | GPIO 22 |

Firmware memakai alamat OLED `0x3C` dengan driver Adafruit SSD1306. Jika modul memakai alamat lain, ubah `OLED_I2C_ADDRESS` di `MGroupCashier.ino`. OLED dan PN532 (bila dipakai) berbagi bus I2C pada GPIO 21/22. Pastikan modul I2C tidak menarik SDA/SCL ke 5 V; GPIO ESP32 menggunakan logika 3,3 V.

## 3. Wiring keypad 4x4

Hubungkan delapan jalur keypad sesuai urutan baris dan kolom berikut. Nama R1–R4/C1–C4 mengacu pada pin baris/kolom keypad, bukan nomor tombol.

| Jalur keypad | GPIO ESP32 |
|---|---:|
| R1 | 32 |
| R2 | 33 |
| R3 | 25 |
| R4 | 26 |
| C1 | 13 |
| C2 | 14 |
| C3 | 16 |
| C4 | 17 |

Fungsi tombol: angka untuk memasukkan nominal/PIN, `*` untuk menghapus digit terakhir, `#` untuk konfirmasi. PIN ditampilkan sebagai tanda bintang.

## 4. Wiring NFC — pilih satu jenis reader

### Opsi A: PN532 I2C

| PN532 | ESP32 |
|---|---:|
| SDA | GPIO 21 |
| SCL | GPIO 22 |
| IRQ | GPIO 39 |
| RESET/RSTO | GPIO 5 |
| GND | GND |
| VCC | Tegangan yang didukung breakout PN532 |

PN532 berbagi bus I2C dengan OLED. Pastikan alamat perangkat I2C tidak bentrok dan level SDA/SCL aman untuk ESP32. GPIO 39 hanya input dan tidak memiliki internal pull-up; breakout PN532 harus menyediakan bias IRQ yang diperlukan.

### Opsi B: RC522 SPI

| RC522 | ESP32 |
|---|---:|
| SCK | GPIO 18 |
| MISO | GPIO 19 |
| MOSI | GPIO 23 |
| SDA/SS | GPIO 27 |
| RST | GPIO 4 |
| 3.3V | 3.3 V |
| GND | GND |

Pada modul RC522, pin bertanda **SDA** biasanya berfungsi sebagai SS/CS untuk SPI, bukan jalur I2C. Jangan memberi daya RC522 dari 5 V.

## 5. Instalasi firmware

1. Pasang Arduino IDE dan dukungan board **ESP32 by Espressif Systems** melalui Boards Manager.
2. Pasang library melalui Library Manager:
   - `Adafruit SSD1306` dan `Adafruit GFX Library`
   - `Keypad`
   - `Adafruit PN532`
   - `MFRC522`
3. Unduh/clone repo M-Group, lalu buka `esp32/cashier/MGroupCashier.ino`. Pastikan `MGroupKeypad.h` dan `MGroupCardReader.h` tetap berada di folder yang sama dengan sketch.
4. Pilih board ESP32 yang sesuai dengan perangkat, port USB, lalu compile. Periksa bahwa semua library ditemukan.
5. Isi konfigurasi di bagian atas `MGroupCashier.ino`:
   - `WIFI_SSID` dan `WIFI_PASSWORD`
   - `M_GROUP_BASE_URL`, contoh `http://192.168.1.24:8011` (ganti IP contoh dengan IP server di jaringan lokal; jangan tambah slash di akhir)
   - `DEVICE_ID`, harus sama persis dengan ID perangkat kasir yang didaftarkan
   - `M_GROUP_DEVICE_KEY`, gunakan key aktif dari registri perangkat server
6. Daftarkan/provision perangkat bertipe kasir pada server dengan ID yang sama. Pastikan key aktif.
7. Pastikan server mendengarkan pada alamat LAN, bukan hanya loopback. Konfigurasi default server `127.0.0.1` tidak dapat diakses perangkat lain. Untuk LAN, gunakan bind yang sesuai (misalnya `M_GROUP_HOST=0.0.0.0`, `M_GROUP_PORT=8011`) dan batasi firewall TCP 8011 ke jaringan tepercaya.
8. Flash sketch, buka Serial Monitor pada **115200 baud**, lalu reset perangkat.

Jangan masukkan device key, kata sandi Wi-Fi, atau PIN asli ke dokumentasi publik maupun log.

## 6. Uji awal

1. OLED menyala dan menampilkan layar awal.
2. Serial Monitor menunjukkan alamat IP Wi-Fi dan heartbeat HTTP yang diterima server.
3. Serial Monitor melaporkan reader `PN532` atau `RC522`. Jika tidak, matikan daya dan periksa wiring, mode breakout, dan tegangan.
4. Uji semua tombol keypad; `*` menghapus dan `#` mengonfirmasi.
5. Gunakan kartu dan akun uji. Masukkan nominal, tap kartu, lalu masukkan PIN uji. Pastikan hasil OLED sesuai respons server dan ledger hanya mencatat satu debit.
6. Uji top-up hanya dengan PIN operator dan anggota uji serta prosedur kas yang disetujui.
7. Jika layar menampilkan `HASIL BELUM ADA` atau `PAYMENT PENDING`, **jangan hapus NVS atau memulai transaksi berbeda**. Pulihkan jaringan dan ikuti permintaan firmware untuk mengulangi PIN agar transaksi yang sama dapat direkonsiliasi.

## 7. Checklist sebelum digunakan

- [ ] Semua GND tersambung bersama.
- [ ] Tidak ada sinyal 5 V langsung ke GPIO ESP32.
- [ ] OLED, keypad, dan reader sudah diuji terpisah.
- [ ] Device ID dan key cocok dengan registri server.
- [ ] Pembayaran sukses, PIN salah, kartu tidak dikenal, dan saldo tidak cukup sudah diuji dengan akun uji.
- [ ] Reboot saat transaksi pending tidak menyebabkan transaksi baru atau debit ganda.

**Status:** build otomatis dapat memeriksa kompilasi, tetapi wiring, pembacaan kartu, OLED, keypad, dan transaksi nyata baru dapat dinyatakan lulus setelah diuji pada perangkat fisik.
