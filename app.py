import os
import re
import time
import unicodedata
from dotenv import load_dotenv, set_key
import gspread
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()


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
    caminho_credenciais = os.getenv("GOOGLE_CREDENTIALS_PATH", credentials_file)
    if not os.path.exists(caminho_credenciais):
        raise FileNotFoundError(
            f"Arquivo de credenciais do Google não encontrado em: {caminho_credenciais}"
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


def integrar_com_google_sheets(
    dados_alunos,
    nome_planilha="Cópia de Resgate_Desempenho",
    credentials_file="credentials.json",
):
    """Conecta ao Google Sheets via gspread e atualiza notas e quarentena."""
    print(f"\n--- Conectando ao Google Sheets: '{nome_planilha}' ---")
    worksheet, sh = _obter_worksheet(nome_planilha, credentials_file)

    valores_tabela = worksheet.get_all_values()
    if not valores_tabela:
        print("A planilha está vazia!")
        return

    col_dest_idx, nome_quiz = _encontrar_coluna_destino(valores_tabela)
    print(f"🎯 Coluna destino identificada: Coluna {col_dest_idx} ('{nome_quiz}')")

    mapa_linhas_alunos = _mapear_alunos_planilha(valores_tabela)

    atualizacoes_celulas = []
    nao_identificados = []

    for nome_kahoot, pontuacao in dados_alunos.items():
        nome_normalizado = _normalizar_texto(nome_kahoot)
        if nome_normalizado in mapa_linhas_alunos:
            linha_aluno = mapa_linhas_alunos[nome_normalizado]
            atualizacoes_celulas.append(
                gspread.Cell(row=linha_aluno, col=col_dest_idx, value=pontuacao)
            )
        else:
            nao_identificados.append([nome_kahoot, pontuacao, nome_quiz])

    if atualizacoes_celulas:
        worksheet.update_cells(atualizacoes_celulas)
        print(
            f"✅ Sucesso! {len(atualizacoes_celulas)} nota(s) inserida(s) na coluna {col_dest_idx} ('{nome_quiz}')."
        )

    if nao_identificados:
        _salvar_quarentena(sh, nao_identificados)


def _obter_configuracoes_interativas():
    env_path = ".env"
    kahoot_padrao = os.getenv("KAHOOT_PADRAO", " - Resgate")
    planilha_nome = os.getenv("PLANILHA_NOME", "Cópia de Resgate_Desempenho")

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

    user_home = os.path.expanduser("~")
    chrome_profile_path = os.getenv(
        "CHROME_PROFILE_PATH", f"{user_home}/.config/google-chrome"
    )

    options.add_argument(f"--user-data-dir={chrome_profile_path}")
    options.add_argument(r"--profile-directory=Default")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)
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


def _navegar_para_relatorio(driver, wait, kahoot_padrao):
    print("Acessando a lista de relatórios...")
    url_lista = "https://create.kahoot.it/user-reports/hosted-by-me/list/?searchMode=host&globalFilter=liveGame&orderBy=time&reverse=true"
    driver.get(url_lista)

    _garantir_sessao_kahoot(driver)

    print(f"Buscando o relatório mais recente com o padrão '{kahoot_padrao}'...")
    primeiro_relatorio = wait.until(
        EC.presence_of_element_located(
            (By.XPATH, f"(//*[contains(text(), '{kahoot_padrao}')])[1]")
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


def main():
    kahoot_padrao, planilha_nome = _obter_configuracoes_interativas()
    driver, wait = _inicializar_driver()

    try:
        _navegar_para_relatorio(driver, wait, kahoot_padrao)
        dados_raspados = extrair_dados_kahoot(driver, wait)

        if dados_raspados:
            integrar_com_google_sheets(
                dados_alunos=dados_raspados, nome_planilha=planilha_nome
            )
    except Exception as e:
        print(f"\n❌ Ocorreu um erro no fluxo: {e}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
