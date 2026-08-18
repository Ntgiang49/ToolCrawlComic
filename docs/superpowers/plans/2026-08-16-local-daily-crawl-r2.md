# Local Daily Comic Crawl → R2/Supabase/Discord Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crawl comic updates locally every day at 07:00, push new chapters to R2, notify Discord daily.

**Architecture:** nettruyen.gg returns 403 to GitHub runner IPs (verified: runner=403, local PC=200). Crawl moves to local machine: `run_daily.bat` (Task Scheduler 07:00) runs crawler → `sync_pipeline.py` pushes R2 + Supabase + Discord. Supabase becomes optional; Discord notifies daily even with 0 new chapters.

**Tech Stack:** Python 3.12, requests, boto3 (`s3.upload_file` to R2), Windows Task Scheduler, Windows curl.

## Global Constraints

- Test runner: `python -m unittest` (repo style, unittest not pytest)
- New pip dependency: `boto3>=1.34.0` only (chosen over AWS CLI — no admin install, self-contained)
- Comic URL control point = `library.json` (already built: `python main.py "<URL>"` adds/updates, `main.py update` skips existing chapters)
- `D:\light-story` = local download folder (crawler output, synced to R2)
- Chinese/Vietnamese titles must survive bat encoding — bat saves as ASCII, content from `secrets.env` (UTF-8 read by `for /f` on Windows 10+)

---

### Task 1: Make Supabase optional in `sync_pipeline.py`

**Files:**
- Modify: `sync_pipeline.py` (add `sb_enabled()`; guard DB ops in `main()`)
- Test: `test_sync_pipeline.py`

**Interfaces:**
- Consumes: existing `SUPABASE_URL`, `SUPABASE_KEY`, `get_or_create_story`, `chapter_exists`, `supabase_post`, `upload_to_r2`
- Produces: `sb_enabled() -> bool` — later tasks rely on it; main-loop DB guards.

- [ ] **Step 1: Write the failing tests**

Append to `test_sync_pipeline.py`:

```python
import sync_pipeline as sp

class TestSupabaseOptional(unittest.TestCase):
    def test_sb_enabled_false_when_no_keys(self):
        sp.SUPABASE_URL = ""
        sp.SUPABASE_KEY = ""
        self.assertFalse(sp.sb_enabled())

    def test_sb_enabled_true_when_keys(self):
        sp.SUPABASE_URL = "https://x.supabase.co"
        sp.SUPABASE_KEY = "k"
        self.assertTrue(sp.sb_enabled())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_sync_pipeline`
Expected: FAIL — `AttributeError: module 'sync_pipeline' has no attribute 'sb_enabled'`

- [ ] **Step 3: Implement `sb_enabled()`**

In `sync_pipeline.py`, after `DRY_RUN = ...` (line 25):

```python
def sb_enabled() -> bool:
    """Supabase DB ops only when URL + service key present."""
    return bool(SUPABASE_URL and SUPABASE_KEY)
```

- [ ] **Step 4: Guard DB ops in `main()`**

Replace lines 286-289:

```python
        story_id = get_or_create_story(title, slug, cover_url)
        if not story_id:
            print("  ERROR: Could not get/create story")
            continue
```

with:

```python
        # ponytail: no Supabase → dedupe relies on aws s3 sync idempotence +
        # local skip-existing. Ceiling: re-upload if R2 objects deleted.
        story_id = get_or_create_story(title, slug, cover_url) if sb_enabled() else None
        if sb_enabled() and not story_id:
            print("  ERROR: Could not get/create story")
            continue
```

Replace lines 294-296:

```python
            # Check DB first (source of truth)
            if not DRY_RUN and chapter_exists(story_id, ch_num):
                continue  # silent skip — expected for existing chapters
```

with:

```python
            # Check DB first (source of truth)
            if sb_enabled() and not DRY_RUN and chapter_exists(story_id, ch_num):
                continue  # silent skip — expected for existing chapters
```

Replace line 315 guard:

```python
            if not DRY_RUN:
```

with:

```python
            if sb_enabled() and not DRY_RUN:
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m unittest test_sync_pipeline`
Expected: PASS (both new tests + existing 2 test classes)

- [ ] **Step 6: Commit**

```bash
git add sync_pipeline.py test_sync_pipeline.py
git commit -m "feat: make Supabase optional in sync pipeline"
```

---

### Task 2: Discord notifies daily (including 0 new chapters)

**Files:**
- Modify: `sync_pipeline.py` (`send_discord`, `main()` end)
- Test: `test_sync_pipeline.py`

**Interfaces:**
- Consumes: `summary: list[dict]` items `{"comic": str, "chapter": str}`
- Produces: `build_discord_payload(summary: list[dict]) -> dict` — pure payload builder used by `send_discord`.

- [ ] **Step 1: Write the failing tests**

Append to `test_sync_pipeline.py`:

```python
class TestDiscordPayload(unittest.TestCase):
    def test_payload_empty_summary(self):
        payload = sp.build_discord_payload([])
        desc = payload["embeds"][0]["description"]
        self.assertEqual(desc, "No new chapters today")

    def test_payload_groups_by_comic(self):
        payload = sp.build_discord_payload([
            {"comic": "A", "chapter": "Ch 1"},
            {"comic": "A", "chapter": "Ch 2"},
            {"comic": "B", "chapter": "Ch 1"},
        ])
        fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
        self.assertEqual(fields["A"], "Ch 1, Ch 2")
        self.assertEqual(fields["B"], "Ch 1")

    def test_payload_reports_count(self):
        payload = sp.build_discord_payload([{"comic": "A", "chapter": "Ch 1"}])
        self.assertEqual(payload["embeds"][0]["description"], "Uploaded 1 new chapter(s)")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest test_sync_pipeline`
Expected: FAIL — `AttributeError: module 'sync_pipeline' has no attribute 'build_discord_payload'`

- [ ] **Step 3: Refactor `send_discord` → split payload builder**

Replace lines 213-252 (`send_discord` body) with:

```python
def build_discord_payload(summary: list[dict]) -> dict:
    """Pure Discord embed payload from sync summary."""
    comics: dict[str, list[str]] = {}
    for item in summary:
        comics.setdefault(item["comic"], []).append(item["chapter"])

    fields = []
    for name, chapters in list(comics.items())[:20]:
        fields.append(
            {"name": name, "value": ", ".join(chapters[:10]), "inline": False}
        )

    if summary:
        description = f"Uploaded {len(summary)} new chapter(s)"
    else:
        description = "No new chapters today"

    return {
        "embeds": [
            {
                "title": "📚 Comic Crawler Report",
                "description": description,
                "color": 5763719,
                "fields": fields,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }


def send_discord(summary: list[dict]) -> None:
    """Send Discord webhook with upload summary (always sends, even empty)."""
    if not DISCORD_WEBHOOK:
        print("DISCORD_WEBHOOK_URL not set, skipping notification")
        return

    payload = build_discord_payload(summary)

    if DRY_RUN:
        print(f"[DRY-RUN] Discord payload:\n{json.dumps(payload, indent=2)}")
        return

    resp = requests.post(DISCORD_WEBHOOK, json=payload)
    if resp.status_code not in (200, 204):
        print(
            f"Discord webhook failed: {resp.status_code} {resp.text}",
            file=sys.stderr,
        )
```

- [ ] **Step 4: Always notify in `main()`**

Replace lines 347-351:

```python
    if summary:
        send_discord(summary)
        print("Discord notification sent")
    else:
        print("No new chapters — skipping Discord")
```

with:

```python
    send_discord(summary)
    print("Discord notification sent")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m unittest test_sync_pipeline`
Expected: PASS (all 4 test classes)

- [ ] **Step 6: Verify dry-run end-to-end (manual)**

Run: `python sync_pipeline.py --dry-run`
Expected: prints DRY RUN, lists comics/chapters found in `downloads/`, prints `[DRY-RUN] Discord payload` with either "Uploaded N new chapter(s)" or "No new chapters today"

- [ ] **Step 7: Commit**

```bash
git add sync_pipeline.py test_sync_pipeline.py
git commit -m "feat: discord notifies daily even with zero new chapters"
```

---

### Task 3: `run_daily.bat` + `secrets.env.template` + `.gitignore`

**Files:**
- Create: `run_daily.bat`, `secrets.env.template`, `.gitignore`
- Verify: `aws --version` (AWS CLI must exist locally — pipeline shells out to it)

**Interfaces:**
- Consumes: `secrets.env` keys (below), `main.py update`, `sync_pipeline.py`
- Produces: daily driver executed by Task Scheduler; exit code 0 = crawl+sync ok, 1 = config missing, 2 = crawl failed (Discord fail notice sent).

- [ ] **Step 1: Create `secrets.env.template`**

```text
# R2 (Cloudflare)
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
R2_PUBLIC_URL=
# Discord
DISCORD_WEBHOOK_URL=
# Supabase (optional — leave empty to skip DB, R2-only mode)
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
# Local download folder (crawler output, synced to R2)
DOWNLOADS_DIR=D:\light-story
```

- [ ] **Step 2: Create `.gitignore`**

```text
secrets.env
downloads/
```

- [ ] **Step 3: Create `run_daily.bat`**

```bat
@echo off
setlocal
cd /d "%~dp0"

if not exist secrets.env (
  echo [ERROR] secrets.env missing. Copy secrets.env.template and fill in values.
  exit /b 1
)

for /f "usebackq eol=# tokens=1,* delims==" %%a in ("secrets.env") do set "%%a=%%b"

if not exist "%DOWNLOADS_DIR%" mkdir "%DOWNLOADS_DIR%"

python main.py update -o "%DOWNLOADS_DIR%" -f images
if errorlevel 1 goto crawl_failed

python sync_pipeline.py
if errorlevel 1 goto crawl_failed

echo [OK] Crawl + sync complete.
endlocal
exit /b 0

:crawl_failed
curl -s -X POST -H "Content-Type: application/json" -d "{\"content\":\"Comic crawler FAILED (exit %errorlevel%). Check run_daily.bat output.\"}" "%DISCORD_WEBHOOK_URL%"
endlocal
exit /b 2
```

- [ ] **Step 4: Verify env parsing + dry run**

Copy template: `copy secrets.env.template secrets.env`, fill real values (same 8 keys as GitHub secrets + `DOWNLOADS_DIR`).

Run: `run_daily.bat` — expected flow: crawler parses comic (200 OK local), downloads new chapters to `D:\light-story\<title>\Chapter NNN\`, then `sync_pipeline.py` prints upload lines, then "Discord notification sent".

- [ ] **Step 5: Verify boto3 upload path**

Run: `pip install boto3` (done), `python -m unittest test_sync_pipeline` → 7 PASS.
Live upload verified in Task 4 (manual trigger → Discord ping confirms).

- [ ] **Step 6: Verify Discord fail path (manual, optional)**

Run: `set DISCORD_WEBHOOK_URL=... & python sync_pipeline.py` with bad R2 keys → confirm webhook receives failure? (Optional — skip if timeboxed.)

- [ ] **Step 7: Commit**

```bash
git add run_daily.bat secrets.env.template .gitignore
git commit -m "feat: add local daily run script with env config"
```

---

### Task 4: Register Task Scheduler + end-to-end verify

**Files:** none (system change)

**Interfaces:** Consumes `run_daily.bat` path `D:\01_Projects\Tool_crawl_comic\run_daily.bat`.

- [ ] **Step 1: Register daily task at 07:00**

```bat
schtasks /create /f /tn ComicCrawlDaily /tr "cmd /c D:\01_Projects\Tool_crawl_comic\run_daily.bat" /sc daily /st 07:00
```

Expected: `SUCCESS: The scheduled task "ComicCrawlDaily" has been created.`

- [ ] **Step 2: Manual trigger test**

```bat
schtasks /run /tn ComicCrawlDaily
```

Wait 2-5 min, check Discord channel: daily report embed appears ("Uploaded N new chapter(s)" or "No new chapters today").

- [ ] **Step 3: Verify task list**

Run: `schtasks /query /tn ComicCrawlDaily`
Expected: status Ready, next run time = tomorrow 07:00.

- [ ] **Step 4: Commit (no code change — skip if nothing to commit)**

---

## Self-Review

1. **Spec coverage:** URL control = existing `main.py <URL>`/`library.json` (Global Constraints, no task needed — verified code exists); local crawl + R2 push from `D:\light-story` = Task 3 (env `DOWNLOADS_DIR`); Task Scheduler 07:00 = Task 4; Discord daily = Task 2; Supabase kept+optional = Task 1. No gaps.
2. **Placeholder scan:** all steps carry full code + exact commands; no TBDs.
3. **Type consistency:** `sb_enabled()` used in Task 1 only; `build_discord_payload(summary)` defined Task 2, consumed by `send_discord` in same task; `summary` item shape `{"comic","chapter"}` consistent with existing code.
