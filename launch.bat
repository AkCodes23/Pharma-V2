@echo off
REM ============================================================
REM  Pharma Agentic AI — Unified Launch Script
REM  Starts all backend agents + frontend dashboard
REM ============================================================
REM
REM  Usage:  launch.bat           — start everything
REM          launch.bat backend   — start backend only
REM          launch.bat frontend  — start frontend only
REM          launch.bat stop      — kill all services
REM
REM  Prerequisites:
REM    1. Python 3.12+ with pip
REM    2. Node.js 20+ with npm
REM    3. .env file configured (copy .env.example)
REM ============================================================

setlocal enabledelayedexpansion

set "PROJECT_ROOT=%~dp0"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=3000"
set "LOG_DIR=%PROJECT_ROOT%logs"
set "PID_FILE=%PROJECT_ROOT%.pids"

REM Color codes for pretty output
set "CYAN=[36m"
set "GREEN=[32m"
set "YELLOW=[33m"
set "RED=[31m"
set "RESET=[0m"

REM ── Handle arguments ──────────────────────────────────────

if "%1"=="stop" goto :stop
if "%1"=="backend" goto :backend_only
if "%1"=="frontend" goto :frontend_only
if "%1"=="install" goto :install
if "%1"=="test" goto :test
if "%1"=="help" goto :help

REM Default: start everything
goto :start_all

REM ── Help ──────────────────────────────────────────────────

:help
echo.
echo %CYAN%============================================================%RESET%
echo %CYAN%  Pharma Agentic AI — Launch Commands%RESET%
echo %CYAN%============================================================%RESET%
echo.
echo   launch.bat              Start all services (backend + frontend)
echo   launch.bat backend      Start backend API only
echo   launch.bat frontend     Start frontend dashboard only
echo   launch.bat install      Install all dependencies
echo   launch.bat test         Run all tests
echo   launch.bat stop         Stop all running services
echo   launch.bat help         Show this help message
echo.
goto :eof

REM ── Install Dependencies ──────────────────────────────────

:install
echo.
echo %CYAN%[1/3] Installing Python backend dependencies...%RESET%
cd /d "%PROJECT_ROOT%"
pip install -e ".[dev]"
if errorlevel 1 (
    echo %RED%[ERROR] Python dependency installation failed!%RESET%
    exit /b 1
)
echo %GREEN%[OK] Python dependencies installed%RESET%

echo.
echo %CYAN%[2/3] Installing frontend dependencies...%RESET%
cd /d "%PROJECT_ROOT%src\frontend"
call npm install
if errorlevel 1 (
    echo %RED%[ERROR] Frontend dependency installation failed!%RESET%
    exit /b 1
)
echo %GREEN%[OK] Frontend dependencies installed%RESET%

echo.
echo %CYAN%[3/3] Verifying .env file...%RESET%
cd /d "%PROJECT_ROOT%"
if not exist ".env" (
    echo %YELLOW%[WARN] .env file not found. Copying .env.example...%RESET%
    copy .env.example .env > nul
    echo %YELLOW%[WARN] Please edit .env with your Azure credentials before running.%RESET%
) else (
    echo %GREEN%[OK] .env file found%RESET%
)

echo.
echo %GREEN%============================================================%RESET%
echo %GREEN%  Installation complete! Run 'launch.bat' to start.%RESET%
echo %GREEN%============================================================%RESET%
goto :eof

REM ── Pre-flight Checks ────────────────────────────────────

:preflight
echo.
echo %CYAN%============================================================%RESET%
echo %CYAN%  Pharma Agentic AI — Pre-flight Checks%RESET%
echo %CYAN%============================================================%RESET%
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo %RED%[FAIL] Python not found. Install Python 3.12+%RESET%
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo %GREEN%  [OK] Python %PYVER%%RESET%

REM Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo %RED%[FAIL] Node.js not found. Install Node.js 20+%RESET%
    exit /b 1
)
for /f %%v in ('node --version 2^>^&1') do set NODEVER=%%v
echo %GREEN%  [OK] Node.js %NODEVER%%RESET%

REM Check .env
if not exist "%PROJECT_ROOT%.env" (
    echo %YELLOW%  [WARN] .env not found — copying from .env.example%RESET%
    copy "%PROJECT_ROOT%.env.example" "%PROJECT_ROOT%.env" > nul
    echo %YELLOW%  [WARN] Edit .env with your Azure credentials!%RESET%
) else (
    echo %GREEN%  [OK] .env file present%RESET%
)

REM Create logs directory
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
echo %GREEN%  [OK] Log directory ready%RESET%

echo.
goto :eof

REM ── Start All ─────────────────────────────────────────────

:start_all
call :preflight
if errorlevel 1 exit /b 1

echo %CYAN%============================================================%RESET%
echo %CYAN%  Starting Pharma Agentic AI Platform%RESET%
echo %CYAN%============================================================%RESET%
echo.

call :start_backend
echo.
call :start_frontend

echo.
echo %GREEN%============================================================%RESET%
echo %GREEN%  ALL SERVICES RUNNING%RESET%
echo %GREEN%============================================================%RESET%
echo.
echo   Backend API:    http://localhost:%BACKEND_PORT%
echo   API Docs:       http://localhost:%BACKEND_PORT%/docs
echo   Health Check:   http://localhost:%BACKEND_PORT%/health
echo   Frontend:       http://localhost:%FRONTEND_PORT%
echo.
echo   Logs:           %LOG_DIR%\
echo.
echo   To stop all:    launch.bat stop
echo.
echo %CYAN%  Tip: Open http://localhost:%FRONTEND_PORT% in your browser%RESET%
echo.
goto :eof

REM ── Start Backend Only ────────────────────────────────────

:backend_only
call :preflight
if errorlevel 1 exit /b 1
call :start_backend
echo.
echo %GREEN%  Backend running at http://localhost:%BACKEND_PORT%%RESET%
echo %GREEN%  API docs at http://localhost:%BACKEND_PORT%/docs%RESET%
goto :eof

REM ── Start Frontend Only ───────────────────────────────────

:frontend_only
call :preflight
if errorlevel 1 exit /b 1
call :start_frontend
echo.
echo %GREEN%  Frontend running at http://localhost:%FRONTEND_PORT%%RESET%
goto :eof

REM ── Start Backend ─────────────────────────────────────────

:start_backend
echo %CYAN%  [BACKEND] Starting Planner Agent on port %BACKEND_PORT%...%RESET%
cd /d "%PROJECT_ROOT%"

REM Start uvicorn in the background
start "" /B cmd /c "cd /d "%PROJECT_ROOT%" && python -m uvicorn src.agents.planner.main:app --host 0.0.0.0 --port %BACKEND_PORT% --reload --log-level info > "%LOG_DIR%\backend.log" 2>&1"

REM Wait for backend to be ready
echo   Waiting for backend to start...
set /a count=0
:wait_backend
timeout /t 1 /nobreak > nul
set /a count+=1
curl -s http://localhost:%BACKEND_PORT%/health > nul 2>&1
if errorlevel 1 (
    if %count% lss 15 (
        goto :wait_backend
    ) else (
        echo %YELLOW%  [WARN] Backend may not be fully ready (check logs\backend.log)%RESET%
        goto :eof
    )
)
echo %GREEN%  [BACKEND] Planner Agent is UP ✓%RESET%
goto :eof

REM ── Start Frontend ────────────────────────────────────────

:start_frontend
echo %CYAN%  [FRONTEND] Starting Next.js dashboard on port %FRONTEND_PORT%...%RESET%
cd /d "%PROJECT_ROOT%src\frontend"

REM Start Next.js dev server in the background
start "" /B cmd /c "cd /d "%PROJECT_ROOT%src\frontend" && npm run dev > "%LOG_DIR%\frontend.log" 2>&1"

REM Wait for frontend to be ready
echo   Waiting for frontend to compile...
set /a count=0
:wait_frontend
timeout /t 2 /nobreak > nul
set /a count+=1
curl -s http://localhost:%FRONTEND_PORT% > nul 2>&1
if errorlevel 1 (
    if %count% lss 20 (
        goto :wait_frontend
    ) else (
        echo %YELLOW%  [WARN] Frontend may not be fully ready (check logs\frontend.log)%RESET%
        goto :eof
    )
)
echo %GREEN%  [FRONTEND] Dashboard is UP ✓%RESET%
goto :eof

REM ── Stop All Services ─────────────────────────────────────

:stop
echo.
echo %CYAN%  Stopping all Pharma AI services...%RESET%

REM Kill Python (uvicorn) processes
taskkill /F /IM "python.exe" /FI "WindowTitle eq *uvicorn*" > nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%BACKEND_PORT% " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%p > nul 2>&1
)
echo %GREEN%  [OK] Backend stopped%RESET%

REM Kill Node.js (Next.js) processes
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%FRONTEND_PORT% " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%p > nul 2>&1
)
echo %GREEN%  [OK] Frontend stopped%RESET%

echo.
echo %GREEN%  All services stopped.%RESET%
goto :eof

REM ── Run Tests ─────────────────────────────────────────────

:test
echo.
echo %CYAN%============================================================%RESET%
echo %CYAN%  Running Tests%RESET%
echo %CYAN%============================================================%RESET%
echo.

echo %CYAN%[1/3] Python unit tests...%RESET%
cd /d "%PROJECT_ROOT%"
python -m pytest tests/ -v --cov=src --cov-report=term-missing --tb=short
if errorlevel 1 (
    echo %RED%[FAIL] Python tests failed!%RESET%
) else (
    echo %GREEN%[PASS] Python tests passed%RESET%
)

echo.
echo %CYAN%[2/3] Python type checking...%RESET%
python -m mypy src/ --ignore-missing-imports
if errorlevel 1 (
    echo %YELLOW%[WARN] Type check issues found%RESET%
) else (
    echo %GREEN%[PASS] Type check passed%RESET%
)

echo.
echo %CYAN%[3/3] Python linting...%RESET%
python -m ruff check src/ tests/
if errorlevel 1 (
    echo %YELLOW%[WARN] Lint issues found%RESET%
) else (
    echo %GREEN%[PASS] Lint check passed%RESET%
)

echo.
echo %GREEN%  Test suite complete.%RESET%
goto :eof

endlocal
