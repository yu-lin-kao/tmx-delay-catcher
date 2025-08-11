# delay\_catcher\_tmx o/

Hello~! This is **delay\_catcher**, currently specifically for the TMx project version: `delay_catcher_tmx` o/

TL;DR: This script runs on NUC, polls Asana for due date / delay reason changes, and logs them to Google Sheets. Start with:
```bash
source .venv/bin/activate && python events_poller.py
```

This is a little automation tool to track task delays in an Asana project.

Using the Asana API, it monitors changes to the task **due date** and **delay reason**, and reacts accordingly:
* When a task’s due date is postponed (or removed → meaning "Parked"), it **automatically increments the "Delay Count"** field on the task and **logs a record to a Google Sheet** for later analysis.
* When the delay reason is updated, it **logs a record to a Google Sheet** for later analysis.
* If a delay occurs but no delay reason is filled in, it **automatically adds `Awaiting identify`** to help prompt follow-up.
-> Google Sheet lives here: [https://docs.google.com/spreadsheets/d/10Xs4ChRlKc\_U737Z7R5nUQBdPtMHexhePv7kQ5YuTa4/edit?usp=sharing](https://docs.google.com/spreadsheets/d/10Xs4ChRlKc_U737Z7R5nUQBdPtMHexhePv7kQ5YuTa4/edit?usp=sharing)

Currently this is **running long-term on the ES NUC**, with flexible reuse for other projects. You can also try deploying it on **fly.io** (but read about the caveats below 👀).

---

## Table of Contents

1. [Notes & Requirements](#1-notes--requirements)
2. [Structure](#2-structure)
3. [NUC Operations](#3-nuc-operations)
4. [Future Improvements](#4-future-improvements)
5. [Pitfalls & Gotchas qwq](#5-pitfalls--gotchas-qwq)

---

## 1. Notes & Requirements

### Before running...

* Python 3.9+ is recommended
* Install packages from `requirements.txt`
* `.env` file should contain: (see .env.example for details)

  * `ASANA_TOKEN`
  * `ASANA_WORKSPACE_ID`
  * `ASANA_TMX_PROJECT_ID`
  * `SHEET_WEBHOOK_URL`
  * `KEEPALIVE_TOKEN` (optional)

### Data & Tracking Limitations

* **Database baseline was created on 2025/08/09** → delay records start from that date.
  > Asana stories API tells us *that* `due_on` changed, but **not exactly when** -> Infer delays by comparing snapshots.

* We use `due_on` (date-only), not `due_at` (datetime), so timezone or sub-day precision isn't supported yet.

---

## 2. Structure

### Main Code - delay_catcher_tmx.py

```
delay_catcher_tmx.py
├─ AsanaManager class
│  ├─ init_database()           # Initialize SQLite and create the tasks table.
│  ├─ get_project_tasks()       # Call the Asana API to fetch task data
│  ├─ increment_delay_count()   # When delayed, increment Delay Count by 1
│  ├─ update_delay_reason()     # When the delay reason changes, write it to Google Sheet
│  ├─ save_tasks_to_db()        # Write back the latest task data
│
├─ compare_and_update_tasks()   # Old data vs new data → determine delay / reason change
├─ main()                       # Main process entry point
```

### Files

```
tmx-delay-catcher/
├─ delay_catcher_tmx.py        # Main logic: fetch → compare → detect delay → update & log
├─ events_poller.py            # Event handling (webhook/polling → trigger main logic)
├─ webhook/                    # (optional) Local webhook tester
├─ requirements.txt            # Python dependencies
├─ fly.toml / Dockerfile       # For fly.io deployment
├─ logs/
│  ├─ poller.out.log
│  ├─ poller.err.log
├─ asana_tasks.db              # DB baseline for comparing delay state
├─ asana_events.db             # Raw webhook event archive (optional)
├─ .env                        # Local/fly.io/NUC environment variables
```

### Interaction flow

```
(Asana Webhook / Polling)
        ↓
events_poller.py
        ↓ Trigger
delay_catcher_tmx.py
    ├─ Read old data from asana_tasks.db
    ├─ Call Asana API to fetch latest data
    ├─ Compare differences:
    │    ├─ due_on delayed → Delay Count +1
    │    └─ Delay Reason changed
    ├─ Auto-fill "Awaiting identify" if necessary
    └─ Write back to asana_tasks.db & Log to Google Sheet
```


### Switching to another project?

* Create a **separate code branch** and edit:

  * `.env`: `ASANA_TMX_PROJECT_ID`, `SHEET_WEBHOOK_URL`
  * Rename all `tmx`-tagged filenames/log/db to match your new project code (ex. tmx -> tpr)
  * Also use separate DB files for each project to avoid cross-contamination


### Fly.io deployment (GitHub Actions + Fly.io)

* Create the app on Fly.io and set environment variables (same as .env).
* Configure fly.toml and Dockerfile.
* Set up a GitHub Actions workflow to auto-deploy updates to Fly.io.
* Once running, Fly.io directly receives Asana webhook pushes—no long polling needed.

---

## 3. NUC Operations

### Update code manually

```bash
cd ~/pm/automation/delay-catcher-tmx/tmx-delay-catcher
git fetch origin
git pull --ff-only

source .venv/bin/activate
pip install -r requirements.txt

sudo systemctl restart delay-poller.service
```

### View logs

```bash
tail -F logs/poller.out.log
tail -F logs/poller.err.log
```
---

## 4. Future Improvements

1. Current minor issues (low priority, not blocking)
    * Sometimes updated_by shows as “Unknown”.
    * When due_date and delay_reason change simultaneously, change_type may only record due_date_change.
2. Future visualization suggestions
    * Retrieve the Teams (custom field) from Asana and log it to db.
    * Update computed values (first_due_on, last_due_on, delay_duration) to DB (or compute afterward from the DB, depend on convenience).
    * Enable direct, real-time visualization from the DB
3. Updated_at timestamp improvement: Not standardized yet since ES is cross time-zone.
    * Consider converting updated_at to a unified timezone later
4. Duplicate execution protection
    * Add deduplication logic at DB or process level (idempotency key / execution guard)
    * Prevent double-recording if multiple instances are running
5. Multi-project support
    * Support monitoring multiple Asana projects in parallel
    * Could be via separate webhook services or multi-process handling
    * Each project should log to separate DB and log paths
6. Observability
    * Add a /health endpoint for basic health checks
    * Optionally export Prometheus metrics (e.g. delay count trends)
    * At minimum, support journalctl log scanning for alert keywords

---

## 5. Experience for references qwq

1. Duplicate executions → double records

    * Symptom: same delay gets logged twice (both Delay Reason and Delay Count)
    * Causes: multiple pollers running (NUC + fly.io + local), duplicate systemd services, etc.
    * Debug tips: check systemctl status, ps aux | grep python, and webhook subscriptions
    * Fix: ensure only one service is active at a time; add locking if needed

2.  Baseline setup was missing
    * Problem: without a DB snapshot, existing tasks don’t get logged when delayed for the first time
    * Fix: Created baseline on 2025/08/09
    * Limitation: Asana’s stories don’t include the timestamp of due date changes, so historical reconstruction isn’t possible

3. Asana pagination
    * Default limit = 50; larger projects (>500 tasks) weren’t being processed completely
    * Fix: Added manual pagination logic to fetch all tasks

4. Rate limit (429) triggered
    * Polling large projects frequently + multi-field updates triggered too many API calls
    * Fix:
        * Debounce events to avoid unnecessary full fetches
        * Use modified_since whenever applicable
        * Add retry with exponential backoff for 429 responses

5. Multi-select delay reason → untrackable
    * Asana API doesn’t reveal which values were changed in a multi-select field
    * Fix: Switched to single-select field for delay reason

6. Delay reason + due date → duplicate logs
When both fields changed, two logs were created → now merged into one with change_type=due_date_change+delay_reason_change

7. Why not smee.io?
smee.io can't be used directly as an Asana webhook target.
During webhook creation, Asana sends a special handshake request with an X-Hook-Secret header that must be echoed back exactly.
smee.io forwards the request to you, but does not forward your response headers back to Asana → handshake will always fail → Asana returns did not respond with the handshake secret

8. Why not fly.io?
fly.io introduces random cold starts, restarts, and delays (even with uptime monitoring)
Every restart resets the DB snapshot in memory, which may lead to incorrect delay detection unless handled manually

9. Why not Render?
Our Request Bot is already deployed on Render. Running another 24/7 service risks exceeding free-tier limits
Expect more bots/automation coming up, so we’re looking for an unrestricted platform

10. Google Apps Script (GAS) 
* Deployment must be via Web App, set to “Anyone with the link can access”
* Must re-deploy after every script change to update endpoint
* script.google.com/.../exec will 302 redirect to script.googleusercontent.com/... → use curl -L or trust client behavior
* Must send JSON (Content-Type: application/json); parse via JSON.parse(e.postData.contents)
* Avoid e.parameter and form-encoded bodies
* Use SpreadsheetApp.openById(...) — avoid openByUrl
* If openById fails, check deployment permissions or versioning
* Use LockService to avoid concurrent writes
* Add request_id to deduplicate
* Always return 200: ContentService.createTextOutput('OK')
* GAS has quota limits — batch writes where possible
* Keep sheet schema stable; if changed, update both code + README
* Add shared_secret field in payload and validate it server-side for basic auth
---

End of README, back to catching delays!
May your delays be rare, and your delay reasons always make sense qwq
If you spot a bug or have ideas, drop me (@yu-lin-kao) a message – this little catcher is always happy to learn o/
