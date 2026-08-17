# Tasks: Comic Crawler Pipeline

- [ ] Task 1: Write `sync_pipeline.py`
  - Acceptance: Script scans downloads/, uploads new images to R2, upserts Supabase, sends Discord webhook
  - Verify: `python sync_pipeline.py --dry-run` lists actions without executing
  - Files: `sync_pipeline.py`

- [ ] Task 2: Update `crawl-daily.yml`
  - Acceptance: Workflow runs crawler with `-f images`, then `sync_pipeline.py`, passes all 7 secrets as env vars
  - Verify: YAML syntax valid, `workflow_dispatch` manual trigger works
  - Files: `.github/workflows/crawl-daily.yml`

- [ ] Task 3: Test + push
  - Acceptance: Commit on master, push, secrets set in GitHub
  - Verify: Manual workflow dispatch → green run
  - Files: none (GitHub UI for secrets)
