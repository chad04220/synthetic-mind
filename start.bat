@echo off
rem Synthetic Mind launcher for Windows. The first run creates a virtual environment in .venv and
rem installs the requirements. The model server (llama.cpp, on the GPU when there is one) and the
rem model download themselves on first use; the training tools for Practice install from the page.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set "VPY=.venv\Scripts\python.exe"

if exist "%VPY%" goto have_venv
echo Creating virtual environment...
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
if not exist "%VPY%" goto fail_python
:have_venv

"%VPY%" -c "import struct,sys; sys.exit(struct.calcsize('P') != 8)" || goto fail_32bit
for /f "delims=" %%V in ('%VPY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%V"
echo Python %PYVER%

:deps
rem Install the requirements again whenever requirements.txt changes (new versions add packages).
fc /b requirements.txt .venv\requirements.installed >nul 2>nul && goto run
echo Installing the requirements...
"%VPY%" -m pip install -r requirements.txt || goto fail_deps
copy /y requirements.txt .venv\requirements.installed >nul

:run
"%VPY%" run.py %*
pause
exit /b

:fail_python
echo Could not create a virtual environment. Install Python 3.12 or 3.13 from https://www.python.org
echo (tick "Add python.exe to PATH") and run start.bat again.
pause
exit /b 1

:fail_32bit
echo This Python is 32-bit; Synthetic Mind needs 64-bit Python. Install the 64-bit Python 3.12 or 3.13,
echo delete the .venv folder and run start.bat again.
pause
exit /b 1

:fail_deps
echo Installing the requirements failed (see the messages above).
pause
exit /b 1
