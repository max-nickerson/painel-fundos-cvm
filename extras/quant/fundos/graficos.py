"""Gráficos e ranking dos 20 fundos a partir de resultado/resultados.pkl."""
import pickle
import textwrap
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

from base import CDI, DIAS, R_IBOV

OUT = Path(__file__).resolve().parent / "resultado"
res = pickle.load(open(OUT / "resultados.pkl", "rb"))
from rodar import BENCH  # noqa: E402

NAVY, LAR, VERDE, VERM, CINZA = "#1F2A4D", "#EC7000", "#2E7D4F", "#B23A3A", "#9AA3B2"

# ------------------------------------------------------------------ tabela e ranking
linhas = []
for r in res:
    f, o, t, rb = r["fundo"], r["oos"], r["total"], r["rob"]
    linhas.append({"fundo": f.nome, "categoria": f.categoria, "benchmark": f.benchmark, "início": f.inicio[:4], "OOS desde": f.corte[:4],
                   "parâmetros": str(r["params"]), "tese": f.tese, "estrutura": f.estrutura,
                   "total a.a. %": t["retorno a.a. %"], "bench total a.a. %": t["benchmark a.a. %"], "OOS a.a. %": o["retorno a.a. %"],
                   "bench OOS a.a. %": o["benchmark a.a. %"], "OOS ativo pp": o["ativo a.a. pp"], "IR IS (bruto)": r["is_ir"], "IR OOS": o["IR vs bench"],
                   "Sharpe OOS": o["Sharpe"], "vol OOS %": o["vol a.a. %"], "pior queda OOS %": o["pior queda %"], "pior queda total %": t["pior queda %"],
                   "beta": t["beta vs bench"], "meses batendo %": o["meses batendo bench %"], "P(bater bench OOS) %": rb["P(bater bench OOS) %"],
                   "PBO %": rb["PBO %"], "Sharpe deflac. %": rb["Sharpe deflac. OOS %"], "% variantes > bench OOS": rb["% variantes > bench OOS"],
                   "OOS custo x2 pp": rb["OOS custo x2 (pp)"], "OOS exec +1 dia pp": rb["OOS execução +1 dia (pp)"], "variantes": rb["variantes"]})
tab = pd.DataFrame(linhas)
rk = lambda s, asc=False: s.rank(pct=True, ascending=not asc)
robusto = ((tab["OOS custo x2 pp"] > 0).astype(float) + (tab["OOS exec +1 dia pp"] > 0).astype(float)) / 2
ganha = (tab["OOS ativo pp"] > 0).astype(float)                         # robustez só conta se a ideia de fato bateu o benchmark
tab["nota"] = (.30 * rk(tab["IR OOS"].fillna(-9)) + .25 * tab["P(bater bench OOS) %"].fillna(0) / 100
               + ganha * (.15 * (1 - tab["PBO %"].fillna(50) / 100) + .15 * tab["% variantes > bench OOS"].fillna(0) / 100 + .15 * robusto)) * 100
tab = tab.sort_values("nota", ascending=False).reset_index(drop=True)
tab.index = tab.index + 1
tab.to_csv(OUT / "ranking.csv", encoding="utf-8-sig")
pd.set_option("display.width", 250)
print(tab[["fundo", "benchmark", "OOS a.a. %", "bench OOS a.a. %", "OOS ativo pp", "IR OOS", "P(bater bench OOS) %", "PBO %",
           "% variantes > bench OOS", "OOS custo x2 pp", "OOS exec +1 dia pp", "nota"]].round(1).to_string())

# ------------------------------------------------------------------ curvas
ordem = {n: i for i, n in enumerate(tab.fundo)}
res_o = sorted(res, key=lambda r: ordem[r["fundo"].nome])
fig, axs = plt.subplots(5, 4, figsize=(20, 22))
for ax, r in zip(axs.flat, res_o):
    f = r["fundo"]
    liq = r["liquido"]
    ini, corte = liq.index[0], pd.Timestamp(f.corte)
    idx = liq.index
    eq = (1 + liq).cumprod() * 100
    bench = BENCH[f.benchmark].reindex(idx).fillna(0)
    eqb = (1 + bench).cumprod() * 100
    eqc = (1 + CDI.reindex(idx).fillna(0)).cumprod() * 100
    eqi = (1 + R_IBOV.reindex(idx).fillna(0)).cumprod() * 100
    ax.axvspan(corte, idx[-1], color="#FFF1E3", zorder=0)
    ax.plot(idx, eqi, color="#C9CFD9", lw=1, label="Ibovespa")
    if f.benchmark not in ("CDI", "Ibovespa"):
        ax.plot(idx, eqb, color=NAVY, lw=1.2, ls=":", label=f.benchmark)
    ax.plot(idx, eqc, "k--", lw=1, label="CDI")
    t = tab[tab.fundo == f.nome].iloc[0]
    ax.plot(idx, eq, color=VERDE if t["OOS ativo pp"] > 0 else VERM, lw=1.8, label="fundo (líquido)")
    ax.set_yscale("log")
    ax.set_title(f"#{ordem[f.nome] + 1}  {f.nome[3:]}\nOOS: {t['OOS ativo pp']:+.1f} pp a.a. vs {f.benchmark.split(' ')[0]} | P(bater) {t['P(bater bench OOS) %']:.0f}%"
                 f" | PBO {t['PBO %']:.0f}%" if t["PBO %"] == t["PBO %"] else
                 f"#{ordem[f.nome] + 1}  {f.nome[3:]}\nOOS: {t['OOS ativo pp']:+.1f} pp a.a. vs {f.benchmark.split(' ')[0]} | P(bater) {t['P(bater bench OOS) %']:.0f}%",
                 fontsize=9, loc="left", fontweight="bold", color=NAVY)
    ax.tick_params(labelsize=7)
    ax.grid(alpha=.2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=6.5, frameon=False, loc="upper left")
for ax in list(axs.flat)[len(res_o):]:
    ax.axis("off")
fig.suptitle("20 fundos simulados (cota líquida de taxas e custos) — fundo laranja = fora da amostra; ordem = ranking", fontsize=15, fontweight="bold",
             color=NAVY)
fig.tight_layout(rect=[0, 0, 1, .975])
fig.savefig(OUT / "curvas_fundos.png", dpi=110)

# ------------------------------------------------------------------ robustez
cols = ["OOS ativo pp", "IR OOS", "P(bater bench OOS) %", "PBO %", "Sharpe deflac. %", "% variantes > bench OOS", "OOS custo x2 pp", "OOS exec +1 dia pp"]
bom = {"OOS ativo pp": (-5, 5), "IR OOS": (-1, 1), "P(bater bench OOS) %": (0, 100), "PBO %": (100, 0), "Sharpe deflac. %": (0, 100),
       "% variantes > bench OOS": (0, 100), "OOS custo x2 pp": (-5, 5), "OOS exec +1 dia pp": (-5, 5)}
M = tab[cols].astype(float)
N = pd.DataFrame({c: ((M[c] - bom[c][0]) / (bom[c][1] - bom[c][0])).clip(0, 1) for c in cols})
cmap = LinearSegmentedColormap.from_list("rg", ["#C0392B", "#F4F4F4", "#2E7D4F"])
fig = plt.figure(figsize=(20, 13))
ax = fig.add_axes([.27, .08, .5, .84])
ax.imshow(N.values, cmap=cmap, aspect="auto", vmin=0, vmax=1)
for i in range(len(M)):
    for j, c in enumerate(cols):
        v = M.iloc[i, j]
        ax.text(j, i, "-" if v != v else (f"{v:.0f}" if "%" in c else f"{v:+.2f}" if c == "IR OOS" else f"{v:+.1f}"), ha="center", va="center",
                fontsize=9, color="#1E2533")
ax.set_xticks(range(len(cols)), [textwrap.fill(c, 14) for c in cols], fontsize=9)
ax.xaxis.tick_top()
ax.set_yticks(range(len(tab)), [f"{i}. {n[3:]}" for i, n in zip(tab.index, tab.fundo)], fontsize=9.5)
ax.set_title("Robustez fora da amostra (verde = bom)", loc="left", fontweight="bold", color=NAVY, pad=40)
ax2 = fig.add_axes([.8, .08, .17, .84])
ax2.barh(range(len(tab)), tab["nota"], color=[VERDE if v >= 55 else LAR if v >= 40 else VERM for v in tab["nota"]])
ax2.set_ylim(len(tab) - .5, -.5)
ax2.set_yticks([])
for i, v in enumerate(tab["nota"]):
    ax2.text(v + 1, i, f"{v:.0f}", va="center", fontsize=9)
ax2.set_title("Nota (0-100)", loc="left", fontweight="bold", color=NAVY, pad=40)
ax2.spines[["top", "right"]].set_visible(False)
fig.text(.27, .02, "P(bater) = bootstrap estacionário do retorno ativo fora da amostra; PBO = prob. de overfitting (CSCV) entre as variantes;\n"
         "Sharpe deflac. = prob. do IR verdadeiro > 0 dado o nº de variantes; custo x2 e execução +1 dia = retorno ativo OOS nesses cenários.",
         fontsize=9, color="#555")
fig.savefig(OUT / "robustez_fundos.png", dpi=110)
pd.DataFrame({r["fundo"].nome: r["liquido"] for r in res}).to_csv(OUT / "fundos_diario.csv")
print("pronto")
