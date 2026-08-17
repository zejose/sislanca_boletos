"""
SISLANÇA -> Informativo em PDF (versão final v2)
====================================================
- Login no sislanca + consulta por número + entra no detalhe
- Filtra cotas: só entram as com Situação = "00" (em aberto) E número de
  cota entre 1 e 12 (ignora cota única/códigos especiais, ex.: 89)
- Baixa o boleto oficial (PDF) de cada cota válida
- LÊ o texto de cada PDF baixado e extrai a linha digitável de dentro dele
- Desenha um PDF final próprio, com uma ficha por cota mostrando parcela,
  vencimento, valor e o código de barras (a partir da linha digitável real,
  extraída do boleto oficial — não inventada)
- Salva em C:\PP\<numero_sislanca>.pdf

INSTALAÇÃO
----------
    pip install playwright beautifulsoup4 python-dotenv reportlab pypdf pdfplumber
    playwright install chromium

CONFIGURAÇÃO (.env na mesma pasta)
-----------------------------------
    SISLANCA_BASE_URL=https://sislanca.fazenda.df.gov.br
    SISLANCA_USER=000.000.000-00      # CPF formatado, com pontos e traço
    SISLANCA_PASS=sua_senha
    SISLANCA_HEADLESS=false

USO
---
    python sislanca_pdf_final2.py
    (pergunta o número sislanca no console)
"""

import os
import re
import sys
import shutil
import tempfile
from datetime import date

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from pypdf import PdfWriter, PdfReader
import pdfplumber

load_dotenv()

BASE_URL = os.environ.get("SISLANCA_BASE_URL", "https://sislanca.fazenda.df.gov.br").rstrip("/")
LOGIN_URL = f"{BASE_URL}/login"
USUARIO = os.environ.get("SISLANCA_USER")
SENHA = os.environ.get("SISLANCA_PASS")
HEADLESS = os.environ.get("SISLANCA_HEADLESS", "true").lower() != "false"

PASTA_SAIDA = r"C:\PP"

NAVY = (0x14 / 255, 0x21 / 255, 0x3D / 255)
STEEL = (0x4A / 255, 0x55 / 255, 0x68 / 255)
COPPER = (0xB5 / 255, 0x65 / 255, 0x1D / 255)
LINE = (0xD8 / 255, 0xDC / 255, 0xE3 / 255)
PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


# =====================================================================
# Código de barras ITF (Interleaved 2 of 5) — usado em boletos
# =====================================================================

ITF_PATTERNS = {
    "0": "NNWWN", "1": "WNNNW", "2": "NWNNW", "3": "WWNNN", "4": "NNWNW",
    "5": "WNWNN", "6": "NWWNN", "7": "NNNWW", "8": "WNNWN", "9": "NWNWN",
}


def only_digits(s):
    return re.sub(r"\D", "", s or "")


def format_linha_digitavel(raw):
    digits = only_digits(raw)
    if len(digits) == 47:
        g1 = digits[0:5] + "." + digits[5:10]
        g2 = digits[10:15] + "." + digits[15:21]
        g3 = digits[21:26] + "." + digits[26:32]
        g4 = digits[32:33]
        g5 = digits[33:47]
        return f"{g1}  {g2}  {g3}  {g4}  {g5}"
    return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def encode_itf_bars(digits):
    if len(digits) % 2 != 0:
        digits = "0" + digits
    bars = [
        {"type": "bar", "wide": False}, {"type": "space", "wide": False},
        {"type": "bar", "wide": False}, {"type": "space", "wide": False},
    ]
    for i in range(0, len(digits), 2):
        d1, d2 = digits[i], digits[i + 1]
        if d1 not in ITF_PATTERNS or d2 not in ITF_PATTERNS:
            return None
        p1, p2 = ITF_PATTERNS[d1], ITF_PATTERNS[d2]
        for j in range(5):
            bars.append({"type": "bar", "wide": p1[j] == "W"})
            bars.append({"type": "space", "wide": p2[j] == "W"})
    bars += [
        {"type": "bar", "wide": True}, {"type": "space", "wide": False},
        {"type": "bar", "wide": False},
    ]
    return bars


def linha_para_codigo_barras(linha_digitavel):
    """Converte a linha digitável (47 dígitos) no código de barras (44 dígitos)."""
    digits = only_digits(linha_digitavel)
    if len(digits) == 44:
        return digits
    if len(digits) == 47:
        campo1 = digits[0:9]
        campo2 = digits[10:20]
        campo3 = digits[21:31]
        dv_geral = digits[32:33]
        campo5 = digits[33:47]
        banco_moeda = campo1[0:4]
        campo_livre = campo1[4:9] + campo2 + campo3
        return banco_moeda + dv_geral + campo5 + campo_livre
    return None


def draw_barcode(c, digits, x, y, width, height):
    bars = encode_itf_bars(digits)
    if not bars:
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.7, 0.1, 0.1)
        c.drawString(x, y + height / 2, "Código de barras inválido")
        return False
    narrow, wide = 1.0, 2.5
    total_units = sum(wide if b["wide"] else narrow for b in bars)
    scale = width / total_units
    c.saveState()
    c.setFillColorRGB(0, 0, 0)
    cursor = x
    for el in bars:
        w = (wide if el["wide"] else narrow) * scale
        if el["type"] == "bar":
            c.rect(cursor, y, w, height, fill=1, stroke=0)
        cursor += w
    c.restoreState()
    return True


# =====================================================================
# Login / navegação (SPA em Angular)
# =====================================================================

def fechar_popup_se_existir(page):
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    candidatos_fechar = [
        "button:has-text('Pular')", "button:has-text('Fechar')",
        "[aria-label='Close']", "[aria-label='Fechar']",
        ".tg-dialog-close", ".p-dialog-header-close",
    ]
    for sel in candidatos_fechar:
        loc = page.locator(sel).first
        if loc.count() > 0:
            try:
                loc.click(timeout=2000)
                page.wait_for_timeout(500)
                return
            except Exception:
                pass
    next_btn = page.locator("#tg-dialog-next-btn")
    tentativas = 0
    while next_btn.count() > 0 and next_btn.first.is_visible() and tentativas < 15:
        try:
            next_btn.first.click(timeout=1500)
            page.wait_for_timeout(400)
        except Exception:
            break
        tentativas += 1


def login(page):
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    fechar_popup_se_existir(page)

    cpf_field = page.locator("#cpf")
    cpf_field.click()
    cpf_field.fill("")
    cpf_field.press_sequentially(USUARIO, delay=40)

    senha_field = page.locator("input[type='password']").first
    senha_field.click()
    senha_field.fill("")
    senha_field.press_sequentially(SENHA, delay=40)

    page.locator("button[data-cy='submit-login-form']").click()
    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    except Exception:
        raise RuntimeError("Login não completou (CPF/senha incorretos ou tela mudou).")

    page.wait_for_timeout(3000)
    fechar_popup_se_existir(page)
    page.wait_for_timeout(1500)


def consultar_lancamento(page, codigo):
    numero_field = page.locator("#numeroLancamento")
    numero_field.click()
    numero_field.fill("")
    numero_field.press_sequentially(codigo, delay=40)
    page.locator("#btn-consultar").click()
    page.wait_for_timeout(4000)

    detalhar_btn = page.locator("[data-cy='detalhar-lancamento-nav-btn']").first
    if detalhar_btn.count() == 0:
        raise RuntimeError(f"Não encontrei resultado para o número '{codigo}'.")
    detalhar_btn.click()
    page.wait_for_timeout(3000)


# =====================================================================
# Extração dos dados da página de detalhe
# =====================================================================

def parse_dados_debito(texto):
    campos = [
        "Nº do Lançamento", "Nome", "CPF/CNPJ", "Quantidade de Cotas",
        "Órgão Gerador", "Situação", "Código da Receita",
    ]
    resultado = {}
    for campo in campos:
        m = re.search(re.escape(campo) + r":\s*\n(.+)", texto)
        if m:
            resultado[campo] = m.group(1).strip()
    return resultado


def ler_dados_e_cotas(page):
    """Retorna (dados, cotas_validas). Só entram cotas com:
    - Situação == '00' (em aberto)
    - número da cota entre 1 e 12 (ignora cota única / códigos especiais)"""
    dados_div = page.locator("[data-cy='dados-debito-div']").first
    texto = dados_div.inner_text() if dados_div.count() else ""
    dados = parse_dados_debito(texto)

    tabela = page.locator("[data-cy='consultar-debitos-table']").first
    linhas = tabela.locator("tbody tr").all()
    cotas_validas = []
    for idx_linha, row in enumerate(linhas):
        cells = row.locator("td").all()
        textos = [td.inner_text().strip().replace("\xa0", " ") for td in cells]
        if len(textos) < 7:
            continue
        cota_num, situacao = textos[0], textos[1]

        try:
            n = int(re.sub(r"\D", "", cota_num) or "-1")
        except ValueError:
            n = -1
        if not (1 <= n <= 12):
            print(f"Ignorando cota '{cota_num}' (fora do intervalo 1-12).", flush=True)
            continue
        if situacao.strip() != "00":
            print(f"Ignorando cota '{cota_num}' (situação '{situacao}', "
                  f"só cotas em aberto '00' geram boleto).", flush=True)
            continue

        cotas_validas.append({
            "idx_linha": idx_linha,
            "cota": cota_num,
            "situacao": situacao,
            "vencimento": textos[2],
            "valor_total": textos[6],
        })
    return dados, cotas_validas


def baixar_boletos(page, pasta_destino, cotas_validas):
    """Clica em 'Emitir boleto' só das linhas válidas, salva o PDF de cada
    uma e devolve a mesma lista de cotas com 'caminho_pdf' preenchido."""
    botoes = page.locator("[data-cy='emitir-boleto-btn']")
    for cota in cotas_validas:
        idx = cota["idx_linha"]
        with page.expect_download(timeout=20000) as download_info:
            botoes.nth(idx).click()
        download = download_info.value
        caminho = os.path.join(pasta_destino, f"boleto_cota_{cota['cota']}.pdf")
        download.save_as(caminho)
        cota["caminho_pdf"] = caminho
        page.wait_for_timeout(600)
    return cotas_validas


# =====================================================================
# Extração da linha digitável de dentro do PDF baixado
# =====================================================================

REGEX_LINHA_ESTRITA = re.compile(
    r"\d{5}\.\d{5}\s+\d{5}\.\d{6}\s+\d{5}\.\d{6}\s+\d\s+\d{14}"
)


def extrair_texto_pdf(caminho_pdf):
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        reader = PdfReader(caminho_pdf)
        return "\n".join((p.extract_text() or "") for p in reader.pages)


def extrair_linha_digitavel(caminho_pdf):
    texto = extrair_texto_pdf(caminho_pdf)

    m = REGEX_LINHA_ESTRITA.search(texto)
    if m:
        return m.group(0)

    for candidato in re.findall(r"[\d\.\s]{40,90}", texto):
        digitos = only_digits(candidato)
        if len(digitos) == 47:
            return candidato.strip()

    return None


# =====================================================================
# Montagem do PDF final (uma ficha por cota, com código de barras real)
# =====================================================================

def _header(c, num_lancamento, interessado, num_cotas):
    c.setFillColorRGB(*NAVY)
    c.rect(0, PAGE_H - 28 * mm, PAGE_W, 28 * mm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGIN, PAGE_H - 14 * mm, "Informativo de Cotas")
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.73, 0.77, 0.86)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 11 * mm,
                       f"Emitido em {date.today().strftime('%d/%m/%Y')}")
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 16 * mm, "SISLANÇA")

    y = PAGE_H - 40 * mm
    campos = [
        ("Nº DE LANÇAMENTO", num_lancamento),
        ("Nº DE COTAS", num_cotas),
        ("INTERESSADO", interessado),
    ]
    for lab, val in campos:
        c.setFillColorRGB(*STEEL)
        c.setFont("Helvetica", 7.5)
        c.drawString(MARGIN, y, lab)
        c.setFillColorRGB(*NAVY)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(MARGIN, y - 12, str(val)[:90])
        y -= 26
    return y - 6


def _perforation(c, y):
    c.setDash(3, 3)
    c.setStrokeColorRGB(*LINE)
    c.setLineWidth(1)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    c.setDash()


def _ticket(c, y_top, cota):
    y = y_top
    c.setFillColorRGB(*STEEL)
    c.setFont("Helvetica", 7)
    c.drawString(MARGIN, y, "VIA DO SISTEMA")
    y -= 14

    col_w = (PAGE_W - 2 * MARGIN) / 3
    fields = [
        ("PARCELA / COTA", cota["cota"]),
        ("VENCIMENTO", cota["vencimento"]),
        ("VALOR", cota["valor_total"]),
    ]
    for i, (lab, val) in enumerate(fields):
        x = MARGIN + i * col_w
        c.setFillColorRGB(*STEEL)
        c.setFont("Helvetica", 7.5)
        c.drawString(x, y, lab)
        c.setFillColorRGB(*(COPPER if lab == "VALOR" else NAVY))
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x, y - 13, str(val))
    y -= 30

    _perforation(c, y)
    y -= 14

    c.setFillColorRGB(*STEEL)
    c.setFont("Helvetica", 7)
    c.drawString(MARGIN, y, "VIA PARA ENVIO AO INTERESSADO")
    y -= 16

    barcode_h = 16 * mm
    codigo_barras = linha_para_codigo_barras(cota["linha_digitavel"])
    if codigo_barras:
        draw_barcode(c, codigo_barras, MARGIN, y - barcode_h, PAGE_W - 2 * MARGIN, barcode_h)
    else:
        c.setFillColorRGB(0.7, 0.1, 0.1)
        c.setFont("Helvetica", 9)
        c.drawString(MARGIN, y - barcode_h / 2, "Não foi possível ler o código de barras deste boleto.")
    y -= (barcode_h + 12)

    c.setFont("Courier", 9)
    c.setFillColorRGB(*NAVY)
    c.drawString(MARGIN, y, format_linha_digitavel(cota["linha_digitavel"]))
    y -= 20
    return y


def gerar_pdf_fichas(caminho_saida, dados, cotas_com_linha):
    c = canvas.Canvas(caminho_saida, pagesize=A4)
    y = _header(c, dados.get("Nº do Lançamento", "—"),
                dados.get("Nome", "—"),
                dados.get("Quantidade de Cotas", str(len(cotas_com_linha))))

    for cota in cotas_com_linha:
        if y - 130 < MARGIN:
            c.showPage()
            y = PAGE_H - MARGIN
        y = _ticket(c, y, cota)
        y -= 10

    c.save()


def montar_pdf_final(caminho_saida, caminho_fichas, caminhos_fallback):
    """Junta as fichas desenhadas + (se houver) os PDFs originais de cotas
    cuja linha digitável não pôde ser extraída (fallback de segurança,
    pra nunca perder um boleto)."""
    writer = PdfWriter()
    reader = PdfReader(caminho_fichas)
    for pagina in reader.pages:
        writer.add_page(pagina)

    for caminho in caminhos_fallback:
        reader = PdfReader(caminho)
        for pagina in reader.pages:
            writer.add_page(pagina)

    with open(caminho_saida, "wb") as f:
        writer.write(f)


# =====================================================================
# MAIN
# =====================================================================

def main():
    if not USUARIO or not SENHA:
        print("Defina SISLANCA_USER e SISLANCA_PASS no .env.", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("SISLANCA_BASE_URL"):
        print("Defina SISLANCA_BASE_URL no .env.", file=sys.stderr)
        sys.exit(1)

    codigo = input("Digite o número sislanca do lançamento: ").strip()
    if not codigo:
        print("Número não informado.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    caminho_final = os.path.join(PASTA_SAIDA, f"{codigo}.pdf")

    pasta_temp = tempfile.mkdtemp(prefix="sislanca_")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        print("Fazendo login...", flush=True)
        login(page)
        print("Login OK.", flush=True)

        print(f"Consultando lançamento {codigo}...", flush=True)
        consultar_lancamento(page, codigo)

        print("Lendo dados do contribuinte e das cotas...", flush=True)
        dados, cotas = ler_dados_e_cotas(page)
        print(f"Interessado: {dados.get('Nome', '?')} | Cotas válidas: {len(cotas)}", flush=True)

        if not cotas:
            print("Nenhuma cota em aberto (status 00) encontrada no intervalo 1-12. Nada a gerar.",
                  file=sys.stderr)
            shutil.rmtree(pasta_temp, ignore_errors=True)
            sys.exit(1)

        print("Baixando os boletos oficiais de cada cota...", flush=True)
        cotas = baixar_boletos(page, pasta_temp, cotas)

        browser.close()

    print("Lendo a linha digitável de dentro de cada boleto baixado...", flush=True)
    caminhos_fallback = []
    for cota in cotas:
        linha = extrair_linha_digitavel(cota["caminho_pdf"])
        cota["linha_digitavel"] = linha
        if linha:
            print(f"  Cota {cota['cota']}: linha digitável OK.", flush=True)
        else:
            print(f"  Cota {cota['cota']}: NÃO consegui ler a linha digitável — "
                  f"o boleto original dessa cota será anexado como está.", flush=True)
            caminhos_fallback.append(cota["caminho_pdf"])

    cotas_com_linha = [c for c in cotas if c.get("linha_digitavel")]

    print("Montando o PDF com as fichas de cada cota...", flush=True)
    caminho_fichas = os.path.join(pasta_temp, "fichas.pdf")
    gerar_pdf_fichas(caminho_fichas, dados, cotas_com_linha)

    print("Montando o PDF final...", flush=True)
    montar_pdf_final(caminho_final, caminho_fichas, caminhos_fallback)

    shutil.rmtree(pasta_temp, ignore_errors=True)

    print(f"\nPDF final gerado em: {caminho_final}", flush=True)
    input("\nPressione Enter para fechar...")


if __name__ == "__main__":
    main()