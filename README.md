# VALD Hub → Insights → 8-Week Programs (Windows)

Automate the full pipeline from **VALD Hub screenshots** → **ChatGPT analysis** → **Grok 8-week training programs**.

- ✅ Scrape athlete screenshots (CMJ, Nordic, 20yd Sprint, 5-0-5, Overhead Squat, Lunge)
- ✅ (Optional) Clean out “test” screenshots
- ✅ Generate **per-athlete analysis** with **GPT-4o mini** (Markdown)
- ✅ Generate **8-week training program** with **xAI Grok 3 Mini** (Word `.docx`)

**Output layout**

```

D:\Vald Data
├─ Athlete A
│   ├─ \*.png (19 images after cleanup)
│   ├─ Athlete A Analysis.md
│   └─ Athlete A 8 Weeks Training Program.docx
└─ Athlete B\\

````

---

## 🚀 What’s new (compared to the previous version)

- **Accordion-based screenshots** for CMJ/Nordic/Sprint/5-0-5 with **patient loading**  
  (stable detection, discovery timeout, settle delays)
- **Device-scale + larger viewport** for sharper images
- **HumanTrak tiles**: Overhead Squat & Lunge (base + 2 metrics) with **mouse moved off** to avoid tooltips
- **Cleanup script** to remove 4 test screenshots (`*_001.png`) in all athlete folders
- **Flexible image intake** (no strict file names; uses whatever images remain)
- **ChatGPT analysis**: one request per athlete (19 images), **11–16 yrs female** cohort (no per-athlete age scraping)
- **Grok 8-week program** generated from the analysis to a **.docx** file
- **Robust rate-limiting** (2 requests/min) + retries and backoff
- **Alphabetical processing**, logs (`run_log.csv`, `run_grok_log.csv`) and **failed lists** for easy re-runs
- **Skip/overwrite controls** for outputs

---

## 🧰 Prerequisites

- **Windows 10/11**
- **Python 3.10+**
- **PowerShell** terminal
- Accounts & keys:
  - VALD Hub email + password
  - **OpenAI API key** for ChatGPT (GPT-4o mini)
  - **xAI API key** for Grok (grok-3-mini)

---

## 🔧 Setup (one-time)

Open PowerShell in your project folder and run:

```powershell
# 1) Create & activate a virtual environment
python -m venv env
env\Scripts\activate

# 2) Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3) Install Playwright browsers (Chromium)
python -m playwright install
````

**`requirements.txt` (example)**

```
playwright
python-dotenv
openai
python-docx
```

> If you don’t have a `requirements.txt`, just run:
> `pip install playwright python-dotenv openai python-docx`

---

## 🔐 Create your `.env`

Create a file named `.env` in the project root:

```dotenv
# VALD Hub login
EMAIL=your_email_here
PASSWORD=your_password_here

# OpenAI (ChatGPT)
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx

# xAI (Grok)
XAI_API_KEY=xai-xxxxxxxxxxxxxxxx
```

---

## ▶️ Run the pipeline

### 1) Scrape VALD → athlete screenshots

```powershell
env\Scripts\activate
python scrape_vald.py
```

**What it does**

* Logs into VALD Hub using `.env`.
* On **Profiles**, selects all matching teams (default: any name starting with **“Fusion Soccer”**).
* For each athlete (skips obvious test rows), opens the overview and:

  * Opens modals (CMJ, Nordic, 20yd Sprint, 5-0-5) and screenshots **each accordion section**.
  * Captures **Overhead Squat** & **Lunge** cards (base + 2 metrics) while **moving the mouse off** to avoid tooltips.
* Saves images under `D:\Vald Data\<Athlete>\*.png`.

> Session cache `auth_state.json` speeds up subsequent runs.

---

### (Optional) 2) Clean out test screenshots

Removes these **four** files from **every** athlete folder:

* `Countermovement_Jump_001.png`
* `20yd_Sprint_001.png`
* `5-0-5_Drill_001.png`
* `Nordic_001.png`

```powershell
python cleanup_vald_images.py --root "D:\Vald Data"
```

> After this, each folder typically has **19 images** used for the analysis.

---

### 3) Generate per-athlete analysis with ChatGPT (GPT-4o mini)

```powershell
python chatgpt_generate.py
```

**Details**

* Model: **gpt-4o-mini** (vision)
* Cohort fixed at **11–16 years old female**
* Sends **all images in the folder** (post-cleanup) in a **single request**
* Output: `{Athlete} Analysis.md` in the athlete’s folder
* Rate limit: **2 RPM**, with extra pacing + retries
* Logs:

  * `D:\Vald Data\run_log.csv`
  * `D:\Vald Data\failed.txt`

**Behavior**

* Skips a folder if `{Athlete} Analysis.md` already exists (configurable in script).
* Flexible: continues even if some images are missing.

---

### 4) Generate 8-week training program with Grok → `.docx`

```powershell
python grok_generate.py
```

**Details**

* Model: **grok-3-mini** (xAI, OpenAI-compatible API)
* Reads `{Athlete} Analysis.md` as input context
* Writes `{Athlete} 8 Weeks Training Program.docx` (no tables, structured headings)
* Weekly plan grouped as **Weeks 1–2**, **Weeks 3–4**, **Weeks 5–6**, **Weeks 7–8**
* Rate limit: **2 RPM**
* Logs:

  * `D:\Vald Data\run_grok_log.csv`
  * `D:\Vald Data\failed_grok.txt`

**CLI options**

```powershell
# Dry run (no API calls)
python grok_generate.py --dry-run

# Change base directory
python grok_generate.py --base-dir "E:\AnotherRoot"

# Change model / rate
python grok_generate.py --model grok-3-mini --rpm 2
```

---

## 🔄 Change which **teams** are scraped (Fusion Soccer → yours)

Open **`scrape_vald.py`** and find:

```python
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
```

**Option A — Prefix filter**
Change the regex to match your prefix:

```python
fusion_teams = team_options.filter(has_text=re.compile(r"^My Club"))
```

**Option B — Exact names**
Replace the block with a fixed list:

```python
team_options = page.locator(".react-select__menu .react-select__option")
desired = [
    "My Club - 2010 Girls",
    "My Club - 2012 Boys",
]
for nm in desired:
    page.get_by_role("option", name=nm).click()
    log("FILTER", f"Selected: {nm}")
```

> If your dropdown isn’t labeled **“All Groups”**, adjust:
>
> ```python
> groups_dropdown = page.locator(".react-select__control", has_text="All Groups").first
> ```
>
> Replace `"All Groups"` with your UI text.

---

## 🗂 Script summary

| Script                   | Purpose                                                                                     | Input                               | Output                                           |
| ------------------------ | ------------------------------------------------------------------------------------------- | ----------------------------------- | ------------------------------------------------ |
| `scrape_vald.py`         | Login, filter teams, open each athlete, screenshot all accordion sections + HumanTrak tiles | `.env` (EMAIL, PASSWORD)            | `D:\Vald Data\{Athlete}\*.png`                   |
| `cleanup_vald_images.py` | Remove 4 test screenshots (`*_001.png`) from each folder                                    | `--root` (default `D:\Vald Data`)   | Folders trimmed to 19 images                     |
| `chatgpt_generate.py`    | One analysis per athlete from all images using GPT-4o mini                                  | `.env` (OPENAI\_API\_KEY)           | `{Athlete} Analysis.md` + logs                   |
| `grok_generate.py`       | 8-week training plan from the analysis with Grok 3 Mini                                     | `.env` (XAI\_API\_KEY), Analysis.md | `{Athlete} 8 Weeks Training Program.docx` + logs |

---

## 🧪 Quick smoke test

```powershell
env\Scripts\activate
python -m playwright install
python scrape_vald.py
python cleanup_vald_images.py --root "D:\Vald Data"
python chatgpt_generate.py
python grok_generate.py
```

Open an athlete folder and confirm:

* 19 images
* `{Athlete} Analysis.md`
* `{Athlete} 8 Weeks Training Program.docx`

---

## 🆘 Troubleshooting

* **Login/session weirdness** → delete `auth_state.json` and re-run.
* **Playwright missing** → `python -m playwright install` (inside your venv).
* **Tooltip overlays in screenshots** → handled automatically (mouse moves off tile).
* **No images found** → check that cleanup didn’t remove everything; scraper logs show what was captured.
* **Rate limit / timeouts** → both generators use retries and pacing; reduce RPM or increase delays in code if needed.
* **Missing analysis for Grok** → ensure `{Athlete} Analysis.md` exists in the folder.

---

## ✅ TL;DR (commands)

```powershell
# One-time setup
python -m venv env
env\Scripts\activate
pip install -r requirements.txt
python -m playwright install

# .env with EMAIL, PASSWORD, OPENAI_API_KEY, XAI_API_KEY

# 1) Scrape
python scrape_vald.py

# 2) (Optional) Remove test screenshots
python cleanup_vald_images.py --root "D:\Vald Data"

# 3) ChatGPT analysis (.md)
python chatgpt_generate.py

# 4) Grok 8-week program (.docx)
python grok_generate.py
```


