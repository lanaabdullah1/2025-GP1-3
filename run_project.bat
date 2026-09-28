@echo off
cd /d %~dp0


#start /min "Eyecept Server" #cmd /k "python\python.exe main.py"

start /min "Eyecept Server" cmd /k ""C:\Users\huawei\AppData\Local\Programs\Python\Python312\python.exe" main.py"

:WAIT_FOR_SERVER
powershell -Command "try { Invoke-WebRequest http://127.0.0.1:5000 -UseBasicParsing -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }"

if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto WAIT_FOR_SERVER
)

start "" http://127.0.0.1:5000

exit