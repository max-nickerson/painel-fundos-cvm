// Painel de fundos - frontend sem framework. Os dados ja vem processados do servidor (/api).
const $ = (s, el = document) => el.querySelector(s);
const CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const nf = (d) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (v, d = 2) => (v == null || Number.isNaN(v) ? "–" : nf(d).format(v));
const pct = (v, d = 2) => (v == null || Number.isNaN(v) ? "–" : nf(d).format(v) + "%");
const sinal = (v) => (v == null ? "" : v >= 0 ? "pos" : "neg");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const mesBR = (m) => { if (!m) return "–"; const [a, b] = m.split("-"); return ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"][+b - 1] + "/" + a; };
const dataBR = (d) => (d ? new Date(d + "T12:00").toLocaleDateString("pt-BR") : "–");
const st = { R: null, chave: null, secao: "resumo", foco: null, ocultos: new Set(), mes: {}, novos: [] };

const SECOES = [
  { g: "Visão geral", id: "resumo", t: "Resumo", d: "Os números principais de cada fundo e o retorno acumulado contra o CDI.", fn: resumo },
  { g: "Desempenho", id: "rentab", t: "Rentabilidade", d: "Retorno por ano e por mês em % do CDI, retorno acumulado e drawdown (queda desde o pico anterior).", fn: rentab },
  { id: "pl", t: "Patrimônio & captação", d: "Patrimônio líquido, aplicações menos resgates de cada mês e número de cotistas.", fn: plcap },
  { g: "Carteira (fundo em foco)", id: "alocacao", t: "Alocação", d: "Carteira look-through: as cotas de outros fundos são abertas até o ativo final. Fonte: CDA mensal da CVM.", foco: 1, fn: alocacao },
  { id: "credito", t: "Crédito", d: "Spread, taxa e duration das debêntures pela marcação ANBIMA, e indexador, prazo e rating informados à CVM.", foco: 1, fn: credito },
  { id: "mov", t: "Movimentações", d: "Compras e vendas do mês informadas na CDA, posições novas e zeradas.", foco: 1, fn: movimentos },
  { id: "deriv", t: "Derivativos & moeda", d: "Futuros, opções e swaps pelo valor informado (em geral o nocional) e a exposição a moeda estrangeira.", foco: 1, fn: derivativos },
  { id: "marc", t: "Marcação (estimada)", d: "Variação de preço das posições mantidas de um mês para o outro. Não é P&L contábil: cupons e amortizações aparecem como queda de preço.", foco: 1, fn: marcacao },
  { g: "Peers", id: "comp", t: "Comparação", d: "Os fundos lado a lado: alocação, crédito, emissores em comum e risco x retorno.", fn: comparacao },
  { id: "dados", t: "Dados & fontes", d: "Downloads e de onde vem cada número.", fn: dados },
];

// ------------------------------------------------------------------ tema
try { const t = localStorage.getItem("tema"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
$("#tema").onclick = () => {
  const escuro = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = escuro ? "light" : "dark";
  try { localStorage.setItem("tema", document.documentElement.dataset.theme); } catch (e) {}
  if (st.R) desenha();
};

// ------------------------------------------------------------------ carga inicial (servidor ja baixou/processou os peers)
const espera = (ms) => new Promise((ok) => setTimeout(ok, ms));
async function inicia() {
  for (;;) {
    let s;
    try { s = await (await fetch("/api/inicial")).json(); } catch (e) { await espera(2000); continue; }
    $("#log-carga").textContent = (s.log || []).join("\n") || "Iniciando...";
    if (s.status === "erro") { $("#log-carga").textContent += "\n\nErro: " + s.erro; return; }
    if (s.status === "ok") return abre(s.chave);
    await espera(2000);
  }
}
async function abre(chave) {
  st.R = await (await fetch("/api/resultado/" + chave)).json();
  st.chave = chave;
  const fs = st.R.meta.fundos.map((f) => f.nome);
  if (!fs.includes(st.foco)) st.foco = (st.R.meta.fundos.find((f) => st.R.por_fundo[f.nome]) || {}).nome;
  st.ocultos = new Set([...st.ocultos].filter((f) => fs.includes(f)));
  const m = st.R.meta;
  $("#datas").textContent = `${m.fundos.length} fundos · carteiras até ${mesBR(m.ult_carteira)} · cotas até ${dataBR(m.ult_cota)} · ANBIMA ${dataBR(m.anbima_data)} · desde ${mesBR(m.desde)}`;
  $("#carregando").hidden = true;
  menu(); desenha();
}
inicia();

// ------------------------------------------------------------------ navegacao
function menu() {
  $("#menu").innerHTML = SECOES.map((s) => (s.g ? `<div class="grupo">${s.g}</div>` : "") +
    `<button data-s="${s.id}" aria-current="${s.id === st.secao}">${s.t}</button>`).join("");
  $("#menu").querySelectorAll("button").forEach((b) => (b.onclick = () => { st.secao = b.dataset.s; menu(); desenha(); scrollTo(0, 0); }));
}
const fundosVisiveis = () => st.R.meta.fundos.filter((f) => !st.ocultos.has(f.nome));
const cor = (f) => (st.R.meta.fundos.find((x) => x.nome === f) || {}).cor || CORES[0];
const corCat = (c) => st.R.categorias[c] || "#898781";

function desenha() {
  const s = SECOES.find((x) => x.id === st.secao), R = st.R;
  $("#titulo").textContent = s.t; $("#descricao").textContent = s.d;
  const comFoco = R.meta.fundos.filter((f) => R.por_fundo[f.nome]);
  $("#foco").innerHTML = s.foco ? `<span class="rot">Fundo em foco</span>` + comFoco.map((f) =>
    `<button class="pill" aria-pressed="${f.nome === st.foco}" data-f="${esc(f.nome)}"><span class="ponto" style="background:${f.cor}"></span>${esc(f.nome)}</button>`).join("") : "";
  $("#foco").querySelectorAll("button").forEach((b) => (b.onclick = () => { st.foco = b.dataset.f; desenha(); }));
  $("#legenda").innerHTML = s.foco || s.id === "dados" ? "" : R.meta.fundos.map((f) =>
    `<button class="pill ${st.ocultos.has(f.nome) ? "desligado" : ""}" data-f="${esc(f.nome)}" title="Mostrar/ocultar nos gráficos"><span class="ponto" style="background:${f.cor}"></span>${esc(f.nome)}</button>`).join("");
  $("#legenda").querySelectorAll("button").forEach((b) => (b.onclick = () => {
    st.ocultos.has(b.dataset.f) ? st.ocultos.delete(b.dataset.f) : st.ocultos.add(b.dataset.f); desenha(); }));
  const el = $("#conteudo");
  try { el.innerHTML = ""; s.fn(el, R); }
  catch (e) { el.innerHTML = `<div class="aviso">Não foi possível desenhar esta seção: ${esc(e.message)}</div>`; console.error(e); }
}

// ------------------------------------------------------------------ componentes
const card = (id, titulo, sub = "") => `<div class="cartao"><h3>${titulo}</h3>${sub ? `<p class="sub">${sub}</p>` : ""}<div id="${id}" class="grafico"></div></div>`;
const cardHTML = (titulo, html, sub = "") => `<div class="cartao"><h3>${titulo}</h3>${sub ? `<p class="sub">${sub}</p>` : ""}${html}</div>`;
const kpi = (r, v, s = "", cls = "") => `<div class="kpi"><div class="r">${r}</div><div class="v ${cls}">${v}</div><div class="s">${s}</div></div>`;
function layout(extra = {}) {
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: css("--font"), size: 12, color: css("--text-2") },
    margin: { l: 48, r: 12, t: 8, b: 36 }, hovermode: "x unified",
    legend: { orientation: "h", y: -0.16, font: { color: css("--text-2") } },
    xaxis: { gridcolor: "rgba(0,0,0,0)", linecolor: css("--line-2"), automargin: true },
    yaxis: { gridcolor: css("--line"), zerolinecolor: css("--line-2"), automargin: true },
    hoverlabel: { bgcolor: css("--surface"), bordercolor: css("--line-2"), font: { color: css("--text-1") } },
  }, extra);
}
const yPct = (extra = {}) => Object.assign({ ticksuffix: "%", gridcolor: css("--line"), zerolinecolor: css("--line-2"), automargin: true }, extra);
function plota(id, dados, lay, h = 320) {
  const el = document.getElementById(id); if (!el) return;
  el.style.height = h + "px";
  Plotly.newPlot(el, dados, lay, { displaylogo: false, responsive: true, displayModeBar: innerWidth > 700 ? "hover" : false,
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] });
}
const periodos = { buttons: [{ count: 12, label: "12m", step: "month", stepmode: "backward" }, { count: 24, label: "24m", step: "month", stepmode: "backward" },
  { count: 1, label: "No ano", step: "year", stepmode: "todate" }, { step: "all", label: "Tudo" }] };
const comPeriodos = () => ({ type: "date", rangeselector: Object.assign({ x: 0, y: 1.12, bgcolor: css("--surface-2"), activecolor: css("--accent-soft"),
  font: { color: css("--text-1") } }, periodos), gridcolor: "rgba(0,0,0,0)", linecolor: css("--line-2") });
function barH(rows, xk, yk, c, h = 380, fmt = "%{x:.3f}% do PL") {
  return { d: [{ type: "bar", orientation: "h", x: rows.map((r) => r[xk]).reverse(), y: rows.map((r) => r[yk]).reverse(), marker: { color: c },
    hovertemplate: "%{y}<br>" + fmt + "<extra></extra>" }],
    l: layout({ hovermode: "closest", margin: { l: 8, r: 12, t: 4, b: 30 }, yaxis: { automargin: true, gridcolor: "rgba(0,0,0,0)", tickfont: { size: 11 } },
      xaxis: { ticksuffix: "%", gridcolor: css("--line"), zerolinecolor: css("--line-2") } }), h };
}
function tabela(cols, linhas, alt = 420) {
  return `<div class="tabela-wrap" style="max-height:${alt}px"><table><thead><tr>${cols.map((c) => `<th class="${c.n ? "n" : ""}">${c.t}</th>`).join("")}</tr></thead><tbody>${
    linhas.map((r) => `<tr>${cols.map((c) => { const v = r[c.k]; return `<td class="${c.n ? "n" : c.w ? "texto" : ""}" ${c.bg ? `style="background:${c.bg(v, r)}"` : ""}>${c.f ? c.f(v, r) : esc(v ?? "–")}</td>`; }).join("")}</tr>`).join("")
  }</tbody></table></div>`;
}
function seletorMes(chave, meses, padrao) {
  st.mes[chave] = meses.includes(st.mes[chave]) ? st.mes[chave] : (meses.includes(padrao) ? padrao : meses[meses.length - 1]);
  return `<div class="filtros"><label>Mês <select id="mes_${chave}">${meses.slice().reverse().map((m) => `<option value="${m}" ${m === st.mes[chave] ? "selected" : ""}>${mesBR(m)}</option>`).join("")}</select></label>
    <span class="sub">Começa no último mês com carteira aberta (meses recentes podem ter ativos confidenciais).</span></div>`;
}
const ligaMes = (chave) => { const s = document.getElementById("mes_" + chave); if (s) s.onchange = () => { st.mes[chave] = s.value; desenha(); }; };

// ------------------------------------------------------------------ Resumo
function resumo(el, R) {
  const vis = new Set(fundosVisiveis().map((f) => f.nome));
  const ks = R.kpis.filter((k) => vis.has(k.fundo));
  el.innerHTML = `<div class="fundos">${ks.map((k) => `<div class="fcard" style="--c:${cor(k.fundo)}">
      <div class="nome">${esc(k.fundo)}</div><div class="cnpj">${esc((R.meta.fundos.find((f) => f.nome === k.fundo) || {}).cnpj)}</div>
      <div class="pl">R$ ${num(k.pl_mi / 1000, 2)} bi <small>de PL</small></div>
      <dl><dt>Retorno 12 meses</dt><dd class="${sinal(k.ret12)}">${pct(k.ret12)}</dd>
      <dt>% do CDI 12 meses</dt><dd>${pct(k.pct_cdi12, 1)}</dd><dt>Retorno no ano</dt><dd class="${sinal(k.ret_ano)}">${pct(k.ret_ano)}</dd>
      <dt>Volatilidade anual</dt><dd>${pct(k.vol)}</dd><dt>Pior drawdown</dt><dd class="neg">${pct(k.dd)}</dd>
      <dt>Captação líquida 12m</dt><dd class="${sinal(k.capt12_mi)}">R$ ${num(k.capt12_mi, 0)} mi</dd>
      <dt>Cotistas</dt><dd>${num(k.cotistas, 0)}</dd><dt>Ativos na carteira</dt><dd>${num(k.ativos, 0)}</dd>
      <dt>Carteira (aberta)</dt><dd>${mesBR(k.ult_carteira)} (${mesBR(k.carteira_aberta)})</dd></dl></div>`).join("")}</div>
    ${card("g_acum", "Retorno acumulado x CDI", "Use os botões para mudar o período.")}
    ${card("g_hm", "% do CDI mês a mês", "Azul: acima do CDI · laranja: abaixo")}`;
  acumulado("g_acum", R, 400);
  heatmap("g_hm", R, 24);
}
function acumulado(id, R, h) {
  const d = fundosVisiveis().filter((f) => R.cotas[f.nome]).map((f) => ({ x: R.cotas[f.nome].datas, y: R.cotas[f.nome].acum, name: f.nome,
    line: { color: f.cor, width: 2.2 }, hovertemplate: "%{y:.2f}%" }));
  d.push({ x: R.cdi.datas, y: R.cdi.acum, name: "CDI", line: { color: css("--text-2"), width: 2, dash: "dash" }, hovertemplate: "%{y:.2f}%" });
  plota(id, d, layout({ xaxis: comPeriodos(), yaxis: yPct(), margin: { l: 48, r: 12, t: 30, b: 36 } }), h);
}
function heatmap(id, R, ultimos) {
  const fs = fundosVisiveis().map((f) => f.nome).filter((f) => R.cotas[f]);
  let meses = [...new Set(R.mensal.map((r) => r.mes))].sort();
  if (ultimos) meses = meses.slice(-ultimos);
  const z = fs.map((f) => meses.map((m) => { const r = R.mensal.find((x) => x.fundo === f && x.mes === m); return r && r.pct_cdi != null ? r.pct_cdi * 100 : null; }));
  plota(id, [{ type: "heatmap", x: meses.map(mesBR), y: fs, z, zmin: 0, zmax: 200, zmid: 100, xgap: 2, ygap: 2,
    colorscale: [[0, "#eb6834"], [0.5, css("--surface-2")], [1, "#2a78d6"]], colorbar: { ticksuffix: "%", thickness: 10, len: 0.9 },
    hovertemplate: "%{y} · %{x}<br>%{z:.0f}% do CDI<extra></extra>" }],
    layout({ hovermode: "closest", yaxis: { autorange: "reversed", automargin: true }, xaxis: { type: "category", tickangle: -45, automargin: true } }),
    90 + 34 * fs.length);
}

// ------------------------------------------------------------------ Rentabilidade
function rentab(el, R) {
  const fs = fundosVisiveis().filter((f) => R.cotas[f.nome]);
  const anos = [...new Set(R.mensal.map((r) => r.mes.slice(0, 4)))].sort().reverse();
  const linhas = anos.map((a) => { const o = { ano: a };
    fs.forEach((f) => { const ms = R.mensal.filter((r) => r.fundo === f.nome && r.mes.startsWith(a) && r.retorno != null);
      if (!ms.length) return; const ret = ms.reduce((p, r) => p * (1 + r.retorno), 1) - 1, cdi = ms.reduce((p, r) => p * (1 + (r.cdi || 0)), 1) - 1;
      o[f.nome] = { ret: ret * 100, pc: cdi ? (ret / cdi) * 100 : null, n: ms.length }; });
    return o; });
  const celula = (v) => (v ? `<b class="${sinal(v.ret)}">${pct(v.ret)}</b> <span class="sub">· ${pct(v.pc, 0)} CDI${v.n < 12 ? ` · ${v.n}m` : ""}</span>` : "–");
  el.innerHTML = cardHTML("Retorno por ano", tabela([{ t: "Ano", k: "ano" }, ...fs.map((f) => ({ t: `<span style="color:${f.cor}">■</span> ${esc(f.nome)}`, k: f.nome, n: 1, f: celula }))], linhas, 360),
      "Retorno da cota no ano e % do CDI no mesmo período (anos incompletos mostram o nº de meses).") +
    card("g_acum2", "Retorno acumulado x CDI") + card("g_hm2", "% do CDI mês a mês") +
    `<div class="grade g2">${card("g_mes", "Retorno mensal")}${card("g_dd", "Drawdown", "Queda desde o pico anterior da cota")}</div>`;
  acumulado("g_acum2", R, 380);
  heatmap("g_hm2", R, 0);
  plota("g_mes", fs.map((f) => { const r = R.mensal.filter((x) => x.fundo === f.nome && x.retorno != null);
    return { type: "bar", x: r.map((x) => x.mes + "-15"), y: r.map((x) => x.retorno * 100), name: f.nome, marker: { color: f.cor }, hovertemplate: "%{y:.2f}%" }; }),
    layout({ barmode: "group", xaxis: comPeriodos(), yaxis: yPct(), margin: { l: 48, r: 12, t: 30, b: 36 } }), 340);
  plota("g_dd", fs.map((f) => ({ x: R.cotas[f.nome].datas, y: R.cotas[f.nome].dd, name: f.nome, line: { color: f.cor, width: 2 }, hovertemplate: "%{y:.2f}%" })),
    layout({ xaxis: comPeriodos(), yaxis: yPct(), margin: { l: 48, r: 12, t: 30, b: 36 } }), 340);
}

// ------------------------------------------------------------------ Patrimonio & captacao
function plcap(el, R) {
  const fs = fundosVisiveis().filter((f) => R.cotas[f.nome]);
  el.innerHTML = card("g_pl", "Patrimônio líquido", "R$ milhões") + card("g_cap", "Captação líquida mensal", "Aplicações menos resgates, R$ milhões") +
    card("g_cot", "Número de cotistas");
  plota("g_pl", fs.map((f) => ({ x: R.cotas[f.nome].datas, y: R.cotas[f.nome].pl, name: f.nome, line: { color: f.cor, width: 2 }, hovertemplate: "R$ %{y:,.1f} mi" })),
    layout({ xaxis: comPeriodos(), margin: { l: 56, r: 12, t: 30, b: 36 } }), 340);
  plota("g_cap", fs.map((f) => { const r = R.mensal.filter((x) => x.fundo === f.nome);
    return { type: "bar", x: r.map((x) => x.mes + "-15"), y: r.map((x) => x.capt_mi), name: f.nome, marker: { color: f.cor }, hovertemplate: "R$ %{y:,.1f} mi" }; }),
    layout({ barmode: "group", xaxis: comPeriodos(), margin: { l: 56, r: 12, t: 30, b: 36 } }), 340);
  plota("g_cot", fs.map((f) => ({ x: R.cotas[f.nome].datas, y: R.cotas[f.nome].cotistas, name: f.nome, line: { color: f.cor, width: 2 } })),
    layout({ xaxis: comPeriodos(), margin: { l: 56, r: 12, t: 30, b: 36 } }), 300);
}

// ------------------------------------------------------------------ Alocacao (fundo em foco)
function alocacao(el, R) {
  const f = st.foco, p = R.por_fundo[f]; if (!p) return (el.innerHTML = `<div class="aviso">Sem carteira para este fundo no período.</div>`);
  const k = R.kpis.find((x) => x.fundo === f) || {};
  const conf = p.carteira.filter((x) => String(x.ativo).startsWith("(confidencial)")).reduce((s, x) => s + x.perc_pl, 0);
  const ult = Object.fromEntries(Object.entries(p.alocacao.series).map(([c, y]) => [c, y[y.length - 1]]));
  const topCat = Object.entries(ult).filter(([c]) => c !== "Outros").sort((a, b) => b[1] - a[1])[0] || ["–", null];
  el.innerHTML = `<div class="kpis">${kpi("Carteira", mesBR(p.ult_mes), "último mês publicado")}${kpi("Ativos", num(k.ativos, 0), "posições distintas")}
      ${kpi("Maior categoria", pct(topCat[1], 1), esc(topCat[0]))}${kpi("Top 10 emissores", pct(k.top10_emissores, 1), "concentração")}
      ${kpi("Confidencial", pct(conf, 1), "do PL ainda não divulgado")}</div>
    ${card("g_area", "Composição ao longo do tempo", "% do PL por categoria (sem derivativos)")}
    <div class="grade g2">${card("g_cat", `Alocação em ${mesBR(p.ult_mes)}`, "% do PL por categoria")}${card("g_emi", "Maiores emissores", "% do PL")}</div>
    <div class="cartao"><h3>Carteira de ${mesBR(p.ult_mes)}</h3><p class="sub">Uma linha por ativo final (look-through). Filtre por texto ou categoria.</p>
      <div class="filtros"><input id="filtro" placeholder="Buscar ativo, emissor, código..."><select id="fcat"><option value="">Todas as categorias</option>${
        [...new Set(p.carteira.map((x) => x.categoria))].sort().map((c) => `<option>${esc(c)}</option>`).join("")}</select></div><div id="t_cart"></div></div>`;
  plota("g_area", Object.entries(p.alocacao.series).map(([c, y]) => ({ x: p.alocacao.meses.map((m) => m + "-15"), y, name: c, stackgroup: "a",
    line: { width: 0.6, color: css("--surface") }, fillcolor: corCat(c), hovertemplate: "%{y:.1f}%" })),
    layout({ xaxis: comPeriodos(), yaxis: yPct(), margin: { l: 48, r: 12, t: 30, b: 36 } }), 400);
  const cats = Object.entries(ult).sort((a, b) => b[1] - a[1]).map(([c, v]) => ({ c, v }));
  plota("g_cat", [{ type: "bar", orientation: "h", y: cats.map((x) => x.c).reverse(), x: cats.map((x) => x.v).reverse(), marker: { color: cats.map((x) => corCat(x.c)).reverse() },
    hovertemplate: "%{y}: %{x:.2f}%<extra></extra>" }], layout({ hovermode: "closest", margin: { l: 8, r: 12, t: 4, b: 30 },
    yaxis: { automargin: true, gridcolor: "rgba(0,0,0,0)" }, xaxis: { ticksuffix: "%", gridcolor: css("--line") } }), 380);
  const e = barH(p.emissores, "perc_pl", "emissor", CORES[0]); plota("g_emi", e.d, e.l, 380);
  const cols = [{ t: "Categoria", k: "categoria" }, { t: "Ativo", k: "ativo", w: 1 }, { t: "Código", k: "codigo" }, { t: "Emissor", k: "emissor", w: 1 },
    { t: "% do PL", k: "perc_pl", n: 1, f: (v) => pct(v, 3) }, { t: "Via (veículo)", k: "veiculo", w: 1 }];
  const pinta = () => { const q = $("#filtro").value.toLowerCase(), c = $("#fcat").value;
    const r = p.carteira.filter((x) => (!c || x.categoria === c) && (!q || [x.ativo, x.emissor, x.codigo].join(" ").toLowerCase().includes(q)));
    $("#t_cart").innerHTML = tabela(cols, r.slice(0, 800), 480) + `<p class="sub">${num(r.length, 0)} linhas · ${pct(r.reduce((s, x) => s + x.perc_pl, 0), 2)} do PL${r.length > 800 ? " · mostrando 800 (CSV completo em Dados & fontes)" : ""}</p>`; };
  $("#filtro").oninput = pinta; $("#fcat").onchange = pinta; pinta();
}

// ------------------------------------------------------------------ Credito
function credito(el, R) {
  const f = st.foco, p = R.por_fundo[f]; if (!p) return; const c = p.credito;
  el.innerHTML = `<div class="aviso">Carteira de <b>${mesBR(c.mes)}</b> (último mês com menos de 5% do PL confidencial). Taxas e duration das debêntures: marcação ANBIMA de <b>${dataBR(R.meta.anbima_data)}</b>.</div>
    <div class="kpis">${kpi("Debêntures", pct(c.deb_pl, 1), "do PL")}${kpi("Com taxa ANBIMA", pct(c.cobertura, 0), "das debêntures")}
      ${kpi("Spread médio DI +", pct(c.spread_di), `a.a. · ${pct(c.pl_di, 1)} do PL`)}${kpi("Taxa média IPCA +", pct(c.taxa_ipca), `a.a. · ${pct(c.pl_ipca, 1)} do PL`)}
      ${kpi("Duration média", num(c.duration) + " anos", "debêntures com taxa")}</div>
    <div class="grade g2">${card("g_sc", "Taxa x duration por debênture", "Tamanho = % do PL · passe o mouse para ver o ativo")}${card("g_tipo", "Debêntures por indexador", "% do PL")}</div>
    <div id="hist"></div>
    ${cardHTML("Debêntures da carteira", `<div id="t_deb"></div>`, "Marcação ANBIMA do dia; “–” = sem taxa indicativa publicada")}
    <div class="grade g3">${card("g_idx", "Indexador (informado à CVM)", "Depósitos bancários e crédito privado")}${card("g_prz", "Prazo até o vencimento", "% do PL")}${card("g_rat", "Rating", "% do PL")}</div>
    ${cardHTML("Resumo por categoria", `<div id="t_res"></div>`, "Médias ponderadas pelo % do PL, só onde a CVM informa a taxa")}`;
  plota("g_sc", ["DI +", "IPCA +"].map((tp, i) => { const r = c.debs.filter((x) => x.tipo === tp && x.taxa_ind != null);
    return { type: "scatter", mode: "markers", name: tp, x: r.map((x) => x.duration_anos), y: r.map((x) => x.taxa_ind), text: r.map((x) => x.ativo),
      marker: { size: r.map((x) => 7 + Math.sqrt(Math.max(x.perc_pl, 0)) * 12), color: CORES[i], opacity: 0.85, line: { color: css("--surface"), width: 1.5 } },
      hovertemplate: "%{text}<br>duration %{x:.2f} anos · taxa %{y:.2f}% a.a.<extra></extra>" }; }),
    layout({ hovermode: "closest", legend: { x: 0.01, y: 0.99, bgcolor: "rgba(0,0,0,0)" }, xaxis: { title: "duration (anos)", gridcolor: css("--line"), zeroline: false },
      yaxis: { title: "taxa indicativa (% a.a.)", gridcolor: css("--line"), zeroline: false } }), 360);
  const t = barH(c.por_tipo.slice().sort((a, b) => b.perc_pl - a.perc_pl), "perc_pl", "t", CORES[0]); plota("g_tipo", t.d, t.l, 360);
  if (c.hist && c.hist.datas && c.hist.datas.length > 1) {
    $("#hist").outerHTML = `<div class="grade g2">${card("g_h1", "Spread médio DI + ao longo dos dias", "Mesma carteira, marcação ANBIMA de cada dia guardado")}${card("g_h2", "Duration média ao longo dos dias", `${R.meta.anbima_dias} dias guardados; cresce a cada dia de uso`)}</div>`;
    plota("g_h1", [{ x: c.hist.datas, y: c.hist.spread_di, mode: "lines+markers", line: { color: CORES[0], width: 2 }, name: "DI +", hovertemplate: "%{y:.3f}%" }], layout({ yaxis: yPct() }), 260);
    plota("g_h2", [{ x: c.hist.datas, y: c.hist.duration, mode: "lines+markers", line: { color: CORES[2], width: 2 }, name: "duration", hovertemplate: "%{y:.2f} anos" }], layout(), 260);
  }
  $("#t_deb").innerHTML = tabela([{ t: "Ativo", k: "ativo", w: 1 }, { t: "Código", k: "codigo" }, { t: "% do PL", k: "perc_pl", n: 1, f: (v) => pct(v, 3) },
    { t: "Indexador", k: "indice" }, { t: "Taxa indicativa", k: "taxa_ind", n: 1, f: (v) => pct(v) }, { t: "Duration (anos)", k: "duration_anos", n: 1, f: (v) => num(v) },
    { t: "% PU par", k: "pct_par", n: 1, f: (v) => num(v) }, { t: "Vencimento", k: "venc" }, { t: "Via (veículo)", k: "veiculo", w: 1 }], c.debs, 400);
  const b1 = barH(c.indexador.slice().sort((a, b) => b.perc_pl - a.perc_pl), "perc_pl", "k", CORES[0]); plota("g_idx", b1.d, b1.l, 300);
  plota("g_prz", [{ type: "bar", x: c.prazo.map((x) => x.k), y: c.prazo.map((x) => x.perc_pl), marker: { color: CORES[2] }, hovertemplate: "%{x}: %{y:.2f}% do PL<extra></extra>" }],
    layout({ hovermode: "closest", yaxis: yPct() }), 300);
  const b3 = barH(c.rating.slice().sort((a, b) => b.perc_pl - a.perc_pl).slice(0, 12), "perc_pl", "k", CORES[6]); plota("g_rat", b3.d, b3.l, 300);
  $("#t_res").innerHTML = tabela([{ t: "Categoria", k: "categoria" }, { t: "% do PL", k: "perc_pl", n: 1, f: (v) => pct(v) },
    { t: "% PL c/ taxa", k: "perc_com_taxa", n: 1, f: (v) => pct(v) }, { t: "% do índice", k: "pct_indexador", n: 1, f: (v) => num(v) },
    { t: "Cupom/spread", k: "cupom", n: 1, f: (v) => num(v) }, { t: "Taxa pré", k: "taxa_pre", n: 1, f: (v) => num(v) },
    { t: "Prazo médio (anos)", k: "prazo", n: 1, f: (v) => num(v) }], c.resumo, 360);
}

// ------------------------------------------------------------------ Movimentacoes
function movimentos(el, R) {
  const f = st.foco, p = R.por_fundo[f]; if (!p) return; const mv = p.movimentos;
  el.innerHTML = seletorMes("mov", mv.meses, p.mes_aberto) + `<div id="cont"></div>`;
  ligaMes("mov");
  const e = mv.por_mes[st.mes.mov] || {};
  $("#cont").innerHTML = `<div class="kpis">${kpi("Posições novas", num(e.novos, 0), pct(e.pct_novos) + " do PL")}${kpi("Posições zeradas", num(e.zerados, 0), pct(e.pct_zerados) + " do PL saiu")}
      ${kpi("Compras no mês", pct((e.compras || []).reduce((s, x) => s + x.compra, 0), 2), "top 15, % do PL")}${kpi("Vendas no mês", pct((e.vendas || []).reduce((s, x) => s + x.venda, 0), 2), "top 15, % do PL")}</div>
    <div class="grade g2">${card("g_c", `Maiores compras · ${mesBR(st.mes.mov)}`, "% do PL do fundo (look-through)")}${card("g_v", `Maiores vendas · ${mesBR(st.mes.mov)}`, "% do PL do fundo (look-through)")}</div>
    ${card("g_giro", "Compras e vendas por mês", "% do PL · vendas para baixo")}`;
  const c = barH(e.compras || [], "compra", "ativo", CORES[0]); plota("g_c", c.d, c.l, 440);
  const v = barH(e.vendas || [], "venda", "ativo", CORES[1]); plota("g_v", v.d, v.l, 440);
  plota("g_giro", [{ type: "bar", x: mv.meses.map((m) => m + "-15"), y: mv.compras, name: "compras", marker: { color: CORES[0] }, hovertemplate: "%{y:.2f}%" },
    { type: "bar", x: mv.meses.map((m) => m + "-15"), y: mv.vendas.map((x) => -x), name: "vendas", marker: { color: CORES[1] }, hovertemplate: "%{y:.2f}%" }],
    layout({ barmode: "relative", xaxis: comPeriodos(), yaxis: yPct(), margin: { l: 48, r: 12, t: 30, b: 36 } }), 320);
}

// ------------------------------------------------------------------ Derivativos & moeda
function derivativos(el, R) {
  const f = st.foco, p = R.por_fundo[f]; if (!p) return; const d = p.derivativos;
  const ult = (a) => (a && a.length ? a[a.length - 1] : null);
  el.innerHTML = `<div class="kpis">${kpi("Derivativos (último mês)", d.meses.length ? pct(Object.values(d.series).reduce((s, y) => s + Math.abs(ult(y) || 0), 0), 1) : "–", "soma dos nocionais em valor absoluto")}
      ${kpi("Investimento no exterior", pct(ult(d.moeda.exterior), 2), "do PL")}${kpi("Futuros de dólar", pct(ult(d.moeda.dolar), 2), "nocional, % do PL")}</div>
    ${d.meses.length ? card("g_der", "Derivativos por tipo de contrato", "% do PL (valor informado, em geral nocional)") : `<div class="aviso">Sem derivativos na carteira no período.</div>`}
    ${d.atual.length ? cardHTML("Posições em derivativos no último mês", `<div id="t_der"></div>`) : ""}
    ${card("g_fx", "Exposição a moeda estrangeira", "% do PL")}`;
  if (d.meses.length) plota("g_der", Object.entries(d.series).map(([k, y], i) => ({ type: "bar", x: d.meses.map((m) => m + "-15"), y, name: k, marker: { color: CORES[i % 8] }, hovertemplate: "%{y:.2f}%" })),
    layout({ barmode: "relative", xaxis: comPeriodos(), yaxis: yPct(), margin: { l: 48, r: 12, t: 30, b: 36 } }), 380);
  if (d.atual.length) $("#t_der").innerHTML = tabela([{ t: "Categoria", k: "categoria" }, { t: "Contrato", k: "tipo_ativo" }, { t: "Ativo", k: "ativo", w: 1 },
    { t: "Via (veículo)", k: "veiculo", w: 1 }, { t: "% do PL", k: "perc_pl", n: 1, f: (v) => pct(v, 3) }], d.atual, 300);
  plota("g_fx", [{ x: d.moeda.meses.map((m) => m + "-15"), y: d.moeda.exterior, name: "Investimento no exterior", line: { color: CORES[3], width: 2 }, hovertemplate: "%{y:.2f}%" },
    { x: d.moeda.meses.map((m) => m + "-15"), y: d.moeda.dolar, name: "Futuros de dólar (nocional)", line: { color: CORES[6], width: 2 }, hovertemplate: "%{y:.2f}%" }],
    layout({ xaxis: comPeriodos(), yaxis: yPct(), margin: { l: 48, r: 12, t: 30, b: 36 } }), 300);
}

// ------------------------------------------------------------------ Marcacao estimada
function marcacao(el, R) {
  const f = st.foco, p = R.por_fundo[f]; if (!p) return; const m = p.marcacao;
  if (!m) return (el.innerHTML = `<div class="aviso">Precisa de pelo menos dois meses de carteira.</div>`);
  el.innerHTML = card("g_mar", "Efeito de marcação por categoria x retorno real da cota", "Barras: variação de preço das posições mantidas (% do PL) · linha: retorno da cota no mês") +
    seletorMes("mar", m.meses, p.mes_aberto) + `<div id="cont"></div>`;
  ligaMes("mar");
  const d = Object.entries(m.series).map(([c, y]) => ({ type: "bar", x: m.meses.map((x) => x + "-15"), y, name: c, marker: { color: corCat(c) }, hovertemplate: "%{y:.2f}%" }));
  d.push({ x: m.meses.map((x) => x + "-15"), y: m.real, name: "retorno real da cota", mode: "lines+markers", line: { color: css("--text-1"), width: 2 }, hovertemplate: "%{y:.2f}%" });
  plota("g_mar", d, layout({ barmode: "relative", xaxis: comPeriodos(), yaxis: yPct(), margin: { l: 48, r: 12, t: 30, b: 36 } }), 400);
  const e = m.por_mes[st.mes.mar] || { altas: [], quedas: [] };
  const cols = [{ t: "Ativo", k: "ativo", w: 1 }, { t: "Categoria", k: "categoria" }, { t: "% do PL", k: "resultado_pct", n: 1, f: (v) => `<span class="${sinal(v)}">${pct(v, 3)}</span>` }];
  $("#cont").innerHTML = `<div class="grade g2">${card("g_alt", `Maiores altas de preço · ${mesBR(st.mes.mar)}`)}${card("g_que", `Maiores quedas de preço · ${mesBR(st.mes.mar)}`, "Inclui pagamentos de juros/amortização")}</div>
    <div class="grade g2">${cardHTML("Maiores altas no período inteiro", tabela(cols, m.periodo.altas, 420))}${cardHTML("Maiores quedas no período inteiro", tabela(cols, m.periodo.quedas, 420))}</div>`;
  const a = barH(e.altas, "resultado_pct", "ativo", CORES[0]); plota("g_alt", a.d, a.l, 420);
  const q = barH(e.quedas.slice().reverse(), "resultado_pct", "ativo", CORES[1]); plota("g_que", q.d, q.l, 420);
}

// ------------------------------------------------------------------ Comparacao
function comparacao(el, R) {
  const vis = fundosVisiveis().map((f) => f.nome);
  const al = R.comparacao.alocacao, em = R.comparacao.emissores;
  const idx = (lista) => vis.map((f) => lista.indexOf(f)).filter((i) => i >= 0);
  const fundoCols = (lista) => idx(lista).map((i) => ({ t: `<span style="color:${cor(lista[i])}">■</span> ${esc(lista[i])}`, k: i + 1, n: 1,
    f: (v) => num(v), bg: (v) => `rgba(42,120,214,${Math.min(Math.abs(v || 0) / 60, 0.55).toFixed(3)})` }));
  const cr = R.meta.fundos.filter((f) => R.por_fundo[f.nome] && vis.includes(f.nome)).map((f) => ({ fundo: f.nome, ...R.por_fundo[f.nome].credito }));
  el.innerHTML = cardHTML("Alocação por categoria na última carteira", tabela([{ t: "Categoria", k: 0 }, ...fundoCols(al.fundos)], al.linhas, 440), "% do PL · cor mais forte = peso maior") +
    cardHTML("Crédito: debêntures com marcação ANBIMA", tabela([{ t: "Fundo", k: "fundo", f: (v) => `<span style="color:${cor(v)}">■</span> ${esc(v)}` },
      { t: "Carteira", k: "mes", f: mesBR }, { t: "Debêntures (% PL)", k: "deb_pl", n: 1, f: (v) => num(v, 1) }, { t: "Cobertura ANBIMA", k: "cobertura", n: 1, f: (v) => pct(v, 0) },
      { t: "Spread DI +", k: "spread_di", n: 1, f: (v) => pct(v) }, { t: "Taxa IPCA +", k: "taxa_ipca", n: 1, f: (v) => pct(v) },
      { t: "Duration (anos)", k: "duration", n: 1, f: (v) => num(v) }], cr, 320), "Última carteira aberta de cada fundo") +
    (em.linhas.length ? cardHTML("Emissores em comum", tabela([{ t: "Emissor", k: 0, w: 1 }, ...fundoCols(em.fundos)], em.linhas, 440), "% do PL de cada fundo no mesmo emissor") : "") +
    card("g_rr", "Risco x retorno (12 meses)", "Volatilidade anual x % do CDI · tamanho = PL");
  const ks = R.kpis.filter((k) => vis.includes(k.fundo));
  plota("g_rr", ks.map((k) => ({ type: "scatter", mode: "markers+text", x: [k.vol], y: [k.pct_cdi12], text: [k.fundo], textposition: "top center", name: k.fundo,
    textfont: { color: css("--text-1") }, marker: { size: 14 + Math.sqrt(Math.max(k.pl_mi || 1, 1)) / 2.5, color: cor(k.fundo), opacity: 0.9, line: { color: css("--surface"), width: 2 } },
    hovertemplate: `${esc(k.fundo)}<br>volatilidade %{x:.2f}% · %{y:.1f}% do CDI<extra></extra>` })),
    layout({ hovermode: "closest", showlegend: false, xaxis: { title: "volatilidade anual (%)", gridcolor: css("--line"), zeroline: false },
      yaxis: { title: "% do CDI em 12 meses", gridcolor: css("--line"), zeroline: false } }), 420);
}

// ------------------------------------------------------------------ Dados & fontes
function dados(el, R) {
  el.innerHTML = cardHTML("Downloads", `<p class="links"><a href="/api/csv/${st.chave}/carteira">Carteira look-through (CSV)</a><a href="/api/csv/${st.chave}/cotas">Cotas diárias (CSV)</a></p>
      <p class="sub">CSV com ponto e vírgula e vírgula decimal (abre direto no Excel em português). Gerado em ${esc(R.meta.gerado)}.</p>`) +
    cardHTML("Fontes", `<ul class="sub"><li><b>CVM, dados abertos</b> (dados.cvm.gov.br): CDA (carteira mensal de todos os fundos), informe diário (cota, PL, captação, cotistas), cadastro de fundos.</li>
      <li><b>ANBIMA</b>: mercado secundário de debêntures, taxa indicativa diária (o arquivo gratuito guarda ~15 dias úteis; o painel guarda os dias que baixar).</li>
      <li><b>Banco Central</b>: CDI diário, série SGS 12.</li></ul>`) +
    cardHTML("Como ler os números", `<ul class="sub"><li><b>Look-through</b>: cotas de outros fundos são abertas até o ativo final; % = produto dos pesos ao longo da cadeia.</li>
      <li><b>Confidencial</b>: o gestor pode omitir ativos por até 6 meses; seções de carteira usam o último mês aberto.</li>
      <li><b>Derivativos</b> entram pelo valor informado (em geral nocional) e ficam fora da soma de 100%.</li>
      <li><b>Ajuste carteira x PL</b>: quando a carteira informada não fecha com o PL, a diferença aparece nessa linha.</li>
      <li><b>Marcação (estimada)</b>: variação de preço das posições mantidas; cupons e amortizações aparecem como queda.</li></ul>`);
}

// ------------------------------------------------------------------ adicionar fundos
const dlg = $("#dlg-add");
$("#btn-add").onclick = () => { st.novos = []; desenhaNovos(); $("#log-add").hidden = true; dlg.showModal(); $("#busca").focus(); };
function desenhaNovos() {
  $("#novos").innerHTML = st.novos.map((f, i) => `<li><div>${esc(f.nome)}<small>${esc(f.cnpj)}</small></div><button type="button" data-i="${i}" aria-label="Remover">×</button></li>`).join("");
  $("#novos").querySelectorAll("button").forEach((b) => (b.onclick = () => { st.novos.splice(+b.dataset.i, 1); desenhaNovos(); }));
}
let tBusca, sel = -1;
$("#busca").addEventListener("input", (e) => {
  clearTimeout(tBusca); const q = e.target.value;
  tBusca = setTimeout(async () => {
    if (q.length < 2) return ($("#sugestoes").hidden = true);
    const r = await (await fetch("/api/busca?q=" + encodeURIComponent(q))).json(); sel = -1;
    $("#sugestoes").innerHTML = r.map((f) => `<li data-c="${esc(f.cnpj)}" data-n="${esc(f.nome)}">${esc(f.nome)}<small>${esc(f.cnpj)}${f.ativo ? "" : " · cancelado"}</small></li>`).join("") || "<li>Nada encontrado</li>";
    $("#sugestoes").hidden = false;
  }, 250);
});
$("#busca").addEventListener("keydown", (e) => {
  const li = [...$("#sugestoes").querySelectorAll("li[data-c]")];
  if (e.key === "Enter") e.preventDefault();
  if (!li.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + li.length) % li.length; li.forEach((x, i) => x.classList.toggle("ativo", i === sel)); e.preventDefault(); }
  else if (e.key === "Enter" && sel >= 0) escolhe(li[sel]);
});
$("#sugestoes").addEventListener("click", (e) => { const li = e.target.closest("li[data-c]"); if (li) escolhe(li); });
function escolhe(li) {
  if (!st.novos.some((f) => f.cnpj === li.dataset.c)) st.novos.push({ cnpj: li.dataset.c, nome: li.dataset.n });
  $("#busca").value = ""; $("#sugestoes").hidden = true; desenhaNovos();
}
$("#btn-processar").onclick = async (e) => {
  e.preventDefault();
  if (!st.novos.length) return dlg.close();
  const atuais = st.R.meta.fundos.map((f) => ({ cnpj: f.cnpj, nome: f.nome, curto: f.nome }));
  const todos = atuais.concat(st.novos.filter((n) => !atuais.some((a) => a.cnpj === n.cnpj))).slice(0, 8);
  const log = $("#log-add"); log.hidden = false; log.textContent = "Processando...";
  try {
    const r = await (await fetch("/api/carregar", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fundos: todos, desde: st.R.meta.desde }) })).json();
    if (r.job) for (;;) { await espera(2000); const s = await (await fetch("/api/status/" + r.job)).json();
      log.textContent = s.log.join("\n") || "Baixando arquivos da CVM..."; if (s.status === "erro") throw new Error(s.erro); if (s.status === "ok") break; }
    await abre(r.chave); dlg.close();
  } catch (err) { log.textContent += "\nErro: " + err.message; }
};
