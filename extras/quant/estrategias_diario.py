"""
As três carteiras (CDI+1, CDI+5, CDI+10) em frequência DIÁRIA, com custo de execução medido nos negócios intradiários.
  Debêntures: retorno diário = %PU da curva (SND, interpolado entre negócios) x PU par do dia; hedge diário com DAP/DI1 pelo
              ajuste da B3 (contrato e razão de duration escolhidos no fim do mês anterior).
  Eurobonds: preço diário (FINRA) + cupom corrido, hedge de câmbio com DOL (ajuste diário) e de juros com Treasury (curva diária).
  Juros: DAP 5a e DI1 2a direcionais, sinal (a) mensal como antes ou (b) atualizado todo dia, executado no dia seguinte.
  Crédito: seleção mensal (modelo de crédito / spread), entrada LAG dias úteis depois do fim do mês, carrega 63 dias úteis.
  Custo: meia dispersão intradiária das taxas negociadas no mesmo papel e dia (balcão B3) x duration, por faixa de spread.
Uso: python estrategias_diario.py   (depois de estrategias.py)
"""
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import estrategias as e
from estrategias import lt

S, DADOS = e.SAIDA, e.DADOS
pn, Hd, mx, pj, fret, ult, fm = pd.read_pickle(S / "cache_estrategias.pkl")
b = pd.read_parquet(S / "credito_ml.parquet")
_, sprd_eb, cad_eb, _, _ = pd.read_pickle(S / "cache_ext.pkl")
ind = pd.read_parquet(DADOS / "indices.parquet")
dias = ind.index[(ind.index >= "2019-01-02")]
cdi = ind.cdi.reindex(dias)
mes = dias.to_period("M")
cad = pn["cad"]
SEGURA = 63


# ------------------------------------------------------------------ futuros diários
fut = pd.read_parquet(DADOS / "futuros.parquet").sort_values("AdjstdQt", na_position="first").drop_duplicates(["date", "ticker"], keep="last")
fut = fut[fut.AdjstdQt.notna() & fut.PrvsAdjstdQt.gt(0)]
F = (fut.AdjstdQt / fut.PrvsAdjstdQt - 1).groupby([fut.date, fut.ticker]).last().unstack().reindex(dias)
cls_, mm = fut.ticker.str[:3], fut.ticker.str[3].map(e.MESES.index if hasattr(e, "MESES") else "FGHJKMNQUVXZ".index) + 1
fut["venc"] = pd.to_datetime(dict(year=2000 + fut.ticker.str[4:6].astype(int), month=mm, day=np.where(cls_.eq("DAP"), 15, 1)))
TX = fut.pivot_table(index="date", columns="ticker", values="AdjstdQtTax").reindex(dias)
OI = fut.pivot_table(index="date", columns="ticker", values="OpnIntrst").reindex(index=dias, columns=TX.columns)
VENC = fut.drop_duplicates("ticker").set_index("ticker").venc


def vertice(cls, anos):
    """Taxa diária interpolada no prazo (anos) e o contrato mais próximo desse prazo (com contratos em aberto)."""
    cols = [c for c in TX.columns if c.startswith(cls)]
    v, tk = pd.Series(np.nan, index=dias), pd.Series(None, index=dias, dtype=object)
    T = pd.DataFrame({c: (VENC[c] - dias).days / 365.25 for c in cols}, index=dias)
    for d in dias:
        x, t, oi = TX.loc[d, cols], T.loc[d], OI.loc[d, cols].fillna(0)
        ok = x.notna() & (t > .08)
        if ok.sum() >= 3:
            o = np.argsort(t[ok].values)
            v[d] = np.interp(anos, t[ok].values[o], x[ok].values[o])
            liq = ok & (oi > 1000)
            if liq.any():
                tk[d] = (t[liq] - anos).abs().idxmin()
    return v, tk


print("vértices diários de juros...", flush=True)
dap5, tk_dap = vertice("DAP", 5)
di2, tk_di = vertice("DI1", 2)
di1a, _ = vertice("DI1", 1)
di5, _ = vertice("DI1", 5)


def ret_tk(tk):
    """Retorno do dia t do contrato escolhido no fechamento de t-1."""
    t = tk.shift(1)
    return pd.Series([F.at[d, c] if isinstance(c, str) and c in F.columns else np.nan for d, c in zip(dias, t)], index=dias)


r_dap, r_di = ret_tk(tk_dap), ret_tk(tk_di)

# sinais: (a) o mensal de antes, válido o mês seguinte inteiro; (b) diário com a mesma lógica (tendência de 21 dias, inclinação, ML)
sig_m = pd.read_csv(S / "sinal_juros.csv", index_col=0)
sig_m.index = pd.PeriodIndex(sig_m.index, freq="M")
incl = di5 - di1a
p_ml = lambda col: pj[col].reindex(mes - 1).set_axis(dias)                  # probabilidade do fim do mês anterior
sig_d = {col: ((np.sign(-(v - v.shift(21))).fillna(0) + np.sign(incl - incl.expanding(250).median()).fillna(0) + np.sign(p_ml(col) - .5).fillna(0)) / 3)
         .where(p_ml(col).notna()) for col, v in (("p_dap", dap5), ("p_di1", di2))}
pos = {"mensal": {c: sig_m[c].reindex(mes - 1).set_axis(dias) for c in ("p_dap", "p_di1")},
       "diário": {c: sig_d[c].shift(1) for c in ("p_dap", "p_di1")}}
ov = {k: {"dap": (v["p_dap"] * r_dap).fillna(0) - (v["p_dap"].diff().abs() * e.CUSTO_FUT).fillna(0),
          "di1": (v["p_di1"] * r_di).fillna(0) - (v["p_di1"].diff().abs() * e.CUSTO_FUT).fillna(0)} for k, v in pos.items()}

# ------------------------------------------------------------------ debêntures diárias
print("debêntures diárias...", flush=True)
snd = pd.read_parquet(DADOS / "snd_negocios.parquet")
snd = snd[snd.codigo.isin(cad.index) & snd.pct_curva.between(30, 150) & (snd.qtd * snd.pu_med >= 1e5)]
snd = snd.assign(w=snd.pct_curva * snd.qtd * snd.pu_med, f=snd.qtd * snd.pu_med)
P = (snd.groupby(["date", "codigo"]).w.sum() / snd.groupby(["date", "codigo"]).f.sum()).unstack().reindex(dias)
P = P[[c for c in P.columns if c in pn["D"].columns]]
Pi = np.exp(np.log(P).interpolate(limit=21, limit_area="inside"))
c = cad.loc[P.columns]
du = cdi.groupby(mes).transform("size")
cdi_aa = (1 + cdi.groupby(mes).transform(lambda s: (1 + s).prod() - 1)) ** (252 / du) - 1
ipca_d = (1 + pn["ipca_m"].reindex(mes).set_axis(dias)) ** (1 / du) - 1
pctdi = (c.indice == "DI") & c.pct.notna() & (c.pct != 100)
j = pd.Series(np.nan_to_num(c.juros) / 100, index=c.index)
G = pd.DataFrame(index=dias, columns=P.columns, dtype=float)
di_, ip, pr = (c.indice == "DI") & ~pctdi, c.indice == "IPCA", c.indice == "PRE"
G.loc[:, di_] = np.outer(1 + cdi, 1) * (1 + j[di_].values) ** (1 / 252)
G.loc[:, pctdi] = 1 + np.outer(cdi, c.pct[pctdi] / 100)
G.loc[:, ip] = np.outer(1 + ipca_d, 1) * (1 + j[ip].values) ** (1 / 252)
G.loc[:, pr] = np.outer(np.ones(len(dias)), (1 + j[pr].values) ** (1 / 252))
vivo = pd.DataFrame({k: dias < c.venc[k] for k in P.columns}, index=dias)
R = (Pi / Pi.shift(1) * G - 1).where(vivo)
R = R.where(R.abs() < .3)
Dd = pn["D"][P.columns].shift(1).reindex(mes).set_axis(dias)               # duration do fim do mês anterior

# hedge diário: contrato e razão escolhidos no fim do mês anterior (como no mensal), aplicados ao ajuste de cada dia
Hdd = pd.DataFrame(0.0, index=dias, columns=P.columns)
for m in pn["meses"][:-1]:
    dn = dias[mes == m + 1]
    if not len(dn):
        continue
    for idx, cl in (("IPCA", "DAP"), ("PRE", "DI1")):
        try:
            u = ult.loc[m]
        except KeyError:
            continue
        u = u[u.index.str.startswith(cl) & u.AdjstdQtTax.notna() & (u.OpnIntrst.fillna(0) > 1000)]
        Df = ((u.venc - fm[m]).dt.days / 365.25) / (1 + u.AdjstdQtTax / 100)
        Df = Df[Df > .25]
        cols = [k for k in c.index[c.indice.eq(idx)] if pd.notna(pn["D"].at[m, k])]
        if Df.empty or not cols:
            continue
        for k in cols:
            d = pn["D"].at[m, k]
            tk = (Df - d).abs().idxmin()
            if tk in F.columns:
                Hdd.loc[dn, k] = -(d / Df[tk]) * F.loc[dn, tk].fillna(0).values
hr = {}
for idx, col in (("IPCA", "p_dap"), ("PRE", "p_di1")):
    for k, v in pos.items():
        hr[(idx, k)] = (.5 - .75 * v[col]).clip(0, 1).fillna(1)
exc_hed = (R + Hdd).sub(cdi, axis=0)


def exc_din(modo):
    h = pd.DataFrame(1.0, index=dias, columns=P.columns)
    for idx in ("IPCA", "PRE"):
        cols = c.index[c.indice.eq(idx)]
        h.loc[:, cols] = np.outer(hr[(idx, modo)], np.ones(len(cols)))
    return (R + Hdd * h).sub(cdi, axis=0)


# ------------------------------------------------------------------ custo pela dispersão intradiária
print("custo de execução pelos negócios intradiários...", flush=True)
bal = pd.read_parquet(DADOS / "balcao.parquet", columns=["date", "tipo", "codigo", "taxa", "vol"])
bal = bal[bal.tipo.eq("DEB") & bal.taxa.notna() & (bal.vol >= 1e5)]
g = bal.groupby(["date", "codigo"])
bal["med"] = g.taxa.transform("median")
bal["n"] = g.taxa.transform("size")
disp = bal[bal.n >= 3].assign(dev=lambda x: (x.taxa - x.med).abs()).groupby(["date", "codigo"]).dev.median().rename("meio").reset_index()
ult_b = b.sort_values("mes").groupby("codigo")[["spread", "D"]].last()
disp = disp.join(ult_b, on="codigo").dropna()
disp = disp[disp.meio < 5]
faixa = pd.cut(disp.spread, [-9, 3, 8, 99], labels=["conservador", "moderado", "high yield"])
custo_fx = (disp.meio * disp.D.clip(.2, 8) / 100).groupby(faixa).median()  # custo de entrar OU sair, em % do preço
print((custo_fx * 100).round(3).to_dict(), "% por perna (mediana)")
CUSTO = {"cons": custo_fx["conservador"], "mod": custo_fx["moderado"], "hy": custo_fx["high yield"]}


# ------------------------------------------------------------------ eurobonds diários
print("eurobonds diários...", flush=True)
px = pd.read_parquet(DADOS / "eurobonds_precos.parquet").drop_duplicates(["date", "isin"], keep="last")
PE = px.pivot(index="date", columns="isin", values="preco").reindex(dias).ffill(limit=5)
PE = PE.where((PE >= 5) & (PE <= 160))
cup = cad_eb.cupom.reindex(PE.columns)
dt = pd.Series(np.r_[1, np.diff(dias).astype("timedelta64[D]").astype(float)], index=dias)
r_usd = (PE + np.outer(dt / 365, cup)) / PE.shift(1) - 1
r_usd = r_usd.where(r_usd.abs() < .3)
fx = ind.ptax.reindex(dias).ffill().pct_change()
tk_dol = pd.Series([min((x for x in F.columns if x.startswith("DOL") and pd.notna(F.at[d, x]) and VENC[x] > d + pd.Timedelta(days=5)), key=lambda x: VENC[x], default=None)
                    for d in dias], index=dias)
r_dol = ret_tk(tk_dol)
ust = lt.treasury()["UST"]
ud = sorted(ust[2])
curva = pd.Series([ust[2][ud[max(np.searchsorted(ud, d, side="right") - 1, 0)]] for d in dias], index=dias)
anos = pd.DataFrame({k: (cad_eb.venc[k] - dias).days / 365.25 for k in PE.columns}, index=dias)
y_m = (sprd_eb + 4.5).reindex(mes).set_axis(dias)[PE.columns]               # yield aproximado (spread + Treasury típico) só para a duration
Dm = ((1 - (1 + y_m / 200) ** (-2 * anos)) / (y_m / 100)).clip(upper=12)
yD = pd.DataFrame({k: [np.interp(a, *cv) / 100 if pd.notna(a) else np.nan for a, cv in zip(anos[k], curva)] for k in PE.columns}, index=dias)
y3 = pd.Series([np.interp(.25, *cv) / 100 for cv in curva], index=dias)
h_ust = -(yD.shift(1) / 252 - Dm.shift(1) * (yD - yD.shift(1)) - np.outer(y3.shift(1) / 252, np.ones(len(PE.columns))))
print("eurobonds com retorno diário:", int(r_dol.notna().sum()), "dias de DOL;", int(((1 + r_usd).mul(1 + fx, axis=0) - (1 + r_usd).mul(r_dol, axis=0)).notna().sum().sum()), "pontos")
exc_eb = ((1 + r_usd).mul(1 + fx, axis=0) - 1 - (1 + r_usd).mul(r_dol, axis=0) + h_ust.fillna(0)).sub(cdi, axis=0)


# ------------------------------------------------------------------ carteiras em tranches diárias
def tranches(sel, ret, lag, custo):
    """Sinal no fim do mês m -> entra LAG dias úteis depois, segura 63 dias; 3 tranches vivas; custo de ida e volta na troca."""
    pos_ = {m: dias.searchsorted(fm[m], side="right") + lag for m in sel}
    soma, n = pd.Series(0.0, index=dias), pd.Series(0, index=dias)
    ant = {}
    for m, nomes in sorted(sel.items()):
        i0 = pos_[m]
        if i0 >= len(dias):
            continue
        nomes = [k for k in nomes if k in ret.columns]
        cres = (1 + ret.iloc[i0:i0 + SEGURA][nomes].fillna(0)).cumprod()      # compra e segura: sem rebalancear todo dia
        val = cres.mean(axis=1)
        bloco = (val / val.shift(1).fillna(1) - 1).fillna(0)
        slot = m.ordinal % 3
        giro = len(set(nomes) ^ ant.get(slot, set())) / max(len(nomes), 1) if slot in ant else 1.0
        ant[slot] = set(nomes)
        bloco.iloc[0] -= giro * custo                                      # sai do papel antigo e entra no novo
        soma.iloc[i0:i0 + len(bloco)] += bloco.values
        n.iloc[i0:i0 + len(bloco)] += 1
    return (soma / n.where(n > 0)).fillna(0) * (n > 0)


lim = lambda lo, hi, dmax=10: (lambda x: x.spread.between(lo, hi) & (x.D <= dmax) & (x.fin > 2e5) & ~(x.ds3 > 1)
                                         & ~(x.get("acao_3m", pd.Series(0, index=x.index)).fillna(0) < -.25))
esc = lambda f_, n, col: {m: list(x[f_(x)].sort_values(col, ascending=False).drop_duplicates("empresa").head(n).codigo)
                          for m, x in b.groupby("mes") if m >= e.INICIO_ML}
corp = [k for k in cad_eb.index[~cad_eb.soberano] if k in sprd_eb.columns]
dP3 = np.log(PE).groupby(mes).last().diff(3)
emis = cad_eb.emissor.str.split().str[0]


def sel_eb(teto=None):
    out = {}
    for m in pn["meses"]:
        if m < e.INICIO_ML or m not in sprd_eb.index:
            continue
        x = sprd_eb.loc[m, corp].dropna().sort_values(ascending=False)
        if m in dP3.index:
            x = x[~(dP3.loc[m].reindex(x.index).fillna(0) < -.10)]
        x = x[~emis.loc[x.index].duplicated()]
        out[m] = list((x[x < teto] if teto else x).head(15).index)
    return out


def carteiras(modo="diário", lag=5, custo="intradiário", fin=.01):
    k = CUSTO if custo == "intradiário" else {"cons": .0015, "mod": .0015, "hy": .003}
    ed = exc_din(modo)
    cons = tranches(esc(lim(-1, 3, 5), 30, "score"), exc_hed, lag, k["cons"])
    mod = tranches(esc(lim(-1, 8), 25, "score"), ed, lag, k["mod"])
    hy = tranches(esc(lim(2, 40), 20, "spread"), ed, lag, k["hy"])
    eb, ebig = tranches(sel_eb(), exc_eb, lag, e.CUSTO_EXT), tranches(sel_eb(3), exc_eb, lag, e.CUSTO_EXT)
    o = ov[modo]
    return {"CDI+1 conservador": .8 * cons + .2 * ebig,
            "CDI+5 moderado": 2 * (.7 * mod + .3 * eb) - fin / 252 + 1.5 * o["dap"] + 1.0 * o["di1"],
            "CDI+10 arrojado": 3 * (.7 * hy + .3 * eb) - 2 * (fin + .005) / 252 + 3.0 * o["dap"] + 2.0 * o["di1"]}


INI = dias[dias.searchsorted(fm[e.INICIO_ML + 2], side="right")]


def met(x):
    x = x[x.index >= INI]
    c_ = cdi.reindex(x.index)
    r = 1 + c_ + x
    eq = r.cumprod()
    a, cc = r.prod() ** (252 / len(r)) - 1, (1 + c_).prod() ** (252 / len(r)) - 1
    return {"CDI + (pp a.a.)": (a - cc) * 100, "Retorno a.a. (%)": a * 100, "Vol a.a. (%)": r.std() * np.sqrt(252) * 100,
            "Sharpe": x.mean() / x.std() * np.sqrt(252), "Pior queda (%)": (eq / eq.cummax() - 1).min() * 100,
            "Pior dia (%)": x.min() * 100, "Dias acima do CDI (%)": (x > 0).mean() * 100}


print("rodando variantes...", flush=True)
base = carteiras()
linhas = []
for nome, kw in [("diário, sinal de juros diário, entra 5 dias depois, custo intradiário", {}),
                 ("diário, sinal de juros MENSAL (como antes)", {"modo": "mensal"}),
                 ("entra 1 dia depois", {"lag": 1}), ("entra 21 dias depois", {"lag": 21}),
                 ("custo fixo 0,15% (como antes)", {"custo": "fixo"}), ("funding CDI+2%", {"fin": .02})]:
    cart = base if not kw else carteiras(**kw)
    for k, v in cart.items():
        linhas.append({"variante": nome, "carteira": k, **met(v)})
tab = pd.DataFrame(linhas)
mensal = pd.read_csv(S / "metricas_carteiras.csv", index_col=0)
pd.set_option("display.width", 250)
print(tab.set_index(["variante", "carteira"]).round(2).to_string())
print("\nmensal (estrategias.py):", mensal.loc[list(base), ["CDI + (pp a.a.)", "Vol a.a. (%)", "Pior queda (%)"]].round(2).to_dict("index"))
tab.to_csv(S / "metricas_diario.csv", index=False)
pd.DataFrame(base).to_csv(S / "excessos_diarios.csv")

# gráfico
cores = {"CDI+1 conservador": "#003399", "CDI+5 moderado": "#EC7000", "CDI+10 arrojado": "#C0392B"}
x = dias[dias >= INI]
c_ = cdi.reindex(x)
fig, ax = plt.subplots(2, 1, figsize=(12, 9), gridspec_kw={"height_ratios": [3, 1.4]}, sharex=True)
ax[0].plot(x, (1 + c_).cumprod() * 100, "k--", lw=2, label="CDI")
for (k, v), alvo in zip(base.items(), (1, 5, 10)):
    eq = (1 + c_ + v.reindex(x)).cumprod()
    ax[0].plot(x, eq * 100, color=cores[k], lw=1.8, label=f"{k}  (CDI {met(v)['CDI + (pp a.a.)']:+.1f} pp a.a.)")
    ax[0].plot(x, ((1 + c_) * (1 + alvo / 100) ** (1 / 252)).cumprod() * 100, color=cores[k], lw=.9, ls=":")
    ax[1].plot(x, (eq / eq.cummax() - 1) * 100, color=cores[k], lw=1.3)
ax[0].set_title("Carteiras com marcação diária, sinal de juros diário e custo medido no intradiário (pontilhado = meta)", loc="left", fontweight="bold")
ax[0].legend(frameon=False, loc="upper left")
ax[1].set_title("Queda a partir do pico (%), diária", loc="left", fontweight="bold")
for a in ax:
    a.grid(alpha=.25)
    a.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(S / "carteiras_diario.png", dpi=140)
print("pronto")
