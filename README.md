# 🎯 Kahoot Points

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Selenium](https://img.shields.io/badge/selenium-4.x-green.svg)
![Google Sheets](https://img.shields.io/badge/Google%20Sheets-API%20v4-34A853.svg)
![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Automated%20Builds-blueviolet.svg)

Uma ferramenta em Python desenvolvida para automatizar a extração de relatórios de desempenho do **Kahoot** via **Selenium** (em modo *Headless*) e realizar a sincronização e consolidação das notas no **Google Sheets** via **gspread**.

---

## 🚀 Principais Funcionalidades

- **Navegação & Autenticação Inteligente**:
  - **Injeção de Sessão via Cookies (`KAHOOT_COOKIES_JSON`)**: Permite injetar cookies de sessão salvos em JSON para ignorar o formulário de login e evitar verificações de Captcha (hCaptcha) em ambientes automatizados / CI/CD.
  - **Fallback para Login por Credenciais**: Autenticação automática segura quando os cookies não estão presentes.
- **Modo Nuvem & Local Adaptativo**:
  - Detecção automática de ambiente (`CI` / GitHub Actions vs CLI Local).
  - Execução no Chrome *Headless* otimizada para contêineres e instâncias de nuvem.
- **Raspagem Dinâmica com Lazy Loading**:
  - Rolagem automática para capturar 100% dos participantes cadastrados no relatório do Kahoot.
- **Normalização & Mapeamento de Alunos**:
  - Algoritmo de correspondência insensível a acentuação e caixa de texto (ex: `João Silva` no Kahoot é associado corretamente a `Joao Silva` na planilha).
- **Validação Rigorosa & Proteção contra Sobreposição**:
  - **Checagem de Compatibilidade do Quiz**: Valida se a numeração do relatório selecionado no Kahoot corresponde à coluna destino na planilha.
  - **Prevenção de Sobregravação**: Identifica se a coluna destino já possui dados preenchidos e bloqueia atualizações acidentais.
- **Quarentena e Auditoria no Google Sheets**:
  - **Aba 'Não Identificados'**: Participantes do Kahoot não encontrados na lista principal da planilha são salvos automaticamente para reconciliação manual.
  - **Aba 'Dados Duplicados'**: Registros que falharem na validação (coluna já preenchida ou quiz incompatível) são redirecionados para esta aba de auditoria com timestamp, motivo detalhado e pontuação.
- **Menu Interativo CLI com Persistência no `.env`**:
  - Permite trocar dinamicamente o relatório padrão e a planilha de destino via terminal antes de cada execução, salvando as escolhas no arquivo `.env`.
- **Diagnóstico Automático & Telemetria em Nuvem**:
  - Captura automática de screenshot (`erro_kahoot.png`), URL e título da página em caso de exceções no fluxo para depuração imediata.

---

## 🛠️ Variáveis de Ambiente & Configuração

Para executar o programa (seja via código-fonte, GitHub Actions ou executáveis), configure as variáveis descritas abaixo:

### Principais Variáveis do `.env`

| Variável | Descrição | Exemplo |
| :--- | :--- | :--- |
| `KAHOOT_USER` | Usuário/E-mail da conta do Kahoot | `usuario@email.com` |
| `KAHOOT_PASS` | Senha da conta do Kahoot | `suasenha123` |
| `KAHOOT_PADRAO` | Padrão de texto para identificar o relatório | `" - Resgate"` |
| `PLANILHA_NOME` | Nome da planilha no Google Sheets | `"Resgate_Desempenhov2"` |
| `GOOGLE_CREDENTIALS_PATH` | Caminho do arquivo JSON da Service Account (Local) | `"credentials.json"` |
| `GOOGLE_CREDENTIALS_JSON` | Conteúdo do JSON da Service Account como string (Nuvem/CI) | `'{"type": "service_account", ...}'` |
| `KAHOOT_COOKIES_JSON` | JSON de cookies para injeção de sessão e bypass de captcha | `'[{"name": "...", "value": "..."}, ...]'` |
| `CHROME_PROFILE_PATH` | *(Opcional)* Caminho do perfil local do Chrome | `~/.config/google-chrome` |

### Exemplo de arquivo `.env` local

```env
KAHOOT_USER="seu_usuario_kahoot"
KAHOOT_PASS="sua_senha_kahoot"
KAHOOT_PADRAO=" - Resgate"
PLANILHA_NOME="Resgate_Desempenhov2"
GOOGLE_CREDENTIALS_PATH="credentials.json"
```

---

## 📊 Estrutura de Abas no Google Sheets

1. **Aba Principal (`Desempenho Trimestral`)**:
   - Recebe as notas dos alunos identificados na primeira coluna vazia validada.
2. **Aba `'Não Identificados'`**:
   - Armazena alunos do Kahoot cujo nome não foi localizado na lista principal.
3. **Aba `'Dados Duplicados'`**:
   - Armazena tentativas de execução em colunas ocupadas ou quizzes divergentes para auditoria sem perda de dados.


---

## 📦 Como Executar os Executáveis (Releases)

Baixe a versão pronta para uso (sem necessidade de instalar o Python) na aba [Releases](https://github.com/Lucas2Araujo/Kahoot_Points/releases).

### 🐧 No Linux (`KahootAuto_linux`)
1. Baixe o executável `KahootAuto_linux`.
2. Mantenha os arquivos `.env` e `credentials.json` na mesma pasta.
3. Conceda permissão de execução e rode:
   ```bash
   chmod +x KahootAuto_linux
   ./KahootAuto_linux
   ```

### 🪟 No Windows (`KahootAuto_win.exe`)
1. Baixe o executável `KahootAuto_win.exe`.
2. Mantenha os arquivos `.env` e `credentials.json` na mesma pasta.
3. Execute o programa dando dois cliques ou pelo Prompt de Comando:
   ```cmd
   .\KahootAuto_win.exe
   ```

---

## 💻 Desenvolvimento Local

Para rodar o projeto pelo código-fonte:

1. Clone o repositório:
   ```bash
   git clone https://github.com/Lucas2Araujo/Kahoot_Points.git
   cd Kahoot_Points
   ```
2. Instale as dependências fixadas:
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
