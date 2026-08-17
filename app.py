"""Interface web local do SISLANCA Boletos.

Reaproveita o pipeline já testado de boletopp.py (consulta pública + geração do
PDF com código de barras) e expõe as telas do design: painel, consulta,
emissão em lote, histórico e consulta pública.

    python app.py   ->  http://localhost:5000
"""

import io
import os
import threading
import time
import zipfile

from flask import Flask, jsonify, render_template, request, send_file

import boletopp
import historico
import sislanca_login

app = Flask(__name__)

CAMINHO_LOGO = boletopp.localizar_logo()
CAMINHO_SELO = boletopp.localizar_selo()

_lote_lock = threading.Lock()
_lote = {"rodando": False, "itens": []}


def normalizar_numero(numero):
    numero = (numero or "").strip()
    if numero.isdigit() and len(numero) < 10:
        numero = numero.zfill(10)
    return numero


def consultar_lancamento(numero, com_linha_digitavel=True):
    """Consulta pública + parsing, na mesma sequência usada por boletopp.main()."""
    texto = boletopp.buscar_pagina(numero, "01")
    guia_inicial = "01"
    if texto is None:
        texto = boletopp.buscar_pagina(numero, "00")
        guia_inicial = "00"
    if texto is None:
        raise ValueError("Lançamento não encontrado. Confira o número informado.")

    dados, cotas, linha_inicial, observacoes = boletopp.parse_dados_e_cotas(texto)
    if not cotas:
        raise ValueError("Não foi possível localizar a tabela de cotas desse lançamento.")

    validas = [c for c in cotas if boletopp.cota_valida(c)]
    if not validas:
        outras = [c for c in cotas if c["cota"] != "00"]
        unica = next((c for c in cotas
                      if c["cota"] == "00" and c["situacao"].strip() == "00"), None)
        if not outras and unica:
            validas = [unica]

    if com_linha_digitavel:
        for cota in validas:
            if cota["cota"] == guia_inicial and linha_inicial:
                cota["linha_digitavel"] = linha_inicial
            else:
                texto_cota = boletopp.buscar_pagina(numero, cota["cota"])
                if texto_cota is None:
                    cota["linha_digitavel"] = None
                else:
                    _, _, linha, _ = boletopp.parse_dados_e_cotas(texto_cota)
                    cota["linha_digitavel"] = linha
                time.sleep(0.5)

    return dados, cotas, validas, observacoes


def gerar_pdf_lancamento(numero, cotas_escolhidas, dados, observacoes, sufixo=""):
    os.makedirs(boletopp.PASTA_SAIDA, exist_ok=True)
    caminho = os.path.join(boletopp.PASTA_SAIDA, f"{numero}{sufixo}.pdf")
    boletopp.gerar_pdf(caminho, dados, cotas_escolhidas, observacoes,
                       CAMINHO_LOGO, CAMINHO_SELO)
    return caminho


def _soma_formatada(cotas):
    total = sum(historico.valor_numerico(c["valor_total"]) for c in cotas)
    return f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _cotas_do_total(cotas):
    """Cota '00' é a cota única: repete o débito inteiro já parcelado nas
    demais, então só entra na soma quando é a única cota do lançamento."""
    parcelas = [c for c in cotas if c["cota"] != "00"]
    return parcelas or cotas


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/logo")
def logo():
    if not CAMINHO_LOGO:
        return "", 404
    return send_file(CAMINHO_LOGO)


@app.route("/api/sessao")
def api_sessao():
    return jsonify(sislanca_login.status())


@app.route("/api/login", methods=["POST"])
def api_login():
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(sislanca_login.login(body.get("usuario"), body.get("senha")))
    except Exception as e:
        return jsonify({"erro": str(e)}), 400


@app.route("/api/logout", methods=["POST"])
def api_logout():
    return jsonify(sislanca_login.logout())


@app.route("/api/consulta/<numero>")
def api_consulta(numero):
    numero = normalizar_numero(numero)
    try:
        dados, cotas, validas, observacoes = consultar_lancamento(numero)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 404
    except Exception as e:
        return jsonify({"erro": f"Falha ao consultar: {e}"}), 502

    return jsonify({
        "numero": numero,
        "dados": dados,
        "observacoes": observacoes or {},
        "cotas": cotas,
        "abertas": [c["cota"] for c in validas],
        "total": _soma_formatada(_cotas_do_total(cotas)),
    })


@app.route("/api/gerar-pdf", methods=["POST"])
def api_gerar_pdf():
    body = request.get_json(silent=True) or {}
    numero = normalizar_numero(body.get("numero"))
    escolhidas = set(body.get("cotas") or [])

    if not numero or not escolhidas:
        return jsonify({"erro": "Informe o lançamento e ao menos uma cota."}), 400

    try:
        dados, _cotas, validas, observacoes = consultar_lancamento(numero)
    except ValueError as e:
        return jsonify({"erro": str(e)}), 404

    selecionadas = [c for c in validas if c["cota"] in escolhidas]
    if not selecionadas:
        return jsonify({"erro": "As cotas escolhidas não estão em aberto."}), 400

    # Um boleto avulso não pode sobrescrever o PDF completo do lançamento.
    sufixo = f"_cota{selecionadas[0]['cota']}" if len(selecionadas) == 1 < len(validas) else ""

    try:
        gerar_pdf_lancamento(numero, selecionadas, dados, observacoes, sufixo)
    except Exception as e:
        historico.registrar(numero, dados.get("nome"), 0, len(validas),
                            "R$ 0,00", "Falha", str(e))
        return jsonify({"erro": f"Falha ao gerar o PDF: {e}"}), 500

    valor = _soma_formatada(selecionadas)
    historico.registrar(numero, dados.get("nome"), len(selecionadas),
                        len(validas), valor, "Emitido")

    return jsonify({
        "numero": numero,
        "cotas": len(selecionadas),
        "valor": valor,
        "download": f"/api/pdf/{numero}{sufixo}",
    })


@app.route("/api/pdf/<arquivo>")
def api_pdf(arquivo):
    nome = os.path.basename(arquivo)
    caminho = os.path.join(boletopp.PASTA_SAIDA, f"{nome}.pdf")
    if not os.path.exists(caminho):
        return jsonify({"erro": "PDF ainda não foi gerado para esse lançamento."}), 404
    return send_file(caminho, mimetype="application/pdf")


def _processar_lote():
    for item in _lote["itens"]:
        numero = item["numero"]
        try:
            item.update(status="Em curso", detalhe="consultando cotas", pct=20)
            dados, _cotas, validas, observacoes = consultar_lancamento(numero)
            if not validas:
                raise ValueError("nenhuma cota em aberto")

            item.update(detalhe=f"gerando {len(validas)} fichas", pct=70)
            gerar_pdf_lancamento(numero, validas, dados, observacoes)

            valor = _soma_formatada(validas)
            historico.registrar(numero, dados.get("nome"), len(validas),
                                len(validas), valor, "Emitido")
            item.update(status="Concluído", pct=100, nome=dados.get("nome") or numero,
                        detalhe=f"{len(validas)} ficha" + ("s" if len(validas) > 1 else ""))
        except Exception as e:
            historico.registrar(numero, item.get("nome") or "—", 0, 0,
                                "R$ 0,00", "Falha", str(e))
            item.update(status="Falha", pct=100, detalhe=str(e)[:60])

    with _lote_lock:
        _lote["rodando"] = False


@app.route("/api/lote", methods=["POST"])
def api_lote():
    body = request.get_json(silent=True) or {}
    numeros = [normalizar_numero(n) for n in (body.get("numeros") or []) if n.strip()]
    if not numeros:
        return jsonify({"erro": "Informe ao menos um lançamento."}), 400

    with _lote_lock:
        if _lote["rodando"]:
            return jsonify({"erro": "Já existe um lote em processamento."}), 409
        _lote["rodando"] = True
        _lote["itens"] = [{"numero": n, "nome": "—", "status": "Na fila",
                           "detalhe": "aguardando", "pct": 0} for n in numeros]

    threading.Thread(target=_processar_lote, daemon=True).start()
    return jsonify(api_lote_status().get_json())


@app.route("/api/lote/status")
def api_lote_status():
    concluidos = sum(1 for i in _lote["itens"] if i["status"] == "Concluído")
    falhas = sum(1 for i in _lote["itens"] if i["status"] == "Falha")
    return jsonify({
        "rodando": _lote["rodando"],
        "itens": _lote["itens"],
        "concluidos": concluidos,
        "falhas": falhas,
    })


@app.route("/api/lote/zip")
def api_lote_zip():
    prontos = [i["numero"] for i in _lote["itens"] if i["status"] == "Concluído"]
    if not prontos:
        return jsonify({"erro": "Nenhum PDF concluído neste lote."}), 404

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for numero in prontos:
            caminho = os.path.join(boletopp.PASTA_SAIDA, f"{numero}.pdf")
            if os.path.exists(caminho):
                zf.write(caminho, f"{numero}.pdf")
    buffer.seek(0)
    return send_file(buffer, mimetype="application/zip",
                     as_attachment=True, download_name="boletos_lote.zip")


@app.route("/api/historico")
def api_historico():
    filtro = request.args.get("filtro", "Todos")
    busca = request.args.get("busca", "")
    return jsonify({"itens": historico.listar(filtro, busca)})


@app.route("/api/painel")
def api_painel():
    return jsonify(historico.indicadores())


if __name__ == "__main__":
    app.run(debug=True, port=5000)
