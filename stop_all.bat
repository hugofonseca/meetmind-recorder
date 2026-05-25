@echo off
setlocal

echo ==========================================
echo        Encerrando servicos do MeetMind
echo ==========================================
echo.

call :killWindow "minutes_api"
call :killWindow "recorder"
call :killWindow "dashboard"

echo.
echo Finalizado.
echo Se alguma janela permanecer aberta, feche manualmente ou rode:
echo taskkill /F /IM python.exe
echo taskkill /F /IM flutter.exe
echo.
pause
exit /b

:killWindow
set "WIN_TITLE=%~1"
echo Tentando fechar %WIN_TITLE%...
taskkill /F /T /FI "WINDOWTITLE eq %WIN_TITLE%*" >nul 2>&1

if %errorlevel%==0 (
    echo [OK] %WIN_TITLE% encerrado.
) else (
    echo [INFO] %WIN_TITLE% nao encontrado ou ja estava fechado.
)
echo.
exit /b