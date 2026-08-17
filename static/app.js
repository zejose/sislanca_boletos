const TITULOS = {
  painel: ["VISÃO GERAL", "Painel de emissões"],
  consulta: ["CONSULTA E EMISSÃO", "Consultar lançamento"],
  lote: ["EMISSÃO EM LOTE", "Processar vários lançamentos"],
  historico: ["REGISTRO", "Histórico de emissões"],
  publica: ["PORTAL DO CONTRIBUINTE", "Consulta de preço público"],
};

const estado = {
  tela: "consulta",
  modo: "interna",
  lancamento: null,
  selecionadas: new Set(),
  filtroHistorico: "Todos",
  ultimoPdf: null,
  pollLote: null,
};

const $ = (id) => document.getElementById(id);
const brl = (n) => "R$ " + n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const paraNumero = (valor) => parseFloat(String(valor || "").replace("R$", "").replace(/\./g, "").replace(",", ".").trim()) || 0;

function classeTag(situacao) {
  const mapa = {
    "Em aberto": "tag-aberto", "Emitido": "tag", "Enviado": "tag",
    "Pago": "tag-pago", "Cancelada": "tag-cancel",
    "Falha": "tag-falha", "Em curso": "tag-curso", "Concluído": "tag",
    "Na fila": "tag-cancel",
  };
  return "tag " + (mapa[situacao] || "");
}

function situacaoCota(codigo) {
  const mapa = { "00": "Em aberto", "01": "Pago", "02": "Cancelada" };
  return mapa[String(codigo).trim()] || `Situação ${codigo}`;
}

function mostrarTela(tela) {
  estado.tela = tela;
  document.querySelectorAll(".tela").forEach((s) => s.classList.remove("ativa"));
  $("tela-" + tela).classList.add("ativa");
  document.querySelectorAll(".nav button").forEach((b) =>
    b.classList.toggle("ativo", b.dataset.tela === tela));

  const [kicker, titulo] = TITULOS[tela];
  $("tela-kicker").textContent = kicker;
  $("tela-titulo").textContent = titulo;

  if (tela === "painel") carregarPainel();
  if (tela === "historico") carregarHistorico();
  if (tela === "lote") atualizarLote();
}

async function pedir(url, opcoes) {
  const resp = await fetch(url, opcoes);
  const dados = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(dados.erro || "Falha na requisição.");
  return dados;
}

/* ---------------- Sessão ---------------- */

function pintarSessao(s) {
  $("form-login").hidden = s.logado;
  $("sessao-ativa").hidden = !s.logado;
  if (s.logado) {
    $("sessao-nome").textContent = s.usuario;
    $("login-senha").value = "";
  }
}

function erroSessao(mensagem) {
  const alvo = $("login-erro");
  alvo.hidden = !mensagem;
  alvo.textContent = mensagem || "";
}

async function entrar(evento) {
  evento.preventDefault();
  const btn = $("btn-entrar");
  erroSessao("");
  btn.disabled = true;
  btn.textContent = "Conectando…";
  try {
    pintarSessao(await pedir("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ usuario: $("login-cpf").value, senha: $("login-senha").value }),
    }));
  } catch (e) {
    erroSessao(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Entrar";
  }
}

async function sair() {
  const btn = $("btn-sair");
  btn.disabled = true;
  btn.textContent = "Saindo…";
  try {
    pintarSessao(await pedir("/api/logout", { method: "POST" }));
  } finally {
    btn.disabled = false;
    btn.textContent = "Sair";
  }
}

/* ---------------- Painel ---------------- */

async function carregarPainel() {
  const dados = await pedir("/api/painel");

  $("painel-kpis").innerHTML = dados.kpis.map((k) => `
    <div class="kpi">
      <div class="rotulo-mini">${k.label}</div>
      <div class="kpi-valor">${k.value}</div>
      <div class="kpi-hint">${k.hint}</div>
    </div>`).join("");

  const max = Math.max(1, ...dados.serie.map((s) => s.n));
  $("painel-barras").innerHTML = dados.serie.map((s) => `
    <div class="barra-col">
      <div class="barra-n">${s.n}</div>
      <div class="barra ${s.n === max && s.n > 0 ? "pico" : ""}" style="height: ${Math.round((s.n / max) * 150)}px;"></div>
    </div>`).join("");
  $("painel-rotulos").innerHTML = dados.serie.map((s) => `<div>${s.dia}</div>`).join("");

  $("painel-recentes").innerHTML = dados.recentes.length
    ? dados.recentes.map((h) => `
        <tr>
          <td class="numerico">${h.numero}</td>
          <td>${h.nome || "—"}</td>
          <td style="color: var(--cinza);">${h.cotas}</td>
          <td style="color: var(--cinza);">${h.quando}</td>
          <td><span class="${classeTag(h.situacao)}">${h.situacao}</span></td>
        </tr>`).join("")
    : `<tr><td colspan="5" class="vazio">Nenhuma emissão registrada ainda.</td></tr>`;
}

/* ---------------- Consulta ---------------- */

async function consultar() {
  const numero = $("input-numero").value.trim();
  if (!numero) return;

  $("consulta-mensagem").innerHTML = `<div class="carregando">Consultando lançamento ${numero}…</div>`;
  $("consulta-corpo").hidden = true;
  $("rodape-acao").hidden = true;

  try {
    const dados = await pedir(`/api/consulta/${encodeURIComponent(numero)}`);
    estado.lancamento = dados;
    estado.selecionadas = new Set(dados.abertas);
    $("consulta-mensagem").innerHTML = "";
    pintarLancamento();
  } catch (e) {
    $("consulta-mensagem").innerHTML = `<div class="erro">${e.message}</div>`;
  }
}

function pintarLancamento() {
  const l = estado.lancamento;
  const d = l.dados;

  $("consulta-corpo").hidden = false;
  $("rodape-acao").hidden = false;
  $("tela-titulo").textContent = "Lançamento " + l.numero;

  $("lanc-numero").textContent = l.numero;
  $("lanc-nome").textContent = d.nome || "—";
  $("lanc-sub").textContent = [d.cpf_cnpj, d.receita_nome].filter(Boolean).join(" · ");
  $("lanc-abertas").textContent = l.abertas.length;
  $("lanc-total").textContent = l.total;

  const campos = [
    ["NOME / RAZÃO SOCIAL", d.nome], ["CPF/CNPJ", d.cpf_cnpj],
    ["ENDEREÇO", d.endereco], ["BAIRRO", d.bairro],
    ["CIDADE / UF", [d.cidade, d.uf].filter(Boolean).join(" / ")], ["CEP", d.cep],
    ["TELEFONE", d.telefone], ["ÓRGÃO GERADOR", d.orgao_nome],
    ["CÓDIGO DA RECEITA", d.receita_nome], ["Nº DO PROCESSO", d.processo],
    ["Nº DA ORIGEM", d.origem], ["PERÍODO", d.periodo],
    ["DATA DA CIÊNCIA", d.data_ciencia], ["DATA DA CONSTITUIÇÃO", d.data_constituicao],
    ["DIAS PARA IMPUGNAÇÃO", d.dias_impugnacao], ["QUANTIDADE DE COTAS", d.quantidade_cotas],
  ];
  $("lanc-cadastro").innerHTML = campos.map(([rotulo, valor]) => `
    <div><div class="rotulo-mini">${rotulo}</div><div class="valor">${valor || "—"}</div></div>`).join("");

  const obs = Object.values(l.observacoes || {}).find((v) => v && v.length > 30);
  $("lanc-obs-bloco").hidden = !obs;
  if (obs) $("lanc-obs").textContent = obs;

  const abertas = l.cotas.filter((c) => l.abertas.includes(c.cota)).length;
  $("resumo-cotas").textContent = `${l.cotas.length} cotas na tabela · ${abertas} em aberto`;

  $("tabela-cotas").innerHTML = l.cotas.map((c) => {
    const emAberto = l.abertas.includes(c.cota);
    const marcada = estado.selecionadas.has(c.cota);
    return `
      <tr class="cota ${marcada ? "marcada" : ""} ${emAberto ? "" : "bloqueada"}" data-cota="${c.cota}" data-aberto="${emAberto ? "1" : ""}">
        <td><div class="check">${marcada ? "✓" : ""}</div></td>
        <td class="numerico" style="font-size: 17px;">${c.cota}</td>
        <td>${c.vencimento}</td>
        <td class="dir numerico" style="font-size: 16px;">${c.valor_total}</td>
        <td><span class="${classeTag(situacaoCota(c.situacao))}">${situacaoCota(c.situacao)}</span></td>
        <td class="linha-digitavel">${c.linha_digitavel ? c.linha_digitavel : "—"}</td>
      </tr>`;
  }).join("");

  document.querySelectorAll("tr.cota").forEach((tr) => {
    tr.addEventListener("click", () => {
      if (!tr.dataset.aberto) return;
      const cota = tr.dataset.cota;
      estado.selecionadas.has(cota) ? estado.selecionadas.delete(cota) : estado.selecionadas.add(cota);
      pintarLancamento();
    });
  });

  atualizarSelecao();
}

function atualizarSelecao() {
  const l = estado.lancamento;
  if (!l) return;

  const escolhidas = l.cotas.filter((c) => estado.selecionadas.has(c.cota));
  const soma = escolhidas.reduce((t, c) => t + paraNumero(c.valor_total), 0);

  $("selecao-label").textContent = `${escolhidas.length} de ${l.abertas.length} cotas`;
  $("soma-label").textContent = brl(soma);
  $("doc-paginas").textContent = 1 + Math.max(1, Math.ceil(escolhidas.length / 6));
  $("btn-gerar").textContent = escolhidas.length
    ? `Gerar PDF · ${escolhidas.length} fichas` : "Selecione uma cota";
  $("btn-gerar").disabled = escolhidas.length === 0;

  $("doc-fichas").innerHTML = escolhidas.slice(0, 3).map((c) => `
    <div class="doc-ficha">
      <div class="cota">${c.cota}</div>
      <div>${c.vencimento}</div>
      <div class="valor">${c.valor_total}</div>
    </div>`).join("");
}

async function gerarPdf() {
  const btn = $("btn-gerar");
  btn.disabled = true;
  btn.textContent = "Gerando PDF…";
  try {
    const r = await pedir("/api/gerar-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ numero: estado.lancamento.numero, cotas: [...estado.selecionadas] }),
    });
    estado.ultimoPdf = r.download;
    window.open(r.download, "_blank");
  } catch (e) {
    alert(e.message);
  } finally {
    atualizarSelecao();
  }
}

/* ---------------- Lote ---------------- */

async function iniciarLote() {
  const numeros = $("lote-texto").value.split("\n").map((n) => n.trim()).filter(Boolean);
  if (!numeros.length) return;

  try {
    pintarLote(await pedir("/api/lote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ numeros }),
    }));
    if (!estado.pollLote) estado.pollLote = setInterval(atualizarLote, 2000);
  } catch (e) {
    alert(e.message);
  }
}

async function atualizarLote() {
  pintarLote(await pedir("/api/lote/status"));
}

function pintarLote(dados) {
  $("lote-concluidos").textContent = dados.concluidos;
  $("lote-falhas").textContent = dados.falhas;
  $("badge-lote").textContent = dados.itens.length || "";
  $("fila-label").textContent = `${dados.concluidos + dados.falhas} de ${dados.itens.length}`;
  $("lote-resumo").textContent = dados.itens.length
    ? `${dados.itens.length} lançamentos · ${dados.rodando ? "em processamento" : "concluído"}`
    : "nenhum lote em andamento";

  $("lote-fila").innerHTML = dados.itens.length
    ? dados.itens.map((j) => `
        <div class="fila-item">
          <div class="fila-numero">${j.numero}</div>
          <div style="flex: 1; min-width: 0;">
            <div class="fila-nome">${j.nome}</div>
            <div class="fila-progresso"><div style="width: ${j.pct}%;"></div></div>
          </div>
          <div class="fila-detalhe">${j.detalhe}</div>
          <span class="${classeTag(j.status)}" style="width: 96px;">${j.status}</span>
        </div>`).join("")
    : `<div class="vazio">Nenhum lançamento na fila.</div>`;

  if (!dados.rodando && estado.pollLote) {
    clearInterval(estado.pollLote);
    estado.pollLote = null;
  }
}

/* ---------------- Histórico ---------------- */

async function carregarHistorico() {
  const busca = $("historico-busca").value.trim();
  const dados = await pedir(`/api/historico?filtro=${encodeURIComponent(estado.filtroHistorico)}&busca=${encodeURIComponent(busca)}`);

  $("badge-historico").textContent = dados.itens.length || "";
  $("historico-resumo").textContent = `${dados.itens.length} emissões registradas`;
  $("tabela-historico").innerHTML = dados.itens.length
    ? dados.itens.map((h) => `
        <tr>
          <td class="numerico" style="font-size: 16px;">${h.numero}</td>
          <td>${h.nome || "—"}</td>
          <td style="color: var(--cinza);">${h.cotas}</td>
          <td class="dir numerico" style="font-size: 15px;">${h.valor}</td>
          <td style="color: var(--cinza);">${h.quando}</td>
          <td><span class="${classeTag(h.situacao)}">${h.situacao}</span></td>
          <td class="dir"><button class="btn-linha" data-reabrir="${h.numero}">Reabrir</button></td>
        </tr>`).join("")
    : `<tr><td colspan="7" class="vazio">Nenhuma emissão registrada ainda.</td></tr>`;

  document.querySelectorAll("[data-reabrir]").forEach((b) => {
    b.addEventListener("click", () => {
      $("input-numero").value = b.dataset.reabrir;
      mostrarTela("consulta");
      consultar();
    });
  });
}

/* ---------------- Consulta pública ---------------- */

async function baixarBoleto(numero, botao) {
  botao.disabled = true;
  botao.textContent = "Gerando…";
  try {
    const r = await pedir("/api/gerar-pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ numero, cotas: [botao.dataset.baixar] }),
    });
    window.open(r.download, "_blank");
  } catch (e) {
    alert(e.message);
  } finally {
    botao.disabled = false;
    botao.textContent = "Baixar boleto";
  }
}

async function consultarPublica() {
  const numero = $("publica-numero").value.trim();
  if (!numero) return;

  $("publica-mensagem").innerHTML = `<div class="carregando">Consultando…</div>`;
  $("publica-resultado").hidden = true;

  try {
    const l = await pedir(`/api/consulta/${encodeURIComponent(numero)}`);
    $("publica-mensagem").innerHTML = "";
    $("publica-resultado").hidden = false;
    $("publica-nome").textContent = l.dados.nome || "—";
    $("publica-sub").textContent =
      `${l.dados.cpf_cnpj || "—"} · Período ${l.dados.periodo || "—"} · ${l.abertas.length} cotas em aberto`;

    const abertas = l.cotas.filter((c) => l.abertas.includes(c.cota));
    $("publica-cotas").innerHTML = abertas.map((c) => `
      <div class="publica-cota">
        <div class="numero">${c.cota}</div>
        <div>
          <div class="rotulo-mini">PAGAR ATÉ</div>
          <div style="font-size: 14px; font-weight: 600;">${c.vencimento}</div>
        </div>
        <div style="margin-left: auto; text-align: right;">
          <div class="rotulo-mini">VALOR</div>
          <div class="valor">${c.valor_total}</div>
        </div>
        <button class="btn-linha" data-copiar="${c.linha_digitavel || ""}" style="padding: 10px 14px; font-weight: 700;">Copiar linha digitável</button>
        <button class="btn" data-baixar="${c.cota}" style="padding: 12px 16px; font-size: 12px;">Baixar boleto</button>
      </div>`).join("");

    document.querySelectorAll("[data-baixar]").forEach((b) => {
      b.addEventListener("click", () => baixarBoleto(l.numero, b));
    });

    document.querySelectorAll("[data-copiar]").forEach((b) => {
      b.addEventListener("click", async () => {
        if (!b.dataset.copiar) return;
        await navigator.clipboard.writeText(b.dataset.copiar);
        b.textContent = "Copiada!";
        setTimeout(() => (b.textContent = "Copiar linha digitável"), 1500);
      });
    });

    $("btn-publica-tudo").onclick = async () => {
      $("btn-publica-tudo").textContent = "Gerando…";
      try {
        const r = await pedir("/api/gerar-pdf", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ numero: l.numero, cotas: l.abertas }),
        });
        window.open(r.download, "_blank");
      } catch (e) {
        alert(e.message);
      } finally {
        $("btn-publica-tudo").textContent = "Baixar todas em um PDF";
      }
    };
  } catch (e) {
    $("publica-mensagem").innerHTML = `<div class="erro">${e.message}</div>`;
  }
}

/* ---------------- Ligações ---------------- */

document.querySelectorAll(".nav button").forEach((b) =>
  b.addEventListener("click", () => {
    estado.modo = "interna";
    document.querySelectorAll("[data-modo]").forEach((m) =>
      m.classList.toggle("ativo", m.dataset.modo === "interna"));
    mostrarTela(b.dataset.tela);
  }));

document.querySelectorAll("[data-modo]").forEach((b) =>
  b.addEventListener("click", () => {
    estado.modo = b.dataset.modo;
    document.querySelectorAll("[data-modo]").forEach((m) =>
      m.classList.toggle("ativo", m === b));
    mostrarTela(b.dataset.modo === "publica" ? "publica" : "consulta");
  }));

document.querySelectorAll("[data-filtro]").forEach((b) =>
  b.addEventListener("click", () => {
    estado.filtroHistorico = b.dataset.filtro;
    document.querySelectorAll("[data-filtro]").forEach((f) =>
      f.classList.toggle("ativo", f === b));
    carregarHistorico();
  }));

$("form-login").addEventListener("submit", entrar);
$("btn-sair").addEventListener("click", sair);
$("btn-consultar").addEventListener("click", consultar);
$("input-numero").addEventListener("keydown", (e) => { if (e.key === "Enter") consultar(); });
$("btn-publica").addEventListener("click", consultarPublica);
$("publica-numero").addEventListener("keydown", (e) => { if (e.key === "Enter") consultarPublica(); });
$("btn-gerar").addEventListener("click", gerarPdf);
$("btn-lote").addEventListener("click", iniciarLote);
$("btn-lote-zip").addEventListener("click", () => (window.location = "/api/lote/zip"));
$("historico-busca").addEventListener("input", carregarHistorico);
$("btn-ir-consulta").addEventListener("click", () => mostrarTela("consulta"));
$("btn-ir-lote").addEventListener("click", () => mostrarTela("lote"));

$("btn-preview").addEventListener("click", () => {
  if (estado.ultimoPdf) window.open(estado.ultimoPdf, "_blank");
  else alert("Gere um PDF primeiro.");
});

$("btn-sel-abertas").addEventListener("click", () => {
  if (!estado.lancamento) return;
  estado.selecionadas = new Set(estado.lancamento.abertas);
  pintarLancamento();
});

$("btn-limpar").addEventListener("click", () => {
  estado.selecionadas.clear();
  pintarLancamento();
});

pedir("/api/sessao").then(pintarSessao).catch(() => {});
mostrarTela("consulta");
