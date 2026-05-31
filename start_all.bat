@echo off
setlocal

title MeetMind Launcher

REM Diretório raiz do projeto (onde o BAT está)
set "ROOT=%~dp0"

echo ==========================================
echo          Iniciando MeetMind
echo ==========================================
echo.

REM =========================
REM API Flask
REM =========================
if not exist "%ROOT%minutes_api\app.py" (
    echo [ERRO] Arquivo nao encontrado: %ROOT%minutes_api\app.py
    pause
    exit /b 1
)

if not exist "%ROOT%minutes_api\.venv\Scripts\activate.bat" (
    echo [ERRO] Venv da API nao encontrado em %ROOT%minutes_api\.venv
    pause
    exit /b 1
)

echo [1/3] Iniciando API...
start "minutes_api" cmd /k "cd /d "%ROOT%minutes_api" && call .venv\Scripts\activate.bat && python app.py"
timeout /t 3 /nobreak >nul

REM =========================
REM Recorder / Bot Discord
REM =========================
if not exist "%ROOT%recorder\main.py" (
    echo [ERRO] Arquivo nao encontrado: %ROOT%recorder\main.py
    pause
    exit /b 1
)

if not exist "%ROOT%recorder\.venv\Scripts\activate.bat" (
    echo [ERRO] Venv do recorder nao encontrado em %ROOT%recorder\.venv
    pause
    exit /b 1
)

echo [2/3] Iniciando bot recorder...
start "recorder" cmd /k "cd /d "%ROOT%recorder" && call .venv\Scripts\activate.bat && python main.py"
timeout /t 3 /nobreak >nul

REM =========================
REM Flutter Dashboard
REM =========================
if not exist "%ROOT%dashboard_flutter\pubspec.yaml" (
    echo [ERRO] Projeto Flutter nao encontrado em %ROOT%dashboard_flutter
    pause
    exit /b 1
)

REM Se o flutter nao estiver no PATH, troque pelo caminho completo:
REM set "FLUTTER_CMD=C:\src\flutter\bin\flutter.bat"
set "FLUTTER_CMD=flutter"

where %FLUTTER_CMD% >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Flutter nao encontrado no PATH.
    echo Ajuste a variavel FLUTTER_CMD dentro deste BAT para o caminho completo do flutter.bat
    echo Exemplo:
    echo set "FLUTTER_CMD=C:\src\flutter\bin\flutter.bat"
    pause
    exit /b 1
)

echo [3/3] Iniciando dashboard Flutter...
start "dashboard" cmd /k "cd /d "%ROOT%dashboard_flutter" && %FLUTTER_CMD% pub get && %FLUTTER_CMD% run -d chrome"

echo.
echo ==========================================
echo Todos os servicos foram iniciados.
echo API       -> janela: minutes_api
echo Recorder  -> janela: recorder
echo Dashboard -> janela: dashboard
echo ==========================================
echo.
echo Use stop_all.bat para encerrar tudo.
pause
endlocal