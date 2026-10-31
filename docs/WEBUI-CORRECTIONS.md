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
- Format tetap: `ID-A001`, `ID-A002`, dan seterusnya.
- `ID-A` adalah prefix tetap; angka berurutan menggunakan minimal tiga digit dan bertambah otomatis bila melewati 999. Contoh member ke-1120: `ID-A1120`.
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
- Contoh label lokasi yang ditampilkan admin: `Vending48cd1` → **Depan Gedung**, mesin kedua → **Dalam Natura**, mesin ketiga → **Sekolahan**. Nama lokasi adalah metadata yang dapat diubah admin; jangan menganggap lokasi bisa disimpulkan dari MAC.
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
- [x] Member ID otomatis pada demo dengan format `UID-00001`; tidak ada input Member ID manual.
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
- Bagian Audit & Backup hanya dapat diakses Admin super-admin. Member tidak memiliki akun WebUI.
- Label perangkat pada WebUI memakai istilah fungsional seperti Terminal Kasir dan Pengendali Vending; identitas perangkat menggunakan nama netral seperti `CASHIER-01`. Tidak menampilkan nama keluarga chipset/controller pada UI.
- Halaman Perangkat & Koneksi menunjukkan kemampuan operasional, status konektivitas, dan kebijakan offline-first tanpa mengungkap platform hardware yang digunakan.

Prinsip wajib:
- Jangan menampilkan nama chipset, board, model MCU, atau platform hardware pada halaman, tabel, status, notifikasi, pesan error, atau label perangkat yang dilihat admin/teller. Detail tersebut hanya boleh ada pada dokumentasi engineering internal bila diperlukan.
- Nama perangkat, MAC address, status, dan last-seen adalah metadata operasional, bukan mekanisme autentikasi. Produksi tetap memerlukan credential perangkat terdaftar dan heartbeat terautentikasi.
- Jangan mengklaim demo melakukan rekonsiliasi nyata, kontrol hak akses nyata, koneksi provider, atau tindakan server/perangkat fisik.
- Untuk top-up dan jurnal, referensi harus unik; produksi harus menerapkan idempotency, validasi saldo/otorisasi, transaksi database atomik, audit, serta mekanisme reversal—bukan menghapus jejak lama.


## 9. Penyederhanaan Member Identity dan Financial Core (revisi 2026-10-09)

### Member & Identity
- Satu identitas anggota digunakan di seluruh UI: `Member UID` format `UID-00001`, dst.
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



## 11. Kontrak Product ID tetap pada API produksi

Implementasi server/WebUI yang aktif mengikuti kontrak katalog tetap:
- ID publik setiap mesin adalah string `1` sampai `5`; ID yang sama boleh ada pada mesin berbeda.
- API menolak ID produk di luar rentang tersebut. Slot dan kanal servo selalu diturunkan dari Product ID, bukan nilai yang dapat dipilih terpisah.
- Database tetap menyimpan kunci internal produk yang stabil agar data lama dan relasi transaksi tidak perlu dihapus atau dirombak. Katalog API hanya menampilkan identitas publik 1–5 untuk slot valid.
- Produk lama dipetakan menurut slot hasil migrasi yang sudah ada; promosi yang masih memakai ID internal lama tetap dicoba sebagai fallback.
- Pengujian kontrak mencakup pemakaian Product ID 1 pada dua mesin berbeda, pemetaan servo, penolakan ID lama/arbitrer melalui API, dan katalog yang dikonsumsi firmware.
- Endpoint katalog memerlukan kunci perangkat terdaftar untuk firmware atau sesi admin yang tervalidasi untuk WebUI.

Kontrak ini tidak berarti bahwa gerakan servo atau sensor produk fisik telah diuji; pengujian perangkat nyata tetap wajib sebelum vending dioperasikan dengan saldo nyata.


## 8. Detail transaksi per perangkat

- **Vending & Inventory:** riwayat transaksi dan detail dispensing harus berada di halaman Vending & Inventory. Seluruh ringkasan, riwayat, katalog, dan event dispensing wajib mengikuti vending machine yang sedang dipilih pada dropdown; pergantian pilihan harus memperbarui seluruh data terkait secara konsisten.
- Detail transaksi vending minimal mencakup waktu, ID transaksi, produk/Product ID, jumlah, harga satuan, total, metode pembayaran, status pembayaran, status dispensing, referensi pembayaran, dan status/refund jika terjadi kegagalan.
- **Cashier:** sediakan menu/tab terpisah dari Vending & Inventory. Riwayat cashier minimal mencakup waktu, ID transaksi, perangkat, jenis transaksi, nominal, metode, Member, akun/tujuan, referensi, status, dan catatan.
- Ringkasan penerimaan, pengeluaran, dan selisih bersih harus dihitung dari transaksi final yang sah; transaksi menunggu, gagal, dan refund tidak boleh keliru dihitung sebagai penerimaan final. Data demo hanya ilustrasi, sedangkan angka produksi wajib bersumber dari server/ledger.
- Sediakan filter periode, jenis/status transaksi, serta akses Lihat detail. Kegagalan dispensing, status pembayaran, dan refund harus dapat ditelusuri dengan ID/korelasi transaksi yang sama.

## 9. Persistensi sesi login admin untuk WebUI produksi

- Pada build asli WebUI M_GROUP, admin tidak seharusnya diminta login ulang hanya karena halaman di-reload selama sesi autentikasi masih valid.
- Implementasikan sesi persisten dengan mekanisme server yang aman, idealnya cookie sesi HttpOnly, Secure pada HTTPS, dan SameSite yang sesuai; gunakan rotasi/validasi sesi di server, masa berlaku/idle timeout, logout/revocation, dan proteksi CSRF sesuai pola autentikasi aplikasi.
- Jangan menyimpan password admin atau token sesi sensitif di localStorage/sessionStorage. Setelah reload, WebUI memeriksa sesi melalui endpoint server; jika sesi valid, lanjut ke dashboard, jika sudah kedaluwarsa/dicabut, arahkan ke login.
- Terapkan otorisasi server pada setiap endpoint; status login di frontend saja tidak cukup untuk melindungi API.
- Catatan ini adalah persyaratan untuk implementasi asli; demo GitHub Pages tetap merupakan simulasi browser dan bukan bukti autentikasi produksi.

### Implementasi branch demo-parity-member-balance

- API sesi tersedia di `POST /api/v1/auth/login`, `GET /api/v1/auth/session`, dan `POST /api/v1/auth/logout`.
- Sesi menggunakan token acak yang hanya disimpan dalam bentuk hash di SQLite; cookie browser bernama `m_group_session` bersifat HttpOnly dan SameSite=Lax, serta Secure bila request memakai HTTPS.
- Sesi berlaku maksimal 12 jam dan ditolak setelah 30 menit tanpa aktivitas. Logout mencabut sesi di server.
- Permintaan mutasi yang memakai cookie sesi harus berasal dari origin yang sama; endpoint admin tetap menjalankan pemeriksaan otorisasi di server.
- Kredensial awal dibaca dari konfigurasi terlindungi, lalu disalin ke tabel `webui_admin_accounts` saat login pertama. Perubahan username/password disimpan di SQLite; password selalu berupa hash PBKDF2-SHA256. Gunakan `m-group hash-password` untuk membuat hash awal; jangan memasukkan password atau hash ke repository.
- Migrasi `021_webui_sessions.sql` menambahkan tabel sesi dan catatan percobaan login. Installer/upgrade menyiapkan konfigurasi login jika belum tersedia.
- Status implementasi ini tetap harus divalidasi oleh CI dan uji upgrade di lingkungan uji sebelum branch siap digabung.


## 10. Keputusan final aktor dan fitur tertunda (revisi 2026-10-31)

- Hanya ada dua aktor manusia: Admin (satu super-admin sekaligus administrator WebUI) dan Member (client transaksi dengan UID otomatis berurutan dari server).
- Tidak ada akun Operator, Teller, atau Auditor; tidak ada PIN operator maupun pengikatan operator ke Cashier.
- Perangkat Cashier dan Vending memakai autentikasi Device Key, bukan akun manusia.
- Pertamini dan pinjaman tidak diaktifkan dan tidak tampil pada navigasi atau runtime v2.
- Member UID tidak dapat diketik atau diubah Admin; UID berikutnya ditentukan server berdasarkan urutan pendaftaran.
