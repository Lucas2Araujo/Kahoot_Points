@echo off
setlocal enabledelayedexpansion

title Kahoot Auto
echo ================================================
echo         Iniciando Kahoot Auto (Windows)         
echo ================================================

cd /d "%~dp0"

:: Verifica se o Python esta instalado
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERRO] Python nao foi encontrado no PATH.
    echo Por favor, instale o Python em https://www.python.org/downloads/ e marque "Add Python to PATH".
    pause
    exit /b 1
)

:: Cria ambiente virtual se nao existir
if not exist ".venv" (
    echo [INFO] Criando ambiente virtual em .venv...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERRO] Falha ao criar o ambiente virtual.
        pause
        exit /b 1
    )
)

:: Ativa o ambiente virtual
echo [INFO] Ativando ambiente virtual...
call .venv\Scripts\activate.bat

:: Instala ou verifica dependencias
if exist "requirements.txt" (
    echo [INFO] Verificando dependencias...
    python -m pip install -q -r requirements.txt
)

:: Avisos de configuracao
if not exist ".env" (
    echo [AVISO] Arquivo .env nao encontrado! Certifique-se de configurar suas variaveis.
)

if not exist "credentials.json" (
    if "%GOOGLE_CREDENTIALS_JSON%"=="" (
        echo [AVISO] Arquivo credentials.json nao encontrado!
    )
)

:: Executa a aplicacao
echo [INFO] Executando app.py...
python app.py %*

if %errorlevel% neq 0 (
    echo.
    echo [INFO] Execucao finalizada com erro ou interrompida.
    pause
)
