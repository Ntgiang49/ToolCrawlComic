# CLAUDE.md

See [AGENTS.md](file:///D:/01_Projects/Tool_crawl_comic/AGENTS.md) for full project architecture, coding conventions, and operational guidelines.

## Quick Commands
- **Test Suite:** `python -m unittest discover -s . -p "test_*.py"`
- **Crawl Comic:** `python main.py "<URL>" -f images -o downloads`
- **Batch Update:** `python main.py update -o downloads`
- **Cloud Sync Dry-Run:** `python sync_pipeline.py --dry-run`
- **Cloud Sync & Prune:** `python sync_pipeline.py --prune`
- **Daily Batch Run:** `run_daily.bat`
