# chatgpt_generate.py
# (Team -> Athlete aware; 1 RPM + ~70s padding; 3-min cooldown after every 5 successes)

import os
import time
import csv
import base64
import mimetypes
import random
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI

# Try to import granular exception types (works with openai>=1.0)
try:
    from openai import RateLimitError, APIError, APIConnectionError, APITimeoutError
except Exception:  # graceful fallback if symbols not present
    RateLimitError = APIError = APIConnectionError = APITimeoutError = Exception


# ===================== CONFIG =====================
BASE_DIR = Path(r"D:\Vald Data")  # Root folder with TEAM subfolders
MODEL = "gpt-4o-mini"  # Vision model
TEMPERATURE = 0.3
MAX_RETRIES = 5  # allow more retries
BACKOFF_BASE = 8  # seconds (base for exponential backoff)
RATE_LIMIT_RPM = 1  # <= 1 request per minute
SAFE_PACE_SECONDS = 70  # ~70s padding between successful calls
BATCH_SUCCESS_SIZE = 5  # cooldown trigger size
BATCH_COOLDOWN_SECONDS = 180  # 3 minutes

LOG_CSV = BASE_DIR / "run_log.csv"
FAILED_LIST = BASE_DIR / "failed.txt"
SKIP_IF_MARKDOWN_EXISTS = True  # skip athlete if Analysis.md exists
FORCE = False  # set True to overwrite Analysis.md

VALID_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MARKDOWN_NAME_TEMPLATE = "{athlete} Analysis.md"


# ===================== INIT =====================
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set in environment (.env).")

client = OpenAI(api_key=API_KEY)


# ===================== HELPERS =====================
def b64_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "image/png"
    with path.open("rb") as f:
        b = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b}"


def list_images(folder: Path) -> List[Path]:
    imgs = []
    for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
        if p.suffix.lower() in VALID_IMAGE_EXTS:
            imgs.append(p)
    return imgs


def gather_team_athletes(root: Path) -> List[Tuple[str, Path]]:
    """
    Return a list of (team_name, athlete_dir) pairs.

    Primary: root/<Team>/<Athlete>/
    Back-compat: if athlete dirs live directly under root, treat team as "".
    """
    pairs: List[Tuple[str, Path]] = []

    # First: Team -> Athlete
    for team_dir in sorted(
        [p for p in root.iterdir() if p.is_dir()], key=lambda x: x.name.lower()
    ):
        # Heuristic: if team_dir contains image files directly, it's probably an athlete folder (old layout)
        # We'll collect real teams as those that have at least one subdirectory.
        subdirs = [c for c in team_dir.iterdir() if c.is_dir()]
        if subdirs:
            for athlete_dir in sorted(subdirs, key=lambda x: x.name.lower()):
                pairs.append((team_dir.name, athlete_dir))

    # Back-compat: athletes directly under base (no team)
    # Only include folders that contain at least one image so we don't double-count teams above.
    direct_athletes = [
        p
        for p in BASE_DIR.iterdir()
        if p.is_dir()
        and any(
            (p / f).is_file() and (p / f).suffix.lower() in VALID_IMAGE_EXTS
            for f in os.listdir(p)
        )
    ]
    for a in sorted(direct_athletes, key=lambda x: x.name.lower()):
        pairs.append(("", a))

    return pairs


def build_prompt(athlete_name: str) -> str:
    # Same structure (unchanged), the images are provided separately
    return f"""These are the performance data of {athlete_name} who is 11–16 years
old female. Here are 5-0-5 Drill, 20 YD Sprint, Lunges, Overhead
Squat, Nordic & Countermovement Jump. Analyze them carefully.
Act as a Physical Coach. Extract the data, analyze them and give me
insights and improvements in 3 short bulletin style. And Save the
style in the memory as Short Format Style.

---

## **Report Structure (Per Athlete)**

### **1. 5-0-5 Drill**

* **Content**:
  * 1 image (5-0-5_Drill_002.png)
  * **Insights**: 3 short bullet points
  * **Improvements**: 3 short bullet points

---

### **2. 20-Yard Sprint**

* **Content**:
  * 1 image (20_Yard_Sprint_002.png)
  * **Insights**: 3 short bullet points
  * **Improvements**: 3 short bullet points

---

### **3. Overhead Squat**

* **Content**:
  * 3 images
  * **Insights**: 3 short bullet points
  * **Improvements**: 3 short bullet points

---

### **4. Lunges**

* **Content**:
  * 3 images
  * **Insights**: 3 short bullet points
  * **Improvements**: 3 short bullet points

---

### **5. Nordic**

* **Content**:
  * 6 images (each screenshot = different metric)
  * **For Nordic_002:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points

  * **For Nordic_003:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points

  * **For Nordic_004:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points

  * **For Nordic_005:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points

  * **For Nordic_006:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points

  * **For Nordic_007:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points

---

### **6. Countermovement Jump (CMJ)**

* **Content**:
  * 6 images (each screenshot = different metric)
  * **For Countermovement_Jump_002:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points

  * **For Countermovement_Jump_003:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points

  * **For Countermovement_Jump_004:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points

  * **For Countermovement_Jump_005:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points

  * **For Countermovement_Jump_006:**: For this image generate at least 3 Insights and Improvements. Both must consist minimum 3 bullet points.
    * Insights: 3 short bullet points
    * Improvements: 3 short bullet points


---
"""


def build_user_content(prompt_text: str, image_paths: List[Path]):
    # One "user" message containing the text and all images as data URLs
    content = [{"type": "text", "text": prompt_text}]
    for p in image_paths:
        content.append({"type": "image_url", "image_url": {"url": b64_data_url(p)}})
    return content


def ensure_log_files():
    if not LOG_CSV.exists():
        with LOG_CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            # keep same header so older consumers don't break
            w.writerow(["athlete", "status", "started_at", "finished_at", "notes"])
    if not FAILED_LIST.exists():
        FAILED_LIST.write_text("", encoding="utf-8")


def append_log(
    athlete: str, status: str, started: float, finished: float, notes: str = ""
):
    with LOG_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([athlete, status, int(started), int(finished), notes])


def append_failure(athlete: str, reason: str):
    with FAILED_LIST.open("a", encoding="utf-8") as f:
        f.write(f"{athlete}\t{reason}\n")


@dataclass
class RateLimiter:
    rpm: int
    window: int = 60

    def __post_init__(self):
        self.calls = deque()

    def wait_for_slot(self):
        now = time.time()
        # Purge old calls outside window
        while self.calls and now - self.calls[0] > self.window:
            self.calls.popleft()
        # If at capacity, sleep until slot frees
        if len(self.calls) >= self.rpm:
            to_sleep = self.window - (now - self.calls[0]) + 0.5
            if to_sleep > 0:
                time.sleep(to_sleep)

    def mark(self):
        self.calls.append(time.time())


rl = RateLimiter(RATE_LIMIT_RPM)
ensure_log_files()


def call_with_retries(model: str, content):
    """
    Strict 1 RPM pacing + ~70s extra padding between *successful* calls.
    Robust 429 handling: exponential backoff with jitter and respect Retry-After when available.
    """
    attempts = 0
    last_err = None

    while attempts < MAX_RETRIES:
        attempts += 1
        try:
            # Respect RPM cap
            rl.wait_for_slot()

            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                temperature=TEMPERATURE,
            )

            # mark a successful call against the RPM bucket
            rl.mark()

            # Gentle extra padding to stay under TPM (token-per-minute) limits
            jitter = random.uniform(5, 12)  # add small randomness to desync requests
            time.sleep(SAFE_PACE_SECONDS + jitter)

            msg = resp.choices[0].message.content if resp.choices else ""
            if not msg or not msg.strip():
                raise RuntimeError("Empty completion content.")
            return msg

        except RateLimitError as e:
            # If we can read Retry-After header, honor it; otherwise exponential + padding.
            retry_after = None
            try:
                retry_after = float(
                    getattr(getattr(e, "response", None), "headers", {}).get(
                        "Retry-After", 0
                    )
                )
            except Exception:
                retry_after = None
            # base wait: padding + exponential backoff
            backoff = max(SAFE_PACE_SECONDS + 10, BACKOFF_BASE * (2 ** (attempts - 1)))
            sleep_for = max(backoff, retry_after or 0)
            time.sleep(sleep_for)
            last_err = e

        except (APIConnectionError, APITimeoutError) as e:
            # transient network; exponential backoff with jitter
            backoff = BACKOFF_BASE * (2 ** (attempts - 1)) + random.uniform(1.0, 4.0)
            time.sleep(backoff)
            last_err = e

        except APIError as e:
            # Server-side hiccup (5xx) -> backoff; 4xx (besides 429) -> likely unrecoverable
            status = getattr(e, "status_code", None)
            if status and 500 <= int(status) < 600:
                backoff = BACKOFF_BASE * (2 ** (attempts - 1)) + random.uniform(
                    1.0, 4.0
                )
                time.sleep(backoff)
                last_err = e
            else:
                # Unrecoverable client error (e.g., 400) — don't spin on it
                raise

        except Exception as e:
            # Unknown error: try a conservative backoff once or twice
            backoff = BACKOFF_BASE * (2 ** (attempts - 1)) + random.uniform(1.0, 3.0)
            time.sleep(backoff)
            last_err = e

    raise RuntimeError(f"API failed after {MAX_RETRIES} attempts: {last_err}")


def write_markdown(
    folder: Path, team: str, athlete: str, images: List[Path], body_md: str
) -> Path:
    filename = MARKDOWN_NAME_TEMPLATE.format(athlete=athlete).strip()
    out_path = folder / filename

    header = [
        f"# {athlete} — Short Format Report",
        "",
        f"- Team: {team if team else '(none)'}",
        f"- Cohort: 11–16 years old female",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Images included ({len(images)}):",
    ]
    for p in images:
        header.append(f"  - {p.name}")
    header.append("\n---\n")

    content = "\n".join(header) + body_md.strip() + "\n"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def process_athlete_folder(team: str, folder: Path) -> Optional[Path]:
    athlete = folder.name.strip()
    started = time.time()

    # Skip if analysis exists (unless FORCE)
    md_path = folder / MARKDOWN_NAME_TEMPLATE.format(athlete=athlete).strip()
    if SKIP_IF_MARKDOWN_EXISTS and not FORCE and md_path.exists():
        append_log(
            athlete,
            "skipped_exists",
            started,
            time.time(),
            f"Analysis.md already exists | Team={team}",
        )
        return md_path

    images = list_images(folder)
    print(
        f"[SCAN] Team='{team if team else '(none)'}' | Athlete='{athlete}' | Images={len(images)}"
    )
    if not images:
        append_log(
            athlete, "no_images", started, time.time(), f"No images found | Team={team}"
        )
        append_failure(athlete, f"No images found | Team={team}")
        return None

    prompt_text = build_prompt(athlete)
    user_content = build_user_content(prompt_text, images)

    try:
        completion_md = call_with_retries(MODEL, user_content)
        out_path = write_markdown(folder, team, athlete, images, completion_md)
        append_log(
            athlete, "ok", started, time.time(), f"Saved: {out_path.name} | Team={team}"
        )
        return out_path
    except Exception as e:
        append_log(athlete, "failed", started, time.time(), f"{e} | Team={team}")
        append_failure(athlete, f"{e} | Team={team}")
        return None


def main():
    print(f"[INFO] Scanning base directory: {BASE_DIR}")

    pairs = gather_team_athletes(BASE_DIR)
    if not pairs:
        print("[WARN] No team/athlete folders found.")
        return

    # Group by team for nicer console output
    current_team = None
    successes_since_break = 0
    total_success = 0

    for team, athlete_dir in pairs:
        if team != current_team:
            current_team = team
            print(f"\n[TEAM] {current_team if current_team else '(none)'}")

        print(f"[RUN ] {athlete_dir.name}")
        res = process_athlete_folder(team, athlete_dir)
        if res:
            print(f"[DONE] {athlete_dir.name} -> {res.name}")
            successes_since_break += 1
            total_success += 1

            # Cooldown after every N successful generations
            if successes_since_break >= BATCH_SUCCESS_SIZE:
                print(
                    f"[SLEEP] Completed {successes_since_break} markdowns. Cooling down for {BATCH_COOLDOWN_SECONDS}s..."
                )
                time.sleep(BATCH_COOLDOWN_SECONDS)
                successes_since_break = 0
        else:
            print(f"[FAIL] {athlete_dir.name}")

    print(f"\n[INFO] Completed. Successful markdowns: {total_success}")


if __name__ == "__main__":
    main()
