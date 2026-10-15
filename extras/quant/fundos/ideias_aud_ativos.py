"""
AUDITORIA (red team) dos 5 candidatos ao "top 5" — versões corrigidas com sufixo " [auditado]".
Caderno: pesquisa/auditoria_ativos.md.   Uso: PYTHONIOENCODING=utf-8 python -W ignore ideias_aud_ativos.py [analise]
  -> resultado/ideias_aud_ativos.pkl  (rodado com com_regime, igual à rodada final, + contrib/trades)

Correções implementadas:
  C4 Mineradoras  : (1) histerese sem reentrada no mesmo dia após saída por prazo/stop (bloqueia o lado até o z voltar a 0);
                    (2) preços das pernas limpos em NÍVEL (CPER 04/12/2014 -33% e 02/02/2015 -29% eram prints errados: o +50% do dia
                        seguinte era zerado por `limpa`, o -33% ficava -> P&L falso no vendido em CPER).
  Eurobonds       : reprecificação com preço "vivo" (print diferente do anterior nos últimos 5 dias úteis), liquidez mínima
                    (>= 40% dos dias com print em 63d), execução no 1º print >= t+1, bid/ask por faixa de preço (0,5/1/1,5/2 pontos),
                    marcação no último print (compra-e-segura, sem venda por "sumiu"), sem acréscimo de cupom abaixo de 50 (bond
                    em default negocia "flat").
  Distressed deb. : marcação pelo PU R$ do último negócio (sem acréscimo da curva enquanto não negocia), custo 2,5% por lado,
                    liquidez mínima de R$ 5 mi em 21 dias e R$ 300 mil no dia da execução.
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from base import CDI, DIAS, TB_US, _limpa_niveis, brl, limpa
from motor import Fundo, roda
from regimes import REG_PADRAO, com_regime, serie_exposicao

OUT = Path(__file__).resolve().parent / "resultado"


def _an(x):
    x = x.dropna()
    return ((1 + x).prod() ** (252 / max(len(x), 1)) - 1) * 100


def _ir(x):
    return x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan


def tabela_regimes(e, corte, ini):
    """Excesso a.a. e IR, IS e OOS, da série e sob cada regime genérico (o executor escolhe 1 no IS)."""
    lin = []
    for g in REG_PADRAO:
        s = serie_exposicao(e, g)
        x = e * s - s.diff().abs().fillna(0) * .001
        i, o = x[(x.index >= ini) & (x.index < corte)], x[x.index >= corte]
        lin.append({"regime": g, "IS a.a.": _an(i), "IR IS": _ir(i), "OOS a.a.": _an(o), "IR OOS": _ir(o), "% tempo ligado OOS": s[s.index >= corte].mean() * 100})
    return pd.DataFrame(lin).set_index("regime").round(2)


# ===================================================================================== 1. C4 MINERADORAS (corrigido)
import ideias_commodities as ic                                                     # noqa: E402

_PM = None


def _p_min():
    """Preços das pernas limpos em nível (erro de print que se desfaz em até 8 dias vira NaN -> último preço bom)."""
    global _PM
    if _PM is None:
        tks = ["GDX", "GLD", "GDXJ", "SIL", "SLV", "COPX", "CPER", "FCX", "VALE", "BHP", "RIO"]
        _PM = _limpa_niveis(ic.P[tks], lim=.15)
    return _PM


def _ex_us(tk):
    r = _p_min()[tk].pct_change(fill_method=None)
    return limpa(r, .45) - ic.TB


def histerese_aud(Z, z_in, z_out=0.0, z_stop=4.0, tmax=120):
    """Igual a ic.histerese, mas a saída por prazo (tmax) ou stop BLOQUEIA o mesmo lado até o z cruzar z_out
    (no original, a posição zerada por prazo era reaberta na mesma linha -> o limite de 120 dias não existia)."""
    Zv = Z.values
    out = np.zeros_like(Zv)
    n = Zv.shape[1]
    pos, t, bl = np.zeros(n), np.zeros(n), np.zeros(n)                                # bl: +1 bloqueia compra, -1 bloqueia venda
    for i in range(len(Zv)):
        z = Zv[i]
        ok = np.isfinite(z)
        bl[(bl == 1) & ok & (z > -z_out)] = 0
        bl[(bl == -1) & ok & (z < z_out)] = 0
        forca = ((pos == 1) & ok & (z < -z_stop)) | ((pos == -1) & ok & (z > z_stop)) | (t >= tmax)
        sai = (pos == 1) & ok & (z > -z_out) | (pos == -1) & ok & (z < z_out) | forca | ~ok
        bl[forca] = pos[forca]
        pos[sai], t[sai] = 0, 0
        pos[(pos == 0) & (bl != 1) & ok & (z < -z_in) & (z > -z_stop)] = 1
        pos[(pos == 0) & (bl != -1) & ok & (z > z_in) & (z < z_stop)] = -1
        t[pos != 0] += 1
        out[i] = pos
    return pd.DataFrame(out, index=Z.index, columns=Z.columns)


PARES_MIN = {"GDX x GLD": ("GDX", ["GLD"]), "GDXJ x GDX": ("GDXJ", ["GDX"]), "SIL x SLV": ("SIL", ["SLV"]),
             "COPX x CPER": ("COPX", ["CPER"]), "FCX x CPER": ("FCX", ["CPER"]), "VALE x BHP/RIO": ("VALE", ["BHP", "RIO"])}


def mineradoras_aud(jan=126, z_in=1.0, fora=(), corrige=True, alvo=.10, custo_mult=1, lag=0, detalhe=False):
    """C4 corrigido. `fora`: pares excluídos (teste deixa-um-fora). corrige=False reproduz o original (só a parte 'pares')."""
    ex_ = _ex_us if corrige else ic.ex_us
    pares = {k: (ex_(a), sum(ex_(h) for h in hs) / len(hs)) for k, (a, hs) in PARES_MIN.items() if k not in fora}
    custo = {k: (.0003 + .0005) if k == "FCX x CPER" else 2 * ic.C_ETF for k in pares}
    R, B = {}, {}
    for k, (ra, rh) in pares.items():
        R[k] = ra - ic.beta(ra, rh, 252) * rh
    R = pd.DataFrame(R).reindex(DIAS)
    R = R.where(R.notna().cumsum() > 0)
    Z = ic.semanal(ic.zscore(R, jan))
    S = (histerese_aud if corrige else ic.histerese)(Z, z_in)
    W = ic.risco_igual(S, R, alvo).where(S != 0, 0)
    return ic.executa(W, R, custo, .003, .005, lag, custo_mult, detalhe)


def _min_func(jan=126, z_in=1.0, custo_mult=1, lag=0):
    return mineradoras_aud(jan, z_in, custo_mult=custo_mult, lag=lag)


# ===================================================================================== 2. EUROBONDS BR (06 / A2 / I7 reprecificados)
import atribuicao_fundos as af                                                      # noqa: E402
from base import DQ                                                                 # noqa: E402

_EB = {}


def _eb_base():
    """Painel honesto dos eurobonds: print bruto (sem ffill de 5 dias), marca = último print, retorno hedgeado (câmbio via DOL e
    Treasury pela duration, como em estrategias_diario) recalculado com a marca e SEM acréscimo de cupom quando o bond está < 50."""
    if _EB:
        return _EB
    I = af.eb_insumos()
    dias = I["dias"]
    px = pd.read_parquet(DQ / "eurobonds_precos.parquet").drop_duplicates(["date", "isin"], keep="last")
    P = px.pivot(index="date", columns="isin", values="preco").reindex(index=dias, columns=I["PE"].columns)
    P = P.where((P >= 5) & (P <= 160))
    Pm = P.ffill()
    cup = I["cup"].reindex(P.columns).fillna(0)
    dt = pd.Series(np.r_[1, np.diff(dias).astype("timedelta64[D]").astype(float)], index=dias)
    accr = pd.DataFrame(np.outer(dt / 365, cup), index=dias, columns=P.columns).where(Pm.shift(1) >= 50, 0.0)
    r = ((Pm + accr) / Pm.shift(1) - 1).where(Pm.shift(1).notna())
    # componentes de hedge reconstruídos do painel original (erro de reconstrução < 1e-8): c = r_fx - r_DOL (cupom cambial), H = Treasury
    PE = I["PE"]
    r0 = ((PE + np.outer(dt / 365, cup)) / PE.shift(1) - 1)
    r0 = r0.where(r0.abs() < .3)
    TB = TB_US.reindex(pd.DatetimeIndex(dias).union(TB_US.index)).ffill().reindex(dias).fillna(0)
    H = -(I["yD"].shift(1) / 252 - I["Dm"].shift(1) * (I["yD"] - I["yD"].shift(1)) - np.outer(TB.shift(1), np.ones(PE.shape[1])))
    cdi = I["cdi"].reindex(dias).fillna(0)
    c = ((I["exc"].add(cdi, axis=0) - H.fillna(0) + 1) / (1 + r0) - 1).median(axis=1)
    c = c.fillna(cdi - TB)
    exc = ((1 + r).mul(1 + c, axis=0) - 1 + H.fillna(0)).sub(cdi, axis=0)
    chg = P.notna() & (Pm.diff().abs() > 1e-9)                                      # print "vivo": existe e mudou
    _EB.update(I=I, dias=dias, P=P, Pm=Pm, exc=exc, vivo5=chg.rolling(5, min_periods=1).max().astype(bool),
               liq=chg.rolling(63, min_periods=63).mean(), q5=Pm / Pm.shift(5) - 1, emis=I["emis"])
    return _EB


def meio_spread(p):
    """Meia ponta do bid/ask em pontos de preço: IG/BB perto do par 0,5; 75-90 1,0; 50-75 1,5; distressed < 50 2,0."""
    return np.where(p >= 90, .5, np.where(p >= 75, 1.0, np.where(p >= 50, 1.5, 2.0)))


def _eb_livro_aud(regra="sinal", lo=40, hi=85, n=15, liq_min=.4, saida=97, prazo=504, custo_mult=1, lag=0):
    b = _eb_base()
    dias, P, Pm, X = b["dias"], b["P"], b["Pm"], b["exc"]
    cols = np.array(P.columns)
    F = b["I"]["F"].reindex(index=dias, columns=cols)
    Pv, Pmv, Xv, Fv = P.to_numpy(), Pm.to_numpy(), X.to_numpy(), F.to_numpy()
    V5, LQ, Q5 = b["vivo5"].to_numpy(), b["liq"].to_numpy(), b["q5"].to_numpy()
    em = np.array([b["emis"].get(c, c) for c in cols])
    gat = np.ones(len(dias), bool)
    if regra == "safra":
        import ideias_i_credito_juros as icj
        ev, _ = icj._eb_gatilho(b["I"])
        gat = ev.astype(float).rolling(126, min_periods=1).max().values > 0
    T, N = len(dias), len(cols)
    out, Cm, nav = np.zeros(T), np.zeros((T, N)), 1.0
    val, info, pend_in, pend_out, trades = {}, {}, {}, {}, []
    for t in range(1, T):
        g = cd = 0.0
        for k in val:                                                               # rende de t-1 a t pela marca (último print)
            x = Xv[t, k]
            x = 0.0 if np.isnan(x) else x
            g += val[k] * x
            Cm[t, k] += val[k] * x / nav
            val[k] *= 1 + x
        for k in list(pend_out):                                                    # vende no 1º print a partir de t+1+lag
            if t >= pend_out[k] and Pv[t, k] == Pv[t, k]:
                c_ = val[k] * custo_mult * meio_spread(Pv[t, k]) / Pv[t, k]
                cd += c_
                Cm[t, k] -= c_ / nav
                val.pop(k)
                a = info.pop(k)
                a.update(saida=dias[t], px_saida=Pv[t, k])
                trades.append(a)
                del pend_out[k]
        for k in list(pend_in):                                                     # compra no 1º print entre t+1+lag e t+5+lag
            t0, t1 = pend_in[k]
            if t > t1:
                del pend_in[k]
            elif t >= t0 and Pv[t, k] == Pv[t, k]:
                del pend_in[k]
                if not (Pv[t, k] <= hi + 3):                                         # o preço fugiu antes de executar
                    continue
                v = nav / n
                c_ = v * custo_mult * meio_spread(Pv[t, k]) / Pv[t, k]
                val[k] = v - c_
                cd += c_
                Cm[t, k] -= c_ / nav
                info[k] = {"ativo": cols[k], "emissor": em[k], "entrada": dias[t], "px_entrada": Pv[t, k], "t0": t}
        out[t] = (g - cd) / nav
        nav *= 1 + out[t]
        # ---- decisões no fechamento de t (só informação até t)
        for k in val:
            if k in pend_out:
                continue
            px, f = Pmv[t, k], Fv[t, k]
            if regra == "sinal":
                sai, mot = not (f >= .5), "sinal < 50%"
            elif regra == "stress":
                sai, mot = (px >= saida) or not (f >= .5), "par" if px >= saida else "sinal < 50%"
            else:
                sai, mot = (px >= saida) or (t - info[k]["t0"] >= prazo), "par" if px >= saida else "prazo"
            if sai:
                pend_out[k] = t + 1 + lag
                info[k]["motivo"] = mot
        livres = n - len(val) - len(pend_in) + len(pend_out)
        if livres <= 0 or not gat[t]:
            continue
        ok = V5[t] & (LQ[t] >= liq_min) & ~np.isnan(Pmv[t])
        if regra == "sinal":
            ok &= (Fv[t] >= .9) & ~(Q5[t] < -.04)
            ordem = -np.nan_to_num(Fv[t], nan=-9)
        elif regra == "stress":
            ok &= (Pmv[t] >= lo) & (Pmv[t] <= hi) & (Fv[t] >= .7)
            ordem = -np.nan_to_num(Fv[t], nan=-9)
        else:
            ok &= (Pmv[t] >= lo) & (Pmv[t] <= hi)
            ordem = -np.nan_to_num(Pmv[t], nan=-9)
        cand = np.flatnonzero(ok)
        emis_h = {em[k] for k in list(val) + list(pend_in)}
        for k in cand[np.argsort(ordem[cand])]:
            if livres <= 0:
                break
            if k in val or k in pend_in or em[k] in emis_h:
                continue
            pend_in[k] = (t + 1 + lag, t + 5 + lag)
            emis_h.add(em[k])
            livres -= 1
    for k, a in info.items():
        a.update(saida=dias[-1], px_saida=Pmv[-1, k], motivo="em carteira")
        trades.append(a)
    C = pd.DataFrame(Cm, index=dias, columns=cols)
    Tr = pd.DataFrame(trades)
    if len(Tr):
        Tr["dias"] = [((dias > a) & (dias <= z)).sum() for a, z in zip(Tr.entrada, Tr.saida)]
        Tr["retorno preço %"] = (Tr.px_saida / Tr.px_entrada - 1) * 100
        Tr["contrib pp"] = [C.loc[(C.index >= a) & (C.index <= z), k].sum() * 100 for k, a, z in zip(Tr.ativo, Tr.entrada, Tr.saida)]
        Tr = Tr.drop(columns="t0")
    return pd.Series(out, index=dias), C.loc[:, C.abs().sum() > 0], Tr


def eb_aud(regra="sinal", n=15, lo=40, hi=85, liq_min=.4, custo_mult=1, lag=0, detalhe=False):
    r, C, T = _eb_livro_aud(regra, lo, hi, n, liq_min, custo_mult=custo_mult, lag=lag)
    e = r.reindex(DIAS).fillna(0)
    return (e, C.reindex(DIAS).fillna(0), T) if detalhe else e


def eb06_aud(n=15, liq_min=.4, custo_mult=1, lag=0):
    return eb_aud("sinal", n=n, liq_min=liq_min, custo_mult=custo_mult, lag=lag)


def eb_a2_aud(lo=40, liq_min=.4, custo_mult=1, lag=0):
    return eb_aud("stress", n=10, lo=lo, hi=85, liq_min=liq_min, custo_mult=custo_mult, lag=lag)


def eb_i7_aud(gatilho="evento", lo=40, hi=80, liq_min=.4, custo_mult=1, lag=0):
    return eb_aud("safra" if gatilho == "evento" else "safra_sempre", n=10, lo=lo, hi=hi, liq_min=liq_min, custo_mult=custo_mult, lag=lag)


# ===================================================================================== 3. C4 DISTRESSED DE DEBÊNTURES (conservador)
_DS = {}


def _ds_base():
    """Excesso diário marcado pelo PU (R$) do ÚLTIMO negócio: entre negócios o PU fica parado (não acumula CDI+spread da curva);
    o acréscimo só aparece quando houver outro negócio. Papel que parou de negociar não 'rende a curva' para sempre."""
    if _DS:
        return _DS
    import ideias_credito as icr
    p = icr.painel()
    Pf, R, E, cdi = p["Pf"], p["R"], p["E"], p["cdi"]
    G = ((1 + R) * Pf.shift(1) / Pf).where(R.notna())                                # acréscimo diário do PU par (recuperado)
    par = np.exp(np.log(G.fillna(1.0)).cumsum())
    pu = (p["P"] * par).where(p["obs"])
    pum = pu.ffill().where(p["vivo"])
    r2 = (pum / pum.shift(1) - 1).where(pum.shift(1).notna())
    r2 = r2.where(r2.abs() < .9)
    H = E - R.sub(cdi, axis=0)                                                       # hedge de duration (IPCA+/pré) do painel
    E2 = r2.add(H.fillna(0)).sub(cdi, axis=0)
    snd = pd.read_parquet(icr.DQ / "snd_negocios.parquet", columns=["date", "codigo", "qtd", "pu_med"])
    fin = (snd.qtd * snd.pu_med).groupby([snd.date, snd.codigo]).sum().unstack().reindex(index=p["dias"], columns=Pf.columns).fillna(0)
    _DS.update(p=p, E2=E2, fin=fin, icr=icr)
    return _DS


def livro_aud(quer, sai, pri, n_max, custo, E, fin_dia, lag=0, max_dias=None, por_emissor=1, fin_min=3e5):
    """Cópia de ideias_credito.livro com: excesso E dado (marcação conservadora), execução só em dia com negócio >= fin_min
    (entrada E saída), custo cheio também na saída por vencimento/sem preço. Devolve (excesso, contrib, trades)."""
    b = _ds_base()
    p = b["p"]
    dias, cols = p["dias"], p["P"].columns
    k0 = 1 + lag
    Q = quer.reindex(index=dias, columns=cols).fillna(False).to_numpy()
    X = sai.reindex(index=dias, columns=cols).fillna(False).to_numpy()
    PR = pri.reindex(index=dias, columns=cols).to_numpy(dtype=float)
    OB = (p["obs"] & (fin_dia >= fin_min)).to_numpy()
    VV, Ev, PF = p["vivo"].to_numpy(), E.to_numpy(), p["Pf"].to_numpy()
    em = p["raiz"].reindex(cols).to_numpy()
    w = 1 / n_max
    C = np.zeros(Ev.shape)
    held, trades = {}, []
    for t in range(k0, len(dias)):
        for k, h in held.items():
            r = Ev[t, k]
            r = 0.0 if np.isnan(r) else r
            C[t, k] += w * h["acum"] * r
            h["acum"] *= 1 + r
        s = t - k0
        for k in list(held):
            h = held[k]
            morto = not VV[t, k]
            if morto or (OB[t, k] and (X[s, k] or (max_dias and t - h["i"] >= max_dias))):
                C[t, k] -= w * h["acum"] * custo
                h["acum"] *= 1 - custo
                trades.append((cols[k], dias[h["i"]], dias[t], h["p0"], PF[t - 1, k] if morto else PF[t, k], h["acum"] - 1,
                               "vencimento/sem preço" if morto else "sinal/prazo"))
                del held[k]
        if len(held) < n_max:
            cand = np.flatnonzero(Q[s] & OB[t])
            if len(cand):
                cand = cand[np.argsort(-np.nan_to_num(PR[s, cand], nan=-1e9))]
                ne = {}
                for k in held:
                    ne[em[k]] = ne.get(em[k], 0) + 1
                for k in cand:
                    if len(held) >= n_max:
                        break
                    if k in held or ne.get(em[k], 0) >= por_emissor:
                        continue
                    held[k] = {"i": t, "p0": PF[t, k], "acum": 1 - custo}
                    ne[em[k]] = ne.get(em[k], 0) + 1
                    C[t, k] -= w * custo
    for k, h in held.items():
        trades.append((cols[k], dias[h["i"]], dias[-1], h["p0"], PF[-1, k], h["acum"] - 1, "aberta"))
    ser = pd.Series(C.sum(axis=1), index=dias).reindex(DIAS).fillna(0)
    us = np.flatnonzero(np.abs(C).sum(axis=0) > 0)
    contrib = pd.DataFrame(C[:, us], index=dias, columns=cols[us])
    tr = pd.DataFrame(trades, columns=["ativo", "entrada", "saida", "pct_entrada", "pct_saida", "retorno", "motivo_saida"])
    if len(tr):
        tr["emissor"] = tr.ativo.map(p["cad"].empresa)
        tr["dias"] = [((dias > a) & (dias <= z)).sum() for a, z in zip(tr.entrada, tr.saida)]
        tr["contrib pp"] = [contrib.loc[(contrib.index >= a) & (contrib.index <= z), k].sum() * 100 for k, a, z in zip(tr.ativo, tr.entrada, tr.saida)]
    return ser, contrib, tr


def distressed_aud(thr=80, modo="todos", custo=.025, liq21=5e6, marca="pu", custo_mult=1, lag=0, detalhe=False):
    """Mesmo sinal de ideias_credito.distressed (preço de crédito <= thr, caiu de >= 90, confirmação no balcão, sai >= 95 ou 2 anos,
    zera na RJ se modo='sem_rj'), com: marcação pelo PU do último negócio, custo 2,5% por lado, giro >= R$ 5 mi em 21 dias para entrar e
    negócio >= R$ 300 mil no dia de execução. marca='curva' usa a marcação original (para isolar os efeitos)."""
    b = _ds_base()
    p, icr = b["p"], b["icr"]
    Pf, dias = p["Pf"], p["dias"]
    ev = icr.eventos_rj().reindex(Pf.columns)
    em_rj = pd.DataFrame({k: dias >= ev.rj[k] if pd.notna(ev.rj[k]) else np.zeros(len(dias), bool) for k in Pf.columns}, index=dias)
    plano = pd.DataFrame({k: dias >= ev.plano[k] if pd.notna(ev.plano[k]) else np.zeros(len(dias), bool) for k in Pf.columns}, index=dias)
    pc = Pf.copy()
    ipc = p["ind"].eq("IPCA").reindex(Pf.columns).to_numpy()
    pc.loc[:, ipc] = 100 * np.exp(-(p["S"].loc[:, ipc] - 1.5).clip(lower=0) * p["D"].loc[:, ipc] / 100)
    pc = pc.where(p["ind"].isin(["DI", "IPCA"]).reindex(Pf.columns).to_numpy()[None, :].repeat(len(dias), 0))
    caiu = pc.where(p["obs"]).rolling(252, min_periods=1).max().shift(1) >= 90
    quer = p["obs"] & (pc <= thr) & (pc >= 10) & caiu & (p["T"] > .25) & (p["fin21"] >= liq21)
    quer &= (dias < pd.Timestamp("2023-04-01"))[:, None] | (icr.preco_balcao() <= thr + 5)
    sai = pc >= 95
    if modo == "sem_rj":
        quer &= ~em_rj
        sai |= em_rj
    elif modo == "sem_rj_ou_plano":
        quer &= ~em_rj | plano
        sai |= em_rj & ~plano
    E = b["E2"] if marca == "pu" else p["E"]
    r = livro_aud(quer, sai, -pc, 10, custo * custo_mult, E, b["fin"], lag, max_dias=504)
    return r if detalhe else r[0]


# ===================================================================================== fundos auditados
def _det_min(p):
    _, C, T = mineradoras_aud(p["jan"], p["z_in"], detalhe=True)
    return C, T


def _det_eb(regra):
    def f(p):
        rg = regra if regra != "safra" else ("safra" if p.get("gatilho", "evento") == "evento" else "safra_sempre")
        _, C, T = eb_aud(rg, n=p.get("n", 10 if regra != "sinal" else 15), lo=p.get("lo", 40), hi=p.get("hi", 85 if regra != "safra" else 80), detalhe=True)
        return C, T
    return f


def _det_ds(p):
    _, C, T = distressed_aud(p["thr"], p["modo"], detalhe=True)
    return C, T


FUNDOS = [
    Fundo("C4 Mineradoras vs metal [auditado]", "Valor relativo commodities", "CDI",
          "Mineradora é uma opção alavancada no metal: GDX/GLD, GDXJ/GDX, SIL/SLV, COPX/CPER, FCX/CPER, VALE vs BHP/RIO. Quando a mineradora "
          "fica para trás do metal, compro a mineradora e vendo o metal (e vice-versa).",
          "Pares em dólar com hedge cambial; beta 1 ano; z-score do resíduo; histerese SEM reentrada após prazo/stop; CPER limpo em nível",
          _min_func, {"jan": [63, 126], "z_in": [1.0, 2.0]}),
    Fundo("06 Crédito offshore com hedge (cupom cambial) [auditado]", "Crédito", "CDI",
          "Eurobonds de empresas brasileiras com hedge cambial e de Treasury: CDI + spread",
          "Top 10% de spread, sai < 50%; só bonds com print vivo (5d) e >= 40% dos dias com negócio; executa no 1º print >= t+1; bid/ask 0,5-2 pts; "
          "compra-e-segura marcado no último print; sem cupom abaixo de 50", eb06_aud, {"n": [10, 15, 25]}, inicio="2021-01-01", corte="2024-01-01"),
    Fundo("A2 Eurobonds BR em stress [auditado]", "Crédito", "CDI",
          "Comprar eurobonds BR com spread no top 30% e preço entre lo e 85, hedge de câmbio e Treasury; vende a 97 ou com sinal < 50%",
          "Até 10 nomes, 1 por emissor; mesmas regras de preço vivo/liquidez/bid-ask do 06 auditado", eb_a2_aud, {"lo": [40, 60]},
          inicio="2021-01-01", corte="2024-01-01"),
    Fundo("I7 Eurobonds BR em stress (safra) [auditado]", "Crédito", "CDI",
          "No stress sistêmico o mercado vende a 60-80 empresas que não quebram: compro a safra com hedge e carrego até o par",
          "Até 10 bonds, compra-e-segura até 97 ou 2 anos; mesmas regras de preço vivo/liquidez/bid-ask", eb_i7_aud,
          {"gatilho": ["evento", "sempre"], "lo": [40, 60], "hi": [80, 85]}, inicio="2019-06-01", corte="2023-01-01"),
    Fundo("C4 Distressed / recuperação [auditado]", "Crédito estressado", "CDI",
          "PU abaixo de 70-80% do par em emissor sem RJ (ou com plano aprovado) é pânico, não perda: compro e vendo na recuperação (>=95%)",
          "Até 10 papéis, 1 por emissor; marcação pelo PU do último negócio; custo 2,5% por lado; giro >= R$ 5 mi/21d; execução só com negócio >= R$ 300 mil",
          lambda thr=80, modo="todos", custo_mult=1, lag=0: distressed_aud(thr, modo, custo_mult=custo_mult, lag=lag),
          {"thr": [70, 80], "modo": ["todos", "sem_rj", "sem_rj_ou_plano"]}, inicio="2019-07-01", corte="2023-01-01"),
]
DETALHE = {FUNDOS[0].nome: _det_min, FUNDOS[1].nome: _det_eb("sinal"), FUNDOS[2].nome: _det_eb("stress"),
           FUNDOS[3].nome: _det_eb("safra"), FUNDOS[4].nome: _det_ds}
# custo de LIGAR/DESLIGAR o regime (por 100% de troca): ETFs 10 bps; eurobonds HY ~2 pts ida e volta; debênture estressada 2 x 2,5%
CUSTO_TROCA = {FUNDOS[0].nome: .001, FUNDOS[1].nome: .02, FUNDOS[2].nome: .02, FUNDOS[3].nome: .02, FUNDOS[4].nome: .05}


if __name__ == "__main__":
    from rodar import BENCH
    log = open(OUT / "ideias_aud_ativos_log.txt", "w", encoding="utf-8")

    def lg(s):
        print(s, flush=True)
        log.write(s + "\n")
        log.flush()

    res = []
    for f in FUNDOS:
        for rot, g in (("regime c/ custo real", com_regime(f, custo_troca=CUSTO_TROCA[f.nome])), ("sem regime", f)):
            r = roda(g, CDI, BENCH[f.benchmark], lambda *a: None)
            o, rb = r["oos"], r["rob"]
            lg(f"{f.nome} [{rot}] | {r['params']} | IS IR {r['is_ir']:.2f} | OOS {o['retorno a.a. %']:.1f}% vs {o['benchmark a.a. %']:.1f}% "
               f"(ativo {o['ativo a.a. pp']:+.1f}, IR {o['IR vs bench']:.2f}) | P {rb['P(bater bench OOS) %']:.0f}% | PBO {rb['PBO %']:.0f}% | "
               f"x2 {rb['OOS custo x2 (pp)']:+.1f} | +1d {rb['OOS execução +1 dia (pp)']:+.1f} | mediana var {rb['mediana OOS das variantes (pp)']:+.1f} "
               f"| % var>bench {rb['% variantes > bench OOS']:.0f}%")
            if rot == "sem regime":
                continue
            p = {k: v for k, v in r["params"].items() if k != "regime"}
            C, T = DETALHE[f.nome](p)
            s = serie_exposicao(r["bruto"] - CDI.reindex(r["bruto"].index), r["params"]["regime"]) if r["params"]["regime"] not in ("dd_stop", "hmm_propria") else 1.0
            r["contrib"] = C.mul(s, axis=0) if not np.isscalar(s) else C
            r["trades"] = T
            r["modulo"] = "ideias_aud_ativos"
            r["fundo"].func = None
            res.append(r)
    pickle.dump(res, open(OUT / "ideias_aud_ativos.pkl", "wb"))
    lg("salvo resultado/ideias_aud_ativos.pkl")
