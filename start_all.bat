@echo off
setlocal

title MeetMind Launcher
cd /d C:\MeetMind

echo ==========================================
echo          Iniciando MeetMind
echo ==========================================
echo.

REM =========================
REM API Flask
REM =========================
if not exist "C:\MeetMind\minutes_api\app.py" (
    echo [ERRO] Arquivo nao encontrado: C:\MeetMind\minutes_api\app.py
    pause
    exit /b 1
)

if not exist "C:\MeetMind\minutes_api\.venv\Scripts\activate.bat" (
    echo [ERRO] Venv da API nao encontrado em C:\MeetMind\minutes_api\.venv
    pause
    exit /b 1
)

echo [1/3] Iniciando API...
start "minutes_api" cmd /k "cd /d C:\MeetMind\minutes_api && call .venv\Scripts\activate.bat && python app.py"
timeout /t 3 >nul

REM =========================
REM Recorder / Bot Discord
REM =========================
if not exist "C:\MeetMind\recorder\main.py" (
    echo [ERRO] Arquivo nao encontrado: C:\MeetMind\recorder\main.py
    pause
    exit /b 1
)

if not exist "C:\MeetMind\recorder\.venv\Scripts\activate.bat" (
    echo [ERRO] Venv do recorder nao encontrado em C:\MeetMind\recorder\.venv
    pause
    exit /b 1
)

echo [2/3] Iniciando bot recorder...
start "recorder" cmd /k "cd /d C:\MeetMind\recorder && call .venv\Scripts\activate.bat && python main.py"
timeout /t 3 >nul

REM =========================
REM Flutter Dashboard
REM =========================
if not exist "C:\MeetMind\dashboard_flutter\pubspec.yaml" (
    echo [ERRO] Projeto Flutter nao encontrado em C:\MeetMind\dashboard_flutter
    pause
    exit /b 1
)

echo [3/3] Iniciando dashboard Flutter...
start "dashboard" cmd /k "cd /d C:\MeetMind\dashboard_flutter && flutter run -d chrome"

echo.
echo ==========================================
echo Todos os servicos foram iniciados.
echo API       -> janela: minutes_api
echo Recorder  -> janela: recorder
echo Dashboard -> janela: dashboard
echo ==========================================
echo.
echo Use stop_all.bat para encerrar tudo.