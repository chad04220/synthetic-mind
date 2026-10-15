@echo off
rem Synthetic Mind launcher for Windows. The first run creates a virtual environment.
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  echo Installing PyTorch with CUDA support...
  pip install torch --index-url https://download.pytorch.org/whl/cu124
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
python run.py %*
pause
