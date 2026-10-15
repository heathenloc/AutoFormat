@echo off
setlocal
set PYTHONDONTWRITEBYTECODE=1
where py.exe >nul 2>nul
if errorlevel 1 goto python
py -3.12 -I -S -B "%~dp0launch.py" %*
goto end
:python
python -I -S -B "%~dp0launch.py" %*
:end
if errorlevel 1 pause
endlocal
