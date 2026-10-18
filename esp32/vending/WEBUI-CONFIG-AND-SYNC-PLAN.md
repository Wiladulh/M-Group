# ESP32-S3 Vending — Rencana WebUI Konfigurasi dan Sinkronisasi
Status: rencana pengembangan; bukan fitur firmware yang sudah tersedia.

## Prinsip antarmuka

Pengaturan vending dilakukan melalui WebUI lokal minimalis yang diakses petugas dari browser ponsel/komputer. LCD/touchscreen yang mungkin ditambahkan kelak hanya untuk tampilan produk dan interaksi pembeli; jangan memindahkan pengaturan teknis ke layar pembeli.

WebUI lokal bukan pengganti Dashboard server M-Group. Server tetap menjadi sumber kebenaran katalog, harga, stok, saldo, pembayaran, dan transaksi.

## Fungsi yang direncanakan

### Koneksi
- SSID Wi-Fi dan password;
- URL dasar server M-Group, termasuk skema, alamat, dan port;
- status Wi-Fi, alamat IP lokal, dan koneksi server;
- validasi konfigurasi sebelum diterapkan serta cara pemulihan jika koneksi gagal.

### Identitas dan keamanan
- Device ID dan status registrasi;
- provisioning/pembaruan Device Key melalui alur berwenang;
- jangan menampilkan Device Key atau password Wi-Fi secara utuh setelah disimpan;
- jangan menyimpan secret dalam file statis browser atau menanamnya dalam URL;
- autentikasi WebUI lokal dan perlindungan perubahan konfigurasi;
- MAC address hanya informasi diagnostik, bukan bukti autentikasi.

### Sinkronisasi katalog/gambar
Tombol utama: **Sinkronisasi Data dari Server**.

Saat ditekan:
1. tampilkan konfirmasi dan cegah beberapa sinkronisasi berjalan bersamaan;
2. periksa Wi-Fi, alamat server, dan autentikasi perangkat;
3. ambil katalog dari endpoint kompatibel yang sudah digunakan firmware;
4. bandingkan versi/hash gambar untuk Product ID 1–5;
5. unduh hanya gambar baru/berubah;
6. validasi dan simpan secara aman, lalu aktifkan katalog baru;
7. tampilkan progres/status dan hasil akhir, termasuk produk yang gagal disinkronkan.

Tidak ada polling berkala khusus untuk mendeteksi perubahan katalog/gambar. Sinkronisasi hanya dimulai atas permintaan petugas, selain komunikasi operasional yang sudah diperlukan firmware.

## Penyimpanan gambar

Target awal adalah lima gambar, sekitar 1 MB per produk. Gunakan flash/filesystem internal hanya setelah partition table diverifikasi. Jangan menganggap seluruh 16 MB flash bebas; firmware, NVS, filesystem, dan OTA mungkin berbagi kapasitas. PSRAM 8 MB dapat digunakan untuk buffer/decode sesuai dukungan library layar, bukan untuk menyimpan file secara persisten.

Untuk setiap gambar:
- simpan ke file sementara;
- cek ukuran, hasil unduh, format yang didukung, dan hash bila tersedia;
- pertahankan gambar lama sampai file baru valid;
- lakukan penggantian dengan operasi yang aman untuk filesystem;
- jika gagal atau listrik mati, lanjutkan memakai gambar terakhir yang valid.

Gambar lokal harus tetap dapat ditampilkan saat server tidak terjangkau. Status UI perlu membedakan data lokal tersedia, sinkronisasi sedang berlangsung, berhasil, gagal, dan sebagian berhasil.

## Operasi yang aman

- Sinkronisasi jangan mengubah transaksi yang sedang berlangsung atau memicu dispensing.
- Jika vending sedang melayani transaksi, tunda penggantian katalog aktif sampai aman.
- Jangan menghapus recovery state transaksi saat konfigurasi atau sinkronisasi gagal.
- Perubahan SSID/server harus dapat dipulihkan jika konfigurasi baru tidak berhasil.
- Jangan log password, Device Key, token, atau data sensitif.
- Terapkan timeout, batas ukuran unduhan, dan penanganan respons server yang tidak valid.

## Pengujian minimum

- konfigurasi benar/salah dan pemulihan jaringan;
- akses WebUI tanpa otorisasi dan percobaan mengubah key;
- server tidak tersedia, download terputus, file tidak valid, dan filesystem penuh;
- sinkronisasi ulang dengan data yang sama;
- gambar berubah, gambar lama tetap utuh saat unduhan gagal;
- sinkronisasi ketika transaksi berjalan;
- reboot/power loss saat pembaruan file;
- kompatibilitas firmware tanpa layar touchscreen;
- compile CI serta uji hardware aktual sebelum menyatakan siap produksi.

Rencana ini tidak mengubah pin/wiring atau firmware yang berjalan saat ini. Spesifikasi implementasi harus dicocokkan dengan `MGroupVending.ino`, kontrak API, partition table, dan library display yang benar-benar dipilih.
