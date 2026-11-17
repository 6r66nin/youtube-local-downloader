@echo off
rem Windows shim so `yt` works from PowerShell, cmd or Win+R.
rem Usage: yt -q 1080 "https://www.youtube.com/watch?v=..."
python "%~dp0yt.py" %*
exit /b %errorlevel%
