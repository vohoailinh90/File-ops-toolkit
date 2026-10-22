@echo off
rem Starts File Fetch. First run installs the Python package and builds the web UI (needs Python 3.10+ and Node.js 22+).
cd /d "%~dp0"
py -3 -c "import openpyxl" 2>nul || py -3 -m pip install -r requirements.txt
if not exist "web\dist\index.html" (
  pushd web
  call npm ci
  call npm run build
  popd
)
py -3 app.py %*
