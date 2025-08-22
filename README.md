# VALD Hub Scraper & Screenshot Automator

Automates login to VALD Hub, navigates to athlete profiles, and captures screenshots of:
- Countermovement Jump (modal accordions)
- Nordic (modal accordions)
- 20yd Sprint (modal accordions)
- 5-0-5 Drill (modal accordions)
- HumanTrak Overhead Squat & Lunge tiles (base + two metric dropdown states)

Screenshots are saved per athlete.

> **Output root:** `D:\Vald Data\<Athlete Name>\*.png`  
> **Session cache:** `auth_state.json` (speeds up subsequent runs)

---

## 1) Activate your virtual environment (Windows)

If you already have a venv named `env`, activate it:

```powershell
env\Scripts\activate
````

*(Optional)* If you **don’t** have a venv yet:

```powershell
python -m venv env
env\Scripts\activate
```

---

## 2) Install dependencies

```powershell
pip install -r requirements.txt
```

Install the Playwright browser binary (Chromium):

```powershell
python -m playwright install chromium
```

---

## 3) Create your `.env` file

Create a file named `.env` in the project root with the following keys:

```dotenv
EMAIL=your_email_here
PASSWORD=your_password_here
```

> Do **not** put quotes around the values.

---

## 4) Run the scraper

```powershell
python scrape_vald.py
```

**What it does:**

* Opens VALD Hub and logs in using `.env` credentials.
* Filters the Profiles page to selected teams (default: all “Fusion Soccer …” entries).
* For each real athlete (skips obvious “test” rows), opens the overview and:

  * Opens each modal (CMJ, Nordic, 20yd Sprint, 5-0-5 Drill) and screenshots **each accordion section**.
  * Screenshots **Overhead Squat** and **Lunge** cards for a base view and two metrics, while moving the mouse off the card to avoid tooltip overlays.
* Saves images under `D:\Vald Data\<Athlete Name>\`.

---

## (Optional) Clean up “Test” screenshots across all athlete folders

Some tiles include an initial “Test” section you may not want to keep.
Use the helper script below to delete these **specific** files from **every** athlete folder:

* `Countermovement_Jump_001.png`
* `20yd_Sprint_001.png`
* `5-0-5_Drill_001.png`
* `Nordic_001.png`

### Run

```powershell
python cleanup_vald_images.py
```

By default it scans `D:\Vald Data\`. You can override the root:

```powershell
python cleanup_vald_images.py --root "D:\Vald Data"
```

> This step is **optional** and permanently deletes the above files if found.

---

## How to change which **teams** are scraped (from “Fusion Soccer” to something else)

Open **`scrape_vald.py`** and find the block labeled:

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

### Option A — Change the prefix filter (all teams that **start with** your text)

Edit the regex on this line:

```python
fusion_teams = team_options.filter(has_text=re.compile(r"^Fusion Soccer"))
```

For example, to target all teams starting with “My Club”:

```python
fusion_teams = team_options.filter(has_text=re.compile(r"^My Club"))
```

### Option B — Select one or more **exact** team names

Replace the `fusion_teams` block with an explicit list:

```python
team_options = page.locator(".react-select__menu .react-select__option")
desired = [
    "My Club - 2010 Girls",
    "My Club - 2012 Boys",
    # add as many as you need
]
for nm in desired:
    page.get_by_role("option", name=nm).click()
    log("FILTER", f"Selected: {nm}")
```

After selecting teams, the script clicks away to close the dropdown and proceeds.

> Tip: If your Groups dropdown isn’t labeled “All Groups” in the UI, adjust the locator:
>
> ```python
> groups_dropdown = page.locator(".react-select__control", has_text="All Groups").first
> ```
>
> Change `"All Groups"` to whatever text your tenant shows.

---

## Troubleshooting

* **Stuck at login / session weirdness**
  Delete `auth_state.json` and run again.
* **Playwright browser not installed**
  Run `python -m playwright install chromium` **inside** your venv.
* **Permission/locking errors on `D:\Vald Data`**
  Close any app (e.g., image viewer) that is holding files open while the script runs or while cleanup executes.

---
