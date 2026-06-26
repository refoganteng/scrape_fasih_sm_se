# ============================================================
# SCRAPING FASIH - VERSI API v2
# Selenium hanya untuk login → ambil cookies
# Semua data diambil via requests langsung ke API

import time, sys, json, requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ============================================================
# KONFIGURASI
# ============================================================
BASE_URL         = "https://fasih-sm.bps.go.id"
FASIH_URL        = f"{BASE_URL}/survey-collection/collect/ecddb52e-f392-403c-a963-47391f217010"
COLLECTION_ID    = FASIH_URL.split("/")[-1]
SURVEY_PERIOD_ID = "37526b20-81c8-42f5-a895-6190137d7394"
GROUP_ID         = "a45adac1-e711-4c15-b3f9-1f30fc151565"
FILTER_EXCEL     = "Filter_SE.xlsx"
timestamp        = datetime.now().strftime("%Y%m%d_%H%M")
OUTPUT_FILE      = f"hasil_scraping_SE_UB_{timestamp}.xlsx"
PAGE_SIZE        = 1000
REGION_BASE      = f"{BASE_URL}/region/api/v1/region"

RETRY_WAIT       = 30   # detik tunggu saat 503/server error sebelum retry
MAX_SERVER_RETRY = 5    # maksimal retry saat server error (503, timeout, non-JSON)

# [1] Delay antar desa (detik) — tuning di sini kalau mau lebih cepat/lambat
DELAY_ANTAR_DESA = 1.5

# File-file persisten
REGION_CACHE_FILE = "region_cache_se_ub.json"
CHECKPOINT_FILE   = "checkpoint_scraping_se_ub.json"

# ============================================================
# BACA FILTER EXCEL
# ============================================================
if not Path(FILTER_EXCEL).exists():
    print(f"[ERROR] File '{FILTER_EXCEL}' tidak ditemukan!")
    sys.exit(1)

df_filter = pd.read_excel(FILTER_EXCEL, header=1)
df_filter.columns = ["drop", "Provinsi", "Kabupaten", "Kecamatan", "Desa"]
df_filter = df_filter.drop(columns=["drop"]).dropna(subset=["Desa"]).reset_index(drop=True)
for col in ["Provinsi", "Kabupaten", "Kecamatan", "Desa"]:
    df_filter[col] = df_filter[col].astype(str).str.strip().str.upper()

# ── Filter hanya Kabupaten BREBES (uncomment kalau perlu) ──
# df_filter = df_filter[df_filter["Kabupaten"] == "BREBES"].reset_index(drop=True)
# ───────────────────────────────────────────────────────────

print(f"[INFO] Total desa (Bengkulu UB): {len(df_filter)}")
print(df_filter.head())


# ============================================================
# HELPER: Bangun session dari cookies Selenium
# ============================================================
def _build_session_from_cookies(cookies):
    session = requests.Session()

    xsrf_token   = None
    cookie_names = []
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
        cookie_names.append(c["name"])
        name_upper = c["name"].upper()
        if "XSRF" in name_upper or "CSRF" in name_upper:
            xsrf_token = c["value"]

    print(f"  [DEBUG] Cookie names: {cookie_names}")

    headers = {
        "Content-Type" : "application/json",
        "Accept"       : "application/json, text/plain, */*",
        "Origin"       : BASE_URL,
        "Referer"      : FASIH_URL,
        "User-Agent"   : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    }
    if xsrf_token:
        headers["X-XSRF-TOKEN"] = xsrf_token
        print(f"  [DEBUG] X-XSRF-TOKEN di-set: {xsrf_token[:30]}...")
    else:
        print("  [DEBUG] TIDAK ada XSRF/CSRF token di cookies.")

    session.headers.update(headers)
    return session


# ============================================================
# STEP 1: LOGIN MANUAL → AMBIL COOKIES
# ============================================================
def login_dan_ambil_cookies():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,800")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(120)
    driver.get(FASIH_URL)

    print("\n" + "="*60)
    print("  Login manual di browser, lalu tekan ENTER.")
    print("  PENTING: tunggu sampai halaman tabel/data sudah terbuka")
    print("  (bukan halaman login) sebelum tekan ENTER.")
    print("="*60)
    input("\n  >> Tekan ENTER setelah halaman data terbuka... ")

    try:
        driver.get(f"{BASE_URL}/analytic")
        time.sleep(2)
    except Exception:
        pass

    cookies = driver.get_cookies()
    driver.quit()
    print("[OK] Browser ditutup, cookies diambil.")
    return _build_session_from_cookies(cookies)


def refresh_session(session):
    """Re-login manual saat 403."""
    print("\n" + "="*60)
    print("  [SESSION EXPIRED] 403 Forbidden.")
    print("  Login ulang di browser, lalu tekan ENTER.")
    print("="*60)

    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,800")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(120)
    driver.get(FASIH_URL)

    input("\n  >> Tekan ENTER setelah halaman data terbuka... ")

    try:
        driver.get(f"{BASE_URL}/analytic")
        time.sleep(2)
    except Exception:
        pass

    cookies = driver.get_cookies()
    driver.quit()
    print("[OK] Browser ditutup, cookies diperbarui.")

    session.cookies.clear()
    xsrf_token = None
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
        if "XSRF" in c["name"].upper() or "CSRF" in c["name"].upper():
            xsrf_token = c["value"]
    if xsrf_token:
        session.headers.update({"X-XSRF-TOKEN": xsrf_token})
        print(f"  [DEBUG] X-XSRF-TOKEN diperbarui: {xsrf_token[:30]}...")


# ============================================================
# STEP 2: LOOKUP UUID REGION
# ============================================================
def fetch_level1(session):
    try:
        r = session.get(f"{REGION_BASE}/level1", params={"groupId": GROUP_ID}, timeout=30)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"  [WARN] fetch level1: {e}")
        return []

def fetch_level2(session, level1_fullcode):
    try:
        r = session.get(f"{REGION_BASE}/level2",
                        params={"groupId": GROUP_ID, "level1FullCode": level1_fullcode},
                        timeout=30)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"  [WARN] fetch level2 (fullCode={level1_fullcode}): {e}")
        return []

def fetch_level3(session, level2_id):
    try:
        r = session.get(f"{REGION_BASE}/level3",
                        params={"groupId": GROUP_ID, "level2Id": level2_id},
                        timeout=30)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"  [WARN] fetch level3 (level2Id={level2_id}): {e}")
        return []

def fetch_level4(session, level3_id):
    try:
        r = session.get(f"{REGION_BASE}/level4",
                        params={"groupId": GROUP_ID, "level3Id": level3_id},
                        timeout=30)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"  [WARN] fetch level4 (level3Id={level3_id}): {e}")
        return []


# [2] Region cache: reuse file JSON kalau sudah ada, rebuild kalau belum/force
def load_or_build_region_cache(session, force_rebuild=False):
    if not force_rebuild and Path(REGION_CACHE_FILE).exists():
        print(f"[INFO] Reusing region cache dari '{REGION_CACHE_FILE}' (gunakan --rebuild-cache untuk paksa rebuild).")
        with open(REGION_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    print("\n[INFO] Membangun cache UUID region (ini hanya dilakukan sekali)...")
    cache = {}

    items  = fetch_level1(session)
    l1_map = {i["name"].strip().upper(): i for i in items}
    cache["l1"] = l1_map
    print(f"  Level 1 (Provinsi): {len(l1_map)} item")

    for provinsi, grp_prov in df_filter.groupby("Provinsi"):
        l1_info = l1_map.get(provinsi)
        if not l1_info:
            print(f"  [WARN] Provinsi '{provinsi}' tidak ditemukan")
            continue
        l1_fullcode = l1_info.get("fullCode") or l1_info.get("code")

        items  = fetch_level2(session, l1_fullcode)
        l2_map = {i["name"].strip().upper(): i for i in items}
        cache[f"l2_{provinsi}"] = l2_map
        print(f"  Level 2 [{provinsi}] (fullCode={l1_fullcode}): {len(l2_map)} item")

        for kabupaten, grp_kab in grp_prov.groupby("Kabupaten"):
            l2_info = l2_map.get(kabupaten)
            if not l2_info:
                print(f"  [WARN] Kabupaten '{kabupaten}' tidak ditemukan")
                continue
            l2_id = l2_info["id"]

            items  = fetch_level3(session, l2_id)
            l3_map = {i["name"].strip().upper(): i for i in items}
            cache[f"l3_{kabupaten}"] = l3_map
            print(f"  Level 3 [{kabupaten}]: {len(l3_map)} item")

            for kecamatan in grp_kab["Kecamatan"].unique():
                l3_info = l3_map.get(kecamatan)
                if not l3_info:
                    print(f"  [WARN] Kecamatan '{kecamatan}' tidak ditemukan")
                    continue
                l3_id = l3_info["id"]

                items  = fetch_level4(session, l3_id)
                l4_map = {i["name"].strip().upper(): i for i in items}
                cache[f"l4_{kecamatan}"] = l4_map
                print(f"  Level 4 [{kecamatan}]: {len(l4_map)} item")

    with open(REGION_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, default=str)
    print(f"[OK] Cache disimpan ke '{REGION_CACHE_FILE}'.\n")
    return cache


# ============================================================
# STEP 3: FETCH DATA TABEL VIA API
# ============================================================

# [4] draw counter: increment per request supaya lebih natural
_draw_counter = 0

def _next_draw():
    global _draw_counter
    _draw_counter += 1
    return _draw_counter


def build_payload(r1, r2, r3, r4, start=0, length=PAGE_SIZE):
    cols = [
        {"data": "id",           "name": "", "searchable": True,  "orderable": False, "search": {"value": "", "regex": False}},
        {"data": "codeIdentity", "name": "", "searchable": True,  "orderable": False, "search": {"value": "", "regex": False}},
        {"data": "data1",        "name": "", "searchable": True,  "orderable": True,  "search": {"value": "", "regex": False}},
        {"data": "data2",        "name": "", "searchable": True,  "orderable": True,  "search": {"value": "", "regex": False}},
        {"data": "data3",        "name": "", "searchable": True,  "orderable": True,  "search": {"value": "", "regex": False}},
        {"data": "data4",        "name": "", "searchable": True,  "orderable": True,  "search": {"value": "", "regex": False}},
    ]
    return {
        "draw"   : _next_draw(),   # [4] increment tiap request
        "columns": cols,
        "order"  : [{"column": 0, "dir": "asc"}],
        "start"  : start,
        "length" : length,
        "search" : {"value": "", "regex": False},
        "assignmentExtraParam": {
            "region1Id": r1, "region2Id": r2, "region3Id": r3, "region4Id": r4,
            "region5Id": None, "region6Id": None, "region7Id": None,
            "region8Id": None, "region9Id": None, "region10Id": None,
            "surveyPeriodId": SURVEY_PERIOD_ID,
            "assignmentErrorStatusType": -1, "assignmentStatusAlias": None,
            "data1": None, "data2": None, "data3": None, "data4": None,
            "data5": None, "data6": None, "data7": None, "data8": None,
            "data9": None, "data10": None,
            "userIdResponsibility": None, "currentUserId": None,
            "regionId": None, "filterTargetType": "TARGET_ONLY",
        }
    }


def fetch_data_desa(session, r1, r2, r3, r4, max_auth_retry=2):
    """
    Fetch semua data untuk satu desa dengan pagination.
    - 403 → re-login (max max_auth_retry kali)
    - 503 / non-JSON / timeout → tunggu RETRY_WAIT detik lalu retry (max MAX_SERVER_RETRY kali)
    - Desa dikembalikan kosong hanya jika semua retry habis
    """
    url          = f"{BASE_URL}/analytic/api/v2/assignment/datatable-all-user-survey-periode"
    semua        = []
    start        = 0
    total        = 0
    auth_retries = 0
    srv_retries  = 0

    while True:
        try:
            r = session.post(url, json=build_payload(r1, r2, r3, r4, start), timeout=60)

            # ── 403: session expired ──────────────────────────────
            if r.status_code == 403:
                if auth_retries < max_auth_retry:
                    auth_retries += 1
                    print(f"    [WARN] 403 — re-login ({auth_retries}/{max_auth_retry})...")
                    refresh_session(session)
                    continue
                else:
                    print(f"    [ERROR] 403 setelah {max_auth_retry}x re-login. Desa dilewati.")
                    break

            # ── 5xx: server sedang down/overload ─────────────────
            if r.status_code >= 500:
                if srv_retries < MAX_SERVER_RETRY:
                    srv_retries += 1
                    print(f"    [WARN] {r.status_code} Server Error — "
                          f"tunggu {RETRY_WAIT}s, retry ({srv_retries}/{MAX_SERVER_RETRY})...")
                    time.sleep(RETRY_WAIT)
                    continue
                else:
                    print(f"    [ERROR] Server error terus setelah {MAX_SERVER_RETRY}x retry. "
                          f"Desa dilewati.")
                    break

            r.raise_for_status()

            # ── Coba parse JSON ───────────────────────────────────
            try:
                data = r.json()
            except ValueError:
                if srv_retries < MAX_SERVER_RETRY:
                    srv_retries += 1
                    preview = r.text[:120].replace("\n", " ")
                    print(f"    [WARN] Response bukan JSON (preview: {preview!r}) — "
                          f"tunggu {RETRY_WAIT}s, retry ({srv_retries}/{MAX_SERVER_RETRY})...")
                    time.sleep(RETRY_WAIT)
                    continue
                else:
                    print(f"    [ERROR] Response terus bukan JSON setelah {MAX_SERVER_RETRY}x retry. "
                          f"Desa dilewati.")
                    break

            # ── Sukses ────────────────────────────────────────────
            srv_retries  = 0
            auth_retries = 0

        except requests.exceptions.Timeout:
            if srv_retries < MAX_SERVER_RETRY:
                srv_retries += 1
                print(f"    [WARN] Timeout — tunggu {RETRY_WAIT}s, "
                      f"retry ({srv_retries}/{MAX_SERVER_RETRY})...")
                time.sleep(RETRY_WAIT)
                continue
            else:
                print(f"    [ERROR] Timeout terus setelah {MAX_SERVER_RETRY}x retry. Desa dilewati.")
                break

        except Exception as e:
            print(f"    [ERROR] start={start}: {e}")
            break

        records = data.get("searchData", [])
        total   = data.get("totalHit", 0)
        semua.extend(records)
        if len(semua) >= total or not records:
            break
        start += PAGE_SIZE

    return semua, total


# ============================================================
# STEP 4: EKSTRAK KOLOM DARI JSON
# ============================================================
def ekstrak_record(rec, provinsi, kabupaten, kecamatan, desa):
    region = rec.get("region", {})
    l4 = region.get("level1", {}).get("level2", {}).get("level3", {}).get("level4", {})
    l5 = l4.get("level5", {})
    l6 = l5.get("level6", {})
    return {
        "Provinsi"              : provinsi,
        "Kabupaten"             : kabupaten,
        "Kecamatan"             : kecamatan,
        "Desa"                  : desa,
        "codeIdentity"          : rec.get("codeIdentity"),
        "assignmentStatus"      : rec.get("assignmentStatusAlias"),
        "data1"                 : rec.get("data1"),
        "data2"                 : rec.get("data2"),
        "data3"                 : rec.get("data3"),
        "data4"                 : rec.get("data4"),
        "data5"                 : rec.get("data5"),
        "data6"                 : rec.get("data6"),
        "data7"                 : rec.get("data7"),
        "data8"                 : rec.get("data8"),
        "data9"                 : rec.get("data9"),
        "done"                  : rec.get("done"),
        "sumError"              : rec.get("sumError"),
        "sumRemark"             : rec.get("sumRemark"),
        "sumClean"              : rec.get("sumClean"),
        "strata"                : rec.get("strata"),
        "currentUserFullname"   : rec.get("currentUserFullname"),
        "currentUserUsername"   : rec.get("currentUserUsername"),
        "currentUserSurveyRole" : rec.get("currentUserSurveyRoleName"),
        "dateCreated"           : rec.get("dateCreated"),
        "dateModified"          : rec.get("dateModified"),
        "SLS"                   : l5.get("name"),
        "SUBSLS"                : l6.get("name"),
        "fullCode"              : l6.get("fullCode"),
        "mode"                  : ", ".join(rec.get("mode", [])),
    }


def save_excel(semua_data, path):
    """Simpan data ke Excel."""
    if semua_data:
        pd.DataFrame(semua_data).to_excel(path, index=False)


# ============================================================
# [3] DELTA UPDATE: cek apakah desa perlu di-refresh
# ============================================================
def parse_date(date_str):
    """Parse dateModified string ke datetime. Return None kalau gagal."""
    if not date_str:
        return None
    # Coba beberapa format umum
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(date_str)[:26], fmt)
        except ValueError:
            continue
    return None


def desa_perlu_update(key, semua_data_lama, last_run_time):
    """
    Cek apakah desa ini perlu di-fetch ulang.
    Logika: kalau ada record desa ini dengan dateModified > last_run_time → perlu update.
    Kalau tidak ada record sama sekali → perlu fetch.
    """
    if last_run_time is None:
        return True  # Tidak ada info run sebelumnya, fetch semua

    provinsi, kabupaten, kecamatan, desa = key
    records_desa = [
        r for r in semua_data_lama
        if r.get("Provinsi") == provinsi
        and r.get("Kabupaten") == kabupaten
        and r.get("Kecamatan") == kecamatan
        and r.get("Desa") == desa
    ]

    if not records_desa:
        return True  # Belum pernah di-fetch

    # Cek apakah ada record yang dateModified-nya lebih baru dari last_run_time
    for rec in records_desa:
        dm = parse_date(rec.get("dateModified"))
        if dm and dm > last_run_time:
            return True

    return False  # Semua record masih fresh


# ============================================================
# MAIN
# ============================================================
def main():
    # Cek flag --rebuild-cache dari argumen
    force_rebuild_cache = "--rebuild-cache" in sys.argv

    session = login_dan_ambil_cookies()

    # [2] Reuse cache region kalau sudah ada
    cache = load_or_build_region_cache(session, force_rebuild=force_rebuild_cache)

    # ── Resume: muat checkpoint jika ada ───────────────────────────────────
    semua_data, gagal = [], []
    desa_selesai = set()
    last_run_time = None  # [3] waktu run terakhir untuk delta update

    if Path(CHECKPOINT_FILE).exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            cp = json.load(f)
        semua_data    = cp.get("semua_data", [])
        gagal         = cp.get("gagal", [])
        desa_selesai  = set(tuple(x) for x in cp.get("desa_selesai", []))
        last_run_str  = cp.get("last_run_time")
        last_run_time = parse_date(last_run_str) if last_run_str else None

        print(f"[INFO] Resume dari checkpoint: {len(semua_data)} baris, "
              f"{len(desa_selesai)} desa sudah selesai.")
        if last_run_time:
            print(f"[INFO] Last run: {last_run_time} — hanya desa yang berubah setelahnya yang akan di-fetch ulang.")

        save_excel(semua_data, OUTPUT_FILE)
        print(f"[INFO] Excel diperbarui dari checkpoint: {len(semua_data)} baris → {OUTPUT_FILE}\n")

    run_start_time = datetime.now()

    def save_checkpoint():
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "semua_data"   : semua_data,
                "gagal"        : gagal,
                "desa_selesai" : [list(x) for x in desa_selesai],
                "last_run_time": run_start_time.isoformat(),  # [3] simpan waktu run ini
            }, f, ensure_ascii=False, default=str)
        save_excel(semua_data, OUTPUT_FILE)
    # ───────────────────────────────────────────────────────────────────────

    total_desa, desa_ke = len(df_filter), 0
    skipped_delta = 0  # [3] counter desa yang di-skip karena belum berubah

    for (provinsi, kabupaten, kecamatan), group in df_filter.groupby(
            ["Provinsi", "Kabupaten", "Kecamatan"], sort=False):

        l1_info = cache.get("l1", {}).get(provinsi)
        l2_info = cache.get(f"l2_{provinsi}", {}).get(kabupaten)
        l3_info = cache.get(f"l3_{kabupaten}", {}).get(kecamatan)

        if not l3_info:
            print(f"\n[WARN] UUID tidak ditemukan: {provinsi} > {kabupaten} > {kecamatan}")
            for desa in group["Desa"]:
                gagal.append({"Provinsi": provinsi, "Kabupaten": kabupaten,
                               "Kecamatan": kecamatan, "Desa": desa,
                               "alasan": "UUID kecamatan tidak ditemukan"})
            continue

        r1 = l1_info["id"]
        r2 = l2_info["id"]
        r3 = l3_info["id"]

        print(f"\n{'='*60}")
        print(f"{provinsi} > {kabupaten} > {kecamatan}  ({len(group)} desa)")
        print(f"{'='*60}")

        for desa in group["Desa"]:
            desa_ke += 1
            l4_info = cache.get(f"l4_{kecamatan}", {}).get(desa)

            if not l4_info:
                print(f"  [{desa_ke}/{total_desa}] {desa}: UUID tidak ditemukan, skip.")
                gagal.append({"Provinsi": provinsi, "Kabupaten": kabupaten,
                               "Kecamatan": kecamatan, "Desa": desa,
                               "alasan": "UUID desa tidak ditemukan"})
                continue

            r4    = l4_info["id"]
            key   = (provinsi, kabupaten, kecamatan, desa)

            # Skip desa yang sudah selesai di run ini (resume mid-run)
            if key in desa_selesai:
                print(f"  [{desa_ke}/{total_desa}] {desa}: sudah selesai di run ini, dilewati.")
                continue

            # [3] Delta update: skip kalau data belum berubah sejak run terakhir
            if not desa_perlu_update(key, semua_data, last_run_time):
                skipped_delta += 1
                print(f"  [{desa_ke}/{total_desa}] {desa}: tidak ada perubahan sejak run terakhir, skip.")
                desa_selesai.add(key)  # tandai selesai supaya tidak diproses lagi
                continue

            t0 = time.time()
            records, total_hit = fetch_data_desa(session, r1, r2, r3, r4)
            elapsed = time.time() - t0

            if records:
                # [3] Hapus data lama untuk desa ini, ganti dengan data baru
                semua_data = [
                    r for r in semua_data
                    if not (r.get("Provinsi") == provinsi
                            and r.get("Kabupaten") == kabupaten
                            and r.get("Kecamatan") == kecamatan
                            and r.get("Desa") == desa)
                ]
                for rec in records:
                    semua_data.append(ekstrak_record(rec, provinsi, kabupaten, kecamatan, desa))
                desa_selesai.add(key)
                save_checkpoint()
                print(f"  [{desa_ke}/{total_desa}] {desa}: "
                      f"{len(records)}/{total_hit} baris ({elapsed:.1f}s) ✓")
            else:
                print(f"  [{desa_ke}/{total_desa}] {desa}: "
                      f"0/{total_hit} baris ({elapsed:.1f}s) ← GAGAL, dicatat")
                gagal.append({"Provinsi": provinsi, "Kabupaten": kabupaten,
                               "Kecamatan": kecamatan, "Desa": desa,
                               "alasan": "0 records returned"})

            # [1] Delay antar desa supaya tidak keliatan seperti bot
            time.sleep(DELAY_ANTAR_DESA)

        print(f"  → [SAVE] {len(semua_data)} total baris → {OUTPUT_FILE}")

    # ── Output akhir ────────────────────────────────────────────────────────
    if semua_data:
        save_excel(semua_data, OUTPUT_FILE)
        print(f"\n{'='*60}")
        print(f"[SELESAI] {len(semua_data)} baris → {OUTPUT_FILE}")
        if skipped_delta:
            print(f"[INFO] {skipped_delta} desa di-skip (data belum berubah sejak run terakhir)")
        print(pd.DataFrame(semua_data).head(5).to_string())
    else:
        print("\n[WARN] Tidak ada data yang berhasil di-fetch.")

    if gagal:
        pd.DataFrame(gagal).to_excel("desa_gagal.xlsx", index=False)
        print(f"\n[INFO] {len(gagal)} desa gagal → desa_gagal.xlsx")
    else:
        print("\n[INFO] Semua desa berhasil!")

    # Hapus checkpoint kalau selesai sempurna
    if Path(CHECKPOINT_FILE).exists():
        Path(CHECKPOINT_FILE).unlink()
        print("[INFO] Checkpoint dihapus.")

if __name__ == "__main__":
    main()