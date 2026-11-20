# FreshFold Laundry Tracker

A complete Ionic/Angular frontend with a FastAPI backend and a portable SQLite database.

## Requirements

- Node.js and npm
- Python 3.11 or newer

## First-time setup

From the repository root in PowerShell:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
cd .\laudryTracker
npm ci
cd ..
```

The repository includes `database/laundry.db`. It contains the complete SQLite schema and can be copied as-is to another PC.

## Run the complete app

Terminal 1:

```powershell
$env:LAUNDRY_DB_ENGINE = "sqlite"
$env:LAUNDRY_DB_PATH = "$PWD\database\laundry.db"
.\venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
cd .\laudryTracker
npm start
```

Open the URL printed by Ionic, usually `http://localhost:8100`.

API documentation: `http://127.0.0.1:8000/docs`

## Portable setup script

After the first checkout, run:

```powershell
.\setup.ps1
.\start.ps1
```

## Database

The committed SQLite database is [database/laundry.db](./database/laundry.db). The schema export is [database/schema.sql](./database/schema.sql).

For MySQL, set `LAUNDRY_DB_ENGINE=mysql` and the `LAUNDRY_DB_HOST`, `LAUNDRY_DB_PORT`, `LAUNDRY_DB_NAME`, `LAUNDRY_DB_USER`, and `LAUNDRY_DB_PASSWORD` environment variables. The SQLite database is the zero-XAMPP setup and does not require MySQL.

## Verify

```powershell
py -m unittest discover -s tests
cd .\laudryTracker
npm run build
cd ..
```
