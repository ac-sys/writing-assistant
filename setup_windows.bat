@echo off
REM One-time setup for Writing Assistant on Windows (needs Python 3.10+ on PATH)
cd /d "%~dp0"
python -m venv .venv || goto :err
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu || goto :err
pip install -r requirements.txt || goto :err
python download_model.py || goto :err
echo.
echo Setup complete. Double-click run_windows.bat to start.
pause
exit /b 0
:err
echo Setup failed - see the messages above.
pause
exit /b 1
