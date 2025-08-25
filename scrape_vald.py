# scrape_vald.py
import os
import re
import time
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Optional, Dict

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

# Tune these if needed on your machine
SHORT_PAUSE = 350  # ms settle pauses inside modals/tiles (was 250)
MENU_AFTER_SELECT = 750
MODAL_MOUNT_WAIT = 800  # ms after modal reported visible (was 500)

# New: more patient accordion discovery & settle timings
ACCORDION_DISCOVERY_TIMEOUT = 30000  # wait up to 30s for accordions to appear
ACCORDION_STABLE_FOR_MS = 1500  # require count to be stable this long
ACCORDION_CHECK_INTERVAL = 250
ACCORDION_SECTION_SETTLE_MS = 600  # settle each section before screenshot

# ===================== WINDOW / VIEWPORT =====================
# Larger headed window + viewport for bigger, sharper screenshots
WINDOW_W = 1920
WINDOW_H = 1080
DEVICE_SCALE = 2  # 1=normal, 2="Retina-like" crisper element screenshots


# ===================== UTILS =====================
def log(tag: str, msg: str) -> None:
    print(f"{tag:<7}| {msg}")


def sanitize_filename(name: str) -> str:
    name = name.replace("\n", " ").replace("\r", " ")
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def move_mouse_off_view(page: Page) -> None:
    """
    Nudge the mouse to the top-left of the viewport so any hover tooltips
    on HumanTrak cards disappear before we screenshot.
    """
    try:
        page.mouse.move(0, 0)
        page.wait_for_timeout(150)
    except Exception:
        pass


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


# ===================== SCREENSHOTS (ACCORDION VERSION) =====================
def _shot(locator: Locator, path: Path) -> None:
    locator.scroll_into_view_if_needed()
    time.sleep(0.15)
    locator.screenshot(path=str(path))


def screenshot_tile(
    tile: Locator, save_dir: Path, prefix: str, counters: defaultdict
) -> None:
    expect(tile).to_be_visible(timeout=15000)
    counters[prefix] += 1
    idx = counters[prefix]
    path = save_dir / f"{prefix}_{idx:03d}.png"
    _shot(tile, path)
    log("SHOT", path.name)


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
    # timeout: return whatever we have
    return modal.locator("div.accordion").count()


def screenshot_modal_accordions(
    page: Page, modal: Locator, save_dir: Path, prefix: str, counters: defaultdict
) -> int:
    """
    Screenshot every 'div.accordion'. If none appear in time,
    fall back to 1 full-modal shot so you still get output.
    """
    # Proactively scroll so lazy sections mount
    _preload_modal_content(modal)

    cnt = _wait_for_accordion_count_to_settle(modal)
    if cnt == 0:
        log("MODAL", "No accordions detected; taking single modal shot as fallback.")
        screenshot_tile(modal, save_dir, prefix, counters)
        return 1

    accordions = modal.locator("div.accordion")
    total = cnt
    log("MODAL", f"{prefix}: found {total} accordion sections (stable).")

    # Move mouse away from charts to avoid floating tooltips
    try:
        page.mouse.move(5, 5)
    except Exception:
        pass

    took = 0
    for i in range(total):
        section = accordions.nth(i)
        try:
            # Give each section's body a chance to render charts/text
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
            section.screenshot(path=str(path))
            log("SHOT", f"{path.name} (accordion {i+1}/{total})")
            took += 1
        except Exception as e:
            log("SHOT", f"Skip accordion {i+1}: {e}")

    return took


# ---------- HumanTrak dropdown helpers ----------
def open_dropdown_and_select_in_tile(page: Page, tile: Locator, label: str) -> None:
    btn = tile.locator('[data-testid="metric-dropdown-button"]').first
    expect(btn).to_be_visible(timeout=12000)
    btn.scroll_into_view_if_needed()
    btn.click()

    # Scope the menu to THIS tile to avoid cross-tile confusion
    menu = tile.locator('[data-testid="metric-dropdown-items"]').first
    expect(menu).to_be_visible(timeout=12000)

    option = menu.get_by_role(
        "menuitem", name=re.compile(rf"^{re.escape(label)}\s*$")
    ).first
    expect(option).to_be_visible(timeout=12000)
    option.scroll_into_view_if_needed()
    option.click(force=True)

    # Wait for button text to reflect new selection (truncate-aware)
    try:
        span = btn.locator("span.truncate").first
        expect(span).to_have_text(re.compile(re.escape(label)), timeout=5000)
    except Exception:
        page.wait_for_timeout(400)  # small fallback
    page.wait_for_timeout(MENU_AFTER_SELECT)


def capture_humantrak_card(
    page: Page,
    title: str,
    labels_to_capture: List[str],
    save_dir: Path,
    counters: defaultdict,
) -> int:
    """
    Screenshot the HumanTrak tile once as-is, then after selecting each requested metric.
    """
    # Prefer data-testid="humantrak-tile"; fallback to heading
    tile = tile_humantrak_by_title(page, title)
    if tile.count() == 0 or not tile.is_visible():
        tile = tile_by_heading_fallback(page, title)

    expect(tile).to_be_visible(timeout=15000)

    taken = 0
    log("CARD", f"{title}: base screenshot")
    move_mouse_off_view(page)
    screenshot_tile(tile, save_dir, title.replace(" ", "_"), counters)
    taken += 1

    for label in labels_to_capture:
        try:
            log("CARD", f"{title}: selecting '{label}'")
            open_dropdown_and_select_in_tile(page, tile, label)
            move_mouse_off_view(page)
            screenshot_tile(tile, save_dir, title.replace(" ", "_"), counters)
            taken += 1
        except Exception as e:
            log("CARD", f"(skip) '{title}' -> '{label}' failed: {e}")

    log("CARD", f"{title}: done ({taken} shots)")
    return taken


# ===================== PER-ATHLETE FLOW =====================
def take_screens_for_athlete(page: Page, out_dir: str, athlete_name: str) -> None:
    log("FLOW", f"Capturing for athlete: {athlete_name}")
    save_dir = Path(out_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    counters: defaultdict = defaultdict(int)

    # Make sure page has mounted at least CMJ
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
        "Avg Hip Adduction at Peak Knee Flexion - Left & Right",
        "Avg Peak Knee Flexion - Left & Right",
    ]
    try:
        capture_humantrak_card(page, "Overhead Squat", ht_labels, save_dir, counters)
    except Exception as e:
        log("FLOW", f"(warn) Overhead Squat failed: {e}")

    try:
        capture_humantrak_card(page, "Lunge", ht_labels, save_dir, counters)
    except Exception as e:
        log("FLOW", f"(warn) Lunge failed: {e}")

    total = sum(counters.values())
    log("FLOW", f"Athlete '{athlete_name}' complete. Total images: {total}")


# ===================== CLEANUP RUNNER =====================
def run_cleanup():
    """
    Runs cleanup_vald_images.py in the same directory as this script.
    Executes even if the main flow raises, thanks to the try/finally in main().
    """
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
                headless=False,
                slow_mo=55,
                args=[f"--window-size={WINDOW_W},{WINDOW_H}"],
            )

            # ----- session -----
            if os.path.exists(AUTH_FILE):
                log("SESS", "Loading saved auth state...")
                context = browser.new_context(
                    storage_state=AUTH_FILE,
                    viewport={"width": WINDOW_W, "height": WINDOW_H},
                    device_scale_factor=DEVICE_SCALE,
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
                )
                page = context.new_page()
                page.set_viewport_size({"width": WINDOW_W, "height": WINDOW_H})
                if not perform_login(page):
                    return
                context.storage_state(path=AUTH_FILE)

            # ----- profiles page -----
            if "/app/profiles" not in page.url:
                page.locator('a[href="/app/profiles"]').click()
            expect(page).to_have_url(re.compile(r".*/app/profiles"))
            log("NAV", "On profiles page; waiting for network idle...")
            page.wait_for_load_state("networkidle", timeout=30000)

            # ----- filter Fusion Soccer teams -----
            log("FILTER", "Selecting all 'Fusion Soccer' teams...")
            groups_dropdown = page.locator(
                ".react-select__control", has_text="All Groups"
            ).first
            expect(groups_dropdown).to_be_visible(timeout=15000)
            groups_dropdown.click()
            expect(page.locator(".react-select__menu")).to_be_visible(timeout=15000)

            team_options = page.locator(".react-select__menu .react-select__option")
            fusion_teams = team_options.filter(has_text=re.compile(r"^Fusion Soccer"))
            names = [t.strip() for t in fusion_teams.all_inner_texts()]
            log("FILTER", f"Found {len(names)} teams.")
            for nm in names:
                page.get_by_role("option", name=nm).click()
                log("FILTER", f"Selected: {nm}")

            # close the select menu
            page.locator("body").click(position={"x": 5, "y": 5})
            page.wait_for_load_state("networkidle")
            log("FILTER", "Done. Starting profiles loop...")

            processed = set()

            # ----- table pagination -----
            while True:
                rows = page.locator("tbody tr")
                nrows = rows.count()
                log("TABLE", f"{nrows} rows on this page.")

                for i in range(nrows):
                    row = rows.nth(i)
                    profile_name = row.locator("td").nth(1).inner_text().strip()

                    # Skip test rows
                    if re.search(r"\d", profile_name):
                        log("TABLE", f"Skip test profile: {profile_name}")
                        continue

                    safe = sanitize_filename(profile_name)
                    if safe in processed:
                        log("TABLE", f"Skip already processed: {safe}")
                        continue

                    log("START", safe)
                    out_dir = OUTPUT_DIR / safe
                    out_dir.mkdir(parents=True, exist_ok=True)

                    # open athlete overview
                    log("NAV", "Opening athlete overview...")
                    row.locator('[aria-label="table-cell-initials"]').click()
                    expect(page).to_have_url(re.compile(r".*/overview"), timeout=30000)
                    page.wait_for_timeout(400)

                    try:
                        take_screens_for_athlete(page, str(out_dir), profile_name)
                        processed.add(safe)
                    except Exception as e:
                        log("ERROR", f"While capturing '{safe}': {e}")

                    # back to list
                    log("NAV", "Back to profiles list...")
                    page.go_back()
                    expect(page).to_have_url(
                        re.compile(r".*/app/profiles"), timeout=20000
                    )
                    page.wait_for_load_state("networkidle")

                next_btn = page.locator('button[aria-label="next page"]')
                if not next_btn.is_enabled():
                    log("TABLE", "Last page reached.")
                    break
                log("TABLE", "Next page...")
                next_btn.click()
                page.wait_for_load_state("networkidle")

            log("DONE", "✅ Automation complete.")

    except Exception as e:
        log("ERROR", f"Top-level error: {e}")
    finally:
        # Close the browser/context first (if they were started), then run cleanup
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
