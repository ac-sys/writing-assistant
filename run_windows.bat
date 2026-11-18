@echo off
cd /d "%~dp0"
call .venv\Scripts\activate
echo Writing Assistant running at http://localhost:8200  (press Ctrl+C to stop)
start "" http://localhost:8200
uvicorn app.main:app --host 127.0.0.1 --port 8200
