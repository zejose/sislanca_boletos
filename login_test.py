"""
Etapa 7: LOGIN + consulta + entrar no detalhe + ler os dados do contribuinte
e a tabela de cotas + clicar em "Emitir boleto da cota" (primeira linha) e
DIAGNOSTICAR o que acontece (baixa PDF? abre nova aba? abre modal na página?).

Uso:
    python login_test7.py
"""

import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BASE_URL = os.environ.get("SISLANCA_BASE_URL", "https://sislanca.fazenda.df.gov.br").rstrip("/")
LOGIN_URL = f"{BASE_URL}/login"
USUARIO = os.environ.get("SISLANCA_USER")
SENHA = os.environ.get("SISLANCA_PASS")

if not USUARIO or not SENHA:
    raise SystemExit("Defina SISLANCA_USER e SISLANCA_PASS no .env antes de rodar.")

CODIGO = input("Digite o número sislanca (numeroLancamento) para testar: ").strip()
if not CODIGO:
    raise SystemExit("Número não informado.")


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


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()

    downloads = []
    novas_paginas = []
    context.on("page", lambda p: novas_paginas.append(p))
    page.on("download", lambda d: downloads.append(d))

    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    fechar_popup_se_existir(page)

    cpf_field = page.locator("#cpf")
    cpf_field.click(); cpf_field.fill(""); cpf_field.press_sequentially(USUARIO, delay=40)
    senha_field = page.locator("input[type='password']").first
    senha_field.click(); senha_field.fill(""); senha_field.press_sequentially(SENHA, delay=40)
    page.locator("button[data-cy='submit-login-form']").click()
    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3000)
    fechar_popup_se_existir(page)
    page.wait_for_timeout(1500)

    numero_field = page.locator("#numeroLancamento")
    numero_field.click(); numero_field.fill(""); numero_field.press_sequentially(CODIGO, delay=40)
    page.locator("#btn-consultar").click()
    page.wait_for_timeout(4000)

    page.locator("[data-cy='detalhar-lancamento-nav-btn']").first.click()
    page.wait_for_timeout(3000)

    print("\n===== Texto de 'dados-debito-div' (dados do lançamento/contribuinte) =====", flush=True)
    dados_div = page.locator("[data-cy='dados-debito-div']").first
    if dados_div.count():
        print(dados_div.inner_text(), flush=True)
    else:
        print("Não encontrado.", flush=True)

    print("\n===== Tabela de cotas (consultar-debitos-table) =====", flush=True)
    tabela = page.locator("[data-cy='consultar-debitos-table']").first
    linhas = tabela.locator("tbody tr").all()
    print(f"Total de cotas na tabela: {len(linhas)}", flush=True)
    for ri, row in enumerate(linhas):
        cells = row.locator("td").all()
        textos = []
        for td in cells:
            try:
                textos.append(td.inner_text().strip().replace("\n", " "))
            except Exception:
                textos.append("?")
        print(f"Cota linha {ri}: {textos}", flush=True)

    print("\n===== Clicando em 'Emitir boleto da cota' (primeira linha) =====", flush=True)
    emitir_btn = page.locator("[data-cy='emitir-boleto-btn']").first
    emitir_btn.click()

    print("Aguardando 5s para ver o que acontece (download / nova aba / modal)...", flush=True)
    page.wait_for_timeout(5000)

    if downloads:
        for d in downloads:
            print(f"DOWNLOAD detectado: {d.suggested_filename} (url: {d.url})", flush=True)
            caminho = f"download_{d.suggested_filename}"
            d.save_as(caminho)
            print(f"Salvo em: {caminho}", flush=True)
    else:
        print("Nenhum download detectado.", flush=True)

    if novas_paginas:
        for i, p in enumerate(novas_paginas):
            print(f"NOVA ABA detectada [{i}]: {p.url}", flush=True)
            try:
                p.wait_for_load_state("domcontentloaded", timeout=8000)
                p.screenshot(path=f"nova_aba_{i}.png", full_page=True)
                print(f"Print salvo em nova_aba_{i}.png — URL final: {p.url}", flush=True)
                if p.url.lower().endswith(".pdf") or "pdf" in p.url.lower():
                    print("Parece ser um PDF direto na URL.", flush=True)
            except Exception as e:
                print(f"Erro ao inspecionar nova aba: {e}", flush=True)
    else:
        print("Nenhuma nova aba detectada.", flush=True)

    print("\n===== Verificando se apareceu algum modal/dialog na MESMA página =====", flush=True)
    dialogs = page.locator(".p-dialog:visible").all()
    print(f"Dialogs visíveis: {len(dialogs)}", flush=True)
    for i, dlg in enumerate(dialogs):
        try:
            txt = dlg.inner_text()
        except Exception:
            txt = "(erro ao ler texto)"
        print(f"--- Dialog {i} ---\n{txt}\n", flush=True)

    page.screenshot(path="depois_emitir_boleto.png", full_page=True)
    with open("depois_emitir_boleto.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    print("Print salvo em depois_emitir_boleto.png, HTML em depois_emitir_boleto.html", flush=True)

    print("\nNavegador ficará aberto por 45s pra você conferir visualmente.", flush=True)
    page.wait_for_timeout(95000)
    browser.close()