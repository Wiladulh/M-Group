# M-Group — Catatan Opsi Pengembangan
Tanggal: 2026-10-18
Status: **keputusan desain untuk pengembangan berikutnya; bukan implementasi produksi**

Dokumen ini mencatat hasil diskusi untuk dijadikan acuan saat pekerjaan server dan firmware utama dilanjutkan. Jangan menganggap fitur di bawah sudah tersedia sebelum implementasi, pengujian, dan verifikasi terpisah selesai.

## Keputusan yang disepakati

### 1. Metode pembayaran

Vending dan Cashier nantinya mendukung dua pilihan pembayaran:
- **NFC Card**: pembayaran menggunakan saldo internal member M-Group, dengan validasi dan pencatatan melalui server/ledger.
- **QRIS**: pembayaran eksternal melalui integrasi payment provider, dengan Midtrans sebagai opsi yang direncanakan.

Satu arsitektur transaksi/pencatatan di server dipakai oleh kedua jenis perangkat. Ini bukan berarti satu transaksi boleh ditagih lewat kedua metode sekaligus. Setiap transaksi memilih satu metode dan harus memiliki status/idempotency yang mencegah debit, kredit, atau dispensing ganda.

Server tetap menjadi sumber kebenaran untuk nominal, status pembayaran, saldo, transaksi, dan keputusan apakah dispensing boleh dilanjutkan. Kredensial rahasia provider pembayaran hanya berada di server, tidak di firmware ESP32 atau browser.

Integrasi Midtrans belum termasuk pekerjaan dalam catatan opsi ini. Sebelum implementasi, periksa kontrak API yang ada, alur webhook/notifikasi, validasi status, timeout/kedaluwarsa, rekonsiliasi, idempotency, refund, serta kebutuhan uji sandbox.

### 2. Gambar produk vending

- Katalog vending tetap memiliki **lima Product ID/posisi tetap (1–5)** sesuai kontrak proyek.
- Rencana awal adalah satu file gambar per produk, sekitar 1 MB per gambar; jumlah awal sekitar 5 MB untuk lima gambar.
- ESP32-S3 N16R8 memiliki flash nominal 16 MB dan PSRAM 8 MB. Jangan menganggap seluruh flash tersedia untuk gambar: periksa partition table aktual, firmware, NVS, filesystem, dan kebutuhan OTA sebelum menentukan kapasitas final.
- Gambar disimpan persisten di flash/filesystem lokal yang dialokasikan untuk itu. PSRAM dipakai sebagai ruang kerja/buffer grafis bila diperlukan, bukan dianggap sebagai penyimpanan persisten.
- Server menyimpan file gambar dan menyediakan metadata/referensi gambar, ukuran, tipe konten, serta versi atau hash.
- Vending **tidak melakukan polling otomatis berkala untuk perubahan katalog/gambar**. Petugas memulai sinkronisasi secara eksplisit melalui WebUI lokal vending.
- Saat sinkronisasi, vending mengambil data katalog terbaru dan hanya mengunduh gambar yang versinya/hash-nya berbeda. Data teks/harga mengikuti kontrak API katalog yang ada.
- File baru harus diunduh ke file sementara, divalidasi, kemudian dipasang sebagai file aktif secara aman. Jika unduhan/verifikasi gagal, pertahankan file lama. Jangan menghapus gambar lama sebelum gambar pengganti tervalidasi.
- Perubahan harga tidak semestinya memicu unduh gambar ulang jika gambar tidak berubah.
- UI touchscreen adalah opsi pengembangan berikutnya. Firmware saat ini tetap harus berjalan tanpa bergantung pada keberadaan layar touchscreen atau gambar.

### 3. WebUI konfigurasi lokal vending

Seluruh pengaturan perangkat dilakukan melalui WebUI lokal minimalis. LCD/touchscreen yang kelak ditambahkan berfungsi untuk pengalaman pembeli, bukan sebagai tempat konfigurasi teknis.

Ruang lingkup konfigurasi yang direncanakan:
- SSID dan password Wi-Fi;
- alamat dasar dan port server M-Group;
- Device ID dan pengelolaan Device Key melalui prosedur provisioning yang aman;
- status jaringan, autentikasi server, firmware, dan penyimpanan;
- tombol **Sinkronisasi Data dari Server**, status/progres, hasil, serta waktu sinkronisasi terakhir.

Keamanan:
- Jangan commit kredensial perangkat, password Wi-Fi, token, atau secret ke repository.
- Setelah tersimpan, rahasia tidak ditampilkan utuh kembali di WebUI.
- Batasi akses konfigurasi kepada petugas berwenang; jangan menganggap tersambung ke AP/LAN sebagai otorisasi yang cukup.
- Validasi konfigurasi sebelum mengganti konfigurasi aktif; sediakan pemulihan bila perubahan jaringan membuat perangkat tidak terjangkau.
- Device Key tetap dipakai untuk autentikasi perangkat ke server sesuai kontrak server yang ada. MAC address saja bukan autentikasi.

### 4. Batas pelaksanaan

Catatan ini adalah opsi pengembangan, bukan izin untuk mengubah perilaku produksi tanpa tinjauan. Implementasi berikutnya harus:
1. memeriksa kontrak API dan struktur database yang ada;
2. menjaga kompatibilitas firmware yang sekarang;
3. menambahkan tes unit/integrasi dan pemeriksaan CI;
4. menguji kegagalan jaringan, unduhan terputus, file gambar tidak valid, dan sinkronisasi berulang;
5. menguji perangkat fisik sebelum menyatakan layar, penyimpanan, atau dispensing siap produksi.

Dokumen terperinci:
- `docs/PRODUCT-IMAGE-SYNC-PLAN.md`
- `docs/PAYMENT-METHODS-NFC-QRIS-PLAN.md`
- `esp32/vending/WEBUI-CONFIG-AND-SYNC-PLAN.md`
