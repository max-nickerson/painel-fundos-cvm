// Painel de fundos - 3 abas: Carteira, Retorno, Consolidado. Dados processados pelo servidor (/api).
const $ = (s, el = document) => el.querySelector(s);
const nf = (d) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (v, d = 2) => (v == null || !isFinite(v) ? "–" : nf(d).format(v));
const pct = (v, d = 2) => (v == null || !isFinite(v) ? "–" : nf(d).format(v) + "%");
const pp = (v, d = 2) => (v == null || !isFinite(v) ? "–" : (v > 0 ? "+" : "") + nf(d).format(v) + " pp");
const cls = (v) => (v == null ? "" : v >= 0 ? "pos" : "neg");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const mesBR = (m) => (m ? MESES[+m.slice(5, 7) - 1] + "/" + m.slice(0, 4) : "–");
const dataBR = (d) => (d ? d.slice(8, 10) + "/" + d.slice(5, 7) + "/" + d.slice(0, 4) : "–");
const semAcento = (t) => String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
const espera = (ms) => new Promise((ok) => setTimeout(ok, ms));
const st = { V: null, F: {}, aba: "carteira", fundo: null, mesCart: {}, ret: { de: null, ate: null }, cons: { sel: null, de: null, ate: null, ord: "ret", asc: false },
  A: {}, cf: { fora: new Set(["Caixa", "Confidencial"]), n: 15, q: "" }, rf: { fora: new Set(["Caixa", "Confidencial"]), n: 15, q: "" } };

// ------------------------------------------------------------------ tema e abas
try { const t = localStorage.getItem("tema"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
$("#tema").onclick = () => {
  const escuro = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = escuro ? "light" : "dark";
  try { localStorage.setItem("tema", document.documentElement.dataset.theme); } catch (e) {}
  if (st.V) desenha();
};
document.querySelectorAll(".abas button").forEach((b) => (b.onclick = () => {
  st.aba = b.dataset.aba;
  document.querySelectorAll(".abas button").forEach((x) => x.setAttribute("aria-selected", x === b));
  desenha();
}));

// ------------------------------------------------------------------ carga
(async function inicia() {
  for (;;) {
    let s;
    try { s = await (await fetch("/api/inicial")).json(); } catch (e) { await espera(2000); continue; }
    $("#log-carga").textContent = (s.log || []).join("\n") || "Iniciando...";
    if (s.status === "erro") return ($("#log-carga").textContent += "\n\nErro: " + s.erro);
    if (s.status === "ok") break;
    await espera(2000);
  }
  st.V = await (await fetch("/api/visao")).json();
  const V = st.V;
  st.fundo = (V.fundos.find((f) => f.nosso && f.tem_carteira) || V.fundos.find((f) => f.tem_carteira) || V.fundos[0]).id;
  st.cons.sel = new Set(V.fundos.map((f) => f.id));
  $("#datas").textContent = `${V.fundos.length} fundos (${V.fundos.filter((f) => f.nosso).length} nossos) · carteiras até ${mesBR(V.ult_carteira)} · cotas até ${dataBR(V.datas[V.datas.length - 1])} · ANBIMA ${dataBR(V.anbima)}`;
  $("#carregando").hidden = true;
  desenha();
})();
async function detalhe(id) {
  if (!st.F[id]) st.F[id] = await (await fetch("/api/fundo/" + id)).json();
  return st.F[id];
}
const fundoPor = (id) => st.V.fundos.find((f) => f.id === id);

// ------------------------------------------------------------------ busca de fundo (digitando)
function campoBusca(onPick, placeholder = "Digite o nome ou CNPJ do fundo...", soComCarteira = false) {
  const wrap = document.createElement("div");
  wrap.className = "busca";
  wrap.innerHTML = `<input type="search" placeholder="${placeholder}" autocomplete="off"><ul class="sugestoes" hidden></ul>`;
  const inp = $("input", wrap), ul = $("ul", wrap);
  let sel = 0, lista = [];
  const filtra = () => {
    const q = semAcento(inp.value.trim()), dig = inp.value.replace(/\D/g, "");
    lista = st.V.fundos.filter((f) => (!soComCarteira || f.tem_carteira) && (!q || semAcento(f.nome).includes(q) || (dig.length > 2 && f.id.includes(dig))))
      .sort((a, b) => b.nosso - a.nosso || a.nome.localeCompare(b.nome)).slice(0, 30);
    sel = 0;
    ul.innerHTML = lista.map((f, i) => `<li data-i="${i}" class="${i === 0 ? "ativo" : ""}"><span>${f.nosso ? '<span class="ponto" style="background:var(--nosso)"></span>' : ""}${esc(f.nome)}</span><small>${esc(f.cnpj)}</small></li>`).join("") || "<li>Nada encontrado</li>";
    ul.hidden = false;
  };
  const escolhe = (i) => { if (lista[i]) { ul.hidden = true; inp.value = ""; onPick(lista[i]); } };
  inp.addEventListener("input", filtra);
  inp.addEventListener("focus", filtra);
  inp.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + lista.length) % Math.max(lista.length, 1);
      ul.querySelectorAll("li").forEach((x, i) => x.classList.toggle("ativo", i === sel)); e.preventDefault();
    } else if (e.key === "Enter") { e.preventDefault(); escolhe(sel); } else if (e.key === "Escape") ul.hidden = true;
  });
  ul.addEventListener("mousedown", (e) => { const li = e.target.closest("li[data-i]"); if (li) escolhe(+li.dataset.i); });
  inp.addEventListener("blur", () => setTimeout(() => (ul.hidden = true), 150));
  return wrap;
}

// ------------------------------------------------------------------ graficos e tabelas
function layout(extra = {}) {
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { family: css("--font"), size: 12, color: css("--text-2") },
    margin: { l: 50, r: 14, t: 10, b: 40 }, hovermode: "x unified", legend: { orientation: "h", y: -0.18, font: { color: css("--text-2") } },
    xaxis: { gridcolor: "rgba(0,0,0,0)", linecolor: css("--line-2"), automargin: true },
    yaxis: { gridcolor: css("--line"), zerolinecolor: css("--line-2"), automargin: true },
    hoverlabel: { bgcolor: css("--surface"), bordercolor: css("--line-2"), font: { color: css("--text-1") } },
  }, extra);
}
function plota(el, dados, lay, h = 340) {
  el.style.height = h + "px";
  Plotly.newPlot(el, dados, lay, { displaylogo: false, responsive: true, displayModeBar: innerWidth > 700 ? "hover" : false,
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] });
}
const cartao = (titulo, sub, corpo) => `<div class="cartao"><h3>${titulo}</h3>${sub ? `<p class="sub">${sub}</p>` : ""}${corpo}</div>`;
function tabela(cols, linhas, extra = {}) {
  const th = cols.map((c) => `<th class="${c.n ? "n" : ""} ${c.ord ? "ord" : ""}" ${c.ord ? `data-ord="${c.ord}"` : ""}>${c.t}</th>`).join("");
  const tr = linhas.map((r) => `<tr class="${r._cls || ""}">${cols.map((c) => `<td class="${c.n ? "n" : c.w ? "texto" : ""}">${c.f ? c.f(r[c.k], r) : esc(r[c.k] ?? "–")}</td>`).join("")}</tr>`).join("");
  return `<div class="tabela-wrap" style="max-height:${extra.alt || 620}px"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}
const kpi = (r, v, s = "", c = "") => `<div class="kpi"><div class="r">${r}</div><div class="v ${c}">${v}</div><div class="s">${s}</div></div>`;
function categoriasPrincipais(series, n = 7) {
  return Object.entries(series).map(([c, ys]) => [c, ys.reduce((s, y) => s + (y || 0), 0)]).sort((a, b) => b[1] - a[1]).slice(0, n).map((x) => x[0]);
}

function desenha() {
  const el = $("#conteudo");
  try {
    if (st.aba === "carteira") carteira(el);
    else if (st.aba === "retorno") retorno(el);
    else consolidado(el);
  } catch (e) { el.innerHTML = `<div class="vazio">Erro ao desenhar: ${esc(e.message)}</div>`; console.error(e); }
}
function cabecalhoFundo(el, f, extra = "") {
  el.innerHTML = `<div class="cab"><div class="titulo-fundo"><h2>${esc(f.nome)} ${f.nosso ? '<span class="tag">NOSSO</span>' : ""}</h2>
    <p class="sub">${esc(f.cnpj)}${f.pl ? ` · PL R$ ${num(f.pl, 0)} mm` : ""}</p></div><div class="controles" id="ctl">${extra}</div></div><div id="corpo"></div>`;
  $("#ctl").prepend(campoBusca((x) => { st.fundo = x.id; desenha(); }, "Trocar de fundo: digite nome ou CNPJ...", st.aba === "carteira"));
}

// ------------------------------------------------------------------ filtros de ativos (categorias liga/desliga, quantos, busca)
function filtros(box, todas, f, redesenha, placeholder) {
  box.innerHTML = `<div class="filtros"><div class="chips">${todas.map((c) => `<button class="chip-t" data-c="${esc(c)}" aria-pressed="${!f.fora.has(c)}">${esc(c)}</button>`).join("")}
      <button class="chip-t mudo" data-t="1">Todas</button><button class="chip-t mudo" data-t="0">Nenhuma</button></div>
    <div class="controles"><div class="busca"><input type="search" class="q" placeholder="${placeholder}" value="${esc(f.q)}"></div>
      <label>Mostrar <select class="n">${[5, 10, 15, 20, 30, 0].map((n) => `<option value="${n}" ${n === f.n ? "selected" : ""}>${n || "Todos"}</option>`).join("")}</select></label></div></div>`;
  const marca = () => box.querySelectorAll("[data-c]").forEach((x) => x.setAttribute("aria-pressed", !f.fora.has(x.dataset.c)));
  box.querySelectorAll("[data-c]").forEach((b) => (b.onclick = () => { const c = b.dataset.c; f.fora.has(c) ? f.fora.delete(c) : f.fora.add(c); marca(); redesenha(); }));
  box.querySelectorAll("[data-t]").forEach((b) => (b.onclick = () => { f.fora = new Set(b.dataset.t === "1" ? [] : todas); marca(); redesenha(); }));
  $(".q", box).oninput = (e) => { f.q = e.target.value; redesenha(); };
  $(".n", box).onchange = (e) => { f.n = +e.target.value; redesenha(); };
}
const passa = (f, x) => !f.fora.has(x.categoria) && (!f.q.trim() || semAcento([x.ativo, x.grupo, x.emissor, x.codigo].join(" ")).includes(semAcento(f.q.trim())));
const corta = (arr, n) => (n ? arr.slice(0, n) : arr);
const fonteCurta = (v) => `<span class="muted">${esc(v || "–")}</span>`;

// ------------------------------------------------------------------ CARTEIRA
async function carteira(el) {
  const f = fundoPor(st.fundo);
  if (!f.tem_carteira) { cabecalhoFundo(el, f); $("#corpo").innerHTML = `<div class="vazio">A CVM não tem carteira deste fundo no período.</div>`; return; }
  cabecalhoFundo(el, f);
  $("#corpo").innerHTML = `<div class="vazio">Carregando ${esc(f.nome)}...</div>`;
  const D = await detalhe(f.id);
  if (st.fundo !== f.id || st.aba !== "carteira") return;
  const ms = D.carteira.map((x) => x.mes);
  const aberto = [...D.carteira].reverse().find((x) => x.conf < 5) || D.carteira[D.carteira.length - 1];
  const mes = ms.includes(st.mesCart[f.id]) ? st.mesCart[f.id] : aberto.mes;
  const C = D.carteira.find((x) => x.mes === mes);
  $("#ctl").insertAdjacentHTML("beforeend", `<label>Carteira <select id="mes">${ms.slice().reverse().map((m) => `<option value="${m}" ${m === mes ? "selected" : ""}>${mesBR(m)}${D.carteira.find((x) => x.mes === m).conf >= 5 ? " (confid.)" : ""}</option>`).join("")}</select></label>
    <a class="botao" href="/api/csv/${f.id}" title="Carteira look-through completa (CSV)">CSV</a>`);
  $("#mes").onchange = (e) => { st.mesCart[f.id] = e.target.value; desenha(); };

  const linhas = C.cats.map((c) => ({ ...c })).concat([{ ...C.total, _cls: "total", categoria: "Total ponderado" }]);
  const tab = tabela([
    { t: "Categoria", k: "categoria", w: 1 },
    { t: "% PL", k: "perc", n: 1, f: (v) => pct(v) },
    { t: "Financeiro (R$ mm)", k: "fin", n: 1, f: (v) => num(v) },
    { t: "Spread CDI+ (% a.a.)", k: "spread", n: 1, f: (v) => num(v) },
    { t: "Duration (anos)", k: "duration", n: 1, f: (v) => num(v) },
  ], linhas);
  const conf = C.conf >= 0.5 ? ` · ${pct(C.conf, 1)} do PL ainda confidencial` : "";
  const fontes = Object.entries(C.fontes || {}).filter(([, v]) => v >= 0.1).map(([k, v]) => `${esc(k)} ${pct(v, 1)}`).join(" · ");
  $("#corpo").innerHTML = cartao(`Carteira de ${mesBR(mes)} por categoria`, `PL R$ ${num(C.pl_mm, 2)} mm · look-through (cotas de fundos abertas até o ativo)${conf}`, tab +
    `<p class="nota">Spread CDI+ = equivalente em CDI (IPCA+ e prefixados contra a curva do Tesouro de mesma duration). Cobertura de 100% dos ativos de crédito; ações, FII, FIP, ETF e FIAGRO não têm spread. Fonte, em % do PL: ${fontes}.</p>`) +
    `<div class="grade g2">${cartao("% do PL por categoria", "Evolução mensal", '<div id="g_aloc"></div>')}${cartao("Spread CDI+ por categoria", "Média ponderada no mês, % a.a.", '<div id="g_spread"></div>')}</div>
    <div class="cartao"><h3>Ativos de ${mesBR(mes)}</h3><p class="sub">Maiores posições por % do PL · filtre por categoria ou busque por ativo, emissor, grupo econômico ou código</p>
      <div id="f_at"></div><div class="grade g-tabela" style="margin:12px 0 0"><div id="t_top"></div><div><h3>Maiores grupos econômicos</h3><p class="sub">% do PL nas categorias escolhidas</p><div id="g_grupos"></div></div></div></div>`;

  const eixoX = { ...layout().xaxis, tickformat: "%m/%y", dtick: ms.length <= 12 ? "M1" : ms.length <= 36 ? "M3" : "M12" };
  const series = {};
  D.carteira.forEach((x, i) => x.cats.forEach((c) => { (series[c.categoria] ||= Array(D.carteira.length).fill(0))[i] = c.perc; }));
  const tops = categoriasPrincipais(series), cores = st.V.cat_cores;
  const agrup = tops.map((c, i) => ({ c, y: series[c], cor: cores[i % cores.length] }));
  agrup.push({ c: "Outros", y: ms.map((_, i) => Object.entries(series).filter(([c]) => !tops.includes(c)).reduce((s, [, y]) => s + (y[i] || 0), 0)), cor: "#9aa0a6" });
  plota($("#g_aloc"), agrup.map((a) => ({ x: ms.map((m) => m + "-15"), y: a.y, name: a.c, stackgroup: "a", line: { width: 0.5, color: css("--surface") },
    fillcolor: a.cor, hovertemplate: "%{y:.1f}%" })), layout({ xaxis: eixoX, yaxis: { ticksuffix: "%", gridcolor: css("--line") } }), 360);
  const sp = {};
  D.carteira.forEach((x, i) => x.cats.forEach((c) => { if (c.spread != null && c.perc > 0.05) (sp[c.categoria] ||= Array(D.carteira.length).fill(null))[i] = c.spread; }));
  const comSpread = tops.filter((c) => sp[c] && c !== "Caixa" && c !== "Títulos Públicos");
  plota($("#g_spread"), comSpread.map((c) => ({ x: ms.map((m) => m + "-15"), y: sp[c], name: c, mode: "lines", connectgaps: false,
    line: { color: cores[tops.indexOf(c) % cores.length], width: 2 }, hovertemplate: "%{y:.2f}%" })),
    layout({ xaxis: eixoX, yaxis: { ticksuffix: "%", gridcolor: css("--line") } }), 360);

  $("#t_top").innerHTML = `<div class="vazio">Carregando ativos...</div>`;
  const k = f.id + mes;
  if (!st.A[k]) st.A[k] = await (await fetch(`/api/ativos/${f.id}?mes=${mes}`)).json();
  if (st.fundo !== f.id || st.aba !== "carteira" || !$("#t_top")) return;
  const A = st.A[k].map((x) => ({ ...x, ativo: x.rotulo }));
  const peso = {};
  A.forEach((x) => (peso[x.categoria] = (peso[x.categoria] || 0) + x.perc));
  const todas = Object.keys(peso).sort((a, b) => peso[b] - peso[a]);
  const cols = [{ t: "Ativo", k: "ativo", w: 1 }, { t: "Categoria", k: "categoria" }, { t: "Grupo econômico", k: "grupo", w: 1 },
    { t: "% PL", k: "perc", n: 1, f: (v) => pct(v) }, { t: "Spread CDI+", k: "spread", n: 1, f: (v) => num(v) },
    { t: "Duration", k: "duration", n: 1, f: (v) => num(v) }, { t: "PU (R$)", k: "pu", n: 1, f: (v) => num(v) }, { t: "Fonte", k: "fonte", f: fonteCurta }];
  const redesenha = () => {
    const F = st.cf, lista = A.filter((x) => passa(F, x)).sort((a, b) => b.perc - a.perc);
    const soma = lista.reduce((s, x) => s + x.perc, 0);
    $("#t_top").innerHTML = tabela(cols, corta(lista, F.n), { alt: 640 }) +
      `<p class="nota">${lista.length} ativo(s) · ${pct(soma)} do PL nas categorias escolhidas${F.n && lista.length > F.n ? ` · mostrando ${F.n}` : ""}</p>`;
    const gp = {};
    lista.forEach((x) => (gp[x.grupo] = (gp[x.grupo] || 0) + x.perc));
    const g = corta(Object.entries(gp).sort((a, b) => b[1] - a[1]), F.n || 40).reverse();
    plota($("#g_grupos"), [{ type: "bar", orientation: "h", x: g.map((x) => x[1]), y: g.map((x) => x[0]), marker: { color: cores[0] }, hovertemplate: "%{y}: %{x:.2f}% do PL<extra></extra>" }],
      layout({ hovermode: "closest", margin: { l: 8, r: 14, t: 6, b: 30 }, yaxis: { automargin: true, gridcolor: "rgba(0,0,0,0)" }, xaxis: { ticksuffix: "%", gridcolor: css("--line") } }), Math.max(220, 24 * g.length + 50));
  };
  filtros($("#f_at"), todas, st.cf, redesenha, "Buscar ativo, emissor, grupo ou código...");
  redesenha();
}

// ------------------------------------------------------------------ RETORNO
function periodoMeses(ms, chave) {
  if (!ms.includes(st[chave].de)) st[chave].de = ms[Math.max(0, ms.length - 12)];
  if (!ms.includes(st[chave].ate)) st[chave].ate = ms[ms.length - 1];
  const opt = (v) => ms.slice().reverse().map((m) => `<option value="${m}" ${m === v ? "selected" : ""}>${mesBR(m)}</option>`).join("");
  return `<label>De <select id="de">${opt(st[chave].de)}</select></label><label>até <select id="ate">${opt(st[chave].ate)}</select></label>
    ${[["6m", 6], ["12m", 12], ["24m", 24], ["No ano", "ano"], ["Tudo", 999]].map(([t, n]) => `<button class="botao" data-p="${n}">${t}</button>`).join("")}`;
}
function ligaPeriodo(ms, chave) {
  $("#de").onchange = (e) => { st[chave].de = e.target.value; desenha(); };
  $("#ate").onchange = (e) => { st[chave].ate = e.target.value; desenha(); };
  document.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => {
    const ult = ms[ms.length - 1], n = b.dataset.p;
    st[chave].ate = ult;
    st[chave].de = n === "ano" ? (ms.find((m) => m.startsWith(ult.slice(0, 4))) || ms[0]) : ms[Math.max(0, ms.length - +n)];
    desenha();
  }));
}
function estatPeriodo(f, i0, i1) {
  // retorno, vol anual e drawdown da cota entre os indices i0..i1 de V.datas (precisa existir no inicio e no fim)
  const c = f.cota; if (!c || !c.length) return null;
  let a = i0; while (a <= i1 && c[a] == null) a++;
  if (a > i0 + 6 || a > i1) return null;
  let b = i1; while (b > a && c[b] == null) b--;
  if (b < i1 - 6) return null;
  const rets = []; let pico = c[a], dd = 0, ant = c[a];
  for (let k = a + 1; k <= b; k++) { if (c[k] == null) continue; rets.push(Math.log(c[k] / ant)); ant = c[k]; pico = Math.max(pico, c[k]); dd = Math.min(dd, c[k] / pico - 1); }
  const m = rets.reduce((s, x) => s + x, 0) / Math.max(rets.length, 1);
  const vol = Math.sqrt(rets.reduce((s, x) => s + (x - m) ** 2, 0) / Math.max(rets.length - 1, 1) * 252);
  const cdi = st.V.cdi[b] / st.V.cdi[a] - 1, ret = c[b] / c[a] - 1;
  return { ret: ret * 100, cdi: cdi * 100, pcdi: cdi ? (ret / cdi) * 100 : null, vol: vol * 100, dd: dd * 100 };
}
function indicesDatas(de, ate) {
  const D = st.V.datas;
  let i0 = D.findIndex((d) => d >= de); if (i0 < 0) i0 = D.length - 1;
  let i1 = D.length - 1; while (i1 > 0 && D[i1] > ate) i1--;
  return [Math.max(0, i0 - 1), i1];   // inclui a cota do dia anterior ao inicio (retorno do 1o dia)
}
async function retorno(el) {
  const f = fundoPor(st.fundo);
  cabecalhoFundo(el, f);
  if (!f.tem_carteira) { $("#corpo").innerHTML = `<div class="vazio">A CVM não tem carteira deste fundo no período.</div>`; return; }
  $("#corpo").innerHTML = `<div class="vazio">Carregando ${esc(f.nome)}...</div>`;
  const D = await detalhe(f.id);
  if (st.fundo !== f.id || st.aba !== "retorno") return;
  const R = D.retorno, ms = R.meses.map((x) => x.mes);
  if (!ms.length) { $("#corpo").innerHTML = `<div class="vazio">Sem meses suficientes para calcular retorno.</div>`; return; }
  $("#ctl").insertAdjacentHTML("beforeend", periodoMeses(ms, "ret"));
  ligaPeriodo(ms, "ret");
  const j0 = ms.indexOf(st.ret.de), j1 = ms.indexOf(st.ret.ate);
  const [a, b] = j0 <= j1 ? [j0, j1] : [j1, j0];
  const J = Array.from({ length: b - a + 1 }, (_, k) => a + k);
  const tot = J.reduce((p, j) => p * (1 + R.meses[j].real / 100), 1) - 1, cdi = J.reduce((p, j) => p * (1 + R.meses[j].cdi / 100), 1) - 1;
  const linhas = Object.entries(R.categorias).map(([c, v]) => {
    let contrib = 0, ret = 1, nP = 0, sP = 0, nR = 0;
    J.forEach((j) => { const cc = v.contrib[j] || 0, p = v.peso[j] || 0; contrib += cc; if (p > 0.05) { ret *= 1 + cc / p; nR++; } sP += p; nP++; });
    return { categoria: c, peso: sP / Math.max(nP, 1), contrib, ret: nR ? (ret - 1) * 100 : null, pcdi: nR && cdi ? ((ret - 1) / cdi) * 100 : null };
  }).filter((r) => Math.abs(r.peso) > 0.05 || Math.abs(r.contrib) > 0.005).sort((x, y) => y.contrib - x.contrib);
  linhas.push({ _cls: "total", categoria: "Fundo (retorno da cota)", peso: 100, contrib: tot * 100, ret: tot * 100, pcdi: cdi ? (tot / cdi) * 100 : null });
  const soma = {}, pesoAt = {};
  R.contrib.forEach(([ia, jm, v, w]) => { if (jm >= a && jm <= b) { soma[ia] = (soma[ia] || 0) + v; pesoAt[ia] = (pesoAt[ia] || 0) + (w || 0); } });
  const ativos = Object.keys(soma).map((ia) => ({ ...R.ativos[ia], contrib: soma[ia], perc: pesoAt[ia] / J.length }));
  const hedge = J.reduce((s, j) => s + (R.meses[j].hedge || 0), 0);
  const per = `${mesBR(ms[a])} a ${mesBR(ms[b])}`;

  $("#corpo").innerHTML = `<div class="kpis">${kpi("Retorno do fundo", pct(tot * 100), per, cls(tot))}${kpi("CDI", pct(cdi * 100), "mesmo período")}
      ${kpi("% do CDI", pct(cdi ? (tot / cdi) * 100 : null, 1), "")}${kpi("Excesso sobre o CDI", pp((tot - cdi) * 100), "", cls(tot - cdi))}${kpi("Derivativos", pp(hedge), "já alocado nos ativos protegidos", cls(hedge))}</div>` +
    cartao("Retorno por categoria", "Contribuição em pontos percentuais do PL; retorno e % do CDI da própria categoria no período", tabela([
      { t: "Categoria", k: "categoria", w: 1 }, { t: "Peso médio", k: "peso", n: 1, f: (v) => pct(v, 1) }, { t: "Contribuição", k: "contrib", n: 1, f: (v) => `<span class="${cls(v)}">${pp(v)}</span>` },
      { t: "Retorno", k: "ret", n: 1, f: (v) => pct(v) }, { t: "% do CDI", k: "pcdi", n: 1, f: (v) => pct(v, 0) }], linhas) +
      `<p class="nota">Estimado com as carteiras mensais da CVM: cada ativo rende CDI + seu spread, ou a variação real de preço quando ela é crível; caixa rende CDI; derivativos (DAP → ativos IPCA+, DI1 → prefixados, dólar → ativos no exterior) entram nos ativos que protegem; a diferença para o retorno real da cota (taxas, negociação, marcação) é distribuída pelo peso. A soma das categorias fecha com o retorno real da cota.</p>`) +
    `<div class="cartao"><h3>Ativos por contribuição</h3><p class="sub">${per} · % PL = peso médio no período · filtre por categoria ou busque por ativo, emissor, grupo ou código</p>
      <div id="f_ret"></div><div class="grade g2" style="margin:12px 0 0"><div><h3>Melhores</h3><div id="t_mel"></div></div><div><h3>Piores</h3><div id="t_pio"></div></div></div></div>`;
  const peso = {};
  ativos.forEach((x) => (peso[x.categoria] = (peso[x.categoria] || 0) + Math.abs(x.perc)));
  const todas = Object.keys(peso).sort((x, y) => peso[y] - peso[x]);
  const cols = [{ t: "Ativo", k: "ativo", w: 1 }, { t: "Categoria", k: "categoria" }, { t: "Grupo econômico", k: "grupo", w: 1 },
    { t: "% PL", k: "perc", n: 1, f: (v) => pct(v) }, { t: "Contribuição", k: "contrib", n: 1, f: (v) => `<span class="${cls(v)}">${pp(v, 3)}</span>` }];
  const redesenha = () => {
    const F = st.rf, lista = ativos.filter((x) => passa(F, x));
    $("#t_mel").innerHTML = tabela(cols, corta(lista.slice().sort((x, y) => y.contrib - x.contrib), F.n), { alt: 560 });
    $("#t_pio").innerHTML = tabela(cols, corta(lista.slice().sort((x, y) => x.contrib - y.contrib), F.n), { alt: 560 });
  };
  filtros($("#f_ret"), todas, st.rf, redesenha, "Buscar ativo, emissor, grupo ou código...");
  redesenha();
}
function riscoRetorno(el, linhas) {
  const grupo = (arr, nome, cor) => ({ type: "scatter", mode: "markers+text", name: nome, x: arr.map((r) => r.vol), y: arr.map((r) => r.pcdi),
    text: arr.map((r) => (r.f.nosso || arr.length <= 12 ? r.f.nome : "")), textposition: "top center", textfont: { size: 11, color: css("--text-2") },
    customdata: arr.map((r) => [r.f.nome, r.ret]), marker: { size: 10, color: cor, opacity: 0.9, line: { width: 1, color: css("--surface") } },
    hovertemplate: "%{customdata[0]}<br>retorno %{customdata[1]:.2f}% · %{y:.1f}% do CDI · vol %{x:.2f}%<extra></extra>" });
  plota(el, [grupo(linhas.filter((r) => !r.f.nosso), "Peers", "#9aa0a6"), grupo(linhas.filter((r) => r.f.nosso), "Nossos", "#eb6834")],
    layout({ hovermode: "closest", legend: { orientation: "h", y: -0.2 }, xaxis: { title: "volatilidade anual (%)", gridcolor: css("--line"), zeroline: false },
      yaxis: { title: "% do CDI", gridcolor: css("--line"), zeroline: false } }), 440);
}

// ------------------------------------------------------------------ CONSOLIDADO
function consolidado(el) {
  const V = st.V, C = st.cons, ult = V.datas[V.datas.length - 1];
  if (!C.ate) C.ate = ult;
  if (!C.de) { const d = new Date(ult + "T12:00"); d.setFullYear(d.getFullYear() - 1); C.de = d.toISOString().slice(0, 10); }
  el.innerHTML = `<div class="cab"><div class="titulo-fundo"><h2>Consolidado</h2><p class="sub">Retorno de cada fundo no período · só fundos ativos do início ao fim do período</p></div>
    <div class="controles"><label>De <input type="date" id="cde" value="${C.de}" min="${V.datas[0]}" max="${ult}"></label><label>até <input type="date" id="cate" value="${C.ate}" min="${V.datas[0]}" max="${ult}"></label>
    ${[["12m", 12], ["24m", 24], ["No ano", "ano"], ["Tudo", "tudo"]].map(([t, n]) => `<button class="botao" data-q="${n}">${t}</button>`).join("")}</div></div>
    <div class="cartao"><div class="controles" style="margin-bottom:8px"><span class="sub" style="margin:0">Fundos:</span>
      <button class="botao" data-s="todos">Todos</button><button class="botao" data-s="nossos">Nossos</button><button class="botao" data-s="peers">Peers</button><button class="botao" data-s="nenhum">Limpar</button></div>
      <div class="multi" id="multi"></div></div>
    <div id="cc"></div>`;
  $("#cde").onchange = (e) => { C.de = e.target.value; desenha(); };
  $("#cate").onchange = (e) => { C.ate = e.target.value; desenha(); };
  document.querySelectorAll("[data-q]").forEach((b) => (b.onclick = () => {
    const d = new Date(ult + "T12:00"), q = b.dataset.q;
    C.ate = ult;
    C.de = q === "tudo" ? V.datas[0] : q === "ano" ? ult.slice(0, 4) + "-01-01" : (d.setMonth(d.getMonth() - +q), d.toISOString().slice(0, 10));
    desenha();
  }));
  document.querySelectorAll("[data-s]").forEach((b) => (b.onclick = () => {
    const s = b.dataset.s;
    C.sel = new Set(V.fundos.filter((f) => s === "todos" || (s === "nossos" && f.nosso) || (s === "peers" && !f.nosso)).map((f) => f.id));
    desenha();
  }));
  const multi = $("#multi");
  const chips = V.fundos.filter((f) => C.sel.has(f.id));
  multi.innerHTML = (chips.length > 24 ? `<span class="chip">${chips.filter((f) => f.nosso).length} nossos + ${chips.filter((f) => !f.nosso).length} peers selecionados</span>`
    : chips.map((f) => `<span class="chip ${f.nosso ? "nosso" : ""}">${esc(f.nome)}<button data-x="${f.id}" aria-label="Remover">×</button></span>`).join(""));
  multi.querySelectorAll("[data-x]").forEach((b) => (b.onclick = () => { C.sel.delete(b.dataset.x); desenha(); }));
  multi.appendChild(campoBusca((x) => { C.sel.add(x.id); desenha(); }, "Adicionar fundo: digite..."));

  const [i0, i1] = indicesDatas(C.de, C.ate);
  const linhas = [], fora = [];
  V.fundos.filter((f) => C.sel.has(f.id)).forEach((f) => { const e = estatPeriodo(f, i0, i1); (e ? linhas : fora).push({ f, ...(e || {}) }); });
  const cdiP = (V.cdi[i1] / V.cdi[i0] - 1) * 100;
  const ord = C.ord, sgn = C.asc ? 1 : -1;
  linhas.sort((x, y) => sgn * ((x[ord] ?? -1e9) - (y[ord] ?? -1e9)));
  $("#cc").innerHTML = cartao("Retorno acumulado", `${dataBR(V.datas[i0 + 1] || V.datas[i0])} a ${dataBR(V.datas[i1])} · CDI ${pct(cdiP)} · laranja = nossos · cinza = peers`, '<div id="g_cons"></div>') +
    cartao("Risco x retorno", "Mesmo período e mesmos fundos · laranja = nossos · cinza = peers", '<div id="g_rr"></div>') +
    cartao("Ranking no período", fora.length ? `${fora.length} fundo(s) selecionado(s) fora por não existirem no período inteiro: ${fora.map((x) => esc(x.f.nome)).join(", ")}` : "Clique no título da coluna para ordenar",
      tabela([{ t: "#", k: "_i" }, { t: "Fundo", k: "nome", w: 1, f: (v, r) => `${r.f.nosso ? '<span class="ponto" style="background:var(--nosso)"></span>' : '<span class="ponto" style="background:#9aa0a6"></span>'}${esc(r.f.nome)}${r.f.distribui ? ' <span class="muted" title="Distribui rendimentos: retorno total, somando as distribuições">· distribui</span>' : ""}` },
        { t: "Retorno", k: "ret", n: 1, ord: "ret", f: (v) => `<span class="${cls(v)}">${pct(v)}</span>` }, { t: "% do CDI", k: "pcdi", n: 1, ord: "pcdi", f: (v) => pct(v, 1) },
        { t: "Vol. anual", k: "vol", n: 1, ord: "vol", f: (v) => pct(v) }, { t: "Pior drawdown", k: "dd", n: 1, ord: "dd", f: (v) => pct(v) },
        { t: "PL (R$ mm)", k: "pl", n: 1, ord: "pl", f: (v) => num(v, 0) }],
        linhas.map((r, i) => ({ ...r, _i: i + 1, nome: r.f.nome, pl: r.f.pl, _cls: r.f.nosso ? "nosso" : "" }))));
  document.querySelectorAll("th[data-ord]").forEach((th) => (th.onclick = () => { if (C.ord === th.dataset.ord) C.asc = !C.asc; else { C.ord = th.dataset.ord; C.asc = false; } desenha(); }));
  const xs = V.datas.slice(i0, i1 + 1);
  const serie = (f) => { const c = f.cota.slice(i0, i1 + 1); let b = c.find((v) => v != null); return c.map((v) => (v == null ? null : (v / b - 1) * 100)); };
  const dados = linhas.filter((r) => !r.f.nosso).map((r) => ({ x: xs, y: serie(r.f), name: r.f.nome, mode: "lines", line: { color: "#9aa0a6", width: 1.2 }, opacity: 0.55, showlegend: false,
    hovertemplate: `${esc(r.f.nome)}: %{y:.2f}%<extra></extra>` }));
  linhas.filter((r) => r.f.nosso).forEach((r) => dados.push({ x: xs, y: serie(r.f), name: r.f.nome, mode: "lines", line: { color: r.f.cor, width: 2.8 }, hovertemplate: `${esc(r.f.nome)}: %{y:.2f}%<extra></extra>` }));
  const c0 = V.cdi[i0];
  dados.push({ x: xs, y: V.cdi.slice(i0, i1 + 1).map((v) => (v / c0 - 1) * 100), name: "CDI", mode: "lines", line: { color: css("--text-1"), width: 2, dash: "dash" }, hovertemplate: "CDI: %{y:.2f}%<extra></extra>" });
  plota($("#g_cons"), dados, layout({ hovermode: "closest", yaxis: { ticksuffix: "%", gridcolor: css("--line") } }), 460);
  riscoRetorno($("#g_rr"), linhas);
}
