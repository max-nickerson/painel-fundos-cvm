"""
As estratégias adaptadas ao que DÁ para operar como pessoa física nas suas contas, com custos de varejo:
  Rico  -> debêntures da prateleira: universo = papéis com negócios de varejo (ticket médio < R$ 100 mil) na B3;
           decide 1x por mês (nota do modelo ridge), compra pagando a "taxa da prateleira" (markup em pp de taxa x duration),
           segura >= 21 dias úteis (sem IOF), 1 papel por emissor.
  Clear / MetaTrader 5 -> juros pelo ETF FIXA11 (futuros de DI até 3 anos; histórico replicado com os futuros porque o do Yahoo é falho):
           comprado quando o DI 2 anos caiu mais que uma banda em 21 dias, zera quando subiu; senão Tesouro Selic (CDI).
  IBKR  -> eurobonds por sinal (livro da pesquisa) com custo de varejo, 1x ou 1,5x com margem em USD (SOFR + 1,5%),
           capital próprio protegido do câmbio (6L na CME / WDO).
Escolhas só na validação 2021-23; teste 2024-26. Retornos antes de IR.
Saídas: resultado/pessoal.csv, pessoal_diario.csv, pessoal.png
"""
import contextlib
import io
import itertools
import warnings

import matplotlib
import numpy as np
import pandas as pd
import requests

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import pesquisa_credito as pc

warnings.filterwarnings("ignore")
S, B, dias, cdi, D_ = pc.S, pc.B, pc.dias, pc.cdi, pc.D_
INI, VAL_FIM = pc.INI_OOS, pc.VAL_FIM
val, teste, o = dias[(dias >= INI) & (dias <= VAL_FIM)], dias[dias > VAL_FIM], dias[dias >= INI]
anual = lambda x: ((1 + x).prod() ** (252 / max(len(x), 1)) - 1) * 100
sh = lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() else -9
TICKET, N_RICO = 1e5, 15


# ------------------------------------------------------------------ universo de varejo (proxy da prateleira)
def universo_varejo():
    """Papel 'de varejo' no dia t: nos 63 dias úteis anteriores teve >= 10 dias com negócios de ticket médio < R$ 100 mil."""
    s = pd.read_parquet(D_ / "snd_negocios.parquet")
    s["ticket"] = s.qtd * s.pu_med / s.negocios.clip(lower=1)
    peq = s[(s.ticket < TICKET) & (s.negocios >= 2)].assign(v=1.0).pivot_table(index="date", columns="codigo", values="v", aggfunc="max")
    return peq.reindex(dias).fillna(0).rolling(63, min_periods=20).sum().shift(1).ge(10)


def nota_mensal(df, filtro, varejo, modelo="ridge"):
    """Nota (percentil) do modelo no 1o dia útil de cada mês, mantida o mês todo; só papéis de varejo."""
    d = df[filtro(df) & (df.date >= INI)]
    v = varejo.stack()
    v = v[v]
    v.index.names = ["date", "codigo"]
    d = d.join(v.rename("varejo"), on=["date", "codigo"])
    d = d[d.varejo.eq(True)]
    f = d.assign(f=d.groupby("date")[modelo].rank(pct=True)).pivot_table(index="date", columns="codigo", values="f").reindex(dias)
    mes = pd.Series(dias.to_period("M"), index=dias)
    decide = ~mes.duplicated()                                             # 1o dia útil do mês
    return f.where(decide, np.nan).ffill(limit=23), decide


exc = pc.excesso_sem_futuro()[0]
EC = B["P"].notna()
Dd = B["Dd"].reindex_like(exc).ffill().fillna(3)
df = pd.read_parquet(S / "credito_scores.parquet")
emissor = df.drop_duplicates("codigo").set_index("codigo").empresa.dropna().to_dict()


def simula_varejo(forca, decide, markup, entra=.8, sai=.5, segura=21, n_max=N_RICO, lag=2):
    """Livro de varejo: só decide nos dias de `decide`; custo por perna = markup (pp de taxa) x duration do papel."""
    F = forca.reindex(columns=exc.columns).shift(lag - 1).to_numpy()
    DEC = decide.shift(lag - 1, fill_value=False).to_numpy()
    E = EC.reindex(columns=exc.columns).fillna(False).to_numpy()
    R, C = exc.to_numpy(), (Dd.to_numpy() * markup / 100)
    em = np.array([emissor.get(c, c) for c in exc.columns])
    val_, desde, out, nav, ops = {}, {}, np.zeros(len(dias)), 1.0, 0
    for t in range(1, len(dias)):
        f, cd = F[t - 1], 0.0
        for k in list(val_):
            sumiu = np.isnan(R[max(t - 25, 0):t, k]).all()
            if sumiu or (DEC[t - 1] and not (f[k] >= sai) and t - desde[k] >= segura and E[t - 1, k]):
                cd += val_.pop(k) * (0 if sumiu else C[t, k])
                ops += 1
        if DEC[t - 1] or len(val_) < n_max // 2:
            eh = {em[k] for k in val_}
            cand = np.where((f >= entra) & E[t - 1])[0]
            for k in cand[np.argsort(-f[cand])]:
                livre = nav - sum(val_.values())
                if len(val_) >= n_max or livre <= 1e-9:
                    break
                if k in val_ or em[k] in eh:
                    continue
                val_[k], desde[k] = min(nav / n_max, livre), t
                eh.add(em[k])
                cd += val_[k] * C[t, k]
                ops += 1
        g = sum(v * (0.0 if np.isnan(R[t, k]) else R[t, k]) for k, v in val_.items())
        for k in val_:
            val_[k] *= 1 + (0.0 if np.isnan(R[t, k]) else R[t, k])
        out[t] = (g - cd) / nav
        nav *= 1 + out[t]
    simula_varejo.final = {exc.columns[k]: v / nav for k, v in val_.items()}
    return pd.Series(out, index=dias), ops / ((dias[-1] - INI).days / 365.25)


# ------------------------------------------------------------------ ETFs (Yahoo)
def yahoo(tk):
    j = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}.SA", params={"range": "10y", "interval": "1d"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()["chart"]["result"][0]
    s = pd.Series(j["indicators"]["adjclose"][0]["adjclose"], index=pd.to_datetime(j["timestamp"], unit="s").normalize(), name=tk)
    return s[~s.index.duplicated(keep="last")].dropna()


def fixa11_sintetico(taxa_adm=.003):
    """O Yahoo tem buracos (2024-25 parado, salto de 50% em 2026), então replica a regra do índice do FIXA11:
    DI1 de janeiro com vencimento de até 3 anos, rolado em junho e dezembro; excesso sobre o CDI = retorno do futuro - taxa."""
    F = B["F"]
    jan = {c: pd.Timestamp(2000 + int(c[-2:]), 1, 1) for c in F.columns if c.startswith("DI1F")}
    rola = pd.Series(dias.month.isin([6, 12]) & ~pd.Series(dias.to_period("M")).duplicated().values, index=dias)
    cur, out = None, []
    for d in dias:
        if cur is None or rola[d]:
            ok = [c for c, v in jan.items() if d + pd.DateOffset(months=6) < v <= d + pd.DateOffset(years=3)]
            cur = max(ok, key=jan.get) if ok else cur
        out.append(F[cur].get(d, np.nan) if cur else np.nan)
    return pd.Series(out, index=dias).fillna(0) - taxa_adm / 252


def etf_por_sinal(exc_etf, di2, banda_bps=0, custo=.002, lag=2):
    """Comprado no ETF quando o DI 2 anos caiu mais que `banda` em 21 dias, zera quando subiu mais que `banda` (histerese);
    decide no fechamento de t, executa em t+1, rende a partir de t+2; fora dele, Tesouro Selic (excesso 0)."""
    d21 = (di2 - di2.shift(21)) * 100
    alvo, cur = [], 0.0
    for x in d21.values:
        if x == x:
            cur = 1.0 if x < -banda_bps else 0.0 if x > banda_bps else cur
        alvo.append(cur)
    pos = pd.Series(alvo, index=dias).shift(lag - 1).fillna(0)
    return (pos.shift(1) * exc_etf).fillna(0) - pos.diff().abs().fillna(0) * custo, pos


if __name__ == "__main__":
    print("universo de varejo...", flush=True)
    varejo = universo_varejo()
    print(f"  papéis de varejo hoje: {int(varejo.iloc[-1].sum())} (de {int(EC.iloc[-63:].any().sum())} negociados no trimestre)", flush=True)
    res, series, finais = {}, {}, {}

    # Rico: grade pequena escolhida na validação (markup de 0,30 pp = realista para prateleira)
    print("Rico (debêntures de varejo)...", flush=True)
    for fx in ("conservador", "moderado"):
        forca, decide = nota_mensal(df, pc.FAIXAS[fx][0], varejo)
        for sai, seg in itertools.product((.5, .2, .1, 0), (21, 63)):
            for mk in (.15, .30, .50):
                r, ops = simula_varejo(forca, decide, mk, sai=sai, segura=seg)
                series[("Rico", fx, sai, seg, mk)] = r
                if mk == .30:
                    finais[("Rico", fx, sai, seg)] = simula_varejo.final
                res[("Rico", fx, sai, seg, mk)] = {"validação CDI+": anual(r.reindex(val)), "validação Sharpe": sh(r.reindex(val)),
                                                    "teste CDI+": anual(r.reindex(teste)), "teste Sharpe": sh(r.reindex(teste)), "operações/ano": ops}
                print(f"  {fx} sai<{sai} segura {seg}d markup {mk}pp: val CDI{anual(r.reindex(val)):+.2f} | teste CDI{anual(r.reindex(teste)):+.2f} | {ops:.0f} op/ano", flush=True)

    # Clear / MT5: FIXA11 (sintético a partir dos futuros) pelo sinal de tendência do DI 2 anos
    print("ETF de juros (FIXA11)...", flush=True)
    di2 = B["curvas"]["DI1_2a"]
    fixa = fixa11_sintetico()
    for banda in (0, 10, 25):
        r, pos = etf_por_sinal(fixa, di2, banda)
        k = ("Clear/MT5", "FIXA11", f"sinal banda {banda}bps")
        series[k] = r
        res[k] = {"validação CDI+": anual(r.reindex(val)), "validação Sharpe": sh(r.reindex(val)), "teste CDI+": anual(r.reindex(teste)),
                  "teste Sharpe": sh(r.reindex(teste)), "operações/ano": pos.diff().abs().reindex(o).sum() / len(o) * 252}
    series[("Clear/MT5", "FIXA11", "comprado sempre")] = fixa
    res[("Clear/MT5", "FIXA11", "comprado sempre")] = {"validação CDI+": anual(fixa.reindex(val)), "validação Sharpe": sh(fixa.reindex(val)),
                                                       "teste CDI+": anual(fixa.reindex(teste)), "teste Sharpe": sh(fixa.reindex(teste)), "operações/ano": 0}

    # IBKR: eurobonds por sinal com custo de varejo
    print("IBKR (eurobonds)...", flush=True)
    with contextlib.redirect_stdout(io.StringIO()):
        import estrategias_sinal as es
    for custo in (.0025, .005):
        eb, ops = es.livro(es.forca_eb(), es.ed.exc_eb, es.ed.PE, 15, custo, -9, es.emis_eb)
        eb = eb.reindex(dias).fillna(0)
        if custo == .0025:
            finais["IBKR"] = dict(es.livro.final)
        for alav in (1.0, 1.5):
            r = alav * eb - (alav - 1) * .015 / 252
            k = ("IBKR", f"eurobonds {alav:g}x", custo)
            series[k] = r
            res[k] = {"validação CDI+": anual(r.reindex(val)), "validação Sharpe": sh(r.reindex(val)), "teste CDI+": anual(r.reindex(teste)),
                      "teste Sharpe": sh(r.reindex(teste)), "operações/ano": ops / ((dias[-1] - dias[0]).days / 365.25)}

    tab = pd.DataFrame(res).T
    pd.set_option("display.width", 250)
    print(tab.round(2).to_string())
    tab.to_csv(S / "pessoal.csv")

    # escolhas na validação (markup 0,30 = realista)
    rico = {k: v for k, v in res.items() if k[0] == "Rico" and k[4] == .30}
    kr = max(rico, key=lambda k: rico[k]["validação Sharpe"])
    etf = {k: v for k, v in res.items() if k[0] == "Clear/MT5" and k[2].startswith("sinal")}
    ke = max(etf, key=lambda k: etf[k]["validação Sharpe"])
    print("\nescolhidos na validação:", kr, ke)
    esc = {"Rico: debêntures de varejo": series[kr], f"Clear/MT5: {ke[1]} por sinal": series[ke], "Clear/MT5: FIXA11 comprado sempre": series[("Clear/MT5", "FIXA11", "comprado sempre")],
           "IBKR: eurobonds 1x": series[("IBKR", "eurobonds 1x", .0025)], "IBKR: eurobonds 1,5x": series[("IBKR", "eurobonds 1.5x", .0025)]}
    # carteiras pessoais (pesos fixos, rebalanceadas todo dia: aproximação)
    esc["Pessoal conservadora (60 Rico / 20 IBKR 1x / 20 ETF)"] = .6 * esc["Rico: debêntures de varejo"] + .2 * esc["IBKR: eurobonds 1x"] + .2 * esc[f"Clear/MT5: {ke[1]} por sinal"]
    esc["Pessoal arrojada (50 Rico / 30 IBKR 1,5x / 20 ETF)"] = .5 * esc["Rico: debêntures de varejo"] + .3 * esc["IBKR: eurobonds 1,5x"] + .2 * esc[f"Clear/MT5: {ke[1]} por sinal"]
    resumo = pd.DataFrame({k: {"validação CDI+": anual(r.reindex(val)), "teste CDI+": anual(r.reindex(teste)), "total CDI+": anual(r.reindex(o)),
                               "Sharpe total": sh(r.reindex(o)),
                               "pior queda %": ((1 + cdi.reindex(o) + r.reindex(o)).cumprod() / (1 + cdi.reindex(o) + r.reindex(o)).cumprod().cummax() - 1).min() * 100}
                           for k, r in esc.items()}).T
    print("\n", resumo.round(2).to_string())
    resumo.to_csv(S / "pessoal_resumo.csv")
    pd.DataFrame(esc).to_csv(S / "pessoal_diario.csv")
    pd.to_pickle({"rico": kr, "etf": ke, "finais": finais}, S / "pessoal_escolhas.pkl")

    # gráfico
    c_ = cdi.reindex(o)
    cores = ["#003399", "#2E8B57", "#9DC3A6", "#7A5195", "#C0392B", "#EC7000", "#8B0000", "#8C8C8C"]
    fig, ax = plt.subplots(2, 1, figsize=(13, 11), gridspec_kw={"height_ratios": [2.3, 1]}, sharex=True)
    ax[0].axvspan(teste[0], teste[-1], color="#FFF4EA", zorder=0)
    ax[0].plot(o, (1 + c_).cumprod() * 100, "k--", lw=1.5, label="CDI")
    for (k, r), c in zip(esc.items(), cores):
        t = resumo.loc[k]
        lw = 2.6 if k.startswith("Pessoal") else 1.4
        ax[0].plot(o, (1 + c_ + r.reindex(o)).cumprod() * 100, color=c, lw=lw,
                   label=f"{k}: val CDI{t['validação CDI+']:+.1f} | teste CDI{t['teste CDI+']:+.1f} | queda {t['pior queda %']:.0f}%")
        eq = (1 + r.reindex(o)).cumprod()
        ax[1].plot(o, (eq / eq.cummax() - 1) * 100, color=c, lw=lw * .6)
    ax[0].set_title("O que dá para operar como pessoa física (custos de varejo) — fundo laranja = teste 2024-26", loc="center", fontweight="bold")
    ax[0].legend(frameon=False, fontsize=8.5, loc="upper left")
    ax[1].set_title("Queda contra o CDI (%)", loc="center", fontweight="bold")
    for a in ax:
        a.grid(alpha=.25)
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(S / "pessoal.png", dpi=130)
    print("pronto")
