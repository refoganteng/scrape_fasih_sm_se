import asyncio
import csv
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from playwright.async_api import async_playwright

OUTPUT_DIR = "output"
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

def map_status(raw_status: str) -> str:
    s = raw_status.strip().upper()
    if s == "OPEN":
        return "OPEN"
    if s == "DRAFT":
        return "DRAFT"
    if s == "SUBMITTED BY PENCACAH":
        return "SUBMITTED BY Pencacah"
    if s == "SUBMITTED RESPONDENT":
        return "SUBMITTED RESPONDENT"
    if s in ("APPROVED BY PENGAWAS", "EDITED BY PENGAWAS", "EDITED BY ADMIN KABUPATEN", "COMPLETED BY ADMIN KABUPATEN"):
        return "APPROVED BY Pengawas"
    if s in ("REJECTED BY PENGAWAS", "REVOKED BY PENGAWAS", "REJECTED BY ADMIN KABUPATEN"):
        return "REJECTED BY Pengawas"
    
    # Fallback keyword matching
    if "SUBMITTED" in s:
        if "RESPONDENT" in s:
            return "SUBMITTED RESPONDENT"
        return "SUBMITTED BY Pencacah"
    if "APPROVED" in s or "EDITED" in s:
        return "APPROVED BY Pengawas"
    if "REJECTED" in s or "REVOKED" in s:
        return "REJECTED BY Pengawas"
    
    return "OPEN"

# ──────────────────────────────────────────────
# HELPER: tunggu user konfirmasi via terminal
# ──────────────────────────────────────────────
def tanya(prompt: str) -> str:
    return input(f"\n{'='*60}\n{prompt}\n> ").strip()

def konfirmasi(prompt: str) -> bool:
    jawab = tanya(f"{prompt} (y/n)").lower()
    return jawab.startswith("y")

# ──────────────────────────────────────────────
# HELPER: Anti-Bot & Delay Natural
# ──────────────────────────────────────────────
async def human_delay(min_sec: float = 1.5, max_sec: float = 3.0):
    await asyncio.sleep(random.uniform(min_sec, max_sec))

# Regex pattern untuk mendeteksi kode bot BPS: BOT-<angka panjang>
BOT_CODE_PATTERN = re.compile(r"BOT-\d{10,}", re.IGNORECASE)

async def check_and_handle_bot_block(page) -> bool:
    """Cek apakah halaman terkena blokir bot FASIH BPS."""
    try:
        content = await page.content()
        is_blocked = (
            "mendeteksi koneksi anda sebagai bot" in content.lower()
            or "perilaku yang tidak wajar" in content.lower()
            or BOT_CODE_PATTERN.search(content)
        )
        if is_blocked:
            print("\a\n" + "!"*60)
            print("  ⚠️  TERDETEKSI BOT oleh FASIH BPS!")
            print("  Berpindah ke jendela Chrome:")
            print("  1. Klik '[Kembali]' di halaman blokir")
            print("  2. Navigasi kembali ke Rekap Petugas Pengawas")
            print("!"*60)
            tanya("Setelah halaman normal kembali, tekan ENTER...")
            await human_delay(2.0, 3.5)
            return True
    except Exception:
        pass
    return False

# ──────────────────────────────────────────────
# CHROME CDP LAUNCHER
# ──────────────────────────────────────────────
CDP_PORT = 9222

def find_chrome_path() -> str:
    """Cari path Google Chrome di macOS."""
    paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    for p in paths:
        if os.path.isfile(p):
            return p
    return ""

def is_chrome_cdp_ready() -> bool:
    """Cek apakah Chrome sudah running dan CDP bisa dihubungi."""
    import urllib.request
    try:
        req = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2)
        req.read()
        return True
    except Exception:
        return False

def launch_chrome_with_cdp():
    """Buka Chrome dengan remote debugging port jika belum jalan."""
    if is_chrome_cdp_ready():
        print(f"[INFO] Chrome sudah running di port {CDP_PORT}, langsung connect...")
        return None

    chrome_path = find_chrome_path()
    if not chrome_path:
        print("[ERROR] Google Chrome tidak ditemukan!")
        print("  Install Google Chrome terlebih dahulu, atau buka Chrome secara manual:")
        print(f'  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port={CDP_PORT}')
        sys.exit(1)

    user_data_dir = os.path.abspath("./chrome_debug_profile")
    os.makedirs(user_data_dir, exist_ok=True)

    print(f"[INFO] Membuka Google Chrome dengan remote debugging (port {CDP_PORT})...")
    proc = subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={user_data_dir}",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check",
            "https://fasih-sm.bps.go.id/",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Tunggu sampai CDP siap
    for _ in range(30):
        time.sleep(1)
        if is_chrome_cdp_ready():
            print("[INFO] Chrome CDP siap!")
            return proc
    
    print("[ERROR] Timeout menunggu Chrome CDP siap.")
    proc.terminate()
    sys.exit(1)


# ──────────────────────────────────────────────
# SCRAPER UTAMA
# ──────────────────────────────────────────────
async def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║         FASIH Scraper — SE2026 Assignment Progress       ║
║   by Refo @ BPS Kepahiang                               ║
║                                                          ║
║   Mode: Connect ke Chrome via CDP (anti-bot)             ║
╚══════════════════════════════════════════════════════════╝
""")

    # Buka Chrome biasa (bukan Playwright) dengan CDP port
    chrome_proc = launch_chrome_with_cdp()

    async with async_playwright() as p:
        # Connect ke Chrome yang sudah berjalan — BUKAN launch baru
        # Ini artinya Playwright tidak inject apa-apa ke Chrome
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        print("\n[INFO] Terhubung ke Chrome yang sudah terbuka!")
        print("[INFO] Silakan LOGIN ke FASIH di Chrome, navigasi ke Rekap Petugas Pengawas.")
        tanya("Setelah LOGIN berhasil & sudah di halaman Rekap Petugas Pengawas, tekan ENTER...")

        # Cek apakah kena bot block setelah login
        if await check_and_handle_bot_block(page):
            pass  # user sudah handle manual

        # ── STEP 2: Klik tab 'Pengawas' kalau belum aktif ──
        print("\n[INFO] Memastikan tab Pengawas aktif...")
        try:
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
        print("[INFO] Chrome tetap terbuka — kamu bisa tutup manual.")
        
        # Disconnect (bukan close — Chrome tetap terbuka)
        await browser.close()


# ──────────────────────────────────────────────
# SCRAPE: SLS Pivot — idsubsls unik, count per status
# ──────────────────────────────────────────────
async def scrape_sls_pivot_semua(page) -> list[dict]:
    """Iterasi semua halaman, kumpulkan idsubsls + count status sebagai pivot."""
    all_data: dict[str, dict] = {}  # idsubsls → row
    halaman = 1

    while True:
        await check_and_handle_bot_block(page)
        print(f"\n  [Halaman {halaman}] Scrape SLS Pivot...")
        if halaman == 1:
            try:
                await page.wait_for_selector(
                    'button[aria-expanded][class*="f:justify-between"]',
                    timeout=10000
                )
            except Exception:
                print("  [WARN] Timeout menunggu accordion muncul di Halaman 1.")
                if await check_and_handle_bot_block(page):
                    # Setelah user handle bot block, coba tunggu lagi
                    try:
                        await page.wait_for_selector(
                            'button[aria-expanded][class*="f:justify-between"]',
                            timeout=10000
                        )
                    except Exception:
                        pass
            await human_delay(1.5, 2.5)
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

        # Klik Next dengan scroll & delay natural
        try:
            await next_btn.scroll_into_view_if_needed()
            await human_delay(0.5, 1.2)
            await next_btn.click()
        except Exception as e:
            print(f"  [WARN] Gagal klik Next: {e}")
            await check_and_handle_bot_block(page)

        # Jeda natural setelah ganti halaman
        await human_delay(4.0, 7.0)
        await check_and_handle_bot_block(page)
        try:
            await page.wait_for_selector(
                'button[aria-expanded][class*="f:justify-between"]',
                timeout=8000
            )
        except Exception:
            await check_and_handle_bot_block(page)
        await human_delay(1.5, 2.5)

        # Cek apakah halaman berubah
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


JS_PIVOT_EXTRACT_SCRIPT = """
(btnIndex) => {
    const SELECTOR = 'button[aria-expanded][class*="f:justify-between"]';
    const buttons = document.querySelectorAll(SELECTOR);
    const btn = buttons[btnIndex];
    if (!btn) return [];

    let panel = null;
    if (btn.nextElementSibling) {
        panel = btn.nextElementSibling;
    }
    if (!panel && btn.parentElement && btn.parentElement.nextElementSibling) {
        panel = btn.parentElement.nextElementSibling;
    }
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

    const idDivs = panel.querySelectorAll(
        '[class*="font-semibold"][class*="text-foreground"][class*="text-sm"]'
    );

    const results = [];
    for (const div of idDivs) {
        const id = div.textContent.trim();
        if (!/^\\d{16}$/.test(id)) continue;

        let row = div.parentElement;
        while (row && !row.className.includes('f:group')) {
            row = row.parentElement;
        }
        if (!row) continue;

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
"""

async def scrape_sls_pivot_halaman(page) -> list[dict]:
    """Parse satu halaman (5 petugas per halaman)."""
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
            await check_and_handle_bot_block(page)
            btn = page.locator(ACCORDION_SELECTOR).nth(i)

            btn_text = (await btn.inner_text()).strip()
            email_match = email_pattern.search(btn_text)
            email = email_match.group().lower() if email_match else f"petugas_{i+1}"

            # Coba ekstrak data DAHULU tanpa klik jika DOM panel sudah ada
            sls_items = await page.evaluate(JS_PIVOT_EXTRACT_SCRIPT, i)
            valid_items = [it for it in sls_items if isinstance(it, dict) and "id" in it]

            if not valid_items:
                # Expand kalau belum terbuka & data belum ada
                is_expanded = (await btn.get_attribute("aria-expanded")) == "true"
                if not is_expanded:
                    await btn.scroll_into_view_if_needed()
                    await human_delay(0.4, 0.9)
                    await btn.click()
                    await human_delay(1.5, 2.5)
                    print(f"      [{i+1}/{total}] ▼ Expand: {email}")
                    await check_and_handle_bot_block(page)
                else:
                    print(f"      [{i+1}/{total}] ✓ Sudah terbuka: {email}")
                sls_items = await page.evaluate(JS_PIVOT_EXTRACT_SCRIPT, i)
            else:
                print(f"      [{i+1}/{total}] ✓ Data sudah siap di DOM: {email}")

            sls_count = 0
            for item in sls_items:
                if "debug" in item or "id" not in item:
                    continue

                id_val = item["id"]
                if id_val in seen_ids:
                    continue
                seen_ids.add(id_val)

                badges = item.get("badges", {})
                row = {"idsubsls": id_val}
                for st in ALL_STATUSES:
                    row[st] = 0
                for raw_st, count in badges.items():
                    target_st = map_status(raw_st)
                    row[target_st] += count
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