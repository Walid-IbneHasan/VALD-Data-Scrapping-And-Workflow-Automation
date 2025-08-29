# scrape_vald.py
import os
import re
import time
import subprocess
import sys
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import List, Optional, Tuple, Callable

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

# Global logger callback
LOGGER_CALLBACK: Optional[Callable[[str, str], None]] = None

def set_logger_callback(callback: Optional[Callable[[str, str], None]]) -> None:
    """Sets a global callback for logging."""
    global LOGGER_CALLBACK
    LOGGER_CALLBACK = callback

# ===================== UTILS =====================
def log(tag: str, msg: str) -> None:
    if LOGGER_CALLBACK:
        LOGGER_CALLBACK(tag, msg)
    else:
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
    if not EMAIL or not PASSWORD:
        log("ERROR", "EMAIL/PASSWORD must be set in .env")
        raise RuntimeError("EMAIL/PASSWORD must be set in .env")

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


# ===================== TILE SELECTORS =====================
def tile_forcedecks_by_name(page: Page, name: str) -> Locator:
    return page.locator(
        f'article:has([data-testid="forcedecks-tile"][data-test-name="{name}"])'
    ).first


def tiles_by_testid(page: Page, testid: str) -> Locator:
    return page.locator(f'article:has([data-testid="{testid}"])')


def tile_humantrak_by_title(page: Page, title_text: str) -> Locator:
    return (
        page.locator('article:has([data-testid="humantrak-tile"])')
        .filter(has=page.locator(".truncate.font-medium", has_text=title_text))
        .first
    )


def tile_by_heading_fallback(page: Page, title_text: str) -> Locator:
    return (
        page.locator("article")
        .filter(has=page.locator(".truncate.font-medium", has_text=title_text))
        .first
    )


def get_tile_heading_text(tile: Locator) -> str:
    heading = tile.locator(".truncate.font-medium").first
    return heading.inner_text().strip() if heading.count() else ""


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


# ===================== MODALS =====================
def _real_modal_locator(page: Page) -> Locator:
    close_btn = page.locator('[data-testid="close-button"]').first
    if close_btn.count() > 0:
        return close_btn.locator(
            "xpath=ancestor::div[contains(@class,'react-responsive-modal') or contains(@class,'fd-chart-modal') or @id='fd-chart-modal']"
        ).first
    return page.locator(
        "#fd-chart-modal, .fd-chart-modal, .react-responsive-modal-modal"
    ).first


def open_modal_forcedecks_by_name(page: Page, name: str) -> Locator:
    log("MODAL", f"Open '{name}'...")
    tile = tile_forcedecks_by_name(page, name)
    expect(tile).to_be_visible(timeout=20000)
    tile.scroll_into_view_if_needed()
    tile.click()
    modal = _real_modal_locator(page)
    expect(modal).to_be_visible(timeout=30000)
    page.wait_for_timeout(MODAL_MOUNT_WAIT)
    reset_zoom(page)
    log("MODAL", f"'{name}' visible.")
    return modal


def open_modal_by_testid(
    page: Page, testid: str, title_hint: Optional[str] = None
) -> Locator:
    if testid == "smartspeed-tile" and title_hint:
        tile = find_smartspeed_tile_by_title(page, title_hint)
    else:
        tile = tiles_by_testid(page, testid).first

    expect(tile).to_be_visible(timeout=20000)
    tile.scroll_into_view_if_needed()

    inner = tile.locator(f'[data-testid="{testid}"]').first
    heading = tile.locator(".truncate.font-medium").first

    attempts = [
        ("article center", lambda: tile.click()),
        ("article top-left", lambda: tile.click(position={"x": 18, "y": 18})),
        ("inner center", lambda: inner.click()),
        ("inner top-left", lambda: inner.click(position={"x": 18, "y": 18})),
        ("heading click", lambda: heading.click()),
    ]
    for label, fn in attempts:
        try:
            fn()
        except Exception:
            pass
        modal = _real_modal_locator(page)
        try:
            expect(modal).to_be_visible(timeout=3000)
            page.wait_for_timeout(MODAL_MOUNT_WAIT)
            reset_zoom(page)
            log("MODAL", f"Opened via {label}.")
            return modal
        except Exception:
            pass

    # Keyboard nudge
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

    raise RuntimeError(f"Could not open modal testid={testid} (after tries).")


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


# ===================== SCREENSHOTS & DEDUP =====================
def _shot_bytes(locator: Locator) -> bytes:
    """Return PNG bytes of the locator for hashing/write-after-unique."""
    locator.scroll_into_view_if_needed()
    time.sleep(0.15)
    return locator.screenshot()  # returns bytes


def _write_png(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def screenshot_tile(
    tile: Locator, save_dir: Path, prefix: str, counters: defaultdict
) -> None:
    """Direct file write (used for modals & base shots)."""
    expect(tile).to_be_visible(timeout=15000)
    counters[prefix] += 1
    idx = counters[prefix]
    path = save_dir / f"{prefix}_{idx:03d}.png"
    data = _shot_bytes(tile)
    _write_png(path, data)
    log("SHOT", path.name)


def screenshot_tile_unique(
    tile: Locator,
    save_dir: Path,
    prefix: str,
    counters: defaultdict,
    seen_hashes: set,
    max_dupe_retries: int = 2,
) -> bool:
    """
    Capture a screenshot; if it duplicates a previous image for this tile prefix, retry a few times.
    Returns True if a new file was written, False otherwise.
    """
    for attempt in range(max_dupe_retries + 1):
        data = _shot_bytes(tile)
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen_hashes:
            log(
                "SHOT",
                f"Duplicate detected for {prefix} (attempt {attempt+1}/{max_dupe_retries}); retrying...",
            )
            # small jiggle/settle to encourage re-render stability
            page = tile.page
            try:
                tile.scroll_into_view_if_needed()
                page.wait_for_timeout(250)
                move_mouse_off_view(page)
            except Exception:
                pass
            continue
        # unique -> write
        counters[prefix] += 1
        idx = counters[prefix]
        path = save_dir / f"{prefix}_{idx:03d}.png"
        _write_png(path, data)
        seen_hashes.add(digest)
        log("SHOT", path.name)
        return True
    return False


def _preload_modal_content(modal: Locator) -> None:
    """Gently scroll the modal top->bottom to trigger lazy blocks, then back up."""
    try:
        modal.evaluate("e => { e.scrollTop = 0; }")
        for y in (0.2, 0.4, 0.6, 0.8, 1.0):
            modal.evaluate("(e, y) => e.scrollTo(0, e.scrollHeight * y)", y)
            modal.page.wait_for_timeout(200)
        modal.evaluate("e => { e.scrollTop = 0; }")
        modal.page.wait_for_timeout(200)
    except Exception:
        pass


def _wait_for_accordion_count_to_settle(
    modal: Locator,
    max_wait_ms: int = ACCORDION_DISCOVERY_TIMEOUT,
    stable_for_ms: int = ACCORDION_STABLE_FOR_MS,
    interval_ms: int = ACCORDION_CHECK_INTERVAL,
) -> int:
    """Wait until the number of div.accordion stops changing for `stable_for_ms`."""
    elapsed = 0
    stable = 0
    prev = -1
    while elapsed < max_wait_ms:
        cnt = modal.locator("div.accordion").count()
        if cnt == prev and cnt > 0:
            stable += interval_ms
            if stable >= stable_for_ms:
                return cnt
        else:
            prev = cnt
            stable = 0
        modal.page.wait_for_timeout(interval_ms)
        elapsed += interval_ms
    return modal.locator("div.accordion").count()


def screenshot_modal_accordions(
    page: Page, modal: Locator, save_dir: Path, prefix: str, counters: defaultdict
) -> int:
    """Screenshot each accordion section; if none, take one full-modal shot."""
    _preload_modal_content(modal)

    cnt = _wait_for_accordion_count_to_settle(modal)
    if cnt == 0:
        log("MODAL", "No accordions detected; taking single modal shot as fallback.")
        screenshot_tile(modal, save_dir, prefix, counters)
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
            idx = counters[prefix]
            path = save_dir / f"{prefix}_{idx:03d}.png"
            data = _shot_bytes(section)
            _write_png(path, data)
            log("SHOT", f"{path.name} (accordion {i+1}/{total})")
            took += 1
        except Exception as e:
            log("SHOT", f"Skip accordion {i+1}: {e}")

    return took


# ---------- HumanTrak dropdown helpers (robust & pixel-aware) ----------
def short_token_for_label(label: str) -> str:
    """A short, unique substring we can reliably match in truncated UI text."""
    if "Ankle Dorsiflexion" in label:
        return "Ankle Dorsiflexion"
    if "Hip Adduction" in label:
        return "Hip Adduction"
    if "Peak Knee Flexion" in label:
        return "Peak Knee Flexion"
    return label[:24]


def _get_chart_locator(tile: Locator) -> Locator:
    """Prefer a specific chart node to fingerprint; fallback to tile."""
    # Prefer canvas if present (common for HumanTrak)
    canvas = tile.locator("canvas").first
    if canvas.count() > 0:
        return canvas
    # Else an SVG inside a wrapper
    svg = tile.locator(".recharts-wrapper svg, svg").first
    if svg.count() > 0:
        return svg
    # Else the wrapper itself
    wrapper = tile.locator(".recharts-wrapper").first
    if wrapper.count() > 0:
        return wrapper
    # Fallback to entire tile
    return tile


def _fingerprint(locator: Locator) -> str:
    """PNG bytes hash for pixel-level change detection."""
    data = _shot_bytes(locator)
    return hashlib.sha256(data).hexdigest()


def _open_metric_menu(tile: Locator, attempts: int = 4) -> Locator:
    """Open the tile's metric dropdown menu robustly and return the menu locator."""
    page = tile.page
    btn = tile.locator('[data-testid="metric-dropdown-button"]').first
    expect(btn).to_be_visible(timeout=12000)
    btn.scroll_into_view_if_needed()

    for _ in range(attempts):
        try:
            btn.click()
        except Exception:
            pass
        menu = tile.locator('[data-testid="metric-dropdown-items"]').first
        try:
            expect(menu).to_be_visible(timeout=2500)
            return menu
        except Exception:
            page.wait_for_timeout(250)

    # Last try: click button via coordinates to avoid overlay swallowing clicks
    try:
        btn.click(position={"x": 10, "y": 10})
        menu = tile.locator('[data-testid="metric-dropdown-items"]').first
        expect(menu).to_be_visible(timeout=2500)
        return menu
    except Exception:
        raise TimeoutError("Metric dropdown did not open for tile.")


def select_metric_and_wait(
    page: Page, tile: Locator, label: str, timeout_ms: int = 10000
) -> None:
    """
    Open the dropdown, click the exact label, then wait until BOTH:
      1) The button text contains the label's short token (handles truncation)
      2) The chart PIXEL fingerprint changes (canvas/SVG safe)
    """
    token = short_token_for_label(label)

    # Snapshot chart fingerprint BEFORE selection
    chart_before = _get_chart_locator(tile)
    fp_before = _fingerprint(chart_before)

    # Open dropdown (robust)
    menu = _open_metric_menu(tile)

    # Click the exact option text
    option = menu.get_by_role("menuitem", name=re.compile(rf"^{re.escape(label)}\s*$"))
    expect(option.first).to_be_visible(timeout=8000)
    option.first.scroll_into_view_if_needed()
    option.first.click(force=True)

    # Ensure menu closed
    try:
        expect(menu).not_to_be_visible(timeout=3000)
    except Exception:
        pass

    # 1) Verify button text reflects new selection (truncate-aware)
    btn = tile.locator('[data-testid="metric-dropdown-button"]').first
    span = btn.locator("span.truncate").first
    try:
        expect(span).to_contain_text(
            re.compile(re.escape(token), re.I), timeout=timeout_ms
        )
    except Exception:
        # give the UI another small beat then re-check
        page.wait_for_timeout(800)
        expect(span).to_contain_text(re.compile(re.escape(token), re.I), timeout=3000)

    # 2) Wait for chart pixel fingerprint to change (canvas/SVG aware)
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        chart_after = _get_chart_locator(tile)  # re-query in case of re-render
        try:
            fp_after = _fingerprint(chart_after)
            if fp_after != fp_before:
                break
        except Exception:
            pass
        page.wait_for_timeout(150)

    # small final settle
    page.wait_for_timeout(MENU_AFTER_SELECT)


def bounce_then_reselect(
    page: Page, tile: Locator, desired_label: str, alternatives: List[str]
) -> None:
    """To break sticky renders, switch to an alternative metric briefly, then back to desired."""
    alt = next((x for x in alternatives if x != desired_label), None)
    if not alt:
        return
    try:
        select_metric_and_wait(page, tile, alt)
        page.wait_for_timeout(400)
    except Exception:
        pass
    select_metric_and_wait(page, desired_label)


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

    taken = 0
    seen_hashes: set = set()
    prefix = title.replace(" ", "_")

    if include_base:
        log("CARD", f"{title}: base screenshot")
        move_mouse_off_view(page)
        if screenshot_tile_unique(tile, save_dir, prefix, counters, seen_hashes):
            taken += 1

    for label in labels_to_capture:
        success = False
        for attempt in range(1, 4):
            try:
                log("CARD", f"{title}: selecting '{label}' (attempt {attempt}/3)")
                select_metric_and_wait(page, tile, label)
                move_mouse_off_view(page)
                if screenshot_tile_unique(
                    tile, save_dir, prefix, counters, seen_hashes
                ):
                    success = True
                    taken += 1
                    break
                else:
                    # If duplicate bytes, try bouncing to another metric and back
                    log(
                        "CARD",
                        f"{title}: duplicate after select, bouncing via alt metric...",
                    )
                    bounce_then_reselect(page, tile, label, labels_to_capture)
                    move_mouse_off_view(page)
            except Exception as e:
                log("CARD", f"(retry) '{title}' -> '{label}' failed: {e}")
                page.wait_for_timeout(600)

        if not success:
            log(
                "CARD",
                f"(skip) '{title}' -> '{label}' produced duplicate content after retries.",
            )

    log("CARD", f"{title}: done ({taken} shots)")
    return taken


# ===================== PER-ATHLETE FLOW =====================
def take_screens_for_athlete(page: Page, out_dir: Path, athlete_name: str) -> None:
    reset_zoom(page)
    log("FLOW", f"Capturing for athlete: {athlete_name}")
    save_dir = Path(out_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    counters: defaultdict = defaultdict(int)

    try:
        expect(tile_forcedecks_by_name(page, "Countermovement Jump")).to_be_visible(
            timeout=20000
        )
    except Exception:
        log("FLOW", "CMJ tile not found immediately; proceeding anyway.")
    page.wait_for_timeout(300)

    # ---------- Modal tiles (accordion-based) ----------
    for label, opener in [
        (
            "Countermovement_Jump",
            lambda: open_modal_forcedecks_by_name(page, "Countermovement Jump"),
        ),
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

    try:
        capture_humantrak_card(
            page, "Lunge", ht_labels, save_dir, counters, include_base=False
        )
    except Exception as e:
        log("FLOW", f"(warn) Lunge failed: {e}")

    total = sum(counters.values())
    log("FLOW", f"Athlete '{athlete_name}' complete. Total images: {total}")


# ===================== TEAM SELECTION HELPERS =====================
def open_groups_dropdown(page: Page) -> None:
    """Robustly open the Groups react-select dropdown (no fragile 'All Groups' text match)."""
    # Ensure we're on profiles and scrolled to top
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
    # last resort
    control.click(position={"x": 10, "y": 10})
    expect(page.locator(".react-select__menu")).to_be_visible(timeout=3000)


def clear_all_selected_groups(page: Page) -> None:
    """If chips are present, remove them so only one team is selected for filtering."""
    control = page.locator(".react-select__control").first
    try:
        # Remove all 'x' chips if present
        while True:
            remove_btns = control.locator(".react-select__multi-value__remove")
            if remove_btns.count() == 0:
                break
            remove_btns.first.click()
            page.wait_for_timeout(120)
    except Exception:
        pass


def list_all_group_options(page: Page) -> List[str]:
    """Return visible option texts currently shown in the open dropdown."""
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
    """Select a single option by exact visible label from the open dropdown."""
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
    Returns ("prefix", [prefix])  OR  ("list", [names...])
    """
    print("\n=== Team selection ===")
    print(
        "1) Start-text mode (e.g., 'KC Fusion' -> process ALL teams that start with it)"
    )
    print(
        "2) Explicit list (paste comma-separated names OR path to a .txt with one per line)"
    )
    mode = input("Pick 1 or 2 (default 1): ").strip() or "1"
    if mode not in ("1", "2"):
        mode = "1"

    if mode == "1":
        prefix = (
            input("Enter starting text (default 'KC Fusion'): ").strip() or "KC Fusion"
        )
        return "prefix", [prefix]
    else:
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


def resolve_teams_by_prefix(page: Page, prefix: str) -> List[str]:
    open_groups_dropdown(page)
    texts = list_all_group_options(page)
    matched = [t for t in texts if t.startswith(prefix)]
    if not matched:
        raise RuntimeError(f"No team options start with: {prefix}")
    return matched


def set_filter_to_single_team(page: Page, team_name: str) -> None:
    """Clear previous selections and set the filter to exactly one team."""
    log("FILTER", f"Setting filter to single team: {team_name}")
    clear_all_selected_groups(page)
    open_groups_dropdown(page)
    select_group_option_exact(page, team_name)
    page.locator("body").click(position={"x": 5, "y": 5})
    page.wait_for_load_state("networkidle")
    reset_zoom(page)


# --- NEW: click the react-select “×” to clear the current team after finishing a team ---
def clear_selected_team_via_cross(page: Page) -> None:
    """
    Click the react-select clear indicator (×) to clear current selection.
    Works for both single- and multi-select variants.
    """
    ensure_profiles_page(page)
    control = page.locator(".react-select__control").first
    if control.count() == 0:
        return

    # Hover/focus can be required for the clear indicator to show
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

    # Give the table a brief moment to refresh (XHR lists)
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        page.wait_for_timeout(400)
    reset_zoom(page)


# ===================== CLEANUP RUNNER =====================
def run_cleanup():
    # This will be handled by the main application
    pass


# ===================== MAIN LOGIC =====================
def run_scraper(
    team_selection_mode: str,
    team_values: List[str],
    output_dir: str,
    headless: bool = True,
    log_callback: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """
    Main scraping logic.
    :param team_selection_mode: 'prefix' or 'list'.
    :param team_values: List of team names or a prefix string.
    :param headless: Whether to run the browser in headless mode.
    :param log_callback: Callback for logging.
    :return: True on success, False on failure.
    """
    if log_callback:
        set_logger_callback(log_callback)

    browser = None
    context = None
    page: Optional[Page] = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                slow_mo=55 if not headless else 0,
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
                    if context:
                        context.close()
                    if os.path.exists(AUTH_FILE):
                        os.remove(AUTH_FILE)
                    context = browser.new_context(
                        viewport={"width": WINDOW_W, "height": WINDOW_H},
                        device_scale_factor=DEVICE_SCALE,
                        reduced_motion="reduce",
                    )
                    page = context.new_page()
                    page.set_viewport_size({"width": WINDOW_W, "height": WINDOW_H})
                    if not perform_login(page):
                        return False
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
                    return False
                context.storage_state(path=AUTH_FILE)

            # ----- profiles page -----
            ensure_profiles_page(page)

            # ----- team selection -----
            if team_selection_mode == "prefix":
                prefix = team_values[0]
                log("FILTER", f"Selecting teams by prefix: '{prefix}'")
                teams = resolve_teams_by_prefix(page, prefix)
            else:
                teams = team_values

            log(
                "FILTER",
                f"{('Prefix=' + team_values[0]) if team_selection_mode=='prefix' else 'Explicit list'} -> {len(teams)} teams resolved.",
            )

            # Process one team at a time into team folder
            for idx, team_name in enumerate(teams, start=1):
                log("TEAM", f"[{idx}/{len(teams)}] {team_name}")

                # ensure we're on the profiles list before switching teams
                ensure_profiles_page(page)
                open_groups_dropdown(page)
                set_filter_to_single_team(page, team_name)

                # Team-level output directory
                team_dir = Path(output_dir) / sanitize_filename(team_name)
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

                        # Skip obvious test rows with digits
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

                        # open athlete overview
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

                        # back to list
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

                # NEW: clear the selected team via the “×” so the next team won't merge
                try:
                    clear_selected_team_via_cross(page)
                    log("FILTER", "Cleared team selection via ×.")
                except Exception as e:
                    log("FILTER", f"(warn) Could not clear via ×: {e}")

            log("DONE", "✅ All teams processed.")
            return True

    except Exception as e:
        log("ERROR", f"Top-level error: {e}")
        return False
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

def main():
    # This is for standalone execution
    if not EMAIL or not PASSWORD:
        print("ERROR| EMAIL and PASSWORD must be set in a .env file.")
        return

    mode, values = prompt_team_mode()
    run_scraper(mode, values, headless=HEADLESS)

if __name__ == "__main__":
    main()
