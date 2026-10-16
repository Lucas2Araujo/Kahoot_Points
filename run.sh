#!/usr/bin/env bash
set -e

# Navega para o diretório do script
cd "$(dirname "$0")"

echo "================================================"
echo "         Iniciando Kahoot Auto (Linux)          "
echo "================================================"

# Verifica se o Python 3 está instalado
if ! command -v python3 &> /dev/null; then
    echo "[ERRO] python3 não foi encontrado. Por favor, instale o Python 3."
    exit 1
fi

# Cria o ambiente virtual caso não exista
if [ ! -d ".venv" ]; then
    echo "[INFO] Ambiente virtual não encontrado. Criando em .venv..."
    python3 -m venv .venv
fi

# Ativa o ambiente virtual
echo "[INFO] Ativando ambiente virtual..."
source .venv/bin/activate

# Instala/atualiza as dependências se o requirements.txt existir
if [ -f "requirements.txt" ]; then
    echo "[INFO] Verificando dependências..."
    pip install -q -r requirements.txt
fi

# Validações básicas de configuração
if [ ! -f ".env" ]; then
    echo "[AVISO] Arquivo .env não encontrado! Certifique-se de configurar suas credenciais."
fi

if [ ! -f "credentials.json" ] && [ -z "$GOOGLE_CREDENTIALS_JSON" ]; then
    echo "[AVISO] Arquivo credentials.json não encontrado."
fi

# Executa a aplicação
echo "[INFO] Executando app.py..."
python3 app.py "$@"
