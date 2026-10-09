"""
A ação do emissor mexe antes da debênture?
  Diário (2019-2026): retorno da ação no dia t x retorno hedgeado da debênture nos dias seguintes, só entre dias com negócio
     (sem a suavização da interpolação). Regressão de Fama-MacBeth (uma por dia, t-stat da média) e estudo de eventos:
     ação cai mais de 2 desvios no dia -> excesso da debênture do mesmo emissor de t+2 a t+6 e t+22 (executando em t+1).
  Intradiário (2024-10 a 2026-10): cada negócio de debênture com taxa x quanto a ação andou do fechamento anterior até a hora
     do negócio (barras de 1 h); e se o resto do ajuste acontece no dia seguinte.
Saída: resultado/lead_lag.txt e resultado/lead_lag.png
"""
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
Q = Path(__file__).resolve().parent
S, D_ = Q / "resultado", Q / "dados"
B = pd.read_pickle(S / "base_diaria.pkl")
dias, cdi, cad = B["dias"], B["cdi"], B["cad"]
txt = []
p = lambda *a: (print(*a, flush=True), txt.append(" ".join(str(x) for x in a)))

# ------------------------------------------------------------------ diário
acoes = pd.read_parquet(D_ / "acoes_diario.parquet").reindex(dias)
acoes.columns = [str(c).zfill(14) for c in acoes.columns]
ra = np.log(acoes).diff()
cnpj = cad.cnpj.astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)
deb = [k for k in B["P"].columns if cnpj.get(k) in ra.columns]
P = B["P"][deb]
exc = np.log1p((B["R"][deb] + B["Hdd"].reindex_like(B["R"])[deb].fillna(0)).sub(cdi, axis=0).fillna(0))
p(f"debêntures com ação do emissor: {len(deb)} de {B['P'].shape[1]}")
A = pd.DataFrame({k: ra[cnpj[k]] for k in deb}, index=dias)
zA = A / A.rolling(63, min_periods=30).std().shift(1)
res = {}
for h in (0, 1, 5, 21):
    # retorno da debênture de t+1+... (h=0: mesmo dia), só onde houve negócio no fim da janela
    fut = exc.shift(-1).rolling(max(h, 1)).sum().shift(-(max(h, 1) - 1)) if h else exc
    fut = fut.where(P.shift(-max(h, 1)).notna() if h else P.notna())
    betas = []
    for d in dias[(dias >= "2019-06-01")]:
        x, y = zA.loc[d], fut.loc[d]
        ok = x.notna() & y.notna()
        if ok.sum() >= 15:
            xx = x[ok] - x[ok].mean()
            if (xx ** 2).sum() > 0:
                betas.append((xx * (y[ok] - y[ok].mean())).sum() / (xx ** 2).sum())
    b = np.array(betas)
    b = b[np.isfinite(b)]
    res[h] = (b.mean() * 1e4, b.mean() / b.std() * np.sqrt(len(b)), len(b))
    p(f"ação em t (1 desvio) -> debênture {'no mesmo dia' if h == 0 else f'de t+1 a t+{h}'}: {b.mean() * 1e4:+.2f} bps, "
      f"t = {res[h][1]:.1f} ({len(b)} dias)")
# estudo de eventos: queda forte da ação
ev = []
for k in deb:
    for d in zA.index[(zA[k] < -2)]:
        i = dias.get_loc(d)
        if i + 23 < len(dias):
            rel = exc[k].iloc[i + 2:i + 23] - exc.iloc[i + 2:i + 23].mean(axis=1)    # contra a média das debêntures
            ev.append({"codigo": k, "date": d, "r5": rel.iloc[:5].sum() * 1e4, "r21": rel.sum() * 1e4,
                       "neg5": P[k].iloc[i + 1:i + 7].notna().any()})
ev = pd.DataFrame(ev)
for nome, g in (("todas", ev), ("com negócio na semana", ev[ev.neg5])):
    p(f"evento ação < -2 desvios ({nome}, n={len(g)}): excesso relativo da debênture t+2..t+6 = {g.r5.mean():+.1f} bps "
      f"(t {g.r5.mean() / g.r5.std() * np.sqrt(len(g)):.1f}); t+2..t+22 = {g.r21.mean():+.1f} bps (t {g.r21.mean() / g.r21.std() * np.sqrt(len(g)):.1f})")

# ------------------------------------------------------------------ intradiário
neg = pd.concat([pd.read_parquet(f) for f in sorted((Q.parent / "dados_monitor" / "b3").glob("2*.parquet"))], ignore_index=True)
neg = neg[neg.tipo.eq("DEB") & neg.taxa.notna() & neg.hora.notna() & (neg.vol >= 1e5)]
neg["cnpj"] = neg.cod.map(cnpj)
h1 = pd.read_parquet(D_ / "acoes_1h.parquet")
mapa = pd.read_csv(D_ / "acoes_mapa.csv", dtype=str)
mapa["cnpj"] = mapa.cnpj.str.zfill(14)
h1 = h1.merge(mapa, on="ticker").sort_values("hora")
h1["dia"] = h1.hora.dt.normalize()
fech = h1.groupby(["cnpj", "dia"]).close.last().rename("fech").reset_index()
fech["fech_ant"] = fech.groupby("cnpj").fech.shift(1)
neg = neg[neg.cnpj.isin(set(h1.cnpj))].copy()
neg["ts"] = pd.to_datetime(neg.data.dt.strftime("%Y-%m-%d") + " " + neg.hora.astype(str), errors="coerce")
neg = neg.dropna(subset=["ts"]).sort_values("ts")
neg = pd.merge_asof(neg, h1[["hora", "cnpj", "close"]].rename(columns={"hora": "ts"}), on="ts", by="cnpj", direction="backward",
                    tolerance=pd.Timedelta(hours=2))
neg = neg.merge(fech, left_on=["cnpj", "data"], right_on=["cnpj", "dia"], how="left")
neg["ret_acao_ate"] = np.log(neg.close / neg.fech_ant)
neg["ret_acao_dia"] = np.log(neg.fech / neg.fech_ant)
med = neg.groupby(["cod", "data"]).apply(lambda g: np.average(g.taxa, weights=g.vol)).rename("med").reset_index()
med["med_ant"] = med.groupby("cod").med.shift(1)
med["med_prox"] = med.groupby("cod").med.shift(-1)
neg = neg.merge(med, on=["cod", "data"])
neg["desvio"] = (neg.taxa - neg.med_ant) * 100                            # taxa do negócio contra a taxa de ontem (bps)
neg = neg[neg.desvio.abs() < 100]
x = neg.dropna(subset=["ret_acao_ate", "desvio"])
b1 = np.polyfit(x.ret_acao_ate * 100, x.desvio, 1)[0]
c1 = x.ret_acao_ate.corr(x.desvio)
p(f"\nintradiário: {len(x)} negócios de {x.cod.nunique()} debêntures ({x.data.min():%m/%Y} a {x.data.max():%m/%Y})")
p(f"ação andou 1% desde o fechamento anterior até a hora do negócio -> taxa do negócio {b1:+.2f} bps (correlação {c1:+.3f})")
d = med.merge(neg.groupby(["cod", "data"]).ret_acao_dia.first().reset_index(), on=["cod", "data"]).dropna()
d["mudou_hoje"], d["muda_amanha"] = (d.med - d.med_ant) * 100, (d.med_prox - d.med) * 100
d = d[(d.mudou_hoje.abs() < 100) & (d.muda_amanha.abs() < 100)]
for nome, col in (("no mesmo dia", "mudou_hoje"), ("no dia seguinte", "muda_amanha")):
    bb = np.polyfit(d.ret_acao_dia * 100, d[col], 1)[0]
    p(f"ação -1% no dia -> taxa da debênture {nome}: {-bb:+.2f} bps (correlação {d.ret_acao_dia.corr(d[col]):+.3f}, n={len(d)})")
grande = d[d.ret_acao_dia < -.05]
p(f"dias com ação < -5% (n={len(grande)}): taxa sobe {grande.mudou_hoje.mean():+.1f} bps no dia e mais {grande.muda_amanha.mean():+.1f} bps no dia seguinte")
open(S / "lead_lag.txt", "w", encoding="utf-8").write("\n".join(txt))

fig, ax = plt.subplots(1, 2, figsize=(13, 4.8))
ax[0].bar([f"mesmo dia", "t+1", "t+1..5", "t+1..21"], [res[h][0] for h in (0, 1, 5, 21)], color=["#BFCDEB", "#EC7000", "#EC7000", "#EC7000"])
for i, h in enumerate((0, 1, 5, 21)):
    ax[0].text(i, res[h][0], f"t={res[h][1]:.1f}", ha="center", va="bottom", fontsize=9)
ax[0].set_title("Ação +1 desvio em t -> retorno da debênture (bps)", loc="left", fontweight="bold")
sm = x.sample(min(20000, len(x)), random_state=0)
ax[1].scatter(sm.ret_acao_ate * 100, sm.desvio, s=3, alpha=.25, color="#003399")
xs = np.linspace(-10, 10, 50)
ax[1].plot(xs, b1 * xs, color="#EC7000", lw=2)
ax[1].set_xlim(-10, 10)
ax[1].set_xlabel("ação: fechamento anterior -> hora do negócio (%)")
ax[1].set_ylabel("taxa do negócio - taxa de ontem (bps)")
ax[1].set_title("Intradiário: negócio a negócio", loc="left", fontweight="bold")
for a in ax:
    a.grid(alpha=.25)
    a.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(S / "lead_lag.png", dpi=140)
