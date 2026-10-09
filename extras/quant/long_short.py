"""
Estratégias long-short só com pontas vendidas negociáveis (debênture não tem aluguel na prática):
  LS0 (teste do sinal, não negociável) debêntures: quintil de cima - quintil de baixo do modelo de crédito
  LS1 crédito x ação: compra debêntures do quintil de cima, vende ações dos emissores do quintil de baixo (neutro em Ibovespa)
  LS2 eurobonds: compra o quintil de maior carrego (ou melhor momentum), vende o de menor carrego (ou pior momentum)
  LS3 curva DI1: comprado em PU no 5a e vendido no 2a (mesmo DV01) quando a inclinação está acima da mediana, e o contrário
  LS4 inflação implícita: comprado em DI1 5a e vendido em DAP 5a (mesmo DV01) quando a implícita está acima do Focus, e o contrário
Regras fixadas antes de rodar; execução 1 mês depois do sinal; custos; aluguel de 0,5% a.a. na ponta vendida.
Uso: python long_short.py   (depois de estrategias.py)
"""
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import estrategias as e

S = e.SAIDA
ALUGUEL, CUSTO_ACAO = .005 / 12, .001


def ls_tranches(longos, curtos, ret_l, ret_s, custo_l, custo_s):
    """Long-short em tranches de 3 meses: excesso da ponta comprada menos o da vendida, menos aluguel."""
    lo = e.tranches(longos, ret_l, 0, custo_l)
    sh = e.tranches(curtos, ret_s, 0, custo_s)
    return (lo - sh - ALUGUEL).dropna(), lo, sh


def futuro_mes(ult, fret, fm, meses, cls, anos):
    """Retorno mensal (comprado em PU) e duration do contrato de prazo mais próximo, escolhido no fim do mês anterior."""
    r, d = {}, {}
    for i, m in enumerate(meses[:-1]):
        n = meses[i + 1]
        try:
            u = ult.loc[m]
        except KeyError:
            continue
        u = u[u.index.str.startswith(cls) & u.AdjstdQtTax.notna() & (u.OpnIntrst.fillna(0) > 1000)]
        if u.empty or n not in fret.index:
            continue
        T = (u.venc - fm[m]).dt.days / 365.25
        tk = (T - anos).abs().idxmin()
        if tk in fret.columns and pd.notna(fret.at[n, tk]):
            r[n], d[n] = fret.at[n, tk], T[tk] / (1 + u.at[tk, "AdjstdQtTax"] / 100)
    return pd.Series(r), pd.Series(d)


def metr(x, nome):
    x = x.dropna()
    x = x[x.index >= e.INICIO_ML + 2]
    eq = (1 + x).cumprod()
    return {"estratégia": nome, "meses": len(x), "retorno a.a. (pp sobre o CDI)": ((1 + x).prod() ** (12 / len(x)) - 1) * 100,
            "vol a.a. (%)": x.std() * np.sqrt(12) * 100, "Sharpe": x.mean() / x.std() * np.sqrt(12),
            "pior queda (%)": (eq / eq.cummax() - 1).min() * 100, "meses positivos (%)": (x > 0).mean() * 100,
            "t": x.mean() / x.std() * np.sqrt(len(x))}


if __name__ == "__main__":
    pn, Hd, mx, pj, fret, ult, fm = pd.read_pickle(S / "cache_estrategias.pkl")
    meses, cdi_m = pn["meses"], pn["cdi_m"]
    b = pd.read_parquet(S / "credito_ml.parquet")
    exc_eb, sprd, cad_eb, exc_etf, dol = pd.read_pickle(S / "cache_ext.pkl")
    exc_hed = (pn["R"] + Hd.fillna(0)).sub(cdi_m, axis=0)
    res, series = [], {}

    # LS0 / LS1: crédito local
    q = lambda x, lado: x[x.spread.between(-1, 8) & (x.fin > 2e5)].sort_values("score", ascending=lado == "baixo") \
        .drop_duplicates("empresa").head(max(10, int(len(x) * .2 / 3)))
    topo = {m: list(q(x, "topo").codigo) for m, x in b.groupby("mes") if m >= e.INICIO_ML}
    fundo = {m: list(q(x, "baixo").codigo) for m, x in b.groupby("mes") if m >= e.INICIO_ML}
    ls0 = e.tranches(topo, exc_hed, 0, 0) - e.tranches(fundo, exc_hed, 0, 0)
    series["LS0 debêntures topo - fundo (teste do sinal, não negociável)"] = ls0
    acoes = pd.read_parquet(e.DADOS / "acoes.parquet").reindex(meses)
    ibov = pd.read_parquet(e.DADOS / "ibov.parquet").ibov.reindex(meses).pct_change()
    cnpj = pn["cad"].cnpj.astype(str).str.replace(r"\D", "", regex=True)
    acao_rel = acoes.sub(ibov, axis=0)                                           # ação do emissor contra o Ibovespa
    fundo_acao = {m: [cnpj[k] for k in v if cnpj.get(k) in acao_rel.columns] for m, v in fundo.items()}
    fundo_acao = {m: list(dict.fromkeys(v)) for m, v in fundo_acao.items()}
    curto_acao = e.tranches(fundo_acao, acao_rel, 0, CUSTO_ACAO)
    longo = e.tranches(topo, exc_hed, 0, e.CUSTO_CRED)
    series["LS1 crédito topo comprado / ações do fundo vendidas"] = (longo - curto_acao - ALUGUEL).dropna()
    series["  ponta vendida sozinha (ações do fundo vs Ibovespa, sinal invertido)"] = -curto_acao
    topo_acao = {m: list(dict.fromkeys(cnpj[k] for k in v if cnpj.get(k) in acao_rel.columns)) for m, v in topo.items()}
    series["  teste: ações do topo - ações do fundo"] = e.tranches(topo_acao, acao_rel, 0, 0) - curto_acao

    # LS2: eurobonds (com hedge de câmbio e juro americano)
    px = pd.read_parquet(e.DADOS / "eurobonds_precos.parquet").assign(mes=lambda x: x.date.dt.to_period("M"))
    Pm = px.sort_values("date").groupby(["mes", "isin"]).preco.last().unstack().reindex(meses)
    mom = np.log(Pm).diff(3)
    corp = [k for k in cad_eb.index[~cad_eb.soberano] if k in sprd.columns]
    emis = cad_eb.emissor.str.split().str[0]

    def pontas(sinal, n=8):
        lo, sh = {}, {}
        for m in meses:
            if m < e.INICIO_ML:
                continue
            x = sinal.loc[m, corp].dropna().sort_values(ascending=False)
            x = x[~emis.loc[x.index].duplicated()]
            if len(x) >= 2 * n:
                lo[m], sh[m] = list(x.head(n).index), list(x.tail(n).index)
        return lo, sh
    for nome, sinal in [("carrego", sprd), ("momentum 3m", mom)]:
        lo, sh = pontas(sinal)
        series[f"LS2 eurobonds {nome}"] = ls_tranches(lo, sh, exc_eb, exc_eb, e.CUSTO_EXT, e.CUSTO_EXT)[0]

    # LS3 / LS4: futuros
    r2, d2 = futuro_mes(ult, fret, fm, meses, "DI1", 2)
    r5, d5 = futuro_mes(ult, fret, fm, meses, "DI1", 5)
    rd, dd = futuro_mes(ult, fret, fm, meses, "DAP", 5)
    incl = mx.di1_5a - mx.di1_2a
    pos3 = np.sign(incl - incl.expanding(12).median()).shift(1)                   # decide no fim do mês anterior
    curva = (r5 - (d5 / d2) * r2) * pos3.reindex(r5.index)                        # +: comprado no 5a, vendido no 2a (mesmo DV01)
    series["LS3 curva DI1 5a x 2a (inclinação)"] = (curva / d5 * 2 - e.CUSTO_FUT * 2).dropna()  # escala: 2 anos de duration por ponta
    fc = pd.read_parquet(e.DADOS / "focus_ipca_completo.parquet")
    fm_ts = pd.Series(fm.values, index=pd.PeriodIndex(fm.index))
    focus12 = {}
    for m in meses:
        x = fc[fc.Data <= fm_ts[m]]
        if x.empty:
            continue
        x = x[x.Data == x.Data.max()]
        x = x[(x.ref > m) & (x.ref <= m + 12)]
        if len(x) >= 10:
            focus12[m] = ((1 + x.Mediana / 100).prod() - 1) * 100
    gap = (mx.di1_5a - mx.dap_5a) - pd.Series(focus12)
    pos4 = np.sign(gap - gap.expanding(12).median()).shift(1)                     # implícita cara -> vende implícita
    infl = (r5 - (d5 / dd) * rd) * pos4.reindex(r5.index)                         # comprado DI1 5a, vendido DAP 5a
    series["LS4 inflação implícita 5a (vs Focus)"] = (infl / d5 * 2 - e.CUSTO_FUT * 2).dropna()

    tab = pd.DataFrame([metr(v, k) for k, v in series.items()]).set_index("estratégia")
    pd.set_option("display.width", 220)
    print(tab.round(2).to_string())
    tab.to_csv(S / "metricas_long_short.csv")
    pd.DataFrame(series).to_csv(S / "long_short_mensal.csv")

    fig, ax = plt.subplots(figsize=(12, 6.5))
    cores = ["#8C8C8C", "#EC7000", "#003399", "#2E9E5B", "#9B59B6", "#C0392B"]
    principais = [k for k in series if not k.startswith("  ")]
    for k, c in zip(principais, cores):
        x = series[k].dropna()
        x = x[x.index >= e.INICIO_ML + 2]
        ax.plot(x.index.to_timestamp(), ((1 + x).cumprod() - 1) * 100, lw=2 if not k.startswith("LS0") else 1.3,
                ls="--" if k.startswith("LS0") else "-", color=c, label=k)
    ax.axhline(0, color="#999", lw=1)
    ax.set_title("Long-short: retorno acumulado acima do CDI (%), execução 1 mês depois do sinal, com custos", loc="left", fontweight="bold")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    ax.grid(alpha=.25)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(S / "long_short.png", dpi=140)
