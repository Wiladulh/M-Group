# NVM Vending — Tutorial Instalasi & Wiring ESP32-S3

Panduan ini mengikuti konstanta GPIO pada `NvmVending.ino`. Board ESP32-S3 berbeda-beda; sebelum merakit, pastikan semua GPIO di tabel tersedia dan tidak dipakai fungsi onboard pada board pilihan.

## 1. Komponen

- ESP32-S3 DevKit.
- OLED SSD1306 I2C 128x64 (alamat default `0x3C`).
- Tiga tombol: UP, DOWN, SELECT.
- Satu reader NFC: PN532 I2C atau RC522 SPI.
- Lima servo dispenser.
- Sensor IR break-beam di jalur corong produk bersama.
- Catu daya servo eksternal yang sesuai arus stall total, kabel dan distribusi daya yang memadai.

## 2. Wiring OLED I2C

| OLED | ESP32-S3 |
|---|---:|
| VCC | Tegangan sesuai spesifikasi modul |
| GND | GND |
| SDA | GPIO 8 |
| SCL | GPIO 9 |

Alamat default firmware adalah `0x3C`. Pastikan pull-up I2C tidak menarik GPIO ESP32-S3 ke 5 V.

## 3. Wiring tombol

Setiap tombol menghubungkan GPIO ke GND ketika ditekan. Firmware memakai `INPUT_PULLUP`, jadi tidak perlu pull-up eksternal untuk tombol sederhana.

| Tombol | Satu kaki | Kaki lainnya |
|---|---:|---|
| UP | GPIO 4 | GND |
| DOWN | GPIO 5 | GND |
| SELECT | GPIO 6 | GND |

UP/DOWN memilih produk yang tampil di OLED. SELECT menampilkan prompt siap/tap kartu; firmware juga memindai kartu saat loop berjalan. Pastikan tombol tidak tertahan LOW saat boot.

## 4. Wiring NFC — pilih satu jenis reader

### Opsi A: PN532 I2C

| PN532 | ESP32-S3 |
|---|---:|
| SDA | GPIO 8 |
| SCL | GPIO 9 |
| IRQ | GPIO 7 |
| RESET/RSTO | GPIO 10 |
| GND | GND |
| VCC | Tegangan yang didukung breakout PN532 |

PN532 berbagi bus I2C dengan OLED. Periksa alamat I2C dan level logika. Firmware mencoba PN532 terlebih dahulu.

### Opsi B: RC522 SPI

| RC522 | ESP32-S3 |
|---|---:|
| SCK | GPIO 12 |
| MISO | GPIO 13 |
| MOSI | GPIO 11 |
| SDA/SS | GPIO 14 |
| RST | GPIO 15 |
| 3.3V | 3.3 V |
| GND | GND |

Pin RC522 yang bertanda **SDA** berfungsi sebagai SS/CS saat SPI, bukan SDA I2C. Jangan beri RC522 tegangan 5 V. Firmware menggunakan RC522 bila PN532 tidak terdeteksi.

## 5. Wiring lima servo

| Kanal servo NVM | Sinyal GPIO | Fungsi |
|---:|---:|---|
| 1 | GPIO 3 | Produk/servo dengan `servo_channel = 1` |
| 2 | GPIO 16 | Produk/servo dengan `servo_channel = 2` |
| 3 | GPIO 17 | Produk/servo dengan `servo_channel = 3` |
| 4 | GPIO 18 | Produk/servo dengan `servo_channel = 4` |
| 5 | GPIO 21 | Produk/servo dengan `servo_channel = 5` |

Setiap servo memiliki tiga jalur: signal ke GPIO pada tabel, V+ ke catu servo eksternal yang sesuai, dan GND ke GND catu servo. **Jangan memasok lima servo dari pin 3.3 V board atau mengandalkan regulator USB ESP32-S3.** Tentukan tegangan/arus catu dari spesifikasi servo dan arus stall; tambahkan kapasitor bulk dekat distribusi servo bila dibutuhkan.

Satukan GND catu servo dengan GND ESP32-S3 agar sinyal memiliki referensi yang sama. Jangan menghubungkan V+ servo ke GPIO. Periksa rentang sinyal dan arus sebelum menyalakan. Firmware menggerakkan servo ke sekitar 70° lalu kembali ke sekitar 10°; mekanik dispenser mungkin memerlukan kalibrasi sudut dan waktu, lakukan tanpa produk terlebih dahulu.

## 6. Wiring sensor IR produk jatuh

Firmware saat ini memakai satu sensor IR break-beam di corong bersama untuk memvalidasi lewatnya produk.

| Sensor IR | ESP32-S3 |
|---|---:|
| OUT digital | GPIO 1 |
| GND | GND |
| VCC | Tegangan sesuai modul |
| Emitter/receiver | Pasang saling berhadapan melintasi jalur jatuh produk |

Firmware menetapkan `PRODUCT_SENSOR_BLOCKED_LEVEL HIGH`, mengatur GPIO sebagai `INPUT_PULLUP`, dan menunggu pola **beam terhalang lalu kembali clear** dalam 4 detik. Ini harus diverifikasi dengan modul yang benar-benar dipakai; beberapa modul memiliki polaritas output terbalik atau keluaran 5 V. **Jangan sambungkan output 5 V langsung ke GPIO.** Gunakan output open-collector dengan pull-up 3.3 V atau level shifter yang sesuai bila diperlukan.

Sebelum menguji servo, pastikan sensor tidak melaporkan beam terhalang saat jalur kosong. Uji dengan tangan/objek, lalu uji produk sebenarnya. Sensor yang tidak pernah berubah status akan menyebabkan laporan gagal dispense/refund sesuai alur server; jangan menonaktifkan pemeriksaan untuk pemakaian nyata.

## 7. Instalasi firmware

1. Pasang Arduino IDE dan dukungan board **ESP32 by Espressif Systems** melalui Boards Manager.
2. Pasang library:
   - `Adafruit GFX Library`
   - `Adafruit SSD1306`
   - `Adafruit PN532`
   - `MFRC522`
   - `ESP32Servo`
3. Buka `esp32/vending/NvmVending.ino`. Pastikan `NvmCardReader.h` tetap berada di folder yang sama dengan sketch.
4. Pilih board ESP32-S3 yang cocok dengan perangkat dan port USB, lalu compile.
5. Atur variabel di bagian atas `NvmVending.ino`:
   - `WIFI_SSID` dan `WIFI_PASSWORD`
   - `NVM_BASE_URL`, misalnya `http://192.168.1.10:8011` (ganti IP contoh dengan IP server di LAN; tanpa slash akhir)
   - `DEVICE_ID`, ID perangkat vending yang terdaftar
   - `NVM_DEVICE_KEY`, key aktif dari registri perangkat
6. Provision perangkat bertipe `esp32-s3-vending` di server. Pastikan ID dan key sama dengan firmware. Daftarkan mesin vending di NVM dengan `device_id` yang menunjuk ke ID perangkat ini; ID mesin vending dapat berbeda dari ID perangkat.
7. Pastikan server dapat dijangkau dari LAN. Bind default `127.0.0.1` hanya menerima koneksi lokal; gunakan bind LAN yang sesuai (misalnya `NVM_HOST=0.0.0.0`, `NVM_PORT=8011`) dan batasi firewall TCP 8011 ke jaringan tepercaya.
8. Flash firmware dan buka Serial Monitor pada **115200 baud**.

Jangan commit SSID, password Wi-Fi, atau device key ke repository publik.

## 8. Konfigurasi produk

- Tambahkan/atur produk di WebUI/server, termasuk harga, stok, status aktif, dan `servo_channel` 1–5.
- Cocokkan setiap `servo_channel` dengan tabel GPIO di atas. Jangan gunakan channel di luar 1–5.
- Firmware mengambil katalog dari `/api/v1/vending/{DEVICE_ID}/products`; server tetap menjadi sumber kebenaran harga, stok, saldo, transaksi, dan refund.
- Produk melewati satu corong, sehingga sensor IR harus dipasang di jalur bersama yang dilalui semua produk.

## 9. Uji awal berurutan

1. Nyalakan ESP32-S3 tanpa mengaktifkan mekanisme berbahaya; cek Serial boot, Wi-Fi/IP, heartbeat, OLED, dan katalog produk.
2. Uji UP/DOWN/SELECT dan pastikan nama/harga produk tampil.
3. Uji NFC dengan kartu uji; Serial harus mendeteksi PN532 atau RC522.
4. Dengan servo tidak terhubung ke mekanik, uji gerakan tiap kanal dan pastikan urutan GPIO benar.
5. Uji sensor IR: jalur kosong harus terbaca clear, objek memutus beam lalu lewat harus menghasilkan blocked-then-clear.
6. Pasang mekanik dan uji satu produk dengan akun uji serta stok yang aman. Periksa transaksi server dan hasil sensor.
7. Cabut Wi-Fi/server pada lingkungan uji untuk memeriksa pemulihan. Jika create request atau laporan dispense tertunda, jangan hapus NVS; firmware menyimpan informasi pemulihan untuk menghindari transaksi ganda atau pengeluaran produk ulang.

## 10. Checklist keselamatan

- [ ] Tegangan semua modul sudah diperiksa; tidak ada output 5 V langsung ke GPIO.
- [ ] Catu servo eksternal memadai dan GND-nya tersambung ke GND ESP32-S3.
- [ ] Servo diuji tanpa beban sebelum terhubung ke mekanik.
- [ ] Sensor IR mengonfirmasi blocked-then-clear pada produk sebenarnya.
- [ ] Setiap produk memakai servo channel yang benar.
- [ ] Device ID/key cocok dengan registri server dan mesin vending terhubung ke device ID tersebut.
- [ ] Pembelian sukses, kartu tidak dikenal, stok habis, produk tidak jatuh, dan pemulihan jaringan diuji dengan akun uji.

**Status:** CI build memastikan firmware dapat dikompilasi, bukan memastikan pin cocok dengan semua varian ESP32-S3 atau bahwa mekanik/sensor sudah teruji. Tandai hardware PASS hanya setelah tes fisik selesai.
