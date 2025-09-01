# scrape_vald.py
import os
import re
import time
import subprocess
import sys
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from playwright.sync_api import (
    sync_playwright,
    expect,
    TimeoutError as PlaywrightTimeoutError,
    Page,
    Locator,
)

# ===================== ENV / CONFIG =====================
load_dotenv()  # .env in CWD
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
if not EMAIL or not PASSWORD:
    raise RuntimeError("EMAIL/PASSWORD must be set in .env")

BASE_URL = "https://hub.valdperformance.com/"
OUTPUT_DIR = Path(r"D:/Vald Data")
AUTH_FILE = "auth_state.json"

# ===================== TIMING TUNABLES =====================
SHORT_PAUSE = 350  # ms settle pauses inside modals/tiles
MENU_AFTER_SELECT = 900
MODAL_MOUNT_WAIT = 800  # ms after modal reported visible

# More patient accordion discovery & settle timings
ACCORDION_DISCOVERY_TIMEOUT = 30000  # wait up to 30s for accordions to appear
ACCORDION_STABLE_FOR_MS = 1500  # require count to be stable this long
ACCORDION_CHECK_INTERVAL = 250
ACCORDION_SECTION_SETTLE_MS = 600  # settle each section before screenshot

# ===================== WINDOW / VIEWPORT =====================
WINDOW_W = 1920
WINDOW_H = 1080
DEVICE_SCALE = 2  # 1=normal, 2=crisper element screenshots

# Run headless to avoid interference. Set to False if you want to watch.
HEADLESS = True

# Extra Chrome args to avoid accidental zoom/gestures & nav gestures
CHROME_ARGS = [
    f"--window-size={WINDOW_W},{WINDOW_H}",
    "--disable-pinch",
    "--overscroll-history-navigation=0",
]


# ===================== UTILS =====================
def log(tag: str, msg: str) -> None:
    print(f"{tag:<7}| {msg}")


def sanitize_filename(name: str) -> str:
    name = name.replace("\n", " ").replace("\r", " ")
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def move_mouse_off_view(page: Page) -> None:
    """Nudge the mouse to the top-left so hover tooltips disappear before screenshots."""
    try:
        page.mouse.move(0, 0)
        page.wait_for_timeout(150)
    except Exception:
        pass


def reset_zoom(page: Page) -> None:
    """Force Chromium zoom back to 100% (guards against pinch/ctrl+wheel)."""
    try:
        page.keyboard.down("Control")
        page.keyboard.press("0")
        page.keyboard.up("Control")
        page.wait_for_timeout(120)
    except Exception:
        pass


def ensure_profiles_page(page: Page) -> None:
    """Make sure we're on the Profiles list and the page is idle, with zoom reset."""
    if "/app/profiles" not in page.url:
        try:
            page.locator('a[href="/app/profiles"]').click()
        except Exception:
            page.goto(BASE_URL)
            page.locator('a[href="/app/profiles"]').click()
    expect(page).to_have_url(re.compile(r".*/app/profiles"))
    page.wait_for_load_state("networkidle", timeout=30000)
    reset_zoom(page)


def perform_login(page: Page) -> bool:
    log("LOGIN", "Navigating...")
    page.goto(BASE_URL)

    try:
        cookie_button = page.locator("#rcc-confirm-button")
        if cookie_button.is_visible():
            cookie_button.click()
            log("LOGIN", "Cookie banner accepted.")
    except PlaywrightTimeoutError:
        pass

    try:
        email_input = page.locator('input[name="username"]')
        expect(email_input).to_be_visible(timeout=15000)
        email_input.fill(EMAIL)
        page.locator('button:has-text("Continue")').click()
        log("LOGIN", "Email submitted.")
    except Exception as e:
        log("LOGIN", f"Email step error: {e}")
        return False

    try:
        password_input = page.locator('input[name="password"]')
        expect(password_input).to_be_visible(timeout=15000)
        password_input.fill(PASSWORD)
        page.locator('button:has-text("Continue")').click()
        log("LOGIN", "Password submitted.")
    except Exception as e:
        log("LOGIN", f"Password step error: {e}")
        return False

    try:
        expect(page.locator('a[href="/app/profiles"]')).to_be_visible(timeout=30000)
        log("LOGIN", "Success.")
        return True
    except PlaywrightTimeoutError:
        log("LOGIN", "Failed (profiles link not visible).")
        return False


# ===================== GENERIC TILE HELPERS =====================
def tiles_by_testid(page: Page, testid: str) -> Locator:
    return page.locator(f'article:has([data-testid="{testid}"])')


def tile_by_heading_fallback(page: Page, title_text: str) -> Locator:
    return (
        page.locator("article")
        .filter(has=page.locator(".truncate.font-medium", has_text=title_text))
        .first
    )


def get_tile_heading_text(tile: Locator) -> str:
    heading = tile.locator(".truncate.font-medium").first
    return heading.inner_text().strip() if heading.count() else ""


# ===================== CMJ: ROBUST FIND & OPEN =====================
def _scan_for_visibility(
    page: Page, cand: Locator, steps: int = 7, pause_ms: int = 280
) -> Optional[Locator]:
    """
    Scroll-scan the page to trigger lazy tiles and return the first visible match if found.
    """
    try:
        page.evaluate("window.scrollTo(0,0)")
    except Exception:
        pass
    page.wait_for_timeout(120)
    for _ in range(max(1, steps)):
        try:
            if cand.count() > 0 and cand.first.is_visible():
                return cand.first
        except Exception:
            pass
        try:
            page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight*0.90))")
        except Exception:
            pass
        page.wait_for_timeout(pause_ms)
    # final check after returning to top
    try:
        page.evaluate("window.scrollTo(0,0)")
    except Exception:
        pass
    page.wait_for_timeout(120)
    try:
        if cand.count() > 0 and cand.first.is_visible():
            return cand.first
    except Exception:
        pass
    return None


def find_countermovement_jump_tile(page: Page) -> Optional[Locator]:
    """
    Heavily guarded discovery for the ForceDecks 'Countermovement Jump' tile.
    Tries multiple selector strategies + scroll scan.
    Returns a Locator (visible article) or None if not found.
    """
    reset_zoom(page)
    pattern = re.compile(r"(counter\s*movement\s*jump|^cmj$|cmj\b)", re.I)

    # PASS A: Original strict attribute selector
    passes = [
        lambda: page.locator(
            'article:has([data-testid="forcedecks-tile"][data-test-name="Countermovement Jump"])'
        ),
        # PASS B: forcedecks-tile + heading regex
        lambda: page.locator('article:has([data-testid="forcedecks-tile"])').filter(
            has=page.locator(".truncate.font-medium", has_text=pattern)
        ),
        # PASS C: any forcedecks* + heading regex
        lambda: page.locator('article:has([data-testid*="forcedecks"])').filter(
            has=page.locator(".truncate.font-medium", has_text=pattern)
        ),
        # PASS D: any article heading match
        lambda: page.locator("article").filter(
            has=page.locator(".truncate.font-medium", has_text=pattern)
        ),
    ]

    for pi, make_locator in enumerate(passes, start=1):
        try:
            cand = make_locator()
        except Exception:
            cand = None
        if not cand:
            continue
        vis = _scan_for_visibility(page, cand)
        if vis:
            log(
                "CMJ",
                f"Found tile via PASS {pi}. Heading='{get_tile_heading_text(vis)}'",
            )
            return vis

    log("CMJ", "Tile not found by any strategy (may be absent for this athlete).")
    return None


def _real_modal_locator(page: Page) -> Locator:
    close_btn = page.locator('[data-testid="close-button"]').first
    if close_btn.count() > 0:
        return close_btn.locator(
            "xpath=ancestor::div[contains(@class,'react-responsive-modal') or contains(@class,'fd-chart-modal') or @id='fd-chart-modal']"
        ).first
    return page.locator(
        "#fd-chart-modal, .fd-chart-modal, .react-responsive-modal-modal"
    ).first


def open_modal_from_tile(
    page: Page, tile: Locator, inner_selectors: List[str]
) -> Locator:
    """
    Open a modal by clicking a tile using several strategies. Returns the modal locator.
    """
    expect(tile).to_be_visible(timeout=20000)
    tile.scroll_into_view_if_needed()

    def _try_open(click_fn_desc: str, click_fn):
        try:
            click_fn()
        except Exception:
            return False
        modal = _real_modal_locator(page)
        try:
            expect(modal).to_be_visible(timeout=3000)
            page.wait_for_timeout(MODAL_MOUNT_WAIT)
            reset_zoom(page)
            log("MODAL", f"Opened via {click_fn_desc}.")
            return modal
        except Exception:
            return False

    # 1) click tile center / top-left
    for desc, fn in [
        ("article center", lambda: tile.click()),
        ("article top-left", lambda: tile.click(position={"x": 18, "y": 18})),
    ]:
        modal = _try_open(desc, fn)
        if modal:
            return modal

    # 2) click inner candidates
    for sel in inner_selectors:
        inner = tile.locator(sel).first
        if inner.count() == 0:
            continue
        for desc, fn in [
            (f'inner "{sel}" center', lambda i=inner: i.click()),
            (
                f'inner "{sel}" top-left',
                lambda i=inner: i.click(position={"x": 10, "y": 10}),
            ),
        ]:
            modal = _try_open(desc, fn)
            if modal:
                return modal

    # 3) click heading
    heading = tile.locator(".truncate.font-medium").first
    if heading.count() > 0:
        modal = _try_open("heading click", lambda: heading.click())
        if modal:
            return modal

    # 4) keyboard Enter
    try:
        tile.focus()
        page.keyboard.press("Enter")
        modal = _real_modal_locator(page)
        expect(modal).to_be_visible(timeout=3000)
        page.wait_for_timeout(MODAL_MOUNT_WAIT)
        reset_zoom(page)
        log("MODAL", "Opened via Enter.")
        return modal
    except Exception:
        pass

    raise RuntimeError("Could not open modal from tile (after multiple strategies).")


def open_modal_countermovement_jump(page: Page) -> Locator:
    """
    Robust opener for CMJ. Finds the tile with multiple strategies, then opens the modal
    with multiple click fallbacks.
    """
    tile = find_countermovement_jump_tile(page)
    if tile is None:
        raise RuntimeError("CMJ tile not present or not discoverable.")

    # Inner clickable selectors to try within the tile
    inner_candidates = [
        '[data-testid="forcedecks-tile"]',
        '[data-testid*="forcedecks"]',
        "canvas",
        "svg",
    ]
    modal = open_modal_from_tile(page, tile, inner_candidates)
    log("MODAL", "'Countermovement Jump' visible.")
    return modal


# ===================== OTHER TILES (SMARTSPEED / HUMANTRAK) =====================
def find_smartspeed_tile_by_title(page: Page, desired_title: str) -> Locator:
    tiles = tiles_by_testid(page, "smartspeed-tile")
    count = tiles.count()
    if count == 0:
        raise RuntimeError("No smartspeed tiles found.")

    want = re.sub(r"\s+", " ", desired_title).strip().lower()
    for i in range(count):
        t = tiles.nth(i)
        cur = re.sub(r"\s+", " ", get_tile_heading_text(t)).strip().lower()
        if cur == want:
            return t

    # Heuristics
    for i in range(count):
        t = tiles.nth(i)
        txt = get_tile_heading_text(t).lower()
        if (
            "sprint" in txt
            and "5-0-5" not in txt
            and "505" not in txt
            and ("20" in txt or "yd" in txt)
        ):
            return t
    for i in range(count):
        t = tiles.nth(i)
        txt = get_tile_heading_text(t).lower()
        if "5-0-5" in txt or "505" in txt:
            return t
    return tiles.first


def open_modal_by_testid(
    page: Page, testid: str, title_hint: Optional[str] = None
) -> Locator:
    if testid == "smartspeed-tile" and title_hint:
        tile = find_smartspeed_tile_by_title(page, title_hint)
    else:
        tile = tiles_by_testid(page, testid).first

    # Open with same robust click routine
    return open_modal_from_tile(
        page,
        tile,
        inner_selectors=[
            f'[data-testid="{testid}"]',
            f'[data-testid*="{testid.split("-")[0]}"]',
        ],
    )


def tile_humantrak_by_title(page: Page, title_text: str) -> Locator:
    return (
        page.locator('article:has([data-testid="humantrak-tile"])')
        .filter(has=page.locator(".truncate.font-medium", has_text=title_text))
        .first
    )


def capture_humantrak_card(
    page: Page,
    title: str,
    labels_to_capture: List[str],
    save_dir: Path,
    counters: defaultdict,
    include_base: bool = False,  # False -> exactly one shot per label
) -> int:
    """
    Take exactly one screenshot per requested metric label (and optionally one base shot).
    Uses robust selection + pixel fingerprinting + bytes hashing + bounce strategy
    to avoid duplicates when the list reorders itself or re-renders slowly.
    """
    tile = tile_humantrak_by_title(page, title)
    if tile.count() == 0 or not tile.is_visible():
        tile = tile_by_heading_fallback(page, title)
    expect(tile).to_be_visible(timeout=15000)

    def _get_chart_locator(t: Locator) -> Locator:
        canvas = t.locator("canvas").first
        if canvas.count() > 0:
            return canvas
        svg = t.locator(".recharts-wrapper svg, svg").first
        if svg.count() > 0:
            return svg
        wrapper = t.locator(".recharts-wrapper").first
        if wrapper.count() > 0:
            return wrapper
        return t

    def _fingerprint(l: Locator) -> str:
        data = l.screenshot()
        return hashlib.sha256(data).hexdigest()

    def _open_metric_menu(t: Locator, attempts: int = 4) -> Locator:
        page = t.page
        btn = t.locator('[data-testid="metric-dropdown-button"]').first
        expect(btn).to_be_visible(timeout=12000)
        btn.scroll_into_view_if_needed()

        for _ in range(attempts):
            try:
                btn.click()
            except Exception:
                pass
            menu = t.locator('[data-testid="metric-dropdown-items"]').first
            try:
                expect(menu).to_be_visible(timeout=2500)
                return menu
            except Exception:
                page.wait_for_timeout(250)

        btn.click(position={"x": 10, "y": 10})
        menu = t.locator('[data-testid="metric-dropdown-items"]').first
        expect(menu).to_be_visible(timeout=2500)
        return menu

    def select_metric_and_wait(label: str, timeout_ms: int = 10000) -> None:
        token = (
            "Ankle Dorsiflexion"
            if "Ankle Dorsiflexion" in label
            else (
                "Hip Adduction"
                if "Hip Adduction" in label
                else "Peak Knee Flexion" if "Peak Knee Flexion" in label else label[:24]
            )
        )

        chart_before = _get_chart_locator(tile)
        fp_before = _fingerprint(chart_before)

        menu = _open_metric_menu(tile)
        option = menu.get_by_role(
            "menuitem", name=re.compile(rf"^{re.escape(label)}\s*$")
        )
        expect(option.first).to_be_visible(timeout=8000)
        option.first.scroll_into_view_if_needed()
        option.first.click(force=True)

        try:
            expect(menu).not_to_be_visible(timeout=3000)
        except Exception:
            pass

        btn = tile.locator('[data-testid="metric-dropdown-button"]').first
        span = btn.locator("span.truncate").first
        try:
            expect(span).to_contain_text(
                re.compile(re.escape(token), re.I), timeout=timeout_ms
            )
        except Exception:
            page.wait_for_timeout(800)
            expect(span).to_contain_text(
                re.compile(re.escape(token), re.I), timeout=3000
            )

        deadline = time.time() + (timeout_ms / 1000.0)
        while time.time() < deadline:
            chart_after = _get_chart_locator(tile)
            try:
                fp_after = _fingerprint(chart_after)
                if fp_after != fp_before:
                    break
            except Exception:
                pass
            page.wait_for_timeout(150)
        page.wait_for_timeout(MENU_AFTER_SELECT)

    def screenshot_tile_unique(
        t: Locator, prefix: str, seen_hashes: set, max_dupe_retries: int = 2
    ) -> bool:
        for attempt in range(max_dupe_retries + 1):
            t.scroll_into_view_if_needed()
            time.sleep(0.15)
            data = t.screenshot()
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen_hashes:
                log(
                    "SHOT",
                    f"Duplicate detected for {prefix} (attempt {attempt+1}/{max_dupe_retries}); retrying...",
                )
                try:
                    t.scroll_into_view_if_needed()
                    page.wait_for_timeout(250)
                    move_mouse_off_view(page)
                except Exception:
                    pass
                continue
            counters[prefix] += 1
            idx = counters[prefix]
            path = save_dir / f"{prefix}_{idx:03d}.png"
            path.write_bytes(data)
            log("SHOT", path.name)
            seen_hashes.add(digest)
            return True
        return False

    taken = 0
    seen_hashes: set = set()
    prefix = title.replace(" ", "_")

    if include_base:
        log("CARD", f"{title}: base screenshot")
        move_mouse_off_view(page)
        if screenshot_tile_unique(tile, prefix, seen_hashes):
            taken += 1

    for label in labels_to_capture:
        success = False
        for attempt in range(1, 4):
            try:
                log("CARD", f"{title}: selecting '{label}' (attempt {attempt}/3)")
                select_metric_and_wait(label)
                move_mouse_off_view(page)
                if screenshot_tile_unique(tile, prefix, seen_hashes):
                    success = True
                    taken += 1
                    break
                else:
                    # bounce strategy
                    alts = [x for x in labels_to_capture if x != label]
                    if alts:
                        try:
                            select_metric_and_wait(alts[0])
                            page.wait_for_timeout(400)
                            select_metric_and_wait(label)
                            move_mouse_off_view(page)
                        except Exception:
                            pass
            except Exception as e:
                log("CARD", f"(retry) '{title}' -> '{label}' failed: {e}")
                page.wait_for_timeout(600)

        if not success:
            log(
                "CARD",
                f"(skip) '{title}' -> '{label}' produced duplicate/failed after retries.",
            )

    log("CARD", f"{title}: done ({taken} shots)")
    return taken


def capture_humantrak_card_any(
    page: Page,
    title_candidates: List[str],
    labels_to_capture: List[str],
    save_dir: Path,
    counters: defaultdict,
    include_base: bool = False,
) -> int:
    """
    Try multiple title variants (e.g., 'Lunge' vs 'Lunges') and capture on the first that exists.
    """
    last_err = None
    for title in title_candidates:
        try:
            return capture_humantrak_card(
                page, title, labels_to_capture, save_dir, counters, include_base
            )
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return 0


# ===================== SCREENSHOTS & ACCORDIONS (shared) =====================
def screenshot_modal_accordions(
    page: Page, modal: Locator, save_dir: Path, prefix: str, counters: defaultdict
) -> int:
    """Screenshot each accordion section; if none, take one full-modal shot."""
    # Preload by gentle scroll
    try:
        modal.evaluate("e => { e.scrollTop = 0; }")
        for y in (0.2, 0.4, 0.6, 0.8, 1.0):
            modal.evaluate("(e, y) => e.scrollTo(0, e.scrollHeight * y)", y)
            modal.page.wait_for_timeout(200)
        modal.evaluate("e => { e.scrollTop = 0; }")
        modal.page.wait_for_timeout(200)
    except Exception:
        pass

    # Wait for stable accordion count
    def _wait_for_accordion_count_to_settle(
        md: Locator,
        max_wait_ms: int = ACCORDION_DISCOVERY_TIMEOUT,
        stable_for_ms: int = ACCORDION_STABLE_FOR_MS,
        interval_ms: int = ACCORDION_CHECK_INTERVAL,
    ) -> int:
        elapsed = 0
        stable = 0
        prev = -1
        while elapsed < max_wait_ms:
            cnt = md.locator("div.accordion").count()
            if cnt == prev and cnt > 0:
                stable += interval_ms
                if stable >= stable_for_ms:
                    return cnt
            else:
                prev = cnt
                stable = 0
            md.page.wait_for_timeout(interval_ms)
            elapsed += interval_ms
        return md.locator("div.accordion").count()

    cnt = _wait_for_accordion_count_to_settle(modal)
    if cnt == 0:
        log("MODAL", "No accordions detected; taking single modal shot as fallback.")
        expect(modal).to_be_visible(timeout=15000)
        counters[prefix] += 1
        path = save_dir / f"{prefix}_{counters[prefix]:03d}.png"
        path.write_bytes(modal.screenshot())
        log("SHOT", path.name)
        return 1

    accordions = modal.locator("div.accordion")
    total = cnt
    log("MODAL", f"{prefix}: found {total} accordion sections (stable).")

    try:
        page.mouse.move(5, 5)
    except Exception:
        pass

    took = 0
    for i in range(total):
        section = accordions.nth(i)
        try:
            body = section.locator(
                ".accordion-body, [data-testid='multiseries-chart'], svg, canvas, .recharts-wrapper"
            ).first
            try:
                expect(body).to_be_visible(timeout=4000)
            except Exception:
                pass

            section.scroll_into_view_if_needed()
            page.wait_for_timeout(ACCORDION_SECTION_SETTLE_MS)

            counters[prefix] += 1
            path = save_dir / f"{prefix}_{counters[prefix]:03d}.png"
            path.write_bytes(section.screenshot())
            log("SHOT", f"{path.name} (accordion {i+1}/{total})")
            took += 1
        except Exception as e:
            log("SHOT", f"Skip accordion {i+1}: {e}")

    return took


def close_modal(page: Page, modal: Locator) -> None:
    log("MODAL", "Closing...")
    btn = modal.locator(
        '[data-testid="close-button"], button[aria-label="Close"]'
    ).first
    if btn.count() > 0 and btn.is_visible():
        btn.click()
    else:
        page.mouse.click(10, 10)
    try:
        expect(modal).not_to_be_visible(timeout=10000)
        log("MODAL", "Closed.")
    except Exception:
        log("MODAL", "Close check timed-out; continuing.")


# ===================== PER-ATHLETE FLOW =====================
def take_screens_for_athlete(page: Page, out_dir: Path, athlete_name: str) -> None:
    reset_zoom(page)
    log("FLOW", f"Capturing for athlete: {athlete_name}")
    save_dir = Path(out_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    counters: defaultdict = defaultdict(int)

    # Try to pre-validate CMJ presence (non-fatal)
    try:
        cmj_tile = find_countermovement_jump_tile(page)
        if cmj_tile:
            log("FLOW", "CMJ tile detected on overview.")
        else:
            log(
                "FLOW", "CMJ tile not detected (may be absent); will still try to open."
            )
    except Exception as e:
        log("FLOW", f"CMJ pre-check failed: {e}")
    page.wait_for_timeout(300)

    # ---------- Modal tiles (accordion-based) ----------
    for label, opener in [
        ("Countermovement_Jump", lambda: open_modal_countermovement_jump(page)),
        ("Nordic", lambda: open_modal_by_testid(page, "nordbord-tile")),
        (
            "20yd_Sprint",
            lambda: open_modal_by_testid(page, "smartspeed-tile", "20yd Sprint"),
        ),
        (
            "5-0-5_Drill",
            lambda: open_modal_by_testid(page, "smartspeed-tile", "5-0-5 Drill"),
        ),
    ]:
        try:
            log("FLOW", f"Modal tile: {label.replace('_',' ')}")
            modal = opener()
            count = screenshot_modal_accordions(
                page, modal, save_dir, prefix=label, counters=counters
            )
            close_modal(page, modal)
            log("FLOW", f"✓ {label.replace('_',' ')} done ({count} shots)")
        except Exception as e:
            log("FLOW", f"(warn) {label.replace('_',' ')} failed: {e}")

    # ---------- HumanTrak tiles (dropdowns) ----------
    ht_labels = [
        "Avg Peak Knee Flexion - Left & Right",
        "Avg Hip Adduction at Peak Knee Flexion - Left & Right",
        "Avg Ankle Dorsiflexion at Peak Knee Flexion - Left & Right",
    ]
    try:
        capture_humantrak_card(
            page, "Overhead Squat", ht_labels, save_dir, counters, include_base=False
        )
    except Exception as e:
        log("FLOW", f"(warn) Overhead Squat failed: {e}")

    # Lunge title can be "Lunge" or "Lunges" depending on UI version
    try:
        capture_humantrak_card_any(
            page, ["Lunge", "Lunges"], ht_labels, save_dir, counters, include_base=False
        )
    except Exception as e:
        log("FLOW", f"(warn) Lunge/Lunges failed: {e}")

    total = sum(counters.values())
    log("FLOW", f"Athlete '{athlete_name}' complete. Total images: {total}")


# ===================== TEAM / SEARCH HELPERS =====================
def open_groups_dropdown(page: Page) -> None:
    ensure_profiles_page(page)
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(100)
    control = page.locator(".react-select__control").first
    expect(control).to_be_visible(timeout=15000)
    attempts = 0
    while attempts < 4:
        try:
            control.click()
        except Exception:
            pass
        try:
            expect(page.locator(".react-select__menu")).to_be_visible(timeout=3000)
            return
        except Exception:
            attempts += 1
            page.wait_for_timeout(300)
    control.click(position={"x": 10, "y": 10})
    expect(page.locator(".react-select__menu")).to_be_visible(timeout=3000)


def clear_all_selected_groups(page: Page) -> None:
    control = page.locator(".react-select__control").first
    try:
        while True:
            remove_btns = control.locator(".react-select__multi-value__remove")
            if remove_btns.count() == 0:
                break
            remove_btns.first.click()
            page.wait_for_timeout(120)
    except Exception:
        pass


def list_all_group_options(page: Page) -> List[str]:
    options = page.locator(".react-select__menu .react-select__option")
    count = options.count()
    texts = []
    for i in range(count):
        try:
            txt = options.nth(i).inner_text().strip()
            if txt:
                texts.append(txt)
        except Exception:
            pass
    return texts


def select_group_option_exact(page: Page, label: str) -> None:
    options = page.locator(".react-select__menu .react-select__option")
    target = options.filter(has_text=re.compile(rf"^{re.escape(label)}$"))
    if target.count() == 0:
        count = options.count()
        for i in range(count):
            o = options.nth(i)
            try:
                if o.inner_text().strip() == label:
                    o.scroll_into_view_if_needed()
                    o.click()
                    return
            except Exception:
                pass
        raise RuntimeError(f"Option not found: {label}")
    target.first.scroll_into_view_if_needed()
    target.first.click()


def prompt_team_mode() -> Tuple[str, List[str]]:
    """
    Ask user which selection mode to use.
    Returns one of:
      ("prefix", [prefix])
      ("list", [names...])
      ("single", [search_text])
    """
    print("\n=== Team/Profile selection ===")
    print(
        "1) Start-text mode (e.g., 'KC Fusion' -> process ALL teams that start with it)"
    )
    print(
        "2) Explicit team list (paste comma-separated OR path to a .txt with one per line)"
    )
    print("3) Single profile via search (type full/partial athlete name)")
    mode = input("Pick 1, 2 or 3 (default 1): ").strip() or "1"
    if mode not in ("1", "2", "3"):
        mode = "1"

    if mode == "1":
        prefix = (
            input("Enter starting text (default 'KC Fusion'): ").strip() or "KC Fusion"
        )
        return "prefix", [prefix]
    elif mode == "2":
        raw = input("Paste comma-separated names OR a path to .txt: ").strip()
        names: List[str] = []
        if raw.lower().endswith(".txt") and Path(raw).exists():
            for line in (
                Path(raw).read_text(encoding="utf-8", errors="ignore").splitlines()
            ):
                line = line.strip()
                if line:
                    names.append(line)
        else:
            for part in raw.split(","):
                nm = part.strip()
                if nm:
                    names.append(nm)
        return "list", names
    else:  # "3"
        query = input("Enter athlete name (full/partial) to search: ").strip()
        if not query:
            raise RuntimeError("Search text cannot be empty for single-profile mode.")
        return "single", [query]


def resolve_teams_by_prefix(page: Page, prefix: str) -> List[str]:
    open_groups_dropdown(page)
    texts = list_all_group_options(page)
    matched = [t for t in texts if t.startswith(prefix)]
    if not matched:
        raise RuntimeError(f"No team options start with: {prefix}")
    return matched


def set_filter_to_single_team(page: Page, team_name: str) -> None:
    log("FILTER", f"Setting filter to single team: {team_name}")
    clear_all_selected_groups(page)
    open_groups_dropdown(page)
    select_group_option_exact(page, team_name)
    page.locator("body").click(position={"x": 5, "y": 5})
    page.wait_for_load_state("networkidle")
    reset_zoom(page)


def clear_selected_team_via_cross(page: Page) -> None:
    ensure_profiles_page(page)
    control = page.locator(".react-select__control").first
    if control.count() == 0:
        return
    try:
        control.hover()
    except Exception:
        pass
    try:
        control.click()
    except Exception:
        pass
    clear_btn = control.locator(".react-select__clear-indicator").first
    if clear_btn.count() == 0:
        return
    try:
        clear_btn.click(force=True)
    except Exception:
        try:
            clear_btn.click()
        except Exception:
            pass
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        page.wait_for_timeout(400)
    reset_zoom(page)


# ===================== SEARCH (SINGLE PROFILE) =====================
def _search_input(page: Page) -> Locator:
    loc = page.locator(".search-input.search-input-profiles input").first
    if loc.count() == 0:
        loc = page.locator('input[placeholder="Search"]').first
    return loc


def apply_search_query(page: Page, query: str) -> None:
    ensure_profiles_page(page)
    box = _search_input(page)
    expect(box).to_be_visible(timeout=10000)
    box.click()
    try:
        box.fill("")
    except Exception:
        box.press("Control+a")
        box.press("Delete")
    box.type(query, delay=30)
    page.wait_for_timeout(300)
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    reset_zoom(page)


def clear_search_query(page: Page) -> None:
    try:
        box = _search_input(page)
        if box.count() > 0 and box.is_visible():
            box.click()
            try:
                box.fill("")
            except Exception:
                box.press("Control+a")
                box.press("Delete")
            page.wait_for_timeout(200)
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
    except Exception:
        pass


def _is_probable_team_text(text: str, profile_name: str) -> bool:
    t = text.strip()
    if not t or t.lower() == profile_name.lower():
        return False
    if "@" in t:
        return False
    letters = sum(ch.isalpha() for ch in t)
    digits = sum(ch.isdigit() for ch in t)
    if letters < 4 or digits > letters:
        return False
    if any(sym in t for sym in ("/", ":", "-", "AM", "PM")):
        if letters < 8:
            return False
    return True


def infer_team_from_row(row: Locator, profile_name: str) -> Optional[str]:
    try:
        tds = row.locator("td")
        count = tds.count()
        candidates = []
        for i in range(count):
            try:
                txt = tds.nth(i).inner_text().strip()
            except Exception:
                continue
            if _is_probable_team_text(txt, profile_name):
                candidates.append(txt)
        if candidates:
            return max(candidates, key=len)
    except Exception:
        pass
    return None


def collect_table_rows(page: Page) -> List[Locator]:
    rows = page.locator("tbody tr")
    n = rows.count()
    return [rows.nth(i) for i in range(n)]


def scrape_single_profile(page: Page, search_text: str) -> None:
    """
    Single-profile mode:
      - Type into Profiles search box
      - Pick exact-match row if possible, else first containing match, else first row
      - Open overview, capture, and ALWAYS save under:
          D:/Vald Data/Single Profile/<Athlete Name>/
    """
    ensure_profiles_page(page)
    log("SINGLE", f"Searching for: {search_text}")
    apply_search_query(page, search_text)

    rows = collect_table_rows(page)
    if not rows:
        log("SINGLE", "No rows found for the search.")
        return

    chosen = None
    exact_lower = search_text.strip().lower()
    fallback_contains = None

    for r in rows:
        try:
            name = r.locator("td").nth(1).inner_text().strip()
        except Exception:
            continue
        if name.lower() == exact_lower:
            chosen = r
            break
        if not fallback_contains and exact_lower in name.lower():
            fallback_contains = r

    if chosen is None:
        chosen = fallback_contains or rows[0]

    try:
        profile_name = chosen.locator("td").nth(1).inner_text().strip()
    except Exception:
        profile_name = search_text.strip()

    # ***** IMPORTANT CHANGE: Always save under "Single Profile" *****
    team_dir_name = "Single Profile"
    team_dir = OUTPUT_DIR / team_dir_name
    team_dir.mkdir(parents=True, exist_ok=True)

    athlete_safe = sanitize_filename(profile_name)
    out_dir = team_dir / athlete_safe
    out_dir.mkdir(parents=True, exist_ok=True)

    log("SINGLE", f"Selected athlete: {profile_name}")
    log("SINGLE", f"Saving under: {team_dir_name}/{athlete_safe}")

    # Open overview & capture
    log("NAV", "Opening athlete overview...")
    try:
        chosen.locator('[aria-label="table-cell-initials"]').click()
    except Exception:
        # if initials cell not clickable, try clicking the name cell, then the whole row
        try:
            chosen.locator("td").nth(1).click()
        except Exception:
            chosen.click()

    expect(page).to_have_url(re.compile(r".*/overview"), timeout=30000)
    page.wait_for_timeout(400)

    try:
        take_screens_for_athlete(page, out_dir, profile_name)
    except Exception as e:
        log("ERROR", f"While capturing '{athlete_safe}': {e}")

    # back to list & clear search box (tidy state)
    log("NAV", "Back to profiles list...")
    page.go_back()
    ensure_profiles_page(page)
    clear_search_query(page)
    log("SINGLE", "✅ Single profile capture complete.")


# ===================== CLEANUP RUNNER =====================
def run_cleanup():
    script_path = Path(__file__).with_name("cleanup_vald_images.py")
    if not script_path.exists():
        log("CLEAN", "cleanup_vald_images.py not found; skipping.")
        return
    try:
        log("CLEAN", f"Running {script_path.name}...")
        subprocess.run(
            [sys.executable, str(script_path)], cwd=str(script_path.parent), check=False
        )
        log("CLEAN", "Cleanup finished.")
    except Exception as e:
        log("CLEAN", f"Cleanup failed: {e}")


# ===================== MAIN =====================
def main():
    browser = None
    context = None
    page: Optional[Page] = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=HEADLESS,
                slow_mo=55 if not HEADLESS else 0,
                args=CHROME_ARGS,
            )

            # ----- session -----
            if os.path.exists(AUTH_FILE):
                log("SESS", "Loading saved auth state...")
                context = browser.new_context(
                    storage_state=AUTH_FILE,
                    viewport={"width": WINDOW_W, "height": WINDOW_H},
                    device_scale_factor=DEVICE_SCALE,
                    reduced_motion="reduce",
                )
                page = context.new_page()
                page.set_viewport_size({"width": WINDOW_W, "height": WINDOW_H})
                page.goto(BASE_URL)
                try:
                    expect(page.locator('a[href="/app/profiles"]')).to_be_visible(
                        timeout=15000
                    )
                    log("SESS", "Session OK.")
                except Exception:
                    log("SESS", "Session invalid. Re-authenticating...")
                    context.close()
                    os.remove(AUTH_FILE)
                    context = browser.new_context(
                        viewport={"width": WINDOW_W, "height": WINDOW_H},
                        device_scale_factor=DEVICE_SCALE,
                        reduced_motion="reduce",
                    )
                    page = context.new_page()
                    page.set_viewport_size({"width": WINDOW_W, "height": WINDOW_H})
                    if not perform_login(page):
                        return
                    context.storage_state(path=AUTH_FILE)
            else:
                context = browser.new_context(
                    viewport={"width": WINDOW_W, "height": WINDOW_H},
                    device_scale_factor=DEVICE_SCALE,
                    reduced_motion="reduce",
                )
                page = context.new_page()
                page.set_viewport_size({"width": WINDOW_W, "height": WINDOW_H})
                if not perform_login(page):
                    return
                context.storage_state(path=AUTH_FILE)

            # ----- profiles page -----
            ensure_profiles_page(page)

            # ----- interactive team/profile selection -----
            mode, values = prompt_team_mode()

            if mode == "single":
                search_text = values[0]
                scrape_single_profile(page, search_text)
                log("DONE", "✅ Single profile processed.")
                return

            if mode == "prefix":
                prefix = values[0]
                log("FILTER", f"Selecting teams by prefix: '{prefix}'")
                teams = resolve_teams_by_prefix(page, prefix)
            else:
                teams = values

            log(
                "FILTER",
                f"{('Prefix=' + values[0]) if mode=='prefix' else 'Explicit list'} -> {len(teams)} teams resolved.",
            )

            # Process one team at a time into team folder
            for idx, team_name in enumerate(teams, start=1):
                log("TEAM", f"[{idx}/{len(teams)}] {team_name}")

                ensure_profiles_page(page)
                open_groups_dropdown(page)
                set_filter_to_single_team(page, team_name)

                # Team-level output directory
                team_dir = OUTPUT_DIR / sanitize_filename(team_name)
                team_dir.mkdir(parents=True, exist_ok=True)

                # ----- table pagination for this team -----
                processed_athletes = set()
                while True:
                    rows = page.locator("tbody tr")
                    nrows = rows.count()
                    log("TABLE", f"{nrows} rows for team '{team_name}' on this page.")

                    for i in range(nrows):
                        row = rows.nth(i)
                        try:
                            profile_name = row.locator("td").nth(1).inner_text().strip()
                        except Exception:
                            continue

                        if re.search(r"\d", profile_name):
                            log("TABLE", f"Skip test profile: {profile_name}")
                            continue

                        safe = sanitize_filename(profile_name)
                        if safe in processed_athletes:
                            log("TABLE", f"Skip already processed: {safe}")
                            continue

                        log("START", safe)
                        out_dir = team_dir / safe
                        out_dir.mkdir(parents=True, exist_ok=True)

                        log("NAV", "Opening athlete overview...")
                        row.locator('[aria-label="table-cell-initials"]').click()
                        expect(page).to_have_url(
                            re.compile(r".*/overview"), timeout=30000
                        )
                        page.wait_for_timeout(400)

                        try:
                            take_screens_for_athlete(page, out_dir, profile_name)
                            processed_athletes.add(safe)
                        except Exception as e:
                            log("ERROR", f"While capturing '{safe}': {e}")

                        log("NAV", "Back to profiles list...")
                        page.go_back()
                        ensure_profiles_page(page)

                    # pagination
                    next_btn = page.locator('button[aria-label="next page"]')
                    if not next_btn.is_enabled():
                        log("TABLE", f"Last page reached for team '{team_name}'.")
                        break
                    log("TABLE", "Next page...")
                    next_btn.click()
                    page.wait_for_load_state("networkidle")
                    reset_zoom(page)

                log("TEAM", f"✅ Team complete: {team_name}")

                try:
                    clear_selected_team_via_cross(page)
                    log("FILTER", "Cleared team selection via ×.")
                except Exception as e:
                    log("FILTER", f"(warn) Could not clear via ×: {e}")

            log("DONE", "✅ All teams processed.")

    except Exception as e:
        log("ERROR", f"Top-level error: {e}")
    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        run_cleanup()


if __name__ == "__main__":
    main()
