"""Registro local das emissões, usado pelo Painel e pela aba Histórico."""

import json
import os
import threading
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(SCRIPT_DIR, "data", "historico.json")

_LOCK = threading.Lock()

DIAS_SEMANA = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"]


def _carregar():
    if not os.path.exists(ARQUIVO):
        return []
    try:
        with open(ARQUIVO, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _salvar(registros):
    os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
    with open(ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)


def registrar(numero, nome, cotas_emitidas, cotas_totais, valor, situacao, detalhe=""):
    with _LOCK:
        registros = _carregar()
        registros.insert(0, {
            "numero": numero,
            "nome": nome,
            "cotas": f"{cotas_emitidas} de {cotas_totais}",
            "valor": valor,
            "quando": datetime.now().isoformat(timespec="seconds"),
            "situacao": situacao,
            "detalhe": detalhe,
        })
        _salvar(registros[:500])


def _quando_legivel(iso):
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    hoje = datetime.now().date()
    if dt.date() == hoje:
        return f"hoje, {dt:%H:%M}"
    if dt.date() == hoje - timedelta(days=1):
        return f"ontem, {dt:%H:%M}"
    return f"{dt:%d/%m, %H:%M}"


def listar(filtro="Todos", busca=""):
    registros = _carregar()

    if filtro == "Emitidos":
        registros = [r for r in registros if r["situacao"] != "Falha"]
    elif filtro == "Com falha":
        registros = [r for r in registros if r["situacao"] == "Falha"]

    termo = (busca or "").strip().lower()
    if termo:
        registros = [r for r in registros
                     if termo in r["numero"].lower() or termo in (r["nome"] or "").lower()]

    return [dict(r, quando=_quando_legivel(r["quando"])) for r in registros]


def valor_numerico(valor):
    digitos = (valor or "").replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(digitos)
    except ValueError:
        return 0.0


def indicadores():
    registros = _carregar()
    hoje = datetime.now().date()

    def _data(reg):
        try:
            return datetime.fromisoformat(reg["quando"]).date()
        except ValueError:
            return None

    de_hoje = [r for r in registros if _data(r) == hoje]
    emitidos = [r for r in registros if r["situacao"] != "Falha"]
    falhas = [r for r in registros if r["situacao"] == "Falha"]
    total = sum(valor_numerico(r["valor"]) for r in emitidos)

    serie = []
    for delta in range(6, -1, -1):
        dia = hoje - timedelta(days=delta)
        serie.append({
            "dia": DIAS_SEMANA[dia.weekday()],
            "n": sum(1 for r in registros if _data(r) == dia),
        })

    return {
        "kpis": [
            {"label": "EMISSÕES HOJE", "value": str(len(de_hoje)),
             "hint": f"{len(registros)} no histórico"},
            {"label": "PDFS EMITIDOS", "value": str(len(emitidos)),
             "hint": "gerados com sucesso"},
            {"label": "COM FALHA", "value": str(len(falhas)),
             "hint": "reprocessar quando possível"},
            {"label": "VALOR EMITIDO", "value": f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
             "hint": "soma das emissões concluídas"},
        ],
        "serie": serie,
        "recentes": listar()[:5],
    }
