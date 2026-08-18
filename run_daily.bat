@echo off
setlocal
cd /d "%~dp0"

if not exist secrets.env (
  echo [ERROR] secrets.env missing. Copy secrets.env.template and fill in values.
  exit /b 1
)

for /f "usebackq eol=# tokens=1,* delims==" %%a in ("secrets.env") do set "%%a=%%b"

if not exist "%DOWNLOADS_DIR%" mkdir "%DOWNLOADS_DIR%"

if exist crawl_daily.log (
  for %%F in (crawl_daily.log) do (
    if %%~zF GTR 5242880 (
      move /y crawl_daily.log crawl_daily.log.old >nul 2>&1
    )
  )
)

python crawl_full.py >> crawl_daily.log 2>&1
if errorlevel 1 goto crawl_failed

python sync_pipeline.py --prune >> crawl_daily.log 2>&1
if errorlevel 1 goto crawl_failed

echo [OK] Crawl + sync + backup + prune complete.
endlocal
exit /b 0

:crawl_failed
curl -s -X POST -H "Content-Type: application/json" -d "{\"content\":\"Comic crawler FAILED (exit %errorlevel%). Check run_daily.bat output.\"}" "%DISCORD_WEBHOOK_URL%"
endlocal
exit /b 2
