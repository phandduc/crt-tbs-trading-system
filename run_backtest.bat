@echo off
title Backtest CRT + TBS (D - H1)
cd /d "%~dp0"
echo ======================================================
echo    BACKTEST CRT + TBS (D - H1), CSV cua repo S2-4 cu, khong ket noi MT5
echo    Rui ro / von chi doi bang balance (USD); so lieu theo R khong doi
echo ======================================================
echo   0. Ca 4 ma
echo   1. XAUUSD   2. EURUSD   3. GBPUSD   4. AUDUSD
set "syms="
set "choice="
set /p choice="Chon ma (0-4, Enter = 0): "
if "%choice%"=="" set choice=0
if "%choice%"=="0" set syms=XAUUSD EURUSD GBPUSD AUDUSD
if "%choice%"=="1" set syms=XAUUSD
if "%choice%"=="2" set syms=EURUSD
if "%choice%"=="3" set syms=GBPUSD
if "%choice%"=="4" set syms=AUDUSD
if not defined syms (
    echo Lua chon khong hop le: %choice%
    pause
    exit /b 1
)
set "risk="
set /p risk="Rui ro %% moi lenh (Enter = 1): "
if "%risk%"=="" set risk=1
set "account="
set /p account="Von ban dau USD (Enter = 10000): "
if "%account%"=="" set account=10000
echo.
echo Dang chay backtest %syms% ^| rui ro %risk%%% ^| von %account% USD ...
python backtest.py --symbols %syms% --risk-percent %risk% --account %account% %*
echo.
pause
