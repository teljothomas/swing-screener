@echo off
rem Morning swing scan - run by Windows Task Scheduler at 8:00 AM on weekdays.
cd /d "%~dp0"
if not exist logs mkdir logs
"C:\Users\teljo\AppData\Local\Programs\Python\Python313\python.exe" screener.py --auto > logs\last_run.log 2>&1
