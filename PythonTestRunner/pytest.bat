@echo off
REM Python Test Runner for LEAN
REM Usage (from Lean root): PythonTestRunner\pytest.bat arbitrage/tests/test_spread_manager.py

dotnet "%~dp0bin\Debug\PythonTestRunner.dll" %*
