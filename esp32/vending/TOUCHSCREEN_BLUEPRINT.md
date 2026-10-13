# Blueprint M-Group Vending Touchscreen v1.0

**Status:** Rencana teknis — dokumentasi saja; belum mengubah firmware, API, database, atau konfigurasi produksi.  
**Tanggal:** 14 Oktober 2026  
**Target implementasi awal:** 15 Oktober 2026  
**Repositori:** `Wiladulh/M-Group`

## 1. Tujuan dan batas lingkup

Mengembangkan antarmuka vending dari tombol/OLED menjadi layar sentuh, sambil mempertahankan alur transaksi NFC yang sudah ada di M-Group.

### Termasuk dalam tahap awal

- Layar TFT SPI 3,5 inci berbasis ILI9488, resolusi native 480 × 320; antarmuka dapat diputar menjadi orientasi 320 × 480.
- Touch resistif pada modul yang mendukungnya.
- Board ESP32-S3 N16R8.
- Lima produk, masing-masing digerakkan satu servo.
- Pembacaan NFC, buzzer, dan sensor untuk memverifikasi produk keluar.
- Katalog produk dan otorisasi transaksi tetap menggunakan server M-Group.
- Penanganan kegagalan jaringan, hasil dispensing yang tidak pasti, dan pemulihan transaksi.

### Belum termasuk

- Integrasi pembayaran QRIS atau payment gateway.
- Perubahan skema database tanpa temuan audit yang membuktikan perubahan diperlukan.
- Penggantian kontrak API hanya demi mendukung layar sentuh.
- Pengujian perangkat keras fisik sebelum perangkat tersedia untuk diuji.

QRIS akan menjadi tahap terpisah. Blueprint UI boleh menyediakan ruang untuk metode pembayaran mendatang, tetapi pilihan QRIS harus nonaktif dan tidak boleh dianggap sebagai pembayaran yang berhasil.

## 2. Arsitektur yang dituju

```text
Layar sentuh
    │ pilihan produk / status UI
    ▼
Firmware ESP32-S3
    ├── driver TFT dan touch
    ├── state machine UI
    ├── pembaca NFC
    ├── komunikasi API + autentikasi perangkat
    ├── kontrol 5 servo
    ├── sensor keluarnya produk
    ├── buzzer
    └── NVS / pemulihan transaksi
             │ HTTPS / API
             ▼
Server M-Group
    ├── katalog produk dan ketersediaan
    ├── transaksi dan otorisasi
    ├── pencatatan hasil dispensing
    └── status perangkat / heartbeat
```

**Prinsip utama:** server adalah sumber kebenaran untuk katalog, saldo/otorisasi, dan status transaksi. ESP32 mengendalikan perangkat fisik, tetapi tidak boleh menganggap transaksi berhasil hanya karena servo telah diperintah bergerak.

## 3. Perangkat keras

| Komponen | Rencana |
|---|---|
| Board | ESP32-S3 N16R8 |
| Layar | TFT SPI 3,5 inci ILI9488, 480 × 320 |
| Touch | Resistif; pastikan pengendali touch pada modul yang benar-benar dibeli |
| Produk | 5 jalur produk dengan 5 servo |
| Pembayaran awal | NFC melalui pembaca yang sudah didukung firmware |
| Sensor keluaran | Satu sensor untuk mendeteksi produk benar-benar lewat |
| Umpan balik | Satu buzzer |
| Catu daya servo | Catu eksternal yang memadai, dengan GND bersama ESP32 |

### Peringatan pin ESP32-S3 N16R8

- Jangan memakai GPIO 35–37 sebelum memastikan konfigurasi board; pin tersebut dapat digunakan oleh octal PSRAM pada varian N16R8.
- GPIO 19/20 berkaitan dengan USB native; hindari jika USB board diperlukan.
- Periksa fungsi pin boot/strapping, pin yang sudah terpakai di board, serta pin periferal yang digunakan firmware.
- Buat tabel pin final setelah modul layar, pengendali touch, dan pembaca NFC dipastikan.
- Jangan menetapkan pin final hanya berdasarkan contoh generik ESP32-S3.

### Catatan sensor yang harus diselesaikan

Dokumentasi/firmware yang ada saat ini menggunakan sensor IR break-beam, sedangkan rancangan perangkat yang diinginkan menyebut LDR. Ini adalah perbedaan nyata yang harus diputuskan saat pemetaan wiring.

Buat antarmuka sensor yang terpisah dari logika transaksi agar sensor IR maupun LDR dapat dipilih secara eksplisit. Untuk LDR, ambang dan kondisi cahaya harus dikalibrasi pada mekanik vending yang sebenarnya. Sensor adalah bukti keluaran fisik, bukan bukti pembayaran.

### Catu daya dan keselamatan

- Jangan mencatu lima servo dari pin 3,3 V board.
- Gunakan suplai servo eksternal sesuai arus stall servo; satukan ground suplai servo dan ESP32.
- Pastikan level logika modul kompatibel dengan GPIO 3,3 V ESP32-S3.
- Periksa kebutuhan arus backlight TFT, regulator board, dan penurunan tegangan ketika servo bergerak.
- Uji satu servo terlebih dahulu, lalu bertahap sampai lima servo.

## 4. Rancangan antarmuka

### Layar A — Pilih produk

- Tampilkan maksimal lima kartu produk.
- Nama, harga, dan status stok berasal dari katalog server; jangan menanam harga tetap di firmware.
- Produk habis atau tidak aktif harus terlihat nonaktif.
- Sediakan status koneksi dan pesan kesalahan yang ringkas.

### Layar B — Instruksi NFC

- Tampilkan produk dan jumlah yang dipilih.
- Minta pengguna menempelkan kartu NFC.
- Jangan mengurangi saldo atau menjalankan servo sebelum server menyatakan transaksi telah diotorisasi.
- Tangani kartu tidak dikenal, saldo tidak cukup, transaksi ditolak, dan timeout secara jelas.

### Layar C — Pemrosesan dispensing

- Tampilkan status “sedang memproses”.
- Jangan izinkan transaksi baru yang dapat bertabrakan dengan gerakan servo.
- Gerakkan hanya servo untuk produk yang diotorisasi.
- Pantau sensor keluaran dan laporkan hasil ke server.

### Layar D — Hasil

- Berhasil hanya jika hasil dispensing telah dikonfirmasi dan status transaksi tersimpan dengan benar.
- Jika produk tidak terdeteksi, tampilkan pesan gagal/ perlu bantuan sesuai hasil server.
- Jika koneksi terputus setelah servo bergerak, tampilkan status belum pasti dan jalankan prosedur pemulihan; jangan otomatis mengulang gerakan servo.

### QRIS di masa mendatang

Boleh ada tempat untuk pilihan “QRIS — segera hadir”, tetapi nonaktif pada rilis NFC awal. QRIS baru boleh diaktifkan ketika alur provider, callback/notifikasi pembayaran terverifikasi di server, pengikatan pembayaran ke transaksi, dan pengujian keamanan selesai.

## 5. Kontrak API server

Rute yang sudah ada dan perlu diverifikasi terhadap implementasi aktual sebelum integrasi:

| Endpoint | Tujuan |
|---|---|
| `GET /api/v1/vending/{machine_id}/products` | Mengambil katalog produk vending |
| `POST /api/v1/vending/{machine_id}/transactions` | Memulai transaksi vending |
| `GET /api/v1/vending/transactions/{transaction_id}` | Memeriksa status transaksi |
| `POST /api/v1/vending/transactions/{transaction_id}/authorize` | Otorisasi transaksi |
| `POST /api/v1/vending/transactions/{transaction_id}/dispense` | Melaporkan hasil dispensing |
| `POST /api/v1/devices/{device_id}/heartbeat` | Heartbeat perangkat |

Autentikasi perangkat menggunakan header `X-M-Group-Device-Key`.

Daftar ini adalah peta awal berdasarkan struktur proyek saat blueprint dibuat, bukan pengganti pemeriksaan kontrak request/response terkini. Sebelum implementasi, cocokkan field wajib, status HTTP, skema respons, idempotency, serta urutan panggilan dengan `app/api/routes.py`, `app/vending/service.py`, dan pengujian kontrak firmware.

### Apakah server perlu diubah?

**Belum ada perubahan server yang terbukti diperlukan hanya untuk mengganti tombol menjadi layar sentuh.** Firmware dapat menggunakan API vending yang ada jika kontrak dan perilaku pemulihannya sudah memadai.

Perubahan server hanya diajukan jika audit atau pengujian menunjukkan kekurangan konkret, misalnya:
- hasil dispensing tidak dapat dilaporkan dengan aman/idempoten;
- status transaksi tidak dapat dipulihkan setelah perangkat kehilangan koneksi;
- katalog tidak menyediakan data yang diperlukan UI;
- atau otorisasi perangkat/aturan transaksi memiliki celah.

Jangan menambah endpoint duplikat atau mengubah database sebelum kebutuhan dibuktikan dan tes kontraknya disiapkan.

## 6. Aturan transaksi dan pemulihan

1. Ambil katalog dan validasi produk dari server.
2. Pengguna memilih produk.
3. Baca kartu NFC dan kirim permintaan transaksi sesuai kontrak API.
4. Tunggu otorisasi server yang valid.
5. Simpan identitas/status transaksi yang diperlukan untuk pemulihan di NVS sebelum tindakan fisik yang berisiko.
6. Gerakkan hanya servo yang sesuai dengan produk yang telah diotorisasi.
7. Gunakan sensor untuk menentukan apakah produk benar-benar keluar.
8. Laporkan hasil dispensing ke server dengan identitas transaksi yang sama.
9. Jika respons jaringan hilang, periksa status transaksi terlebih dahulu; jangan mengirim perintah dispensing baru secara membabi buta.
10. Setelah reboot, rekonsiliasi transaksi yang belum selesai. Jika hasil fisik tidak dapat diketahui, tandai sebagai tidak pasti untuk rekonsiliasi, bukan mengulang dispensing otomatis.

Setiap retry jaringan harus mempertahankan identitas transaksi/idempotency sesuai kontrak server. Status “servo diperintah bergerak” tidak boleh disamakan dengan “produk berhasil keluar”.

## 7. Struktur kode yang direncanakan

Pertahankan implementasi firmware utama yang sudah ada, dan pisahkan UI agar perubahan layar tidak merusak logika transaksi.

- `esp32/vending/MGroupVending.ino` — integrasi utama, state machine, API, NFC, servo, dan pemulihan.
- `esp32/vending/MGroupTouchUI.h` — kandidat modul baru untuk gambar layar, touch, tombol virtual, dan navigasi UI.
- `firmware/esp32-vending/platformio.ini` — dependensi build PlatformIO, disesuaikan dengan library yang dipilih.
- Dokumentasi wiring di direktori vending — pinout final, daya, sensor, kalibrasi touch, dan langkah uji.

Nama modul adalah usulan, bukan file yang sudah dibuat. Sebelum menambahkan library, cek versi yang kompatibel dengan PlatformIO dan kode firmware sekarang. Bandingkan Arduino_GFX atau TFT_eSPI untuk TFT serta library pengendali touch yang sesuai dengan IC pada modul aktual; jangan menganggap semua modul ILI9488 memakai IC touch yang sama.

## 8. Tahapan implementasi

### Tahap 1 — Audit sebelum coding

- Baca firmware utama, helper pembaca kartu, konfigurasi PlatformIO, rute API, service vending, dan tes kontrak.
- Catat pin yang sudah digunakan oleh NFC, servo, sensor, buzzer, dan periferal board.
- Pastikan tipe pengendali touch pada modul layar.
- Putuskan sensor produk: LDR atau IR break-beam.

### Tahap 2 — Driver dan pinout

- Tetapkan GPIO final dengan memperhatikan board ESP32-S3 N16R8.
- Tambahkan library yang dibutuhkan dengan versi yang diketahui.
- Uji build sebelum menggabungkan UI ke alur transaksi.

### Tahap 3 — UI mandiri

- Inisialisasi layar dan orientasi.
- Kalibrasi koordinat touch.
- Uji lima area sentuh, navigasi layar, dan penanganan touch di luar tombol.
- Gunakan data dummy hanya pada uji UI terisolasi; jangan jadikan data dummy sebagai katalog produksi.

### Tahap 4 — Integrasi server dan NFC

- Ganti data dummy dengan katalog API.
- Sambungkan pemilihan produk ke alur NFC dan otorisasi yang sudah ada.
- Pertahankan autentikasi perangkat dan kontrak API.
- Tambahkan pesan untuk timeout, penolakan, stok habis, dan server tidak tersedia.

### Tahap 5 — Dispensing dan pemulihan

- Uji servo satu per satu.
- Uji sensor keluaran dengan produk nyata.
- Uji kehilangan jaringan sebelum otorisasi, setelah otorisasi, selama dispensing, dan setelah dispensing tetapi sebelum laporan diterima.
- Uji reboot saat transaksi belum selesai untuk memastikan tidak terjadi dispensing ganda.

### Tahap 6 — Verifikasi

- Build PlatformIO lulus.
- Tes API/pytest dan tes kontrak firmware lulus.
- Tidak ada perubahan tak sengaja pada API/database.
- Pengujian perangkat fisik dicatat terpisah dari tes CI.
- Perbarui wiring dan instruksi pemasangan berdasarkan hasil perangkat nyata.

## 9. Kriteria penerimaan

- [ ] Layar menyala stabil dan orientasi benar.
- [ ] Touch terkalibrasi serta lima pilihan produk dapat digunakan.
- [ ] Katalog dan stok ditampilkan berdasarkan server.
- [ ] NFC mengikuti alur transaksi dan otorisasi server.
- [ ] Kartu/transaksi ditolak tidak menggerakkan servo.
- [ ] Hanya servo untuk produk terotorisasi yang bergerak.
- [ ] Hasil sensor dilaporkan ke server.
- [ ] Timeout, kehilangan jaringan, dan reboot tidak menyebabkan dispensing ganda otomatis.
- [ ] Buzzer memberi umpan balik tanpa mengganggu state machine.
- [ ] Build dan tes regresi lulus.
- [ ] Wiring diuji pada perangkat fisik sebelum dinyatakan siap produksi.
- [ ] QRIS tetap nonaktif dan tidak ada klaim pembayaran QRIS pada tahap ini.

## 10. Catatan keputusan

Blueprint ini adalah dokumen perencanaan. Belum menyatakan bahwa pinout, library, layar, sensor, atau wiring telah diuji pada perangkat fisik. Catat setiap perubahan desain berikutnya di dokumen ini atau tambahkan catatan keputusan terpisah agar implementasi dan hasil pengujian mudah dilacak.
