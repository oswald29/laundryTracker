$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Set-Location $root
$env:LAUNDRY_DB_ENGINE = "sqlite"
$env:LAUNDRY_DB_PATH = Join-Path $root "database\laundry.db"

$backendCommand = "Set-Location '$root'; `$env:LAUNDRY_DB_ENGINE='sqlite'; `$env:LAUNDRY_DB_PATH='$env:LAUNDRY_DB_PATH'; .\venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $backendCommand

Set-Location (Join-Path $root "laudryTracker")
npm start
