"""Sessão autenticada no SISLANCA via Playwright.

As credenciais são informadas na interface a cada login e usadas só para
preencher o formulário — nunca são gravadas em disco nem mantidas depois que
a sessão é encerrada.

O navegador é mantido aberto entre requisições para preservar a sessão; como o
Playwright síncrono não pode ser usado de várias threads, todo acesso passa
pelo _LOCK e fica preso à thread que criou a sessão.
"""

import os
import threading

from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ.get("SISLANCA_BASE_URL", "https://sislanca.fazenda.df.gov.br").rstrip("/")
LOGIN_URL = f"{BASE_URL}/login"
HEADLESS = os.environ.get("SISLANCA_HEADLESS", "false").strip().lower() in ("1", "true", "sim")

_LOCK = threading.RLock()
_sessao = None


class SessaoError(RuntimeError):
    pass


def _fechar_popup_se_existir(page):
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    for sel in ("button:has-text('Pular')", "button:has-text('Fechar')",
                "[aria-label='Close']", "[aria-label='Fechar']",
                ".tg-dialog-close", ".p-dialog-header-close"):
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


def status():
    with _LOCK:
        if _sessao is None:
            return {"logado": False, "usuario": None}
        return {"logado": True, "usuario": _sessao["usuario"]}


def login(usuario, senha):
    global _sessao

    usuario = (usuario or "").strip()
    senha = senha or ""
    if not usuario or not senha:
        raise SessaoError("Informe o CPF e a senha para entrar.")

    with _LOCK:
        if _sessao is not None:
            return status()

        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch(headless=HEADLESS)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            _fechar_popup_se_existir(page)

            cpf_field = page.locator("#cpf")
            cpf_field.click()
            cpf_field.fill("")
            cpf_field.press_sequentially(usuario, delay=40)

            senha_field = page.locator("input[type='password']").first
            senha_field.click()
            senha_field.fill("")
            senha_field.press_sequentially(senha, delay=40)

            page.locator("button[data-cy='submit-login-form']").click()
            try:
                page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
            except Exception:
                raise SessaoError("Login não completou — confira o CPF e a senha.")

            page.wait_for_timeout(3000)
            _fechar_popup_se_existir(page)

            _sessao = {"pw": pw, "browser": browser, "context": context,
                       "page": page, "usuario": usuario}
        except Exception:
            try:
                pw.stop()
            except Exception:
                pass
            raise

        return status()


def logout():
    global _sessao

    with _LOCK:
        if _sessao is None:
            return status()
        try:
            _sessao["browser"].close()
        except Exception:
            pass
        try:
            _sessao["pw"].stop()
        except Exception:
            pass
        _sessao = None
        return status()
