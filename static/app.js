// Painel de fundos - frontend (sem framework). Dados vem de /api (server.py).
const $ = (s, el = document) => el.querySelector(s);
const CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const ABAS = ["Visão geral", "Rentabilidade", "PL & captação", "Alocação", "Crédito", "Movimentações",
  "Derivativos & moeda", "Marcação (estimada)", "Comparação", "Dados"];
const st = { escolhidos: [], R: null, chave: null, aba: 0, fundo: {}, mes: {} };
const nf = (d) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (v, d = 2) => (v == null || Number.isNaN(v) ? "-" : nf(d).format(v));
const pct = (v, d = 2) => (v == null ? "-" : num(v, d) + "%");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// ------------------------------------------------------------------ tema
const tema = localStorage.getItem("tema");
if (tema) document.documentElement.dataset.theme = tema;
$("#tema").onclick = () => {
  const escuro = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = escuro ? "light" : "dark";
  try { localStorage.setItem("tema", document.documentElement.dataset.theme); } catch (e) {}
  if (st.R) desenha();
};

// ------------------------------------------------------------------ escolha de fundos
function curto(nome) {
  let n = nome.toUpperCase();
  [["FUNDO DE INVESTIMENTO FINANCEIRO", "FIF"], ["FUNDO DE INVESTIMENTO", "FI"], ["MULTIMERCADO", "MM"],
   ["CRÉDITO PRIVADO", "CP"], ["RENDA FIXA", "RF"], ["RESPONSABILIDADE LIMITADA", "RL"], ["LONGO PRAZO", "LP"]]
    .forEach(([a, b]) => (n = n.replaceAll(a, b)));
  return n.slice(0, 22).trim();
}
function desenhaEscolhidos() {
  $("#escolhidos").innerHTML = st.escolhidos.map((f, i) => `<li>
    <span class="ponto" style="background:${CORES[i % 8]}"></span>
    <div><input value="${esc(f.curto)}" data-i="${i}" aria-label="Nome curto"><small title="${esc(f.nome)}">${esc(f.cnpj)} · ${esc(f.nome)}</small></div>
    <button data-x="${i}" title="Remover" aria-label="Remover">×</button></li>`).join("");
  $("#escolhidos").querySelectorAll("input").forEach((el) => (el.onchange = () => (st.escolhidos[el.dataset.i].curto = el.value.trim() || "Fundo")));
  $("#escolhidos").querySelectorAll("button").forEach((b) => (b.onclick = () => { st.escolhidos.splice(+b.dataset.x, 1); desenhaEscolhidos(); }));
}
let tBusca, sel = -1;
$("#busca").addEventListener("input", (e) => {
  clearTimeout(tBusca);
  const q = e.target.value;
  tBusca = setTimeout(async () => {
    if (q.length < 2) return ($("#sugestoes").hidden = true);
    const r = await (await fetch("/api/busca?q=" + encodeURIComponent(q))).json();
    sel = -1;
    $("#sugestoes").innerHTML = r.map((f) => `<li data-c="${esc(f.cnpj)}" data-n="${esc(f.nome)}">${esc(f.nome)}<small>${esc(f.cnpj)}${f.ativo ? "" : " · cancelado"}</small></li>`).join("")
      || "<li>Nada encontrado</li>";
    $("#sugestoes").hidden = false;
  }, 250);
});
$("#busca").addEventListener("keydown", (e) => {
  const li = [...$("#sugestoes").querySelectorAll("li[data-c]")];
  if (!li.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + li.length) % li.length;
    li.forEach((x, i) => x.classList.toggle("ativo", i === sel));
    e.preventDefault();
  } else if (e.key === "Enter" && sel >= 0) adiciona(li[sel]);
});
$("#sugestoes").addEventListener("click", (e) => { const li = e.target.closest("li[data-c]"); if (li) adiciona(li); });
function adiciona(li) {
  if (st.escolhidos.length >= 8) return alert("Máximo de 8 fundos por vez.");
  if (!st.escolhidos.some((f) => f.cnpj === li.dataset.c))
    st.escolhidos.push({ cnpj: li.dataset.c, nome: li.dataset.n, curto: curto(li.dataset.n) });
  $("#busca").value = ""; $("#sugestoes").hidden = true; desenhaEscolhidos();
}
document.addEventListener("click", (e) => { if (!e.target.closest(".busca-wrap")) $("#sugestoes").hidden = true; });

const hoje = new Date();
for (let a = hoje.getFullYear(); a >= 2005; a--) $("#desde").insertAdjacentHTML("beforeend", `<option value="${a}-01">jan/${a}</option>`);
$("#desde").value = `${hoje.getFullYear() - 2}-01`;
fetch("/api/padrao").then((r) => r.json()).then((p) => { st.escolhidos = p; desenhaEscolhidos(); });

// ------------------------------------------------------------------ carga (job em segundo plano)
$("#carregar").onclick = async () => {
  if (!st.escolhidos.length) return alert("Escolha ao menos um fundo.");
  const b = $("#carregar"); b.disabled = true; b.textContent = "Carregando...";
  const pr = $("#progresso"); pr.hidden = false; pr.textContent = "Iniciando...";
  try {
    const r = await (await fetch("/api/carregar", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fundos: st.escolhidos, desde: $("#desde").value }) })).json();
    let chave = r.chave;
    if (r.job) {
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 2000));
        const s = await (await fetch("/api/status/" + r.job)).json();
        pr.textContent = s.log.join("\n") || "Baixando arquivos da CVM...";
        if (s.status === "erro") throw new Error(s.erro);
        if (s.status === "ok") break;
      }
    }
    st.R = await (await fetch("/api/resultado/" + chave)).json(); st.chave = chave;
    st.fundo = {}; st.mes = {};
    pr.textContent = "Pronto."; setTimeout(() => (pr.hidden = true), 1500);
    desenhaAbas(); desenha();
  } catch (e) { pr.textContent = "Erro: " + e.message; }
  b.disabled = false; b.textContent = "Carregar";
};

// ------------------------------------------------------------------ graficos
function base(titulo, extra = {}) {
  return Object.assign({
    title: { text: titulo, font: { size: 14, color: css("--text-1") }, x: 0, xanchor: "left" },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Arial", size: 12, color: css("--text-2") },
    margin: { l: 50, r: 10, t: 40, b: 40 }, hovermode: "x unified",
    legend: { orientation: "h", y: -0.18, font: { color: css("--text-2") } },
    xaxis: { gridcolor: "rgba(0,0,0,0)", linecolor: css("--axis"), automargin: true },
    yaxis: { gridcolor: css("--grid"), zerolinecolor: css("--axis"), automargin: true },
    hoverlabel: { bgcolor: css("--surface-1"), font: { color: css("--text-1") } },
  }, extra);
}
function plota(id, dados, layout, h = 340) {
  const el = document.getElementById(id); if (!el) return;
  el.style.height = h + "px";
  Plotly.newPlot(el, dados, layout, { displaylogo: false, responsive: true, displayModeBar: innerWidth > 700 ? "hover" : false,
    modeBarButtonsToRemove: ["lasso2d", "select2d"] });
}
const cor = (f) => (st.R.meta.fundos.find((x) => x.nome === f) || {}).cor || CORES[0];
const corCat = (c) => st.R.categorias[c] || "#898781";
const barH = (rows, xk, yk, c, titulo) => ({ d: [{ type: "bar", orientation: "h", x: rows.map((r) => r[xk]).reverse(), y: rows.map((r) => r[yk]).reverse(),
  marker: { color: c }, hovertemplate: "%{y}<br>%{x:.3f}% do PL<extra></extra>" }], l: base(titulo, { hovermode: "closest", margin: { l: 10, r: 10, t: 40, b: 30 },
  yaxis: { automargin: true, gridcolor: "rgba(0,0,0,0)", tickfont: { size: 11 } }, xaxis: { gridcolor: css("--grid"), ticksuffix: "%" } }) });
function tabela(cols, linhas, alt = 460) {
  return `<div class="tabela-wrap" style="max-height:${alt}px"><table><thead><tr>${cols.map((c) => `<th class="${c.n ? "n" : ""}">${c.t}</th>`).join("")}</tr></thead><tbody>${
    linhas.map((r) => `<tr>${cols.map((c) => { const v = r[c.k]; return `<td class="${c.n ? "n" : c.w ? "texto" : ""}">${c.f ? c.f(v, r) : esc(v ?? "-")}</td>`; }).join("")}</tr>`).join("")
  }</tbody></table></div>`;
}
function seletorFundo(aba) {
  const fs = st.R.meta.fundos.filter((f) => st.R.por_fundo[f.nome]);
  if (!fs.length) return "";
  st.fundo[aba] = st.fundo[aba] && st.R.por_fundo[st.fundo[aba]] ? st.fundo[aba] : fs[0].nome;
  return `<div class="seletor" data-aba="${aba}">${fs.map((f) => `<button aria-pressed="${f.nome === st.fundo[aba]}" data-f="${esc(f.nome)}"><span class="ponto" style="background:${f.cor}"></span>${esc(f.nome)}</button>`).join("")}</div>`;
}
function ligaSeletor() {
  document.querySelectorAll(".seletor[data-aba] button").forEach((b) => (b.onclick = () => { st.fundo[b.parentElement.dataset.aba] = b.dataset.f; desenha(); }));
}

// ------------------------------------------------------------------ abas
function desenhaAbas() {
  $("#abas").innerHTML = ABAS.map((a, i) => `<button role="tab" aria-selected="${i === st.aba}" data-i="${i}">${a}</button>`).join("");
  $("#abas").querySelectorAll("button").forEach((b) => (b.onclick = () => { st.aba = +b.dataset.i; desenhaAbas(); desenha(); }));
}
function desenha() {
  const R = st.R, el = $("#conteudo");
  if (!R) return;
  try { el.innerHTML = ""; [geral, rentab, plcap, alocacao, credito, movimentos, derivativos, marcacao, comparacao, dados][st.aba](el, R); }
  catch (e) { el.innerHTML = `<div class="aviso">Erro ao desenhar esta aba: ${esc(e.message)}</div>`; console.error(e); }
  ligaSeletor();
}

function geral(el, R) {
  el.innerHTML = `<h2>Resumo</h2>` + tabela([
    { t: "Fundo", k: "fundo", f: (v) => `<b style="color:${cor(v)}">■</b> ${esc(v)}` },
    { t: "PL (R$ mi)", k: "pl_mi", n: 1, f: (v) => num(v, 1) }, { t: "Retorno 12m", k: "ret12", n: 1, f: (v) => pct(v) },
    { t: "%CDI 12m", k: "pct_cdi12", n: 1, f: (v) => pct(v, 1) }, { t: "No ano", k: "ret_ano", n: 1, f: (v) => pct(v) },
    { t: "Vol. anual", k: "vol", n: 1, f: (v) => pct(v) }, { t: "Pior drawdown", k: "dd", n: 1, f: (v) => pct(v) },
    { t: "Captação líq. 12m (R$ mi)", k: "capt12_mi", n: 1, f: (v) => num(v, 1) }, { t: "Cotistas", k: "cotistas", n: 1, f: (v) => num(v, 0) },
    { t: "Ativos", k: "ativos", n: 1, f: (v) => num(v, 0) }, { t: "Top 10 emissores", k: "top10_emissores", n: 1, f: (v) => pct(v, 1) },
    { t: "Última carteira", k: "ult_carteira" }, { t: "Última aberta", k: "carteira_aberta" }, { t: "Última cota", k: "ult_cota" },
  ], R.kpis, 300) + `<div id="g_acum" class="grafico"></div>`;
  const d = Object.entries(R.cotas).map(([f, s]) => ({ x: s.datas, y: s.acum, name: f, line: { color: cor(f), width: 2 }, hovertemplate: "%{y:.2f}%" }));
  d.push({ x: R.cdi.datas, y: R.cdi.acum, name: "CDI", line: { color: css("--text-2"), width: 2, dash: "dash" }, hovertemplate: "%{y:.2f}%" });
  plota("g_acum", d, base("Retorno acumulado no período (%)", { yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 420);
}

function rentab(el, R) {
  el.innerHTML = `<div id="g_hm" class="grafico"></div><div id="g_mes" class="grafico"></div><div id="g_dd" class="grafico"></div>`;
  const fs = R.meta.fundos.map((f) => f.nome).filter((f) => R.cotas[f]);
  const meses = [...new Set(R.mensal.map((r) => r.mes))].sort();
  const z = fs.map((f) => meses.map((m) => { const r = R.mensal.find((x) => x.fundo === f && x.mes === m); return r && r.pct_cdi != null ? r.pct_cdi * 100 : null; }));
  plota("g_hm", [{ type: "heatmap", x: meses, y: fs, z, zmin: 0, zmax: 200, zmid: 100,
    colorscale: [[0, "#eb6834"], [0.5, css("--surface-2")], [1, "#2a78d6"]], colorbar: { ticksuffix: "%", title: { text: "%CDI" } },
    hovertemplate: "%{y}<br>%{x}: %{z:.0f}% do CDI<extra></extra>" }],
    base("%CDI mês a mês (azul acima do CDI, laranja abaixo)", { hovermode: "closest", yaxis: { autorange: "reversed" } }), 110 + 34 * fs.length);
  plota("g_mes", fs.map((f) => { const r = R.mensal.filter((x) => x.fundo === f && x.retorno != null);
    return { type: "bar", x: r.map((x) => x.mes), y: r.map((x) => x.retorno * 100), name: f, marker: { color: cor(f) }, hovertemplate: "%{y:.2f}%" }; }),
    base("Retorno mensal (%)", { barmode: "group", yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }));
  plota("g_dd", fs.map((f) => ({ x: R.cotas[f].datas, y: R.cotas[f].dd, name: f, line: { color: cor(f), width: 2 }, hovertemplate: "%{y:.2f}%" })),
    base("Drawdown (% abaixo do pico anterior)", { yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }));
}

function plcap(el, R) {
  el.innerHTML = `<div id="g_pl" class="grafico"></div><div id="g_cap" class="grafico"></div><div id="g_cot" class="grafico"></div>`;
  const fs = Object.keys(R.cotas);
  plota("g_pl", fs.map((f) => ({ x: R.cotas[f].datas, y: R.cotas[f].pl, name: f, line: { color: cor(f), width: 2 }, hovertemplate: "R$ %{y:,.1f} mi" })),
    base("Patrimônio líquido (R$ milhões)"));
  plota("g_cap", fs.map((f) => { const r = R.mensal.filter((x) => x.fundo === f);
    return { type: "bar", x: r.map((x) => x.mes), y: r.map((x) => x.capt_mi), name: f, marker: { color: cor(f) }, hovertemplate: "R$ %{y:,.1f} mi" }; }),
    base("Captação líquida mensal (aplicações - resgates, R$ mi)", { barmode: "group" }));
  plota("g_cot", fs.map((f) => ({ x: R.cotas[f].datas, y: R.cotas[f].cotistas, name: f, line: { color: cor(f), width: 2 } })), base("Número de cotistas"));
}

function alocacao(el, R) {
  el.innerHTML = seletorFundo("aloc");
  const f = st.fundo.aloc, p = R.por_fundo[f]; if (!p) return;
  el.insertAdjacentHTML("beforeend", `<div id="g_area" class="grafico"></div>
    <div class="grade g2"><div id="g_emi" class="grafico"></div><div id="g_atual" class="grafico"></div></div>
    <h2>Carteira de ${p.ult_mes} (look-through)</h2><input class="filtro" id="filtro" placeholder="Filtrar ativo, emissor, categoria...">
    <div id="t_cart"></div>`);
  plota("g_area", Object.entries(p.alocacao.series).map(([c, y]) => ({ x: p.alocacao.meses, y, name: c, stackgroup: "a",
    line: { width: 0.5, color: css("--surface-1") }, fillcolor: corCat(c), hovertemplate: "%{y:.1f}%" })),
    base(`${f}: % do PL por categoria (look-through)`, { yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 420);
  const e = barH(p.emissores, "perc_pl", "emissor", CORES[0], `Maiores emissores (${p.ult_mes})`); plota("g_emi", e.d, e.l, 460);
  const fs = R.comparacao.alocacao.fundos, cats = Object.keys(R.categorias);
  const agreg = (fund) => { const t = {}; R.comparacao.alocacao.linhas.forEach(([c, ...v]) => { const k = cats.includes(c) ? c : "Outros"; t[k] = (t[k] || 0) + v[fs.indexOf(fund)]; }); return t; };
  plota("g_atual", cats.map((c) => ({ type: "bar", orientation: "h", name: c, y: fs, x: fs.map((x) => agreg(x)[c] || 0), marker: { color: corCat(c) },
    hovertemplate: c + ": %{x:.1f}%<extra></extra>" })), base("Alocação atual: todos os fundos (% do PL)", { barmode: "relative", hovermode: "closest",
    yaxis: { autorange: "reversed", automargin: true }, xaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 460);
  const cols = [{ t: "Categoria", k: "categoria" }, { t: "Ativo", k: "ativo", w: 1 }, { t: "Código", k: "codigo" }, { t: "Emissor", k: "emissor", w: 1 },
    { t: "% PL", k: "perc_pl", n: 1, f: (v) => pct(v, 3) }, { t: "Veículo", k: "veiculo", w: 1 }];
  const pinta = () => { const q = $("#filtro").value.toLowerCase();
    const r = p.carteira.filter((x) => !q || [x.categoria, x.ativo, x.emissor, x.codigo].join(" ").toLowerCase().includes(q));
    $("#t_cart").innerHTML = tabela(cols, r.slice(0, 600)) + `<p class="legenda">${r.length} linhas${r.length > 600 ? " (mostrando 600; baixe o CSV na aba Dados)" : ""}</p>`; };
  $("#filtro").oninput = pinta; pinta();
}

function credito(el, R) {
  el.innerHTML = seletorFundo("cred");
  const f = st.fundo.cred, p = R.por_fundo[f]; if (!p) return; const c = p.credito;
  const an = R.meta.anbima_data ? new Date(R.meta.anbima_data + "T12:00").toLocaleDateString("pt-BR") : "-";
  el.insertAdjacentHTML("beforeend", `<div class="aviso">Carteira de <b>${c.mes}</b>: o mês mais recente com parte confidencial abaixo de 5% do PL.
    Taxas e duration das debêntures: marcação ANBIMA de <b>${an}</b>.</div>
    <div class="kpis">
      <div class="kpi"><div class="r">Debêntures</div><div class="v">${pct(c.deb_pl, 1)}</div><div class="s">do PL</div></div>
      <div class="kpi"><div class="r">Com taxa ANBIMA</div><div class="v">${pct(c.cobertura, 0)}</div><div class="s">das debêntures</div></div>
      <div class="kpi"><div class="r">Spread médio DI +</div><div class="v">${pct(c.spread_di)}</div><div class="s">a.a. · ${pct(c.pl_di, 1)} do PL</div></div>
      <div class="kpi"><div class="r">Taxa média IPCA +</div><div class="v">${pct(c.taxa_ipca)}</div><div class="s">a.a. · ${pct(c.pl_ipca, 1)} do PL</div></div>
      <div class="kpi"><div class="r">Duration média</div><div class="v">${num(c.duration)} anos</div><div class="s">debêntures com taxa</div></div>
    </div>
    <div class="grade g2"><div id="g_tipo" class="grafico"></div><div id="g_sc" class="grafico"></div></div>
    <div id="g_hist"></div><h2>Debêntures</h2><div id="t_deb"></div>
    <h2>Demais títulos (informado pela própria CVM)</h2>
    <p class="legenda">Indexador, % do índice, cupom, taxa e rating vêm na CDA para depósitos bancários e títulos de crédito privado; prazo vem do vencimento quando informado.</p>
    <div class="grade g3"><div id="g_idx" class="grafico"></div><div id="g_prz" class="grafico"></div><div id="g_rat" class="grafico"></div></div><div id="t_res"></div>`);
  const t = barH(c.por_tipo.sort((a, b) => b.perc_pl - a.perc_pl), "perc_pl", "t", CORES[0], "Debêntures por indexador (% do PL)"); plota("g_tipo", t.d, t.l, 340);
  plota("g_sc", ["DI +", "IPCA +"].map((tp, i) => { const r = c.debs.filter((x) => x.tipo === tp && x.taxa_ind != null);
    return { type: "scatter", mode: "markers", name: tp, x: r.map((x) => x.duration_anos), y: r.map((x) => x.taxa_ind), text: r.map((x) => x.ativo),
      marker: { size: r.map((x) => 6 + Math.sqrt(Math.max(x.perc_pl, 0)) * 12), color: CORES[i], line: { color: css("--surface-1"), width: 1.5 } },
      hovertemplate: "%{text}<br>duration %{x:.2f}a · taxa %{y:.2f}%<extra></extra>" }; }),
    base("Taxa indicativa x duration (tamanho = % do PL)", { hovermode: "closest", legend: { x: 0.01, y: 0.99, bgcolor: "rgba(0,0,0,0)" }, xaxis: { title: "duration (anos)", gridcolor: css("--grid") },
      yaxis: { title: "taxa (% a.a.)", gridcolor: css("--grid") } }), 340);
  if (c.hist && c.hist.datas && c.hist.datas.length > 1) {
    $("#g_hist").outerHTML = `<div class="grade g2"><div id="g_h1" class="grafico"></div><div id="g_h2" class="grafico"></div></div>
      <p class="legenda">Mesma carteira, marcação de cada dia guardado (${R.meta.anbima_dias} dias). O site gratuito da ANBIMA mantém ~15 dias úteis; o histórico cresce a cada uso.</p>`;
    plota("g_h1", [{ x: c.hist.datas, y: c.hist.spread_di, mode: "lines+markers", line: { color: CORES[0] }, name: "DI +" }], base("Spread médio DI + (% a.a.)"), 280);
    plota("g_h2", [{ x: c.hist.datas, y: c.hist.duration, mode: "lines+markers", line: { color: CORES[2] }, name: "duration" }], base("Duration média (anos)"), 280);
  }
  $("#t_deb").innerHTML = tabela([{ t: "Ativo", k: "ativo", w: 1 }, { t: "Código", k: "codigo" }, { t: "% PL", k: "perc_pl", n: 1, f: (v) => pct(v, 3) },
    { t: "Indexador", k: "indice" }, { t: "Taxa indicativa", k: "taxa_ind", n: 1, f: (v) => pct(v) }, { t: "Duration (anos)", k: "duration_anos", n: 1, f: (v) => num(v) },
    { t: "% PU par", k: "pct_par", n: 1, f: (v) => num(v) }, { t: "Vencimento", k: "venc" }, { t: "Veículo", k: "veiculo", w: 1 }], c.debs, 380);
  const b1 = barH(c.indexador.sort((a, b) => b.perc_pl - a.perc_pl), "perc_pl", "k", CORES[0], "Indexador (CDA)"); plota("g_idx", b1.d, b1.l, 320);
  plota("g_prz", [{ type: "bar", x: c.prazo.map((x) => x.k), y: c.prazo.map((x) => x.perc_pl), marker: { color: CORES[2] }, hovertemplate: "%{y:.2f}% do PL<extra></extra>" }],
    base("Prazo até o vencimento", { hovermode: "closest", yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 320);
  const b3 = barH(c.rating.sort((a, b) => b.perc_pl - a.perc_pl).slice(0, 12), "perc_pl", "k", CORES[6], "Rating"); plota("g_rat", b3.d, b3.l, 320);
  $("#t_res").innerHTML = tabela([{ t: "Categoria", k: "categoria" }, { t: "% PL", k: "perc_pl", n: 1, f: (v) => pct(v) },
    { t: "% PL c/ taxa", k: "perc_com_taxa", n: 1, f: (v) => pct(v) }, { t: "% do índice", k: "pct_indexador", n: 1, f: (v) => num(v) },
    { t: "Cupom/spread", k: "cupom", n: 1, f: (v) => num(v) }, { t: "Taxa pré", k: "taxa_pre", n: 1, f: (v) => num(v) },
    { t: "Prazo médio (anos)", k: "prazo", n: 1, f: (v) => num(v) }], c.resumo, 360);
}

function seletorMes(chave, meses, padrao) {
  st.mes[chave] = meses.includes(st.mes[chave]) ? st.mes[chave] : (meses.includes(padrao) ? padrao : meses[meses.length - 1]);
  return `<label class="seletor">Mês <select id="mes_${chave}">${meses.slice().reverse().map((m) => `<option ${m === st.mes[chave] ? "selected" : ""}>${m}</option>`).join("")}</select>
    <span class="legenda">(começa no último mês com carteira aberta)</span></label>`;
}
function ligaMes(chave) { const s = document.getElementById("mes_" + chave); if (s) s.onchange = () => { st.mes[chave] = s.value; desenha(); }; }

function movimentos(el, R) {
  el.innerHTML = seletorFundo("mov");
  const f = st.fundo.mov, p = R.por_fundo[f]; if (!p) return; const mv = p.movimentos;
  el.insertAdjacentHTML("beforeend", seletorMes("mov", mv.meses, p.mes_aberto));
  const e = mv.por_mes[st.mes.mov] || {};
  el.insertAdjacentHTML("beforeend", `<div class="kpis">
    <div class="kpi"><div class="r">Posições novas</div><div class="v">${num(e.novos, 0)}</div><div class="s">${pct(e.pct_novos)} do PL</div></div>
    <div class="kpi"><div class="r">Posições zeradas</div><div class="v">${num(e.zerados, 0)}</div><div class="s">${pct(e.pct_zerados)} do PL saiu</div></div></div>
    <div class="grade g2"><div id="g_c" class="grafico"></div><div id="g_v" class="grafico"></div></div><div id="g_giro" class="grafico"></div>`);
  ligaMes("mov");
  const c = barH(e.compras || [], "compra", "ativo", CORES[0], `Maiores compras em ${st.mes.mov} (% do PL)`); plota("g_c", c.d, c.l, 460);
  const v = barH(e.vendas || [], "venda", "ativo", CORES[1], `Maiores vendas em ${st.mes.mov} (% do PL)`); plota("g_v", v.d, v.l, 460);
  plota("g_giro", [{ type: "bar", x: mv.meses, y: mv.compras, name: "compras", marker: { color: CORES[0] }, hovertemplate: "%{y:.2f}%" },
    { type: "bar", x: mv.meses, y: mv.vendas.map((x) => -x), name: "vendas", marker: { color: CORES[1] }, hovertemplate: "%{y:.2f}%" }],
    base("Compras e vendas do mês (% do PL, look-through)", { barmode: "relative", yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }));
}

function derivativos(el, R) {
  el.innerHTML = seletorFundo("der");
  const f = st.fundo.der, p = R.por_fundo[f]; if (!p) return; const d = p.derivativos;
  el.insertAdjacentHTML("beforeend", `<p class="legenda">Derivativos aparecem pelo valor que o fundo informa à CVM (em geral o nocional), em % do PL; por isso ficam fora da soma de 100% e dos gráficos de alocação.</p>
    <div id="g_der" class="grafico"></div><div id="t_der"></div><div id="g_fx" class="grafico"></div>`);
  if (!d.meses.length) $("#g_der").outerHTML = `<div class="aviso">Sem derivativos na carteira no período.</div>`;
  else plota("g_der", Object.entries(d.series).map(([k, y], i) => ({ type: "bar", x: d.meses, y, name: k, marker: { color: CORES[i % 8] }, hovertemplate: "%{y:.2f}%" })),
    base("Derivativos por tipo de contrato (% do PL)", { barmode: "relative", yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 420);
  if (d.atual.length) $("#t_der").innerHTML = tabela([{ t: "Categoria", k: "categoria" }, { t: "Contrato", k: "tipo_ativo" }, { t: "Ativo", k: "ativo", w: 1 },
    { t: "Veículo", k: "veiculo", w: 1 }, { t: "% PL", k: "perc_pl", n: 1, f: (v) => pct(v, 3) }], d.atual, 300);
  plota("g_fx", [{ x: d.moeda.meses, y: d.moeda.exterior, name: "Investimento no exterior", line: { color: CORES[3], width: 2 } },
    { x: d.moeda.meses, y: d.moeda.dolar, name: "Futuros de dólar (nocional)", line: { color: CORES[6], width: 2 } }],
    base("Exposição a moeda estrangeira (% do PL)", { yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 300);
}

function marcacao(el, R) {
  el.innerHTML = `<p class="legenda">Efeito de marcação estimado com a CDA mensal: quantidade do mês anterior × variação do preço unitário (valor ÷ quantidade), só para ativos mantidos de um mês para o outro, em % do PL. Não inclui carrego de caixa/compromissadas, ganho de negociação nem ativos confidenciais. <b>Pagamentos de juros/amortização aparecem como queda de preço</b>: use para ver marcações e eventos de crédito, não como P&L contábil. A linha é o retorno real da cota.</p>` + seletorFundo("mar");
  const f = st.fundo.mar, p = R.por_fundo[f]; if (!p) return; const m = p.marcacao;
  if (!m) return el.insertAdjacentHTML("beforeend", `<div class="aviso">Precisa de pelo menos dois meses de carteira.</div>`);
  el.insertAdjacentHTML("beforeend", `<div id="g_mar" class="grafico"></div>${seletorMes("mar", m.meses, p.mes_aberto)}
    <div class="grade g2"><div id="g_alt" class="grafico"></div><div id="g_que" class="grafico"></div></div>
    <h2>No período inteiro</h2><div class="grade g2"><div id="t_alt"></div><div id="t_que"></div></div>`);
  ligaMes("mar");
  const d = Object.entries(m.series).map(([c, y]) => ({ type: "bar", x: m.meses, y, name: c, marker: { color: corCat(c) }, hovertemplate: "%{y:.2f}%" }));
  d.push({ x: m.meses, y: m.real, name: "retorno real da cota", mode: "lines+markers", line: { color: css("--text-1"), width: 2 }, hovertemplate: "%{y:.2f}%" });
  plota("g_mar", d, base("Efeito de marcação por categoria e retorno real da cota (% do PL)", { barmode: "relative", yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 420);
  const e = m.por_mes[st.mes.mar] || { altas: [], quedas: [] };
  const a = barH(e.altas, "resultado_pct", "ativo", CORES[0], `Maiores altas de preço em ${st.mes.mar}`); plota("g_alt", a.d, a.l, 440);
  const q = barH(e.quedas.slice().reverse(), "resultado_pct", "ativo", CORES[1], `Maiores quedas de preço em ${st.mes.mar}`); plota("g_que", q.d, q.l, 440);
  const cols = [{ t: "Ativo", k: "ativo", w: 1 }, { t: "Categoria", k: "categoria" }, { t: "% PL", k: "resultado_pct", n: 1, f: (v) => pct(v, 3) }];
  $("#t_alt").innerHTML = tabela(cols, m.periodo.altas, 420); $("#t_que").innerHTML = tabela(cols, m.periodo.quedas, 420);
}

function comparacao(el, R) {
  const al = R.comparacao.alocacao, em = R.comparacao.emissores;
  const cr = R.meta.fundos.filter((f) => R.por_fundo[f.nome]).map((f) => ({ fundo: f.nome, ...R.por_fundo[f.nome].credito }));
  el.innerHTML = `<h2>Alocação por categoria na última carteira (% do PL)</h2>` +
    tabela([{ t: "Categoria", k: 0 }, ...al.fundos.map((f, i) => ({ t: esc(f), k: i + 1, n: 1, f: (v) => num(v) }))], al.linhas, 420) +
    `<h2>Crédito: debêntures com marcação ANBIMA (última carteira aberta)</h2>` +
    tabela([{ t: "Fundo", k: "fundo" }, { t: "Carteira", k: "mes" }, { t: "Debêntures (%PL)", k: "deb_pl", n: 1, f: (v) => num(v) },
      { t: "Cobertura ANBIMA", k: "cobertura", n: 1, f: (v) => pct(v, 0) }, { t: "Spread DI +", k: "spread_di", n: 1, f: (v) => pct(v) },
      { t: "Taxa IPCA +", k: "taxa_ipca", n: 1, f: (v) => pct(v) }, { t: "Duration (anos)", k: "duration", n: 1, f: (v) => num(v) }], cr, 300) +
    (em.linhas.length ? `<h2>Emissores em comum (% do PL)</h2>` + tabela([{ t: "Emissor", k: 0, w: 1 }, ...em.fundos.map((f, i) => ({ t: esc(f), k: i + 1, n: 1, f: (v) => num(v) }))], em.linhas, 420) : "") +
    `<div id="g_rr" class="grafico"></div>`;
  plota("g_rr", R.kpis.map((k) => ({ type: "scatter", mode: "markers+text", x: [k.vol], y: [k.pct_cdi12], text: [k.fundo], textposition: "top center", name: k.fundo,
    marker: { size: 12 + Math.sqrt(Math.max(k.pl_mi || 1, 1)) / 2, color: cor(k.fundo), line: { color: css("--surface-1"), width: 2 } },
    hovertemplate: `${esc(k.fundo)}<br>vol %{x:.2f}% · %{y:.1f}% do CDI<extra></extra>` })),
    base("Risco x retorno (12 meses): volatilidade anual x %CDI", { hovermode: "closest", showlegend: false,
      xaxis: { title: "volatilidade anual (%)", gridcolor: css("--grid") }, yaxis: { title: "%CDI 12m", gridcolor: css("--grid") } }), 420);
}

function dados(el) {
  el.innerHTML = `<h2>Downloads</h2><p class="links"><a href="/api/csv/${st.chave}/carteira">Carteira look-through (CSV)</a>
    <a href="/api/csv/${st.chave}/cotas">Cotas diárias (CSV)</a></p>
    <p class="legenda">CSV com ponto e vírgula e vírgula decimal (abre direto no Excel em português).</p>
    <h2>Fontes</h2><ul class="legenda"><li>CVM, dados abertos: CDA (carteira mensal), informe diário, cadastro de fundos (dados.cvm.gov.br)</li>
    <li>ANBIMA: mercado secundário de debêntures, taxa indicativa diária (anbima.com.br)</li><li>Banco Central: CDI, série SGS 12</li></ul>`;
}
