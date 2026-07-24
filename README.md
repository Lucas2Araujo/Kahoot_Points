# 🎯 Kahoot Points

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Selenium](https://img.shields.io/badge/selenium-4.x-green.svg)
![Google Sheets](https://img.shields.io/badge/Google%20Sheets-API%20v4-34A853.svg)
![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Automated%20Builds-blueviolet.svg)

Uma ferramenta em Python desenvolvida para automatizar a extração de relatórios de desempenho do **Kahoot** via **Selenium** (em modo *Headless*) e realizar a sincronização automática das notas no **Google Sheets** via **gspread**.

---

## 🚀 Principais Funcionalidades

- **Navegação & Login Automatizado**: Acessa os relatórios hosted no Kahoot reaproveitando perfil espelhado de sessão ou realizando login seguro.
- **Raspagem Dinâmica com Lazy Loading**: Lida com rolagem automática para capturar 100% dos participantes cadastrados no relatório.
- **Normalização de Nomes de Alunos**: Algoritmo insensível a acentuação e caixa de texto (ex: `João Silva` no Kahoot corresponde a `Joao Silva` na planilha).
- **Descoberta Automática de Coluna Destino**: Identifica dinamicamente a primeira coluna vazia a partir da linha de pontuação máxima.
- **Quarentena de Alunos Não Identificados**: Participantes do Kahoot não encontrados na lista principal da planilha são enviados para a aba **'Não Identificados'** para conciliação manual.
- **Menu Interativo de Terminal**: Permite trocar o relatório padrão e a planilha de destino dinamicamente antes de cada execução.

---

## 🛠️ Estrutura de Configuração

Para executar o programa (seja via código-fonte ou pelos executáveis das Releases), são necessários dois arquivos na mesma pasta do programa:

### 1. Arquivo `.env`
Crie um arquivo chamado `.env` no mesmo diretório do executável contendo:

```env
KAHOOT_USER=seu_usuario_kahoot
KAHOOT_PASS=sua_senha_kahoot
KAHOOT_PADRAO=" - Resgate"
PLANILHA_NOME="Resgate_Desempenhov2"
GOOGLE_CREDENTIALS_PATH="credentials.json"
```

### 2. Arquivo `credentials.json`
Faça o download da chave da **Conta de Serviço (Service Account)** do Google Cloud Platform com permissão na API do Google Sheets e salve como `credentials.json`.

---

## 📦 Como Executar os Executáveis (Releases)

Você pode baixar a versão pronta para uso sem precisar instalar o Python no seu sistema diretamente da aba [Releases](https://github.com/Lucas2Araujo/Kahoot_Points/releases).

### 🐧 No Linux (`KahootAuto_linux`)
1. Baixe o executável `KahootAuto_linux` da página de Releases.
2. Certifique-se de que os arquivos `.env` e `credentials.json` estejam na mesma pasta do executável.
3. Abra o terminal na pasta e dê permissão de execução:
   ```bash
   chmod +x KahootAuto_linux
   ```
4. Execute o programa:
   ```bash
   ./KahootAuto_linux
   ```

### 🪟 No Windows (`KahootAuto_win.exe`)
1. Baixe o executável `KahootAuto_win.exe` da página de Releases.
2. Coloque o arquivo `KahootAuto_win.exe` na mesma pasta onde estão os arquivos `.env` e `credentials.json`.
3. Dê dois cliques em `KahootAuto_win.exe` (ou execute pelo Prompt de Comando / PowerShell):
   ```cmd
   .\KahootAuto_win.exe
   ```

---

## 💻 Desenvolvimento Local

Para rodar o projeto a partir do código-fonte:

1. Clone o repositório:
   ```bash
   git clone https://github.com/Lucas2Araujo/Kahoot_Points.git
   cd Kahoot_Points
   ```
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Execute o script:
   ```bash
   python app.py
   ```

---

## 📝 Licença

Distribuído sob a licença MIT. Sinta-se livre para utilizar e contribuir!
