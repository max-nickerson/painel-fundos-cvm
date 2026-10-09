"""
Robustez dos três finalistas: CDI+1 e CDI+5 = mix fixo com tamanho do crédito pelo spread (a); CDI+10 = moderado alavancado (c).
  1) parâmetros vizinhos  2) custo x2 e x3  3) execução 1 dia mais lenta  4) Monte Carlo (bootstrap estacionário)
  5) seleção aleatória de papéis (é sorte?)  6) ano a ano e por regime  7) sem os melhores dias  8) Sharpe deflacionado
"""
import contextlib
import io
import itertools

import matplotlib
import numpy as np
import pandas as pd
from arch.bootstrap import StationaryBootstrap
from scipy.stats import norm

matplotlib.use("Agg")
import matplotlib.pyplot as plt

with contextlib.redirect_stdout(io.StringIO()):
    import alocador as al
pc, dias, cdi, S, L0 = al.pc, al.dias, al.cdi, al.S, al.L.copy()
INI, val, teste, anual, sh = al.INI, al.val, al.teste, al.anual, al.sh
CRED = al.CRED
FIN = {"CDI+1": (1.0, 0.0), "CDI+5": (1.5, .01), "CDI+10": (2.0, .015)}
META = {"CDI+1": 1, "CDI+5": 5, "CDI+10": 10}


def tamanho_spread(base, lmax, piso=.25, jan=252):
    pct = al.spr.expanding(jan).rank(pct=True).reindex(columns=CRED).fillna(.5)
    w = pd.DataFrame({k: base.get(k, 0) * (piso + (1 - piso) * pct[k]) if k in CRED else base.get(k, 0) for k in L0.columns}, index=dias)
    s = w[CRED].sum(axis=1)
    w[CRED] = w[CRED].mul(np.minimum(1, lmax / s), axis=0)
    return w


def finalista(p, L=None, lag=2, piso=.25, jan=252, banda=.05, escala_eb=1., escala_j=1., escala_cred=1.):
    lmax, fin = FIN[p]
    if L is not None:
        al.L = L
    base = dict(al.alav_c["CDI+10"] if p == "CDI+10" else al.fixo[p])
    base = {k: v * (escala_eb if k == "eurobonds" else escala_j if k == "juros DI 2a" else escala_cred) for k, v in base.items()}
    w = al.const(base) if p == "CDI+10" else tamanho_spread(base, lmax, piso, jan)
    r = al.carteira(w, lmax * 1.2 if p == "CDI+10" else lmax, fin, banda, lag)[0]
    al.L = L0
    return r


base = {p: finalista(p) for p in FIN}
o = dias[dias >= INI]
txt = []
pr = lambda *a: (print(*a, flush=True), txt.append(" ".join(str(x) for x in a)))
stats = lambda r: {"val": anual(r.reindex(val)), "teste": anual(r.reindex(teste)), "total": anual(r.reindex(o)),
                   "Sharpe total": sh(r.reindex(o)), "queda": ((1 + r.reindex(o)).cumprod() / (1 + r.reindex(o)).cumprod().cummax() - 1).min() * 100}
pr("==== finalistas (% a.a. acima do CDI)")
pr(pd.DataFrame({p: stats(r) for p, r in base.items()}).round(2).to_string())

# 1) parâmetros vizinhos
pr("\n==== 1) parâmetros vizinhos: distribuição do resultado (CDI+ % a.a.)")
grade = {"CDI+1": dict(piso=(.1, .25, .5), jan=(126, 252, 504), banda=(.02, .05, .1), escala_eb=(.5, 1, 1.5), escala_j=(.5, 1, 1.5)),
         "CDI+5": dict(piso=(.1, .25, .5), jan=(126, 252, 504), banda=(.02, .05, .1), escala_eb=(.5, 1, 1.5), escala_j=(.5, 1, 1.5)),
         "CDI+10": dict(escala_cred=(.8, .9, 1, 1.1), banda=(.02, .05, .1), escala_eb=(.5, 1, 1.5), escala_j=(.5, 1, 1.5))}
viz = {}
rng = np.random.default_rng(0)
for p, g in grade.items():
    comb = list(itertools.product(*g.values()))
    comb = [comb[i] for i in rng.choice(len(comb), min(40, len(comb)), replace=False)]
    v = pd.DataFrame([stats(finalista(p, **dict(zip(g, c)))) for c in comb])
    viz[p] = v
    pr(f"{p} ({len(v)} combinações): teste mediana CDI{v.teste.median():+.2f}, pior {v.teste.min():+.2f}, melhor {v.teste.max():+.2f}; "
       f"teste > 0 em {(v.teste > 0).mean()*100:.0f}%; total >= meta em {(v.total >= META[p]).mean()*100:.0f}%")

# 2) e 3) custos e atraso: refaz os livros de crédito
pr("\n==== 2) custo x2, x3 e 3) execução um dia mais lenta")


def livros(mult=1., lag=2):
    L = L0.copy()
    for fx, (filtro, n, ck) in pc.FAIXAS.items():
        d = al.df[filtro(al.df) & (al.df.date >= INI)]
        forca = d.assign(f=d.groupby("date")[al.MODELO[fx]].rank(pct=True)).pivot_table(index="date", columns="codigo", values="f")
        L[fx] = al.simula(forca, pc.B["custo"][ck] * mult, n, lag=lag)[0]
    return L


cus = al.CUSTO.copy()
sens = {}
for nome, mult, lag in (("custo x2", 2, 2), ("custo x3", 3, 2), ("execução +1 dia", 1, 3)):
    al.CUSTO = {k: v * mult for k, v in cus.items()}
    L = livros(mult, lag)
    sens[nome] = {p: stats(finalista(p, L=L, lag=lag)) for p in FIN}
    al.CUSTO = cus
    pr(nome, {p: f"teste CDI{s['teste']:+.2f} total CDI{s['total']:+.2f}" for p, s in sens[nome].items()})

# 4) Monte Carlo
pr("\n==== 4) Monte Carlo (bootstrap estacionário, blocos de 21 dias, 5000 caminhos de 3 anos)")
mc = {}
for p, r in base.items():
    x = r.reindex(o).fillna(0).to_numpy()
    sims = np.array([b[0][0][:756] for b in StationaryBootstrap(21, np.tile(x, 2), seed=1).bootstrap(5000)])
    a = ((1 + sims).prod(axis=1) ** (252 / 756) - 1) * 100
    eq = (1 + sims).cumprod(axis=1)
    dd = (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1) * 100
    mc[p] = a
    pr(f"{p}: CDI+ em 3 anos mediana {np.median(a):+.2f} (5% {np.percentile(a, 5):+.2f} a 95% {np.percentile(a, 95):+.2f}); "
       f"P(< CDI) {(a < 0).mean()*100:.1f}%; P(>= meta) {(a >= META[p]).mean()*100:.0f}%; queda pior que -10%: {(dd < -10).mean()*100:.0f}%")

# 5) seleção aleatória: troca o modelo por notas aleatórias (mesmas regras, mesmos custos)
pr("\n==== 5) é sorte? 20 carteiras com papéis escolhidos ao acaso (mesmas regras, custos e alocação)")
aleat = {p: [] for p in FIN}
for s in range(20):
    L = L0.copy()
    for fx, (filtro, n, ck) in pc.FAIXAS.items():
        d = al.df[filtro(al.df) & (al.df.date >= INI)]
        z = d[["date", "codigo"]].assign(f=np.random.default_rng(s).random(len(d)))
        z["f"] = z.groupby("codigo").f.transform(lambda v: v.rolling(21, min_periods=1).mean())   # nota aleatória mas persistente
        forca = z.assign(f=z.groupby("date").f.rank(pct=True)).pivot_table(index="date", columns="codigo", values="f")
        L[fx] = al.simula(forca, pc.B["custo"][ck], n)[0]
    for p in FIN:
        aleat[p].append(anual(finalista(p, L=L).reindex(o)))
for p in FIN:
    a = np.array(aleat[p])
    pr(f"{p}: finalista CDI{anual(base[p].reindex(o)):+.2f} x aleatórias mediana CDI{np.median(a):+.2f} (melhor {a.max():+.2f}) "
       f"-> percentil {(a < anual(base[p].reindex(o))).mean()*100:.0f}")

# 6) ano a ano e por regime
pr("\n==== 6) ano a ano (CDI+ % no ano) e por regime de crédito (% a.a.)")
ano = pd.DataFrame({p: r.reindex(o).groupby(o.year).apply(lambda x: ((1 + x).prod() - 1) * 100) for p, r in base.items()})
pr(ano.round(2).to_string())
rg = al.reg.reindex(o).idxmax(axis=1)
pr(pd.DataFrame({p: r.reindex(o).groupby(rg).mean() * 252 * 100 for p, r in base.items()}).round(2).to_string())

# 7) sem os melhores dias
pr("\n==== 7) tirando os melhores dias")
for p, r in base.items():
    x = r.reindex(o)
    pr(p, {f"sem os {k} melhores": round(anual(x.drop(x.nlargest(k).index)), 2) for k in (1, 5, 20)})

# 8) Sharpe deflacionado (todas as tentativas desta pesquisa: ~61 + 49 + vizinhos)
pr("\n==== 8) Sharpe deflacionado e t-stat no período todo 2021-26")
n_tent = 61 + 49 + 18
for p, r in base.items():
    x = r.reindex(o)
    s, T = x.mean() / x.std(), len(x)
    sr0 = .5 / np.sqrt(252) * ((1 - .5772) * norm.ppf(1 - 1 / n_tent) + .5772 * norm.ppf(1 - 1 / (n_tent * np.e)))   # dispersão de Sharpe 0,5 entre tentativas
    dsr = norm.cdf((s - sr0) * np.sqrt(T - 1) / np.sqrt(1 - x.skew() * s + (x.kurt() + 2) / 4 * s ** 2))
    pr(f"{p}: Sharpe {s*np.sqrt(252):.2f}, t-stat {s*np.sqrt(T):.2f}, Sharpe deflacionado {dsr*100:.0f}% ({n_tent} tentativas)")
open(S / "robustez_final.txt", "w", encoding="utf-8").write("\n".join(txt))
pd.DataFrame(base).to_csv(S / "finalistas_v2_diario.csv")

# ------------------------------------------------------------------ gráfico
cores = {"CDI+1": "#003399", "CDI+5": "#EC7000", "CDI+10": "#C0392B"}
c_ = cdi.reindex(o)
fig = plt.figure(figsize=(14, 13))
gs = fig.add_gridspec(3, 3, height_ratios=[2.2, 1, 1.2])
a0 = fig.add_subplot(gs[0, :])
a0.axvspan(teste[0], teste[-1], color="#FFF4EA", zorder=0)
a0.plot(o, (1 + c_).cumprod() * 100, "k--", lw=1.5, label="CDI")
for p, r in base.items():
    st = stats(r)
    a0.plot(o, (1 + c_ + r.reindex(o)).cumprod() * 100, color=cores[p], lw=2.2,
            label=f"{p}: validação CDI{st['val']:+.1f} | teste CDI{st['teste']:+.1f} | queda máx. vs CDI {st['queda']:.0f}%")
    a0.plot(o, ((1 + c_) * (1 + META[p] / 100) ** (1 / 252)).cumprod() * 100, color=cores[p], ls=":", lw=.9)
a0.set_title("Três finalistas (pontilhado = meta) — fundo laranja = teste 2024-26", loc="center", fontweight="bold")
a0.legend(frameon=False, loc="upper left", fontsize=9)
for j, p in enumerate(FIN):
    a = fig.add_subplot(gs[1, j])
    a.hist(mc[p], bins=60, color=cores[p], alpha=.8)
    a.axvline(0, color="k", lw=1)
    a.axvline(META[p], color="k", ls=":", lw=1)
    a.set_title(f"{p}: Monte Carlo 3 anos (CDI+ % a.a.)", loc="center", fontsize=10, fontweight="bold")
    a.set_yticks([])
for j, p in enumerate(FIN):
    a = fig.add_subplot(gs[2, j])
    labels = ["finalista", "vizinhos\n(mediana)", "custo x2", "custo x3", "exec. +1d", "aleatório\n(mediana)"]
    vals = [anual(base[p].reindex(o)), viz[p].total.median(), sens["custo x2"][p]["total"], sens["custo x3"][p]["total"],
            sens["execução +1 dia"][p]["total"], np.median(aleat[p])]
    a.bar(labels, vals, color=[cores[p]] + ["#BFBFBF"] * 5)
    a.axhline(META[p], color="k", ls=":", lw=1)
    for i, v in enumerate(vals):
        a.text(i, v, f"{v:+.1f}", ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
    a.set_title(f"{p}: CDI+ % a.a. 2021-26 sob estresse", loc="center", fontsize=10, fontweight="bold")
    a.tick_params(axis="x", labelsize=7.5)
for a in fig.axes:
    a.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(S / "robustez_final.png", dpi=130)
print("pronto")
