@echo off
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m uvicorn levelup.main:app --port 8322
