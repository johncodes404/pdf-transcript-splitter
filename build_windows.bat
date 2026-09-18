@rem Windows 单文件打包脚本：安装依赖并生成可独立运行的 EXE。
@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 pause & exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --additional-hooks-dir "." --name "成绩单PDF拆分工具" --icon "app.ico" --add-data "app.ico;." app.py
if errorlevel 1 pause & exit /b 1
echo.
echo 打包完成：dist\成绩单PDF拆分工具.exe
pause
