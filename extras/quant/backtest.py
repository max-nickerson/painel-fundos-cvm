"""
Cinco hipóteses de estratégia em renda fixa (crédito + juros) com dados públicos, backtest mensal 2019-2026 contra o CDI.

Retorno de cada debênture no mês (exato, sem aproximação de duration):
    r = (%PU da curva no fim do mês / %PU no início) x G - 1
    G = quanto o PU par andou no mês: CDI x (1+spread contratado) | % do CDI | IPCA x (1+taxa) | (1+taxa pré)
IPCA+ e prefixadas são protegidas com o futuro de DAP / DI1 de duration mais próxima (P&L real do ajuste diário da B3):
    r_hedge = r - (D_ativo / D_futuro) x retorno do futuro comprado no mês       -> CDI + spread + variação do spread
Custos: 0,15% sobre o volume girado em crédito, 0,01% em DI1. Execução realista: o sinal do fim do mês m só é executado
no fim de m+1 (o preço do último negócio de papel ilíquido não é executável; sem essa defasagem o backtest infla muito).

H1 Carry        compra o quintil de maior spread de mercado (hedgeado)
H2 Valor        compra o quintil mais barato contra a curva justa dos pares (resíduo de spread ~ duration, indexador, incentivada)
H3 Momentum     compra o quintil cujo spread mais fechou em 3 meses
H4 Juros (DI1)  CDI + DI1 de ~2 anos: recebe/paga conforme tendência de 3 meses e inclinação 5a-1a
H5 ML           gradient boosting prevê o excesso sobre o CDI do mês seguinte (treino só com o passado, refeito todo mês)
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
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

warnings.filterwarnings("ignore")
PASTA = Path(__file__).resolve().parent
DADOS, SAIDA = PASTA / "dados", PASTA / "resultado"
SAIDA.mkdir(exist_ok=True)
os.environ.setdefault("PAINEL_DADOS", str(Path(os.environ.get("LOCALAPPDATA", ".")) / "cvm_cache"))
sys.path.insert(0, r"C:\Users\maxpn\OneDrive\Documents\Personal\itau_database")
import lookthrough_cvm as lt  # noqa: E402

CUSTO_CRED, CUSTO_DI1, QUANTIL, MIN_NOMES, FIN_MIN = 0.0015, 0.0001, 0.2, 10, 1e5
MESES = "FGHJKMNQUVXZ"


# ------------------------------------------------------------------ dados mensais
def carrega():
    ind = pd.read_parquet(DADOS / "indices.parquet")
    ipca = pd.read_parquet(DADOS / "ipca.parquet").ipca
    cad = pd.read_parquet(DADOS / "snd_cadastro.parquet").set_index("codigo")
    snd = pd.read_parquet(DADOS / "snd_negocios.parquet")
    fut = pd.read_parquet(DADOS / "futuros.parquet")
    return ind, ipca, cad, snd, fut


def fins_de_mes(ind):
    d = ind.index.to_series()
    fm = d.groupby(d.dt.to_period("M")).max()
    return fm[fm.index < pd.Timestamp.today().to_period("M")]           # só meses completos


def futuros_mensal(fut, fm, ind):
    """Retorno mensal (comprado) de cada contrato e taxa/vencimento no fim de cada mês."""
    fut = fut.sort_values("AdjstdQt", na_position="first").drop_duplicates(["date", "ticker"], keep="last")
    fut = fut[fut.AdjstdQt.notna() & fut.PrvsAdjstdQt.gt(0)].copy()
    fut["e"] = fut.AdjstdQt / fut.PrvsAdjstdQt - 1
    fut["mes"] = fut.date.dt.to_period("M")
    ret = fut.groupby(["ticker", "mes"]).e.apply(lambda s: (1 + s).prod() - 1).unstack(0)
    cls, m, a = fut.ticker.str[:3], fut.ticker.str[3].map(MESES.index) + 1, 2000 + fut.ticker.str[4:6].astype(int)
    fut["venc"] = pd.to_datetime(dict(year=a, month=m, day=np.where(cls.eq("DAP"), 15, 1)))
    ult = fut[fut.date.isin(fm.values)].set_index(["mes", "ticker"])[["AdjstdQtTax", "venc", "OpnIntrst"]]
    return ret, ult


def taxa_vertice(ult, mes, classe, anos, data):
    """Taxa interpolada da curva de futuros no prazo (anos) no fim do mês."""
    try:
        x = ult.loc[mes]
    except KeyError:
        return np.nan
    x = x[x.index.str.startswith(classe) & x.AdjstdQtTax.notna()]
    t = (x.venc - data).dt.days / 365.25
    x, t = x[t > 0.08], t[t > 0.08]
    if len(x) < 3:
        return np.nan
    o = np.argsort(t.values)
    return float(np.interp(anos, t.values[o], x.AdjstdQtTax.values[o]))


def painel(ind, ipca, cad, snd, fm, fret, ult, tes):
    """Uma linha por debênture e fim de mês: %PU, spread, duration, liquidez, retorno do mês seguinte (bruto e com hedge)."""
    cad = cad[cad.indice.isin(["DI", "IPCA", "PRE"])]
    snd = snd[snd.codigo.isin(cad.index) & snd.pct_curva.between(30, 150) & (snd.qtd * snd.pu_med >= FIN_MIN)].copy()
    snd["fin"] = snd.qtd * snd.pu_med
    snd["mes"] = snd.date.dt.to_period("M")
    janela = snd[snd.date >= snd.mes.map(lambda p: fm.get(p, pd.NaT)) - pd.Timedelta(days=14)]   # últimas 2 semanas do mês
    pfim = janela.groupby(["mes", "codigo"]).apply(lambda g: np.average(g.pct_curva, weights=g.fin)).unstack()
    liq = snd.groupby(["mes", "codigo"]).agg(fin=("fin", "sum"), dias=("date", "nunique")).unstack()
    meses = pd.PeriodIndex(fm.index)
    P = pfim.reindex(meses)
    Pi = np.exp(np.log(P).interpolate(limit=6, limit_area="inside"))          # sem negócio: interpola até o próximo
    cdi = ind.cdi
    cdi_m = (1 + cdi).groupby(cdi.index.to_period("M")).prod().reindex(meses) - 1
    du = cdi.groupby(cdi.index.to_period("M")).size().reindex(meses)
    cdi_aa = (1 + cdi).groupby(cdi.index.to_period("M")).prod().pow(252 / cdi.groupby(cdi.index.to_period("M")).size()).reindex(meses) - 1
    ipca_m = ipca.groupby(ipca.index.to_period("M")).last().reindex(meses)
    linhas = []
    for i, m in enumerate(meses[:-1]):
        n = meses[i + 1]
        d0 = fm[m]
        obs = P.loc[m].dropna()
        hed = {}                                                              # futuros do mês para hedge: duration de cada contrato
        for cls in ("DAP", "DI1"):
            try:
                u = ult.loc[m]
                u = u[u.index.str.startswith(cls) & u.AdjstdQtTax.notna() & (u.OpnIntrst.fillna(0) > 1000)]
                hed[cls] = ((u.venc - d0).dt.days / 365.25) / (1 + u.AdjstdQtTax / 100)
            except KeyError:
                hed[cls] = pd.Series(dtype=float)
        for c, p0 in obs.items():
            k = cad.loc[c]
            if pd.isna(k.venc) or k.venc <= fm[n] + pd.Timedelta(days=90):
                continue
            T = (k.venc - d0).days / 365.25
            amort = k.cada_amort > 0 and pd.notna(k.carencia) and k.carencia < k.venc
            vida = (max((k.carencia - d0).days / 365.25, 0) + T) / 2 if amort else T
            pctdi = k.indice == "DI" and pd.notna(k.pct) and k.pct != 100
            j = (k.pct / 100 - 1) * cdi_aa[m] if pctdi else np.nan_to_num(k.juros) / 100
            y0 = {"DI": cdi_aa[m] + j, "IPCA": .065 + j, "PRE": j}[k.indice]
            D = min((1 - (1 + y0) ** -vida) / y0 if y0 > 0 else vida, 10)
            P0 = p0 / 100
            y = (1 + j) / P0 ** (1 / max(D, .1)) - 1                          # taxa de mercado implícita no %PU
            if k.indice == "DI":
                s = y * 100
            else:
                base = lt.curva(tes, "IPCA" if k.indice == "IPCA" else "PRE", d0, np.array([D]))[0]
                s = y * 100 - base
            p1 = Pi.loc[n, c] if pd.notna(Pi.loc[n, c]) else p0
            G = (1 + cdi_m[n]) * (1 + j) ** (du[n] / 252) if k.indice == "DI" and not pctdi else \
                (1 + cdi_m[n] * k.pct / 100) if pctdi else \
                (1 + ipca_m[n]) * (1 + j) ** (du[n] / 252) if k.indice == "IPCA" else (1 + j) ** (du[n] / 252)
            r = p1 / p0 * G - 1
            h, fut_tk = 0.0, ""
            if k.indice in ("IPCA", "PRE"):                                    # hedge com DAP / DI1
                Df = hed["DAP" if k.indice == "IPCA" else "DI1"]
                Df = Df[Df > 0.25]
                if len(Df):
                    fut_tk = (Df - D).abs().idxmin()
                    h = -(D / Df[fut_tk]) * fret.loc[n, fut_tk] if fut_tk in fret.columns and n in fret.index else np.nan
                else:
                    h = np.nan
            linhas.append(dict(mes=m, codigo=c, emissor=k.empresa, indice="%DI" if pctdi else k.indice, incentivada=bool(k.incentivada),
                               amortiza=amort, pct=p0, spread=s, j=j * 100, D=D, T=T, fin=liq["fin"].get(c, pd.Series()).get(m, 0),
                               dias=liq["dias"].get(c, pd.Series()).get(m, 0), proximo_obs=pd.notna(P.loc[n, c]),
                               r=r, hedge=h, r_hedge=r + h, cdi=cdi_m[n], fut=fut_tk))
    df = pd.DataFrame(linhas)
    df["exc"] = df.r_hedge - df.cdi
    return df.dropna(subset=["r_hedge"]), cdi_m


# ------------------------------------------------------------------ features
def features(df, ult, fm):
    df = df.sort_values(["codigo", "mes"]).copy()
    g = df.groupby("codigo")
    for k in (1, 3, 6):
        df[f"ds{k}"] = df.spread - g.spread.shift(k)
        df[f"dp{k}"] = np.log(df.pct) - np.log(g.pct.shift(k))
    df["vol6"] = g.exc.transform(lambda s: s.shift(1).rolling(6, min_periods=3).std())
    df["ret_ant"] = g.exc.shift(1)
    df["liq"] = np.log1p(df.fin)
    df["preco_par"] = df.pct - 100
    df["spread_vs_emissao"] = df.spread - df.j.where(df.indice.isin(["DI", "%DI"]))
    for c in ["DI", "%DI", "IPCA", "PRE"]:
        df["idx_" + c] = df.indice.eq(c).astype(int)
    m = df.groupby("mes")
    df["rank_spread"] = m.spread.rank(pct=True)
    df["mkt_ds1"] = m.ds1.transform("median")
    df["emissor_ds1"] = df.groupby(["mes", "emissor"]).ds1.transform("mean")
    df["emissor_n"] = df.groupby(["mes", "emissor"]).codigo.transform("size")
    # valor relativo: resíduo do spread contra a curva justa do mês (log duration, indexador, incentivada)
    df["residuo"] = np.nan
    for mes, x in df.groupby("mes"):
        X = np.column_stack([np.ones(len(x)), np.log(x.D.clip(.2)), x.incentivada, x.indice.eq("IPCA"), x.indice.eq("%DI")]).astype(float)
        ok = x.spread.between(-2, 15)
        if ok.sum() > 20:
            b = np.linalg.lstsq(X[ok.values], x.spread[ok].values, rcond=None)[0]
            df.loc[x.index, "residuo"] = x.spread - X @ b
    macro = pd.DataFrame({mes: {"di1_1a": taxa_vertice(ult, mes, "DI1", 1, fm[mes]), "di1_2a": taxa_vertice(ult, mes, "DI1", 2, fm[mes]),
                                "di1_5a": taxa_vertice(ult, mes, "DI1", 5, fm[mes]), "dap_5a": taxa_vertice(ult, mes, "DAP", 5, fm[mes])}
                          for mes in df.mes.unique()}).T.sort_index()
    macro["inclinacao"] = macro.di1_5a - macro.di1_1a
    macro["d_di1_2a_1m"], macro["d_di1_2a_3m"] = macro.di1_2a.diff(), macro.di1_2a.diff(3)
    macro["d_dap_5a_1m"] = macro.dap_5a.diff()
    return df.merge(macro, left_on="mes", right_index=True, how="left"), macro


FEATS = ["spread", "j", "pct", "preco_par", "spread_vs_emissao", "D", "T", "amortiza", "incentivada", "idx_DI", "idx_%DI", "idx_IPCA",
         "idx_PRE", "ds1", "ds3", "ds6", "dp1", "dp3", "dp6", "vol6", "ret_ant", "liq", "dias", "rank_spread", "mkt_ds1",
         "emissor_ds1", "emissor_n", "residuo", "di1_1a", "di1_2a", "di1_5a", "dap_5a", "inclinacao", "d_di1_2a_1m",
         "d_di1_2a_3m", "d_dap_5a_1m"]


# ------------------------------------------------------------------ estratégias
def defasa(df):
    """Execução realista: sinal no fim do mês m, compra no fim de m+1 (o preço do sinal não é executável)."""
    g = df.sort_values(["codigo", "mes"]).groupby("codigo")
    d = df.sort_values(["codigo", "mes"]).assign(r_hedge=g.r_hedge.shift(-1), cdi=g.cdi.shift(-1))
    return d.dropna(subset=["r_hedge"]).assign(exc=lambda x: x.r_hedge - x.cdi)


def carteira(df, sinal, nome, filtro=None, k=1):
    """A cada k meses escolhe o quintil de maior sinal (mínimo 10 nomes), pesos iguais; custo sobre o giro."""
    out, sel = {}, None
    for i, (mes, x) in enumerate(df.groupby("mes")):
        if i % k == 0 or sel is None:
            c = x[x[sinal].notna() & (filtro(x) if filtro else True)]
            if len(c) < MIN_NOMES * 2:
                continue
            novo = set(c.nlargest(max(MIN_NOMES, int(len(c) * QUANTIL)), sinal).codigo)
            giro, sel = (len(novo ^ sel) / len(novo) if sel else 1.0), novo
        else:
            giro = 0.0
        h = x[x.codigo.isin(sel)]
        if len(h):
            out[mes + 1] = {"r": h.r_hedge.mean() - giro * CUSTO_CRED, "cdi": x.cdi.iloc[0], "n": len(h), "giro": giro}
    return pd.DataFrame(out).T.assign(estrategia=nome)


def estrategia_di1(macro, fret, ult, fm, cdi_m):
    """CDI + DI1 de ~2 anos: +1 recebe (comprado em PU) / -1 paga, pela tendência de 3 meses e inclinação 5a-1a."""
    out, pos_ant = {}, 0
    meses = list(macro.index)
    for i, m in enumerate(meses[:-1]):
        n = meses[i + 1]
        x = macro.loc[m]
        if pd.isna(x.d_di1_2a_3m) or pd.isna(x.inclinacao):
            continue
        score = -np.sign(x.d_di1_2a_3m) + 0.5 * np.sign(x.inclinacao - macro.inclinacao.loc[:m].median())
        pos = np.sign(score)
        u = ult.loc[m]
        u = u[u.index.str.startswith("DI1") & u.AdjstdQtTax.notna()]
        tk = ((u.venc - fm[m]).dt.days / 365.25 - 2).abs().idxmin()
        e = fret.loc[n, tk] if tk in fret.columns else np.nan
        if pd.isna(e):
            continue
        out[n] = {"r": cdi_m[n] + pos * e - abs(pos - pos_ant) * CUSTO_DI1, "cdi": cdi_m[n], "n": 1, "giro": abs(pos - pos_ant), "pos": pos}
        pos_ant = pos
    return pd.DataFrame(out).T.assign(estrategia="H4 Juros DI1 (tendência + inclinação)")


def estrategia_ml(df, inicio="2021-01", atraso=2):
    """Walk-forward: a cada mês treina com tudo que já era conhecido (alvo = excesso do mês seguinte) e compra o top quintil."""
    df = df.copy()
    df["alvo"] = df.exc.clip(-0.2, 0.1)
    df["pred"] = np.nan
    meses = sorted(df.mes.unique())
    modelo = None
    for i, m in enumerate(meses):
        if m < pd.Period(inicio, "M"):
            continue
        treino = df[df.mes <= meses[i - atraso]] if i >= atraso else df.iloc[:0]  # só alvos já realizados no mês m
        if len(treino) < 2000:
            continue
        modelo = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=80,
                                               l2_regularization=1.0, random_state=0).fit(treino[FEATS], treino.alvo)
        x = df.mes == m
        df.loc[x, "pred"] = modelo.predict(df.loc[x, FEATS])
    teste = df[df.mes >= meses[-14]].dropna(subset=["exc"])
    imp = permutation_importance(modelo, teste[FEATS], teste.alvo, n_repeats=5, random_state=0)
    imp = pd.Series(imp.importances_mean, FEATS).sort_values(ascending=False)
    return carteira(df, "pred", "H5 Machine learning (gradient boosting)"), imp, df


# ------------------------------------------------------------------ métricas e gráficos
def metricas(r):
    m = r.set_index(r.index.astype(str))
    a = (1 + m.r).prod() ** (12 / len(m)) - 1
    c = (1 + m.cdi).prod() ** (12 / len(m)) - 1
    exc = m.r - m.cdi
    idx = (1 + m.r).cumprod()
    return {"Início": m.index[0], "Meses": len(m), "Retorno a.a. (%)": a * 100, "CDI a.a. (%)": c * 100, "% do CDI": a / c * 100,
            "Excesso a.a. (pp)": (a - c) * 100, "Vol. excesso a.a. (%)": exc.std() * np.sqrt(12) * 100,
            "Sharpe (excesso)": exc.mean() / exc.std() * np.sqrt(12) if exc.std() else np.nan,
            "Pior queda (%)": ((idx / idx.cummax()) - 1).min() * 100, "Meses acima do CDI (%)": (exc > 0).mean() * 100,
            "Nomes": m.n.mean(), "Giro mensal (%)": m.giro.iloc[1:].mean() * 100}


def graficos(res, cdi_m, imp):
    cores = {"CDI": "#2B2B2B", "Universo (todas, pesos iguais)": "#8C8C8C", "H1": "#EC7000", "H2": "#003399", "H3": "#2E9E5B",
             "H4": "#9B59B6", "H5": "#D62728"}
    ini = min(r.index.min() for r in res.values())
    fig, ax = plt.subplots(2, 1, figsize=(12, 10), gridspec_kw={"height_ratios": [3, 2]})
    cdi = cdi_m[cdi_m.index >= ini]
    ax[0].plot(cdi.index.to_timestamp(), (1 + cdi).cumprod() * 100, color=cores["CDI"], lw=2.2, ls="--", label="CDI")
    for nome, r in res.items():
        cor = cores.get(nome[:2], cores.get(nome, "#555"))
        r = r.reindex(cdi.index)
        eq = (1 + r.r.fillna(cdi)).cumprod() * 100
        exc = (1 + r.r.fillna(cdi)).cumprod() / (1 + cdi).cumprod() * 100 - 100
        ax[0].plot(cdi.index.to_timestamp(), eq, color=cor, lw=1.8, label=nome)
        ax[1].plot(cdi.index.to_timestamp(), exc, color=cor, lw=1.8)
    ax[0].set_title("Patrimônio (base 100) — estratégias x CDI", loc="left", fontweight="bold")
    ax[1].set_title("Excesso acumulado sobre o CDI (%)", loc="left", fontweight="bold")
    ax[1].axhline(0, color="#999", lw=1)
    ax[0].legend(frameon=False, fontsize=8.5, loc="upper left")
    for a in ax:
        a.grid(alpha=.25)
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(SAIDA / "curvas.png", dpi=140)
    fig, a = plt.subplots(figsize=(8, 7))
    imp.head(20)[::-1].plot.barh(ax=a, color="#EC7000")
    a.set_title("H5: importância das features (permutação, últimos 14 meses)", loc="left", fontweight="bold")
    a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(SAIDA / "features.png", dpi=140)


if __name__ == "__main__":
    ind, ipca, cad, snd, fut = carrega()
    fm = fins_de_mes(ind)
    fret, ult = futuros_mensal(fut, fm, ind)
    tes = lt.tesouro()
    print("montando o painel mensal...", flush=True)
    df, cdi_m = painel(ind, ipca, cad, snd, fm, fret, ult, tes)
    df, macro = features(df, ult, fm)
    df.to_parquet(SAIDA / "painel.parquet")
    print(f"{len(df)} linhas (debênture x mês), {df.codigo.nunique()} debêntures, {df.mes.nunique()} meses", flush=True)
    base = lambda x: x.spread.between(-2, 25)
    ingenuo = {"H1": carteira(df, "spread", "H1", base), "H2": carteira(df, "residuo", "H2", lambda x: x.spread.between(-2, 10))}
    df = defasa(df)                                                              # daqui em diante: execução realista
    uni = df[base(df)].groupby("mes").agg(r=("r_hedge", "mean"), cdi=("cdi", "first"), n=("codigo", "size")).assign(giro=0.0)
    uni.index = uni.index + 1                                                    # retorno pertence ao mês seguinte à formação
    res = {
        "Universo (todas, pesos iguais)": uni,
        "H1 Carry (spread alto, trimestral)": carteira(df, "spread", "H1", base, k=3),
        "H2 Valor relativo (barato x pares, trimestral)": carteira(df, "residuo", "H2", lambda x: x.spread.between(-2, 10), k=3),
        "H3 Momentum (spread fechando)": carteira(df.assign(mom=-df.ds3), "mom", "H3", base),
        "H4 Juros DI1 (tendência + inclinação)": estrategia_di1(macro, fret, ult, fm, cdi_m),
    }
    print("machine learning (walk-forward)...", flush=True)
    res["H5 Machine learning (gradient boosting)"], imp, dfp = estrategia_ml(df)
    print("ingênuo (preço do sinal executável, mensal):", {k: round(metricas(v)["% do CDI"], 1) for k, v in ingenuo.items()})
    tab = pd.DataFrame({k: metricas(v) for k, v in res.items()}).T
    tab.to_csv(SAIDA / "metricas.csv")
    pd.concat({k: v[["r", "cdi"]] for k, v in res.items()}, axis=1).to_csv(SAIDA / "retornos_mensais.csv")
    imp.to_csv(SAIDA / "importancia_features.csv")
    graficos(res, cdi_m, imp)
    pd.set_option("display.width", 250)
    print(tab.round(2).to_string())
    print(imp.head(15).round(5).to_string())
