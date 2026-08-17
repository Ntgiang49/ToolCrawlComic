# Plan: Comic Crawler Pipeline

## Components

1. `sync_pipeline.py` — single Python script (scan → upload → upsert → notify)
2. `.github/workflows/crawl-daily.yml` — updated YAML (add sync step + secrets)

## Dependencies

```
crawl-daily.yml → sync_pipeline.py → (R2 via AWS CLI, Supabase via REST, Discord via webhook)
```

## Order

1. Write `sync_pipeline.py` (all logic in one file)
2. Update `crawl-daily.yml` (add sync step, change `-f cbz` to `-f images`, add new secrets)
3. Test locally with `--dry-run`
4. Push

## Risks

| Risk | Mitigation |
|------|-----------|
| Crawler output folder names vary | Regex `\d+` for chapter number, slugify for title |
| R2 upload partial fail | DB insert skipped → re-run picks up |
| Supabase REST API auth | Service key in env, test with curl first |
| Discord embed too long | Truncate at 20 items |
