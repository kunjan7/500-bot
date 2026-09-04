@echo off
:loop
set HANDLE=kunjan1387
set MAX_DRAFTS=100
set HOLD_SEC=12
python spin_serial.py
timeout /t 5
goto loop