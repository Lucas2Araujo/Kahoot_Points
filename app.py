import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from dotenv import load_dotenv, set_key
import gspread
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()

KAHOOT_PADRAO_DEFAULT = " - Resgate"
PLANILHA_NOME_DEFAULT = "Resgate_Desempenhov2"


def _normalizar_texto(texto):
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFD", texto)
    sem_acentos = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return sem_acentos.strip().lower()


def _validar_credenciais_kahoot():
    usuario = os.getenv("KAHOOT_USER")
    senha = os.getenv("KAHOOT_PASS")
    if not usuario or not senha:
        raise ValueError(
            "Variáveis KAHOOT_USER ou KAHOOT_PASS não encontradas no arquivo .env."
        )
    return usuario, senha


def _aguardar_e_selecionar_participantes(driver, wait):
    try:
        wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//table | //*[contains(@class, 'player') or contains(@class, 'table')] | //*[@id='main-content-container']",
                )
            )
        )
    except Exception as err:
        print(f"Aviso ao aguardar carregamento inicial da tabela: {err}")

    try:
        print("Procurando a aba 'Participantes'...")
        aba_participantes = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//*[contains(translate(text(), 'PARTICIPANTES', 'participantes'), 'participante') or contains(translate(text(), 'PLAYERS', 'players'), 'player')]",
                )
            )
        )
        driver.execute_script("arguments[0].click();", aba_participantes)
        time.sleep(2)
        print("Aba 'Participantes' selecionada com sucesso!")
    except Exception as err:
        print(f"Aviso ao tentar clicar na aba Participantes: {err}")


def _processar_linha_jogador(linha):
    texto_linha = linha.text.strip()
    if not texto_linha:
        return None, None

    colunas = linha.find_elements(By.XPATH, "./td | ./div")
    if len(colunas) >= 2:
        nome = colunas[0].text.strip()
        score_raw = colunas[-1].text.strip()
    else:
        partes = texto_linha.split("\n")
        nome = partes[0].strip()
        score_raw = partes[-1].strip()

    score_digits = re.sub(r"[^\d]", "", score_raw)
    if score_digits and nome:
        return nome, int(score_digits)
    return None, None


def _coletar_jogadores_pagina(driver):
    dados = {}
    linhas = driver.find_elements(
        By.XPATH,
        "//tr[td] | //div[contains(@class, 'player-row') or contains(@data-functional-id, 'player-row') or contains(@class, 'table-row')]",
    ) or driver.find_elements(
        By.XPATH, "//*[@id='main-content-container']//table//tr[position()>1]"
    )

    for linha in linhas:
        try:
            nome, pontuacao = _processar_linha_jogador(linha)
            if nome and pontuacao is not None:
                dados[nome] = pontuacao
        except Exception:
            continue
    return dados


def extrair_dados_kahoot(driver, wait):
    """Mapeia e raspa os nicknames dos alunos e as pontuações finais do Kahoot."""
    print("\n--- Iniciando Extração de Dados (Kahoot) ---")
    _aguardar_e_selecionar_participantes(driver, wait)

    print("Rolando a página para carregar todos os participantes...")
    dados_alunos = {}
    tentativas_sem_novos_dados = 0

    while tentativas_sem_novos_dados < 4:
        qtd_anterior = len(dados_alunos)
        dados_alunos.update(_coletar_jogadores_pagina(driver))

        print(f"Total de alunos capturados até agora: {len(dados_alunos)}")
        driver.execute_script("window.scrollBy(0, 800);")
        time.sleep(1.5)

        if len(dados_alunos) == qtd_anterior:
            tentativas_sem_novos_dados += 1
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        else:
            tentativas_sem_novos_dados = 0

    print(f"✅ Raspagem concluída! Total de alunos extraídos: {len(dados_alunos)}")
    return dados_alunos


def _obter_worksheet(nome_planilha, credentials_file):
    creds_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json_str and creds_json_str.strip():
        print("🔑 Autenticando no Google Sheets via GOOGLE_CREDENTIALS_JSON (Nuvem)...")
        credenciais_dict = json.loads(creds_json_str)
        gc = gspread.service_account_from_dict(credenciais_dict)
    else:
        caminho_credenciais = os.getenv("GOOGLE_CREDENTIALS_PATH", credentials_file)
        if not os.path.exists(caminho_credenciais):
            raise FileNotFoundError(
                f"Arquivo de credenciais do Google não encontrado em: {caminho_credenciais}"
            )
        print(
            f"🔑 Autenticando no Google Sheets via arquivo local ('{caminho_credenciais}')..."
        )
        gc = gspread.service_account(filename=caminho_credenciais)

    sh = gc.open(nome_planilha)

    try:
        worksheet = sh.worksheet("Desempenho Trimestral")
    except Exception:
        print(
            "Aba 'Desempenho Trimestral' não encontrada. Utilizando a primeira aba disponível."
        )
        worksheet = sh.sheet1

    return worksheet, sh


def _encontrar_coluna_destino(valores_tabela):
    cabecalho = valores_tabela[0] if valores_tabela else []
    linha_4 = valores_tabela[3] if len(valores_tabela) >= 4 else []
    limite = max(len(cabecalho), len(linha_4), 4) + 10

    for col_zero in range(3, limite):
        val_celula = linha_4[col_zero].strip() if col_zero < len(linha_4) else ""
        if val_celula:
            continue

        col_dest = col_zero + 1
        nome_quiz = (
            cabecalho[col_zero].strip()
            if col_zero < len(cabecalho) and cabecalho[col_zero].strip()
            else f"Coluna {col_dest}"
        )
        return col_dest, nome_quiz

    return 4, "Coluna 4"


def _obter_coluna_participante(cabecalho):
    for i, h in enumerate(cabecalho):
        if h.strip().lower() in ["participante", "nome", "aluno", "alunos"]:
            return i + 1
    return 1


def _mapear_alunos_planilha(valores_tabela):
    cabecalho = valores_tabela[0] if valores_tabela else []
    col_idx = _obter_coluna_participante(cabecalho)

    mapa = {}
    for num_linha, linha in enumerate(valores_tabela[1:], start=2):
        if num_linha > 24:
            break
        if len(linha) < col_idx:
            continue
        nome = linha[col_idx - 1].strip()
        if nome and _normalizar_texto(nome) != "pontuacao maxima":
            mapa[_normalizar_texto(nome)] = num_linha

    return mapa


def _salvar_quarentena(sh, nao_identificados):
    print(
        f"\n⚠️ {len(nao_identificados)} participante(s) do Kahoot não localizado(s) na planilha principal."
    )
    try:
        ws_quarentena = sh.worksheet("Não Identificados")
    except Exception:
        print("Criando a aba 'Não Identificados'...")
        ws_quarentena = sh.add_worksheet(title="Não Identificados", rows=100, cols=3)
        ws_quarentena.append_row(["Nome Kahoot", "Pontuação", "Quiz Referência"])

    ws_quarentena.append_rows(nao_identificados)
    print(
        f"📌 {len(nao_identificados)} registro(s) salvos na aba 'Não Identificados' para reconciliação manual."
    )


def _salvar_dados_duplicados(sh, dados_alunos, motivo):
    print(
        f"\n⚠️ Redirecionando {len(dados_alunos)} registro(s) para a aba 'Dados Duplicados'. Motivo: {motivo}"
    )
    try:
        ws_duplicados = sh.worksheet("Dados Duplicados")
    except (gspread.exceptions.WorksheetNotFound, Exception):
        print("Criando a aba 'Dados Duplicados'...")
        ws_duplicados = sh.add_worksheet(title="Dados Duplicados", rows=100, cols=4)
        ws_duplicados.append_row(
            ["Data da Execução", "Aluno", "Pontuação", "Coluna Alvo/Motivo"]
        )

    data_execucao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    novas_linhas = [
        [data_execucao, nome_aluno, pontuacao, motivo]
        for nome_aluno, pontuacao in dados_alunos.items()
    ]

    if novas_linhas:
        ws_duplicados.append_rows(novas_linhas)
        print(
            f"📌 {len(novas_linhas)} registro(s) salvos na aba 'Dados Duplicados' para auditoria."
        )


def _checar_compatibilidade_quiz(nome_quiz, kahoot_padrao, col_dest_idx):
    """Verifica se o número do quiz no Kahoot coincide com o número no cabeçalho da coluna."""
    if not kahoot_padrao:
        return None

    match_quiz = re.search(r"\d+", nome_quiz)
    match_kahoot = re.search(r"\d+", kahoot_padrao)

    if match_quiz and match_kahoot:
        num_quiz = match_quiz.group(0)
        num_kahoot = match_kahoot.group(0)
        if num_kahoot != num_quiz:
            return (
                f"Incompatibilidade de Quiz: Kahoot '{kahoot_padrao}' (Quiz {num_kahoot}) "
                f"!= Coluna {col_dest_idx} '{nome_quiz}' (Quiz {num_quiz})"
            )
    return None


def _encontrar_linhas_com_dados(valores_tabela, col_dest_idx):
    """Encontra linhas da tabela que já possuem dados preenchidos na coluna destino (até a linha 24)."""
    if not valores_tabela:
        return []

    cabecalho = valores_tabela[0]
    col_idx_participante = _obter_coluna_participante(cabecalho)
    col_zero = col_dest_idx - 1
    linhas_com_dados = []

    for num_linha, linha in enumerate(valores_tabela[1:24], start=2):
        if len(linha) <= col_zero or not linha[col_zero].strip():
            continue

        nome_participante = (
            linha[col_idx_participante - 1].strip()
            if len(linha) >= col_idx_participante
            else ""
        )
        if _normalizar_texto(nome_participante) != "pontuacao maxima":
            linhas_com_dados.append(num_linha)

    return linhas_com_dados


def _validar_coluna_destino(nome_quiz, kahoot_padrao, col_dest_idx, valores_tabela):
    """Valida se o quiz corrente bate com a coluna destino e se a coluna está sem dados (até a linha 24)."""
    motivos = []

    erro_quiz = _checar_compatibilidade_quiz(nome_quiz, kahoot_padrao, col_dest_idx)
    if erro_quiz:
        motivos.append(erro_quiz)

    linhas_com_dados = _encontrar_linhas_com_dados(valores_tabela, col_dest_idx)
    if linhas_com_dados:
        motivos.append(
            f"Coluna {col_dest_idx} ('{nome_quiz}') possui dados preenchidos nas linhas: {linhas_com_dados[:5]}"
        )

    if not motivos:
        return None
    return " | ".join(motivos)


def _preparar_atualizacoes_notas(dados_alunos, mapa_linhas_alunos, col_dest_idx, nome_quiz):
    """Separa os alunos entre células a atualizar e registros não identificados."""
    atualizacoes = []
    nao_identificados = []

    for nome_kahoot, pontuacao in dados_alunos.items():
        nome_normalizado = _normalizar_texto(nome_kahoot)
        if nome_normalizado in mapa_linhas_alunos:
            linha_aluno = mapa_linhas_alunos[nome_normalizado]
            atualizacoes.append(
                gspread.Cell(row=linha_aluno, col=col_dest_idx, value=pontuacao)
            )
        else:
            nao_identificados.append([nome_kahoot, pontuacao, nome_quiz])

    return atualizacoes, nao_identificados


def integrar_com_google_sheets(
    dados_alunos,
    nome_planilha=PLANILHA_NOME_DEFAULT,
    credentials_file="credentials.json",
    kahoot_padrao="",
):
    """Conecta ao Google Sheets via gspread e atualiza notas, quarentena e auditoria."""
    print(f"\n--- Conectando ao Google Sheets: '{nome_planilha}' ---")
    worksheet, sh = _obter_worksheet(nome_planilha, credentials_file)

    valores_tabela = worksheet.get_all_values()
    if not valores_tabela:
        print("A planilha está vazia!")
        return

    col_dest_idx, nome_quiz = _encontrar_coluna_destino(valores_tabela)
    print(f"🎯 Coluna destino identificada: Coluna {col_dest_idx} ('{nome_quiz}')")

    motivo_falha = _validar_coluna_destino(
        nome_quiz, kahoot_padrao, col_dest_idx, valores_tabela
    )
    if motivo_falha:
        print(f"❌ Validação falhou: {motivo_falha}")
        _salvar_dados_duplicados(sh, dados_alunos, motivo_falha)
        return

    mapa_linhas_alunos = _mapear_alunos_planilha(valores_tabela)
    atualizacoes, nao_identificados = _preparar_atualizacoes_notas(
        dados_alunos, mapa_linhas_alunos, col_dest_idx, nome_quiz
    )

    if atualizacoes:
        worksheet.update_cells(atualizacoes)
        print(
            f"✅ Sucesso! {len(atualizacoes)} nota(s) inserida(s) na coluna {col_dest_idx} ('{nome_quiz}')."
        )

    if nao_identificados:
        _salvar_quarentena(sh, nao_identificados)


def _obter_configuracoes_interativas():
    env_path = ".env"
    kahoot_padrao = os.getenv("KAHOOT_PADRAO", KAHOOT_PADRAO_DEFAULT)
    planilha_nome = os.getenv("PLANILHA_NOME", PLANILHA_NOME_DEFAULT)

    print("\n" + "=" * 60)
    print("      ⚙️  MENU DE CONFIGURAÇÃO INTERATIVO DE EXECUÇÃO")
    print("=" * 60)
    print(f" 📌 Padrão do relatório Kahoot atual : '{kahoot_padrao}'")
    print(f" 📊 Nome da planilha Google Sheets atual: '{planilha_nome}'")
    print("-" * 60)

    input_padrao = input(
        f"Digite o padrão do relatório [ENTER para manter '{kahoot_padrao}']: "
    ).strip()
    if input_padrao:
        kahoot_padrao = input_padrao
        set_key(env_path, "KAHOOT_PADRAO", kahoot_padrao)
        print(f" 💾 Padrão do Kahoot salvo no .env -> '{kahoot_padrao}'")

    input_planilha = input(
        f"Digite o nome da planilha [ENTER para manter '{planilha_nome}']: "
    ).strip()
    if input_planilha:
        planilha_nome = input_planilha
        set_key(env_path, "PLANILHA_NOME", planilha_nome)
        print(f" 💾 Nome da planilha salvo no .env -> '{planilha_nome}'")

    print("-" * 60)
    print(" 🚀 Iniciando automação com:")
    print(f"    • Padrão Kahoot:  '{kahoot_padrao}'")
    print(f"    • Planilha Sheets: '{planilha_nome}'")
    print("=" * 60 + "\n")

    return kahoot_padrao, planilha_nome


def _inicializar_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")

    # Verifica se estamos na nuvem para aplicar as flags de contêiner
    modo_nuvem = os.getenv("CI") == "true" or not sys.stdout.isatty()

    if modo_nuvem:
        # Flags ESSENCIAIS e obrigatórias para rodar Chrome no GitHub Actions/Docker
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        # Na nuvem, o Chrome usará um perfil temporário descartável, sem tentar ler pastas locais
    else:
        # Apenas tenta espelhar a sessão se estiver rodando no seu ambiente local
        user_home = os.path.expanduser("~")
        chrome_profile_path = os.getenv(
            "CHROME_PROFILE_PATH", f"{user_home}/.config/google-chrome"
        )
        options.add_argument(f"--user-data-dir={chrome_profile_path}")
        options.add_argument(r"--profile-directory=Default")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 25)
    return driver, wait


def _garantir_sessao_kahoot(driver):
    try:
        campo_usuario = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@name='username' or @id='username']")
            )
        )
        precisa_logar = True
    except Exception:
        precisa_logar = False
        print("Sessão espelhada válida! Já estamos logados.")

    if precisa_logar:
        print(
            "Sessão expirada detectada. Lidando com cookies e iniciando login seguro..."
        )
        try:
            botao_cookie = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
            )
            botao_cookie.click()
            time.sleep(1)
            print("Banner de cookies aceito!")
        except Exception:
            pass

        usuario, senha = _validar_credenciais_kahoot()
        campo_usuario.send_keys(usuario)
        campo_senha = driver.find_element(
            By.XPATH, "//input[@name='password' or @id='password']"
        )
        campo_senha.send_keys(senha)
        campo_senha.send_keys(Keys.RETURN)

        print("Login enviado com a tecla ENTER!")
        time.sleep(5)

    return precisa_logar


def _navegar_para_relatorio(driver, wait, kahoot_padrao):
    print("Acessando a lista de relatórios...")
    url_lista = "https://create.kahoot.it/user-reports/hosted-by-me/list/?searchMode=host&globalFilter=liveGame&orderBy=time&reverse=true"
    driver.get(url_lista)

    fez_login = _garantir_sessao_kahoot(driver)
    if fez_login:
        print("Redirecionando de volta para a lista de relatórios após o login...")
        driver.get(url_lista)
        time.sleep(3)  # Pausa rápida para garantir que a tabela carregou

    print(f"Buscando o relatório mais recente com o padrão '{kahoot_padrao}'...")
    primeiro_relatorio = wait.until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                f"(//a[contains(., '{kahoot_padrao}')] | //*[contains(@data-functional-id, 'report-list-item') and contains(., '{kahoot_padrao}')] | //*[contains(@class, 'list-item') and contains(., '{kahoot_padrao}')] | //*[contains(@class, 'report-card') and contains(., '{kahoot_padrao}')])[1]",
            )
        )
    )
    driver.execute_script("arguments[0].click();", primeiro_relatorio)

    print("Entrando no relatório e aguardando os dados...")
    wait.until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                "//*[contains(translate(text(), 'PARTICIPANTES', 'participantes'), 'participante') or contains(translate(text(), 'PLAYERS', 'players'), 'player')]",
            )
        )
    )
    print("Página do relatório pronta e confirmada!")


def main(kahoot_padrao=None, planilha_nome=None):
    if not kahoot_padrao or not planilha_nome:
        kahoot_padrao, planilha_nome = _obter_configuracoes_interativas()
    driver, wait = _inicializar_driver()

    try:
        _navegar_para_relatorio(driver, wait, kahoot_padrao)
        dados_raspados = extrair_dados_kahoot(driver, wait)

        if dados_raspados:
            integrar_com_google_sheets(
                dados_alunos=dados_raspados,
                nome_planilha=planilha_nome,
                kahoot_padrao=kahoot_padrao,
            )
    except Exception as e:
        print(f"\n❌ Ocorreu um erro no fluxo: {e}")
        try:
            print(f"🔗 URL no momento do erro: {driver.current_url}")
            print(f"📄 Título da página: {driver.title}")
            driver.save_screenshot("erro_kahoot.png")
            print("📸 Screenshot salvo com sucesso como 'erro_kahoot.png'")
        except Exception as ex:
            print(f"⚠️ Não foi possível capturar o status da tela: {ex}")
    finally:
        driver.quit()


if __name__ == "__main__":
    print("\n--- Configuração da Execução ---")

    # Verifica se o script está rodando no GitHub Actions (ou sem terminal interativo)
    modo_nuvem = os.getenv("CI") == "true" or not sys.stdout.isatty()

    if modo_nuvem:
        print("☁️ Ambiente de nuvem detectado! Operando no modo silencioso.")
        kahoot_padrao = os.getenv("KAHOOT_PADRAO", KAHOOT_PADRAO_DEFAULT)
        planilha_nome = os.getenv("PLANILHA_NOME", PLANILHA_NOME_DEFAULT)
        print("-" * 60)
        print(" 🚀 Iniciando automação com:")
        print(f"    • Padrão Kahoot:  '{kahoot_padrao}'")
        print(f"    • Planilha Sheets: '{planilha_nome}'")
        print("=" * 60 + "\n")
    else:
        print("💻 Ambiente local detectado! Iniciando CLI.")
        kahoot_padrao, planilha_nome = _obter_configuracoes_interativas()

    main(kahoot_padrao, planilha_nome)
