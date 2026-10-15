"""
AUDITORIA (red team) dos candidatos macro do top 5 — versões corrigidas.
  python ideias_aud_macro.py          -> roda os fundos auditados (com regimes executados em t+1) e salva resultado/ideias_aud_macro.pkl
  python ideias_aud_macro.py analise  -> só as tabelas de sensibilidade do caderno pesquisa/auditoria_macro.md
Correções (detalhe no caderno):
  1. Carry de moedas: carry por moeda realista (BRL medido no cupom cambial B3; NDF 50%; EM entregável -0,5 pp; TRY com haircut)
     e custo por tipo de moeda (G10 2 bps, EM 10, NDF 20, TRY 30) em vez de 3 bps para todas.
  2. Base cripto: capital 1,5-2x o nocional (margem que aguenta +50% sem liquidação) e perda esperada de contraparte (2,5% a.a. do alocado).
  3. Swap de variância vendido: strike VIX-1 / VIX-2, teto de vega por PL (perda de fev/2018 <= ~10% do PL).
  Regime: o dd_stop de regimes.py decide no fechamento de t-1 e já zera o retorno de t (execução no mesmo fechamento que gerou o sinal);
  aqui todo regime da própria curva é executado 1 dia depois (com_regime_t1).
"""
import copy
import pickle
import sys

import numpy as np
import pandas as pd

from base import BIS, CDI, CDI_AA, DIAS, DIAS_US, FXY, IDX, brl, limpa_fx, mensal, vol_alvo, D
from motor import Fundo, roda
import regimes as rg
import ideias_i_arb_comm as iac

# =============================================================== 1. CARRY DE MOEDAS COM CARRY REALISTA
MOEDA = {"EURUSD=X": ("XM", 1, "G10"), "GBPUSD=X": ("GB", 1, "G10"), "AUDUSD=X": ("AU", 1, "G10"), "NZDUSD=X": ("NZ", 1, "G10"),
         "JPY=X": ("JP", -1, "G10"), "CAD=X": ("CA", -1, "G10"), "CHF=X": ("CH", -1, "G10"), "NOK=X": ("NO", -1, "G10"),
         "SEK=X": ("SE", -1, "G10"), "MXN=X": ("MX", -1, "EM"), "ZAR=X": ("ZA", -1, "EM"), "PLN=X": ("PL", -1, "EM"),
         "HUF=X": ("HU", -1, "EM"), "CZK=X": ("CZ", -1, "EM"), "ILS=X": ("IL", -1, "EM"), "TRY=X": ("TR", -1, "TRY"),
         "INR=X": ("IN", -1, "NDF"), "IDR=X": ("ID", -1, "NDF"), "KRW=X": ("KR", -1, "NDF"), "CLP=X": ("CL", -1, "NDF"),
         "COP=X": ("CO", -1, "NDF"), "THB=X": ("TH", -1, "NDF"), "PHP=X": ("PH", -1, "NDF"), "CNY=X": ("CN", -1, "NDF"),
         "BRL=X": ("BR", -1, "BRL")}
CUSTO = {"G10": .0002, "EM": .0010, "NDF": .0020, "TRY": .0030, "BRL": .0010}


def carry_brl_b3():
    """Carry de quem fica comprado em real via DOL/NDF = CDI - cupom cambial (1º FRC, B3, 2019+), em fração a.a.
    Antes de 2019: Selic - FF (BIS) - 1,07 pp (spread médio medido do cupom curto sobre a SOFR em 2019+)."""
    from ideias_juros_fx import futuros
    x = futuros()
    fr = x[x.ticker.str.startswith("FRC") & x.AdjstdQtTax.notna() & (x.AdjstdQtTax != 0)].sort_values(["date", "venc"])
    cup = fr.groupby("date").AdjstdQtTax.first().reindex(DIAS).ffill(limit=5) / 100
    b3 = CDI_AA - cup
    i = BIS.reindex(DIAS).ffill()
    bis = (i["BR"] - i["US"]) / 100 - .0107
    return b3.combine_first(bis.where(b3.index < b3.first_valid_index()))


def carry_realista(try_hc=.5):
    """Diferencial anual por moeda (comprado na moeda vs USD) que um forward/NDF de fato paga."""
    i = BIS.reindex(DIAS_US).ffill()
    out = {}
    for k, (c, s, g) in MOEDA.items():
        if k not in FXY or c not in i:
            continue
        d = (i[c] - i["US"]) / 100
        if g == "EM":
            d = d - .005 * np.sign(d)                 # forward points pagam menos que a política (bid/ask + spread onshore)
        elif g == "NDF":
            d = d * .5
        elif g == "TRY":
            d = d * try_hc
        elif g == "BRL":
            b = carry_brl_b3()
            b = b.reindex(DIAS_US.union(b.index)).ffill().reindex(DIAS_US)
            d = b.combine_first(d * .7)
        out[k] = d
    return pd.DataFrame(out).reindex(DIAS_US)


def _fx_spot():
    v = pd.DataFrame({k: FXY[k] ** s for k, (c, s, g) in MOEDA.items() if k in FXY}).reindex(DIAS_US).ffill(limit=5)
    return v, limpa_fx(v.pct_change(fill_method=None))


def carry_aud(n=3, try_hc=.5, alvo=.08, teto=.25, custo_mult=1, lag=0, detalhe=False, dif=None):
    """Mesma máquina do '11 Carry de moedas global' (top/bottom n, inverso da vol, vol-alvo, teto depois do vol-alvo, mensal),
    mas o carry (sinal e acúmulo) é o realista por moeda e o custo depende do tipo de moeda."""
    v, spot = _fx_spot()
    dif = carry_realista(try_hc) if dif is None else dif
    dif = dif.reindex(columns=[c for c in dif.columns if c in v])
    R = (spot[dif.columns] + dif.shift(1) / 252).dropna(how="all")
    rk = dif.rank(axis=1, ascending=False)
    W = (rk <= n).astype(float) - ((rk > dif.notna().sum(axis=1).values[:, None] - n) & dif.notna()).astype(float)
    vol = spot[dif.columns].rolling(63, min_periods=40).std()
    W = (W / vol).div((W / vol).abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    W = mensal(vol_alvo(W, R[W.columns].fillna(0), alvo)).clip(-teto, teto)
    cst = {k: CUSTO[MOEDA[k][2]] for k in W.columns}
    return iac.para_brl(iac.executa(W, R[W.columns], cst, 0, 0, lag, custo_mult, detalhe, fin=0.0), detalhe)


# =============================================================== 2. BASE CRIPTO (PERPÉTUO) COM MARGEM E CONTRAPARTE
def base_aud(thr=.10, capital=2.0, perda_cp=.025, custo_mult=1, lag=0, detalhe=False):
    """carry_perp do IAC9 com capital = `capital` x nocional (1 spot + margem do short que aguenta alta de (capital-1)x100% sem
    liquidação, já que o spot na conta à vista não vale como margem do USDT-M) e perda esperada de contraparte `perda_cp` a.a. sobre
    o capital alocado na corretora (ex.: 5% a.a. de chance de um evento tipo FTX x 50% de perda). Nada do capital na corretora rende CDI."""
    F, S, P, V = iac.painel_perp()
    tb = iac.TB_AA.reindex(F.index, method="ffill").fillna(0)
    f7 = F.rolling(7, min_periods=7).sum() / 7 * 365
    liga, desl = f7.sub(tb, axis=0) > thr, f7.sub(tb, axis=0) < 0
    st = pd.DataFrame(0.0, index=F.index, columns=F.columns)
    for c in F.columns:
        on, x = False, np.zeros(len(F))
        L, Dl = liga[c].values, desl[c].values
        ok = (S[c].notna() & P[c].notna() & (V[c].rolling(30).median() > 5e7)).values
        for i in range(len(F)):
            if on and (Dl[i] or not ok[i]):
                on = False
            elif not on and L[i] and ok[i]:
                on = True
            x[i] = on
        st[c] = x
    W = st.div(st.sum(axis=1).clip(lower=1), axis=0).clip(upper=.4)
    R = (S / S.shift(1) - P / P.shift(1) + F) / capital - perda_cp / 365
    R = R.sub(tb / 365, axis=0).mask(S.isna() | P.isna() | S.shift(1).isna() | P.shift(1).isna(), 0.0)
    return iac.para_brl(iac.executa(W, R, .0015 / capital, 0, 0, lag, custo_mult, detalhe, fin=0.0), detalhe)


# =============================================================== 3. SWAP DE VARIÂNCIA VENDIDO, EXECUÇÃO E TAMANHO REALISTAS
def vol_aud(spread=.01, teto=.4, alvo=.08, custo_mult=1, lag=0, detalhe=False):
    """Vendido em swap de variância de 1 mês no S&P com strike = VIX - spread (bid do dealer), hedge de beta rolante, vol-alvo 8%,
    mas com teto de vega-nocional por PL `teto` (0,4 => o choque de 5/fev/2018, ~25 pontos de vol por 1 de vega, custa ~10% do PL)."""
    x = iac._cache(("vs_aud", spread), lambda: iac.var_swap(iac.px("^VIX"), iac.px("^GSPC"), iac.CAL, custo_vol=spread))
    h = iac.r_(iac.px("^GSPC"))
    b = iac.beta_n(x, h.to_frame("h"), 252)["h"].clip(-1, 2)
    Rr = (x - b * h).where(x.index >= x.ne(0).idxmax())
    v = Rr.rolling(126, min_periods=40).std().shift(1) * np.sqrt(252)
    W = (alvo / v).clip(upper=min(3, teto)).fillna(0).where(Rr.notna().cumsum() > 40, 0).to_frame("VS_EUA")
    return iac.para_brl(iac.executa(W, Rr.to_frame("VS_EUA"), .0041, 0, 0, lag, custo_mult, detalhe, fin=0.0), detalhe)


# =============================================================== regime com execução em t+1
def com_regime_t1(f, regimes=None, custo_troca=.001):
    """Igual a regimes.com_regime, mas o regime da própria curva (dd_stop, hmm_propria) é executado 1 dia depois do sinal."""
    regimes = regimes or rg.REG_PADRAO
    memo, base = {}, f.func

    def func(regime="nenhum", custo_mult=1, lag=0, **p):
        k = (tuple(sorted(p.items())), custo_mult, lag)
        if k not in memo:
            memo[k] = base(**p, custo_mult=custo_mult, lag=lag)
        e = memo[k]
        s = rg.serie_exposicao(e, regime)
        if regime in ("dd_stop", "hmm_propria"):
            s = s.shift(1).fillna(1.0)
        return e * s - s.diff().abs().fillna(0) * custo_troca * custo_mult

    g = copy.copy(f)
    g.func = func
    g.grade = {**f.grade, "regime": regimes}
    return g


FUNDOS = [
    Fundo("11 Carry de moedas global [auditado]", "Macro", "CDI",
          "Carry de moedas G10+EM, mas medido pelo que o forward/NDF paga de fato, não pela taxa de política do BIS",
          "Top/bottom n por carry realista (BRL = CDI - cupom FRC B3; NDF x0,5; EM entregável -0,5 pp; TRY x haircut), inverso da vol, "
          "vol-alvo 8%, teto 25%/moeda; custo G10 2 bps, EM 10, NDF 20, TRY 30", carry_aud,
          {"n": [3, 4], "try_hc": [.5, 0.0]}, inicio="2010-01-01", corte="2021-01-01"),
    Fundo("IAC9 Base cripto perpétuo [auditado]", "Arbitragem global", "CDI",
          "Financiamento dos perpétuos acima do T-bill paga quem fornece alavancagem — líquido de margem realista e de risco de corretora",
          "Spot x perpétuo USDT-M Binance (BTC, ETH, SOL, BNB, XRP, DOGE); capital 1,5-2x o nocional; perda esperada de contraparte 2,5% a.a.",
          base_aud, {"thr": [.05, .10], "capital": [1.5, 2.0]}, inicio="2020-01-01", corte="2023-01-01"),
    Fundo("IAC4 Variância EUA vendida [auditado]", "Volatilidade global", "CDI",
          "Prêmio de variância do S&P com beta vendido, executado ao bid do dealer e com tamanho que sobrevive a fev/2018",
          "Swap de variância 1m sintético, strike VIX-1 ou VIX-2, hedge de beta, vol-alvo 8% com teto de vega 0,25-0,4x PL",
          vol_aud, {"spread": [.01, .02], "teto": [.25, .4]}, inicio="2008-01-01", corte="2021-01-01"),
]


# =============================================================== análises do caderno
def _st(e, c, ini=None):
    e = e[e.index >= c] if ini is None else e[(e.index >= ini) & (e.index < c)]
    cdi = CDI.reindex(e.index)
    aa = ((1 + cdi + e).prod() ** (252 / len(e)) - (1 + cdi).prod() ** (252 / len(e))) * 100
    eq = (1 + cdi + e).cumprod()
    return {"ativo pp": round(aa, 2), "IR": round(e.mean() / e.std() * np.sqrt(252), 2), "DD %": round(((eq / eq.cummax()) - 1).min() * 100, 1)}


def analise(log=print):
    pd.set_option("display.width", 200)
    import fundos_global as fg
    # --- carry: decomposição e sensibilidade
    v, spot = _fx_spot()
    i = BIS.reindex(DIAS_US).ffill()
    bis = pd.DataFrame({k: (i[c] - i["US"]) / 100 for k, (c, s, g) in MOEDA.items() if k in v and c in i})
    real = carry_realista(.5)
    b3 = carry_brl_b3()
    log("BRL: BIS (Selic-FF) x carry B3 (CDI - cupom FRC), média anual pp")
    x = pd.DataFrame({"BIS": bis["BRL=X"].reindex(DIAS, method="ffill"), "B3": b3}).dropna()
    log((x.groupby(x.index.year).mean() * 100).round(2).T.to_string())
    lin = {}
    lin["original (carry_fx, BIS, NDF x0,7, 3 bps)"] = fg.carry_fx(3, 0, "ls")
    lin["BIS puro, custos por moeda"] = carry_aud(3, dif=bis)
    lin["realista, TRY x1"] = carry_aud(3, 1.0)
    lin["realista, TRY x0,5"] = carry_aud(3, .5)
    lin["realista, sem carry TRY (x0)"] = carry_aud(3, 0.0)
    lin["realista, sem TRY nenhuma"] = carry_aud(3, dif=real.drop(columns="TRY=X"))
    lin["realista, TRY x0,5, custo x2"] = carry_aud(3, .5, custo_mult=2)
    t = pd.DataFrame({k: {**{f"IS {a}": b for a, b in _st(e, "2021-01-01", "2010-01-01").items()},
                          **{f"OOS {a}": b for a, b in _st(e, "2021-01-01").items()}} for k, e in lin.items()}).T
    log("\nCarry de moedas (n=3, ls, sem regime): IS 2010-20 x OOS 2021+")
    log(t.to_string())
    # contribuição por moeda OOS da versão realista TRY 0,5
    ex, C, T = carry_aud(3, .5, detalhe=True)
    c = C[C.index >= "2021-01-01"].sum().sort_values()
    log("\nContribuição OOS por moeda (soma do excesso, pp), realista TRY x0,5:")
    log((c * 100).round(2).to_string())
    # --- dd_stop no mesmo fechamento x t+1
    log("\ndd_stop: executado no mesmo fechamento (regimes.py) x 1 dia depois")
    casos = {"11 Carry original": (fg.carry_fx(3, 0, "ls"), "2021-01-01", "2010-01-01"),
             "IAC4 VS_EUA original": (iac.premio_vol("VS_EUA", "sempre"), "2021-01-01", "2008-01-01"),
             "IAC9 perp original": (iac.base("perp", .10), "2023-01-01", "2020-01-01")}
    rows = {}
    for k, (e, c, i0) in casos.items():
        e = e[e.index >= i0]
        s0 = rg._dd_stop(e)
        for nm, s in (("nenhum", pd.Series(1.0, index=e.index)), ("dd_stop mesmo fech.", s0), ("dd_stop t+1", s0.shift(1).fillna(1))):
            ee = e * s - s.diff().abs().fillna(0) * .001
            rows[(k, nm)] = {**{f"IS {a}": b for a, b in _st(ee, c, i0).items()}, **{f"OOS {a}": b for a, b in _st(ee, c).items()}}
    log(pd.DataFrame(rows).T.to_string())
    # --- IAC4: strike e tamanho
    log("\nIAC4 swap de variância: strike x teto de vega (sem regime)")
    rows = {}
    for sp in (0.0, .01, .02):
        for te in (3.0, .4, .25):
            e = vol_aud(sp, te)
            rows[(f"VIX-{sp * 100:.0f}", f"teto {te}")] = {**{f"IS {a}": b for a, b in _st(e, "2021-01-01", "2008-01-01").items()},
                                                           **{f"OOS {a}": b for a, b in _st(e, "2021-01-01").items()},
                                                           "pior dia %": round(e.min() * 100, 1)}
    log(pd.DataFrame(rows).T.to_string())
    e = vol_aud(.01, .4)
    log("\nCaudas (VIX-1, teto 0,4): perda acumulada na janela, % do PL")
    for a, b in [("2018-01-29", "2018-02-16"), ("2020-02-20", "2020-03-31"), ("2024-07-29", "2024-08-09"), ("2025-03-31", "2025-04-17"),
                 ("2008-09-15", "2008-11-28"), ("2015-08-18", "2015-08-31")]:
        log(f"  {a} a {b}: {((1 + e[a:b]).prod() - 1) * 100:6.1f}%   pior dia {e[a:b].min() * 100:5.1f}%")
    # VIX - vol realizada seguinte (prêmio bruto)
    vix, spx = iac.px("^VIX"), iac.px("^GSPC")
    rv = np.log(spx).diff().rolling(21).std().shift(-21) * np.sqrt(252) * 100
    d = (vix - rv).dropna()
    log("\nVIX - vol realizada dos 21 dias seguintes (pontos de vol), média por ano:")
    log(d.groupby(d.index.year).mean().round(1).to_string())
    # --- IAC9
    log("\nIAC9 perp: capital x perda de contraparte (thr 10%)")
    rows = {}
    for cap in (1.25, 1.5, 2.0):
        for cp in (0.0, .025):
            e = base_aud(.10, cap, cp)
            rows[(cap, cp)] = {**{f"IS {a}": b for a, b in _st(e, "2023-01-01", "2020-01-01").items()},
                               **{f"OOS {a}": b for a, b in _st(e, "2023-01-01").items()}}
    log(pd.DataFrame(rows).T.to_string())
    F, S, P, V = iac.painel_perp()
    ex, C, T = iac.carry_perp(.10, 1.25, detalhe=True)
    W = pd.DataFrame(0.0, index=C.index, columns=C.columns)
    for _, r in T.iterrows():
        W.loc[r.entrada:r.saida, r.ativo] = r.peso_medio
    alloc = W.sum(axis=1)
    log(f"Fração do PL alocada (nocional x capital 1,25): média IS {alloc[:'2022'].mean() * 1.25:.2f}, OOS {alloc['2023':].mean() * 1.25:.2f}, "
        f"dias com posição OOS {(alloc['2023':] > 0).mean() * 100:.0f}%; máx {alloc.max() * 1.25:.2f}")
    for perda in (.2, .5):
        for cap in (1.25, 2.0):
            log(f"  Evento de corretora com perda de {perda:.0%} do alocado (capital {cap}x), alocação máxima OOS "
                f"{min(1, alloc['2023':].max() * cap):.0%} do PL: perda = {perda * min(1, alloc['2023':].max() * cap) * 100:.1f}% do PL")
    return t


if __name__ == "__main__":
    if sys.argv[1:2] == ["analise"]:
        analise()
        sys.exit()
    from rodar import BENCH
    res = []
    for f in FUNDOS:
        for nome_r, g in (("sem regime", f), ("regimes t+1", com_regime_t1(f))):
            r = roda(g, CDI, BENCH[f.benchmark], lambda *a: None)
            o, rb = r["oos"], r["rob"]
            print(f"{f.nome} [{nome_r}] | {r['params']} | IR IS {r['is_ir']:.2f} | OOS {o['retorno a.a. %']:.1f}% vs {o['benchmark a.a. %']:.1f}% "
                  f"(ativo {o['ativo a.a. pp']:+.1f}, IR {o['IR vs bench']:.2f}, DD {o['pior queda %']:.1f}%) | P {rb['P(bater bench OOS) %']:.0f}% "
                  f"| PBO {rb['PBO %']:.0f}% | x2 {rb['OOS custo x2 (pp)']:+.1f} | +1d {rb['OOS execução +1 dia (pp)']:+.1f}", flush=True)
            if nome_r == "regimes t+1":
                p = {k: v for k, v in r["params"].items() if k != "regime"}
                ex, C, T = f.func(**p, detalhe=True)
                r["contrib"], r["trades"], r["modulo"] = C, T, "ideias_aud_macro"
                r["fundo"].func = None
                res.append(r)
    pickle.dump(res, open(D.parent / "resultado" / "ideias_aud_macro.pkl", "wb"))
    print("pronto")
