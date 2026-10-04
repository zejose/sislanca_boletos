# Imagem de producao do SISLANCA Boletos -- Flask atras do Caddy (TLS na
# borda, ver deploy/Caddyfile.boletos). So a aplicacao web roda aqui.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Chromium do Playwright (login no SISLANCA). "pip install playwright" so
# traz o pacote Python -- sem isto o binario do navegador nao existe na
# imagem e todo login falha com erro generico (mesma licao do Cadastro PP).
# --with-deps cobre as libs do sistema que o Chromium precisa pra rodar
# headless. PLAYWRIGHT_BROWSERS_PATH fora de /root: o container roda como
# usuario nao-root (ver USER abaixo).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

COPY . .

RUN useradd --create-home --uid 1000 boletos \
    && mkdir -p /app/data /app/saida \
    && chown -R boletos:boletos /app

USER boletos

# PASTA_SAIDA fora de /app/data: historico.json (dado persistente, pequeno)
# e os PDFs gerados (voláteis, podem ser recriados) ficam em volumes
# separados -- ver deploy/docker-compose.yml.
ENV PASTA_SAIDA=/app/saida

EXPOSE 5000
CMD ["python", "-c", "from app import app; from waitress import serve; serve(app, host='0.0.0.0', port=5000, threads=4)"]
