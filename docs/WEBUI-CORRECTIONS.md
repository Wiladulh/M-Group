# M_GROUP WebUI — Koreksi Desain yang Dikunci

Status: keputusan desain disepakati; demo UI diperbarui secara terpisah dari implementasi backend/firmware.

## 1. Vending & Inventory

- Setiap vending machine memiliki tepat 5 posisi produk tetap, Product ID 1 sampai Product ID 5.
- Katalog tidak menyediakan tombol **Tambah produk**. Admin hanya memilih Product ID 1–5 lalu mengedit nama produk, harga, stok, dan kapasitas.
- Jangan tampilkan input slot atau servo pada WebUI. Pemetaan perangkat bersifat tetap: Product ID 1 → slot/servo 1, ... Product ID 5 → slot/servo 5.
- API dan firmware harus memvalidasi Product ID 1–5 untuk mesin yang dituju. Identitas slot/servo tidak boleh diedit terpisah dari Product ID.
- Setiap mesin memiliki katalog lima posisi sendiri; Product ID yang sama pada mesin berbeda bukan produk yang sama secara global.

## 2. Registrasi Member & NFC

Form tambah member berisi:
1. Nama lengkap.
2. Nomor NIK.
3. Dropdown pemilihan Cashier.
4. Tombol **Scan** di samping dropdown.

Alur pendaftaran credential:
1. Admin memilih cashier lalu menekan Scan.
2. Server membuat sesi enrollment dan mengirim perintah melalui API ke cashier yang dipilih.
3. Layar cashier menampilkan **“Silakan scan kartu”**.
4. Setelah UID NFC terbaca, cashier menampilkan **“Silakan masukkan PIN transaksi”**.
5. PIN transaksi divalidasi untuk mengikat credential NFC dengan member.
6. Server menyimpan UID/credential dan verifier PIN dengan aman, lalu menyelesaikan pendaftaran.

Sesi enrollment harus memiliki timeout, status, korelasi permintaan, dan audit event. UID kartu tidak boleh diketik manual dalam alur normal. PIN asli tidak boleh ditampilkan kembali atau disimpan sebagai teks biasa. Demo browser hanya mensimulasikan alur ini; implementasi nyata memerlukan API server dan dukungan firmware cashier.

## 3. Member ID otomatis

- Member ID tidak dapat diinput atau diedit manual oleh admin.
- Format tetap: `NTR-00001`, `NTR-00002`, dan seterusnya.
- `NTR` adalah prefix tetap; angka lima digit adalah nomor urut pendaftaran. Contoh member ke-1120: `NTR-01120`.
- Nomor dibuat di server/database secara atomik agar pendaftaran bersamaan tidak menghasilkan ID duplikat. Jangan mengandalkan penghitung browser atau jumlah baris UI.
- NIK harus divalidasi dan diberi batasan unik sesuai kebijakan data member.

## 4. Top-up saldo manual

- Di tabel Member Registry, sediakan tombol **+** di sisi saldo simpanan.
- Tombol membuka form top-up dengan nominal, referensi/keterangan, dan konfirmasi admin.
- Top-up nyata harus melalui Financial Core: validasi nominal dan otorisasi, posting kredit ke ledger dengan referensi unik/idempotency, memperbarui saldo secara transaksional, serta mencatat audit event.
- Jangan mengubah saldo secara langsung tanpa ledger. UI demo boleh menyimulasikan alur tetapi harus jelas berlabel DEMO.

## 5. Batas implementasi

Demo HTML tidak terhubung ke backend dan perangkat fisik. Perilaku di atas baru dianggap production-ready setelah API, database/migrasi, autentikasi/otorisasi, audit, dan firmware ESP32 Cashier/Vending mendukungnya. Cloudflare Tunnel bukan prasyarat untuk menguji enrollment NFC lokal secara offline.

## 6. Vending Device Registry & selector dinamis

- Tab **Vending & Inventory** harus memiliki dropdown mesin yang diisi dari daftar vending yang dikenali/terdaftar oleh server; bukan daftar Machine ID statis di HTML.
- Setiap entri mesin mengikat identitas perangkat yang stabil: device name/Machine ID, MAC address, kredensial perangkat terdaftar, status heartbeat/online-offline, dan metadata lokasi/nama tampilan.
- Contoh label lokasi yang ditampilkan admin: `Vending48cd1` → **Depan Natura**, mesin kedua → **Dalam Natura**, mesin ketiga → **Sekolahan**. Nama lokasi adalah metadata yang dapat diubah admin; jangan menganggap lokasi bisa disimpulkan dari MAC.
- Dropdown dan tabel registry menampilkan nama lokasi, device name/Machine ID, MAC, dan status. Mesin offline tetap terlihat agar admin dapat memilih dan memeriksa katalog/stok terakhir yang diketahui, dengan status offline yang jelas.
- Saat mesin dipilih, tabel katalog, stok, dan editor hanya menampilkan data milik mesin tersebut. Setiap mesin memiliki tepat lima Product ID (1–5); Product ID sama pada dua mesin tidak berbagi stok atau konfigurasi.
- MAC address membantu identifikasi, tetapi bukan autentikasi yang cukup karena dapat dipalsukan. Implementasi nyata wajib mengikat perangkat melalui enrollment/credential perangkat dan heartbeat terautentikasi.
- Pada demo GitHub Pages, daftar perangkat dan statusnya adalah data contoh statis di browser untuk memvalidasi UX. Deteksi/registrasi dinamis sebenarnya baru dibuat saat backend M_GROUP diimplementasikan; jangan mengklaim demo melakukan auto-discovery jaringan nyata.

## 7. Alur kerja yang disepakati: DEMO dahulu, implementasi server belakangan

Keputusan proses:
- **Jangan mulai perombakan backend M_GROUP atau firmware untuk butir UI ini sekarang.**
- Sempurnakan dan tinjau demo GitHub Pages terlebih dahulu sampai pengguna menyatakan desain dan alurnya sesuai harapan serta siap diimplementasikan.
- Koreksi berikutnya dilakukan pada demo dan dokumen spesifikasi yang sama, bukan membangun implementasi produksi lebih awal.
- Setelah demo disetujui, gunakan dokumen ini sebagai spesifikasi implementasi untuk server/API/database dan firmware; petakan setiap butir ke pekerjaan implementasi dan tes agar tidak mengulang desain dari awal.
- Label DEMO MODE harus tetap jelas. Data, status, pemindaian NFC, top-up, dan perubahan katalog di browser hanyalah simulasi lokal; jangan mengklaim ada koneksi server/perangkat sungguhan.
- Jangan menghapus atau mengubah baseline sistem M_GROUP yang sudah lulus tes hanya demi perubahan tampilan demo.

### Checklist status demo saat checkpoint 2026-10-09

- [x] Demo berada di `demo/index.html`; URL publik yang dituju: https://wiladulh.github.io/M_GROUP/demo/
- [x] Label DEMO MODE dan batasan simulasi browser.
- [x] Member ID otomatis pada demo dengan format `NTR-00001`; tidak ada input Member ID manual.
- [x] Form member: nama, NIK, dropdown cashier, dan tombol Scan.
- [x] Alur pesan simulasi cashier: “Silakan scan kartu”, lalu “Silakan masukkan PIN transaksi”.
- [x] Tombol + top-up di dekat saldo member; ledger kredit ditambahkan dalam simulasi demo.
- [x] Product ID tetap 1–5; tidak ada tombol tambah produk atau input slot/servo.
- [x] Dropdown vending menampilkan contoh lokasi Depan Natura, Dalam Natura, Sekolahan, device name/Machine ID, MAC, dan status.
- [x] Memilih mesin memfilter katalog dan stok hanya untuk mesin tersebut; data lima Product ID per mesin terpisah.
- [x] Mesin offline tetap ada di dropdown/registry dengan status offline.
- [ ] Tinjauan visual dan interaksi langsung oleh pengguna pada browser.
- [ ] Koreksi lanjutan sesuai umpan balik pengguna.
- [ ] Persetujuan eksplisit pengguna bahwa demo sudah final/siap implementasi.
- [ ] Baru setelah persetujuan: rencana implementasi produksi, lalu server/API/database dan firmware dengan tes terpisah.

Catatan verifikasi terakhir: pemeriksaan sintaks JavaScript dan pemeriksaan kode statis untuk selector dinamis, filter per mesin, tiga nama lokasi contoh, MAC address, status offline, dan lima Product ID lulus. Ini **bukan** pengujian end-to-end di browser dan bukan bukti auto-discovery jaringan nyata.


## 8. Standar kegunaan admin/teller dan penyamaran detail perangkat

Perbaikan demo UI yang ditambahkan:
- Riwayat pembayaran memiliki pencarian dan filter kanal NFC/QRIS serta status; tabel menampilkan referensi transaksi.
- Panel rekonsiliasi demo memisahkan transaksi berhasil, menunggu, gagal, dan refund. Panel ini hanya ringkasan simulasi, bukan rekonsiliasi terhadap provider atau ledger produksi.
- Tabel Member Registry juga menampilkan NIK dan pencarian mencakup Member ID, nama, serta NIK.
- Alur top-up demo meminta nominal, referensi unik, keterangan/sumber setoran, dan konfirmasi sebelum membuat kredit ledger serta audit event. Data hanya hidup selama halaman terbuka.
- Bagian Audit & Backup memuat matriks contoh peran Admin, Teller, dan Auditor. Ini dokumentasi UX saja; produksi harus menegakkan RBAC pada server/API.
- Label perangkat pada WebUI memakai istilah fungsional seperti Terminal Kasir dan Pengendali Vending; identitas perangkat menggunakan nama netral seperti `CASHIER-01`. Tidak menampilkan nama keluarga chipset/controller pada UI.
- Halaman Perangkat & Koneksi menunjukkan kemampuan operasional, status konektivitas, dan kebijakan offline-first tanpa mengungkap platform hardware yang digunakan.

Prinsip wajib:
- Jangan menampilkan nama chipset, board, model MCU, atau platform hardware pada halaman, tabel, status, notifikasi, pesan error, atau label perangkat yang dilihat admin/teller. Detail tersebut hanya boleh ada pada dokumentasi engineering internal bila diperlukan.
- Nama perangkat, MAC address, status, dan last-seen adalah metadata operasional, bukan mekanisme autentikasi. Produksi tetap memerlukan credential perangkat terdaftar dan heartbeat terautentikasi.
- Jangan mengklaim demo melakukan rekonsiliasi nyata, kontrol hak akses nyata, koneksi provider, atau tindakan server/perangkat fisik.
- Untuk top-up dan jurnal, referensi harus unik; produksi harus menerapkan idempotency, validasi saldo/otorisasi, transaksi database atomik, audit, serta mekanisme reversal—bukan menghapus jejak lama.


## 9. Penyederhanaan Member Identity dan Financial Core (revisi 2026-10-09)

### Member & Identity
- Satu identitas anggota digunakan di seluruh UI: `Member ID` format `NTR-00001`, dst.
- Tidak ada Account ID terpisah di antarmuka. Untuk model data saat ini, identitas rekening simpanan utama menggunakan Member ID yang sama; setiap referensi ledger/transaksi mengarah ke Member ID.
- Kolom tabel Member Registry: Member ID, Nama, NIK, Nomor HP, Credential NFC, Status.
- Form pendaftaran menampilkan Member ID otomatis di urutan paling atas (read-only), lalu Nama lengkap, NIK, Nomor HP, pemilihan terminal kasir, dan proses Scan NFC/PIN.
- ID demo mengikuti urutan data yang tersedia; produksi harus menghasilkan ID secara atomik di server/database.

### Financial Core
- Tabel saldo dibuat ringkas: Member ID, Nama, Saldo Simpanan, tombol (+).
- Top-up hanya tersedia dari Financial Core, bukan di Member & Identity.
- Form top-up meminta nominal, referensi unik, keterangan/sumber setoran, dan konfirmasi. Produksi tetap wajib memvalidasi otorisasi dan membukukan jurnal ledger secara atomik; demo hanya mengubah data dalam memori browser.

### Ekspor laporan
- Admin/Teller memilih jenis laporan: Penjualan Vending, Transaksi Kasir, atau Data Member.
- Pilihan rentang: harian `1d`, mingguan `1w`, bulanan `1m`, tahunan `1y`.
- Format timestamp nama file: `HHMMDDMMYY` = jam, menit, tanggal, bulan, dua digit tahun.
- Contoh pola: `vend-HHMMDDMMYY-1d.xlsx`, `cash-HHMMDDMMYY-1m.xlsx`, dan `Memb-HHMMDDMMYY.xls`.
- Ekspor demo membuat file spreadsheet yang dapat dibuka dengan aplikasi spreadsheet. Data sumber tetap data contoh yang tersedia pada browser, bukan query transaksi historis dari server. Implementasi produksi harus menyaring berdasarkan periode waktu sebenarnya dan memasukkan metadata periode/timezone serta total yang dapat direkonsiliasi.
- Kesalahan contoh waktu seperti menit `61` tidak digunakan; timestamp dibuat dari jam sistem saat ekspor sehingga nilai menit selalu valid.

## 10. Dashboard Analytics — Volume Transaksi & Most Used Vending

- Bagian **Volume Transaksi** menyediakan tombol ringkas tanpa dropdown: `1d`, `1w`, `1m`, `3m`, `5m`, `1y`.
- Grafik menggunakan blok/batang biru seperti visualisasi sebelumnya. Makin panjang rentang yang dipilih, makin rapat/kecil lebar batangnya agar skala waktu tetap terbaca: jam untuk 1d, hari untuk 1w/1m, minggu untuk 3m/5m, dan bulan untuk 1y.
- Grafik bergaya trading memakai crosshair/garis penunjuk saat pengguna menyentuh atau menggeser grafik; tooltip mengikuti posisi dan menampilkan waktu, jumlah transaksi, serta estimasi penjualan pada titik itu. Interaksi pointer harus mendukung desktop dan layar sentuh.
- Lebar batang dihitung relatif terhadap jumlah titik dan lebar plot (bukan lebar tetap), dengan jarak proporsional yang konsisten di semua periode. Grafik tidak boleh terlalu rapat pada 1m atau terlalu renggang pada 1y.
- Label sumbu waktu dikurangi secara adaptif agar tidak bertumpuk. Skala vertikal dan nilai tooltip mengikuti data periode terpilih.
- Penjualan yang ditampilkan di demo adalah estimasi ilustratif saja; produksi harus memakai jumlah transaksi dan nominal penjualan agregat sebenarnya.
- Ringkasan total, puncak, dan terendah dibuat kecil dan ditempatkan sejajar di sisi pemilihan periode bila lebar layar cukup.
- Peringkat Most Used Vending hanya menampilkan nama lokasi/mesin yang mudah dikenali, misalnya “Depan Natura”, tanpa ID internal seperti `Vending48cd1`.
- Ringkasan grafik menampilkan total transaksi, puncak trafik, trafik terendah, dan label waktu terjadinya puncak/terendah sesuai periode.
- Bagian **Most Used Vending** ditempatkan setelah grafik volume transaksi dan memberi peringkat mesin berdasarkan jumlah transaksi berhasil selama periode yang dipilih.
- Filter periode harus memengaruhi grafik, metrik puncak/terendah, insight trafik, dan peringkat Most Used Vending secara konsisten.
- Dashboard perlu membantu admin mengidentifikasi jam/hari/bulan dengan trafik tinggi atau rendah untuk mengevaluasi strategi promo. Evaluasi produksi idealnya membandingkan periode sebelum/sesudah promo, tanpa menganggap korelasi sebagai bukti sebab-akibat.
- Definisi produksi: hitung transaksi final berhasil berdasarkan waktu transaksi; keluarkan transaksi pending/gagal/refund sesuai aturan analitik yang disepakati; agregasikan berdasarkan jam, hari, tanggal, atau bulan.
- Demo browser menggunakan data ilustrasi untuk memperlihatkan interaksi dan bentuk visual saja. Angka serta peringkat demo bukan data aktual dan tidak boleh digunakan untuk keputusan bisnis.
- Implementasi produksi memerlukan query agregasi dari backend/database, zona waktu yang konsisten, dan filter periode yang sama untuk semua komponen dashboard.

