# chatgpt_generate.py
import os
import time
import csv
import base64
import mimetypes
import random
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Callable

from dotenv import load_dotenv
from openai import OpenAI

try:
    from openai import RateLimitError, APIError, APIConnectionError, APITimeoutError
except Exception:
    RateLimitError = APIError = APIConnectionError = APITimeoutError = Exception

# ===================== CONFIG =====================
BASE_DIR = Path(r"D:\Vald Data")
MODEL = "gpt-4o-mini"
TEMPERATURE = 0.3
MAX_RETRIES = 5
BACKOFF_BASE = 8
RATE_LIMIT_RPM = 1
SAFE_PACE_SECONDS = 70
BATCH_SUCCESS_SIZE = 5
BATCH_COOLDOWN_SECONDS = 180

LOG_CSV = BASE_DIR / "run_log.csv"
FAILED_LIST = BASE_DIR / "failed.txt"
SKIP_IF_MARKDOWN_EXISTS = True
FORCE = False

VALID_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
MARKDOWN_NAME_TEMPLATE = "{athlete} Analysis.md"

# ===================== INIT =====================
load_dotenv()
API_KEY = os.getenv("OPENAI_API_KEY")

client: Optional[OpenAI] = None

# Global logger callback
LOGGER_CALLBACK: Optional[Callable[[str, str], None]] = None

def set_logger_callback(callback: Optional[Callable[[str, str], None]]) -> None:
    global LOGGER_CALLBACK
    LOGGER_CALLBACK = callback

def log(tag: str, msg: str) -> None:
    if LOGGER_CALLBACK:
        LOGGER_CALLBACK(tag, msg)
    else:
        print(f"[{tag.upper()}] {msg}")

def init_client():
    global client
    if not API_KEY:
        log("ERROR", "OPENAI_API_KEY not set in environment (.env).")
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
    pairs: List[Tuple[str, Path]] = []
    for team_dir in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda x: x.name.lower()):
        subdirs = [c for c in team_dir.iterdir() if c.is_dir()]
        if subdirs:
            for athlete_dir in sorted(subdirs, key=lambda x: x.name.lower()):
                pairs.append((team_dir.name, athlete_dir))

    direct_athletes = [
        p for p in root.iterdir() if p.is_dir() and any((p / f).is_file() and (p / f).suffix.lower() in VALID_IMAGE_EXTS for f in os.listdir(p))
    ]
    for a in sorted(direct_athletes, key=lambda x: x.name.lower()):
        pairs.append(("", a))
    return pairs


def build_prompt(athlete_name: str) -> str:
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
    content = [{"type": "text", "text": prompt_text}]
    for p in image_paths:
        content.append({"type": "image_url", "image_url": {"url": b64_data_url(p)}})
    return content


def ensure_log_files():
    if not LOG_CSV.exists():
        with LOG_CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["athlete", "status", "started_at", "finished_at", "notes"])
    if not FAILED_LIST.exists():
        FAILED_LIST.write_text("", encoding="utf-8")


def append_log(athlete: str, status: str, started: float, finished: float, notes: str = ""):
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
        while self.calls and now - self.calls[0] > self.window:
            self.calls.popleft()
        if len(self.calls) >= self.rpm:
            to_sleep = self.window - (now - self.calls[0]) + 0.5
            if to_sleep > 0:
                log("SLEEP", f"Rate limiting: sleeping for {to_sleep:.2f}s")
                time.sleep(to_sleep)

    def mark(self):
        self.calls.append(time.time())


def call_with_retries(model: str, content, rl: RateLimiter):
    if not client:
        raise RuntimeError("OpenAI client not initialized.")
    attempts = 0
    last_err = None

    while attempts < MAX_RETRIES:
        attempts += 1
        try:
            rl.wait_for_slot()
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                temperature=TEMPERATURE,
            )
            rl.mark()
            jitter = random.uniform(5, 12)
            time.sleep(SAFE_PACE_SECONDS + jitter)
            msg = resp.choices[0].message.content if resp.choices else ""
            if not msg or not msg.strip():
                raise RuntimeError("Empty completion content.")
            return msg
        except RateLimitError as e:
            retry_after = None
            try:
                retry_after = float(getattr(getattr(e, "response", None), "headers", {}).get("Retry-After", 0))
            except Exception:
                retry_after = None
            backoff = max(SAFE_PACE_SECONDS + 10, BACKOFF_BASE * (2 ** (attempts - 1)))
            sleep_for = max(backoff, retry_after or 0)
            log("SLEEP", f"Rate limit error. Sleeping for {sleep_for:.2f}s")
            time.sleep(sleep_for)
            last_err = e
        except (APIConnectionError, APITimeoutError) as e:
            backoff = BACKOFF_BASE * (2 ** (attempts - 1)) + random.uniform(1.0, 4.0)
            log("SLEEP", f"Connection error. Retrying in {backoff:.2f}s")
            time.sleep(backoff)
            last_err = e
        except APIError as e:
            status = getattr(e, "status_code", None)
            if status and 500 <= int(status) < 600:
                backoff = BACKOFF_BASE * (2 ** (attempts - 1)) + random.uniform(1.0, 4.0)
                log("SLEEP", f"API error. Retrying in {backoff:.2f}s")
                time.sleep(backoff)
                last_err = e
            else:
                raise
        except Exception as e:
            backoff = BACKOFF_BASE * (2 ** (attempts - 1)) + random.uniform(1.0, 3.0)
            log("SLEEP", f"Unknown error. Retrying in {backoff:.2f}s")
            time.sleep(backoff)
            last_err = e
    raise RuntimeError(f"API failed after {MAX_RETRIES} attempts: {last_err}")


def write_markdown(folder: Path, team: str, athlete: str, images: List[Path], body_md: str) -> Path:
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


def process_athlete_folder(team: str, folder: Path, rl: RateLimiter) -> Optional[Path]:
    athlete = folder.name.strip()
    started = time.time()
    md_path = folder / MARKDOWN_NAME_TEMPLATE.format(athlete=athlete).strip()
    if SKIP_IF_MARKDOWN_EXISTS and not FORCE and md_path.exists():
        log("SKIP", f"Analysis.md already exists for {athlete}")
        append_log(athlete, "skipped_exists", started, time.time(), f"Analysis.md already exists | Team={team}")
        return md_path

    images = list_images(folder)
    log("SCAN", f"Team='{team if team else '(none)'}' | Athlete='{athlete}' | Images={len(images)}")
    if not images:
        log("FAIL", f"No images found for {athlete}")
        append_log(athlete, "no_images", started, time.time(), f"No images found | Team={team}")
        append_failure(athlete, f"No images found | Team={team}")
        return None

    prompt_text = build_prompt(athlete)
    user_content = build_user_content(prompt_text, images)

    try:
        completion_md = call_with_retries(MODEL, user_content, rl)
        out_path = write_markdown(folder, team, athlete, images, completion_md)
        append_log(athlete, "ok", started, time.time(), f"Saved: {out_path.name} | Team={team}")
        return out_path
    except Exception as e:
        log("FAIL", f"Failed to process {athlete}: {e}")
        append_log(athlete, "failed", started, time.time(), f"{e} | Team={team}")
        append_failure(athlete, f"{e} | Team={team}")
        return None


def run_chatgpt_generation(base_dir: str, log_callback: Optional[Callable[[str, str], None]] = None) -> bool:
    if log_callback:
        set_logger_callback(log_callback)

    init_client()

    base_path = Path(base_dir)
    log("INFO", f"Scanning base directory: {base_path}")

    # Update global paths
    global LOG_CSV, FAILED_LIST
    LOG_CSV = base_path / "run_log.csv"
    FAILED_LIST = base_path / "failed.txt"

    ensure_log_files()
    rl = RateLimiter(RATE_LIMIT_RPM)

    pairs = gather_team_athletes(base_path)
    if not pairs:
        log("WARN", "No team/athlete folders found.")
        return True

    current_team = None
    successes_since_break = 0
    total_success = 0
    total_processed = 0

    for team, athlete_dir in pairs:
        if team != current_team:
            current_team = team
            log("TEAM", f"{current_team if current_team else '(none)'}")

        log("RUN", f"{athlete_dir.name}")
        res = process_athlete_folder(team, athlete_dir, rl)
        total_processed += 1
        if res:
            log("DONE", f"{athlete_dir.name} -> {res.name}")
            successes_since_break += 1
            total_success += 1

            if successes_since_break >= BATCH_SUCCESS_SIZE:
                log("SLEEP", f"Completed {successes_since_break} markdowns. Cooling down for {BATCH_COOLDOWN_SECONDS}s...")
                time.sleep(BATCH_COOLDOWN_SECONDS)
                successes_since_break = 0
        else:
            log("FAIL", f"{athlete_dir.name}")

    log("INFO", f"Completed. Successful markdowns: {total_success}/{total_processed}")
    return True


def main():
    run_chatgpt_generation()

if __name__ == "__main__":
    main()
