@echo off
rem Synthetic Mind launcher for Windows. The first run creates a virtual environment in .venv,
rem installs a CUDA build of PyTorch if an NVIDIA GPU is present, then the other requirements.
rem It also repairs an environment that ended up with the CPU-only PyTorch build.
setlocal
cd /d "%~dp0"
set "VPY=.venv\Scripts\python.exe"

if exist "%VPY%" goto have_venv
echo Creating virtual environment...
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
if not exist "%VPY%" goto fail_python
:have_venv

"%VPY%" -c "import struct,sys; sys.exit(struct.calcsize('P') != 8)" || goto fail_32bit
for /f "delims=" %%V in ('%VPY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%V"
echo Python %PYVER%

rem PyTorch: keep a CUDA build if there is one; otherwise get one when an NVIDIA GPU is present.
"%VPY%" -c "import torch, sys; sys.exit(0 if torch.version.cuda else 1)" >nul 2>nul && goto deps
where nvidia-smi >nul 2>nul || goto cpu_torch
echo Installing PyTorch with CUDA support...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip uninstall -y torch >nul 2>nul
rem Newest-first is not always best: CUDA 12.6 runs on the widest range of drivers.
for %%C in (cu126 cu128 cu130 cu124) do (
  echo   trying %%C ...
  "%VPY%" -m pip install torch --index-url https://download.pytorch.org/whl/%%C && goto check_cuda
)
echo.
echo No CUDA build of PyTorch exists for Python %PYVER%. Install Python 3.12 or 3.13 from python.org,
echo delete the .venv folder and run start.bat again. Continuing on the CPU for now.
goto cpu_torch

:check_cuda
"%VPY%" -c "import torch, sys; sys.exit(0 if torch.version.cuda else 1)" && goto deps
:cpu_torch
"%VPY%" -c "import torch" >nul 2>nul || "%VPY%" -m pip install torch

:deps
if exist .venv\deps-ok goto run
echo Installing the other requirements...
"%VPY%" -m pip install -r requirements.txt || goto fail_deps
echo ok> .venv\deps-ok

:run
"%VPY%" -c "import torch; print('PyTorch', torch.__version__, '| GPU:', torch.cuda.get_device_name() if torch.cuda.is_available() else 'none, training on the CPU (slow)')"
"%VPY%" run.py %*
pause
exit /b

:fail_python
echo Could not create a virtual environment. Install Python 3.12 or 3.13 from https://www.python.org
echo (tick "Add python.exe to PATH") and run start.bat again.
pause
exit /b 1

:fail_32bit
echo This Python is 32-bit; PyTorch needs 64-bit Python. Install the 64-bit Python 3.12 or 3.13,
echo delete the .venv folder and run start.bat again.
pause
exit /b 1

:fail_deps
echo Installing the requirements failed (see the messages above).
pause
exit /b 1
