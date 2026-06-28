import asyncio
import csv
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

OUTPUT_DIR = "output"
import os
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Semua jenis status dokumen (pivot CSV) ─────────────────────
ALL_STATUSES = [
    "OPEN",
    "DRAFT",
    "SUBMITTED BY Pencacah",
    "SUBMITTED RESPONDENT",
    "APPROVED BY Pengawas",
    "REJECTED BY Pengawas",
]
SLS_PIVOT_FIELDNAMES = ["idsubsls"] + ALL_STATUSES

# ──────────────────────────────────────────────
# HELPER: tunggu user konfirmasi via terminal
# ──────────────────────────────────────────────
def tanya(prompt: str) -> str:
    return input(f"\n{'='*60}\n{prompt}\n> ").strip()

def konfirmasi(prompt: str) -> bool:
    jawab = tanya(f"{prompt} (y/n)").lower()
    return jawab.startswith("y")

# ──────────────────────────────────────────────
# SCRAPER UTAMA
# ──────────────────────────────────────────────
async def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║         FASIH Scraper — SE2026 Assignment Progress       ║
║   by Refo @ BPS Kepahiang                               ║
╚══════════════════════════════════════════════════════════╝
""")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=200,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"]
        )
        ctx = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await ctx.new_page()
        await Stealth().apply_stealth_async(page)

        # ── STEP 1: Buka FASIH & tunggu login ──
        await page.goto("https://fasih-sm.bps.go.id/", wait_until="domcontentloaded")
        print("\n[INFO] Browser terbuka → silakan LOGIN dulu di browser ya bro!")
        tanya("Setelah LOGIN berhasil & sudah di halaman Rekap Petugas Pengawas, tekan ENTER...")

        # ── STEP 2: Klik tab 'Pengawas' kalau belum aktif ──
        print("\n[INFO] Memastikan tab Pengawas aktif...")
        try:
            # Tunggu tab Pengawas muncul di DOM (maks 5 detik)
            try:
                await page.wait_for_selector(
                    'button:has-text("Pengawas"), [role="tab"]:has-text("Pengawas")',
                    timeout=5000
                )
            except Exception:
                pass

            tab_pengawas = page.locator(
                'button:has-text("Pengawas"), [role="tab"]:has-text("Pengawas")'
            ).first
            if await tab_pengawas.count() > 0:
                tab_is_active = await tab_pengawas.get_attribute("aria-selected") or \
                                await tab_pengawas.get_attribute("data-state")
                if tab_is_active not in ["true", "active", "selected"]:
                    await tab_pengawas.click()
                    await page.wait_for_timeout(1500)
                    print("  [✓] Tab Pengawas diklik")
                else:
                    print("  [✓] Tab Pengawas sudah aktif")
            else:
                print("  [WARN] Tab Pengawas tidak ditemukan — lanjut scraping dari halaman ini")
        except Exception as e:
            print(f"  [WARN] Gagal klik tab Pengawas: {e}")

        # ── STEP 3: Langsung scrape SLS Pivot ──
        print("\n[SCRAPING] Mulai ambil data SLS Pivot semua halaman...")
        pivot_data = await scrape_sls_pivot_semua(page)

        if pivot_data:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_file = f"{OUTPUT_DIR}/sls_pivot_{ts}.csv"
            simpan_csv_pivot(pivot_data, out_file)
            print(f"\n[DONE] SLS Pivot → {out_file} ({len(pivot_data)} baris)")
            # Preview 10 baris pertama
            print(f"\n{'idsubsls':<18} " + "  ".join(f"{s[:14]:<14}" for s in ALL_STATUSES))
            print("-" * 110)
            for r in pivot_data[:10]:
                vals = "  ".join(f"{r[s]:<14}" for s in ALL_STATUSES)
                print(f"{r['idsubsls']:<18} {vals}")
        else:
            print("\n[WARN] Tidak ada data SLS Pivot yang berhasil di-scrape.")

        # ── SUMMARY ──
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        print(f"  Total idsubsls unik : {len(pivot_data)}")
        print("\n[INFO] File tersimpan di folder: output/")
        tanya("Tekan ENTER untuk tutup browser...")
        await browser.close()




# ──────────────────────────────────────────────
# SCRAPE: Daftar petugas (semua halaman)
# ──────────────────────────────────────────────
async def scrape_petugas_semua(page) -> list[dict]:
    all_data = []
    halaman = 1
    
    while True:
        print(f"  [Halaman {halaman}] Scraping...")
        if halaman == 1:
            try:
                await page.wait_for_selector(
                    '[class*="rounded-xl"][class*="border"]',
                    timeout=10000
                )
            except Exception:
                pass
            await page.wait_for_timeout(1500)
        data = await scrape_petugas_halaman(page)
        if not data:
            print(f"  [Halaman {halaman}] Tidak ada data, berhenti.")
            break
        
        all_data.extend(data)
        print(f"  [Halaman {halaman}] → {len(data)} petugas (total: {len(all_data)})")
        
        # Cari tombol Next
        next_btn = page.locator('a[aria-label="Go to next page"], a:has-text("Next")').first
        if await next_btn.count() == 0 or await next_btn.is_disabled():
            print("  [INFO] Sudah halaman terakhir.")
            break
        
        await next_btn.click()
        await page.wait_for_timeout(9500)  # +3 detik
        halaman += 1
    
    return all_data


async def scrape_petugas_halaman(page) -> list[dict]:
    hasil = []
    # Cari card petugas — berdasarkan struktur HTML FASIH
    # Card = .rounded-xl.border yang punya email + total assignment
    cards = page.locator('[class*="rounded-xl"][class*="border"]').filter(
        has=page.locator('[class*="font-semibold"][class*="text-sm"]')
    )
    
    count = await cards.count()
    if count == 0:
        # Fallback: coba cari langsung elemen email
        # Struktur: div.f\:m-0.f\:truncate.f\:font-semibold.f\:text-sm
        emails = await page.locator('text=@gmail.com, text=@bps.go.id').all_text_contents()
        print(f"  [DEBUG] Fallback email scan: {emails[:3]}")
        return hasil
    
    for i in range(count):
        card = cards.nth(i)
        try:
            # Email
            email_el = card.locator('[class*="font-semibold"][class*="text-sm"]').first
            email = (await email_el.inner_text()).strip() if await email_el.count() > 0 else ""
            
            if not email or "@" not in email:
                continue
            
            # Total assignment
            total_el = card.locator('[class*="font-bold"][class*="text-primary"]').first
            total = (await total_el.inner_text()).strip() if await total_el.count() > 0 else "0"
            
            hasil.append({
                "email": email,
                "total_assignment": total.replace(",", "").replace(".", ""),
            })
        except Exception as e:
            print(f"  [WARN] Card {i}: {e}")
    
    return hasil


# ──────────────────────────────────────────────
# SCRAPE: Per SLS (expand tiap card petugas)
# ──────────────────────────────────────────────
async def scrape_sls_semua(page) -> list[dict]:
    all_data = []
    halaman = 1
    
    while True:
        print(f"\n  [Halaman {halaman}] Expand petugas untuk scrape SLS...")
        if halaman == 1:
            try:
                await page.wait_for_selector(
                    'button[aria-expanded="false"]',
                    timeout=10000
                )
            except Exception:
                pass
            await page.wait_for_timeout(1500)
        data = await scrape_sls_halaman(page)
        all_data.extend(data)
        print(f"  [Halaman {halaman}] → {len(data)} SLS records")
        
        # Next page
        next_btn = page.locator('a[aria-label="Go to next page"], a:has-text("Next")').first
        if await next_btn.count() == 0 or await next_btn.is_disabled():
            break
        
        await next_btn.click()
        await page.wait_for_timeout(5000)  # +3 detik
        halaman += 1
    
    return all_data


async def scrape_sls_halaman(page) -> list[dict]:
    hasil = []
    
    # Klik semua tombol expand (accordion)
    expand_buttons = page.locator('button[aria-expanded="false"]').filter(
        has=page.locator('[class*="tabler-icon-chevron-down"]')
    )
    
    count = await expand_buttons.count()
    print(f"    Found {count} petugas cards to expand")
    
    for i in range(count):
        try:
            btn = page.locator('button[aria-expanded="false"]').filter(
                has=page.locator('[class*="tabler-icon-chevron-down"]')
            ).first
            
            if await btn.count() == 0:
                break
            
            # Ambil email dari card ini sebelum expand
            card_parent = btn.locator('xpath=ancestor::div[@class and contains(@class,"rounded-xl")]').last
            email_el = card_parent.locator('[class*="font-semibold"][class*="text-sm"]').first
            email = ""
            if await email_el.count() > 0:
                email = (await email_el.inner_text()).strip()
            
            # Expand
            await btn.click()
            await page.wait_for_timeout(1000)
            
            # Scrape isi accordion yang baru terbuka
            # Cari panel yang terbuka (data-state=open)
            open_panel = page.locator('[data-state="open"]').last
            
            # Cari baris SLS/Assignment dalam panel
            rows = open_panel.locator('tr, [class*="flex"][class*="items"]').all()
            
            # Fallback: cari tabel jika ada
            table_rows = open_panel.locator('tr')
            tr_count = await table_rows.count()
            
            if tr_count > 1:  # ada header + data
                for j in range(1, tr_count):  # skip header
                    row = table_rows.nth(j)
                    cells = await row.locator('td').all_text_contents()
                    if cells:
                        row_data = {
                            "petugas_email": email,
                            "raw_cells": " | ".join(c.strip() for c in cells),
                        }
                        # Coba parsing berdasarkan posisi kolom umum FASIH
                        # (id_sls, nama_sls, status, submitted_at, dst)
                        col_names = ["id_sls", "nama_sls", "status", "keterangan", "col5", "col6", "col7", "col8"]
                        for k, cell in enumerate(cells):
                            if k < len(col_names):
                                row_data[col_names[k]] = cell.strip()
                        hasil.append(row_data)
            else:
                # Fallback: tangkap semua teks struktural dari panel
                all_text = await open_panel.inner_text()
                lines = [l.strip() for l in all_text.split("\n") if l.strip()]
                for line in lines[:100]:  # max 100 baris per petugas
                    if any(kw in line.lower() for kw in ["submitted", "approved", "rejected", "open", "draft", "review"]):
                        hasil.append({
                            "petugas_email": email,
                            "raw_text": line,
                        })
            
            print(f"    [{i+1}/{count}] {email} → {tr_count} rows")
            
        except Exception as e:
            print(f"    [WARN] Error expand card {i}: {e}")
    
    return hasil


# ──────────────────────────────────────────────
# SCRAPE: SLS Pivot — idsubsls unik, count per status
# ──────────────────────────────────────────────
async def scrape_sls_pivot_semua(page) -> list[dict]:
    """Iterasi semua halaman, kumpulkan idsubsls + count status sebagai pivot."""
    all_data: dict[str, dict] = {}  # idsubsls → row
    halaman = 1

    while True:
        print(f"\n  [Halaman {halaman}] Scrape SLS Pivot...")
        if halaman == 1:
            try:
                await page.wait_for_selector(
                    'button[aria-expanded][class*="f:justify-between"]',
                    timeout=10000
                )
            except Exception:
                print("  [WARN] Timeout menunggu accordion muncul di Halaman 1.")
            await page.wait_for_timeout(1500)
        rows = await scrape_sls_pivot_halaman(page)
        for row in rows:
            id_ = row["idsubsls"]
            if id_ not in all_data:
                all_data[id_] = row
            else:
                # Merge: tambah count
                for st in ALL_STATUSES:
                    all_data[id_][st] += row[st]
        print(f"  [Halaman {halaman}] → {len(rows)} SLS cards (unik total: {len(all_data)})")

        # ── Deteksi halaman terakhir ────────────────────────────
        # Di SPA ini semua href="#", is_disabled() tidak andal.
        # Cara andal: cek nomor halaman aktif via aria-current,
        # lalu bandingkan dengan nomor di link Next atau halaman terakhir.

        # Ambil nomor halaman aktif saat ini
        current_page_el = page.locator('[aria-label="pagination"] a[aria-current="page"]').first
        if await current_page_el.count() > 0:
            current_num = (await current_page_el.inner_text()).strip()
        else:
            current_num = str(halaman)

        # Cek apakah tombol Next ada
        next_btn = page.locator('a[aria-label="Go to next page"]').first
        if await next_btn.count() == 0:
            print("  [INFO] Tombol Next tidak ditemukan — halaman terakhir.")
            break

        # Klik Next
        await next_btn.click()
        # Tunggu skeleton loading hilang — cek sampai accordion muncul atau timeout
        await page.wait_for_timeout(9500)  # jeda awal (+3 detik)
        try:
            await page.wait_for_selector(
                'button[aria-expanded][class*="f:justify-between"]',
                timeout=5000
            )
        except Exception:
            pass  # fallback: lanjut meski timeout
        await page.wait_for_timeout(1500)  # jeda tambahan untuk data render

        # Cek apakah halaman berubah (nomor aktif berubah)
        new_page_el = page.locator('[aria-label="pagination"] a[aria-current="page"]').first
        if await new_page_el.count() > 0:
            new_num = (await new_page_el.inner_text()).strip()
        else:
            new_num = current_num

        if new_num == current_num:
            print(f"  [INFO] Halaman tidak berubah ({current_num}) — sudah halaman terakhir.")
            break

        halaman += 1

    return list(all_data.values())



async def scrape_sls_pivot_halaman(page) -> list[dict]:
    """
    Parse satu halaman (5 petugas per halaman).

    Strategi: pakai JavaScript DOM langsung (page.evaluate) setelah expand
    tiap accordion — tidak ada regex/string slicing yang fragile.
    JS query elemen DOM secara tepat per panel accordion.
    """
    import re
    email_pattern = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.IGNORECASE)

    ACCORDION_SELECTOR = 'button[aria-expanded][class*="f:justify-between"]'

    hasil = []
    seen_ids: set[str] = set()

    all_accordions = page.locator(ACCORDION_SELECTOR)
    total = await all_accordions.count()
    print(f"    [{total} accordion petugas] ditemukan di halaman ini")

    if total == 0:
        print("    [WARN] Tidak ada accordion ditemukan!")
        return hasil

    for i in range(total):
        try:
            btn = page.locator(ACCORDION_SELECTOR).nth(i)

            # Ambil email dari teks button
            btn_text = (await btn.inner_text()).strip()
            email_match = email_pattern.search(btn_text)
            email = email_match.group().lower() if email_match else f"petugas_{i+1}"

            # Expand kalau belum terbuka
            is_expanded = (await btn.get_attribute("aria-expanded")) == "true"
            if not is_expanded:
                await btn.click()
                await page.wait_for_timeout(1500)  # tunggu animasi accordion + data load
                print(f"      [{i+1}/{total}] ▼ Expand: {email}")
            else:
                print(f"      [{i+1}/{total}] ✓ Sudah terbuka: {email}")

            # ── Extract data langsung dari DOM via JavaScript ──────────
            sls_items = await page.evaluate(
                """
                (btnIndex) => {
                    const SELECTOR = 'button[aria-expanded][class*="f:justify-between"]';
                    const buttons = document.querySelectorAll(SELECTOR);
                    const btn = buttons[btnIndex];
                    if (!btn) return [];

                    // Cari panel konten accordion.
                    // Struktur Radix UI: AccordionItem > [Trigger(button), Content(div)]
                    // Panel biasanya nextElementSibling dari button, atau dari wrapper button.
                    let panel = null;

                    // Coba 1: sibling langsung dari button
                    if (btn.nextElementSibling) {
                        panel = btn.nextElementSibling;
                    }

                    // Coba 2: parent button punya sibling berikutnya
                    if (!panel && btn.parentElement && btn.parentElement.nextElementSibling) {
                        panel = btn.parentElement.nextElementSibling;
                    }

                    // Coba 3: walk up dari button, cari div dengan class f:p-6 atau f:space-y
                    // yang bukan ancestor button itu sendiri
                    if (!panel) {
                        let el = btn.parentElement;
                        for (let d = 0; d < 6 && el; d++) {
                            for (const child of el.children) {
                                if (!child.contains(btn) &&
                                    (child.className.includes('f:p-6') ||
                                     child.className.includes('f:space-y') ||
                                     child.className.includes('f:pt-0'))) {
                                    panel = child;
                                    break;
                                }
                            }
                            if (panel) break;
                            el = el.parentElement;
                        }
                    }

                    if (!panel) return [{ debug: 'panel not found' }];

                    // Ambil semua item SLS dari panel
                    // ID subsls ada di: div dengan class f:font-semibold f:text-foreground f:text-sm
                    const idDivs = panel.querySelectorAll(
                        '[class*="font-semibold"][class*="text-foreground"][class*="text-sm"]'
                    );

                    const results = [];
                    for (const div of idDivs) {
                        const id = div.textContent.trim();
                        // Hanya kode subsls 16 digit mulai 17
                        if (!/^17\\d{14}$/.test(id)) continue;

                        // Cari parent row: walk up sampai ketemu elemen dengan class group atau flex
                        let row = div.parentElement;
                        while (row && !row.className.includes('f:group')) {
                            row = row.parentElement;
                        }
                        if (!row) continue;

                        // Ambil semua badge status dalam row ini
                        const badges = {};
                        const statusSpans = row.querySelectorAll(
                            '[class*="uppercase"][class*="tracking-wider"]'
                        );
                        for (const span of statusSpans) {
                            const statusName = span.textContent.trim();
                            const countSpan = span.nextElementSibling;
                            if (countSpan) {
                                badges[statusName] = parseInt(countSpan.textContent.trim()) || 0;
                            }
                        }
                        results.push({ id, badges });
                    }
                    return results;
                }
                """,
                i,
            )


            # Konversi hasil JS ke format row CSV
            sls_count = 0
            for item in sls_items:
                # Debug item dari JS (bukan data SLS)
                if "debug" in item:
                    print(f"        [DEBUG] JS: {item['debug']}")
                    continue
                if "id" not in item:
                    continue

                id_val = item["id"]
                if id_val in seen_ids:
                    continue
                seen_ids.add(id_val)

                badges = item.get("badges", {})
                row = {"idsubsls": id_val}
                for st in ALL_STATUSES:
                    row[st] = badges.get(st, 0)
                hasil.append(row)
                sls_count += 1

            print(f"        → {sls_count} SLS dari {email}")

        except Exception as e:
            print(f"      [WARN] Error accordion {i+1}: {e}")

    return hasil





# ──────────────────────────────────────────────
# SAVE CSV
# ──────────────────────────────────────────────
def simpan_csv(data: list[dict], filepath: str):
    if not data:
        return
    fieldnames = list(data[0].keys())
    # Union semua keys
    for row in data:
        for k in row.keys():
            if k not in fieldnames:
                fieldnames.append(k)

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

def simpan_csv_pivot(data: list[dict], filepath: str):
    """Simpan CSV pivot dengan kolom tetap: idsubsls + semua status."""
    if not data:
        return
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SLS_PIVOT_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

if __name__ == "__main__":
    asyncio.run(main())