# 📋 Panduan FASIH-SM Scraper SE2026
**by Refo @ BPS Kepahiang**

---

## Apa yang Dilakukan Script Ini?

`scraper.py` mengambil data progres assignment SE2026 dari aplikasi FASIH, lalu menyimpannya sebagai file **CSV pivot** dengan format:

| idsubsls | OPEN | DRAFT | SUBMITTED BY Pencacah | SUBMITTED RESPONDENT | APPROVED BY Pengawas | REJECTED BY Pengawas |
|---|---|---|---|---|---|---|
| 1708010002000200 | 155 | 1 | 4 | 0 | 13 | 0 |
| ... | | | | | | |

Setiap baris = 1 SLS unik, kolom = jumlah dokumen per status.

---

## Prasyarat

### Install Python dependencies
```bash
pip install playwright
playwright install chromium
```

---

## Cara Pakai

### 1. Jalankan script
```bash
python scraper.py
```

### 2. Browser Chromium akan terbuka otomatis

### 3. Login ke FASIH
- Masuk ke **https://fasih-sm.bps.go.id/**
- Login dengan akun Pengawas/Koordinator kamu

### 4. Navigasi ke halaman yang benar
Pergi ke: **Dashboard → Rekap Petugas → Tab "Pengawas"**

Pastikan daftar petugas sudah tampil di layar.

### 5. Tekan ENTER di terminal
Script akan otomatis:
- Klik tab **Pengawas** (kalau belum aktif)
- Expand semua accordion tiap petugas di setiap halaman
- Pindah ke halaman berikutnya sampai selesai
- Simpan hasil ke folder `output/`

### 6. Selesai
File CSV tersimpan di `output/sls_pivot_YYYYMMDD_HHMMSS.csv`

---

## Struktur File Output

```
output/
└── sls_pivot_20260623_161141.csv   ← hasil scraping
```

### Format CSV

```
idsubsls,OPEN,DRAFT,SUBMITTED BY Pencacah,SUBMITTED RESPONDENT,APPROVED BY Pengawas,REJECTED BY Pengawas
1708050020000100,268,15,4,0,31,0
1708050014000200,262,1,0,0,0,0
...
```

- **idsubsls** — kode SLS 16 digit (unik, 1 baris per SLS)
- **OPEN** — jumlah dokumen masih Open
- **DRAFT** — jumlah dokumen Draft
- **SUBMITTED BY Pencacah** — sudah disubmit pencacah
- **SUBMITTED RESPONDENT** — submitted oleh responden
- **APPROVED BY Pengawas** — sudah diapprove pengawas
- **REJECTED BY Pengawas** — ditolak pengawas

---
struktur projek
scrape-progres-se26/
├── scraper.py      ← script utama (jalankan ini)
├── panduan.md      ← panduan ini
└── output/         ← hasil CSV tersimpan di sini
```
