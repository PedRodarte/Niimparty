@echo off
rem Niimparty no Windows sem make.
rem   run.bat            -> inicia (pergunta a configuracao na 1a vez)
rem   run.bat setup      -> refaz as perguntas
rem   run.bat qr         -> placa A5 com QR codes
rem   run.bat preview    -> etiquetas de exemplo
rem   run.bat test       -> testes
setlocal
cd /d "%~dp0"
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente Python em .venv ...
    where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
    if errorlevel 1 (
        echo Nao encontrei o Python. Instale o Python 3.12 em https://www.python.org/downloads/
        exit /b 1
    )
)

if not exist ".venv\.installed" (
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1
    echo ok> ".venv\.installed"
)

set CMD=%1
if "%CMD%"=="" set CMD=run
shift
".venv\Scripts\python.exe" niimparty.py %CMD% %1 %2 %3 %4 %5 %6 %7 %8 %9
