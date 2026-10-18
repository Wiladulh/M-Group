# Rencana Server — Gambar Produk dan Sinkronisasi Vending
Status: opsi pengembangan; belum diimplementasikan.

## Tujuan

Server M-Group menyediakan metadata dan file gambar untuk lima produk pada setiap vending. Perangkat menarik data hanya saat petugas meminta sinkronisasi melalui WebUI lokal; tidak ada polling perubahan gambar berkala.

## Upload dan penyimpanan server

WebUI admin server nantinya menyediakan upload gambar pada produk yang sesuai. Server harus:
- memvalidasi tipe file dari isi file, bukan hanya ekstensi;
- membatasi ukuran file, dimensi/resolusi, dan format yang diterima;
- memberi nama file internal yang aman, bukan menggunakan nama file pengguna sebagai path;
- menyimpan file pada lokasi data aplikasi yang dikonfigurasi dan tidak menaruh upload di direktori kode;
- menghubungkan file dengan identitas produk/mesin yang benar;
- menyimpan ukuran, MIME type, dan versi/hash konten;
- mencegah path traversal, upload konten berbahaya, dan akses tanpa otorisasi;
- mempertahankan referensi gambar yang ada bila upload/penggantian gagal.

Jangan menaruh file gambar biner besar ke dalam respons JSON katalog. Respons katalog berisi metadata dan referensi/endpoint gambar yang bisa diunduh secara terpisah.

## Kontrak data yang disarankan

Pertahankan endpoint katalog yang digunakan firmware saat ini, `/api/v1/vending/{DEVICE_ID}/products`, dan evaluasi perluasan kompatibel alih-alih merusak kontrak yang sudah ada.

Untuk setiap produk, pertimbangkan metadata opsional:
- `image_version` atau `image_sha256`;
- `image_size_bytes`;
- `image_content_type`;
- `image_url` atau referensi endpoint gambar yang terautentikasi.

Field gambar harus opsional agar firmware yang belum mendukung gambar tetap dapat membaca katalog. Jangan mengubah harga, stok, transaksi, atau aturan Product ID demi menambahkan gambar.

Endpoint pengunduhan gambar harus memverifikasi identitas/credential perangkat sesuai pola autentikasi API yang ada, membatasi akses pada mesin/produk yang berhak diakses, serta mengirim tipe konten dan panjang konten yang benar. Jangan memasukkan Device Key ke URL atau log.

## Alur sinkronisasi

1. WebUI lokal mengirim perintah sinkronisasi kepada firmware.
2. Firmware mengautentikasi diri ke server dan meminta metadata katalog terkini.
3. Firmware membandingkan ID produk dan versi/hash gambar lokal dengan metadata server.
4. Firmware mengunduh hanya gambar yang baru/berubah.
5. Firmware memvalidasi status HTTP, ukuran, format yang didukung, dan hash jika disediakan.
6. Firmware menyimpan unduhan ke file sementara; setelah valid, file baru menggantikan file aktif.
7. Katalog aktif diperbarui dengan cara yang konsisten dan WebUI menampilkan hasil per produk serta hasil keseluruhan.

Jika salah satu gambar gagal diunduh, jangan merusak gambar lama. Status sinkronisasi harus membedakan berhasil, sebagian berhasil, gagal, dan server tidak terjangkau. Sinkronisasi berulang harus aman/idempotent.

## Kapasitas dan format

Target diskusi awal: lima gambar, sekitar 1 MB per gambar (total kira-kira 5 MB). Sebelum memilih filesystem dan ukuran partisi, hitung ruang aktual untuk firmware, NVS, filesystem, dan OTA dari konfigurasi PlatformIO/partition table yang benar-benar digunakan. Nominal flash 16 MB bukan berarti 16 MB bebas untuk gambar.

Gunakan format yang didukung oleh library layar yang akhirnya dipilih. Evaluasi apakah file asli 1 MB memang diperlukan; optimasi dimensi/kompresi dapat mengurangi waktu unduh dan ruang flash. Penggunaan PSRAM 8 MB membantu buffer/decode bila library mendukung, tetapi bukan pengganti penyimpanan persisten.

## Pengujian minimum sebelum produksi

- upload format benar, format palsu, file rusak, file terlalu besar, dan dimensi berlebihan;
- otorisasi admin dan otorisasi perangkat;
- lima produk terpisah pada setiap vending;
- gambar sama (tidak diunduh ulang) dan gambar berubah (diunduh ulang);
- koneksi putus di tengah download dan hash tidak cocok;
- listrik mati saat download/penggantian file;
- filesystem hampir penuh;
- server offline: katalog dan gambar lokal sebelumnya tetap tersedia;
- firmware lama mengabaikan field gambar opsional;
- CI dan pengujian fisik pada board serta layar yang ditargetkan.

Dokumen ini bukan spesifikasi final API dan tidak mengklaim upload/sinkronisasi gambar sudah tersedia.
