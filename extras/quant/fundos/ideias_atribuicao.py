"""
Fundos melhorados a partir da atribuição dos vencedores da rodada 1 (ver pesquisa/atribuicao.md).
  A1 Carry G10+LatAm com teto real e stop de crash  — o carry original era 55-75% lira turca porque o teto de 25% era aplicado ANTES do vol-alvo.
  A2 Eurobonds BR em stress (compra entre lo e 85, sai em 97) — o ganho do F06 veio de bonds comprados a 70-80 em 2023 que voltaram ao par.
  A3 Put-write com hedge de beta — o F15 era 0,76 x S&P: aqui o beta é vendido em SPY para isolar o prêmio de volatilidade.
  A4 Termo conservador — trava a MENOR taxa entre fechamento e VWAP à vista (o F02 original vivia de ruído de horário).
Uso: PYTHONIOENCODING=utf-8 python -W ignore ideias_atribuicao.py   -> resultado/ideias_atribuicao.pkl
"""
import pickle

import numpy as np
import pandas as pd

import atribuicao_fundos as af
import fundos_global as fg
from base import CDI, DIAS, DIAS_US, ETF, IDX, TB_US, brl, carteira, limpa, mensal, vol_alvo
from motor import Fundo, roda

OUT = af.OUT
G10 = ["EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X", "JPY=X", "CAD=X", "CHF=X", "NOK=X", "SEK=X"]
UNIV = {"G10+LatAm": G10 + ["MXN=X", "BRL=X", "CLP=X", "COP=X"],
        "todas sem TRY": [k for k in fg.MOEDA if k != "TRY=X"]}


# ---------------------------------------------------------------- A1 carry com teto real e stop de crash
def _carry(univ="G10+LatAm", stop=1, n=3, alvo=.08, teto_pl=.25, lag=0, custo_mult=1):
    v, spot, dif = fg._fx()
    cols = [c for c in UNIV[univ] if c in dif]
    v, spot, dif = v[cols], spot[cols], dif[cols]
    car = dif.shift(1) / 252
    R = (spot + car).dropna(how="all")
    rk = dif.rank(axis=1, ascending=False)
    W = (rk <= n).astype(float) - ((rk > dif.notna().sum(axis=1).values[:, None] - n) & dif.notna()).astype(float)
    vol = spot.rolling(63, min_periods=40).std()
    W = (W / vol).div((W / vol).abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    W = vol_alvo(mensal(W), R[cols], alvo).clip(-teto_pl, teto_pl)        # teto DEPOIS do vol-alvo: nenhuma moeda passa de 25% do PL
    if stop:                                                              # moeda andou > 2 desvios contra em 10 dias: zera até o fim do mês
        lv = np.log(v)
        contra = np.sign(W) * (lv - lv.shift(10)) < -2 * vol * np.sqrt(10)
        mes = pd.Series(W.index.to_period("M"), index=W.index)
        trava = contra.astype(int).groupby(mes.values).cummax().astype(bool)
        W = W.where(~trava, 0)
    return W, R[cols]


def carry_g10latam(univ="G10+LatAm", stop=1, custo_mult=1, lag=0):
    W, R = _carry(univ, stop, lag=lag)
    alav = (W.abs().sum(axis=1) - 1).clip(lower=0).shift(2).fillna(0) * .005 / 252
    return brl(carteira(W, R, fg.C_FX * custo_mult, lag) - alav)


def carry_partes(univ, stop):
    W, R = _carry(univ, stop)
    C, Wh, _ = af.partes(W, R, fg.C_FX)
    ren = lambda X: X.rename(columns=lambda c: c.replace("=X", ""))
    return ren(C), af.episodios(ren(Wh), ren(C), ren(R))


# ---------------------------------------------------------------- A2 eurobonds em stress
def _eb_stress(lo=60, hi=85, stop=1, n=10, saida=97, custo_mult=1):
    I = af.eb_insumos()
    dias, P, X = I["dias"], I["PE"], I["exc"]
    F = I["F"].reindex(columns=[c for c in I["F"].columns if c in X.columns])
    cols = np.array(F.columns)
    R, Pv, Fv = X[cols].to_numpy(), P[cols].to_numpy(), F.to_numpy()
    em = np.array([I["emis"].get(c, c) for c in cols])
    custo = I["custo"] * custo_mult
    val, entrada_px, proib, out, nav = {}, {}, {}, np.zeros(len(dias)), 1.0
    Cm = np.zeros((len(dias), len(cols)))
    abertos, trades = {}, []
    for t in range(1, len(dias)):
        i, cd = t - 1, 0.0
        for k in list(val):
            px = Pv[i, k]
            sumiu = np.isnan(R[max(i - 2, 0):i + 1, k]).all()
            caiu = stop and px == px and px < .8 * entrada_px[k]
            if sumiu or (px == px and px >= saida) or caiu or not (Fv[i, k] >= .5):
                c_ = val.pop(k) * custo
                cd += c_
                Cm[t, k] -= c_ / nav
                if caiu:
                    proib[k] = t + 63
                a = abertos.pop(k)
                a.update(saida=dias[t], px_saida=px, motivo="sumiu" if sumiu else "stop -20%" if caiu else "chegou ao par" if px >= saida else "sinal fraco")
                trades.append(a)
        if len(val) < n:
            emis_h = {em[k] for k in val}
            ok = np.where((Pv[i] >= lo) & (Pv[i] <= hi) & (Fv[i] >= .7) & ~np.isnan(R[i]))[0]
            for k in ok[np.argsort(-Fv[i, ok])]:
                livre = nav - sum(val.values())
                if len(val) >= n or livre <= 1e-9:
                    break
                if k in val or proib.get(k, 0) > t or em[k] in emis_h:
                    continue
                val[k] = min(nav / n, livre)
                entrada_px[k] = Pv[i, k]
                emis_h.add(em[k])
                cd += val[k] * custo
                Cm[t, k] -= val[k] * custo / nav
                abertos[k] = {"ativo": cols[k], "emissor": em[k], "entrada": dias[t], "px_entrada": Pv[i, k]}
        g = 0.0
        for k in val:
            r = R[t, k] if not np.isnan(R[t, k]) else 0.0
            g += val[k] * r
            Cm[t, k] += val[k] * r / nav
            val[k] *= 1 + r
        out[t] = (g - cd) / nav
        nav *= 1 + out[t]
    for k, a in abertos.items():
        a.update(saida=dias[-1], px_saida=Pv[-1, k], motivo="em carteira")
        trades.append(a)
    C = pd.DataFrame(Cm, index=dias, columns=cols)
    T = pd.DataFrame(trades)
    if len(T):
        T["dias"] = [((dias > a) & (dias <= b)).sum() for a, b in zip(T.entrada, T.saida)]
        T["contrib pp"] = [C.loc[(C.index >= a) & (C.index <= b), k].sum() * 100 for k, a, b in zip(T.ativo, T.entrada, T.saida)]
    return pd.Series(out, index=dias), C, T


def eb_stress(lo=60, stop=1, custo_mult=1, lag=0):
    r = _eb_stress(lo, 85, stop, custo_mult=custo_mult)[0].reindex(DIAS).fillna(0)
    return r.shift(lag).fillna(0) if lag else r


# ---------------------------------------------------------------- A3 put-write com hedge de beta
def _putw(hedge=1.0, peso_svxy=0.0, custo_mult=1, lag=0):
    pw = limpa(IDX["^PUT"].reindex(DIAS_US).pct_change(fill_method=None)) - TB_US
    spy = limpa(ETF["SPY"].reindex(DIAS_US).pct_change(fill_method=None)) - TB_US
    sv = limpa(ETF["SVXY"].reindex(DIAS_US).pct_change(fill_method=None), .9) - TB_US
    vix, v3 = IDX["^VIX"].reindex(DIAS_US).ffill(), IDX["^VIX3M"].reindex(DIAS_US).ffill()
    vv = IDX["^VVIX"].reindex(DIAS_US).ffill()
    on = (vix / v3 < 1) & (vv < vv.rolling(252, min_periods=100).quantile(.8))
    R = pd.DataFrame({"put": pw, "svxy": sv, "spy": spy})
    W = pd.DataFrame({"put": 1 - peso_svxy, "svxy": on.astype(float) * peso_svxy}, index=DIAS_US)
    livro = (W.shift(1) * R[["put", "svxy"]]).sum(axis=1)
    beta = (livro.rolling(126, min_periods=60).cov(spy) / spy.rolling(126, min_periods=60).var()).clip(0, 1.5)
    W["spy"] = -hedge * beta.fillna(.6)
    return W, R


def putwrite_hedge(hedge=1.0, peso_svxy=0.0, custo_mult=1, lag=0):
    W, R = _putw(hedge, peso_svxy)
    return brl(carteira(W, R, fg.C_ETF * custo_mult, lag))


# ---------------------------------------------------------------- A4 termo conservador
_CT = None


def _cand_cons():
    global _CT
    if _CT is None:
        c = af.cand_termo()
        c["taxa_compra"] = np.minimum(c.taxa_compra, c.taxa_vw)          # só entra se as duas medidas pagam; trava a pior
        _CT = c
    return _CT


def termo_cons(thr=.005, peso=.1, custo_mult=1, lag=0):
    C, T, _ = af.termo_partes(thr=thr, peso=peso, lag=lag, cand=_cand_cons())
    e = C.sum(axis=1).reindex(DIAS).fillna(0)
    if custo_mult != 1:
        e -= (custo_mult - 1) * .002 / 60 * (e != 0)
    return e


FUNDOS = [
    Fundo("A1 Carry G10+LatAm (teto real + stop)", "Macro", "CDI",
          "Carry sem lira turca: comprar MXN/BRL/COP/CLP e vender JPY/CHF/EUR quando o diferencial é grande; teto de 25% do PL por moeda DEPOIS do vol-alvo e stop de 2 desvios em 10 dias",
          "Top/bottom 3 por juro BIS, inverso da vol, vol-alvo 8%, mensal", carry_g10latam, {"univ": ["G10+LatAm", "todas sem TRY"], "stop": [0, 1]}, inicio="2010-01-01"),
    Fundo("A2 Eurobonds BR em stress", "Crédito", "CDI",
          "Comprar eurobonds brasileiros com spread no top 30% e preço entre lo e 85 (stress, não falência), hedge de câmbio e de Treasury; vende ao chegar a 97 ou com o sinal fraco",
          "Até 10 nomes, 1 por emissor, stop opcional de -20% no preço", eb_stress, {"lo": [40, 60], "stop": [0, 1]}, inicio="2021-01-01", corte="2024-01-01"),
    Fundo("A3 Put-write com hedge de beta", "Volatilidade", "CDI",
          "O prêmio de vol vendido sem o beta de ações: put-write da CBOE vendido em SPY pelo beta móvel (126d)",
          "^PUT (+SVXY opcional com filtro) - beta x SPY", putwrite_hedge, {"hedge": [0, .5, 1.0], "peso_svxy": [0, .25]}, inicio="2012-01-01"),
    Fundo("A4 Termo conservador", "Arbitragem B3", "CDI",
          "Financiar termo só quando a taxa paga com o fechamento E com o VWAP à vista; trava a menor das duas",
          "Até 10 posições de 10% (ou 5%) do PL, 60-400 dias", termo_cons, {"thr": [.005, .01, .02], "peso": [.05, .1]}, inicio="2015-01-01"),
]


def partes(f, p):
    if f.nome.startswith("A1"):
        return carry_partes(p["univ"], p["stop"])
    if f.nome.startswith("A2"):
        _, C, T = _eb_stress(p["lo"], 85, p["stop"])
        return C, T
    if f.nome.startswith("A3"):
        W, R = _putw(**p)
        C, Wh, _ = af.partes(W, R, fg.C_ETF)
        return C, af.episodios(Wh[["svxy"]], C[["svxy"]], R[["svxy"]]) if p["peso_svxy"] else pd.DataFrame()
    C, T, _ = af.termo_partes(cand=_cand_cons(), **p)
    return C, T.drop(columns=["diaria"])


if __name__ == "__main__":
    from rodar import BENCH
    res = []
    for f in FUNDOS:
        r = roda(f, CDI, BENCH[f.benchmark], print)
        if r is None:
            continue
        o, rb = r["oos"], r["rob"]
        print(f"{f.nome}: {r['params']} | IR IS {r['is_ir']:.2f} | OOS {o['retorno a.a. %']:.1f}% vs {o['benchmark a.a. %']:.1f}% (IR {o['IR vs bench']:.2f}) | "
              f"P(bater) {rb['P(bater bench OOS) %']:.0f}% | PBO {rb['PBO %']:.0f}% | custo x2 {rb['OOS custo x2 (pp)']:.2f} | +1 dia {rb['OOS execução +1 dia (pp)']:.2f} "
              f"| mediana variantes {rb['mediana OOS das variantes (pp)']:.2f}", flush=True)
        r["contrib"], r["trades"] = partes(f, r["params"])
        r["fundo"].func = None
        res.append(r)
    pickle.dump(res, open(OUT / "ideias_atribuicao.pkl", "wb"))
    print("pronto")
