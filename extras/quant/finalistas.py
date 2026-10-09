"""
Três finalistas (CDI+1, CDI+5, CDI+10), diários, com escolha feita SÓ na validação (2021-2023) e teste intocado (2024-2026).
  Livros: crédito por faixa (melhor modelo da validação, de pesquisa_credito), eurobonds por sinal (carrego, sem stop),
          juros DAP 5a e DI1 2a (melhor modelo da validação de pesquisa_juros; se nenhum tiver Sharpe > 0 na validação, fica zerado).
  Alavancagem realista: crédito 1x (CDI+1), 1,5x (CDI+5, compromissada a CDI+1%), 2x (CDI+10, a CDI+1,5%);
          juros por futuros com volatilidade-alvo; regime de estresse (HMM) pode cortar o risco à metade (escolhido na validação).
  Significância: Sharpe deflacionado pelo nº de configurações, bootstrap estacionário e teste SPA (Hansen) contra o CDI.
"""
import contextlib
import io
import itertools
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from arch.bootstrap import SPA, StationaryBootstrap
from scipy.stats import norm

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
Q = Path(__file__).resolve().parent
S = Q / "resultado"
B = pd.read_pickle(S / "base_diaria.pkl")
dias, cdi = B["dias"], B["cdi"]
INI, VAL_FIM = pd.Timestamp("2021-01-04"), pd.Timestamp("2023-12-31")
oos = dias[dias >= INI]
val, teste = oos[oos <= VAL_FIM], oos[oos > VAL_FIM]
sh = lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() else -9

cred = pd.read_parquet(S / "credito_livros.parquet")
cred.columns = pd.MultiIndex.from_tuples([tuple(c.split("', '")) if isinstance(c, str) and "', '" in c else c for c in cred.columns]) \
    if not isinstance(cred.columns, pd.MultiIndex) else cred.columns
jur = pd.read_parquet(S / "juros_modelos.parquet")


def melhor(tab, grupo):
    """Modelo com maior Sharpe na validação dentro do grupo."""
    cols = [c for c in tab.columns if c[0] == grupo]
    s = {c: sh(tab[c].reindex(val).fillna(0)) for c in cols}
    c = max(s, key=s.get)
    return c, s[c], len(cols)


escolhas, n_tent = {}, 0
for fx in ("conservador", "moderado", "high yield"):
    c, s_, n = melhor(cred, fx)
    escolhas[fx] = (c, s_)
    n_tent += n
for lv in ("DAP5", "DI2"):
    c, s_, n = melhor(jur, lv)
    escolhas[lv] = (c if s_ > 0 else None, s_)
    n_tent += n
print("escolhas na validação:", {k: (v[0][1] if v[0] else "zerado", round(v[1], 2)) for k, v in escolhas.items()})

with contextlib.redirect_stdout(io.StringIO()):
    import estrategias_sinal as es
eb = es.livro(es.forca_eb(), es.ed.exc_eb, es.ed.PE, 15, es.e.CUSTO_EXT, -9, es.emis_eb)[0]   # eurobonds por sinal, sem stop
livro = lambda k: cred[escolhas[k][0]].reindex(dias).fillna(0)
juros = {lv: (jur[escolhas[lv][0]].reindex(dias).fillna(0) if escolhas[lv][0] else pd.Series(0.0, index=dias)) for lv in ("DAP5", "DI2")}
reg = pd.read_parquet(S / "juros_features.parquet")
estresse = reg[[c for c in reg if c.startswith("reg")]].iloc[:, -1].reindex(dias).fillna(0)     # regime de maior volatilidade
corte = (1 - .5 * (estresse > .5)).shift(2).fillna(1)                      # decide em t, vale a partir de t+2


def carteira(perfil, w_eb, w_juros, regime):
    cr, alav, fin = {"CDI+1": ("conservador", 1.0, 0), "CDI+5": ("moderado", 1.5, .01), "CDI+10": ("high yield", 2.0, .015)}[perfil]
    credito = alav * ((1 - w_eb) * livro(cr) + w_eb * eb) - (alav - 1) * fin / 252
    jr = w_juros * (juros["DAP5"] + juros["DI2"]) / 2                       # cada livro de juros a 5% de vol; w_juros escala
    tot = credito + jr
    return tot * (corte if regime else 1)


grade = {"CDI+1": list(itertools.product([0, .2], [0, .2, .5], [False, True])),
         "CDI+5": list(itertools.product([.3], [.5, 1, 2], [False, True])),
         "CDI+10": list(itertools.product([.3], [1, 2, 3], [False, True]))}
meta = {"CDI+1": 1, "CDI+5": 5, "CDI+10": 10}
finais, todas = {}, {}
for p, cfgs in grade.items():
    cand = {}
    for w_eb, w_j, rg in cfgs:
        r = carteira(p, w_eb, w_j, rg)
        todas[(p, w_eb, w_j, rg)] = r
        rv = r.reindex(val)
        anual = ((1 + rv).prod() ** (252 / len(rv)) - 1) * 100
        cand[(w_eb, w_j, rg)] = (sh(rv), anual)
    ok = {k: v for k, v in cand.items() if v[1] >= meta[p]} or cand        # bate a meta na validação; entre esses, maior Sharpe
    k = max(ok, key=lambda z: ok[z][0])
    finais[p] = (k, todas[(p, *k)])
    n_tent += len(cfgs)


def estat(r, n_trials):
    x = r.reindex(teste).fillna(0)
    T, s = len(x), x.mean() / x.std()
    g3, g4 = x.skew(), x.kurt() + 3
    sr_all = np.array([sh(v.reindex(val).fillna(0)) / np.sqrt(252) for v in todas.values()] + [s])
    sr0 = np.std(sr_all) * ((1 - .5772) * norm.ppf(1 - 1 / n_trials) + .5772 * norm.ppf(1 - 1 / (n_trials * np.e)))
    dsr = norm.cdf((s - sr0) * np.sqrt(T - 1) / np.sqrt(1 - g3 * s + (g4 - 1) / 4 * s ** 2))
    bs = StationaryBootstrap(21, x.to_numpy(), seed=0)
    ann = np.array([((1 + b[0][0]).prod() ** (252 / T) - 1) * 100 for b in bs.bootstrap(2000)])
    return {"teste CDI+ % a.a.": ((1 + x).prod() ** (252 / T) - 1) * 100, "teste Sharpe": s * np.sqrt(252),
            "IC 5%": np.percentile(ann, 5), "IC 95%": np.percentile(ann, 95), "P(< CDI)": (ann < 0).mean() * 100,
            "t-stat": s * np.sqrt(T), "Sharpe deflacionado %": dsr * 100}


linhas = []
for p, (k, r) in finais.items():
    rv, rt = r.reindex(val), r.reindex(teste)
    eq = (1 + r.reindex(oos)).cumprod()
    linhas.append({"perfil": p, "eurobonds": k[0], "peso juros": k[1], "corte por regime": k[2],
                   "validação CDI+ % a.a.": ((1 + rv).prod() ** (252 / len(rv)) - 1) * 100, "validação Sharpe": sh(rv),
                   **estat(r, n_tent), "pior queda total %": (eq / eq.cummax() - 1).min() * 100,
                   "vol a.a. %": r.reindex(oos).std() * np.sqrt(252) * 100})
tab = pd.DataFrame(linhas).set_index("perfil")
spa = SPA(np.zeros(len(oos)), -np.column_stack([v.reindex(oos).fillna(0) for v in todas.values()]), reps=2000, seed=0)
spa.compute()
pd.set_option("display.width", 250)
print(f"\nconfigurações testadas no total: {n_tent}")
print(tab.round(2).T.to_string())
print("\nSPA (Hansen) — H0: nenhuma configuração bate o CDI; p-valores (inferior, consistente, superior):", np.round(spa.pvalues.values, 4))
tab.to_csv(S / "finalistas.csv")
pd.DataFrame({p: r for p, (k, r) in finais.items()}).to_csv(S / "finalistas_diario.csv")

# gráfico
c_ = cdi.reindex(oos)
cores = {"CDI+1": "#003399", "CDI+5": "#EC7000", "CDI+10": "#C0392B"}
fig, ax = plt.subplots(2, 1, figsize=(13, 9.5), gridspec_kw={"height_ratios": [3, 1.3]}, sharex=True)
for a in ax:
    a.axvspan(teste[0], teste[-1], color="#FFF4EA", zorder=0)
    est = estresse.reindex(oos) > .5
    for i0, g in est.groupby((est != est.shift()).cumsum()):
        if g.iloc[0]:
            a.axvspan(g.index[0], g.index[-1], color="#E6E6E6", zorder=0, lw=0)
ax[0].plot(oos, (1 + c_).cumprod() * 100, "k--", lw=1.8, label="CDI")
for p, (k, r) in finais.items():
    eq = (1 + c_ + r.reindex(oos)).cumprod()
    t = tab.loc[p]
    ax[0].plot(oos, eq * 100, color=cores[p], lw=2, label=f"{p}: validação CDI{t['validação CDI+ % a.a.']:+.1f}, teste CDI{t['teste CDI+ % a.a.']:+.1f} "
                                                          f"(IC {t['IC 5%']:+.1f} a {t['IC 95%']:+.1f})")
    ax[0].plot(oos, ((1 + c_) * (1 + meta[p] / 100) ** (1 / 252)).cumprod() * 100, color=cores[p], ls=":", lw=1)
    ax[1].plot(oos, (eq / eq.cummax() - 1) * 100, color=cores[p], lw=1.2)
ax[0].set_title("Finalistas diários (escolhidos só na validação) — fundo laranja = teste intocado 2024-26, cinza = regime de estresse (HMM)",
                loc="left", fontweight="bold", fontsize=11)
ax[0].legend(frameon=False, loc="upper left", fontsize=9)
ax[1].set_title("Queda a partir do pico (%)", loc="left", fontweight="bold")
for a in ax:
    a.grid(alpha=.25)
    a.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(S / "finalistas.png", dpi=140)
print("pronto")
