# VALD Scraper & Report Generators — (Team → Athlete)

This project automates three things:

1. **Scrape** each athlete’s test screenshots from VALD Hub into
   `D:\Vald Data\<Team Name>\<Athlete Name>\*.png`

2. **Clean** unwanted “\_001” screenshots and remove **empty athlete/team folders**

3. **Generate reports**

   * `chatgpt_generate.py` → reads images and writes **Analysis.md** (per athlete)
   * `grok_generate.py` → reads **Analysis.md** and writes **8-week training program .docx** (per athlete)

---

## 1) Requirements

* **Python 3.10+**
* **Node/Webkit for Playwright browsers**

  ```bash
  pip install -r requirements.txt  # if you keep one
  playwright install
  ```
* Python packages:

  * `playwright`, `python-dotenv`
  * `openai` (used both for OpenAI and xAI “OpenAI-compatible” clients)
  * `python-docx` (for .docx output)
* A `.env` file (see below)

---

## 2) Environment (.env)

Create a `.env` in the project root:

```ini
# VALD Hub login
EMAIL=you@example.com
PASSWORD=your_vald_password

# OpenAI for Analysis (chatgpt_generate.py)
OPENAI_API_KEY=sk-...

# xAI for Training Program (grok_generate.py)
XAI_API_KEY=xai-...
```

---

## 3) Output structure

All scripts assume a single base folder (default `D:\Vald Data`) with this shape:

```
D:\Vald Data\
  ├─ <Team A>\
  │   ├─ <Athlete 1>\   # images (.png) + "<Athlete 1> Analysis.md" + "<Athlete 1> 8 Weeks Training Program.docx"
  │   └─ <Athlete 2>\
  └─ <Team B>\
      └─ <Athlete N>\
```

You can change the base path in each script via `--base-dir` (generators) or `--root` (cleanup) or by editing the constant in `scrape_vald.py`.

---

## 4) `scrape_vald.py` — Scrape VALD screenshots

### What it captures

Per athlete (on the Overview page):

* **Modals (accordion screenshots)**

  * Countermovement Jump (CMJ) — \~6 sections
  * Nordic — \~7 sections
  * 20yd Sprint — \~2 sections
  * 5-0-5 Drill — \~2 sections

* **HumanTrak cards (dropdown metrics, 1 shot each)**

  * **Overhead Squat**:

    * Avg Peak Knee Flexion — L/R
    * Avg Hip Adduction at Peak Knee Flexion — L/R
    * Avg Ankle Dorsiflexion at Peak Knee Flexion — L/R
  * **Lunge**: same 3 metrics

The script uses **pixel hashing** to avoid duplicate images and robust waits for charts/menus.

### Interactive team selection (what you’ll be asked)

When you run the scraper, you’ll see:

```
=== Team selection ===
1) Start-text mode (e.g., 'KC Fusion' -> process ALL teams that start with it)
2) Explicit list (paste comma-separated names OR path to a .txt with one per line)
Pick 1 or 2 (default 1):
```

* **Option 1 (Start-text / prefix)**
  Type a word/phrase that the team **starts with**, e.g. `KC Fusion`.
  The script will scrape **all teams whose names start with that text**.

* **Option 2 (Explicit list)**
  Paste a comma-separated list:
  `KC Fusion 07/08G Navy GA, KC Fusion 09G Navy, KC Fusion 10G Navy`
  **Or** provide a path to a `.txt` file with one team name per line.

### Guarantees about team isolation

* Before each team is processed, we **clear** any previous selection chips in the dropdown.
* We **re-open** the dropdown and select **exactly one** team.
* We verify we’re on the Profiles page and wait for **network idle**.
* This prevents “players leaking into the next team”.

### After each team

The script **clicks the dropdown’s clear indicator (×)** or removes chips to ensure no residual filters remain before moving to the next team.

### Run it

```bash
python scrape_vald.py
```

Tips:

* Toggle **headless**/watch mode by setting `HEADLESS = False` in the script.
* You can tune waits/timeouts near the top of the file if your network is slow.
* Login is cached in `auth_state.json` between runs.

---

## 5) `cleanup_vald_images.py` — Remove first screenshots & empty folders

This script does **two things**:

1. **Delete these “test” first screenshots** from every athlete folder (if present):

   * `Countermovement_Jump_001.png`
   * `20yd_Sprint_001.png`
   * `5-0-5_Drill_001.png`
   * `Nordic_001.png`
2. **Remove empty athlete folders** (and optionally empty team folders)

### Usage

```bash
# Default root: D:\Vald Data
python cleanup_vald_images.py

# Choose a different root
python cleanup_vald_images.py --root "D:\Vald Data"

# Dry run (prints what would be removed, but does not delete)
python cleanup_vald_images.py --dry-run

# Only affect specific teams (exact names, comma-separated)
python cleanup_vald_images.py --teams "KC Fusion 10G Navy,KC Fusion 12B Gold"

# Also prune team folder if it ends up empty
python cleanup_vald_images.py --prune-empty-teams
```

The script prints counts for teams scanned, athlete folders checked, files deleted, and how many athlete/team folders were removed.

---

## 6) `chatgpt_generate.py` — Build **Analysis.md** from images (OpenAI)

Reads all PNGs for each athlete, sends them to an OpenAI vision model, and writes:

```
< Athlete Name > Analysis.md
```

into that athlete’s folder.

### Team-aware traversal & console output

* Walks **Base → Team → Athlete** and processes each athlete folder containing images.
* For each athlete it prints: **team name, athlete name, and number of images used**.

### Pacing / cooldowns

* Strict pacing to avoid rate limits.
* **After every 5 athletes**, the script **pauses 3 minutes** automatically.
* Additional built-in per-request pacing is included.

### Typical run

```bash
python chatgpt_generate.py
# optional
python chatgpt_generate.py --base-dir "D:\Vald Data"
```

Key behavior:

* Skips an athlete if their `Analysis.md` already exists (configurable in the script).
* Writes a CSV log and a `failed.txt` list in the base folder.

> Make sure `OPENAI_API_KEY` is set in `.env`.

---

## 7) `grok_generate.py` — Build **8-week program .docx** from Analysis.md (xAI)

Reads:

```
< Athlete Name > Analysis.md
```

and writes:

```
< Athlete Name > 8 Weeks Training Program.docx
```

in the same athlete folder, using **xAI (Grok) via OpenAI-compatible API**.

### Team-aware traversal

* Walks **Base → Team → Athlete**
* For each athlete, it looks for **exact** `"<Athlete> Analysis.md"` first,
  otherwise falls back to the first `* Analysis.md`.

### Run it

```bash
python grok_generate.py
# or
python grok_generate.py --base-dir "D:\Vald Data" --model grok-3-mini --rpm 2
```

It logs to `run_grok_log.csv` and `failed_grok.txt` in the base directory.

> Make sure `XAI_API_KEY` is set in `.env`.

---

## 8) FAQ / Troubleshooting

**Q: Team A’s players show up when scraping Team B.**
A: The scraper explicitly **clears** chips/selection and **re-ensures** the Profiles page before switching teams. If you still see this, increase delays:

* `page.wait_for_load_state("networkidle")` is already used after filter changes.
* You can add a small extra pause after setting the filter.

**Q: Dropdown didn’t open / ‘Could not set filter to ONLY ...’.**
A: The script scrolls to the top and uses robust selectors for the **react-select** menu. If your UI is slow, increase the dropdown timeout / retries in `open_groups_dropdown`.

**Q: I want to watch what’s happening.**
A: Set `HEADLESS = False` and optionally `slow_mo` in `scrape_vald.py` for slower, visible interactions.

**Q: The site uses a cookie banner.**
A: The scraper auto-accepts it (`#rcc-confirm-button`) when present.

**Q: Where are my screenshots?**
A: `D:\Vald Data\<Team>\<Athlete>\*.png` (configurable via `OUTPUT_DIR` or CLI in cleanup/generators).

---

## 9) One-liners

```bash
# Scrape (interactive team selection)
python scrape_vald.py

# Clean first screenshots + remove empty athlete folders (dry run first)
python cleanup_vald_images.py --dry-run
python cleanup_vald_images.py --prune-empty-teams

# Generate Analysis.md from images (pauses 3 min after every 5 athletes)
python chatgpt_generate.py

# Generate 8-week training program .docx from Analysis.md
python grok_generate.py
```

---

**Tip:** Commit your scripts and a sample `.env.example` (without secrets) so future runs are plug-and-play.
