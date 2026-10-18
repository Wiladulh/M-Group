# Rencana Metode Pembayaran M-Group — NFC Card dan QRIS
Status: opsi pengembangan; integrasi QRIS/Midtrans belum diimplementasikan oleh dokumen ini.

## Keputusan produk

Vending dan Cashier direncanakan memiliki dua pilihan metode pembayaran:
1. **NFC Card** — menggunakan saldo internal member M-Group melalui mekanisme saldo/ledger yang sudah ada.
2. **QRIS** — pembayaran eksternal melalui payment provider; Midtrans adalah provider yang direncanakan untuk dievaluasi.

Kedua perangkat menggunakan arsitektur transaksi terpusat pada server M-Group. Jangan membuat sistem pembayaran yang sepenuhnya terpisah untuk vending dan cashier, dan jangan menganggap satu transaksi dibayar melalui kedua metode sekaligus.

## Prinsip arsitektur

- Server adalah sumber kebenaran untuk nominal, transaksi, saldo, status pembayaran, dan keputusan lanjutan.
- NFC tetap memakai mekanisme identitas/credential, validasi saldo, ledger, dan idempotency yang ada. UID NFC saja bukan otorisasi pembayaran.
- Untuk QRIS, server membuat transaksi dan mengaitkannya dengan perangkat, transaksi bisnis, nominal, serta ID provider.
- Server memverifikasi notifikasi/status provider sebelum menandai pembayaran berhasil. Jangan percaya screenshot pembeli atau status sukses dari browser/perangkat.
- Kredensial rahasia provider hanya disimpan pada konfigurasi server yang terlindungi, tidak pada firmware ESP32, WebUI lokal, atau repository.
- Satu transaksi memiliki satu metode pembayaran final; request ulang/notifikasi duplikat tidak boleh membuat posting ledger atau dispensing ganda.
- Status pending, sukses, gagal, kedaluwarsa, pembatalan, dan refund perlu dipetakan secara eksplisit.
- Kegagalan dispensing setelah QRIS sukses memerlukan prosedur rekonsiliasi/refund yang dapat ditelusuri.
- Gangguan jaringan tidak boleh menyebabkan vending menganggap pembayaran belum diverifikasi sebagai sukses.

## Batas pengembangan

Dokumen ini belum memilih kontrak endpoint final, model biaya, settlement, atau kebijakan refund Midtrans. Sebelum implementasi:
1. audit API transaksi/ledger dan database yang sudah ada;
2. tinjau dokumentasi Midtrans terkini serta persyaratan akun/merchant;
3. desain endpoint create/status dan webhook/notifikasi yang aman;
4. validasi signature/notifikasi sesuai kontrak provider dan lakukan pemeriksaan status server-to-server bila diperlukan;
5. terapkan idempotency, transaksi database atomik, audit trail, timeout, rekonsiliasi, dan refund;
6. uji di sandbox, termasuk notifikasi duplikat/terlambat dan internet terputus;
7. sesuaikan firmware Cashier dan Vending hanya setelah kontrak server stabil.

Tidak ada kredensial atau secret provider yang boleh dimasukkan ke repository. Catatan ini adalah rancangan, bukan klaim bahwa QRIS/Midtrans sudah berfungsi.
