r"""
SISLANCA -> Informativo em PDF (versão final v6)
=======================================================================
- Página 1: logo + carta explicativa + dados cadastrais do contribuinte
  + observações do lançamento (endereço, localização, decreto etc.)
- Páginas seguintes: fichas compactas, 6 cotas por página, cada uma com
  código de barras real (extraído da linha digitável de cada guia)

Salva em C:\PP\<numero_lancamento>.pdf

INSTALAÇÃO
----------
    pip install requests beautifulsoup4 reportlab

ARQUIVO NECESSÁRIO NA MESMA PASTA DO SCRIPT
---------------------------------------------
    logo_df_legal.jpg

USO
---
    python sislanca_pdf_v6.py
"""

import os
import re
import sys
import time
import glob
import subprocess
from datetime import date

import requests
from bs4 import BeautifulSoup
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas as canvas_mod
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, NextPageTemplate,
    Paragraph, Spacer, PageBreak, Flowable, Table, TableStyle, HRFlowable,
)

BASE_URL = "https://www2.agencianet.fazenda.df.gov.br/extranet.publica/GerarBoletoInternet"
PASTA_SAIDA = r"C:\PP"
ORGAO_DF_LEGAL = "092"  # órgão gerador dos lançamentos da DF Legal
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COTAS_POR_PAGINA = 6

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

NAVY = colors.HexColor("#0E1F45")
NAVY_2 = colors.HexColor("#16305E")
STEEL = colors.HexColor("#5A6472")
GOLD = colors.HexColor("#C9A227")
CARD_BG = colors.HexColor("#F7F8FB")
LINEC = colors.HexColor("#DDE2EA")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm

TITULO_CAPA = "Lançamento realizado pela DF Legal"

TEXTO_CARTA = """Olá!

Este comunicado está relacionado à cobrança do preço público devido pela ocupação de área pública pelo seu estabelecimento comercial, localizado no Comércio Local Sul, na Asa Sul, Plano Piloto.

A ocupação de área pública por estabelecimentos comerciais no Comercio Local Sul – CLS (os "puxadinhos da Asa Sul"), é regulamentada pela Lei Complementar nº 998, de 11 de janeiro de 2022 e pelo Decreto 43.609, de 1º de agosto de 2022. O preço público é a cobrança devida pela utilização desta área pública. O art. 16 da LC 998/2022 e o art. 30 do Decreto 43.609/2022 definem a competência da DF Legal para a cobrança do preço público e estabelecem a fórmula de cálculo das cobranças.

Ressaltamos que esta cobrança é independente daquela feita pelo IPTU. O IPTU abrange, eventualmente, toda a área construída do imóvel, ainda que proveniente de ocupação de área pública. O preço público restringe-se à cobrança de contraprestação pela utilização da área pública, que pertence ao Distrito Federal. A cobrança do IPTU, portanto, não dispensa a exigibilidade do pagamento do preço público.

Esta cobrança do preço público será feita todos os anos. Para contestar ou revisar a cobrança, procure um Núcleo de Atendimento ao Cidadão da DF Legal, cujos endereços estão disponíveis no site https://www.dflegal.df.gov.br/folder-locais-nucleos-de-atendimento-ao-cidadao.

O pagamento em dia do preço público é uma obrigação de todos que ocupam áreas públicas. O atraso no pagamento pode gerar medidas como multa e juros moratórios, inscrição em dívida ativa, protesto em cartório, a exclusão do Simples Nacional e, em casos de atrasos mais longos, até mesmo o ajuizamento de ação de execução. Evite transtornos para a sua atividade: pague o preço público em dia e, se tiver dificuldade para pagar, os débitos de anos anteriores podem ser parcelados junto à DF Legal.

Por fim, cabe ressaltar que o pagamento do preço público, apesar de ser uma obrigação a ser cumprida, não dispensa o particular de regularizar a sua ocupação de área pública. A regularização dos puxadinhos do Plano Piloto deve ser providenciada junto à Administração Regional do Plano Piloto. O pagamento do preço público não autoriza a ocupação nem isenta o particular de fiscalizações ligadas à regularidade da ocupação."""


# =====================================================================
# Localizar a logo
# =====================================================================

def localizar_selo():
    candidatos = []
    for nome in ["df_legal1.jpeg", "df_legal1.jpg", "df_legal_selo.png",
                 "selo_df_legal.png", "selo.png", "selo.jpg"]:
        candidatos.append(os.path.join(SCRIPT_DIR, nome))
        candidatos.append(os.path.join(os.getcwd(), nome))

    for caminho in candidatos:
        if os.path.exists(caminho):
            print(f"Selo encontrado em: {caminho}", flush=True)
            return caminho

    for pasta in {SCRIPT_DIR, os.getcwd()}:
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            for achado in glob.glob(os.path.join(pasta, ext)):
                nome_lower = os.path.basename(achado).lower()
                if "selo" in nome_lower or "df_legal1" in nome_lower:
                    print(f"Selo encontrado por busca ampla em: {achado}", flush=True)
                    return achado

    print("AVISO: não encontrei a logo/selo (opcional — aparece no canto de cada "
          "página de boletos). Procurei em:", flush=True)
    for c in candidatos[:6]:
        print(f"   - {c}", flush=True)
    print(f"Pasta do script: {SCRIPT_DIR}", flush=True)
    print(f"Pasta atual (cwd): {os.getcwd()}", flush=True)
    print("=> Salve o arquivo 'df_legal1.jpeg' (a bandeira com o selo da DF Legal) "
          "numa dessas pastas.", flush=True)
    return None


def gerar_marca_dagua(caminho_selo, opacidade=0.06):
    """Gera uma versão bem clara (baixa opacidade) do selo, usada como
    marca d'água decorativa na página 1. Retorna o caminho do arquivo
    temporário gerado, ou None se não for possível."""
    if not caminho_selo:
        return None
    try:
        from PIL import Image
        im = Image.open(caminho_selo).convert("RGBA")
        r, g, b, a = im.split()
        a = a.point(lambda px: int(px * opacidade))
        im_wm = Image.merge("RGBA", (r, g, b, a))
        destino = os.path.join(
            os.path.dirname(os.path.abspath(caminho_selo)), "_marca_dagua_tmp.png")
        im_wm.save(destino)
        return destino
    except Exception as e:
        print(f"(aviso: não consegui gerar a marca d'água: {e})", flush=True)
        return None


# =====================================================================
# Cabeçalho/rodapé padrão (faixa navy + filete dourado + logo), no
# mesmo modelo usado no sistema de Certidões/Histórico de Lançamentos
# =====================================================================

_LOGO_PROPORCAO = 1000 / 313  # largura/altura reais da logo retangular
_logo_reader_cache = {}


def _logo_reader(caminho_logo):
    """ImageReader da logo, decodificado uma única vez por caminho e
    reaproveitado — evita reabrir o arquivo em toda página do PDF."""
    if not caminho_logo:
        return None
    if caminho_logo not in _logo_reader_cache:
        try:
            from reportlab.lib.utils import ImageReader
            _logo_reader_cache[caminho_logo] = ImageReader(caminho_logo)
        except Exception:
            _logo_reader_cache[caminho_logo] = False
    return _logo_reader_cache[caminho_logo] or None


def _desenhar_faixa_topo(c, caminho_logo, titulo=None, fonte_titulo_max=15,
                          altura=32 * mm, compacta=False):
    """Desenha a faixa navy no topo da página — faixa full-width, filete
    dourado logo abaixo, logo oficial alinhada à direita e (opcional) um
    título em branco à esquerda, com auto-ajuste de fonte pra nunca
    colidir com a logo. Usada em toda página do documento: a primeira
    (com título e as linhas de identificação do órgão) e as demais, numa
    versão compacta (só a faixa + logo).

    Devolve o 'y' logo abaixo da faixa (e do filete dourado)."""
    if compacta:
        altura = 20 * mm

    c.saveState()
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - altura, PAGE_W, altura, fill=1, stroke=0)
    c.setFillColor(GOLD)
    filete_h = 1.1 * mm
    c.rect(0, PAGE_H - altura - filete_h, PAGE_W, filete_h, fill=1, stroke=0)

    logo_h = (10 if compacta else 13) * mm
    logo_w = logo_h * _LOGO_PROPORCAO
    logo_x = PAGE_W - MARGIN - logo_w
    logo_y = PAGE_H - (5 if compacta else 7) * mm - logo_h
    logo = _logo_reader(caminho_logo)
    if logo is not None:
        c.drawImage(logo, logo_x, logo_y, width=logo_w, height=logo_h,
                    preserveAspectRatio=True, mask="auto")

    if not compacta:
        hoje = date.today().strftime("%d/%m/%Y")
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.73, 0.77, 0.86)
        c.drawRightString(PAGE_W - MARGIN, logo_y - 7, "Governo do Distrito Federal")
        c.drawRightString(PAGE_W - MARGIN, logo_y - 16,
                           "Secretaria de Estado de Proteção da Ordem "
                           "Urbanística do Distrito Federal")
        c.drawRightString(PAGE_W - MARGIN, logo_y - 25, f"Emitido em {hoje}")

    if titulo:
        largura_disponivel = logo_x - MARGIN - 6 * mm
        fonte_titulo = fonte_titulo_max
        while (fonte_titulo > 9 and
               stringWidth(titulo, "Helvetica-Bold", fonte_titulo) > largura_disponivel):
            fonte_titulo -= 1
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", fonte_titulo)
        c.drawString(MARGIN, PAGE_H - 15 * mm, titulo)

    c.restoreState()
    return PAGE_H - altura - filete_h


def _desenhar_rodape_padrao(c, texto):
    """Rodapé padrão: filete dourado fino + texto informativo em itálico."""
    c.saveState()
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.8)
    c.line(MARGIN, MARGIN + 10, PAGE_W - MARGIN, MARGIN + 10)
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(STEEL)
    c.drawString(MARGIN, MARGIN, texto)
    c.restoreState()


def localizar_logo():
    candidatos = []
    for nome in ["logo_df_legal.jpg", "logo-df-legal.jpg", "Logo-DF-Legal.jpg",
                 "LOGO_DF_LEGAL.jpg", "logo_df_legal.jpeg", "logo_df_legal.png"]:
        candidatos.append(os.path.join(SCRIPT_DIR, nome))
        candidatos.append(os.path.join(os.getcwd(), nome))

    for caminho in candidatos:
        if os.path.exists(caminho):
            print(f"Logo encontrada em: {caminho}", flush=True)
            return caminho

    for pasta in {SCRIPT_DIR, os.getcwd()}:
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            for achado in glob.glob(os.path.join(pasta, ext)):
                if "logo" in os.path.basename(achado).lower():
                    print(f"Logo encontrada por busca ampla em: {achado}", flush=True)
                    return achado

    print("AVISO: não encontrei a logo. Procurei em:", flush=True)
    for c in candidatos[:6]:
        print(f"   - {c}", flush=True)
    print(f"Pasta do script: {SCRIPT_DIR}", flush=True)
    print(f"Pasta atual (cwd): {os.getcwd()}", flush=True)
    print("=> Salve o arquivo como 'logo_df_legal.jpg' numa dessas pastas.", flush=True)
    return None


# =====================================================================
# Código de barras ITF (Interleaved 2 of 5)
# =====================================================================

ITF_PATTERNS = {
    "0": "NNWWN", "1": "WNNNW", "2": "NWNNW", "3": "WWNNN", "4": "NNWNW",
    "5": "WNWNN", "6": "NWWNN", "7": "NNNWW", "8": "WNNWN", "9": "NWNWN",
}


def only_digits(s):
    return re.sub(r"\D", "", s or "")


def linha_convenio_para_barcode(linha48):
    digitos = only_digits(linha48)
    if len(digitos) != 48:
        return None
    blocos = [digitos[i:i + 12] for i in range(0, 48, 12)]
    return "".join(b[:11] for b in blocos)


def format_linha_digitavel(raw):
    d = only_digits(raw)
    if len(d) == 48:
        return " ".join(d[i:i + 12] for i in range(0, 48, 12))
    return " ".join(d[i:i + 4] for i in range(0, len(d), 4))


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


class CircleBadge(Flowable):
    """Desenha um pequeno emblema circular (fundo cheio + texto centralizado),
    usado como 'carimbo' visual do número da cota em cada ficha."""

    def __init__(self, texto, diametro, bg=None, fg=None, fontsize=13):
        Flowable.__init__(self)
        self.texto = texto
        self.diametro = diametro
        self.bg = bg or NAVY
        self.fg = fg or colors.white
        self.fontsize = fontsize

    def wrap(self, availWidth, availHeight):
        return (self.diametro, self.diametro)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.bg)
        c.circle(self.diametro / 2, self.diametro / 2, self.diametro / 2, fill=1, stroke=0)
        c.setFillColor(self.fg)
        c.setFont("Helvetica-Bold", self.fontsize)
        c.drawCentredString(self.diametro / 2, self.diametro / 2 - self.fontsize * 0.35, self.texto)
        c.restoreState()


class BarcodeFlowable(Flowable):
    def __init__(self, digits, width, height):
        Flowable.__init__(self)
        self.digits = digits
        self.width = width
        self.height = height

    def wrap(self, availWidth, availHeight):
        return (self.width, self.height)

    def draw(self):
        draw_barcode(self.canv, self.digits, 0, 0, self.width, self.height)


# =====================================================================
# Busca e parsing da página pública
# =====================================================================

def formatar_valor(v):
    v = v.strip()
    partes = v.split(",")
    inteiro = partes[0]
    dec = partes[1] if len(partes) > 1 else "00"
    try:
        inteiro_fmt = f"{int(inteiro):,}".replace(",", ".")
    except ValueError:
        inteiro_fmt = inteiro
    return f"R$ {inteiro_fmt},{dec}"


def buscar_pagina(numero_lancamento, numero_guia):
    resp = requests.get(
        BASE_URL,
        params={"NumeroLancamento": numero_lancamento, "NumeroGuia": numero_guia},
        headers=HEADERS,
        timeout=20,
    )
    if resp.status_code == 400:
        # essa guia não existe para este lançamento (ex.: só tem cota única "00")
        return None
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    texto = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()
    return texto


def _buscar(padrao, txt, grupo=1, flags=0):
    m = re.search(padrao, txt, flags)
    return m.group(grupo).strip() if m else None


def _limpar_texto_colado(v):
    """Insere espaços em transições óbvias (minúscula/dígito -> maiúscula)
    em trechos onde o site devolve o texto sem espaçamento correto."""
    v = re.sub(r"(?<=[a-zà-ÿ0-9\)\%\²])(?=[A-ZÀ-Ÿ])", " ", v)
    v = re.sub(r":(?=\S)", ": ", v)
    return re.sub(r"\s+", " ", v).strip()


def parse_dados_e_cotas(texto):
    dados = {
        "nome": _buscar(r"NOME OU RAZ[ÃA]O SOCIAL\s+(.*?)\s+CPF/CNPJ", texto),
        "cpf_cnpj": _buscar(r"CPF/CNPJ\s+([\d./-]+)", texto),
        "endereco": _buscar(r"ENDERE[ÇC]O PARA CORRESPOND[ÊE]NCIA\s+(.*?)\s+BAIRRO", texto),
        "bairro": _buscar(r"BAIRRO\s+(.*?)\s+CIDADE", texto),
        "cidade": _buscar(r"CIDADE\s+(.*?)\s+UF\s", texto),
        "uf": _buscar(r"\bUF\s+([A-Z]{2})\s+CEP", texto),
        "cep": _buscar(r"CEP\s+([\d.-]+)\s+TELEFONE", texto),
        "telefone": _buscar(r"TELEFONE\s+(\([\d]+\)[\d-]+)", texto),
        "orgao_codigo": _buscar(r"(?<!NOME )[ÓO]RG[ÃA]O GERADOR\s+(\d+)", texto),
        "orgao_nome": _buscar(r"NOME [ÓO]RG[ÃA]O GERADOR\s+(.*?)\s+C[ÓO]DIGO DA RECEITA", texto),
        "receita_nome": _buscar(r"NOME DA RECEITA\s+(.*?)\s+(?:№|N[ºo])\s*LAN[ÇC]AMENTO", texto),
        "numero_lancamento": _buscar(r"LAN[ÇC]AMENTO\s+(\d{6,})", texto),
        "quantidade_cotas": _buscar(r"QUANTIDADE DE COTAS\s+(\d+)", texto),
        "processo": _buscar(r"DO PROCESSO\s+([\d./-]+)", texto),
        "origem": _buscar(r"DA ORIGEM\s+([\w./-]+)", texto),
        "data_ciencia": _buscar(r"DATA DA CI[ÊE]NCIA\s+(\d{2}/\d{2}/\d{4})", texto),
        "dias_impugnacao": _buscar(r"DIAS PARA IMPUGNA[ÇC][ÃA]O\s+(\d+)", texto),
        "data_constituicao": _buscar(r"DATA DA CONSTITUI[ÇC][ÃA]O\s+(\d{2}/\d{2}/\d{4})", texto),
        "periodo": _buscar(r"PER[ÍI]ODO \(M[ÊE]S/ANO\)\s+([\d/]+ A [\d/]+)", texto),
    }

    m_secao = re.search(
        r"RELA[ÇC][ÃA]O DE COTAS(.*?)(\d{12}\s+\d{12}\s+\d{12}\s+\d{12})",
        texto, re.DOTALL,
    )
    cotas = []
    linha_digitavel = None
    if m_secao:
        secao_cotas, linha_digitavel = m_secao.group(1), m_secao.group(2)
        padrao_linha = re.compile(
            r"(\d{2})\s+(\d{2}/\d{2}/\d{4})\s+([\d\.]+,\d{2})\s+([\d\.]+,\d{2})\s+"
            r"([\d\.]+,\d{2})\s+([\d\.]+,\d{2})\s+(\d{2})\s+(\d{2}/\d{2}/\d{4})"
        )
        for m in padrao_linha.finditer(secao_cotas):
            cota, venc, principal, multa, juros, total, sit, pag_ate = m.groups()
            cotas.append({
                "cota": cota,
                "vencimento": pag_ate,
                "vencimento_original": venc,
                "valor_total": formatar_valor(total),
                "situacao": sit,
            })

    observacoes = None
    m_obs = re.search(
        r"INFORMA[ÇC][ÕO]ES PREVISTAS EM INSTRU[ÇC][ÃA]O.*?(?:\d{1,2}\s+RESERVADO|$)",
        texto, re.DOTALL,
    )
    if m_obs:
        rotulos = [
            r"INFORMA[ÇC][ÕO]ES PREVISTAS EM INSTRU[ÇC][ÃA]O",
            r"ORIGEM DO D[EÉ]BITO",
            r"CPF/CNPJ",
            r"PER[IÍ]ODO",
            r"VALOR ORIGINAL DA COTA",
            r"LOCALIZA[ÇC][ÃA]?O",
        ]
        padrao_obs = re.compile("(" + "|".join(rotulos) + ")", re.IGNORECASE)
        partes = padrao_obs.split(m_obs.group(0))
        campos_obs = {}
        for i in range(1, len(partes), 2):
            rot = partes[i].strip().upper()
            val = partes[i + 1].strip(" :") if i + 1 < len(partes) else ""
            if val:
                campos_obs[rot] = _limpar_texto_colado(val)
        observacoes = campos_obs

    return dados, cotas, linha_digitavel, observacoes


def cota_valida(cota):
    try:
        n = int(re.sub(r"\D", "", cota["cota"]) or "-1")
    except ValueError:
        n = -1
    return (1 <= n <= 12) and (cota["situacao"].strip() == "00")


# =====================================================================
# Rodapé com paginação
# =====================================================================

class NumberedCanvas(canvas_mod.Canvas):
    """Só cuida de saber o total de páginas pra imprimir 'Página X de Y'
    — o desenho do cabeçalho/rodapé em si fica a cargo do onPage de cada
    PageTemplate (ver _desenhar_faixa_topo/_desenhar_rodape_padrao)."""

    def __init__(self, *args, **kwargs):
        canvas_mod.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._desenhar_numero_pagina(num_pages)
            canvas_mod.Canvas.showPage(self)
        canvas_mod.Canvas.save(self)

    def _desenhar_numero_pagina(self, total_paginas):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(STEEL)
        self.drawRightString(PAGE_W - MARGIN, MARGIN, f"Página {self._pageNumber} de {total_paginas}")
        self.restoreState()


# =====================================================================
# Montagem do PDF final
# =====================================================================

def gerar_pdf(caminho_saida, dados, cotas, observacoes, caminho_logo,
              caminho_selo=None, texto_carta=None, incluir_carta=True):
    # A tela de consulta pode reescrever a carta; em branco vale o padrão.
    # A consulta pública sai sem carta: só dados cadastrais e fichas.
    texto_carta = (texto_carta or "").strip() or TEXTO_CARTA
    margem_capa = 40 * mm    # espaço reservado para a faixa completa (com título)
    margem_fichas = 26 * mm  # espaço reservado para a faixa compacta (só logo)

    frame_capa = Frame(
        MARGIN, 20 * mm, PAGE_W - 2 * MARGIN, PAGE_H - margem_capa - 20 * mm,
        id="capa", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0,
    )
    frame_fichas = Frame(
        MARGIN, 20 * mm, PAGE_W - 2 * MARGIN, PAGE_H - margem_fichas - 20 * mm,
        id="fichas", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0,
    )

    def _pagina_capa(c, _doc):
        _desenhar_faixa_topo(c, caminho_logo,
                              titulo=TITULO_CAPA)
        _desenhar_rodape_padrao(c, "SISLANCA — DF Legal")
        if caminho_marca_dagua:
            largura, altura = A4
            tam = 115 * mm
            x = (largura - tam) / 2
            y = (altura - tam) / 2
            try:
                c.saveState()
                c.drawImage(caminho_marca_dagua, x, y, width=tam, height=tam,
                            mask="auto", preserveAspectRatio=True)
                c.restoreState()
            except Exception:
                pass

    def _pagina_fichas(c, _doc):
        _desenhar_faixa_topo(c, caminho_logo, compacta=True)
        _desenhar_rodape_padrao(c, "SISLANCA — DF Legal")

    caminho_marca_dagua = gerar_marca_dagua(caminho_selo)

    doc = BaseDocTemplate(caminho_saida, pagesize=A4)
    doc.addPageTemplates([
        PageTemplate(id="Capa", frames=[frame_capa], onPage=_pagina_capa),
        PageTemplate(id="Fichas", frames=[frame_fichas], onPage=_pagina_fichas),
    ])

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TituloCarta", parent=styles["Heading1"], fontName="Times-Bold",
        fontSize=13, textColor=NAVY, spaceAfter=7, spaceBefore=2,
    )
    subtitle_style = ParagraphStyle(
        "Subtitulo", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=9.5, textColor=NAVY, spaceBefore=10, spaceAfter=5,
    )

    def cabecalho_secao(texto):
        return Paragraph(
            f"<font color='#C9A227' size=11>■</font>&nbsp;&nbsp;"
            f"<font color='#0E1F45' size=9.5><b>{texto.upper()}</b></font>",
            subtitle_style)

    body_style = ParagraphStyle(
        "CorpoCarta", parent=styles["Normal"], fontSize=8, leading=10.8,
        alignment=TA_JUSTIFY, spaceAfter=5, textColor=colors.HexColor("#20242C"),
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["Normal"], fontSize=6.3, textColor=STEEL,
        spaceAfter=0, fontName="Helvetica-Bold",
    )
    value_style = ParagraphStyle(
        "Value", parent=styles["Normal"], fontSize=7.8, textColor=NAVY,
        fontName="Helvetica-Bold", spaceAfter=1, leading=9.5,
    )
    obs_label_style = ParagraphStyle(
        "ObsLabel", parent=styles["Normal"], fontSize=6.5, textColor=GOLD,
        fontName="Helvetica-Bold", spaceBefore=3, spaceAfter=1,
    )
    obs_value_style = ParagraphStyle(
        "ObsValue", parent=styles["Normal"], fontSize=7.3, textColor=colors.HexColor("#20242C"),
        leading=9.5, spaceAfter=1,
    )

    story = []

    # ---- Página 1 (template "Capa"): título já vai dentro da própria
    # faixa navy (ver _pagina_capa) — aqui começa direto o corpo da carta.
    if incluir_carta:
        for paragrafo in texto_carta.split("\n\n"):
            story.append(Paragraph(paragrafo.replace("\n", " "), body_style))

    # ---- Dados cadastrais + Observações, num único cartão ----
    conteudo_cadastro = [cabecalho_secao("Dados cadastrais")]
    campos_cadastro = [
        ("NOME / RAZÃO SOCIAL", dados.get("nome")),
        ("CPF/CNPJ", dados.get("cpf_cnpj")),
        ("ENDEREÇO", dados.get("endereco")),
        ("BAIRRO", dados.get("bairro")),
        ("CIDADE / UF", f"{dados.get('cidade') or '—'} / {dados.get('uf') or '—'}"),
        ("CEP", dados.get("cep")),
        ("TELEFONE", dados.get("telefone")),
        ("ÓRGÃO GERADOR", dados.get("orgao_nome")),
        ("CÓDIGO DA RECEITA", dados.get("receita_nome")),
        ("Nº DO PROCESSO", dados.get("processo")),
        ("Nº DA ORIGEM", dados.get("origem")),
        ("PERÍODO", dados.get("periodo")),
        ("DATA DA CIÊNCIA", dados.get("data_ciencia")),
        ("DATA DA CONSTITUIÇÃO", dados.get("data_constituicao")),
        ("DIAS PARA IMPUGNAÇÃO", dados.get("dias_impugnacao")),
    ]
    linhas_tbl = []
    for i in range(0, len(campos_cadastro), 3):
        trio = campos_cadastro[i:i + 3]
        linha = []
        for lab, val in trio:
            celula = [Paragraph(lab, label_style), Paragraph(str(val or "—"), value_style)]
            linha.append(celula)
        while len(linha) < 3:
            linha.append([Paragraph("", label_style)])
        linhas_tbl.append(linha)
    cadastro_tbl = Table(linhas_tbl, colWidths=[54.6 * mm, 54.6 * mm, 54.6 * mm])
    cadastro_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
    ]))
    conteudo_cadastro.append(cadastro_tbl)

    if observacoes:
        for k, v in observacoes.items():
            if "LOCALIZA" in k.replace("É", "E").replace("Í", "I"):
                conteudo_cadastro.append(HRFlowable(
                    width="100%", thickness=0.6, color=LINEC, spaceBefore=8, spaceAfter=6))
                conteudo_cadastro.append(cabecalho_secao("Observações do lançamento"))
                texto_obs = v if len(v) <= 260 else v[:257] + "..."
                conteudo_cadastro.append(Paragraph(texto_obs, obs_value_style))
                break

    cartao_cadastro = Table([[conteudo_cadastro]], colWidths=[173.8 * mm])
    cartao_cadastro.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, LINEC),
        ("LINEBEFORE", (0, 0), (0, 0), 2.5, GOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(cartao_cadastro)

    story.append(NextPageTemplate("Fichas"))
    story.append(PageBreak())
    info_ficha_label = ParagraphStyle(
        "InfoFichaLabel", parent=styles["Normal"], fontSize=6.3, textColor=STEEL,
        fontName="Helvetica-Bold", spaceAfter=0,
    )
    info_ficha_valor = ParagraphStyle(
        "InfoFichaValor", parent=styles["Normal"], fontSize=8, textColor=NAVY,
        fontName="Helvetica-Bold", spaceAfter=3, leading=9.5,
    )
    obs_ficha_style = ParagraphStyle(
        "ObsFicha", parent=styles["Normal"], fontSize=6.8, textColor=colors.HexColor("#3A3F47"),
        leading=8.6, spaceAfter=6,
    )

    localizacao_txt = None
    if observacoes:
        for k, v in observacoes.items():
            if "LOCALIZA" in k.replace("É", "E").replace("Í", "I"):
                localizacao_txt = v if len(v) <= 200 else v[:197] + "..."
                break

    orgao_ficha_style = ParagraphStyle(
        "OrgaoFicha", parent=styles["Normal"], fontSize=6.8, textColor=STEEL,
        fontName="Helvetica-Bold", spaceAfter=4,
    )

    def bloco_cabecalho_fichas():
        bloco = [
            Paragraph("SECRETARIA DE ESTADO DE PROTEÇÃO DA ORDEM URBANÍSTICA "
                      "DO DISTRITO FEDERAL", orgao_ficha_style),
            cabecalho_secao(f"Boletos — Lançamento {dados.get('numero_lancamento', '')}"),
        ]
        info_tbl = Table(
            [[Paragraph("INTERESSADO", info_ficha_label),
              Paragraph("CPF/CNPJ", info_ficha_label),
              Paragraph("CÓDIGO DA RECEITA", info_ficha_label),
              Paragraph("PERÍODO", info_ficha_label)],
             [Paragraph(str(dados.get("nome") or "—"), info_ficha_valor),
              Paragraph(str(dados.get("cpf_cnpj") or "—"), info_ficha_valor),
              Paragraph(str(dados.get("receita_nome") or "—"), info_ficha_valor),
              Paragraph(str(dados.get("periodo") or "—"), info_ficha_valor)]],
            colWidths=[54 * mm, 34 * mm, 56 * mm, 26 * mm],
        )
        info_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        bloco.append(info_tbl)
        if localizacao_txt:
            bloco.append(Paragraph(
                f"<b><font color='#C9A227' size=6.3>OBSERVAÇÕES: </font></b>{localizacao_txt}",
                obs_ficha_style))
        bloco.append(HRFlowable(width="100%", thickness=1, color=GOLD, spaceBefore=2, spaceAfter=8))
        return bloco

    story.extend(bloco_cabecalho_fichas())

    for idx, cota in enumerate(cotas):
        conteudo = []

        linha_topo = Table(
            [[CircleBadge(cota['cota'], 13 * mm, fontsize=11.5),
              Paragraph(f"<font color='#5A6472' size=6.5><b>VENCIMENTO</b></font><br/>"
                        f"<font color='#0E1F45' size=10><b>{cota['vencimento']}</b></font>",
                        styles["Normal"]),
              Paragraph(f"<font color='#5A6472' size=6.5><b>VALOR</b></font><br/>"
                        f"<font color='#C9A227' size=12><b>{cota['valor_total']}</b></font>",
                        styles["Normal"])]],
            colWidths=[20 * mm, 74 * mm, 70 * mm],
        )
        linha_topo.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        conteudo.append(linha_topo)

        codigo_barras = linha_convenio_para_barcode(cota.get("linha_digitavel", ""))
        if codigo_barras:
            conteudo.append(BarcodeFlowable(codigo_barras, 164 * mm, 9 * mm))
        else:
            conteudo.append(Paragraph(
                "<font color='#B3261E' size=8>Não foi possível ler a linha digitável.</font>",
                styles["Normal"]))
        conteudo.append(Paragraph(
            f"<font face='Courier' size=7.8 color='#0E1F45'>"
            f"{format_linha_digitavel(cota.get('linha_digitavel', ''))}</font>",
            styles["Normal"]))

        card = Table([[conteudo]], colWidths=[168 * mm])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
            ("BOX", (0, 0), (-1, -1), 0.6, LINEC),
            ("LINEBEFORE", (0, 0), (0, 0), 2.5, NAVY),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        if idx % COTAS_POR_PAGINA != 0:
            story.append(Spacer(1, 6))
        story.append(card)

        fim_de_pagina = (idx + 1) % COTAS_POR_PAGINA == 0
        eh_ultimo = (idx == len(cotas) - 1)
        if fim_de_pagina and not eh_ultimo:
            story.append(PageBreak())
            story.extend(bloco_cabecalho_fichas())

    doc.build(story, canvasmaker=NumberedCanvas)


# =====================================================================
# Abrir o PDF gerado automaticamente (pop-up do visualizador padrão)
# =====================================================================

def abrir_arquivo(caminho):
    """Abre 'caminho' no aplicativo padrão do sistema — no caso de um PDF,
    o visualizador instalado (Adobe, Edge, Chrome etc.) abre numa janela
    própria assim que o arquivo é gerado, além de já estar salvo na pasta.

    Detecta o sistema operacional e usa o mecanismo nativo de cada um.
    Nunca interrompe a execução se não conseguir abrir (arquivo
    inexistente, nenhum programa associado etc.) — só avisa no console."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(caminho)  # noqa: só existe no Windows
        elif sys.platform == "darwin":
            subprocess.run(["open", caminho], check=False)
        else:
            subprocess.run(["xdg-open", caminho], check=False)
    except Exception as e:
        print(f"Aviso: não consegui abrir '{caminho}' automaticamente "
              f"({e}). Abra manualmente na pasta de saída.", flush=True)


# =====================================================================
# MAIN
# =====================================================================

def main():
    numero_lancamento = input("Digite o número do lançamento: ").strip()
    if not numero_lancamento:
        print("Número não informado.", file=sys.stderr)
        sys.exit(1)
    if numero_lancamento.isdigit() and len(numero_lancamento) < 10:
        numero_lancamento = numero_lancamento.zfill(10)
        print(f"Número completado com zeros à esquerda: {numero_lancamento}", flush=True)

    caminho_logo = localizar_logo()
    caminho_selo = localizar_selo()

    print("Consultando a página pública (guia 01) para ler os dados gerais...", flush=True)
    texto_inicial = buscar_pagina(numero_lancamento, "01")
    guia_inicial = "01"
    if texto_inicial is None:
        print("Guia 01 não existe para este lançamento (provavelmente só tem cota única) "
              "— tentando guia 00...", flush=True)
        texto_inicial = buscar_pagina(numero_lancamento, "00")
        guia_inicial = "00"

    if texto_inicial is None:
        print("Não consegui obter dados nem pela guia 01 nem pela 00. "
              "Confira o número do lançamento.", file=sys.stderr)
        sys.exit(1)

    dados, cotas, linha_guia_inicial, observacoes = parse_dados_e_cotas(texto_inicial)

    if not cotas:
        print("Não consegui localizar a tabela de cotas. Confira o número do lançamento.",
              file=sys.stderr)
        sys.exit(1)

    print(f"Interessado: {dados.get('nome')} | Total de cotas na tabela: {len(cotas)}", flush=True)

    cotas_validas = [c for c in cotas if cota_valida(c)]
    print(f"Cotas válidas (situação 00, entre 1 e 12): "
          f"{[c['cota'] for c in cotas_validas]}", flush=True)

    if not cotas_validas:
        outras_cotas = [c for c in cotas if c["cota"] != "00"]
        cota_unica = next(
            (c for c in cotas if c["cota"] == "00" and c["situacao"].strip() == "00"), None
        )
        if not outras_cotas and cota_unica:
            print("Não há parcelas 1-12 nesse lançamento; como a cota única (00) é a "
                  "ÚNICA cota existente, ela será usada.", flush=True)
            cotas_validas = [cota_unica]

    if not cotas_validas:
        print("Nenhuma cota em aberto encontrada (nem parcelas 1-12, nem cota única "
              "isolada). Confira o número do lançamento.", file=sys.stderr)
        sys.exit(1)

    print("Buscando a linha digitável de cada cota válida...", flush=True)
    for cota in cotas_validas:
        if cota["cota"] == guia_inicial and linha_guia_inicial:
            cota["linha_digitavel"] = linha_guia_inicial
        else:
            texto_cota = buscar_pagina(numero_lancamento, cota["cota"])
            if texto_cota is None:
                cota["linha_digitavel"] = None
            else:
                _, _, linha, _ = parse_dados_e_cotas(texto_cota)
                cota["linha_digitavel"] = linha
        status = "OK" if cota.get("linha_digitavel") else "FALHOU"
        print(f"  Cota {cota['cota']}: {status}", flush=True)
        time.sleep(0.5)

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    caminho_final = os.path.join(PASTA_SAIDA, f"{numero_lancamento}.pdf")

    print("Gerando o PDF final...", flush=True)
    gerar_pdf(caminho_final, dados, cotas_validas, observacoes, caminho_logo, caminho_selo)

    print(f"\nPDF gerado em: {caminho_final}", flush=True)
    abrir_arquivo(caminho_final)
    input("\nPressione Enter para fechar...")


if __name__ == "__main__":
    main()