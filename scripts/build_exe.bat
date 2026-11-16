@echo off
rem Builds dist\FileOpsToolkit.exe (one file, no Python needed to run it). Run on Windows.
rem Needs Python 3.10+ and Node.js 22+. Usage: scripts\build_exe.bat [onedir]
rem   (no argument)  one self-contained exe; it unpacks to a temp folder on every start
rem   onedir         dist\FileOpsToolkit\ folder holding the exe; starts faster, fewer antivirus false alarms
setlocal
cd /d "%~dp0.." || exit /b 1
set "ROOT=%CD%"

set "MODE=--onefile"
if /i "%~1"=="onedir" set "MODE=--onedir"

echo [1/3] Installing Python packages...
py -3 -m pip install -r requirements.txt pyinstaller || (echo Failed to install Python packages. & exit /b 1)

echo [2/3] Building the web UI...
pushd web
if not exist "node_modules" (
  call npm ci || (popd & echo npm ci failed. & exit /b 1)
)
call npm run build || (popd & echo Web UI build failed. & exit /b 1)
popd
if not exist "web\dist\index.html" (echo web\dist\index.html is missing after the build. & exit /b 1)

echo [3/3] Packaging with PyInstaller...
rem Generated files stay under build\ and dist\ (both ignored by git) so the repository root stays clean.
rem server.py finds the UI at web\dist and the catalogs at file_ops_toolkit\locales relative to its own
rem file, so both folders are bundled at the same relative paths.
py -3 -m PyInstaller --noconfirm --clean %MODE% --name FileOpsToolkit ^
  --distpath "%ROOT%\dist" --workpath "%ROOT%\build\pyinstaller" --specpath "%ROOT%\build" ^
  --add-data "%ROOT%\web\dist;web\dist" ^
  --add-data "%ROOT%\file_ops_toolkit\locales;file_ops_toolkit\locales" ^
  "%ROOT%\app.py" || (echo PyInstaller failed. & exit /b 1)

echo.
if "%MODE%"=="--onedir" echo Done: %ROOT%\dist\FileOpsToolkit\FileOpsToolkit.exe - copy the whole FileOpsToolkit folder.
if "%MODE%"=="--onefile" echo Done: %ROOT%\dist\FileOpsToolkit.exe
endlocal
