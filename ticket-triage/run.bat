@echo off
REM Windows: double-click or run "run.bat". Add --mock to test without a key.
if not exist venv (python -m venv venv)
call venv\Scripts\activate
pip install -q -r requirements.txt
python main.py %*
pause
