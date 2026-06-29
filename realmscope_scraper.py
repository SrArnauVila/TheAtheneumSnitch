import urllib.request
import threading
from bs4 import BeautifulSoup
from typing import Optional
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from player_tracker import get_online_status
import concurrent.futures
import time as time_module

REALMSCOPE_BASE = "https://realmscope.gg"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

try:
    from curl_cffi import requests as _cffi_req
    _HAS_CURL_CFFI = True
except ImportError:
    _cffi_req = None
    _HAS_CURL_CFFI = False

# Persistent browser session — one Chrome for the bot's lifetime.
# Solves Cloudflare's JS challenge once; subsequent requests reuse the session cookies.
_persistent_driver = None
_driver_lock = threading.Lock()
_cf_cookie_cache: dict = {}
_cf_cookie_ts: float = 0.0
_CF_COOKIE_TTL: float = 3600.0


def _ensure_driver() -> webdriver.Chrome:
    """Return the persistent Chrome session, (re)creating if crashed. Caller must hold _driver_lock."""
    global _persistent_driver
    if _persistent_driver is not None:
        try:
            _ = _persistent_driver.current_url
            return _persistent_driver
        except Exception:
            print("Persistent driver died — restarting")
            try:
                _persistent_driver.quit()
            except Exception:
                pass
            _persistent_driver = None

    _persistent_driver = _make_driver()
    print("Browser: new session, solving CF challenge...")
    try:
        _persistent_driver.get(f"{REALMSCOPE_BASE}/")
        _wait_for_cloudflare(_persistent_driver, timeout=30)
        print(f"Browser: ready — {_persistent_driver.title[:60]}")
    except Exception as e:
        print(f"Browser: warmup failed: {e}")
    return _persistent_driver


def _browser_get_soup(url: str, wait_css: str = None) -> Optional[BeautifulSoup]:
    """Navigate the persistent browser to url and return a BeautifulSoup."""
    global _persistent_driver
    with _driver_lock:
        driver = _ensure_driver()
        try:
            driver.get(url)
            _wait_for_cloudflare(driver)
            if wait_css:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, wait_css))
                )
            return BeautifulSoup(driver.page_source, "html.parser")
        except Exception as e:
            print(f"_browser_get_soup({url}): {e}")
            try:
                _persistent_driver.quit()
            except Exception:
                pass
            _persistent_driver = None
            return None


def _cf_cookies() -> dict:
    """Return cached CF cookies from the persistent browser, refreshing if stale."""
    global _cf_cookie_cache, _cf_cookie_ts
    now = time_module.time()
    if _cf_cookie_cache and (now - _cf_cookie_ts) < _CF_COOKIE_TTL:
        return _cf_cookie_cache
    with _driver_lock:
        driver = _ensure_driver()
        try:
            cookies = {c["name"]: c["value"] for c in driver.get_cookies()
                       if c["name"] in ("cf_clearance", "__cf_bm", "__cflb")}
            _cf_cookie_cache = cookies
            _cf_cookie_ts = now
            return cookies
        except Exception:
            return _cf_cookie_cache


def fetch_page(url: str) -> Optional[BeautifulSoup]:
    """Fetch a static page. Tries curl_cffi with browser CF cookies first, then browser fallback."""
    if _HAS_CURL_CFFI:
        try:
            cookies = _cf_cookies()
            resp = _cffi_req.get(url, impersonate="chrome120", timeout=15, cookies=cookies)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            print(f"fetch_page: curl_cffi got {resp.status_code} for {url}, using browser")
        except Exception as e:
            print(f"fetch_page: curl_cffi error: {e}")
    return _browser_get_soup(url)

def get_player_info(player_name: str) -> Optional[dict]:
    soup = fetch_page(f"{REALMSCOPE_BASE}/player/{player_name}")
    if not soup:
        return None

    stats_list = soup.find("ul", id="player-stats-list")
    if not stats_list:
        return None

    # Pull data attributes directly — clean and reliable
    account_fame     = stats_list.get("data-account-fame", "?")
    total_exalts     = stats_list.get("data-total-exaltations", "?")
    total_skins      = stats_list.get("data-total-skin-count", "?")
    total_fame       = stats_list.get("data-total-character-fame", "?")
    seasonal_fame    = stats_list.get("data-total-seasonal-character-fame", "?")
    total_shinies    = stats_list.get("data-total-shiny-count", "?")
    seasonal_shinies = stats_list.get("data-total-seasonal-shiny-count", "?")

    # Replace the entire stars + title block with this:

    stars = "?"
    title = ""

    player_name_div = soup.find("div", class_="player-name")
    if player_name_div:
        # Stars — the number is always in a span with "margin-left: 4px"
        number_span = player_name_div.find("span", style=lambda s: s and "margin-left: 4px" in s)
        if number_span:
            stars = number_span.get_text(strip=True)

        # Title — first div that isn't First Seen / Last Seen
        for div in player_name_div.find_all("div"):
            text = div.get_text(strip=True)
            if (text
                and "First Seen" not in text
                and "Last Seen" not in text
                and "Last Server" not in text):
                title = text
                break

    # Add this after the title block:
    guild_rank = ""
    # Find the player-info-list that contains guild info (has "Rank:" li)
    for ul in soup.find_all("ul", class_="player-info-list"):
        for li in ul.find_all("li"):
            if li.get_text(strip=True).startswith("Rank:"):
                guild_rank = li.get_text(strip=True).replace("Rank:", "").strip()
                break
    # Last seen and server from the list items
    last_seen = "?"
    server = "?"
    for li in stats_list.find_all("li"):
        text = li.get_text(" ", strip=True)
        if "Last Seen:" in text:
            last_seen = text.split("Last Seen:")[-1].strip()
        if "Last Server:" in text:
            server = text.split("Last Server:")[-1].strip()

    # Rank links
    def get_rank(label_text):
        for li in stats_list.find_all("li"):
            if label_text in li.get_text():
                a = li.find("a")
                return a.get_text(strip=True) if a else ""
        return ""

    return {
        "name": player_name,
        "title": title,
        "stars": stars,
        "account_fame": int(account_fame) if account_fame != "?" else 0,
        "total_fame": int(total_fame) if total_fame != "?" else 0,
        "seasonal_fame": int(seasonal_fame) if seasonal_fame != "?" else 0,
        "exaltations": int(total_exalts) if total_exalts != "?" else 0,
        "skins": int(total_skins) if total_skins != "?" else 0,
        "total_shinies": int(total_shinies) if total_shinies != "?" else 0,
        "seasonal_shinies": int(seasonal_shinies) if seasonal_shinies != "?" else 0,
        "last_seen": last_seen,
        "server": server,
        "rank_fame": get_rank("Fame:"),
        "rank_seasonal_fame": get_rank("Seasonal Fame:"),
        "rank_skins": get_rank("Skins:"),
        "rank_account_fame": get_rank("Account Fame:"),
        "guild_rank": guild_rank,
    }

def _get_rendered_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetch a JS-rendered page via the persistent browser."""
    return _browser_get_soup(url, wait_css="table.party-table tbody tr")


def get_top_parties(limit: int = 5) -> Optional[list]:
    soup = _get_rendered_soup(f"{REALMSCOPE_BASE}/party")
    if not soup:
        return None

    rows = soup.select("table.party-table tbody tr")
    parties = []
    for row in rows[:limit]:
        tds = row.find_all("td")
        if len(tds) < 10:
            continue

        party_id = tds[0].get_text(strip=True).replace("\u25cf", "").strip()
        desc     = tds[1].get_text(strip=True) or "—"
        players  = tds[2].get_text(strip=True).replace("/", " / ")
        status   = tds[3].get_text(strip=True)
        privacy  = tds[4].get_text(strip=True)
        ptype    = tds[5].get_text(strip=True)
        server   = tds[7].get_text(strip=True)
        created  = tds[9].get_text(strip=True)

        parties.append({
            "id":      party_id,
            "desc":    desc,
            "players": players,
            "status":  status,
            "privacy": privacy,
            "type":    ptype,
            "server":  server,
            "created": created,
        })

    return parties


def get_shiny_data(player_name: str) -> Optional[dict]:
    soup = fetch_page(f"{REALMSCOPE_BASE}/shiny/{player_name}")
    if not soup:
        return None

    # Stats box
    info_box = soup.find("div", class_="shiny-info-box")
    if not info_box:
        return None

    def get_stat(label):
        for item in info_box.select(".shiny-stat-item"):
            lbl = item.select_one(".shiny-stat-label")
            val = item.select_one(".shiny-stat-value")
            sub = item.select_one(".shiny-stat-sub")
            if lbl and label.lower() in lbl.get_text(strip=True).lower():
                return {
                    "value": val.get_text(strip=True) if val else "?",
                    "sub": sub.get_text(strip=True) if sub else ""
                }
        return {"value": "?", "sub": ""}

    total       = get_stat("Total Shinies")
    progress    = get_stat("Collection Progress")
    rank        = get_stat("Shiny Rank")
    season_rank = get_stat("Seasonal Shiny Rank")

    # Obtained shinies — data-is-obtained="1", grouped by season
    seasons = []
    for season_box in soup.select("div.shiny-season-box"):
        title_el = season_box.select_one(".shiny-season-title")
        season_name = title_el.get_text(strip=True) if title_el else "Unknown"
        obtained = []
        for img in season_box.select("img.shiny-item-image"):
            if img.get("data-is-obtained") == "1":
                obtained.append({
                    "name": img.get("data-item-name", "Unknown"),
                    "asset_id": _extract_asset_id(img.get("src", "")),
                    "obtained_date": img.get("data-obtained-date", "")
                })
        if obtained:
            seasons.append({"season": season_name, "items": obtained})

    return {
        "total": total["value"],
        "progress": progress["value"],
        "progress_pct": progress["sub"],
        "rank": rank["value"],
        "rank_sub": rank["sub"],
        "season_rank": season_rank["value"],
        "season_rank_sub": season_rank["sub"],
        "seasons": seasons
    }

def _extract_asset_id(src: str) -> Optional[int]:
    try:
        return int(src.strip("/").split("/")[-1].replace(".png", "").replace("_hidden", ""))
    except ValueError:
        return None

def _make_driver() -> webdriver.Chrome:
    """Create a Chrome instance that bypasses Cloudflare bot detection.

    Uses undetected-chromedriver (patches cdc_ ChromeDriver variables out of the
    binary) + non-headless mode via Xvfb (real rendering pipeline, no headless
    fingerprint). Falls back to regular Selenium if uc isn't installed.
    """
    import os, shutil
    has_display = bool(os.environ.get("DISPLAY"))

    try:
        import undetected_chromedriver as uc

        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--log-level=3")

        # Find system Chromium binary
        browser_path = next(
            (p for p in ("/usr/bin/chromium-browser", "/usr/bin/chromium", "/usr/bin/google-chrome")
             if shutil.which(p)),
            None,
        )

        driver = uc.Chrome(
            options=options,
            driver_executable_path="/usr/bin/chromedriver",
            browser_executable_path=browser_path,
            headless=not has_display,
            use_subprocess=False,
            version_main=None,
        )
        driver.set_page_load_timeout(30)
        mode = f"non-headless (DISPLAY={os.environ.get('DISPLAY')})" if has_display else "headless=new"
        print(f"_make_driver: undetected-chromedriver ({mode}, browser={browser_path})")
        return driver

    except Exception as e:
        print(f"_make_driver: undetected-chromedriver unavailable ({e}), using regular Selenium")

    # Fallback: regular Selenium with best-effort anti-detection flags
    options = Options()
    if not has_display:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--log-level=3")
    service = Service("/usr/bin/chromedriver", log_path="/tmp/chromedriver.log")
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}, app: {}, csi: () => {}, loadTimes: () => {}};
            """
        })
    except Exception:
        pass
    return driver


def _wait_for_cloudflare(driver, timeout: int = 15) -> bool:
    """
    Waits up to `timeout` seconds for Cloudflare's 'Just a moment...' challenge to pass.
    Returns True if the real page loaded, False if still on Cloudflare after timeout.
    """
    for _ in range(timeout):
        if "just a moment" not in driver.title.lower():
            return True
        time.sleep(1)
    return "just a moment" not in driver.title.lower()

def get_guild_members(guild_name: str) -> set:
    global _persistent_driver
    members = set()
    with _driver_lock:
        driver = _ensure_driver()
        try:
            driver.get(f"{REALMSCOPE_BASE}/guild/{guild_name}")
            _wait_for_cloudflare(driver)
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr[data-player]"))
            )
            soup = BeautifulSoup(driver.page_source, "html.parser")
            for table in soup.find_all("table"):
                rows = table.select("tbody tr[data-player]")
                if rows:
                    for row in rows:
                        player = row.get("data-player", "").lower()
                        if player:
                            members.add(player)
                    break
            print(f"Found {len(members)} guild members")
        except Exception as e:
            print(f"Error fetching guild members: {e}")
            try:
                _persistent_driver.quit()
            except Exception:
                pass
            _persistent_driver = None
    return members


def _get_party_members_selenium(party_ids: list) -> dict:
    """Opens the party page and clicks each member dot to get member lists."""
    global _persistent_driver
    result = {}
    with _driver_lock:
        driver = _ensure_driver()
        try:
            driver.get(f"{REALMSCOPE_BASE}/party")
            _wait_for_cloudflare(driver)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.party-table tbody tr"))
            )

            soup = BeautifulSoup(driver.page_source, "html.parser")
            for row in soup.select("table.party-table tbody tr"):
                pid = row.get("data-party-id")
                if not pid:
                    continue
                tds = row.find_all("td")
                if len(tds) < 10:
                    continue
                desc   = tds[1].get_text(strip=True) or "—"
                server = tds[7].get_text(strip=True)
                players_text = tds[2].get_text(strip=True)
                current, max_p = 0, 50
                try:
                    parts   = players_text.split("/")
                    current = int(parts[0].strip())
                    max_p   = int(parts[1].strip())
                except Exception:
                    pass
                result[pid] = {
                    "desc":    desc,
                    "current": current,
                    "max":     max_p,
                    "server":  server,
                    "members": []
                }

            for pid in party_ids:
                if pid not in result:
                    continue
                try:
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, f"tr[data-party-id='{pid}'] .members-dot")
                        )
                    )
                    dot = driver.find_element(
                        By.CSS_SELECTOR, f"tr[data-party-id='{pid}'] .members-dot"
                    )
                    driver.execute_script("arguments[0].scrollIntoView(true);", dot)
                    driver.execute_script("arguments[0].click();", dot)
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "div.member-grid a.member-card")
                        )
                    )
                    modal_soup = BeautifulSoup(driver.page_source, "html.parser")
                    members = []
                    for card in modal_soup.select("div.member-grid a.member-card"):
                        href = card.get("href", "")
                        name = href.replace("/player/", "").lower()
                        if name:
                            members.append(name)
                    result[pid]["members"] = members
                    try:
                        WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.ID, "membersModalClose"))
                        )
                        close_btn = driver.find_element(By.ID, "membersModalClose")
                        driver.execute_script("arguments[0].click();", close_btn)
                        WebDriverWait(driver, 3).until(
                            EC.invisibility_of_element_located(
                                (By.CSS_SELECTOR, "div.member-grid")
                            )
                        )
                    except Exception:
                        driver.execute_script("document.body.click();")
                        time.sleep(0.5)
                except Exception as e:
                    print(f"Could not get members for party {pid}: {e}")
                    time.sleep(0.5)
                    continue

        except Exception as e:
            print(f"_get_party_members_selenium error: {e}")
            try:
                _persistent_driver.quit()
            except Exception:
                pass
            _persistent_driver = None

    return result

def get_guild_party_status(guild_name: str) -> dict:
    """
    Returns guild members found in parties.
    Result: { player_name: { party_id, desc, current, max, server } }
    """
    guild_members = get_guild_members(guild_name)
    if not guild_members:
        return {}

    # Get all parties with member dots
    soup = _get_rendered_soup(f"{REALMSCOPE_BASE}/party")
    if not soup:
        return {}

    party_ids_with_members = []
    for row in soup.select("table.party-table tbody tr.has-members"):
        pid = row.get("data-party-id")
        if pid:
            party_ids_with_members.append(pid)

    all_parties = _get_party_members_selenium(party_ids_with_members)

    # Cross-reference
    found = {}
    for pid, info in all_parties.items():
        for member in info["members"]:
            if member in guild_members:
                display = member.capitalize()
                found[display] = {
                    "party_id": pid,
                    "desc":     info["desc"],
                    "current":  info["current"],
                    "max":      info["max"],
                    "server":   info["server"]
                }
    return found

def get_guild_party_status_with_members(guild_name: str, guild_members: set) -> dict:
    """Same as get_guild_party_status but uses a pre-fetched member set."""
    if not guild_members:
        return {}

    soup = _get_rendered_soup(f"{REALMSCOPE_BASE}/party")
    if not soup:
        return {}

    party_ids_with_members = []
    for row in soup.select("table.party-table tbody tr.has-members"):
        pid = row.get("data-party-id")
        if pid:
            party_ids_with_members.append(pid)

    all_parties = _get_party_members_selenium(party_ids_with_members)

    found = {}
    for pid, info in all_parties.items():
        for member in info["members"]:
            if member in guild_members:
                display = member.capitalize()
                found[display] = {
                    "party_id": pid,
                    "desc":     info["desc"],
                    "current":  info["current"],
                    "max":      info["max"],
                    "server":   info["server"]
                }
    return found

def get_guild_roster(guild_name: str) -> Optional[list]:
    global _persistent_driver
    members = []
    with _driver_lock:
        driver = _ensure_driver()
        try:
            driver.get(f"{REALMSCOPE_BASE}/guild/{guild_name}")
            _wait_for_cloudflare(driver)
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr[data-player]"))
            )
            soup = BeautifulSoup(driver.page_source, "html.parser")
            member_table = None
            for table in soup.find_all("table"):
                if table.select("tbody tr[data-player]"):
                    member_table = table
                    break
            if member_table:
                for row in member_table.select("tbody tr[data-player]"):
                    tds = row.find_all("td")
                    if len(tds) < 5:
                        continue
                    name_link = tds[1].select_one("a.username-link")
                    name      = name_link.get_text(strip=True) if name_link else row.get("data-player", "")
                    members.append({
                        "name":          name,
                        "rank":          tds[3].get_text(strip=True),
                        "fame":          int(row.get("data-totalfame", 0)),
                        "active_fame":   int(row.get("data-activefame", 0)),
                        "seasonal_fame": int(row.get("data-seasonalfame", 0)),
                        "stars":         int(row.get("data-rank", 0)),
                    })
        except Exception as e:
            print(f"Error fetching guild roster: {e}")
            try:
                _persistent_driver.quit()
            except Exception:
                pass
            _persistent_driver = None
    return members if members else None

def get_player_shiny_count(player_name: str) -> int:
    """Fetches total shiny count from player profile. Returns 0 on failure."""
    soup = fetch_page(f"{REALMSCOPE_BASE}/player/{player_name}")
    if not soup:
        return 0
    stats_list = soup.find("ul", id="player-stats-list")
    if not stats_list:
        return 0
    try:
        return int(stats_list.get("data-total-shiny-count", 0))
    except (ValueError, TypeError):
        return 0

def get_player_recruitment_info(player_name: str) -> Optional[dict]:
    """Fetches all info needed for recruitment evaluation."""
    soup = fetch_page(f"{REALMSCOPE_BASE}/player/{player_name}")
    if not soup:
        return None

    stats_list = soup.find("ul", id="player-stats-list")
    if not soup:
        return None

    # Basic stats from data attributes
    account_fame  = int(stats_list.get("data-account-fame", 0))
    total_fame    = int(stats_list.get("data-total-character-fame", 0))
    seasonal_fame = int(stats_list.get("data-total-seasonal-character-fame", 0))
    exaltations   = int(stats_list.get("data-total-exaltations", 0))
    skins         = int(stats_list.get("data-total-skin-count", 0))
    shinies       = int(stats_list.get("data-total-shiny-count", 0))

    # Stars
    stars = "?"
    player_name_div = soup.find("div", class_="player-name")
    if player_name_div:
        number_span = player_name_div.find("span", style=lambda s: s and "margin-left: 4px" in s)
        if number_span:
            stars = number_span.get_text(strip=True)

    # Last seen and server
    last_seen = "?"
    server    = "?"
    last_li = stats_list.find("li", style=lambda s: s and "margin-top" in s if s else False)
    if last_li:
        for div in last_li.find_all("div"):
            text = div.get_text(strip=True)
            if "Last Seen:" in text:
                last_seen = text.split("Last Seen:")[-1].strip()
            if "Last Server:" in text:
                server = text.split("Last Server:")[-1].strip()

    # Online status
    status = "Offline"
    status_container = soup.find("div", class_="status-container")
    if status_container:
        if status_container.find("div", class_="status-online"):
            status = "Online"

    # Characters from the character table
    char_rows = soup.select("tbody tr[data-level]")
    total_chars = len(char_rows)
    maxed_chars = sum(1 for r in char_rows if r.get("data-stats") == "8")

    # Best character stats
    best_stats = 0
    for r in char_rows:
        try:
            s = int(r.get("data-stats", 0))
            if s > best_stats:
                best_stats = s
        except ValueError:
            pass

    # First seen
    first_seen = "?"
    if player_name_div:
        for div in player_name_div.find_all("div"):
            text = div.get_text(strip=True)
            if "First Seen:" in text:
                first_seen = text.replace("First Seen:", "").strip()
                break

    return {
        "name":          player_name,
        "stars":         stars,
        "status":        status,
        "last_seen":     last_seen,
        "server":        server,
        "first_seen":    first_seen,
        "total_fame":    total_fame,
        "seasonal_fame": seasonal_fame,
        "account_fame":  account_fame,
        "exaltations":   exaltations,
        "skins":         skins,
        "shinies":       shinies,
        "total_chars":   total_chars,
        "maxed_chars":   maxed_chars,
        "best_stats":    best_stats,
    }

import time as time_module

def get_afk_members(guild_name: str, min_days_offline: int = 30) -> Optional[list]:
    """Returns members offline for at least min_days_offline, sorted longest first."""
    global _persistent_driver
    afk = []
    with _driver_lock:
        driver = _ensure_driver()
        try:
            driver.get(f"{REALMSCOPE_BASE}/guild/{guild_name}")
            _wait_for_cloudflare(driver)
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr[data-player]"))
            )
            soup = BeautifulSoup(driver.page_source, "html.parser")
            now    = int(time_module.time())
            cutoff = min_days_offline * 86400

            for table in soup.find_all("table"):
                rows = table.select("tbody tr[data-player]")
                if not rows:
                    continue
                for row in rows:
                    last_seen = int(row.get("data-lastseen", 0))
                    seconds_offline = now - last_seen
                    if seconds_offline < cutoff:
                        continue
                    tds = row.find_all("td")
                    if len(tds) < 5:
                        continue
                    fame = int(row.get("data-totalfame", 0))
                    rank = tds[3].get_text(strip=True)
                    name_link = tds[1].select_one("a.username-link")
                    name = name_link.get_text(strip=True) if name_link else row.get("data-player", "")
                    days_offline = seconds_offline // 86400
                    months = days_offline // 30
                    days   = days_offline % 30
                    time_str = f"{months}mo {days}d" if months > 0 else f"{days}d"
                    afk.append({
                        "name":     name,
                        "rank":     rank,
                        "fame":     fame,
                        "days":     days_offline,
                        "time_str": time_str,
                    })
                break

            afk.sort(key=lambda x: x["days"], reverse=True)

        except Exception as e:
            print(f"Error fetching AFK members: {e}")
            try:
                _persistent_driver.quit()
            except Exception:
                pass
            _persistent_driver = None
    return afk

def get_wiki_item(item_name: str) -> Optional[dict]:
    """
    Scrapes item data from RealmEye wiki.
    Handles weapons, abilities, armor, rings, artifacts, consumables.
    """
    slug = item_name.lower().strip().replace(" ", "-")
    url  = f"https://www.realmeye.com/wiki/{slug}"
    req  = urllib.request.Request(url, headers={"User-Agent": "Magic Browser"})
    try:
        page = urllib.request.urlopen(req, timeout=10)
        html = page.read().decode("utf-8")
    except Exception as e:
        print(f"Error fetching wiki page for {item_name}: {e}")
        return None

    soup     = BeautifulSoup(html, "html.parser")
    wiki_div = soup.find("div", id="d")
    if not wiki_div:
        return None

    name_tag = soup.find("h1")
    name     = name_tag.get_text(strip=True) if name_tag else item_name

    # ── Item image + shiny image ──────────────────────────────────────────────
    # First table in wiki_div: td[width=50] = item img, row 2 = shiny img
    item_img  = None
    shiny_img = None
    first_tbl = wiki_div.find("table")
    if first_tbl:
        rows = first_tbl.find_all("tr")
        for row_i, row in enumerate(rows[:3]):
            tds = row.find_all("td")
            if not tds:
                continue
            # Main item image — first td with width=50
            for td in tds:
                if td.get("width") == "50":
                    imgs = td.find_all("img")
                    for img in imgs:
                        alt = img.get("alt", "")
                        src = img.get("src", "")
                        if not src:
                            continue
                        full_src = f"https://www.realmeye.com{src}" if src.startswith("/") else src
                        if "(Shiny)" in alt:
                            shiny_img = full_src
                        elif item_img is None:
                            item_img = full_src

    # ── Stats table — second table ────────────────────────────────────────────
    # Parse ALL <th>/<td> pairs generically — works for any item type
    stats    = {}
    tables   = wiki_div.find_all("table")

    SKIP_TH = {"loot bag", "drops from", "obtained through", "blueprint",
               "reskin of", "reskin", "set piece"}

    for tbl in tables[1:]:  # skip first table (item image table)
        rows = tbl.find_all("tr")
        for row in rows:
            ths = row.find_all("th")
            tds = row.find_all("td")
            if not ths or not tds:
                continue

            label = ths[0].get_text(" ", strip=True).lower().rstrip(":")
            if any(s in label for s in SKIP_TH):
                continue

            # Tier — grab from th class (ut, st, at, t, etc.) + text
            if label == "tier":
                # The tier value is in a second <th> with a class
                if len(ths) >= 2:
                    tier_th    = ths[1]
                    tier_class = tier_th.get("class", [])
                    tier_text  = tier_th.get_text(strip=True)
                    # Remove dungeon-source image alt text
                    tier_img = tier_th.find("img")
                    source   = ""
                    if tier_img:
                        source    = tier_img.get("title", tier_img.get("alt", ""))
                        tier_text = tier_th.get_text(strip=True).replace(source, "").strip()
                    stats["tier"]        = tier_text or (tier_class[0].upper() if tier_class else "?")
                    stats["tier_source"] = source  # e.g. "The Tavern", "The Realm"
                continue

            # Generic: get text value from td, clean up
            val = tds[0].get_text(" ", strip=True)

            # Map known labels to clean keys
            key_map = {
                "shots":              "shots",
                "damage":             "damage",
                "total damage":       "total_damage",
                "projectile speed":   "speed",
                "lifetime":           "lifetime",
                "range":              "range",
                "amplitude":          "amplitude",
                "frequency":          "frequency",
                "rate of fire":       "rof",
                "on equip":           "on_equip",
                "effect(s)":          "effects",
                "mp cost":            "mp_cost",
                "xp bonus":           "xp_bonus",
                "feed power":         "feed_power",
                "soulbound":          "soulbound",
                "stack limit":        "stack_limit",
                "dust cost":          "dust_cost",
                "forging cost":       "forging_cost",
                "dismantling value":  "dismantling",
                "used dust":          "used_dust",
                "power level":        "power_level",
                "weight effect(s)":   "weight_effects",
                "minimum mod tier":   "min_mod_tier",
            }

            for search, clean_key in key_map.items():
                if search in label:
                    # For dust cost, grab the img title
                    if clean_key in ("used_dust", "dust_cost"):
                        dust_imgs = tds[0].find_all("img")
                        dust_types = [i.get("title", "") for i in dust_imgs if "Dust" in i.get("title","")]
                        val = ", ".join(dust_types) if dust_types else val
                    # For soulbound, just mark True/False
                    if clean_key == "soulbound":
                        val = True
                    stats[clean_key] = val
                    break

    # ── Loot bag, drops, blueprint, obtained ─────────────────────────────────
    loot_bag  = ""
    drops     = []
    obtained  = []
    blueprint = ""
    reskin_of = ""

    for tbl in tables:
        for row in tbl.find_all("tr"):
            ths = row.find_all("th")
            tds = row.find_all("td")
            if not ths or not tds:
                continue
            label = ths[0].get_text(strip=True).lower().rstrip(":")

            if "loot bag" in label:
                bag_img = tds[0].find("img")
                if bag_img:
                    loot_bag = bag_img.get("title", "").replace("Assigned to ", "")

            elif "drops from" in label:
                # Only take from the table that also has "Loot Bag" nearby
                # to avoid picking up blueprint drops
                parent_tbl = ths[0].find_parent("table")
                has_loot_bag = any(
                    "loot bag" in r.find("th").get_text(strip=True).lower()
                    for r in (parent_tbl.find_all("tr") if parent_tbl else [])
                    if r.find("th")
                )
                links = [a.get_text(strip=True) for a in tds[0].find_all("a")]
                if has_loot_bag:
                    drops = links
                # If this row is in a Blueprint table, skip

            elif "obtained through" in label:
                obtained = [a.get_text(strip=True) for a in tds[0].find_all("a")]

            elif "blueprint" in label and len(ths) == 1:
                bp_img = tds[0].find("img")
                if bp_img:
                    blueprint = bp_img.get("alt", "").replace(" Blueprint", "").strip()

            elif "reskin of" in label or (label == "reskin" and tds):
                reskin_of = tds[0].get_text(strip=True)

    # ── Shiny detection ───────────────────────────────────────────────────────
    # True if shiny image found in first table OR page links to /wiki/shiny-items
    has_shiny = (shiny_img is not None) or bool(soup.find("a", href="/wiki/shiny-items"))

    # ── Awakened enchantments ─────────────────────────────────────────────────
    awakened = []
    for tbl in tables:
        for row in tbl.find_all("tr"):
            th = row.find("th")
            td = row.find("td")
            if not th or not td:
                continue
            if "awakened" in th.get_text(strip=True).lower():
                awakened.append(td.get_text(" ", strip=True))

    return {
        "name":        name,
        "img_url":     item_img,
        "shiny_url":   shiny_img,
        "stats":       stats,
        "loot_bag":    loot_bag,
        "drops":       drops,
        "obtained":    obtained,
        "blueprint":   blueprint,
        "reskin_of":   reskin_of,
        "has_shiny":   has_shiny,
        "awakened":    awakened,
        "wiki_url":    url,
    }

    
def get_guild_online_status(guild_name: str) -> Optional[list]:
    """
    Returns all guild members with their online/offline status.
    Uses the guild page for names, then checks each player's status page.
    """
    global _persistent_driver
    members = []
    with _driver_lock:
        driver = _ensure_driver()
        try:
            driver.get(f"{REALMSCOPE_BASE}/guild/{guild_name}")
            _wait_for_cloudflare(driver)
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr[data-player]"))
            )
            soup = BeautifulSoup(driver.page_source, "html.parser")
            for table in soup.find_all("table"):
                rows = table.select("tbody tr[data-player]")
                if not rows:
                    continue
                for row in rows:
                    name_link = row.select_one("a.username-link")
                    name = name_link.get_text(strip=True) if name_link else row.get("data-player", "")
                    last_seen = int(row.get("data-lastseen", 0))
                    members.append({"name": name, "last_seen": last_seen})
                break
        except Exception as e:
            print(f"Error fetching guild for online status: {e}")
            try:
                _persistent_driver.quit()
            except Exception:
                pass
            _persistent_driver = None

    if not members:
        return None

    results = []
    for m in members:
        status = get_online_status(m["name"])
        results.append({"name": m["name"], "status": status or "Offline"})
    return results

def get_player_fame_history(player_name: str) -> Optional[dict]:
    """Scrapes the 24h and 7d fame gained from realmscope fame-history page."""
    soup = fetch_page(f"{REALMSCOPE_BASE}/fame-history/{player_name}")
    if not soup:
        return None

    result = {"daily": 0, "weekly": 0, "seasonal_daily": 0, "seasonal_weekly": 0}

    summaries = soup.select("div.fame-graph-summary")
    fame_summaries     = []
    seasonal_summaries = []

    # Fame history and seasonal fame history sections
    fame_panel     = soup.find("div", id="history-panel-fame")
    seasonal_panel = soup.find("div", id="history-panel-seasonal-fame")

    if fame_panel:
        for s in fame_panel.select("div.fame-graph-summary strong"):
            fame_summaries.append(s.get_text(strip=True).replace(",", ""))

    if seasonal_panel:
        for s in seasonal_panel.select("div.fame-graph-summary strong"):
            seasonal_summaries.append(s.get_text(strip=True).replace(",", ""))

    try:
        if len(fame_summaries) >= 1:
            result["daily"] = int(fame_summaries[0])
        if len(fame_summaries) >= 2:
            result["weekly"] = int(fame_summaries[1])
        if len(seasonal_summaries) >= 1:
            result["seasonal_daily"] = int(seasonal_summaries[0])
        if len(seasonal_summaries) >= 2:
            result["seasonal_weekly"] = int(seasonal_summaries[1])
    except (ValueError, IndexError):
        pass

    return result

def get_player_seasonal_fame_history(player_name: str, retries: int = 2) -> Optional[dict]:
    """Scrapes seasonal fame history with retries."""
    for attempt in range(retries + 1):
        try:
            soup = fetch_page(f"{REALMSCOPE_BASE}/fame-history/{player_name}")
            if not soup:
                if attempt < retries:
                    time_module.sleep(1)
                    continue
                return None

            seasonal_panel = soup.find("div", id="history-panel-seasonal-fame")
            if not seasonal_panel:
                return None

            graphs = seasonal_panel.select("div.fame-graph-container")

            def parse_summary(graph) -> int:
                strong = graph.select_one("div.fame-graph-summary strong")
                if strong:
                    try:
                        return int(strong.get_text(strip=True).replace(",", ""))
                    except ValueError:
                        pass
                return 0

            daily        = parse_summary(graphs[0]) if len(graphs) > 0 else 0
            weekly       = parse_summary(graphs[1]) if len(graphs) > 1 else 0
            current_total = 0
            if len(graphs) > 2:
                dots = graphs[2].select("circle.fame-dot")
                if dots:
                    try:
                        current_total = int(dots[-1].get("data-fame", 0))
                    except (ValueError, TypeError):
                        pass

            return {
                "name":          player_name,
                "daily":         daily,
                "weekly":        weekly,
                "current_total": current_total,
            }

        except Exception as e:
            print(f"Attempt {attempt+1} failed for {player_name}: {e}")
            if attempt < retries:
                time_module.sleep(1)

    return None

def get_guild_seasonal_fame(guild_members: list) -> list:
    """
    Fetches seasonal fame for all guild members.
    Retries aggressively. Returns all members — failed ones included with 0.
    """
    results    = {}
    remaining  = list(guild_members)
    max_passes = 4

    for pass_num in range(1, max_passes + 1):
        if not remaining:
            break

        print(f"Fame fetch pass {pass_num}: {len(remaining)} players remaining")

        # Use more workers on first pass, fewer on retries to reduce server load
        workers = 3 if pass_num == 1 else 2

        failed_this_pass = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_name = {
                executor.submit(get_player_seasonal_fame_history, name, 2): name
                for name in remaining
            }
            for future in concurrent.futures.as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    data = future.result(timeout=20)
                    if data:
                        results[name.lower()] = data
                    else:
                        failed_this_pass.append(name)
                except Exception as e:
                    print(f"Pass {pass_num} failed for {name}: {e}")
                    failed_this_pass.append(name)

        remaining = failed_this_pass

        if remaining and pass_num < max_passes:
            wait = pass_num * 3  # increasing backoff: 3s, 6s, 9s
            print(f"Pass {pass_num} done. {len(remaining)} failed, retrying in {wait}s...")
            time_module.sleep(wait)

    # Any still remaining after all passes — mark as failed
    final_results = list(results.values())
    for name in remaining:
        print(f"Giving up on {name} after {max_passes} passes")
        final_results.append({
            "name":          name,
            "daily":         0,
            "weekly":        0,
            "current_total": 0,
            "failed":        True
        })

    return final_results

def get_guild_member_history(guild_name: str) -> dict:
    """
    Scrapes the member history page to get the most recent join date per member.
    Returns dict: { 'playername_lower': unix_timestamp_of_join }
    Only returns players currently in the guild (data-currentguild matches).
    """
    global _persistent_driver
    join_dates  = {}
    guild_lower = guild_name.lower()
    with _driver_lock:
        driver = _ensure_driver()
        try:
            driver.get(f"{REALMSCOPE_BASE}/member-history-of-guild/{guild_name}")
            _wait_for_cloudflare(driver)
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr[data-player]"))
            )
            soup = BeautifulSoup(driver.page_source, "html.parser")
            for row in soup.select("tbody tr[data-player]"):
                player    = row.get("data-player", "").lower()
                event     = row.get("data-event", "")
                date      = row.get("data-date", "0")
                cur_guild = row.get("data-currentguild", "").lower()
                if not player or event != "joined" or cur_guild != guild_lower:
                    continue
                try:
                    ts = int(date)
                except ValueError:
                    continue
                if player not in join_dates or ts > join_dates[player]:
                    join_dates[player] = ts
        except Exception as e:
            print(f"Error fetching member history: {e}")
            try:
                _persistent_driver.quit()
            except Exception:
                pass
            _persistent_driver = None
    return join_dates
