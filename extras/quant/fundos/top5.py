"""
Rodada 2: junta todos os fundos testados (rodada 1 + ideias_*.py), ranqueia e faz o dossiê dos 5 melhores:
curva vs benchmarks, sensibilidade (parâmetros, custo, atraso de execução, ano a ano) e robustez (bootstrap, PBO, DSR).
Uso: python top5.py [nome1 nome2 ...]   (sem nomes = escolhe pela nota)
Saídas em resultado/rodada2/: ranking_todos.csv, top5_curvas.png, top5_<n>.png, top5_correlacao.png, top5.csv
"""
import glob
import importlib
import pickle
import sys
import textwrap
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from base import CDI, R_IBOV
from motor import anual, aplica_taxas, bootstrap_prob
from regimes import com_regime
from rodada_final import EXCLUI
from rodar import BENCH

AQUI = Path(__file__).resolve().parent
OUT = AQUI / "resultado" / "final" / "top5"
OUT.mkdir(parents=True, exist_ok=True)
NAVY, LAR, VERDE, VERM, CINZA = "#1F2A4D", "#EC7000", "#2E7D4F", "#B23A3A", "#9AA3B2"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": .2, "font.size": 9})


def carrega():
    res = []
    for p in sorted(map(Path, glob.glob(str(AQUI / "resultado" / "final" / "*.pkl")))):
        try:
            rs = pickle.load(open(p, "rb"))
        except Exception as e:
            print("falhou", p.name, e)
            continue
        for r in rs if isinstance(rs, list) else rs.values():
            if r and r["fundo"].nome not in EXCLUI:
                r["origem"] = p.stem
                res.append(r)
    return res


def funcoes():
    """nome do fundo -> Fundo com func (reimporta os módulos, que não vão para o pickle)."""
    m = {}
    for mod in ["rodar"] + [Path(x).stem for x in glob.glob(str(AQUI / "ideias_*.py"))]:
        try:
            mm = importlib.import_module(mod)
            for f in (getattr(mm, "FUNDOS", None) or mm._fundos()):
                m[f.nome] = com_regime(f)
        except Exception as e:
            print("módulo", mod, e)
    return m


def alfa(r):
    """Alfa OOS depois de tirar beta de Ibovespa e S&P (com hedge): regressão diária do excesso sobre o CDI."""
    liq, corte = r["liquido"], pd.Timestamp(r["fundo"].corte)
    y = (liq - CDI.reindex(liq.index)).loc[corte:].dropna()
    X = pd.DataFrame({"ibov": (R_IBOV - CDI).reindex(y.index), "sp": (BENCH["S&P 500 (R$ c/ hedge)"] - CDI).reindex(y.index)}).fillna(0)
    X.insert(0, "c", 1.0)
    b, *_ = np.linalg.lstsq(X.values, y.values, rcond=None)
    res_ = y.values - X.values @ b
    se = np.sqrt(res_.var(ddof=3) * np.linalg.inv(X.T @ X)[0, 0])
    return b[0] * 252 * 100, b[0] / se, b[1], b[2]


def tabela(res):
    L = []
    for r in res:
        f, o, rb = r["fundo"], r["oos"], r["rob"]
        L.append({"fundo": f.nome, "origem": r["origem"], "categoria": f.categoria, "benchmark": f.benchmark, "OOS desde": f.corte[:7],
                  "params": str(r["params"]), "OOS a.a. %": o["retorno a.a. %"], "bench OOS %": o["benchmark a.a. %"], "OOS ativo pp": o["ativo a.a. pp"],
                  "IR OOS": o["IR vs bench"], "vol OOS %": o["vol a.a. %"], "pior queda OOS %": o["pior queda %"], "IR IS": r["is_ir"],
                  "P(bater) %": rb["P(bater bench OOS) %"], "PBO %": rb["PBO %"], "DSR %": rb["Sharpe deflac. OOS %"],
                  "% variantes > bench": rb["% variantes > bench OOS"], "custo x2 pp": rb["OOS custo x2 (pp)"], "exec +1 pp": rb["OOS execução +1 dia (pp)"],
                  "variantes": rb["variantes"], "tese": f.tese, "estrutura": f.estrutura})
        L[-1]["alfa OOS pp"], L[-1]["t alfa"], L[-1]["beta Ibov"], L[-1]["beta S&P"] = alfa(r)
    t = pd.DataFrame(L).drop_duplicates("fundo", keep="last")
    ganha = (t["OOS ativo pp"] > 0).astype(float)
    rob = ((t["custo x2 pp"] > 0).astype(float) + (t["exec +1 pp"] > 0).astype(float)) / 2
    t["nota"] = (.15 * t["IR OOS"].fillna(-9).rank(pct=True) + .15 * t["t alfa"].fillna(-9).rank(pct=True) + .25 * t["P(bater) %"].fillna(0) / 100
                 + ganha * (.15 * (1 - t["PBO %"].fillna(50) / 100) + .15 * t["% variantes > bench"].fillna(0) / 100 + .15 * rob)) * 100
    return t.sort_values("nota", ascending=False).reset_index(drop=True)


def liquido(f, e, b):
    e = e[e.index >= pd.Timestamp(f.inicio)]
    return aplica_taxas(e, CDI.reindex(e.index), b.reindex(e.index), f)


def ativo_oos(f, liq, b):
    o = liq[liq.index >= pd.Timestamp(f.corte)]
    return anual(o) - anual(b.reindex(o.index).fillna(0))


def dossie(k, r, F, b):
    f = F.get(r["fundo"].nome, r["fundo"])
    liq, corte = r["liquido"], pd.Timestamp(f.corte)
    fig = plt.figure(figsize=(18, 11))
    g = fig.add_gridspec(3, 3, hspace=.45, wspace=.25)
    # 1 curva
    ax = fig.add_subplot(g[0, :2])
    idx = liq.index
    for s, lab, kw in ((liq, "fundo (líquido de custos)", dict(color=VERDE, lw=2)), (CDI.reindex(idx).fillna(0), "CDI", dict(color="k", ls="--", lw=1)),
                       (R_IBOV.reindex(idx).fillna(0), "Ibovespa", dict(color="#C9CFD9", lw=1))):
        ax.plot(idx, (1 + s).cumprod() * 100, label=lab, **kw)
    if f.benchmark not in ("CDI", "Ibovespa"):
        ax.plot(idx, (1 + b.reindex(idx).fillna(0)).cumprod() * 100, color=NAVY, ls=":", label=f.benchmark)
    ax.axvspan(corte, idx[-1], color="#FFF1E3", zorder=0)
    ax.set_yscale("log")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.set_title("Cota vs benchmarks (faixa laranja = fora da amostra)", loc="left", fontweight="bold", color=NAVY)
    # 2 drawdown
    ax = fig.add_subplot(g[0, 2])
    eq = (1 + liq).cumprod()
    ax.fill_between(idx, (eq / eq.cummax() - 1) * 100, color=VERM, alpha=.5)
    ax.set_title("Queda a partir do pico (%)", loc="left", fontweight="bold", color=NAVY)
    # 3 ano a ano
    ax = fig.add_subplot(g[1, 0])
    a = (liq - b.reindex(idx).fillna(0))
    ano = a.groupby(a.index.year).apply(lambda x: ((1 + liq.loc[x.index]).prod() - (1 + b.reindex(x.index).fillna(0)).prod()) * 100)
    ax.bar(ano.index.astype(str), ano.values, color=[VERDE if v > 0 else VERM for v in ano], width=.7)
    ax.tick_params(axis="x", rotation=90, labelsize=7)
    ax.set_title(f"Retorno ativo por ano vs {f.benchmark.split(' ')[0]} (pp)", loc="left", fontweight="bold", color=NAVY)
    # 4 sensibilidade de parâmetros: OOS de cada variante
    ax = fig.add_subplot(g[1, 1])
    at = r["ativos"]
    oos_v = at[at.index >= corte].apply(lambda x: (((1 + x).prod()) ** (252 / max(len(x), 1)) - 1) * 100).sort_values()
    lab = [textwrap.shorten(c.replace("'", ""), 34) for c in oos_v.index]
    esc = [c == str(r["params"]) for c in oos_v.index]
    ax.barh(range(len(oos_v)), oos_v.values, color=[LAR if e else (VERDE if v > 0 else VERM) for e, v in zip(esc, oos_v)])
    ax.set_yticks(range(len(oos_v)), lab, fontsize=6)
    ax.axvline(0, color="k", lw=.6)
    ax.set_title("Sensibilidade: ativo OOS de cada variante (pp a.a.; laranja = escolhida no IS)", loc="left", fontweight="bold", color=NAVY, fontsize=8.5)
    # 5 custo e atraso
    ax = fig.add_subplot(g[1, 2])
    linhas = {}
    if f.func is not None:
        for nome, kws in (("custo", [{"custo_mult": m} for m in (0, .5, 1, 2, 3)]), ("atraso", [{"lag": l} for l in (0, 1, 2, 5)])):
            vals = []
            for kw in kws:
                try:
                    vals.append(ativo_oos(f, liquido(f, f.func(**r["params"], **kw), b), b))
                except Exception:
                    vals.append(np.nan)
            linhas[nome] = vals
        ax.plot(["0", "0,5x", "1x", "2x", "3x"], linhas["custo"], "o-", color=NAVY, label="custo (multiplicador)")
        ax2 = ax.twiny()
        ax2.plot(["t+1", "t+2", "t+3", "t+6"], linhas["atraso"], "s--", color=LAR, label="execução")
        ax2.tick_params(labelsize=7, colors=LAR)
        ax.axhline(0, color="k", lw=.6)
        ax.legend(frameon=False, fontsize=7, loc="lower left")
        ax2.legend(frameon=False, fontsize=7, loc="lower right")
    ax.set_title("Sensibilidade a custo e atraso (ativo OOS, pp a.a.)", loc="left", fontweight="bold", color=NAVY, fontsize=8.5, pad=18)
    # 6 bootstrap
    ax = fig.add_subplot(g[2, 0])
    ao = (liq - b.reindex(idx).fillna(0))[idx >= corte].values
    rng = np.random.default_rng(0)
    n, bl = len(ao), 21
    sims = []
    for _ in range(2000):
        ini = rng.integers(0, n, n // bl + 1)
        amostra = np.concatenate([np.take(ao, range(i, i + bl), mode="wrap") for i in ini])[:n]
        sims.append(amostra.mean() * 252 * 100)
    sims = np.array(sims)
    ax.hist(sims, bins=50, color=NAVY, alpha=.75)
    ax.axvline(0, color=VERM, lw=1.5)
    ax.set_title(f"Bootstrap do ativo OOS (pp a.a.): P(>0) = {(sims > 0).mean() * 100:.0f}%", loc="left", fontweight="bold", color=NAVY)
    # 7 ativo rolante 12m
    ax = fig.add_subplot(g[2, 1])
    roll = (1 + liq).rolling(252).apply(np.prod, raw=True) - (1 + b.reindex(idx).fillna(0)).rolling(252).apply(np.prod, raw=True)
    ax.plot(idx, roll * 100, color=NAVY)
    ax.axhline(0, color="k", lw=.6)
    ax.axvline(corte, color=LAR, lw=1.5)
    ax.set_title("Ativo em 12 meses móveis (pp)", loc="left", fontweight="bold", color=NAVY)
    # 8 ficha
    ax = fig.add_subplot(g[2, 2])
    ax.axis("off")
    o, rb = r["oos"], r["rob"]
    txt = (f"Benchmark: {f.benchmark}   |   OOS desde {f.corte[:7]}\nParâmetros: {r['params']}\n\n"
           f"OOS: {o['retorno a.a. %']:.1f}% a.a. vs {o['benchmark a.a. %']:.1f}%  (ativo {o['ativo a.a. pp']:+.1f} pp)\n"
           f"IR OOS {o['IR vs bench']:.2f} | Sharpe {o['Sharpe']:.2f} | vol {o['vol a.a. %']:.1f}% | pior queda {o['pior queda %']:.1f}%\n"
           f"P(bater) {rb['P(bater bench OOS) %']:.0f}% | PBO {rb['PBO %']:.0f}% | Sharpe deflac. {rb['Sharpe deflac. OOS %']:.0f}%\n"
           f"Variantes que batem o bench: {rb['% variantes > bench OOS']:.0f}% de {rb['variantes']}\n"
           f"Custo x2: {rb['OOS custo x2 (pp)']:+.1f} pp | execução +1 dia: {rb['OOS execução +1 dia (pp)']:+.1f} pp\n\n"
           + "\n".join(textwrap.wrap("Tese: " + f.tese, 70)) + "\n" + "\n".join(textwrap.wrap("Estrutura: " + f.estrutura, 70)))
    ax.text(0, 1, txt, va="top", fontsize=8.3, family="DejaVu Sans")
    fig.suptitle(f"#{k}  {f.nome}", fontsize=16, fontweight="bold", color=NAVY, x=.01, ha="left")
    fig.savefig(OUT / f"top5_{k}.png", dpi=105, bbox_inches="tight")
    plt.close(fig)
    return linhas


if __name__ == "__main__":
    res = carrega()
    t = tabela(res)
    t.to_csv(OUT / "ranking_todos.csv", encoding="utf-8-sig", index=False)
    pd.set_option("display.width", 250)
    print(t[["fundo", "origem", "benchmark", "OOS a.a. %", "bench OOS %", "OOS ativo pp", "IR OOS", "P(bater) %", "PBO %", "% variantes > bench",
             "custo x2 pp", "exec +1 pp", "alfa OOS pp", "t alfa", "beta Ibov", "beta S&P", "nota"]].round(2).to_string())
    escolha = sys.argv[1:] or list(t.fundo[:5])
    por_nome = {r["fundo"].nome: r for r in res}
    F = funcoes()
    top = [por_nome[n] for n in escolha]
    sens = {}
    for k, r in enumerate(top, 1):
        b = BENCH[r["fundo"].benchmark]
        sens[r["fundo"].nome] = dossie(k, r, F, b)
        print("dossiê", k, r["fundo"].nome)
    # visão conjunta
    fig, axs = plt.subplots(1, len(top), figsize=(5 * len(top), 4.2))
    for ax, (k, r) in zip(np.atleast_1d(axs), enumerate(top, 1)):
        liq, f = r["liquido"], r["fundo"]
        b = BENCH[f.benchmark].reindex(liq.index).fillna(0)
        ax.plot(liq.index, (1 + liq).cumprod() * 100, color=VERDE, lw=2, label="fundo")
        ax.plot(liq.index, (1 + b).cumprod() * 100, color=NAVY, ls="--", lw=1.2, label=f.benchmark)
        ax.plot(liq.index, (1 + R_IBOV.reindex(liq.index).fillna(0)).cumprod() * 100, color="#C9CFD9", lw=1, label="Ibovespa")
        ax.axvspan(pd.Timestamp(f.corte), liq.index[-1], color="#FFF1E3", zorder=0)
        ax.set_yscale("log")
        ax.set_title(f"#{k} {textwrap.shorten(f.nome, 40)}\nOOS {r['oos']['ativo a.a. pp']:+.1f} pp a.a. | P(bater) {r['rob']['P(bater bench OOS) %']:.0f}%",
                     loc="left", fontweight="bold", color=NAVY, fontsize=9)
        ax.legend(frameon=False, fontsize=7, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "top5_curvas.png", dpi=110)
    # correlação e carteira igual-ponderada dos 5
    A = pd.DataFrame({r["fundo"].nome[:28]: r["liquido"] - CDI.reindex(r["liquido"].index) for r in top}).dropna()
    fig, ax = plt.subplots(figsize=(7, 6))
    c = A.corr()
    ax.imshow(c, cmap="RdBu_r", vmin=-1, vmax=1)
    for i in range(len(c)):
        for j in range(len(c)):
            ax.text(j, i, f"{c.iloc[i, j]:.2f}", ha="center", va="center", fontsize=9)
    ax.set_xticks(range(len(c)), [textwrap.fill(x, 14) for x in c.columns], fontsize=7)
    ax.set_yticks(range(len(c)), c.columns, fontsize=7)
    ax.set_title("Correlação diária dos excessos sobre o CDI", loc="left", fontweight="bold", color=NAVY)
    fig.tight_layout()
    fig.savefig(OUT / "top5_correlacao.png", dpi=110)
    t[t.fundo.isin(escolha)].to_csv(OUT / "top5.csv", encoding="utf-8-sig", index=False)
    pickle.dump(sens, open(OUT / "sensibilidade.pkl", "wb"))
    print("pronto")
