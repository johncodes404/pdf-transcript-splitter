@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "import pypdf" >nul 2>&1
if errorlevel 1 (
  echo 首次运行，正在安装依赖...
  python -m pip install -r requirements.txt
  if errorlevel 1 pause & exit /b 1
)
python app.py
if errorlevel 1 pause
