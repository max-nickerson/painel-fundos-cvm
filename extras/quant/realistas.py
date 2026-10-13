"""
Estratégias REALISTAS para pessoa física (Rico, Clear, IBKR): poucas decisões, pouco giro, preços de execução de varejo,
históricos longos (15-24 anos) para ter significância. Regras definidas antes do teste; validação até 2016, teste 2017-2026.
  A) Tesouro tático (Rico/Clear, manual): Selic x Prefixado ~3a x IPCA+ ~6a, decisão mensal por carrego/valor + tendência de 3 meses.
     Compra no PU de compra e vende no PU de venda do próprio Tesouro Direto; custódia B3 0,20% a.a. Antes de IR.
  B) Tendência em minicontratos (Clear + MetaTrader 5, automático): WIN e WDO comprados/vendidos pela média dos sinais de
     1, 3 e 12 meses, cada um com 10% de vol-alvo; decisão semanal; capital fica no Tesouro Selic (overlay).
     Histórico: BOVA11 (retorno total) - CDI para o índice; PTAX - carrego (CDI - T-bill) para o dólar.
  C) Tendência global em ETFs (IBKR, automático): 11 ETFs; mensal; fica no ETF se o retorno de 12 meses bater o T-bill,
     peso inverso à volatilidade; o resto em T-bill. Com hedge do câmbio (6L), excesso sobre T-bill = excesso sobre o CDI.
Saídas: resultado/realistas.csv, realistas_diario.csv, realistas.png
"""
import io
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import requests
from arch.bootstrap import StationaryBootstrap

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
Q = Path(__file__).resolve().parent
D_, S = Q / "dados", Q / "resultado"
VAL_FIM = pd.Timestamp("2016-12-31")
CUST_TD = .002                                                            # custódia B3 do Tesouro Direto (a.a.)


def sgs(cod, ini="2000-01-01"):
    """Série do Banco Central em blocos de 10 anos."""
    out = []
    for a in range(pd.Timestamp(ini).year, pd.Timestamp.today().year + 1, 10):
        u = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados?formato=json&dataInicial=01/01/{a}&dataFinal=31/12/{a + 9}"
        j = requests.get(u, timeout=60).json()
        out.append(pd.DataFrame(j))
    d = pd.concat(out)
    return pd.Series(d.valor.astype(float).values, index=pd.to_datetime(d.data, dayfirst=True)).sort_index().pipe(lambda s: s[~s.index.duplicated()])


print("dados...", flush=True)
cdi = sgs(12) / 100                                                       # CDI diário (fração)
ptax = sgs(1)                                                             # dólar PTAX venda
y = pd.read_parquet(D_ / "yahoo_realistas.parquet")
dias = cdi.index[cdi.index >= "2002-01-01"]
tbill = (y["^IRX"].reindex(dias).ffill() / 100 / 252)                       # T-bill 3 meses, diário
anual = lambda x: ((1 + x).prod() ** (252 / max(len(x), 1)) - 1) * 100
sh = lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() else np.nan


# ------------------------------------------------------------------ A) Tesouro tático
def tesouro():
    t = pd.read_csv(D_ / "tesouro_direto.csv", sep=";", decimal=",")
    t["venc"] = pd.to_datetime(t["Data Vencimento"], dayfirst=True)
    t["data"] = pd.to_datetime(t["Data Base"], dayfirst=True)
    t = t[t["Tipo Titulo"].isin(["Tesouro Prefixado", "Tesouro IPCA+"])]
    t["anos"] = (t.venc - t.data).dt.days / 365.25
    return t


def tesouro_tatico(t, trend=63, alvo={"Tesouro Prefixado": (3, 1.5, 5), "Tesouro IPCA+": (6, 3, 10)}, valor=True, sempre=False):
    """Fim de cada mês: decide com as taxas do dia; executa no dia útil seguinte (PU de compra / PU de venda); rende no PU base."""
    ds = dias[dias >= t.data.min()]
    pu = {k: g.pivot_table(index="data", columns="venc", values="PU Base Manha").reindex(ds) for k, g in t.groupby("Tipo Titulo")}
    puc = {k: g.pivot_table(index="data", columns="venc", values="PU Compra Manha").reindex(ds) for k, g in t.groupby("Tipo Titulo")}
    puv = {k: g.pivot_table(index="data", columns="venc", values="PU Venda Manha").reindex(ds) for k, g in t.groupby("Tipo Titulo")}
    tx = {k: g.pivot_table(index="data", columns="venc", values="Taxa Compra Manha").reindex(ds) for k, g in t.groupby("Tipo Titulo")}
    # taxa de prazo constante (para o sinal): título com vencimento mais perto do alvo em cada dia
    def cm(k):
        a = alvo[k][0]
        T = np.array([(v - ds).days / 365.25 for v in tx[k].columns]).T
        X = tx[k].to_numpy()
        dist = np.where(np.isnan(X), np.inf, np.abs(T - a))
        i = dist.argmin(axis=1)
        return pd.Series(np.where(np.isfinite(dist.min(axis=1)), X[np.arange(len(ds)), i], np.nan), index=ds).ffill()
    taxa = {k: cm(k) for k in alvo}
    selic_aa = ((1 + cdi.reindex(ds).ffill()) ** 252 - 1) * 100
    fim_mes = pd.Series(ds.to_period("M"), index=ds)
    decide = fim_mes.ne(fim_mes.shift(-1))                                  # último dia útil do mês
    sinal = {}
    for k, s in taxa.items():
        caindo = s - s.shift(trend) < 0
        if k == "Tesouro Prefixado":
            barato = s > selic_aa                                           # carrego positivo: pré acima da Selic
        else:
            barato = s > s.rolling(756, min_periods=252).median()           # juro real acima da mediana de 3 anos
        sinal[k] = pd.Series(1.0, index=ds) if sempre else (caindo & (barato if valor else True)).astype(float)
    # simulação
    seg, out, ops = {}, np.zeros(len(ds)), 0                                # seg: {(tipo, venc): valor}
    c = cdi.reindex(ds).fillna(0).to_numpy()
    pendente = None
    for i in range(1, len(ds)):
        d = ds[i]
        # rende o dia
        r_dia, tot = 0.0, sum(seg.values())
        for (k, v), x in list(seg.items()):
            p0, p1 = pu[k].at[ds[i - 1], v], pu[k].at[d, v]
            r = p1 / p0 - 1 if p0 == p0 and p1 == p1 else c[i]
            if v <= d:                                                      # venceu: vira Selic
                r = c[i]
            seg[(k, v)] = x * (1 + r - CUST_TD / 252)
            r_dia += x * (r - CUST_TD / 252)
        caixa = 1 - tot
        r_dia += caixa * (c[i] - CUST_TD / 252 * 0)                        # Selic até R$ 10 mil sem custódia: ignora
        out[i] = r_dia - c[i]                                               # excesso sobre o CDI (base 1)
        tot_novo = sum(seg.values()) + caixa * (1 + c[i])
        seg = {kk: vv / tot_novo for kk, vv in seg.items()}
        # executa a decisão de ontem
        if pendente is not None:
            alvo_w = pendente
            pendente = None
            atual = {}
            for (k, v), x in seg.items():
                atual[k] = (v, x)
            novo = {}
            for k, w in alvo_w.items():
                if w <= 0:
                    continue
                a, lo, hi = alvo[k]
                if k in atual and lo <= (atual[k][0] - d).days / 365.25 <= hi:
                    novo[k] = (atual[k][0], w)                              # mantém o mesmo título
                else:
                    vs = [v for v in pu[k].columns if pu[k].at[d, v] == pu[k].at[d, v] and puc[k].at[d, v] == puc[k].at[d, v]]
                    if not vs:
                        continue
                    v = min(vs, key=lambda v: abs((v - d).days / 365.25 - a))
                    novo[k] = (v, w)
            custo = 0.0
            for (k, v), x in list(seg.items()):                            # vende o que sai ou reduz
                w_novo = novo[k][1] if k in novo and novo[k][0] == v else 0.0
                if x > w_novo + 1e-9:
                    pv, pb = puv[k].at[d, v], pu[k].at[d, v]
                    custo += (x - w_novo) * (1 - pv / pb if pv == pv and pb == pb else 0)
                    seg[(k, v)] = w_novo
                    ops += 1
            for k, (v, w) in novo.items():                                  # compra o que entra ou aumenta
                x = seg.get((k, v), 0.0)
                if w > x + 1e-9:
                    pc_, pb = puc[k].at[d, v], pu[k].at[d, v]
                    custo += (w - x) * (pc_ / pb - 1 if pc_ == pc_ and pb == pb else 0)
                    seg[(k, v)] = w
                    ops += 1
            seg = {kk: vv for kk, vv in seg.items() if vv > 1e-9}
            out[i] -= custo
        if decide[d]:
            ativos = [k for k in alvo if sinal[k].get(d, 0) == 1]
            pendente = {k: 1 / len(ativos) for k in ativos} if ativos else {}
    r = pd.Series(out, index=ds)
    return r, ops / ((ds[-1] - ds[0]).days / 365.25), pd.DataFrame(sinal)


# ------------------------------------------------------------------ B) tendência em minicontratos
def excesso_futuros():
    bova = y["BOVA11.SA"].reindex(dias).ffill(limit=5).pct_change(fill_method=None)
    win = (bova - cdi.reindex(dias)).where(dias >= "2008-12-01")
    dol = ptax.reindex(dias).ffill(limit=5).pct_change(fill_method=None)
    wdo = dol - (cdi.reindex(dias) - tbill)                                 # comprado em dólar futuro paga o carrego
    return pd.DataFrame({"WIN": win, "WDO": wdo})


def tendencia_minis(X, vol_alvo=.10, janelas=(21, 63, 252), freq="W-FRI", custo=.0002, lag=1):
    """Média dos sinais (+1/-1) de 1, 3 e 12 meses; posição = sinal x vol-alvo / vol de 63 dias (máx. 2x); decisão semanal."""
    cum = np.log1p(X.fillna(0)).cumsum()
    sig = sum(np.sign(cum - cum.shift(j)) for j in janelas) / len(janelas)
    vol = X.rolling(63, min_periods=40).std() * np.sqrt(252)
    pos = (sig * vol_alvo / vol).clip(-2, 2)
    per = pd.Series(X.index.to_period(freq), index=X.index)
    pos[~per.ne(per.shift(-1)).values] = np.nan                            # só o último dia útil da semana/mês decide
    pos = pos.ffill().shift(lag)                                           # decide no fechamento de sexta, executa na segunda
    r = (pos.shift(1) * X).sum(axis=1, min_count=1).fillna(0) - (pos.diff().abs() * custo).sum(axis=1)
    return r, pos


# ------------------------------------------------------------------ C) tendência global em ETFs
ETFS = ["SPY", "EFA", "EEM", "TLT", "IEF", "LQD", "HYG", "EMB", "GLD", "DBC", "VNQ"]


def tendencia_global(janela=252, custo=.0005, lag=1):
    p = y[ETFS].reindex(dias).ffill(limit=5)
    R = p.pct_change(fill_method=None)
    ex = R.sub(tbill, axis=0)
    mom = (np.log1p(ex.fillna(0)).rolling(janela, min_periods=janela).sum() > 0).astype(float).where(p.notna())
    iv = 1 / (R.rolling(63, min_periods=40).std())
    w = (mom * iv).div((iv.where(p.notna())).sum(axis=1), axis=0).fillna(0)  # peso inverso à vol entre TODOS; o que não passa vai p/ T-bill
    fim = pd.Series(dias.to_period("M"), index=dias)
    reb = fim.ne(fim.shift(-1))
    w = w.where(reb, np.nan).ffill().shift(lag).fillna(0)
    r = (w.shift(1) * ex).sum(axis=1).fillna(0) - (w.diff().abs() * custo).sum(axis=1)
    return r.where(dias >= "2008-02-01", 0), w


def estat(r, ini):
    x = r[r.index >= ini]
    v, t = x[x.index <= VAL_FIM], x[x.index > VAL_FIM]
    eq = (1 + x).cumprod()
    bs = np.array([anual(pd.Series(b[0][0])) for b in StationaryBootstrap(21, t.to_numpy(), seed=0).bootstrap(1000)])
    return {"início": f"{x.index[0]:%Y}", "validação CDI+": anual(v), "validação Sharpe": sh(v), "teste 2017-26 CDI+": anual(t),
            "teste Sharpe": sh(t), "teste t-stat": t.mean() / t.std() * np.sqrt(len(t)), "P(teste < CDI) %": (bs < 0).mean() * 100,
            "pior queda vs CDI %": (eq / eq.cummax() - 1).min() * 100}


if __name__ == "__main__":
    print("A) Tesouro tático...", flush=True)
    t = tesouro()
    res, series = {}, {}
    for nome, kw in {"A) Tesouro tático (valor + tendência 3m)": {}, "A') só tendência 3m": {"valor": False},
                     "A'') valor + tendência 6m": {"trend": 126}, "A''') valor + tendência 1m": {"trend": 21}}.items():
        r, ops, _ = tesouro_tatico(t, **kw)
        series[nome] = r
        res[nome] = estat(r, "2004-01-01") | {"operações/ano": ops}
        print(f"  {nome}: {res[nome]['validação CDI+']:+.2f} / {res[nome]['teste 2017-26 CDI+']:+.2f}", flush=True)
    for k, a_ in (("Tesouro Prefixado", (3, 1.5, 5)), ("Tesouro IPCA+", (6, 3, 10))):   # referência: sempre comprado
        r, ops, _ = tesouro_tatico(t, alvo={k: a_}, sempre=True)
        series[f"ref: sempre {k}"] = r
        res[f"ref: sempre {k}"] = estat(r, "2004-01-01") | {"operações/ano": ops}
    print("B) minicontratos...", flush=True)
    X = excesso_futuros()
    for nome, kw in {"B) Tendência WIN + WDO (semanal)": {}, "B') mensal": {"freq": "M"}, "B'') só 12 meses": {"janelas": (252,)}}.items():
        r, _ = tendencia_minis(X, **kw)
        series[nome] = r
        res[nome] = estat(r, "2004-01-01") | {"operações/ano": np.nan}
        print(f"  {nome}: {res[nome]['validação CDI+']:+.2f} / {res[nome]['teste 2017-26 CDI+']:+.2f}", flush=True)
    for k in ("WIN", "WDO"):
        r, _ = tendencia_minis(X[[k]])
        series[f"B) só {k}"] = r
        res[f"B) só {k}"] = estat(r, "2004-01-01" if k == "WDO" else "2009-06-01") | {"operações/ano": np.nan}
    print("C) ETFs globais...", flush=True)
    for nome, kw in {"C) Tendência global 12m (IBKR)": {}, "C') 6m": {"janela": 126}, "C'') 10m": {"janela": 210}}.items():
        r, w = tendencia_global(**kw)
        series[nome] = r
        res[nome] = estat(r, "2008-02-01") | {"operações/ano": np.nan}
        print(f"  {nome}: {res[nome]['validação CDI+']:+.2f} / {res[nome]['teste 2017-26 CDI+']:+.2f}", flush=True)
    # referências simples
    p = y[ETFS].reindex(dias).ffill(limit=5).pct_change(fill_method=None).sub(tbill, axis=0)
    series["ref: 60/40 SPY/IEF"] = (.6 * p.SPY + .4 * p.IEF).fillna(0)
    res["ref: 60/40 SPY/IEF"] = estat(series["ref: 60/40 SPY/IEF"], "2008-02-01") | {"operações/ano": np.nan}
    series["ref: Ibovespa (BOVA11) - CDI"] = X.WIN.fillna(0)
    res["ref: Ibovespa (BOVA11) - CDI"] = estat(series["ref: Ibovespa (BOVA11) - CDI"], "2009-06-01") | {"operações/ano": np.nan}
    # combinação: Tesouro tático com o capital, overlay de minis e 30% na IBKR
    comb = .7 * series["A) Tesouro tático (valor + tendência 3m)"].reindex(dias).fillna(0) + series["B) Tendência WIN + WDO (semanal)"] \
        + .3 * series["C) Tendência global 12m (IBKR)"]
    series["Combinada: 70% Tesouro tático + minis (overlay) + 30% IBKR"] = comb
    res["Combinada: 70% Tesouro tático + minis (overlay) + 30% IBKR"] = estat(comb, "2008-02-01") | {"operações/ano": np.nan}
    tab = pd.DataFrame(res).T
    pd.set_option("display.width", 250)
    print(tab.round(2).to_string())
    tab.to_csv(S / "realistas.csv")
    pd.DataFrame(series).to_csv(S / "realistas_diario.csv")

    # gráfico: as principais
    principais = ["A) Tesouro tático (valor + tendência 3m)", "B) Tendência WIN + WDO (semanal)", "C) Tendência global 12m (IBKR)",
                  "Combinada: 70% Tesouro tático + minis (overlay) + 30% IBKR", "ref: 60/40 SPY/IEF", "ref: Ibovespa (BOVA11) - CDI"]
    cores = ["#003399", "#2E8B57", "#7A5195", "#EC7000", "#8C8C8C", "#BFBFBF"]
    o = dias[dias >= "2008-02-01"]
    c_ = cdi.reindex(o).fillna(0)
    fig, ax = plt.subplots(2, 1, figsize=(13, 11), gridspec_kw={"height_ratios": [2.3, 1]}, sharex=True)
    for a in ax:
        a.axvspan(pd.Timestamp("2017-01-01"), o[-1], color="#FFF4EA", zorder=0)
    ax[0].plot(o, (1 + c_).cumprod() * 100, "k--", lw=1.5, label="CDI")
    for k, c in zip(principais, cores):
        r = series[k].reindex(o).fillna(0)
        t_ = tab.loc[k]
        lw = 2.6 if k.startswith("Combinada") else 1.5
        ax[0].plot(o, (1 + c_ + r).cumprod() * 100, color=c, lw=lw, ls=":" if k.startswith("ref") else "-",
                   label=f"{k}: val CDI{t_['validação CDI+']:+.1f} | teste CDI{t_['teste 2017-26 CDI+']:+.1f} (t {t_['teste t-stat']:.1f})")
        eq = (1 + r).cumprod()
        ax[1].plot(o, (eq / eq.cummax() - 1) * 100, color=c, lw=lw * .6, ls=":" if k.startswith("ref") else "-")
    ax[0].set_yscale("log")
    ax[0].set_title("Estratégias realistas para pessoa física (escala log) — fundo laranja = teste 2017-26", loc="center", fontweight="bold")
    ax[0].legend(frameon=False, fontsize=8.5, loc="upper left")
    ax[1].set_title("Queda contra o CDI (%)", loc="center", fontweight="bold")
    for a in ax:
        a.grid(alpha=.25)
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(S / "realistas.png", dpi=130)
    print("pronto")
