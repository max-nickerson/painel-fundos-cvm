"""
Três carteiras-alvo (CDI+1, CDI+5, CDI+10) com machine learning, hedge dinâmico, exterior e alavancagem. Backtest mensal.

Peças:
  1. Painel mensal completo de debêntures (todas as datas entre o 1o e o último negócio): retorno sem hedge (aposta no PU),
     retorno do hedge com DAP/DI1 (P&L real dos futuros B3), spread, duration, liquidez. Sinais só com informação até o mês.
  2. Modelo de juros: probabilidade de o DAP 5a e o DI1 2a caírem em 3 meses (macro, Focus, EMBI, Treasury, fluxo de fundos).
     -> hedge dinâmico das IPCA+/prefixadas e posição direcional em futuros.
  3. Modelo de crédito: classifica cada debênture pela chance de ficar no terço de cima do excesso de 3 meses
     (rótulos só com preço negociado na entrada e na saída; execução 1 mês depois do sinal).
  4. Exterior: eurobonds de emissores brasileiros (FINRA) e ETFs de crédito EUA/Europa, com hedge cambial via DOL.
  5. Carteiras em tranches de 3 meses (1/3 renovado por mês), custos e financiamento da alavancagem.
Uso: python estrategias.py   (depois de dados.py, dados_extra.py e backtest.py)
"""
import os
import sys
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
PASTA = Path(__file__).resolve().parent
DADOS, SAIDA = PASTA / "dados", PASTA / "resultado"
os.environ.setdefault("PAINEL_DADOS", str(Path(os.environ.get("LOCALAPPDATA", ".")) / "cvm_cache"))
sys.path.insert(0, r"C:\Users\maxpn\OneDrive\Documents\Personal\itau_database")
sys.path.insert(0, str(PASTA))
import lookthrough_cvm as lt  # noqa: E402
from backtest import fins_de_mes, futuros_mensal, taxa_vertice  # noqa: E402

CUSTO_CRED, CUSTO_EXT, CUSTO_FUT = 0.0015, 0.0010, 0.0001
H = 3                    # meses de carregamento de cada tranche
INICIO_ML = pd.Period("2021-01", "M")


# ------------------------------------------------------------------ 1. painel completo de debêntures
def painel_completo(fm):
    ind = pd.read_parquet(DADOS / "indices.parquet")
    ipca = pd.read_parquet(DADOS / "ipca.parquet").ipca
    cad = pd.read_parquet(DADOS / "snd_cadastro.parquet").set_index("codigo")
    cad = cad[cad.indice.isin(["DI", "IPCA", "PRE"]) & cad.venc.notna()]
    snd = pd.read_parquet(DADOS / "snd_negocios.parquet")
    snd = snd[snd.codigo.isin(cad.index) & snd.pct_curva.between(30, 150) & (snd.qtd * snd.pu_med >= 1e5)].copy()
    snd["fin"], snd["mes"] = snd.qtd * snd.pu_med, snd.date.dt.to_period("M")
    meses = pd.PeriodIndex(fm.index)
    fim = snd.mes.map(lambda p: fm.get(p, pd.NaT))
    j2 = snd[snd.date >= fim - pd.Timedelta(days=14)]
    P = j2.assign(w=j2.pct_curva * j2.fin).groupby(["mes", "codigo"]).agg(w=("w", "sum"), f=("fin", "sum"))
    P = (P.w / P.f).unstack().reindex(meses)
    fin = snd.groupby(["mes", "codigo"]).fin.sum().unstack().reindex(meses).fillna(0)
    dias = snd.groupby(["mes", "codigo"]).date.nunique().unstack().reindex(meses).fillna(0)
    Pi = np.exp(np.log(P).interpolate(limit=6, limit_area="inside"))            # valorização entre negócios
    Pf = P.ffill(limit=6)                                                       # sinal: só o último preço conhecido
    c = cad.loc[P.columns]
    t_fim = pd.Series(fm.values, index=meses)
    vivo = pd.DataFrame({k: t_fim.values < c.venc.get(k) for k in P.columns}, index=meses)
    cdi = ind.cdi
    g = cdi.groupby(cdi.index.to_period("M"))
    cdi_m, du = (1 + cdi).groupby(cdi.index.to_period("M")).prod().reindex(meses) - 1, g.size().reindex(meses)
    cdi_aa = (1 + cdi_m) ** (252 / du) - 1
    ipca_m = ipca.groupby(ipca.index.to_period("M")).last().reindex(meses)
    pctdi = (c.indice == "DI") & c.pct.notna() & (c.pct != 100)
    j = np.where(pctdi, 0, np.nan_to_num(c.juros) / 100)
    jm = pd.DataFrame(np.tile(j, (len(meses), 1)), index=meses, columns=P.columns)
    jm.loc[:, pctdi.values] = np.outer(cdi_aa, c.pct[pctdi] / 100 - 1)
    G = pd.DataFrame(index=meses, columns=P.columns, dtype=float)
    dif = (c.indice == "DI") & ~pctdi
    G.loc[:, dif.values] = np.outer(1 + cdi_m, 1) * (1 + jm.loc[:, dif.values]) ** (du.values[:, None] / 252)
    G.loc[:, pctdi.values] = 1 + np.outer(cdi_m, c.pct[pctdi] / 100)
    ip = (c.indice == "IPCA").values
    G.loc[:, ip] = np.outer(1 + ipca_m, 1) * (1 + jm.loc[:, ip]) ** (du.values[:, None] / 252)
    pr = (c.indice == "PRE").values
    G.loc[:, pr] = (1 + jm.loc[:, pr]) ** (du.values[:, None] / 252)
    R = (Pi / Pi.shift(1) * G - 1).where(vivo)                                  # retorno do mês n (sem hedge)
    # duration e spread no fim de cada mês (com o último preço conhecido)
    T = pd.DataFrame({k: (c.venc[k] - t_fim).dt.days.values / 365.25 for k in P.columns}, index=meses).clip(lower=0)
    car = pd.DataFrame({k: ((c.carencia[k] - t_fim).dt.days.values / 365.25 if pd.notna(c.carencia[k]) else np.full(len(meses), np.nan))
                        for k in P.columns}, index=meses)
    amort = (c.cada_amort > 0) & c.carencia.notna() & (c.carencia < c.venc)
    vida = T.where(np.tile(~amort.values, (len(meses), 1)), (car.clip(lower=0) + T) / 2)
    y0 = pd.DataFrame(np.where(ip, .065, 0) + np.where(c.indice.eq("DI"), 1, 0) * cdi_aa.values[:, None], index=meses, columns=P.columns) + jm
    D = ((1 - (1 + y0) ** -vida) / y0).where(y0 > 0, vida).clip(upper=10)
    y = (1 + jm) / (Pf / 100) ** (1 / D.clip(lower=.1)) - 1
    tes = lt.tesouro()
    curva = lambda tipo, m: np.array([lt.curva(tes, tipo, fm[m], np.array([d]))[0] for d in D.loc[m]])
    S = y * 100
    for m in meses:
        if ip.any():
            S.loc[m, ip] = S.loc[m, ip] - curva("IPCA", m)[ip]
        if pr.any():
            S.loc[m, pr] = S.loc[m, pr] - curva("PRE", m)[pr]
    return dict(P=P, Pf=Pf, R=R, D=D, T=T, S=S, J=jm * 100, fin=fin, dias=dias, cad=c, cdi_m=cdi_m, cdi_aa=cdi_aa, meses=meses,
                ipca_m=ipca_m)


def hedges(pn, fret, ult, fm):
    """Retorno do mês n do hedge (vendido no futuro de duration igual) escolhido no fim de n-1, para IPCA (DAP) e PRE (DI1)."""
    c, D, meses = pn["cad"], pn["D"], pn["meses"]
    Hd = pd.DataFrame(0.0, index=meses, columns=D.columns)
    for i, m in enumerate(meses[:-1]):
        n = meses[i + 1]
        for idx, cls in (("IPCA", "DAP"), ("PRE", "DI1")):
            cols = c.index[c.indice.eq(idx)]
            try:
                u = ult.loc[m]
            except KeyError:
                continue
            u = u[u.index.str.startswith(cls) & u.AdjstdQtTax.notna() & (u.OpnIntrst.fillna(0) > 1000)]
            Df = ((u.venc - fm[m]).dt.days / 365.25) / (1 + u.AdjstdQtTax / 100)
            Df = Df[Df > .25]
            if Df.empty or n not in fret.index:
                continue
            for k in cols:
                d = D.at[m, k]
                if pd.notna(d):
                    tk = (Df - d).abs().idxmin()
                    Hd.at[n, k] = -(d / Df[tk]) * fret.at[n, tk] if tk in fret.columns and pd.notna(fret.at[n, tk]) else np.nan
    return Hd


# ------------------------------------------------------------------ 2. macro e modelo de juros
def macro(fm, ult, meses, cdi_aa, ipca_m):
    x = pd.DataFrame({m: {v: taxa_vertice(ult, m, cls, a, fm[m]) for v, cls, a in
                          [("di1_1a", "DI1", 1), ("di1_2a", "DI1", 2), ("di1_5a", "DI1", 5), ("dap_2a", "DAP", 2), ("dap_5a", "DAP", 5)]}
                      for m in meses}).T
    x["inclinacao"], x["implicita_5a"] = x.di1_5a - x.di1_1a, x.di1_5a - x.dap_5a
    x["cortes_1a"] = x.di1_1a - cdi_aa * 100
    focus = pd.read_parquet(DADOS / "focus_ipca.parquet").focus_ipca
    x["surpresa_ipca"] = (ipca_m - focus.reindex(meses)) * 100
    x["surpresa_ipca_3m"] = x.surpresa_ipca.rolling(3, min_periods=1).sum()
    x["ipca_12m"] = ((1 + ipca_m).rolling(12).apply(np.prod) - 1) * 100
    x["embi"] = pd.read_parquet(DADOS / "embi.parquet").embi.reindex(meses)
    ust = lt.treasury()["UST"]
    u10 = pd.Series({d: np.interp(10, *ust[2][d]) for d in ust[1]})
    x["ust10"] = u10.groupby(u10.index.to_period("M")).last().reindex(meses)
    ind = pd.read_parquet(DADOS / "indices.parquet")
    x["usdbrl"] = ind.ptax.groupby(ind.index.to_period("M")).last().reindex(meses)
    fl = pd.read_parquet(DADOS / "fluxos.parquet") if (DADOS / "fluxos.parquet").exists() else pd.DataFrame(index=meses)
    for c in ["fluxo_credito", "fluxo_infra"]:
        x[c] = fl[c].reindex(meses) * 100 if c in fl else np.nan
        x[c + "_3m"] = x[c].rolling(3, min_periods=1).sum()
    for c in ["di1_1a", "di1_2a", "di1_5a", "dap_2a", "dap_5a", "inclinacao", "implicita_5a", "embi", "ust10"]:
        x[f"d_{c}_1m"], x[f"d_{c}_3m"] = x[c].diff(), x[c].diff(3)
    x["fx_1m"], x["fx_3m"] = x.usdbrl.pct_change() * 100, x.usdbrl.pct_change(3) * 100
    return x.drop(columns=["usdbrl"])


def modelo_juros(mx):
    """Walk-forward: P(DAP 5a cai em 3 meses) e P(DI1 2a cai em 3 meses). Média de logística + gradient boosting."""
    feats = [c for c in mx.columns if mx[c].notna().mean() > .8 and "embi" not in c]   # EMBI parou em jul/2024 no Ipeadata
    out = pd.DataFrame(index=mx.index, columns=["p_dap", "p_di1"], dtype=float)
    for alvo, col in (("dap_5a", "p_dap"), ("di1_2a", "p_di1")):
        y = (mx[alvo].shift(-3) < mx[alvo]).astype(float).where(mx[alvo].shift(-3).notna())
        X = mx[feats].ffill().fillna(0)
        for i, m in enumerate(mx.index):
            if m < INICIO_ML:
                continue
            tr = mx.index[: max(i - 3, 0)]                                       # rótulo de 3 meses: só o que já venceu
            yt = y.loc[tr].dropna()
            if len(yt) < 18 or yt.nunique() < 2:
                continue
            lr = make_pipeline(StandardScaler(), LogisticRegression(C=0.2, max_iter=500)).fit(X.loc[yt.index], yt)
            gb = HistGradientBoostingClassifier(max_iter=100, max_depth=2, learning_rate=.05, min_samples_leaf=6).fit(X.loc[yt.index], yt)
            out.at[m, col] = (lr.predict_proba(X.loc[[m]])[0, 1] + gb.predict_proba(X.loc[[m]])[0, 1]) / 2
    return out


# ------------------------------------------------------------------ 3. modelo de crédito
def base_credito(pn, Hd, mx):
    """Linhas (debênture x mês do sinal) com features e rótulo de 3 meses com execução 1 mês depois."""
    P, Pf, R, S, D = pn["P"], pn["Pf"], pn["R"], pn["S"], pn["D"]
    c, meses, cdi_m = pn["cad"], pn["meses"], pn["cdi_m"]
    Rh = R + Hd.reindex_like(R).fillna(0)
    exc_h = Rh.sub(cdi_m, axis=0)
    fwd = sum(np.log1p(exc_h.shift(-k)) for k in (2, 3, 4))                    # entra no fim de m+1, sai no fim de m+4
    limpo = P.shift(-1).notna() & P.shift(-4).notna()
    acoes = pd.read_parquet(DADOS / "acoes.parquet") if (DADOS / "acoes.parquet").exists() else pd.DataFrame()
    cnpj = c.cnpj.astype(str).str.replace(r"\D", "", regex=True)
    linhas = []
    for k in P.columns:
        f = pd.DataFrame({"pct": Pf[k], "obs": P[k].notna(), "spread": S[k], "j": pn["J"][k], "D": D[k], "T": pn["T"][k],
                          "fin": pn["fin"][k], "dias": pn["dias"][k], "alvo": fwd[k], "limpo": limpo[k], "exc_h": exc_h[k]})
        f["ds1"], f["ds3"], f["ds6"] = f.spread.diff(), f.spread.diff(3), f.spread.diff(6)
        f["vol6"] = f.exc_h.shift(0).rolling(6, min_periods=3).std()
        f["ret1"], f["ret3"] = f.exc_h, f.exc_h.rolling(3).sum()
        f["meses_sem_negocio"] = (~f.obs).groupby(f.obs.cumsum()).cumsum()
        f["liq3"] = np.log1p(f.fin.rolling(3, min_periods=1).sum())
        if cnpj[k] in acoes.columns:
            a = acoes[cnpj[k]].reindex(meses)
            f["acao_1m"], f["acao_3m"], f["acao_6m"], f["acao_vol"] = a, (1 + a).rolling(3).apply(np.prod) - 1, \
                (1 + a).rolling(6).apply(np.prod) - 1, a.rolling(6).std()
        f["codigo"], f["mes"] = k, meses
        linhas.append(f[f.obs & f.spread.notna()])
    b = pd.concat(linhas, ignore_index=True)
    b = b.merge(c[["indice", "incentivada", "empresa", "pct", "cada_amort"]].rename(columns={"pct": "pct_di"}), left_on="codigo", right_index=True)
    b["pct_di"] = b.pct_di.where(b.indice.eq("DI") & b.pct_di.ne(100))
    b["spread_vs_emissao"] = b.spread - b.j
    b["preco_par"] = b.pct - 100
    for x in ["DI", "IPCA", "PRE"]:
        b["idx_" + x] = b.indice.eq(x).astype(int)
    b["incentivada"] = b.incentivada.astype(int)
    g = b.groupby("mes")
    b["rank_spread"], b["mkt_ds1"], b["mkt_ds3"] = g.spread.rank(pct=True), g.ds1.transform("median"), g.ds3.transform("median")
    b["emissor_ds3"] = b.groupby(["mes", "empresa"]).ds3.transform("mean")
    b["emissor_n"] = b.groupby(["mes", "empresa"]).codigo.transform("size")
    b["residuo"] = np.nan
    for m, x in b.groupby("mes"):
        X = np.column_stack([np.ones(len(x)), np.log(x.D.clip(.2)), x.incentivada, x.idx_IPCA, x.pct_di.notna()]).astype(float)
        ok = x.spread.between(-2, 15).values
        if ok.sum() > 30:
            coef = np.linalg.lstsq(X[ok], x.spread.values[ok], rcond=None)[0]
            b.loc[x.index, "residuo"] = x.spread - X @ coef
    b = b.merge(mx, left_on="mes", right_index=True, how="left")
    b["alvo_rank"] = b[b.limpo].groupby("mes").alvo.rank(pct=True)
    return b


FEATS_CRED = ["spread", "j", "spread_vs_emissao", "pct", "preco_par", "D", "T", "cada_amort", "incentivada", "idx_DI", "idx_IPCA",
              "idx_PRE", "ds1", "ds3", "ds6", "vol6", "ret1", "ret3", "meses_sem_negocio", "liq3", "dias", "rank_spread",
              "emissor_ds3", "emissor_n", "residuo", "acao_1m", "acao_3m", "acao_6m", "acao_vol", "carry_dur", "spread_rel_emissor", "distress"]


def modelo_credito(b):
    """Regressão walk-forward (erro absoluto, robusta a caudas) do excesso de 3 meses RELATIVO à média do mês: ordena os papéis.
    Só features do próprio papel (macro é igual para todos no mês e só atrapalha o ranking). Retreina a cada 3 meses."""
    b["carry_dur"] = b.spread / b.D.clip(.3)
    b["spread_rel_emissor"] = b.spread - b.groupby(["mes", "empresa"]).spread.transform("mean")
    b["distress"] = (b.pct < 85).astype(int)
    b["alvo_dm"] = b.alvo - b[b.limpo].groupby("mes").alvo.transform("mean")
    feats = [f for f in FEATS_CRED if f in b.columns]
    b["score"] = np.nan
    meses = sorted(b.mes.unique())
    modelo = None
    for i, m in enumerate(meses):
        if m < INICIO_ML:
            continue
        if modelo is None or i % 3 == 0:
            tr = b[(b.mes <= meses[i - 5]) & b.limpo & b.alvo_dm.notna()]            # rótulo vai até m+4: embargo de 5 meses
            modelo = HistGradientBoostingRegressor(loss="absolute_error", max_iter=300, learning_rate=.04, max_leaf_nodes=15,
                                                   min_samples_leaf=150, l2_regularization=1.0, random_state=0).fit(tr[feats], tr.alvo_dm.clip(-.1, .1))
        x = b.mes == m
        b.loc[x, "score"] = modelo.predict(b.loc[x, feats])
    te = b[(b.mes >= meses[-24]) & (b.mes <= meses[-5]) & b.limpo & b.alvo_dm.notna()]
    imp = permutation_importance(modelo, te[feats], te.alvo_dm.clip(-.1, .1), n_repeats=4, random_state=0, scoring="neg_mean_absolute_error")
    return b, pd.Series(imp.importances_mean, feats).sort_values(ascending=False)


# ------------------------------------------------------------------ 4. exterior: eurobonds e ETFs com hedge cambial
def dol_mensal(fret, ult, fm, meses):
    """Retorno mensal do DOL comprado (contrato mais curto vivo no fim do mês anterior)."""
    s = {}
    for i, m in enumerate(meses[:-1]):
        n = meses[i + 1]
        try:
            u = ult.loc[m]
        except KeyError:
            continue
        u = u[u.index.str.startswith("DOL") & (u.venc > fm[m] + pd.Timedelta(days=5))]
        if len(u) and n in fret.index:
            s[n] = fret.at[n, u.venc.idxmin()]
    return pd.Series(s)


def ytm(preco, cupom, anos):
    lo, hi = np.full(len(preco), -20.0), np.full(len(preco), 200.0)
    n = np.ceil(np.asarray(anos) * 2)
    for _ in range(60):
        yy = (lo + hi) / 2
        k = np.arange(1, max(n.max(), 1) + 1)[None, :]
        t = k - (n[:, None] - np.asarray(anos)[:, None] * 2)
        pv = cupom / 2 * ((1 + yy[:, None] / 200) ** -t * (k <= n[:, None])).sum(1) + 100 * (1 + yy / 200) ** -(np.asarray(anos) * 2) \
            - cupom / 2 * (n - np.asarray(anos) * 2)
        alto = pv > preco
        lo, hi = np.where(alto, yy, lo), np.where(alto, hi, yy)
    return (lo + hi) / 2


def hedge_ddi(Dm, fret, ult, fm, meses):
    """Retorno do mês n de vender DDI na duration de cada ativo (protege o juro em dólar), escolhido no fim de n-1."""
    out = pd.DataFrame(0.0, index=meses, columns=Dm.columns)
    for i, m in enumerate(meses[:-1]):
        n = meses[i + 1]
        try:
            u = ult.loc[m]
        except KeyError:
            continue
        u = u[u.index.str.startswith("DDI") & u.AdjstdQtTax.notna() & (u.OpnIntrst.fillna(0) > 1000)]
        Df = ((u.venc - fm[m]).dt.days / 365.25) / (1 + u.AdjstdQtTax / 100)
        Df = Df[Df > .25]
        if Df.empty or n not in fret.index:
            continue
        for k, d in Dm.loc[m].dropna().items():
            tk = (Df - d).abs().idxmin()
            if tk in fret.columns and pd.notna(fret.at[n, tk]):
                out.at[n, k] = -(d / Df[tk]) * fret.at[n, tk]
    return out


def hedge_ust(Dm, u, meses):
    """Retorno do mês n de vender Treasury (futuro de T-note) na duration de cada ativo, financiado no juro de 3 meses:
    -(y(D)/12 - D x variação de y(D) - y(3m)/12). Curva oficial do Tesouro americano."""
    out = pd.DataFrame(0.0, index=meses, columns=Dm.columns)
    for i, m in enumerate(meses[:-1]):
        n = meses[i + 1]
        if not u[m] or not u[n]:
            continue
        d = Dm.loc[m].dropna()
        y0, y1 = np.interp(d.values, *u[m]) / 100, np.interp(d.values, *u[n]) / 100
        out.loc[n, d.index] = -(y0 / 12 - d.values * (y1 - y0) - np.interp(.25, *u[m]) / 1200)
    return out


def exterior(fm, meses, dol, cdi_m, fret, ult):
    """Excesso mensal sobre o CDI (com hedge cambial) de cada eurobond e de cada ETF; sinal = carrego hedgeado."""
    ind = pd.read_parquet(DADOS / "indices.parquet")
    fx = ind.ptax.groupby(ind.index.to_period("M")).last().reindex(meses).pct_change()
    cad = pd.read_parquet(DADOS / "eurobonds_cadastro.parquet").set_index("isin")
    px = pd.read_parquet(DADOS / "eurobonds_precos.parquet")
    px["mes"] = px.date.dt.to_period("M")
    Pm = px.sort_values("date").groupby(["mes", "isin"]).preco.last().unstack().reindex(meses)
    Pm = Pm.where((Pm >= 5) & (Pm <= 160))
    cup = cad.cupom.reindex(Pm.columns)
    r_usd = (Pm + cup / 12) / Pm.shift(1) - 1                                    # preço + cupom corrido do mês
    r_usd = r_usd.where(r_usd.abs() < .5)
    hed = lambda r: (1 + r).mul(1 + fx, axis=0) - 1 - (1 + r).mul(dol.reindex(meses), axis=0)   # vendido em DOL no valor do ativo
    ust = lt.treasury()["UST"]
    anos = pd.DataFrame({k: (cad.venc[k] - pd.Series(fm.values, index=meses)).dt.days.values / 365.25 for k in Pm.columns}, index=meses)
    Y = pd.DataFrame(index=meses, columns=Pm.columns, dtype=float)
    for m in meses:
        ok = Pm.loc[m].notna() & (anos.loc[m] > .3)
        if ok.any():
            Y.loc[m, ok] = ytm(Pm.loc[m, ok].values, cup[ok].values, anos.loc[m, ok].values)
    u = {}
    for m in meses:
        d = [k for k in ust[1] if k <= fm[m]]
        u[m] = ust[2][d[-1]] if d else None
    Dmod = ((1 - (1 + Y / 200) ** (-2 * anos)) / (Y / 100)).where(Y > 0).clip(upper=12)       # duration modificada aprox.
    exc_eb = (hed(r_usd) + hedge_ust(Dmod, u, meses).reindex_like(r_usd).fillna(0)).sub(cdi_m, axis=0)
    sprd = Y - pd.DataFrame({k: [np.interp(a, *u[m]) if u[m] and pd.notna(a) else np.nan for m, a in zip(meses, anos[k])] for k in Pm.columns}, index=meses)
    g = pd.read_parquet(DADOS / "globais.parquet").reindex(meses)
    eur_usd = g["EURUSD=X"].pct_change()
    r_etf = g[["LQD", "HYG", "CEMB", "EMB"]].pct_change()
    for t in ["IHYG.L", "IEAC.L"]:                                               # euro com hedge para dólar: + (juro US - €STR)
        r_etf[t] = g[t].pct_change() + (u10_curto(meses, u) - g.estr.fillna(0)) / 12
    dur_etf = {"LQD": 8.3, "HYG": 3.2, "CEMB": 4.5, "EMB": 7.0, "IHYG.L": 3.0, "IEAC.L": 4.5}
    Detf = pd.DataFrame({k: np.full(len(meses), v) for k, v in dur_etf.items()}, index=meses)
    exc_etf = (hed(r_etf) + hedge_ust(Detf, u, meses)[r_etf.columns]).sub(cdi_m, axis=0)
    return exc_eb, sprd, cad, exc_etf


def u10_curto(meses, u):
    return pd.Series([np.interp(.25, *u[m]) / 100 if u[m] else np.nan for m in meses], index=meses)


# ------------------------------------------------------------------ 5. carteiras
def tranches(sinal_mes, ret_exc, n_nomes, custo):
    """sinal_mes: {mês do sinal: lista de ativos}. Entra no fim do mês seguinte e segura H meses; 1/H do livro renova por mês.
    Devolve o excesso mensal sobre o CDI (média das tranches vivas) já com custo de entrada/saída."""
    meses = ret_exc.index
    out, ant = {}, {}
    for i, n in enumerate(meses):
        rs = []
        for s in range(1, H + 1):
            j = i - 1 - s                                                        # sinal em j, entrada no fim de j+1, retorno a partir de j+2
            if j < 0 or meses[j] not in sinal_mes:
                continue
            nomes = [k for k in sinal_mes[meses[j]] if k in ret_exc.columns]
            r = ret_exc.loc[n, nomes].dropna()
            if len(r):
                giro = (len(set(nomes) ^ ant.get(s % H, set())) / max(len(nomes), 1)) if s == 1 else 0
                if s == 1:
                    ant[s % H] = set(nomes)
                rs.append(r.mean() - giro * custo)
        if rs:
            out[n] = np.mean(rs)
    return pd.Series(out)


def escolhe(b, filtro, n, col="score"):
    """Os n melhores pelo critério, no máximo 1 papel por emissor, sem papel cujo crédito está piorando
    (spread abriu mais de 1 pp em 3 meses ou ação do emissor caiu mais de 25% em 3 meses)."""
    ok = lambda x: filtro(x) & ~(x.ds3 > 1) & ~(x.get("acao_3m", pd.Series(0, index=x.index)).fillna(0) < -.25)
    return {m: list(x[ok(x)].sort_values(col, ascending=False).drop_duplicates("empresa").head(n).codigo)
            for m, x in b.groupby("mes") if m >= INICIO_ML}


def alavanca(exc, L, custo_fin):
    return L * exc - (L - 1) * custo_fin / 12


def metricas(exc, cdi_m, alvo):
    exc = exc.dropna()
    cdi = cdi_m.reindex(exc.index)
    r = (1 + cdi + exc)
    a, c = r.prod() ** (12 / len(r)) - 1, (1 + cdi).prod() ** (12 / len(r)) - 1
    eq = r.cumprod()
    return {"Início": str(exc.index[0]), "Meses": len(exc), "Retorno a.a. (%)": a * 100, "CDI a.a. (%)": c * 100,
            "CDI + (pp a.a.)": (a - c) * 100, "Meta CDI +": alvo, "% do CDI": a / c * 100, "Vol a.a. (%)": (cdi + exc).std() * np.sqrt(12) * 100,
            "Sharpe": exc.mean() / exc.std() * np.sqrt(12), "Pior queda (%)": (eq / eq.cummax() - 1).min() * 100,
            "Meses acima do CDI (%)": (exc > 0).mean() * 100}


if __name__ == "__main__":
    fut = pd.read_parquet(DADOS / "futuros.parquet")
    ind = pd.read_parquet(DADOS / "indices.parquet")
    fm = fins_de_mes(ind)
    fret, ult = futuros_mensal(fut, fm, ind)
    print("painel completo...", flush=True)
    pn = painel_completo(fm)
    meses, cdi_m = pn["meses"], pn["cdi_m"]
    Hd = hedges(pn, fret, ult, fm)
    mx = macro(fm, ult, meses, pn["cdi_aa"], pn["ipca_m"])
    print("modelo de juros...", flush=True)
    pj = modelo_juros(mx)
    print("modelo de crédito...", flush=True)
    b, imp = modelo_credito(base_credito(pn, Hd, mx))
    b.to_parquet(SAIDA / "credito_ml.parquet")

    # excesso mensal de cada debênture com hedge cheio, sem hedge e com hedge dinâmico (pelo modelo de juros)
    R, cad = pn["R"], pn["cad"]
    exc_sem = R.sub(cdi_m, axis=0)
    exc_hed = (R + Hd.fillna(0)).sub(cdi_m, axis=0)
    # sinal de juros (regra fixa, sem escolher o melhor depois): voto de tendência de 1 mês, inclinação e modelo ML, de -1 a +1
    sig = {}
    for alvo, col in (("dap_5a", "p_dap"), ("di1_2a", "p_di1")):
        sig[col] = ((np.sign(-mx[f"d_{alvo}_1m"]).fillna(0) + np.sign(mx.inclinacao - mx.inclinacao.expanding().median()).fillna(0)
                     + np.sign(pj[col] - .5).fillna(0)) / 3).where(pj[col].notna())
    pd.DataFrame(sig).to_csv(SAIDA / "sinal_juros.csv")
    hr = {}
    for idx, col in (("IPCA", "p_dap"), ("PRE", "p_di1")):
        hr[idx] = (.5 - .75 * sig[col].shift(1)).clip(0, 1).fillna(1)           # +1 (juro cai): sem hedge; -1: hedge cheio
    hr_m = pd.DataFrame(1.0, index=meses, columns=R.columns)
    for idx in ("IPCA", "PRE"):
        cols = cad.index[cad.indice.eq(idx)]
        hr_m.loc[:, cols] = np.outer(hr[idx], np.ones(len(cols)))
    exc_din = (R + Hd.fillna(0) * hr_m).sub(cdi_m, axis=0)

    # futuros direcionais: DAP 5a e DI1 2a recebidos/pagos conforme o modelo de juros
    def overlay(cls, anos, col):
        s = {}
        for i, m in enumerate(meses[:-1]):
            n, pos = meses[i + 1], sig[col].get(m)
            if pd.isna(pos):
                continue
            try:
                u = ult.loc[m]
            except KeyError:
                continue
            u = u[u.index.str.startswith(cls) & u.AdjstdQtTax.notna()]
            tk = ((u.venc - fm[m]).dt.days / 365.25 - anos).abs().idxmin()
            if tk in fret.columns and n in fret.index:
                s[n] = pos * fret.at[n, tk] - abs(pos) * CUSTO_FUT
        return pd.Series(s)
    ov_dap, ov_di1 = overlay("DAP", 5, "p_dap"), overlay("DI1", 2, "p_di1")

    dol = dol_mensal(fret, ult, fm, meses)
    print("exterior...", flush=True)
    exc_eb, sprd_eb, cad_eb, exc_etf = exterior(fm, meses, dol, cdi_m, fret, ult)
    corp = [k for k in cad_eb.index[~cad_eb.soberano] if k in sprd_eb.columns]
    # mesmas defesas do crédito local: 1 bond por emissor e não compra bond cujo preço caiu mais de 10% em 3 meses
    # (sem isso a carteira chegou a ter 8-10 bonds da Braskem e perdeu 28% em set/2025)
    px = pd.read_parquet(DADOS / "eurobonds_precos.parquet").assign(mes=lambda x: x.date.dt.to_period("M"))
    dP3 = np.log(px.sort_values("date").groupby(["mes", "isin"]).preco.last().unstack().reindex(meses)).diff(3)
    emis = cad_eb.emissor.str.replace(r"(?i)\s+(netherlands|finance|fuels|europe|lux|international|s\.?a\.?.*|bv|sapi|ltd|gmbh|trading|downstream).*$",
                                      "", regex=True).str.strip()

    def sel_ext(m, teto=None):
        x = sprd_eb.loc[m, corp].dropna().sort_values(ascending=False)
        x = x[~(dP3.loc[m, x.index].fillna(0) < -.10)]
        x = x[~emis.loc[x.index].duplicated()]
        return list((x[x < teto] if teto else x).head(15).index)
    sel_eb = {m: sel_ext(m) for m in meses if m >= INICIO_ML}
    sel_eb_ig = {m: sel_ext(m, 3) for m in meses if m >= INICIO_ML}
    eb_hy = tranches(sel_eb, exc_eb, 15, CUSTO_EXT)
    eb_ig = tranches(sel_eb_ig, exc_eb, 15, CUSTO_EXT)
    mom = exc_etf.rolling(6).sum()
    sel_etf = {m: list(mom.loc[m].dropna().nlargest(2).index) for m in meses if m >= INICIO_ML}
    etf = tranches(sel_etf, exc_etf, 2, 0.0005)

    # componentes de crédito local por perfil (ML) e referências sem ML
    lim = lambda lo, hi, dmax=10: (lambda x: x.spread.between(lo, hi) & (x.D <= dmax) & (x.fin > 2e5))
    comp = {
        "Universo (todas, hedge cheio)": tranches({m: list(x.codigo) for m, x in b.groupby("mes") if m >= INICIO_ML}, exc_hed, 0, 0),
        "Crédito conservador ML": tranches(escolhe(b, lim(-1, 3, 5), 30), exc_hed, 30, CUSTO_CRED),
        "Crédito conservador sem ML (carry)": tranches(escolhe(b, lim(-1, 3, 5), 30, "spread"), exc_hed, 30, CUSTO_CRED),
        "Crédito moderado ML (hedge dinâmico)": tranches(escolhe(b, lim(-1, 8), 25), exc_din, 25, CUSTO_CRED),
        "Crédito moderado ML (hedge cheio)": tranches(escolhe(b, lim(-1, 8), 25), exc_hed, 25, CUSTO_CRED),
        "Crédito arrojado ML (hy)": tranches(escolhe(b, lim(2, 40), 20), exc_din, 20, CUSTO_CRED * 2),
        "Crédito arrojado maior spread (hedge dinâmico)": tranches(escolhe(b, lim(2, 40), 20, "spread"), exc_din, 20, CUSTO_CRED * 2),
        "Eurobonds hedgeados (maior carrego)": eb_hy, "Eurobonds hedgeados (grau de investimento)": eb_ig,
        "ETFs crédito EUA/Europa hedgeados (momentum)": etf, "DAP 5a direcional (modelo de juros)": ov_dap,
        "DI1 2a direcional (modelo de juros)": ov_di1,
    }
    C = pd.DataFrame(comp).reindex(meses)
    C = C[C.index >= INICIO_ML + 2].fillna(0)
    carteiras = {
        "CDI+1 conservador": .8 * C["Crédito conservador ML"] + .2 * C["Eurobonds hedgeados (grau de investimento)"],
        "CDI+5 moderado": alavanca(.7 * C["Crédito moderado ML (hedge dinâmico)"] + .3 * C["Eurobonds hedgeados (maior carrego)"], 2.0, .01)
                          + 1.5 * C["DAP 5a direcional (modelo de juros)"] + 1.0 * C["DI1 2a direcional (modelo de juros)"],
        "CDI+10 arrojado": alavanca(.7 * C["Crédito arrojado maior spread (hedge dinâmico)"] + .3 * C["Eurobonds hedgeados (maior carrego)"], 3.0, .015)
                           + 3.0 * C["DAP 5a direcional (modelo de juros)"] + 2.0 * C["DI1 2a direcional (modelo de juros)"],
    }
    tab = pd.DataFrame({**{k: metricas(v, cdi_m, a) for (k, v), a in zip(carteiras.items(), (1, 5, 10))},
                        **{k: metricas(C[k], cdi_m, "") for k in C}}).T
    pd.set_option("display.width", 260)
    print(tab.round(2).to_string())
    print("acerto do modelo de juros (direção em 3 meses):",
          {c: round(((pj[col] > .5) == (mx[a].shift(-3) < mx[a])).loc[pj[col].notna() & mx[a].shift(-3).notna()].mean() * 100, 1)
           for c, col, a in (("DAP 5a", "p_dap", "dap_5a"), ("DI1 2a", "p_di1", "di1_2a"))})
    print(imp.head(15).round(4).to_string())
    tab.to_csv(SAIDA / "metricas_carteiras.csv")
    C.assign(**carteiras).to_csv(SAIDA / "excessos_mensais.csv")
    imp.to_csv(SAIDA / "importancia_credito.csv")
    pj.to_csv(SAIDA / "modelo_juros.csv")

    cores = {"CDI+1 conservador": "#003399", "CDI+5 moderado": "#EC7000", "CDI+10 arrojado": "#C0392B"}
    cdi = cdi_m.reindex(C.index)
    x = C.index.to_timestamp()
    fig, ax = plt.subplots(2, 1, figsize=(12, 10), gridspec_kw={"height_ratios": [3, 2]})
    ax[0].plot(x, (1 + cdi).cumprod() * 100, "k--", lw=2, label="CDI")
    for k, a in zip(carteiras, (1, 5, 10)):
        ax[0].plot(x, (1 + cdi + carteiras[k]).cumprod() * 100, color=cores[k], lw=2.2, label=k)
        ax[0].plot(x, ((1 + cdi) * (1 + a / 100) ** (1 / 12)).cumprod() * 100, color=cores[k], lw=1, ls=":", label=f"meta CDI+{a}")
    ax[0].set_title("Patrimônio (base 100): carteiras x CDI e metas", loc="left", fontweight="bold")
    ax[0].legend(frameon=False, fontsize=8.5, ncol=2, loc="upper left")
    for k, cor in [("Crédito moderado ML (hedge dinâmico)", "#EC7000"), ("Crédito moderado ML (hedge cheio)", "#F5B041"),
                   ("Crédito conservador ML", "#003399"), ("Crédito conservador sem ML (carry)", "#85A3E0"),
                   ("Universo (todas, hedge cheio)", "#8C8C8C"), ("Eurobonds hedgeados (maior carrego)", "#2E9E5B"),
                   ("ETFs crédito EUA/Europa hedgeados (momentum)", "#16A085"), ("DAP 5a direcional (modelo de juros)", "#9B59B6")]:
        ax[1].plot(x, ((1 + C[k]).cumprod() - 1) * 100, color=cor, lw=1.6, label=k)
    ax[1].axhline(0, color="#999", lw=1)
    ax[1].set_title("Componentes: excesso acumulado sobre o CDI (%)", loc="left", fontweight="bold")
    ax[1].legend(frameon=False, fontsize=7.5, ncol=2, loc="upper left")
    for a in ax:
        a.grid(alpha=.25)
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(SAIDA / "carteiras.png", dpi=140)
