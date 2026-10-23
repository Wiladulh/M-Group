# M-Group Rebuild — Master Specification

**Status:** Rebuild specification / implementation contract  
**Language:** Indonesian product UI; technical identifiers may use English  
**Repository:** Wiladulh/M-Group  
**Target:** Clean implementation preserving all agreed features, workflows, WebUI intent, and operational behavior  
**Rule:** This document is the source of truth for the rebuild. If implementation, API, database, firmware, or another document conflicts with it, update the implementation or explicitly revise this specification before coding.

---

## 1. Tujuan dan prinsip rebuild

M-Group dibangun ulang dengan fondasi kode yang bersih, bukan dengan mengorbankan fitur yang telah disepakati. Proyek lama tetap menjadi referensi untuk perilaku bisnis, tampilan, protokol perangkat, dan kebutuhan operasional; kode lama tidak otomatis dianggap benar dan tidak boleh disalin tanpa evaluasi.

Prinsip wajib:

1. Semua fitur yang telah disepakati dipertahankan, termasuk WebUI, Cashier, Vending, layanan server, API, database, firmware ESP32, laporan, backup/restore, instalasi VPS, dan workflow GitHub.
2. **Tidak ada field, parameter, tabel, header, variabel, endpoint, logika, migrasi, dokumentasi, atau test yang bergantung pada device_id.** Penghapusan mencakup backend, database, API, WebUI, firmware, konfigurasi, installer, dokumentasi, dan seluruh test.
3. Autentikasi perangkat menggunakan secret/key yang dibuat dan dikelola server. Secret tidak dikirim ulang atau ditampilkan kembali setelah provisioning. Server memvalidasi key, status, jenis perangkat, dan scope izin; identitas/izin perangkat disimpulkan dari credential yang tervalidasi, bukan dari device_id yang dikirim klien.
4. machine_id boleh tetap digunakan sebagai identitas **entitas bisnis vending** jika dibutuhkan oleh domain. Nilai ini bukan identitas perangkat keras dan tidak boleh menjadi pengganti nama bagi device_id. API vending tidak boleh meminta identitas perangkat keras sebagai pengganti credential.
5. Server adalah sumber kebenaran untuk saldo, ledger, stok, harga, promo yang aktif, transaksi, status pembayaran, izin, dan hasil audit. ESP32 tidak menjadi arsip transaksi utama.
6. Operasi finansial harus aman terhadap retry, request ganda, timeout, dan gangguan jaringan. Gunakan transaksi database, idempotency key, validasi saldo/stok atomik, serta jejak audit.
7. Jangan melakukan migrasi destruktif pada database VPS lama secara otomatis. Backup terlebih dahulu; rebuild baru dikembangkan terpisah dan migrasi/transfer data hanya dilakukan dengan rencana eksplisit.
8. Tidak menyatakan siap rilis hanya karena kode telah berubah. Build, test, workflow, kontrak API, migrasi, UI, firmware, dan fresh-install VPS harus diverifikasi.

## 2. Lingkup produk dan aktor

### 2.1 Aktor

- **Admin/Operator:** mengatur sistem, akun/member, produk, harga, stok, terminal, vending machine, key perangkat, laporan, backup, dan konfigurasi.
- **Operator Cashier:** melakukan transaksi sesuai izin; setoran tabungan memerlukan PIN operator yang dikonfigurasi eksplisit dan PIN NFC member. Tidak ada PIN operator default bersama.
- **Member/Pelanggan:** menggunakan kartu/credential NFC dan PIN yang sesuai untuk transaksi yang memerlukannya, melihat saldo melalui alur yang tersedia.
- **Cashier ESP32:** terminal fisik untuk alur kasir, NFC, pembayaran, setoran tabungan, cek saldo, dan hasil transaksi.
- **Vending ESP32:** mesin penjual otomatis dengan layar/antarmuka perangkat, NFC/payment flow, cek saldo, pilihan produk, pengeluaran barang, dan konfirmasi hasil.
- **Layanan internal:** API, ledger, inventory, payments, device-key management, reporting, backup, audit, dan housekeeping.

### 2.2 Sumber kebenaran

- Server/backend: saldo dan ledger; transaksi dan idempotency; harga/promo yang aktif; stok; hasil dispense/refund; status credential/key; konfigurasi bisnis.
- WebUI: antarmuka administrasi dan monitoring, bukan sumber kebenaran transaksi.
- ESP32: antarmuka fisik, pembacaan input dan pelaksanaan dispense; menyimpan hanya konfigurasi/credential yang diperlukan dan antrean retry terbatas bila dirancang, bukan ledger otoritatif.
- Database: data operasional; backup asli M-Group adalah format pemulihan yang otoritatif.

## 3. Arsitektur target

Implementasi tetap modular dan ringan untuk VPS Linux dengan target minimum proyek saat ini: 2 CPU core, RAM sekitar 315 MB, Python 3.10+, SQLite3, dan POSIX shell. Hindari ketergantungan pada distro Linux, hostname, alamat IP, username, home directory, atau init system tertentu. Service manager (systemd/OpenRC/dll.) boleh dikonfigurasi terpisah.

Lapisan:

1. **WebUI** — HTML/CSS/JavaScript responsif untuk admin/operator, disajikan oleh server.
2. **API** — REST JSON berversi, validasi request/response, autentikasi, otorisasi, rate limiting yang relevan, idempotency, dan error contract konsisten.
3. **Domain services** — members/credentials, balance/ledger, cashier, products/catalog, inventory, vending, payments, device keys, reporting, audit, backup/restore.
4. **Persistence** — SQLite, schema versioning, foreign keys, indeks, transaksi atomik, migrasi yang dapat diulang dengan aman.
5. **Firmware** — firmware terpisah untuk Cashier dan Vending ESP32, protokol API terdokumentasi, penyimpanan key di NVS, timeout/retry dan recovery.
6. **Operations** — installer, konfigurasi environment, health checks, log, backup, restore, CI, release artifact, serta panduan fresh install VPS.

Struktur direktori target (nama dapat disesuaikan jika repository mengharuskan, namun batas modul harus tetap jelas):

- app/api/ — route, request/response schema, dependencies.
- app/core/ — config, database, logging, errors, security, clock.
- app/members/ — member, credential/NFC, PIN policy.
- app/ledger/ — balance, entries, deposits, debits, refunds, corrections.
- app/cashier/ — cashier workflows and transaction orchestration.
- app/catalog/ — product records, images, prices, stock/promo presentation.
- app/inventory/ — stock movements and reconciliation.
- app/vending/ — machines, slot mapping, purchase lifecycle, dispense and refund.
- app/payments/ — payment method/provider adapters and payment states.
- app/device_keys/ — provisioned credential lifecycle; no device_id.
- app/reports/ — filters, aggregation, exports.
- app/audit/ — security and business audit events.
- app/backup/ — native backup, manifest, checksum, restore validation.
- app/webui/ — HTML, CSS, JavaScript, image serving.
- migrations/ — schema migrations.
- esp32/cashier/ and esp32/vending/ — separate firmware and setup docs.
- tests/ — unit, API, integration, migration, UI-contract, and regression tests.
- docs/ — this specification and operational/API documents.
- scripts/ — installer, maintenance and release helpers.
- .github/workflows/ — CI, validation and release workflows.

## 4. WebUI: navigasi, tab, isi dan tindakan

UI harus konsisten, responsif, berbahasa Indonesia, dan mempertahankan seluruh fungsi yang telah disepakati. Setiap tab mempunyai status loading, empty state, error state, validasi form, konfirmasi tindakan berisiko, dan notifikasi hasil. Daftar panjang memakai pencarian/filter/paginasi yang sesuai. Tombol yang tampil harus benar-benar berfungsi; jangan menampilkan kontrol dummy.

### 4.1 Dashboard / Ringkasan

- Ringkasan saldo/aktivitas agregat yang diizinkan, transaksi hari ini, setoran, pembayaran Cashier, penjualan Vending, refund, produk/stok kritis, status layanan, dan waktu backup terakhir.
- Filter tanggal/periode dan akses cepat ke laporan.
- Ringkasan tidak boleh mengungkap PIN, secret key, atau data credential sensitif.
- Angka keuangan harus berasal dari agregasi server dan mempunyai definisi yang konsisten dengan laporan.

### 4.2 Member / Anggota

- Daftar member: pencarian, filter status, detail, tambah/edit, aktif/nonaktif, dan riwayat transaksi sesuai izin.
- Identitas member dan credential NFC dikelola terpisah; jangan menyimpan UID NFC mentah di URL/log. Kirim credential identifier dalam body request bila diperlukan.
- Pengaturan PIN member melalui alur aman: tidak menampilkan PIN yang sudah ada; simpan bentuk hash yang sesuai; batasi percobaan.
- Detail member menampilkan saldo terkini dari ledger, ringkasan transaksi, setoran, debit, refund/koreksi, dan riwayat yang diizinkan.
- Top-up/koreksi harus mempunyai alasan, operator, referensi transaksi terkait bila relevan, idempotency, dan audit trail. Koreksi tidak boleh mengubah saldo secara langsung tanpa ledger entry.

### 4.3 Produk / Katalog

Tampilan produk wajib mendukung pengeditan langsung per baris atau panel edit yang jelas. Setiap baris menampilkan:

- **Image** — thumbnail gambar dan tombol **Upload** di samping produk.
- Nama produk.
- Harga.
- Stok.
- Promo NFC.
- Promo QRIS.

Aturan:

- Setiap produk memiliki paling banyak satu gambar aktif untuk ditampilkan di layar vending; batas file gambar maksimum **2 MB**.
- Validasi ukuran, format gambar yang diizinkan, MIME type, dan isi file dilakukan di server; jangan hanya mempercayai ekstensi.
- Gambar bisa diganti, dihapus, dan dipratinjau; kegagalan upload tidak boleh menghapus gambar lama.
- Produk dapat dibuat, diedit, diaktifkan/nonaktifkan, dan diurutkan/diidentifikasi untuk tampilan mesin.
- Harga disimpan sebagai integer unit mata uang terkecil, bukan floating point.
- **Promo NFC dan Promo QRIS untuk tahap awal selalu 0% / belum diterapkan.** UI tetap menyediakan kolomnya agar pengembangan promo nanti tidak memerlukan desain ulang. Jangan mengurangi harga selama fitur promo belum diaktifkan secara resmi.
- Validasi harga non-negatif, stok tidak negatif kecuali ada kebijakan eksplisit, dan perubahan harga/stok dicatat bila berdampak operasional.
- Gambar dikirim ke vending melalui mekanisme yang hemat bandwidth; perangkat tidak harus menyimpan seluruh katalog beresolusi besar bila kapasitas terbatas.

### 4.4 Cashier / Kasir

- Konfigurasi kasir/terminal, lokasi atau nama tampilan, status aktif, dan penetapan izin tanpa field device_id.
- Alur transaksi NFC, cek saldo, pembayaran sesuai metode yang diaktifkan, setoran tabungan, koreksi/top-up yang berizin, dan hasil transaksi.
- Setoran tabungan wajib meminta PIN operator yang telah dikonfigurasi eksplisit serta PIN NFC member. Tidak ada PIN default bersama.
- Riwayat transaksi dengan filter waktu, metode, operator, status, dan pencarian referensi.
- Status transaksi yang pending/timeout harus dapat direkonsiliasi; jangan meminta pelanggan mengulang debit secara membabi buta.
- Kontrol sensitif membutuhkan autentikasi/otorisasi operator dan audit log.

### 4.5 Vending / Mesin Penjual

- Daftar mesin sebagai entitas bisnis: nama, lokasi, status, produk/slot, stok, transaksi terakhir, dan status koneksi/heartbeat bila tersedia.
- Pengelolaan mapping produk publik ke slot fisik servo. Untuk perangkat yang menggunakan lima slot tetap, public Product ID **1–5** dipetakan ke slot/channel servo; ID internal database tidak diekspos ke firmware.
- Mesin dapat dikelola/diaktifkan/nonaktifkan tanpa mengaitkan entitas bisnis dengan device_id.
- Detail mesin menampilkan produk, gambar, harga, stok, penjualan, kegagalan dispense, refund, dan log kesehatan.
- Kunci autentikasi mesin diatur melalui alur provisioning aman; tidak ada input manual device_id.

### 4.6 Perangkat / Device Keys

- Menghasilkan key provisioning satu kali dari server untuk jenis/scope yang benar (Cashier atau Vending).
- Menampilkan plaintext key hanya pada saat pembuatan; setelah ditutup tidak dapat dibaca kembali. Sediakan salin/unduh sekali bila sesuai kebijakan UI.
- Simpan hash key di server; tampilkan hint/non-secret metadata saja.
- Daftar credential: jenis, nama tampilan/lokasi, status, dibuat, terakhir terlihat, rotasi/revoke, dan audit event. Tidak ada kolom atau filter device_id.
- Provisioning harus mengikat credential ke jenis dan scope/izin; key Cashier tidak boleh dipakai sebagai Vending dan sebaliknya.
- Revoke/rotate harus membuat key lama tidak berlaku; rotasi mempunyai prosedur recovery.
- Jangan mencatat key plaintext pada log, URL, analytics, test output, atau laporan.

### 4.7 Laporan / Audit Transaksi

- Filter harian, mingguan, bulanan, rentang tanggal, sumber **CASHIER** atau **VENDING**, metode pembayaran, status, dan jenis transaksi.
- Kategori sumber transaksi wajib konsisten: **CASHIER** mencakup setoran tabungan dan pembayaran NFC Cashier; **VENDING** mencakup pembelian vending, hasil dispense, dan refund.
- Tampilkan total, rincian, status, referensi, operator/entitas yang relevan, dan rekonsiliasi ledger.
- Retensi transaksi operasional server adalah **12 bulan**, dengan backup/archive sebelum purge. Jangan melakukan purge bila archive/backup yang diwajibkan belum diverifikasi.
- Export XLSX kompatibel Excel dengan kolom stabil, timestamp konsisten, filter yang tercatat, dan data yang tidak mengungkap secret/PIN.
- Koreksi finansial harus dicatat sebagai transaksi koreksi terpisah dan mempunyai alasan serta jejak audit.

### 4.8 Backup / Restore

- Buat backup native M-Group yang berisi database dump, manifest, versi schema/aplikasi, timestamp, dan checksum; boleh menyertakan export yang kompatibel Excel.
- Validasi integritas backup sebelum menganggap berhasil.
- Restore harus memvalidasi checksum, versi, schema, dan integritas sebelum mengganti database aktif.
- Sediakan mode pemeriksaan/validasi dan konfirmasi eksplisit sebelum restore destruktif.
- Excel bukan format pemulihan utama. Import Excel hanya boleh melalui validasi ketat dan tidak menggantikan native backup.
- Jangan pernah memasukkan secret key, PIN, atau file konfigurasi sensitif ke dalam arsip tanpa desain keamanan yang eksplisit.

### 4.9 Pengaturan / Settings

- Konfigurasi nama sistem, zona waktu, parameter operasional, retensi, batas upload gambar, konfigurasi PIN operator, payment provider/method yang diaktifkan, dan parameter keamanan.
- Rahasia dikelola melalui environment/config secret, tidak ditampilkan kembali dan tidak di-commit ke repository.
- Pengaturan yang memengaruhi transaksi harus divalidasi, diaudit, dan memiliki nilai default aman.
- Tidak boleh ada penghapusan variabel token lama yang masih menjadi syarat runtime baru; bersihkan konfigurasi lama secara konsisten dan dokumentasikan perubahan.

### 4.10 Status Sistem / Logs

- Health status API/database, versi aplikasi, status layanan, kapasitas disk bila tersedia, hasil backup terakhir, dan ringkasan workflow/deployment jika tersedia.
- Log terstruktur, timestamp jelas, level log, correlation/request ID yang tidak sensitif.
- Redaksi key, PIN, credential NFC, dan data rahasia.
- Pesan error UI harus dapat ditindaklanjuti tanpa membocorkan stack trace atau secret.

## 5. WebUI Cashier dan Vending pada perangkat fisik

### 5.1 Cashier ESP32

Alur layar minimum:

1. Boot/self-check dan koneksi Wi-Fi.
2. Status server dan status provisioning/authentication.
3. Menu utama dengan tindakan yang jelas.
4. **Cek Saldo** sebagai pilihan menu tingkat utama.
5. Pembacaan kartu NFC dan PIN jika dibutuhkan kebijakan.
6. Tampilkan saldo dari server, timestamp/respons status, dan tombol kembali/selesai.
7. Pembayaran/transaksi sesuai alur yang diaktifkan.
8. Setoran tabungan dengan PIN operator dan PIN member.
9. Tampilkan hasil transaksi sukses/gagal/pending secara tegas dengan reference bila ada.
10. Pemulihan koneksi, retry aman, dan penanganan timeout.

Saldo tidak boleh dihitung atau diambil dari cache lokal sebagai sumber kebenaran. Cegah saldo member terlihat setelah sesi selesai; hapus data sensitif dari layar dan RAM bila memungkinkan.

### 5.2 Vending ESP32

Alur layar minimum:

1. Boot/self-check, koneksi, dan autentikasi key.
2. Sinkronisasi katalog dan status mesin.
3. Layar katalog produk dengan gambar produk, nama, harga, dan stok yang tersedia.
4. **Cek Saldo** tersedia pada menu utama/layar yang mudah dijangkau, tidak tersembunyi di menu admin.
5. Pembacaan NFC/PIN sesuai kebijakan; saldo diambil dari server dan ditampilkan tanpa membuat debit.
6. Pilih produk; validasi harga/stok dan otorisasi pembayaran di server.
7. Buat transaksi dengan idempotency key; server mencatat status payment/ledger sesuai desain.
8. Jalankan dispense hanya sesuai protokol status transaksi yang disepakati.
9. Kirim hasil dispense ke server; sukses menutup transaksi, gagal memulai proses refund/reversal yang aman sesuai status debit.
10. Timeout/offline: jangan melakukan debit ganda; tampilkan status tidak pasti/pending dan lakukan rekonsiliasi.

**Persyaratan cek saldo untuk kedua jenis perangkat:** cek saldo merupakan operasi baca, tidak boleh membuat debit, tidak boleh mengurangi stok, tidak boleh dianggap sebagai pembelian, dan tidak boleh memerlukan pemilihan produk. Log akses yang diperlukan tidak boleh menyimpan PIN atau UID NFC mentah.

## 6. Backend dan tanggung jawab layanan

| Modul | Tanggung jawab |
|---|---|
| Core/config | Konfigurasi, environment, startup, error handling, logging, request ID, clock/timezone. |
| Database | Koneksi, transaksi, foreign key, schema version, migrasi aman, backup consistency. |
| Auth/security | Verifikasi sesi admin/operator dan key perangkat, hashing secret, role/scope, rate limiting, redaksi log. |
| Device keys | Generate/provision/rotate/revoke key; simpan hash; scope ke Cashier/Vending; tanpa device_id. |
| Members | CRUD member, status, credential NFC, PIN lifecycle, pembatasan percobaan. |
| Ledger/balance | Saldo turunan dari ledger, credit/debit, deposit, refund, correction, atomicity, reconciliation. |
| Cashier | Orkestrasi transaksi kasir, cek saldo, setoran, pembayaran, status dan idempotency. |
| Catalog/products | Produk, harga, image upload/validation/serving, status, promo placeholders. |
| Inventory | Stok, stock movement, reservasi/pengurangan atomik, rekonsiliasi. |
| Vending | Mesin bisnis, slot mapping, purchase state machine, dispense result, refund/reversal. |
| Payments | Metode NFC dan QRIS/provider adapter, status pending/success/failed, callback verification jika relevan. |
| Reports | Agregasi dan filter, laporan CASHIER/VENDING, export XLSX, batas akses. |
| Audit | Perubahan konfigurasi, transaksi sensitif, provisioning, revoke, restore, koreksi. |
| Backup/restore | Native archive, manifest, checksum, validation, restore aman, archive sebelum purge. |
| WebUI/static | UI asset, API client, form, validasi, navigasi, aksesibilitas dan feedback. |
| Housekeeping | Retensi 12 bulan, archive verification, pembersihan aman, health tasks. |

### 6.1 Ledger dan saldo

- Saldo member adalah hasil ledger yang otoritatif, bukan kolom yang dapat diedit bebas.
- Semua debit/kredit harus menghasilkan ledger entry immutable dengan reference unik, jenis transaksi, amount integer, timestamp, source, status, dan metadata audit yang diperlukan.
- Jika saldo disimpan sebagai cache/materialized value untuk performa, cache harus diperbarui dalam transaksi yang sama dan dapat direkonsiliasi dari ledger.
- Tolak debit bila saldo tidak cukup; pemeriksaan dan debit harus atomik.
- Refund/reversal membuat entry kompensasi yang terkait dengan transaksi awal; jangan menghapus atau menulis ulang transaksi yang telah terjadi.
- Idempotency key unik dalam scope transaksi; replay dengan payload sama mengembalikan hasil yang sama, sedangkan key sama dengan payload berbeda ditolak.
- Gunakan status eksplisit untuk transaksi yang menunggu konfirmasi eksternal atau hasil dispense.

### 6.2 State machine vending

State minimal yang harus dimodelkan secara eksplisit: created → payment_pending (bila diperlukan) → paid/authorized → dispense_pending → dispensed atau dispense_failed → completed / refund_pending / refunded / needs_reconciliation.

Nama status final dapat disesuaikan, tetapi transisi harus dibatasi dan tercatat. Jangan menjalankan dispense sebelum syarat otorisasi pembayaran dipenuhi. Kegagalan jaringan setelah dispense memerlukan rekonsiliasi, bukan debit ulang otomatis.

### 6.3 Image service

- Batas maksimum 2 MB per gambar produk.
- Whitelist format, validasi MIME dan signature, normalisasi nama file, cegah path traversal, dan simpan dengan nama internal acak/terkontrol.
- Batasi ukuran dimensi/decompression untuk menghindari file image bomb.
- Gambar publik yang diperlukan vending hanya boleh memuat informasi produk; jangan melayani file path arbitrary.
- Cache/version gambar harus memungkinkan firmware mendeteksi perubahan gambar tanpa mengunduh ulang semuanya.

## 7. Autentikasi dan penghapusan device_id

Ini adalah persyaratan migrasi paling penting.

### 7.1 Model credential

- Admin/operator WebUI menggunakan sesi autentikasi sesuai model server yang dipilih; token lama tidak boleh diam-diam diterjemahkan menjadi sesi test.
- Perangkat fisik menggunakan key yang dibuat server dan diprovision sekali ke ESP32. Server hanya menyimpan hash key dan metadata non-secret.
- Key terkait dengan jenis dan izin, misalnya cashier atau vending, serta entitas/lokasi yang relevan melalui relasi domain yang tidak memakai device_id.
- Client mengirim credential melalui header autentikasi yang ditetapkan dalam kontrak API, melalui HTTPS dalam deployment produksi.
- Server memperoleh konteks terminal/izin dari credential yang terautentikasi; client tidak boleh memilih identitas/role hanya dengan mengirim string ID.
- Revoke/rotate, rate limit, audit, dan mekanisme recovery harus tersedia.

### 7.2 Penghapusan global

Tidak boleh ada referensi runtime atau schema ke device_id pada:

- tabel/kolom/indeks/foreign key database dan migration;
- model, repository, service, API request/response, path parameter, header, query parameter;
- WebUI HTML/JS, label/form, filter, tabel, local storage, fixture;
- firmware Cashier/Vending, provisioning portal, NVS mapping, URL dan JSON body;
- installer, environment template, shell scripts, CI workflow;
- test, mocks, conftest, snapshots, demo UI;
- docs, checklist, API examples, README, comments, generated artifacts.

Pengecualian hanya diperbolehkan pada dokumen historis/arsip yang sengaja dipertahankan dan jelas diberi label **historis, bukan kontrak aktif**. Tidak boleh ada kode aktif yang mendukung kompatibilitas lama. Saat menyatakan bersih, lakukan pencarian repository-wide untuk variasi nama/kapitalisasi dan periksa hasilnya secara manual.

### 7.3 Jangan salah menghapus konsep yang berbeda

- device_id adalah identitas perangkat keras/credential lama yang harus dihilangkan.
- machine_id adalah ID entitas bisnis mesin vending, jika masih diperlukan.
- product_id, member_id, transaction_id, dan operator_id adalah identitas domain yang terpisah dan tidak otomatis dihapus.
- Jangan mengganti nama device_id menjadi hardware_id, terminal_device_id, atau sinonim lain untuk mempertahankan desain lama. Bila diperlukan nama terminal bisnis, definisikan sebagai entitas bisnis dengan alasan yang jelas, bukan identitas perangkat tersembunyi.

## 8. Kontrak API

Semua endpoint di bawah adalah **kontrak target** untuk implementasi baru; path/field final harus disatukan di OpenAPI/API reference dan diuji. Gunakan prefix /api/v1, JSON, skema validasi eksplisit, error envelope konsisten, dan timestamp ISO-8601 UTC. Jangan mengekspos detail internal atau secret.

### 8.1 Health dan admin session

- GET /health — status liveness dasar.
- GET /ready — readiness termasuk database dan dependency wajib.
- Endpoint login/logout/session admin/operator sesuai implementasi autentikasi yang dipilih.
- Endpoint administrasi memerlukan role/scope yang sesuai; health publik tidak boleh membocorkan konfigurasi.

### 8.2 Members dan balance

- CRUD/list/detail member dengan filter dan paginasi.
- Endpoint credential NFC: assign/replace/revoke sesuai izin.
- Endpoint set/change PIN tanpa mengembalikan PIN.
- GET /api/v1/members/{member_id}/balance — saldo dari server, akses dibatasi dan respons minimal.
- Endpoint riwayat ledger/transaksi member dengan paginasi.
- Endpoint top-up/koreksi jika diaktifkan, selalu dengan idempotency, operator, alasan, dan audit.

### 8.3 Device key provisioning

- Endpoint admin untuk generate key sekali, list metadata, rotate dan revoke.
- Provisioning response mengembalikan plaintext secret hanya pada saat key dibuat.
- Endpoint autentikasi perangkat memvalidasi key dan memberi konteks izin/credential; tidak menerima atau mensyaratkan device_id.
- Tidak boleh ada endpoint registrasi yang memaksa ESP32 mengirim ID turunan dari MAC address.

### 8.4 Cashier

- Endpoint untuk cek saldo dengan credential NFC di request body yang terlindungi; operasi read-only.
- Endpoint pembayaran Cashier dan setoran tabungan, masing-masing dengan validasi PIN sesuai kebijakan.
- Endpoint status transaksi dan rekonsiliasi setelah timeout.
- Transaksi setoran membutuhkan PIN operator yang telah dikonfigurasi dan PIN member.
- Setiap mutasi keuangan memerlukan idempotency key dan menghasilkan transaction reference.

### 8.5 Products/images/inventory

- CRUD produk dan listing katalog yang dapat diakses role/perangkat berizin.
- Upload, replace, delete, dan retrieve image dengan batas 2 MB.
- Endpoint stok/stock movement dan rekonsiliasi yang tidak mengizinkan nilai negatif tanpa aturan eksplisit.
- Promo NFC/QRIS tetap 0% pada rilis awal; API tidak boleh menerapkan diskon secara implisit.

### 8.6 Vending

- List/detail mesin bisnis, status, produk-slot mapping, dan health/heartbeat sesuai kebutuhan.
- Mulai transaksi vending dengan product public ID, credential/payment context, dan idempotency key.
- Ambil status transaksi; laporkan hasil dispense; minta/konfirmasi refund atau reversal sesuai state machine.
- Cek saldo tersedia sebagai operasi terpisah dari pembelian.
- Key menentukan scope mesin/terminal; API tidak meminta hardware device_id.

### 8.7 Payments

- Adapter untuk metode yang diaktifkan, termasuk NFC dan QRIS sesuai cakupan produk.
- QRIS harus memvalidasi callback/status dari provider berdasarkan mekanisme resmi provider; jangan percaya callback tanpa verifikasi.
- Pisahkan payment state dari dispense state agar kegagalan mesin tidak merusak rekonsiliasi pembayaran.
- Promo QRIS/NFC belum diterapkan dan tetap 0% sampai ada persetujuan fitur dan aturan harga.

### 8.8 Reports, audit, backup

- Endpoint laporan dengan rentang tanggal, filter sumber CASHIER/VENDING, metode/status, dan paginasi bila perlu.
- Endpoint export XLSX.
- Endpoint audit hanya untuk role yang berwenang.
- Endpoint backup, list/validate/restore hanya untuk admin dengan konfirmasi dan audit.
- Endpoint purge/retention harus mensyaratkan archive yang tervalidasi.

### 8.9 API error contract

Gunakan bentuk konsisten seperti { "error": { "code": "...", "message": "...", "request_id": "..." } }. Kode yang perlu dibedakan meliputi unauthenticated, forbidden, invalid input, not found, conflict/idempotency mismatch, insufficient balance, out of stock, payment pending/failed, dispense pending/failed, rate limited, dan internal error. Detail internal/stack trace tidak dikirim ke client.

### 8.10 Keamanan transport dan privasi

- HTTPS untuk deployment produksi; jangan mengirim key atau PIN lewat plaintext network publik.
- NFC UID/credential mentah tidak diletakkan di URL/path/query atau log.
- Jangan pernah mengembalikan key plaintext setelah provisioning atau mengembalikan PIN.
- Validasi ukuran request, tipe data, content type, role, status key, dan scope setiap endpoint.
- CORS, cookie/session flags, CSRF protection bila cookie digunakan, dan rate limiting ditetapkan berdasarkan model autentikasi.
- Dokumentasikan threat model dan asumsi bahwa secret yang diekstrak dari perangkat dapat dicabut/dirotasi.

## 9. Database: domain dan invariant

Nama tabel final boleh mengikuti implementasi, tetapi domain dan relasi berikut harus tercakup:

- Members dan status member.
- NFC credentials/token references (hindari penyimpanan data sensitif yang tidak perlu).
- PIN hashes, failed-attempt counters/cooldown bila diperlukan.
- Admin/operator accounts, roles/permissions, sessions.
- Device keys: key hash, hint, kind/scope, status, creation/last-seen/revocation metadata; **tanpa device_id**.
- Vending machines sebagai entitas bisnis dan relasi ke lokasi/produk/slot bila dibutuhkan; tanpa foreign key ke device_id.
- Products: name, description bila dibutuhkan, integer price, image metadata, active status, promo placeholders.
- Inventory/stock movements.
- Ledger entries dan transaction records.
- Cashier operation records, vending purchases, dispense outcomes, payment records, refunds/reversals.
- Idempotency records dengan scope dan payload fingerprint.
- Audit events.
- App/schema settings.
- Backup/retention/archive metadata.

Invariant database:

1. Foreign keys aktif dan diuji.
2. Unique constraints untuk idempotency scope, key hash, dan reference yang harus unik.
3. Amount integer; timestamp format konsisten.
4. Status transaksi dibatasi ke nilai yang dikenal dan transisi divalidasi service.
5. Jangan hapus transaksi finansial untuk memperbaiki kesalahan; buat reversal/correction.
6. Migrasi mempunyai versi, dapat dijalankan berurutan pada database kosong, dan punya rencana upgrade/rollback.
7. Tes fresh install wajib dimulai dari database kosong; tes upgrade harus memakai salinan fixture database yang aman.
8. Data produksi, key, credential, backup produksi, dan konfigurasi rahasia tidak masuk Git.

## 10. Firmware ESP32 dan protokol perangkat

- Pisahkan firmware Cashier dan Vending; gunakan shared library hanya untuk komponen yang benar-benar sama.
- Wi-Fi setup portal meminta SSID/password, URL server, dan provisioning key satu kali; tidak meminta device_id.
- Setup credential disimpan aman di NVS; key tidak ditampilkan kembali setelah disimpan.
- Boot menguji koneksi, autentikasi, konfigurasi, dan versi protokol; jika autentikasi gagal, blokir transaksi.
- HTTP timeout, retry exponential/backoff, batas percobaan, dan idempotency harus konsisten dengan API.
- Jangan membuat idempotency key dari device_id; gunakan random/persisted transaction nonce atau sequence yang scoped dengan credential dan aman terhadap reboot.
- Jangan retry operasi finansial dengan key baru ketika hasil request sebelumnya belum diketahui.
- Vending memetakan public Product ID 1–5 ke slot/servo bila hardware target memakai lima slot; mapping terdokumentasi dan tidak mengekspos database key internal.
- Hasil dispense harus dikirim ke server; bila server tidak terjangkau setelah dispense, simpan event pending secara terbatas untuk rekonsiliasi tanpa mengeksekusi dispense ulang.
- Firmware harus menangani gambar produk sesuai batas memori/bandwidth, mendukung cache/invalidation, dan tetap menyediakan fallback nama/harga bila gambar gagal diunduh.
- Semua pesan serial/log firmware harus menghindari key, PIN, dan credential NFC mentah.

## 11. Installer, konfigurasi dan VPS

- Installer POSIX shell, aman untuk diulang, memberi pesan error yang jelas, dan tidak bergantung pada distro atau system manager tertentu.
- Validasi versi Python, SQLite, direktori data, izin file, kapasitas disk, dan environment sebelum mengubah sistem.
- Pisahkan source/app, data, log, backup, dan secrets/config.
- Default bind ke loopback (misalnya 127.0.0.1) kecuali konfigurasi secara eksplisit mengubahnya. Untuk akses LAN, ikat interface yang sesuai dan batasi firewall ke jaringan tepercaya.
- Reverse proxy/tunnel seperti Cloudflare Tunnel dapat dikonfigurasi terpisah; aplikasi tidak boleh mengasumsikan ICMP proxy aktif. Dokumentasikan warning ICMP sebagai non-fatal bila layanan HTTP tetap berjalan.
- Installer tidak boleh mencetak secret ke log atau shell history. File konfigurasi rahasia memakai permission ketat.
- Health/readiness checks, restart policy, log rotation, backup schedule, disk-space warning, dan prosedur restore harus terdokumentasi.
- Fresh-install checklist mencakup admin awal yang aman, konfigurasi operator PIN, provisioning key Cashier/Vending, konfigurasi URL server, dan uji konektivitas.
- Tidak ada database VPS lama yang ditimpa otomatis saat fresh install atau rebuild.

## 12. Testing, CI dan quality gates

Jalankan pengujian secara bertahap; perubahan kode tidak boleh dinyatakan selesai hanya berdasarkan pencarian teks atau pemeriksaan visual.

### 12.1 Test suites

- Unit tests: balance/ledger, idempotency, auth scope, pricing, stock, image validation, state machine, refund/reversal, retention.
- API tests: auth, validation, status code/error envelope, role checks, endpoint response schema.
- Database tests: fresh migrations, upgrade path, foreign keys, constraints, rollback on failure.
- Integration tests: Cashier balance check, savings deposit, NFC payment, Vending purchase, dispense success/failure, refund, network timeout/retry.
- WebUI tests/checklist: semua tab, tombol, form, upload image, filter, loading/empty/error state, responsive layout.
- Firmware checks/builds: Cashier and Vending compile, provisioning, auth failure, offline retry, idempotency, balance screen, vending display.
- Backup/restore tests: checksum, corrupted archive rejection, successful restore, archive-before-purge.
- Security regression tests: key tidak masuk log, PIN tidak dikembalikan, scope key salah ditolak, rate limit, akses tanpa autentikasi ditolak.
- Repository-wide forbidden-reference scan untuk device_id, diikuti pemeriksaan manual hasil pencarian agar tidak ada referensi aktif tersisa.

### 12.2 GitHub Actions

- Workflow harus dipisah dengan jelas untuk lint/static checks, backend tests, migration tests, firmware build, UI checks bila tersedia, dan packaging/release.
- Workflow tidak boleh bergantung pada secret produksi untuk test normal.
- Test config tidak boleh mengubah header/token lama menjadi sesi palsu; test harus menggunakan mekanisme auth baru secara eksplisit.
- Workflow gagal harus diperbaiki berdasarkan log akar masalah, bukan disembunyikan atau dilewati.
- Gunakan dependency pinning yang masuk akal, cache yang tidak merusak determinisme, dan artifact bernama jelas.
- Branch rebuild terpisah dari main; perubahan besar masuk lewat PR dengan ringkasan, test evidence, migration note, dan checklist.

### 12.3 Definisi selesai

Sebuah modul selesai bila:
- implementasi, schema, API contract, UI/firmware yang relevan dan dokumentasi selaras;
- test modul dan regression tests lulus;
- tidak ada credential/secret yang bocor;
- transaksi retry-safe dan tercatat;
- tidak ada referensi aktif device_id;
- workflow terkait lulus;
- prosedur install/upgrade dan rollback terdokumentasi;
- perubahan ditinjau dan dapat diuji ulang oleh pihak lain.

## 13. Rencana fase rebuild

### Fase 0 — Kunci spesifikasi dan inventaris fitur
- Inventaris fitur/UI/API/database/firmware dari proyek lama dan percakapan keputusan.
- Petakan fitur: dipertahankan, diperbaiki, atau diubah sesuai dokumen ini.
- Catat semua konflik/ketidakpastian sebagai pertanyaan keputusan; jangan menebak perilaku finansial yang berdampak nyata.
- Tetapkan acceptance criteria per fitur.

### Fase 1 — Repository dan fondasi
- Branch rebuild terpisah; format/lint, konfigurasi, error handling, logging, CI minimal.
- Struktur modular, schema versioning, database kosong, migrations, health/readiness.
- Implementasi auth admin/operator dan pola credential perangkat tanpa device_id.

### Fase 2 — Domain member dan ledger
- Members/NFC/PIN, ledger, balance, idempotency, audit, koreksi.
- Uji atomicity, saldo tidak cukup, duplikasi request, rollback dan recovery.

### Fase 3 — Produk, gambar dan inventory
- UI edit produk, upload image 2 MB, harga/stok, promo NFC/QRIS 0%, inventory movements.
- Kontrak katalog yang bisa digunakan WebUI dan firmware.

### Fase 4 — Cashier
- API dan UI kasir, cek saldo pada Cashier WebUI/ESP32, pembayaran, setoran tabungan dengan PIN operator dan member, riwayat serta timeout recovery.

### Fase 5 — Vending
- Mesin bisnis, slot mapping, katalog bergambar, cek saldo pada Vending UI/ESP32, pembelian, dispense, hasil dispense, refund/reconciliation.

### Fase 6 — Payments dan integrasi
- NFC dan QRIS/payment provider sesuai cakupan yang telah disepakati; verifikasi status/callback; belum menerapkan promo.
- Uji kegagalan jaringan dan state transition.

### Fase 7 — Reports, backup dan admin
- Laporan day/week/month, filter CASHIER/VENDING, XLSX, backup native, restore, audit, retention 12 bulan dengan archive.

### Fase 8 — Firmware hardening dan WebUI completeness
- Compile kedua firmware, test provisioning/revoke/rotate, retry, gambar, balance screen, seluruh tab dan tombol UI.
- Tidak ada fitur yang hanya berupa placeholder kecuali promo 0% yang memang sengaja disiapkan untuk tahap berikutnya.

### Fase 9 — VPS staging dan release candidate
- Fresh install pada lingkungan staging kosong.
- Smoke test end-to-end, migrasi, backup/restore, HTTPS/network configuration, logs, service restart.
- Repository-wide scan untuk device_id dan tinjauan manual.
- Semua GitHub workflows lulus; dokumentasikan hasil serta isu yang belum selesai.

### Fase 10 — Cutover terkendali
- Backup database dan konfigurasi lama, verifikasi backup.
- Rencanakan migrasi data hanya jika diperlukan dan disetujui; jangan menyalin schema lama secara buta.
- Deploy dengan rollback path yang diuji; jangan menghapus proyek lama atau data lama sampai sistem baru stabil dan pengguna menyetujui.

## 14. Acceptance checklist final

### Produk dan WebUI
- [ ] Semua tab dan alur yang disepakati tersedia.
- [ ] Daftar produk menampilkan image, nama, harga, stok, promo NFC, promo QRIS.
- [ ] Tombol upload gambar berada di samping tiap produk; maksimal 2 MB.
- [ ] Promo NFC/QRIS tetap 0% dan tidak memengaruhi harga.
- [ ] UI responsif, semua tombol aktif, error/loading/empty state tersedia.

### Cashier
- [ ] Cek saldo tersedia di Cashier WebUI dan perangkat Cashier.
- [ ] Cek saldo read-only dan tidak membuat transaksi debit.
- [ ] Pembayaran dan setoran mengikuti izin yang benar.
- [ ] Setoran membutuhkan PIN operator yang dikonfigurasi dan PIN NFC member.
- [ ] Riwayat, idempotency, timeout, dan audit bekerja.

### Vending
- [ ] Cek saldo tersedia di Vending UI/perangkat.
- [ ] Katalog dapat menampilkan satu gambar produk per item.
- [ ] Slot/product mapping jelas; internal database key tidak bocor ke firmware.
- [ ] Pembelian, dispense result, kegagalan, refund dan rekonsiliasi diuji.
- [ ] Timeout tidak menyebabkan debit atau dispense ganda.

### Backend/API/database
- [ ] Ledger menjadi sumber saldo; transaksi atomik dan idempotent.
- [ ] Kontrak API terdokumentasi dan tervalidasi.
- [ ] Migrasi fresh install dan upgrade path teruji.
- [ ] Backup native + checksum + manifest dan restore tervalidasi.
- [ ] Retensi 12 bulan hanya setelah archive/backup terverifikasi.

### Security dan device_id removal
- [ ] Key dibuat server, plaintext hanya ditampilkan saat provisioning, hash disimpan di server.
- [ ] Scope key Cashier/Vending ditegakkan; rotate/revoke bekerja.
- [ ] device_id tidak ada dalam schema, kode aktif, API, WebUI, firmware, test, scripts, workflows atau dokumen aktif.
- [ ] Tidak ada key/PIN/NFC secret pada log, URL, export, atau error.
- [ ] Tidak ada migrasi destruktif otomatis ke database VPS lama.

### Release
- [ ] Backend tests, migrations, firmware builds, UI checks, security regressions lulus.
- [ ] Semua workflow GitHub yang diwajibkan hijau.
- [ ] Fresh install VPS berhasil dari keadaan bersih.
- [ ] Backup/restore dan rollback telah dibuktikan.
- [ ] Release report mencantumkan commit, workflow, test evidence, known limitations, dan langkah deploy.

## 15. Keputusan yang harus dikunci sebelum implementasi

Dokumen ini menetapkan perilaku yang sudah diketahui dari keputusan proyek. Hal berikut perlu diverifikasi terhadap desain lama/konfigurasi provider sebelum implementasi final, tanpa mengubah prinsip utama:

1. Model autentikasi admin/operator WebUI dan alur pembuatan admin pertama.
2. Payment provider QRIS yang benar-benar digunakan, mekanisme callback, dan status settlement.
3. Detail hardware Cashier (model ESP32, display, NFC reader, keypad) dan hardware vending/servo.
4. Definisi bisnis setoran tabungan, koreksi/top-up, penarikan dana, limit, dan hak akses tiap role.
5. Daftar tab yang memang sudah ada pada WebUI dan perbedaan tampilan yang harus direplikasi dari demo/UI lama.
6. Apakah data lama perlu dimigrasikan, dan data mana yang wajib dipertahankan.
7. Zona waktu laporan yang ditampilkan kepada operator; simpan timestamp dengan format konsisten dan tampilkan berdasarkan konfigurasi zona waktu.
8. Kebijakan expiry/rotasi key, batas percobaan PIN, dan retensi audit selain retensi transaksi 12 bulan.

Pertanyaan yang memengaruhi saldo, pembayaran, refund, hak akses, atau kehilangan data tidak boleh diselesaikan dengan asumsi diam-diam. Catat keputusan eksplisit sebelum implementasi bagian terkait.

---

## 16. Instruksi untuk pengembang/agent

Baca dokumen ini sebelum mengubah kode. Kerjakan satu fase dalam satu waktu. Untuk setiap fase, laporkan:

- file/modul yang dibuat atau diubah;
- keputusan implementasi yang dibuat;
- migration/API/UI/firmware yang terpengaruh;
- test dan workflow yang dijalankan beserta hasil sebenarnya;
- pencarian global device_id dan penjelasan setiap hasil yang tersisa;
- risiko, asumsi, dan pekerjaan yang belum selesai.

Jangan mengklaim test, build, deploy, atau penghapusan global selesai bila belum dijalankan. Jangan menggabungkan ke main atau mengubah database produksi tanpa persetujuan dan bukti pemeriksaan yang sesuai.


## 17. SPBU Mini / Pertamini — Modul Penjualan BBM

Modul SPBU Mini/Pertamini menjadi jenis layanan baru M-Group, terpisah dari Cashier dan Vending tetapi memakai fondasi yang sama untuk member, ledger, pembayaran, autentikasi key, laporan, audit, dan backup. Modul ini mengendalikan transaksi penjualan BBM melalui dispenser/pompa yang sesuai standar keselamatan. **ESP32/server M-Group tidak boleh dianggap sebagai satu-satunya lapisan keselamatan untuk peralatan BBM.** Instalasi fisik, perangkat pemutus aliran, sensor, grounding, proteksi kebakaran, dan komponen listrik harus dipilih serta dipasang oleh tenaga kompeten sesuai ketentuan keselamatan dan peraturan yang berlaku.

### 17.1 Alur pelanggan

1. Pembeli memilih nominal pembelian BBM atau jumlah rupiah yang ingin dibelanjakan.
2. Sistem menampilkan jenis BBM, harga per liter, nominal, batas volume perkiraan, dan ketentuan transaksi sebelum pembayaran.
3. Pembeli membayar melalui NFC/member balance atau QRIS yang benar-benar telah diverifikasi server/provider.
4. **Tidak ada aliran BBM yang diizinkan sebelum server memastikan pembayaran sah dan dana telah diotorisasi/ditahan secara konsisten.** Untuk QRIS, jangan mengandalkan tampilan sukses pada ponsel pembeli; verifikasi harus berasal dari server/provider.
5. Setelah pembayaran terkonfirmasi, server membuat sesi dispensing dengan nominal maksimum, masa berlaku, referensi transaksi, dan izin sekali pakai.
6. Pembeli mengangkat nozzle dan menekan/menahan tombol pada pegangan selang (dead-man handle). Aliran hanya aktif selama semua interlock keselamatan terpenuhi.
7. Meter aliran yang sesuai mengukur volume aktual. Sistem menghentikan aliran saat nominal/volume yang dibayar tercapai, tombol dilepas, sesi kedaluwarsa, komunikasi/telemetri gagal, atau kondisi keselamatan meminta berhenti.
8. Setelah aliran berhenti, server merekonsiliasi nilai aktual dengan dana yang ditahan. Sisa dana dikembalikan ke saldo member atau melalui refund ke sumber pembayaran jika metode/provider mendukungnya.
9. Layar menunjukkan liter aktual, harga per liter, nilai terpakai, sisa/refund, dan status transaksi. Jika status belum dapat dipastikan, tampilkan **Menunggu rekonsiliasi** dan jangan membuat debit/refund kedua.

### 17.2 Pengamanan luapan dan penghentian darurat

Sistem harus mengantisipasi tangki pembeli yang kecil/penuh, nozzle yang tidak tertutup rapat, salah penempatan nozzle, sensor rusak, meter aliran tidak masuk akal, kehilangan jaringan, kehilangan daya, dan tombol yang macet. Pengamanan minimum:

- **Dead-man handle:** aliran memerlukan tindakan terus-menerus dari pengguna; melepas tombol harus memicu penghentian. Jangan memakai tombol yang mengunci aliran terus-menerus tanpa pengawasan.
- **Emergency stop fisik:** mudah dijangkau, memutus aktuasi aliran secara independen dari aplikasi/server, dan memerlukan prosedur reset yang disengaja setelah kondisi aman.
- **Katup/pompa fail-safe:** kehilangan daya, watchdog, kabel kontrol putus, atau kontroler crash harus membawa aktuator ke kondisi aman yang ditentukan desain. Detail dan rating komponen harus ditetapkan teknisi yang kompeten.
- **Proteksi overfill/luapan:** bila layak secara teknis, gunakan sensor/fitur penghentian yang sesuai untuk mendeteksi kondisi tangki penuh atau risiko luapan. Sensor ini bukan satu-satunya pengaman; pengguna tetap harus mengawasi pengisian dan mengikuti prosedur operasi.
- **Batas maksimum transaksi:** setiap sesi memiliki batas nominal, volume, dan waktu operasi. Batas harus dikonfigurasi oleh operator berwenang dan tidak dapat dinaikkan oleh firmware tanpa otorisasi.
- **Batas aliran/waktu:** jika volume, laju aliran, durasi, atau pembacaan meter menyimpang dari rentang yang masuk akal, hentikan aliran dan tandai sesi untuk pemeriksaan.
- **Interlock status:** aliran ditolak jika autentikasi gagal, pembayaran belum sah, sesi kedaluwarsa/terpakai, emergency stop aktif, sensor kritis gagal, atau status katup/pompa tidak diketahui.
- **Tidak ada auto-resume:** setelah emergency stop, luapan, kegagalan sensor, kehilangan daya, atau kegagalan keselamatan, aliran tidak boleh menyala kembali otomatis. Operator harus memeriksa kondisi dan melakukan reset yang sah.
- **Pemutus lokal independen:** keputusan menghentikan aliran karena keselamatan harus tetap bekerja meskipun server, Wi-Fi, aplikasi, atau ESP32 tidak tersedia. Server dipakai untuk otorisasi dan pencatatan, bukan sebagai satu-satunya pengendali darurat.
- **Sesuai bahan bakar:** peralatan yang bersentuhan dengan BBM, sensor, enclosure, konektor, kabel, pompa, dan katup harus sesuai untuk lingkungan serta jenis bahan bakar yang digunakan. Jangan memakai modul/relay umum yang tidak memiliki rating dan sertifikasi yang sesuai.
- **Operasi aman:** grounding/bonding, pencegahan sumber nyala, ventilasi, proteksi kebakaran, signage, prosedur tumpahan, dan penempatan unit harus ditentukan dalam desain instalasi profesional dan memenuhi aturan lokal. Modul perangkat lunak tidak menggantikan kepatuhan ini.

Jika sistem mendeteksi luapan atau tombol stop ditekan, urutan prioritasnya adalah: **hentikan aliran melalui jalur keselamatan lokal terlebih dahulu**, pastikan status aktuator aman, lalu kirim event ke server dan lakukan rekonsiliasi finansial. Jangan menunda pemutusan aliran untuk menunggu respons server.

### 17.3 Penagihan, sisa dana, dan refund

- Transaksi menggunakan model **otorisasi nominal maksimum → dispensing terukur → finalisasi nilai aktual → refund sisa**.
- Untuk saldo member, dana dapat ditahan/dipesan secara atomik sebelum dispensing; setelah transaksi berakhir, debit final hanya sebesar nilai BBM yang benar-benar terukur dan sisa reservasi dilepas/dikreditkan kembali sesuai ledger.
- Untuk QRIS, dukungan refund bergantung pada kemampuan resmi provider dan status settlement. Jangan menjanjikan pengembalian otomatis ke rekening/sumber QRIS jika provider tidak mendukungnya. Jika refund ke sumber asal tidak tersedia, buat kewajiban refund yang terlacak dan ikuti kebijakan yang disetujui untuk penyelesaian manual atau kredit saldo member.
- Jika luapan menyebabkan nilai BBM yang terukur berbeda dari jumlah yang direncanakan, sistem tetap harus menghentikan aliran secepat jalur keselamatan merespons. Nilai terpakai dihitung dari meter tervalidasi; refund dihitung dari dana yang ditahan dikurangi nilai yang sah, dengan penanganan khusus bila terdapat tumpahan atau sengketa.
- Jangan otomatis menyimpulkan bahwa semua BBM yang keluar merupakan BBM yang diterima pembeli bila terjadi luapan. Catat insiden, nilai meter, perkiraan nilai BBM terpakai/terbuang jika dapat ditentukan, bukti sensor, dan keputusan operator. Kebijakan kompensasi harus eksplisit dan dapat diaudit.
- Semua debit, reservasi, finalisasi, pelepasan sisa dana, kredit saldo, dan refund harus idempotent, saling tertaut dengan satu transaction reference, dan aman dari retry/timeout.
- Jika jaringan terputus ketika BBM sedang mengalir, kontrol lokal harus menghentikan aliran sesuai kebijakan keselamatan (default aman: berhenti), mencatat data meter/insiden secara lokal dengan integritas yang memadai, dan mengirimkannya untuk rekonsiliasi saat koneksi pulih. Jangan melanjutkan sesi baru sebelum sesi sebelumnya direkonsiliasi.
- Untuk QRIS, status pembayaran, settlement, refund request, refund accepted, dan refund completed adalah status berbeda; jangan menandai refund selesai hanya karena permintaan refund berhasil dikirim.

### 17.4 WebUI SPBU Mini

Tambahkan tab **SPBU Mini** dengan bagian berikut:

- **Ringkasan:** status unit, transaksi hari ini, volume terjual, nilai penjualan, sesi pending, refund, dan insiden keselamatan.
- **Unit/Dispenser:** nama unit, lokasi, status operasional, jenis BBM, harga per liter, batas nominal/volume/durasi, status meter dan sensor, status emergency stop, status terakhir terlihat, serta versi konfigurasi. Tidak ada device_id.
- **Transaksi:** referensi, member/pembeli bila sah, metode pembayaran, nominal diotorisasi, liter aktual, nilai aktual, sisa dana/refund, status dispensing, status refund, timestamp dan hasil rekonsiliasi.
- **Insiden & Keselamatan:** emergency stop, luapan, sensor gagal, meter abnormal, komunikasi terputus, shutdown daya, tindakan operator, catatan pemeriksaan, dan reset yang diotorisasi. Insiden tidak boleh dihapus dari audit.
- **Harga & Batas:** jenis BBM, harga per liter, batas transaksi, batas volume/durasi, dan konfigurasi keselamatan yang boleh diubah. Perubahan harga atau batas memerlukan role berwenang, validasi, konfirmasi, dan audit.
- **Refund/Rekonsiliasi:** antrean refund, provider reference, nilai, status, alasan, percobaan, dan tindakan operator. Mencegah refund ganda.
- **Pengujian/Perawatan:** status kalibrasi meter, pemeriksaan sensor, hasil pemeriksaan berkala, tanggal perawatan, dan status unit (aktif, dibatasi, dikunci/maintenance).
- Unit harus otomatis ditandai tidak siap bertransaksi bila pengaman kritis belum lulus pemeriksaan, masa kalibrasi terlewati jika diwajibkan, atau ada insiden yang belum ditutup.

### 17.5 Backend dan domain SPBU Mini

Tambahkan layanan modular `app/fuel/` (nama dapat disesuaikan) untuk:

- Fuel unit/dispenser registry sebagai entitas bisnis, tanpa identitas perangkat keras device_id.
- Fuel types, price-per-litre versioning, limit policies, and configuration audit.
- Dispensing session lifecycle dan otorisasi sekali pakai.
- Meter readings, plausibility checks, final volume/value calculation, and reconciliation.
- Safety events and lockout state.
- Payment authorization/reservation, final capture/debit, release of unused reservation, member balance credit, provider refund and refund status tracking.
- Idempotency, offline event reconciliation, operator incident review, reporting, and audit.

Data penting yang perlu disimpan mencakup unit bisnis, jenis BBM, versi harga yang dipakai sesi, jumlah yang diotorisasi, nilai reservasi, meter awal/akhir, liter aktual, nilai terhitung, hasil stop, alasan penghentian, event sensor yang relevan, nilai sisa, refund state/provider reference, status rekonsiliasi, dan audit operator. Jangan menyimpan data rahasia yang tidak diperlukan.

### 17.6 State machine transaksi BBM

Gunakan state eksplisit, misalnya:

`created → payment_pending → authorized → dispensing → stopped → reconciling → completed`

Jalur lain termasuk `payment_failed`, `safety_stopped`, `meter_fault`, `refund_pending`, `refund_completed`, dan `needs_manual_review`. Status final harus ditetapkan oleh backend sesuai bukti pembayaran, data meter, hasil keselamatan, dan status refund. Sesi tidak boleh melompat dari `created` ke `dispensing` tanpa otorisasi server dan interlock lokal yang terpenuhi.

Sesi wajib berhenti atau dikunci bila: tombol dead-man dilepas, emergency stop aktif, indikasi luapan terdeteksi, batas nominal/volume/waktu tercapai, pembacaan meter tidak valid, watchdog/sensor kritis gagal, atau kontroler kehilangan kondisi aman yang terkonfirmasi. Safety controller lokal harus menegakkan penghentian meskipun server tidak dapat dijangkau.

### 17.7 API target SPBU Mini

Kontrak endpoint final akan dirinci dalam OpenAPI, tetapi API harus mendukung operasi berikut di bawah prefix `/api/v1`:

- Admin CRUD unit bisnis, jenis BBM, harga versi aktif, limit, dan status perawatan.
- Memulai sesi penjualan dan mengotorisasi pembayaran NFC/member balance atau QRIS.
- Memverifikasi status pembayaran di server dan menerbitkan izin dispensing sekali pakai dengan masa berlaku.
- Menerima heartbeat/status kesiapan, pembacaan meter, hasil stop, dan event keselamatan dari credential unit yang terautentikasi.
- Melaporkan hasil dispensing dan finalisasi transaksi.
- Membuat/menjalankan refund atau melepas sisa reservasi secara idempotent.
- Membaca status sesi, riwayat transaksi, insiden, laporan, dan status refund.
- Mengunci unit, membuka kembali setelah pemeriksaan, dan mencatat identitas operator yang mengotorisasi reset.
- Menolak request dispensing bila key tidak sah/revoked, scope salah, sesi tidak valid/expired/used, pembayaran belum terverifikasi, atau unit terkunci.

Jangan membuat endpoint yang memungkinkan WebUI atau server mengabaikan emergency stop lokal. Status keselamatan yang dikirim perangkat adalah telemetri; perangkat keras harus tetap menghentikan aliran secara lokal tanpa menunggu API.

### 17.8 Hardware/firmware dan commissioning

- Buat controller/interface untuk dispenser terpisah dari firmware Cashier/Vending, dengan batas tanggung jawab dan protokol terdokumentasi.
- ESP32 dapat menjadi controller aplikasi hanya bila cocok untuk desain yang telah ditinjau; fungsi keselamatan kritis perlu dirancang sebagai jalur lokal independen dengan komponen dan rating yang sesuai.
- Commissioning sebelum unit diaktifkan wajib memeriksa emergency stop, dead-man handle, penutupan katup/pompa, perilaku saat listrik/jaringan hilang, sensor luapan jika digunakan, meter dan kalibrasi, batas nominal/volume/durasi, serta rekonsiliasi pembayaran/refund.
- Uji keselamatan awal harus dilakukan tanpa BBM atau dalam prosedur pengujian profesional yang disetujui, bukan dengan mengandalkan simulasi software sebagai bukti keselamatan fisik.
- Unit harus dapat dikunci dari transaksi bila pemeriksaan gagal; hanya personel berwenang dapat membuka lockout setelah pemeriksaan dan pencatatan.
- Perangkat lunak harus menyediakan fallback aman: jika status sensor atau aktuator kritis tidak diketahui, jangan mulai atau lanjutkan dispensing.

### 17.9 Laporan, audit dan acceptance criteria SPBU Mini

Laporan harus membedakan jumlah pembayaran, nilai BBM terukur, nilai final, dana dilepas/dikembalikan, refund yang diminta, refund yang selesai, dan transaksi yang masih perlu rekonsiliasi. Sumber laporan baru adalah **FUEL** atau **SPBU_MINI**, dengan filter periode, unit, jenis BBM, metode pembayaran, status dispensing, dan status refund.

Checklist penerimaan:

- [ ] NFC/member balance dan QRIS baru mengizinkan aliran setelah pembayaran terverifikasi server.
- [ ] Nominal/volume/durasi maksimum ditegakkan oleh server dan kontrol lokal.
- [ ] Dead-man handle dan emergency stop menghentikan aliran melalui jalur lokal independen.
- [ ] Kondisi sensor/meter kritis tidak valid membuat unit tidak siap atau menghentikan sesi.
- [ ] Batas tercapai, tombol dilepas, timeout, kehilangan daya/jaringan, dan indikasi luapan mengarah ke kondisi aman.
- [ ] Tidak ada auto-resume setelah insiden/lockout.
- [ ] Liter aktual dan nilai transaksi direkonsiliasi dari pembacaan meter tervalidasi.
- [ ] Sisa reservasi saldo member dilepas/dikembalikan tanpa duplikasi.
- [ ] Refund QRIS mengikuti kemampuan provider dan status refund yang sebenarnya.
- [ ] Insiden luapan tidak otomatis dianggap sebagai transaksi BBM normal; ada alur audit dan review.
- [ ] Request retry, timeout, restart, dan event offline tidak menyebabkan dispense, debit, atau refund ganda.
- [ ] Unit tidak dapat diaktifkan tanpa commissioning dan pemeriksaan keselamatan yang disyaratkan.
- [ ] Laporan, backup, restore, audit, dan role access mencakup modul SPBU Mini.

