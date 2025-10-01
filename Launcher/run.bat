@echo off
REM Auto-detect Python DLL path from conda environment
for /f "tokens=*" %%i in ('conda run -n lean python -c "import sys; print(sys.base_prefix + '\\python311.dll')"') do set PYTHONNET_PYDLL=%%i

copy /Y config.json bin\Debug\config.json
cd bin\Debug
dotnet QuantConnect.Lean.Launcher.dll
