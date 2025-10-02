@echo off
REM Auto-detect Python DLL path from conda environment
for /f "tokens=*" %%i in ('conda run -n lean python -c "import sys; print(sys.base_prefix + '\\python311.dll')"') do set PYTHONNET_PYDLL=%%i

REM Kill any running IB Gateway processes to ensure clean state
taskkill /F /IM ibgateway.exe 2>nul

REM Wait for processes to fully terminate
timeout /t 2 /nobreak >nul

copy /Y config.json bin\Debug\config.json
cd bin\Debug
dotnet QuantConnect.Lean.Launcher.dll
