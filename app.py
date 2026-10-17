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
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()

KAHOOT_PADRAO_DEFAULT = " - Profetas"
PLANILHA_NOME_DEFAULT = "Profetas_Desempenho"


def _normalizar_texto(texto):
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFD", texto)
    sem_acentos = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return sem_acentos.strip().lower()


def _carregar_dicionario_nomes(caminho="nomes_kahoot.json"):
    """Carrega o dicionário local de apelidos. Retorna mapa com chaves normalizadas."""
    if not os.path.exists(caminho):
        return {}
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
            # {apelido_normalizado: (apelido_original, nome_planilha)}
            return {_normalizar_texto(k): (k, v) for k, v in dados.items() if k and v}
    except Exception as e:
        print(f"⚠️ Erro ao carregar '{caminho}': {e}")
        return {}


def _salvar_entrada_dicionario(apelido, nome_oficial, caminho="nomes_kahoot.json"):
    """Salva um novo par apelido -> nome oficial no arquivo local de dicionário."""
    dados = {}
    if os.path.exists(caminho):
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except Exception:
            dados = {}
    dados[apelido] = nome_oficial
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        print(f"  💾 Dicionário atualizado: '{apelido}' -> '{nome_oficial}' salvo em '{caminho}'.")
    except Exception as e:
        print(f"  ⚠️ Falha ao salvar no dicionário: {e}")


def _identificar_aluno_por_pontuacao(pontuacao_kahoot, col_dest_idx, valores_tabela, mapa_linhas_alunos):
    """
    Busca na coluna do quiz se existe exatamente 1 aluno na planilha com a mesma pontuação.
    Retorna o nome oficial do aluno se candidato único, ou None.
    """
    col_zero = col_dest_idx - 1
    candidatos = []

    # Inverte mapa para buscar nome original pela linha
    linha_para_aluno = {linha: nome_norm for nome_norm, linha in mapa_linhas_alunos.items()}

    for linha_num, nome_norm in linha_para_aluno.items():
        if linha_num - 1 < len(valores_tabela):
            linha_dados = valores_tabela[linha_num - 1]
            val_str = linha_dados[col_zero].strip() if col_zero < len(linha_dados) else ""
            digitos = re.sub(r"[^\d]", "", val_str)
            if digitos and int(digitos) == pontuacao_kahoot:
                # Recupera o nome exato escrito na coluna de participante
                col_idx_part = _obter_coluna_participante(valores_tabela)
                nome_oficial = linha_dados[col_idx_part - 1].strip() if len(linha_dados) >= col_idx_part else nome_norm
                candidatos.append((nome_norm, nome_oficial))

    if len(candidatos) == 1:
        return candidatos[0]
    return None


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


def _obter_linha_cabecalho(valores_tabela):
    """Retorna a linha que contém os cabeçalhos dos quizzes e colunas (Linha 2 da planilha, índice 1)."""
    if len(valores_tabela) >= 2:
        return valores_tabela[1]
    elif valores_tabela:
        return valores_tabela[0]
    return []


def _encontrar_coluna_destino(valores_tabela, nome_relatorio=""):
    """
    Encontra a coluna destino correta baseando-se no número do quiz do relatório
    ou na primeira coluna de quiz vazia a partir da coluna D (índice 4).
    """
    cabecalho = _obter_linha_cabecalho(valores_tabela)

    # Tenta extrair o número do quiz do relatório (ex: '1 - Profetas' -> 1)
    match_num_rel = re.search(r"\b(\d+)\b", nome_relatorio)
    num_esperado = match_num_rel.group(1) if match_num_rel else None

    # Se encontramos o número do quiz, procura uma coluna na linha 2 cujo cabeçalho bata com 'Quiz X' ou 'X'
    if num_esperado:
        for idx, texto_col in enumerate(cabecalho):
            match_col = re.search(r"(?:quiz\s*|lição\s*|licao\s*|\b)(\d+)\b", texto_col, re.IGNORECASE)
            if match_col and match_col.group(1) == num_esperado:
                col_dest = idx + 1
                return col_dest, texto_col.strip()

    # Fallback: procura a primeira coluna de Quiz (a partir da coluna 4 / D) sem preenchimento na maioria dos alunos
    limite = len(cabecalho)
    for col_zero in range(3, limite):
        texto_col = cabecalho[col_zero].strip()
        # Ignora colunas que não são de notas (ex: Total Pontos)
        if "total" in texto_col.lower() or "visita" in texto_col.lower():
            continue

        # Verifica se essa coluna possui dados preenchidos entre a linha 3 e 27
        linhas_ocupadas = _encontrar_linhas_com_dados(valores_tabela, col_zero + 1)
        if not linhas_ocupadas:
            col_dest = col_zero + 1
            nome_quiz = texto_col if texto_col else f"Coluna {col_dest}"
            return col_dest, nome_quiz

    return 4, (cabecalho[3].strip() if len(cabecalho) > 3 else "Coluna 4")


def _obter_coluna_participante(valores_tabela):
    cabecalho = _obter_linha_cabecalho(valores_tabela)
    for i, h in enumerate(cabecalho):
        if any(termo in h.strip().lower() for termo in ["participante", "nome", "aluno", "alunos"]):
            return i + 1
    return 1


def _mapear_alunos_planilha(valores_tabela):
    col_idx = _obter_coluna_participante(valores_tabela)

    mapa = {}
    # Linha 3 (índice 2) até a linha 28 (linha 29 é Ayla - pontuação máxima)
    for num_linha, linha in enumerate(valores_tabela[2:], start=3):
        if num_linha > 28:
            break
        if len(linha) < col_idx:
            continue
        nome = linha[col_idx - 1].strip()
        if nome and "pontuacao maxima" not in _normalizar_texto(nome) and "legenda" not in _normalizar_texto(nome):
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
    """Verifica se o número do quiz no Kahoot coincide com o número no cabeçalho da coluna (Linha 2)."""
    if not kahoot_padrao:
        return None

    # Procura número do quiz no cabeçalho (ex: 'Quiz 1 \n 03/Oct' -> '1')
    match_quiz = re.search(r"(?:quiz\s*|lição\s*|licao\s*|\b)(\d+)\b", nome_quiz, re.IGNORECASE)
    # Procura número do quiz no nome do Kahoot (ex: '1 - Profetas (O Criador fala)' -> '1')
    match_kahoot = re.search(r"\b(\d+)\b", kahoot_padrao)

    if match_quiz and match_kahoot:
        num_quiz = match_quiz.group(1)
        num_kahoot = match_kahoot.group(1)
        if num_kahoot != num_quiz:
            return (
                f"Incompatibilidade de Quiz: Kahoot '{kahoot_padrao}' (Quiz {num_kahoot}) "
                f"!= Coluna {col_dest_idx} '{nome_quiz.replace(chr(10), ' ')}' (Quiz {num_quiz})"
            )
    return None


def _encontrar_linhas_com_dados(valores_tabela, col_dest_idx):
    """Encontra linhas de alunos que já possuem dados preenchidos na coluna destino (linha 3 até 28)."""
    if not valores_tabela:
        return []

    col_idx_participante = _obter_coluna_participante(valores_tabela)
    col_zero = col_dest_idx - 1
    linhas_com_dados = []

    # Linha 3 (índice 2) até a linha 28 (linha 29 é Ayla - pontuação máxima)
    for num_linha, linha in enumerate(valores_tabela[2:28], start=3):
        if len(linha) <= col_zero or not linha[col_zero].strip():
            continue

        nome_participante = (
            linha[col_idx_participante - 1].strip()
            if len(linha) >= col_idx_participante
            else ""
        )
        nome_norm = _normalizar_texto(nome_participante)
        if "pontuacao maxima" not in nome_norm and "legenda" not in nome_norm:
            linhas_com_dados.append(num_linha)

    return linhas_com_dados


def _validar_coluna_destino(nome_quiz, kahoot_padrao, col_dest_idx):
    """Valida apenas incompatibilidade de quiz. A validação de células preenchidas é feita aluno a aluno."""
    erro_quiz = _checar_compatibilidade_quiz(nome_quiz, kahoot_padrao, col_dest_idx)
    return erro_quiz


def _preparar_atualizacoes_notas(dados_alunos, mapa_linhas_alunos, col_dest_idx, nome_quiz, valores_tabela, modo_nuvem=False):
    """
    Varre aluno a aluno:
    - Consulta o dicionário de apelidos local (nomes_kahoot.json).
    - Se desconhecido, tenta correlacionar pela pontuação na coluna correspondente e sugere mapeamento.
    - Se a célula já tiver a mesma pontuação: avisa que já foi computada e pula.
    - Se a célula tiver pontuação divergente: avisa no terminal e encaminha para quarentena/auditoria.
    - Se a célula estiver vazia: prepara para inserção.
    - Se o aluno não for encontrado: quarentena 'Não Identificados'.
    """
    col_zero = col_dest_idx - 1
    atualizacoes = []
    nao_identificados = []
    divergencias = {}

    dicionario_nomes = _carregar_dicionario_nomes()

    print("\n🔍 Comparando pontuações com a planilha:")
    for nome_kahoot, pontuacao_kahoot in dados_alunos.items():
        nome_normalizado = _normalizar_texto(nome_kahoot)
        nome_exibicao = nome_kahoot

        # 1. Verifica se já está mapeado no dicionário de apelidos
        if nome_normalizado in dicionario_nomes:
            apelido_orig, nome_oficial = dicionario_nomes[nome_normalizado]
            nome_normalizado = _normalizar_texto(nome_oficial)
            nome_exibicao = f"{nome_kahoot} (-> {nome_oficial})"

        # 2. Se ainda não encontrado na planilha, tenta identificar por pontuação idêntica nessa lição
        if nome_normalizado not in mapa_linhas_alunos:
            candidato = _identificar_aluno_por_pontuacao(
                pontuacao_kahoot, col_dest_idx, valores_tabela, mapa_linhas_alunos
            )
            if candidato and not modo_nuvem:
                candidato_norm, candidato_oficial = candidato
                print(f"\n💡 [Sugestão por Pontuação] No '{nome_quiz}', o participante '{nome_kahoot}' fez {pontuacao_kahoot} pts.")
                print(f"   A aluna/aluno '{candidato_oficial}' tem exatamente {pontuacao_kahoot} pts nessa mesma lição na planilha.")
                resp = input(f"   Deseja mapear o apelido '{nome_kahoot}' -> '{candidato_oficial}' no dicionário? [S/n]: ").strip().lower()
                if resp in ["", "s", "sim", "y", "yes"]:
                    _salvar_entrada_dicionario(nome_kahoot, candidato_oficial)
                    dicionario_nomes[_normalizar_texto(nome_kahoot)] = (nome_kahoot, candidato_oficial)
                    nome_normalizado = candidato_norm
                    nome_exibicao = f"{nome_kahoot} (-> {candidato_oficial})"

        # 3. Processamento das notas
        if nome_normalizado in mapa_linhas_alunos:
            linha_aluno = mapa_linhas_alunos[nome_normalizado]
            linha_dados = valores_tabela[linha_aluno - 1] if linha_aluno - 1 < len(valores_tabela) else []
            valor_atual_str = linha_dados[col_zero].strip() if col_zero < len(linha_dados) else ""

            # Converte valor atual numérico se existir
            valor_atual_digitos = re.sub(r"[^\d]", "", valor_atual_str)

            if valor_atual_digitos:
                pontuacao_planilha = int(valor_atual_digitos)
                if pontuacao_planilha == pontuacao_kahoot:
                    print(f"  ℹ️  {nome_exibicao}: pontuação {pontuacao_kahoot} já computada (idêntica na planilha).")
                else:
                    msg = (
                        f"Divergência detectada para '{nome_exibicao}': pontuação na planilha é {pontuacao_planilha}, "
                        f"mas a obtida pelo Kahoot é {pontuacao_kahoot}."
                    )
                    print(f"  ⚠️  {msg}")
                    divergencias[nome_kahoot] = (
                        f"Planilha={pontuacao_planilha} vs Kahoot={pontuacao_kahoot} ({nome_quiz})"
                    )
            else:
                # Célula vazia: nota pronta para ser inserida
                print(f"  ➕ {nome_exibicao}: inserindo pontuação {pontuacao_kahoot}.")
                atualizacoes.append(
                    gspread.Cell(row=linha_aluno, col=col_dest_idx, value=pontuacao_kahoot)
                )
        else:
            nao_identificados.append([nome_kahoot, pontuacao_kahoot, nome_quiz])

    return atualizacoes, nao_identificados, divergencias


def integrar_com_google_sheets(
    dados_alunos,
    nome_planilha=PLANILHA_NOME_DEFAULT,
    credentials_file="credentials.json",
    kahoot_padrao="",
    modo_nuvem=False,
):
    """Conecta ao Google Sheets via gspread e atualiza notas, quarentena e auditoria."""
    print(f"\n--- Conectando ao Google Sheets: '{nome_planilha}' ---")
    worksheet, sh = _obter_worksheet(nome_planilha, credentials_file)

    valores_tabela = worksheet.get_all_values()
    if not valores_tabela:
        print("A planilha está vazia!")
        return

    col_dest_idx, nome_quiz = _encontrar_coluna_destino(valores_tabela, nome_relatorio=kahoot_padrao)
    nome_quiz_limpo = nome_quiz.replace("\n", " ").strip()
    print(f"🎯 Coluna destino identificada: Coluna {col_dest_idx} ('{nome_quiz_limpo}')")

    motivo_incompativel = _validar_coluna_destino(
        nome_quiz, kahoot_padrao, col_dest_idx
    )
    if motivo_incompativel:
        print(f"❌ Validação falhou: {motivo_incompativel}")
        _salvar_dados_duplicados(sh, dados_alunos, motivo_incompativel)
        return

    mapa_linhas_alunos = _mapear_alunos_planilha(valores_tabela)
    atualizacoes, nao_identificados, divergencias = _preparar_atualizacoes_notas(
        dados_alunos, mapa_linhas_alunos, col_dest_idx, nome_quiz, valores_tabela, modo_nuvem=modo_nuvem
    )

    if atualizacoes:
        worksheet.update_cells(atualizacoes)
        print(
            f"✅ Sucesso! {len(atualizacoes)} nova(s) nota(s) inserida(s) na coluna {col_dest_idx} ('{nome_quiz_limpo}')."
        )
    else:
        print(f"ℹ️ Nenhuma nova célula vazia precisou ser atualizada na coluna {col_dest_idx}.")

    if divergencias:
        _salvar_dados_duplicados(
            sh,
            {aluno: dados_alunos[aluno] for aluno in divergencias},
            motivo="Divergência de nota entre Kahoot e Planilha",
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
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    # Verifica se estamos na nuvem
    modo_nuvem = os.getenv("CI") == "true" or not sys.stdout.isatty()

    if not modo_nuvem:
        # Usa perfil local específico para Kahoot na pasta do projeto, evitando problemas de permissão
        script_dir = os.path.dirname(os.path.abspath(__file__))
        perfil_automacao = os.getenv(
            "CHROME_PROFILE_PATH", os.path.join(script_dir, ".chrome_profile")
        )
        os.makedirs(perfil_automacao, exist_ok=True)
        options.add_argument(f"--user-data-dir={perfil_automacao}")

    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        # Fallback inteligente: se o Selenium Manager falhar em resolver binários automaticamente
        user_home = os.path.expanduser("~")
        chrome_cached = f"{user_home}/.cache/selenium/chrome/linux64/153.0.8010.52/chrome"
        driver_cached = f"{user_home}/.cache/selenium/chromedriver/linux64/153.0.8010.52/chromedriver"
        if os.path.exists(chrome_cached) and os.path.exists(driver_cached):
            options.binary_location = chrome_cached
            service = Service(executable_path=driver_cached)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            raise e

    wait = WebDriverWait(driver, 25)
    return driver, wait


def _garantir_sessao_kahoot(driver):
    # TENTATIVA 1: Injeção de Cookies (Passe VIP)
    cookies_str = os.getenv("KAHOOT_COOKIES_JSON")
    if cookies_str and cookies_str.strip():
        print("🍪 Cookies detectados! Iniciando injeção de sessão...")
        try:
            # Acessa uma página leve e pública do domínio apenas para habilitar a injeção
            driver.get("https://kahoot.it/robots.txt")
            time.sleep(1)
            
            cookies_list = json.loads(cookies_str)
            for cookie in cookies_list:
                cookie_dict = {
                    'name': cookie['name'],
                    'value': cookie['value'],
                    'domain': cookie.get('domain', '.kahoot.it')
                }
                try:
                    driver.add_cookie(cookie_dict)
                except Exception:
                    pass
            
            print("✅ Sessão injetada com sucesso! Pulando o formulário de login.")
            return True
        except Exception as e:
            print(f"⚠️ Falha ao injetar cookies: {e}. Tentando login manual...")

    # TENTATIVA 2: Login Convencional (Fallback)
    try:
        driver.get("https://create.kahoot.it/auth/login")
        campo_usuario = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//input[@name='username' or @id='username']"))
        )
        precisa_logar = True
    except Exception:
        precisa_logar = False
        print("Sessão já estava válida na máquina!")

    if precisa_logar:
        print("Iniciando login com credenciais...")
        try:
            botao_cookie = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
            )
            botao_cookie.click()
            time.sleep(1)
        except Exception:
            pass

        usuario, senha = _validar_credenciais_kahoot()
        
        campo_usuario.click()
        campo_usuario.send_keys(usuario)
        time.sleep(0.5)
        
        campo_senha = driver.find_element(By.XPATH, "//input[@name='password' or @id='password']")
        campo_senha.click()
        campo_senha.send_keys(senha)
        time.sleep(0.5)

        botao_login = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//button[@type='submit' or contains(., 'Log in') or contains(., 'Entrar')]"))
        )
        driver.execute_script("arguments[0].click();", botao_login)
        print("Login submetido!")
        
        WebDriverWait(driver, 15).until(EC.url_changes(driver.current_url))
        return True

    return False


def _listar_relatorios_kahoot(driver, wait, kahoot_padrao):
    """Localiza todos os relatórios rolando a página até carregar a listagem completa e extrai texto e link."""
    print(f"Buscando relatórios com o padrão '{kahoot_padrao}'...")
    xpath_alvo = f"//*[contains(text(), '{kahoot_padrao}')]"
    try:
        wait.until(EC.presence_of_element_located((By.XPATH, xpath_alvo)))
    except Exception:
        return []

    # Rola a página para baixo incrementalmente para forçar o Kahoot a carregar toda a lista de relatórios (virtual DOM)
    for _ in range(6):
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(0.7)

    # Coleta todos os elementos de texto e tenta encontrar o link <a> correspondente
    elementos = driver.find_elements(By.XPATH, xpath_alvo)
    relatorios = []
    textos_vistos = set()

    for el in elementos:
        try:
            texto = el.text.strip()
            if not texto or kahoot_padrao.lower() not in texto.lower():
                continue
            if texto in textos_vistos:
                continue

            # Tenta pegar a URL direta do relatório (se houver tag <a> no elemento ou em um ancestral)
            href = None
            try:
                ancestral_link = el.find_elements(By.XPATH, "./ancestor-or-self::a[@href] | ./ancestor::tr//a[@href] | ./ancestor::div[contains(@class, 'row')]//a[@href]")
                if ancestral_link:
                    href = ancestral_link[0].get_attribute("href")
            except Exception:
                pass

            textos_vistos.add(texto)
            relatorios.append({"texto": texto, "href": href})
        except Exception:
            continue

    # Rola de volta ao topo
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)
    return relatorios


def _selecionar_opcao_relatorios(relatorios, modo_nuvem=False):
    """Exibe os relatórios identificados e solicita a escolha das opções no CLI."""
    total = len(relatorios)
    print("\n" + "=" * 60)
    print(f" 📋 RELATÓRIOS IDENTIFICADOS ({total} encontrado(s)):")
    print("=" * 60)
    for idx, item in enumerate(relatorios, start=1):
        print(f"  [{idx}] {item['texto']}")
    print("-" * 60)

    if modo_nuvem:
        print("☁️ Modo nuvem: selecionando automaticamente o mais recente.")
        return "processar", [relatorios[0]]

    print(" Escolha uma das opções:")
    print("  [1] Processar apenas o mais recente")
    print("  [2] Processar o mais recente e N atrasados")
    print("  [3] Processar TODOS os identificados com essa nomenclatura")
    print("  [4] Gerar/Treinar Dicionário com TODOS os relatórios passados")
    print("  [5] Escolher UMA LIÇÃO ESPECÍFICA para treinar o dicionário")
    print("  [0] Sair")
    print("-" * 60)

    while True:
        opcao = input("Digite a opção desejada [1, 2, 3, 4, 5 ou 0]: ").strip()
        if opcao == "0":
            print("Operação cancelada pelo usuário.")
            sys.exit(0)
        elif opcao == "1":
            return "processar", [relatorios[0]]
        elif opcao == "2":
            while True:
                num_str = input(
                    f"Quantos relatórios atrasados além do mais recente? (1 a {max(1, total - 1)}): "
                ).strip()
                try:
                    num_atrasados = int(num_str)
                    if num_atrasados >= 0:
                        qtd_total = min(num_atrasados + 1, total)
                        selecionados = relatorios[:qtd_total]
                        selecionados.reverse()
                        return "processar", selecionados
                    else:
                        print("Por favor, digite um número maior ou igual a 0.")
                except ValueError:
                    print("Número inválido.")
        elif opcao == "3":
            selecionados = list(relatorios)
            selecionados.reverse()
            return "processar", selecionados
        elif opcao == "4":
            selecionados = list(relatorios)
            selecionados.reverse()
            return "treinar", selecionados
        elif opcao == "5":
            while True:
                num_str = input(f"Digite o número da lição desejada (1 a {total}): ").strip()
                try:
                    num_escolhido = int(num_str)
                    if 1 <= num_escolhido <= total:
                        escolhido = relatorios[num_escolhido - 1]
                        return "treinar", [escolhido]
                    else:
                        print(f"Por favor, digite um número entre 1 e {total}.")
                except ValueError:
                    print("Número inválido.")
        else:
            print("Opção inválida. Digite 1, 2, 3, 4, 5 ou 0.")


def _treinar_dicionario_com_relatorio(dados_alunos, nome_rel, nome_planilha):
    """Varre um relatório passado e sugere mapeamento de apelidos baseado nas notas da planilha."""
    print(f"\n🧠 Analisando correspondências de pontuação para o relatório: '{nome_rel}'...")
    worksheet, sh = _obter_worksheet(nome_planilha, "credentials.json")
    valores_tabela = worksheet.get_all_values()
    if not valores_tabela:
        return

    col_dest_idx, nome_quiz = _encontrar_coluna_destino(valores_tabela, nome_relatorio=nome_rel)
    mapa_linhas_alunos = _mapear_alunos_planilha(valores_tabela)
    dicionario_nomes = _carregar_dicionario_nomes()

    novos_mapeamentos = 0
    for nome_kahoot, pontuacao_kahoot in dados_alunos.items():
        nome_normalizado = _normalizar_texto(nome_kahoot)
        if nome_normalizado in dicionario_nomes or nome_normalizado in mapa_linhas_alunos:
            continue

        candidato = _identificar_aluno_por_pontuacao(
            pontuacao_kahoot, col_dest_idx, valores_tabela, mapa_linhas_alunos
        )
        if candidato:
            candidato_norm, candidato_oficial = candidato
            print(f"\n💡 [Correspondência Encontrada] No '{nome_quiz}', '{nome_kahoot}' fez {pontuacao_kahoot} pts.")
            print(f"   Na planilha, '{candidato_oficial}' tem exatamente {pontuacao_kahoot} pts nessa mesma coluna.")
            resp = input(f"   Deseja adicionar '{nome_kahoot}' -> '{candidato_oficial}' ao dicionário? [S/n]: ").strip().lower()
            if resp in ["", "s", "sim", "y", "yes"]:
                _salvar_entrada_dicionario(nome_kahoot, candidato_oficial)
                dicionario_nomes[_normalizar_texto(nome_kahoot)] = (nome_kahoot, candidato_oficial)
                novos_mapeamentos += 1

    if novos_mapeamentos == 0:
        print("  ℹ️ Nenhuma nova correspondência não mapeada encontrada neste relatório.")


def _abrir_relatorio_por_item(driver, wait, item_relatorio):
    """Abre o relatório usando o campo de pesquisa interno do Kahoot e seletores nativos de título."""
    texto_relatorio = item_relatorio["texto"]
    print(f"\n📂 Abrindo relatório: '{texto_relatorio}'...")

    # Extrai o termo de busca (ex: "3 - Resgate")
    texto_busca = texto_relatorio.split("(")[0].strip()

    # Extrai número do relatório para desambiguação (ex: '2' em '2 - Resgate', para não pegar '12 - Resgate')
    match_num = re.search(r"\b(\d+)\b", texto_relatorio)
    num_esperado = match_num.group(1) if match_num else None

    # 1. Usa o campo de busca nativo do Kahoot para filtrar o relatório
    try:
        campo_pesquisa = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//input[@placeholder='Pesquisar' or @placeholder='Search'] | //input[@type='search']",
                )
            )
        )
        campo_pesquisa.click()
        campo_pesquisa.send_keys(Keys.CONTROL + "a")
        campo_pesquisa.send_keys(Keys.BACKSPACE)
        time.sleep(0.3)
        campo_pesquisa.send_keys(texto_busca)
        campo_pesquisa.send_keys(Keys.ENTER)
        time.sleep(2)
    except Exception as e:
        print(f"Aviso ao usar campo de pesquisa: {e}")

    # 2. Localiza os títulos usando o seletor funcional nativo do Kahoot
    xpath_titulos = "//*[@data-functional-selector='reports-list__row__title'] | //div[contains(@class, 'Title-sc-')]"
    titles = []
    try:
        titles = WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((By.XPATH, xpath_titulos))
        )
    except Exception:
        pass

    elemento = None

    # Prioridade 1: Match exato de texto
    for t in titles:
        if t.text.strip() == texto_relatorio:
            elemento = t
            break

    # Prioridade 2: Match com número exato do quiz (evita '2' casar com '12')
    if not elemento and num_esperado:
        for t in titles:
            txt = t.text.strip()
            match_t = re.search(r"\b(\d+)\b", txt)
            if match_t and match_t.group(1) == num_esperado and texto_busca.lower() in txt.lower():
                elemento = t
                break

    # Prioridade 3: Match parcial com texto_busca
    if not elemento:
        for t in titles:
            if texto_busca.lower() in t.text.lower():
                elemento = t
                break

    # Prioridade 4: Se só houver 1 linha filtrada, usa ela
    if not elemento and len(titles) == 1:
        elemento = titles[0]

    if not elemento:
        raise Exception(
            f"Não foi possível localizar o relatório '{texto_relatorio}' na lista filtrada do Kahoot."
        )

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento)
    time.sleep(0.5)

    aba_principal = driver.current_window_handle
    try:
        elemento.click()
    except Exception:
        driver.execute_script("arguments[0].click();", elemento)

    time.sleep(2)
    if len(driver.window_handles) > 1:
        for handle in driver.window_handles:
            if handle != aba_principal:
                driver.switch_to.window(handle)
                break

    # Aguarda a página do relatório carregar
    try:
        wait.until(EC.url_contains("/reports/"))
    except Exception:
        pass

    wait.until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                "//*[contains(translate(text(), 'PARTICIPANTES', 'participantes'), 'participante') or contains(translate(text(), 'PLAYERS', 'players'), 'player')]",
            )
        )
    )
    print("Relatório carregado com sucesso!")


def main(kahoot_padrao=None, planilha_nome=None):
    modo_nuvem = os.getenv("CI") == "true" or not sys.stdout.isatty()
    if not kahoot_padrao or not planilha_nome:
        kahoot_padrao, planilha_nome = _obter_configuracoes_interativas()

    driver, wait = _inicializar_driver()

    try:
        url_lista = "https://create.kahoot.it/user-reports/hosted-by-me/list/?searchMode=host&globalFilter=liveGame&orderBy=time&reverse=true"
        print("Acessando a lista de relatórios...")
        driver.get(url_lista)

        fez_login = _garantir_sessao_kahoot(driver)
        if fez_login:
            print("Redirecionando de volta para a lista de relatórios após o login...")
            driver.get(url_lista)
            time.sleep(3)

        relatorios_encontrados = _listar_relatorios_kahoot(driver, wait, kahoot_padrao)
        if not relatorios_encontrados:
            print(f"❌ Nenhum relatório encontrado com o padrão '{kahoot_padrao}'.")
            return

        acao, relatorios_para_processar = _selecionar_opcao_relatorios(
            relatorios_encontrados, modo_nuvem=modo_nuvem
        )

        titulo_bloco = "TREINAMENTO DE DICIONÁRIO" if acao == "treinar" else "PROCESSAMENTO DE NOTAS"
        print("\n" + "=" * 60)
        print(f"🚀 INICIANDO {titulo_bloco} ({len(relatorios_para_processar)} RELATÓRIO(S)):")
        for idx, r in enumerate(relatorios_para_processar, start=1):
            print(f"  {idx}º -> {r['texto']}")
        print("=" * 60)

        aba_lista = driver.current_window_handle

        for idx, item_rel in enumerate(relatorios_para_processar, start=1):
            nome_rel = item_rel["texto"]
            print(f"\n[{idx}/{len(relatorios_para_processar)}] Acessando: '{nome_rel}'")

            # Fecha abas adicionais que o relatório anterior tenha deixado abertas
            while len(driver.window_handles) > 1:
                for handle in driver.window_handles:
                    if handle != aba_lista:
                        driver.switch_to.window(handle)
                        driver.close()
                driver.switch_to.window(aba_lista)

            driver.switch_to.window(aba_lista)

            # Sempre volta para a lista limpa (sem query params de busca anterior)
            driver.get(url_lista)
            time.sleep(3)

            _abrir_relatorio_por_item(driver, wait, item_rel)
            dados_raspados = extrair_dados_kahoot(driver, wait)

            if dados_raspados:
                if acao == "treinar":
                    _treinar_dicionario_com_relatorio(dados_raspados, nome_rel, planilha_nome)
                else:
                    integrar_com_google_sheets(
                        dados_alunos=dados_raspados,
                        nome_planilha=planilha_nome,
                        kahoot_padrao=nome_rel,
                        modo_nuvem=modo_nuvem,
                    )
            else:
                print(f"⚠️ Nenhum dado capturado no relatório '{nome_rel}'.")

        if acao == "treinar":
            print("\n🎉 Treinamento do dicionário concluído! O arquivo 'nomes_kahoot.json' está pronto.")
        else:
            print("\n🎉 Todos os relatórios selecionados foram processados com sucesso!")

    except Exception as e:
        print(f"\n❌ Ocorreu um erro no fluxo: {e}")
        try:
            print(f"🔗 URL no momento do erro: {driver.current_url}")
            print(f"📄 Título da página: {driver.title}")
            driver.save_screenshot("erro_kahoot.png")
            print("📸 Screenshot salvo com sucesso como 'erro_kahoot.png'")
        except Exception as ex:
            print(f"⚠️ Não foi possível capturar o status da tela: {ex}")

        # Força o encerramento do script com status de erro para o GitHub Actions
        sys.exit(1)
    finally:
        driver.quit()


if __name__ == "__main__":
    print("\n--- Configuração da Execução ---")

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

