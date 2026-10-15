"""
Frente CRÉDITO PRIVADO / DEBÊNTURES / FUNDOS LISTADOS — 9 teses de mesa testadas sem olhar o futuro.

Retorno diário por debênture (painel papel x dia, 2019+):
  r(t) = Pf(t)/Pf(t-1) * G(t) - 1, onde Pf = %PU da curva do ÚLTIMO negócio (>= R$100 mil) até t (sem interpolar para o
  negócio seguinte) e G = acréscimo do PU par no dia (CDI+spread, %CDI ou IPCA+taxa). IPCA+/pré com hedge de duration em
  DAP/DI1 (contrato e razão escolhidos no fim do mês anterior, base_diaria.pkl). Excesso = r + hedge - CDI.
Execução: decide no fechamento de t; compra/vende no 1º dia >= t+1(+lag) em que o papel NEGOCIA (preço real do dia) e
  paga custo por lado no PU (30 bps; 100 bps para papéis estressados). Debênture não se vende a descoberto: o lado
  "vendido" é zerar ou operar a ação do emissor contra BOVA11.
Uso: python ideias_credito.py  -> resultado/ideias_credito.pkl (+ log em resultado/ideias_credito_log.txt)
"""
import pickle
import re
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
from base import CDI, DIAS, D, DQ, RQ, carteira, limpa, mensal, semanal
from motor import Fundo, roda
import dados_credito as dc

OUT = Path(__file__).resolve().parent / "resultado"
CORTE, CORTE_B = "2023-01-01", "2024-07-01"
C_DEB, C_HY, C_ACAO = .003, .01, .002          # custo por lado (PU) debênture comum / estressada; ação + BOVA (2 pernas)

# =============================================================================== painel de debêntures
_P = {}


def _setor(cad):
    cc = dc.cad_cia().drop_duplicates("cnpj").set_index("cnpj").SETOR_ATIV
    raiz = cc.groupby(cc.index.str[:8]).first()
    cn = cad.cnpj.astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)
    s = cn.map(cc).fillna(cn.str[:8].map(raiz))
    s = s.str.replace(r"^Emp\. Adm\. Part\. - ", "", regex=True).replace({"Emp. Adm. Participações": np.nan, "Sem Setor Principal": np.nan})
    return s.fillna(pd.Series(np.where(cad.incentivada.fillna(False), "Infra (incentivada, sem cadastro)", "Outros (sem cadastro)"), index=cad.index))


def _limpa_precos(P, tol=.10, conf=.03):
    """Filtro de prints sem olhar o futuro: um negócio que se afasta mais de `tol` da última marca só vira marca quando outro
    negócio em dia POSTERIOR o confirma (dentro de `conf`). Até lá o papel fica na marca antiga e não é negociável para o livro.
    Quedas reais (Americanas 100 -> 20) entram com 1 negócio de atraso; prints de lote estranho (TBCR18 90/102/71/57) não."""
    X = P.to_numpy()
    out = np.full(X.shape, np.nan)
    for j in range(X.shape[1]):
        idx = np.flatnonzero(~np.isnan(X[:, j]))
        m = pend = np.nan
        for i in idx:
            x = X[i, j]
            if np.isnan(m) or abs(x / m - 1) <= tol or (not np.isnan(pend) and abs(x / pend - 1) <= conf):
                m, pend = x, np.nan
                out[i, j] = x
            else:
                pend = x
    return pd.DataFrame(out, index=P.index, columns=P.columns)


def painel():
    if _P:
        return _P
    B = pd.read_pickle(RQ / "base_diaria.pkl")
    dias, cad = B["dias"], B["cad"].loc[B["P"].columns]
    # %PU da curva: VWAP dos negócios >= R$100 mil do dia. A base antiga cortava 30-150%, o que apagava justamente os
    # negócios de default (Light, Americanas, Ambipar, Raízen a 5-30% da curva); aqui o corte é 5-200%.
    snd = pd.read_parquet(DQ / "snd_negocios.parquet", columns=["date", "codigo", "qtd", "pu_med", "pct_curva"])
    snd = snd[snd.codigo.isin(B["P"].columns) & snd.pct_curva.between(5, 200) & (snd.qtd * snd.pu_med >= 1e5)]
    snd = snd.assign(w=snd.pct_curva * snd.qtd * snd.pu_med, f=snd.qtd * snd.pu_med)
    g = snd.groupby(["date", "codigo"])
    P = _limpa_precos((g.w.sum() / g.f.sum()).unstack().reindex(index=dias, columns=B["P"].columns))
    cdi = CDI.reindex(dias).fillna(0)
    vivo = pd.DataFrame({k: dias < cad.venc[k] for k in P.columns}, index=dias)
    obs = P.notna() & vivo
    Pf = P.ffill().where(vivo)
    # acréscimo do PU par
    ip = pd.read_parquet(DQ / "ipca.parquet").ipca
    ip.index = ip.index.to_period("M")
    mes = dias.to_period("M")
    ip = ip.reindex(pd.period_range(ip.index.min(), mes.max(), freq="M"))
    ip = ip.fillna(ip.rolling(12, min_periods=1).mean().ffill())
    du = pd.Series(1, index=dias).groupby(mes).transform("size")
    ipd = ((1 + ip.reindex(mes).to_numpy()) ** (1 / du.to_numpy()) - 1)
    j = np.nan_to_num(cad.juros.to_numpy(dtype=float)) / 100
    pct = cad.pct.to_numpy(dtype=float)
    ind = cad.indice.to_numpy()
    pctdi = (ind == "DI") & ~np.isnan(pct) & (pct != 100)
    di = (ind == "DI") & ~pctdi
    G = np.ones(P.shape)
    c = cdi.to_numpy()[:, None]
    G[:, di] = (1 + c) * (1 + j[di]) ** (1 / 252)
    G[:, pctdi] = 1 + c * pct[pctdi] / 100
    G[:, ind == "IPCA"] = (1 + ipd[:, None]) * (1 + j[ind == "IPCA"]) ** (1 / 252)
    G[:, ind == "PRE"] = (1 + j[ind == "PRE"]) ** (1 / 252)
    R = (Pf / Pf.shift(1) * G - 1).where(vivo)
    R = R.where(R.abs() < .9)                                               # só erro grosseiro; quedas de default ficam
    Dd = B["Dd"].reindex_like(P).clip(.25, 15)
    # hedge de duration (DAP p/ IPCA+, DI1 p/ pré): -razão x variação do ajuste B3. O "ajuste anterior" da B3 já vem corrigido
    # por (1+CDI)/(1+IPCA projetado), então a variação já é o P&L em excesso do futuro (testado: DAPK27 out/26).
    H = B["Hdd"].reindex_like(R).fillna(0)
    E = R.add(H).sub(cdi, axis=0)                                           # excesso hedgeado sobre o CDI
    prem = -np.log(Pf / 100) / Dd * 100                                     # pp a.a. sobre a taxa de emissão
    cdi_aa = ((1 + cdi) ** 252 - 1) * 100
    S = pd.DataFrame(np.nan, index=dias, columns=P.columns)
    S.loc[:, di] = (prem.loc[:, di] + j[di] * 100).to_numpy()
    S.loc[:, pctdi] = (prem.loc[:, pctdi] + np.outer(cdi_aa, pct[pctdi] / 100 - 1)).to_numpy()
    cv = B["curvas"].reindex(dias).ffill()
    xs = np.array([2, 3, 5, 8, 10.])
    dap = cv[[f"DAP_{x:g}a" for x in xs]].to_numpy()
    iip = np.flatnonzero(ind == "IPCA")
    Dip = Dd.iloc[:, iip].to_numpy()
    Y = np.full(Dip.shape, np.nan)
    for t in range(len(dias)):
        if not np.isnan(dap[t]).any():
            Y[t] = np.interp(Dip[t], xs, dap[t])
    taxa = prem.iloc[:, iip].to_numpy() + j[iip] * 100
    S.iloc[:, iip] = taxa - Y                                               # spread sobre a NTN-B/DAP de mesma duration
    _P["dapD"] = pd.DataFrame(Y, index=dias, columns=P.columns[iip])
    snd = pd.read_parquet(DQ / "snd_negocios.parquet", columns=["date", "codigo", "qtd", "pu_med"])
    fin = (snd.qtd * snd.pu_med).groupby([snd.date, snd.codigo]).sum().unstack().reindex(index=dias, columns=P.columns).fillna(0)
    pos = np.arange(len(dias))[:, None]
    ult = pd.DataFrame(np.where(obs, pos, np.nan), index=dias, columns=P.columns).ffill()
    age = pos - ult
    T = pd.DataFrame({k: (cad.venc[k] - dias).days / 365.25 for k in P.columns}, index=dias)
    cn = cad.cnpj.astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)
    _P.update(dias=dias, cad=cad, P=P, Pf=Pf, obs=obs, vivo=vivo, E=E, R=R, D=Dd, prem=prem, S=S, fin21=fin.rolling(21).sum(),
              fin63=fin.rolling(63).sum(), age=age, T=T, cnpj=cn, raiz=cn.str[:8], setor=_setor(cad), cdi=cdi, ind=cad.indice)
    # papel que só "negocia" a 100,00% da curva (registro/compromissada, não preço de mercado): >= 80% dos negócios dos últimos
    # 126 dias no par. Fica fora do universo: carregaria CDI+5 sem volatilidade nenhuma (DM Securitizadora, Urbem...).
    no_par = ((P - 100).abs() < .05).rolling(126, min_periods=1).sum() / obs.rolling(126, min_periods=1).sum().replace(0, np.nan)
    _P["so_par"] = no_par >= .8
    _P["elig"] = vivo & (age <= 5) & (_P["fin21"] >= 1e6) & (T > .75) & S.notna() & ~_P["so_par"]
    return _P


# =============================================================================== livro de debêntures (execução em dia de negócio)
CACHE = {}


def livro(quer, sai, pri, n_max, custo, lag=0, max_dias=None, por_emissor=1, motivo=None, chave=None):
    """quer/sai: desejo de entrar/sair decidido no fechamento de t; executa no 1º dia >= t+1+lag com negócio.
    Cada posição entra com 1/n_max do PL (resto no CDI) e depois deriva com o preço (sem rebalancear: com marcas ruidosas,
    peso fixo diário "ganharia" com a oscilação de prints — 79/57/79 viraria +11%). Devolve excesso diário sobre o CDI em DIAS e guarda contrib/trades."""
    p = painel()
    dias, cols = p["dias"], p["P"].columns
    k0 = 1 + lag
    Q = quer.reindex(index=dias, columns=cols).fillna(False).to_numpy()
    X = sai.reindex(index=dias, columns=cols).fillna(False).to_numpy()
    PR = pri.reindex(index=dias, columns=cols).to_numpy(dtype=float)
    OB, VV = p["obs"].to_numpy(), p["vivo"].to_numpy()
    E, PF = p["E"].to_numpy(), p["Pf"].to_numpy()
    em = p["raiz"].reindex(cols).to_numpy()
    MO = motivo.reindex(index=dias, columns=cols).to_numpy(dtype=float) if motivo is not None else None
    w = 1 / n_max
    out = np.zeros(len(dias))
    C = np.zeros(E.shape)
    held, trades = {}, []
    for t in range(k0, len(dias)):
        # rende o dia t quem estava na carteira no fechamento de t-1
        for k, h in held.items():
            r = E[t, k]
            r = 0.0 if np.isnan(r) else r
            C[t, k] += w * h["acum"] * r                                   # compra e segura: o peso deriva com o preço
            h["acum"] *= 1 + r
        s = t - k0
        for k in list(held):                                               # saídas
            h = held[k]
            morto = not VV[t, k]
            if morto or (OB[t, k] and (X[s, k] or (max_dias and t - h["i"] >= max_dias))):
                cst = 0.0 if morto else w * h["acum"] * custo
                C[t, k] -= cst
                h["acum"] *= 1 - (0.0 if morto else custo)
                trades.append((cols[k], h["i"], t, h["p0"], PF[t - 1, k] if morto else PF[t, k], h["acum"] - 1, h["m"],
                               "vencimento/sem preço" if morto else "sinal"))
                del held[k]
        if len(held) < n_max:                                               # entradas: só quem negociou hoje
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
                    held[k] = {"i": t, "p0": PF[t, k], "acum": 1 - custo, "m": (MO[s, k] if MO is not None else PR[s, k])}
                    ne[em[k]] = ne.get(em[k], 0) + 1
                    C[t, k] -= w * custo
    for k, h in held.items():
        trades.append((cols[k], h["i"], len(dias) - 1, h["p0"], PF[-1, k], h["acum"] - 1, h["m"], "aberta"))
    out = C.sum(axis=1)
    ser = pd.Series(out, index=dias).reindex(DIAS).fillna(0)
    if chave is not None:
        usados = np.flatnonzero(np.abs(C).sum(axis=0) > 0)
        contrib = pd.DataFrame(C[:, usados], index=dias, columns=cols[usados])
        tr = pd.DataFrame(trades, columns=["ativo", "i0", "i1", "pct_entrada", "pct_saida", "retorno", "sinal", "motivo_saida"])
        if len(tr):
            tr["entrada"], tr["saida"] = dias[tr.i0.to_numpy()], dias[tr.i1.to_numpy()]
            tr["dias"] = tr.i1 - tr.i0
            tr["contrib"] = [contrib[a].iloc[i0:i1 + 1].sum() for a, i0, i1 in zip(tr.ativo, tr.i0, tr.i1)]
            tr["emissor"] = tr.ativo.map(p["cad"].empresa)
            tr["indice"] = tr.ativo.map(p["cad"].indice)
            tr = tr.drop(columns=["i0", "i1"])[["ativo", "emissor", "indice", "entrada", "saida", "dias", "pct_entrada", "pct_saida",
                                                "retorno", "contrib", "sinal", "motivo_saida"]]
        CACHE[chave] = (contrib, tr)
    return ser


def _chave(nome, custo_mult, lag, **kw):
    return (nome, tuple(sorted(kw.items()))) if custo_mult == 1 and lag == 0 else None


def _long(M, nome):
    s = M.stack()
    s.index.names = ["date", "codigo"]
    return s.rename(nome)


# =============================================================================== 1. valor relativo de spread contra pares
def _res_pares(pares):
    p = painel()
    S = p["S"].where(p["elig"] & (p["Pf"] >= 85))
    df = _long(S, "s").reset_index()
    cad = p["cad"]
    dur = _long(p["D"].where(S.notna()), "D").reset_index().D
    df["db"] = np.digitize(dur, [2, 4])
    df["ind"] = df.codigo.map(cad.indice)
    if pares == "setor":
        df["g"] = df.codigo.map(p["setor"])
    else:                                                                    # "rating" implícito: spread/taxa de emissão
        jj = df.codigo.map(cad.juros)
        df["g"] = np.where(df.ind == "DI", np.digitize(jj, [1, 1.75, 3]), 10 + np.digitize(jj, [5.5, 7]))
    g = df.groupby(["date", "ind", "g", "db"]).s
    df["med"], df["n"] = g.transform("median"), g.transform("size")
    df = df[df.n >= 4]
    return (df.s - df.med).set_axis(pd.MultiIndex.from_frame(df[["date", "codigo"]])).unstack().reindex_like(p["S"])


def _faca(p):
    """Faca caindo: spread abriu > 50 bps em 21 dias ou preço 3 pontos abaixo do máximo de 63 dias (só preços negociados)."""
    if "faca" not in _P:
        _P["faca"] = ((p["prem"] - p["prem"].shift(21)) > .5) | (p["Pf"] < p["Pf"].rolling(63, min_periods=1).max() - 3)
    return _P["faca"]


def vr_pares(pares="setor", x=1.0, filtro=0, n=20, custo_mult=1, lag=0):
    res = _res_pares(pares)
    p = painel()
    quer = res >= x
    sai = (res <= x / 4) | (p["Pf"] < 70)
    if filtro:
        quer &= ~_faca(p)
    return livro(quer, sai, res, n, C_DEB * custo_mult, lag, max_dias=252,
                 chave=_chave("vr_pares", custo_mult, lag, pares=pares, x=x, filtro=filtro, n=n))


# =============================================================================== 2. irmãos: mesmo emissor, mesmo indexador
def _res_irmaos():
    p = painel()
    S = p["S"].where(p["elig"] & (p["Pf"] >= 85))
    df = _long(S, "s").reset_index()
    df["D"] = _long(p["D"].where(S.notna()), "D").to_numpy()
    df["e"] = df.codigo.map(p["raiz"]) + df.codigo.map(p["ind"])
    g = df.groupby(["date", "e"])
    n = g.s.transform("size")
    df["res"] = df.s - (g.s.transform("sum") - df.s) / (n - 1)
    df["dD"] = df.D - (g.D.transform("sum") - df.D) / (n - 1)
    df = df[(n >= 2) & (df.dD.abs() <= 2.5)]
    return df.set_index(["date", "codigo"]).res.unstack().reindex_like(p["S"])


def irmaos(x=.4, n=15, custo_mult=1, lag=0):
    res = _res_irmaos()
    return livro(res >= x, res <= .05, res, n, C_DEB * custo_mult, lag, max_dias=252, chave=_chave("irmaos", custo_mult, lag, x=x, n=n))


# =============================================================================== 3. carry com filtro de qualidade
def carry(n=20, filtro=1, liq=5e6, custo_mult=1, lag=0):
    p = painel()
    S, Pf = p["S"], p["Pf"]
    faca = _faca(p)
    base = p["elig"] & (p["fin63"] >= liq) & (Pf >= 90) & (S < 8)
    if filtro:
        base &= ~faca
    rk = S.where(base).rank(axis=1, ascending=False)
    quer = rk <= n
    sai = (p["elig"] & ~(rk <= 2 * n)) | (faca if filtro else False)
    return livro(quer, sai, S.where(base), n, C_DEB * custo_mult, lag, chave=_chave("carry", custo_mult, lag, n=n, filtro=filtro, liq=liq))


# =============================================================================== 4. distressed / recuperação
RJ_CAT = ("Informações de Companhias em Recuperação Judicial ou Extrajudicial", "Pedidos de falência", "Sentença de Falência",
          "Informações Companhias em Falência")
RJ_FR = r"(ajuizamento|pedido|protocolo|requerimento|deferimento|petição|ajuizou|ajuíza).{0,40}recupera[çc][ãa]o (judicial|extrajudicial)"
# grupos em que a debênture é de uma subsidiária com outro CNPJ: casa pelo nome (só estes, para não pegar "VALE", "RIO" etc.)
GRUPOS = {"LIGHT", "AMERICANAS", "AMBIPAR", "RAIZEN", "RAÍZEN", "INTERCEMENT", "UNIGEL", "SEQUOIA", "KORA", "BRASKEM", "ONCOCLINICAS",
          "ONCOCLÍNICAS", "CASAS", "OI", "GOL", "AZUL", "ALLIANCA", "ALLIANÇA", "AGROGALAXY", "SOUTHROCK", "COSAN"}
_STOP = {"COMPANHIA", "CIA", "S.A.", "SA", "S/A", "DE", "DO", "DA", "GRUPO"}


def _tok(nome):
    for w in re.sub(r"[^A-ZÀ-Ú0-9 ]", " ", str(nome).upper()).split():
        if w not in _STOP and len(w) >= 2:
            return w
    return None


def eventos_rj():
    """Por debênture: data de ENTREGA à CVM (IPE) do 1º documento de RJ/RE/falência do emissor e da aprovação do plano.
    Regra estrita: categoria 'Informações de Companhias em RJ/RE' (ou falência) ou Fato Relevante de ajuizamento/pedido —
    comunicados que só citam RJ de terceiros (Vale/Samarco, Equatorial/CELPA, Natura/Avon) não contam.
    Casa por raiz do CNPJ; para subsidiárias, pelo nome do grupo (lista GRUPOS: Light SESA -> Light S.A.)."""
    if "rj" in _P:
        return _P["rj"]
    i = dc.ipe()
    a = i.Assunto.fillna("").str.lower()
    m_rj = i.Categoria.isin(RJ_CAT) | (i.Categoria.eq("Fato Relevante") & a.str.contains(RJ_FR))
    rj = i[m_rj].groupby("cnpj").Data_Entrega.min()
    m_pl = (i.Categoria.isin(RJ_CAT) | i.Categoria.eq("Fato Relevante")) & a.str.contains("plano") &         a.str.contains("aprova|homolog|confirma|concess") & i.cnpj.isin(rj.index)
    pl = i[m_pl].groupby("cnpj").Data_Entrega.min()
    nomes = i.drop_duplicates("cnpj").set_index("cnpj").Nome_Companhia
    tk_rj, tk_pl = {}, {}
    for ser, dst in ((rj, tk_rj), (pl, tk_pl)):
        for c, d0 in ser.items():
            t = _tok(nomes.get(c, ""))
            if t in GRUPOS:
                dst[t] = min(d0, dst.get(t, d0))
    p = painel()
    cad = p["cad"]
    raiz_rj = rj.groupby(rj.index.str[:8]).min()
    raiz_pl = pl.groupby(pl.index.str[:8]).min()
    d_rj, d_pl = {}, {}
    for k in cad.index:
        r8, t = p["raiz"][k], _tok(cad.empresa[k])
        for src_r, src_t, dst in ((raiz_rj, tk_rj, d_rj), (raiz_pl, tk_pl, d_pl)):
            xs = [x for x in (src_r.get(r8, pd.NaT), src_t.get(t, pd.NaT)) if pd.notna(x)]
            dst[k] = min(xs) if xs else pd.NaT
    ev = pd.DataFrame({"rj": pd.Series(d_rj), "plano": pd.Series(d_pl)})
    ev.loc[~(ev.plano >= ev.rj), "plano"] = pd.NaT                         # plano só vale depois do pedido
    _P["rj"] = ev
    return ev


def preco_balcao():
    """Preço de crédito implícito na taxa mediana negociada no balcão B3 nos últimos 5 pregões (2023+): DI+ -> exp(-(taxa-spread
    de emissão) x D); IPCA+ -> exp(-(taxa - NTN-B(D) - 1,5) x D). NaN se não houve negócio ou o papel é %CDI/pré."""
    if "pcb" in _P:
        return _P["pcb"]
    p = painel()
    g = fluxo_balcao()
    TX = g.pivot_table(index="date", columns="codigo", values="tx").reindex(index=p["dias"], columns=p["P"].columns).ffill(limit=5)
    cad, Dd = p["cad"], p["D"]
    j = cad.juros.astype(float)
    pc = pd.DataFrame(np.nan, index=TX.index, columns=TX.columns)
    di = cad.index[cad.indice.eq("DI") & (cad.pct.isna() | cad.pct.eq(100))]
    pc[di] = 100 * np.exp(-(TX[di] - j[di]).clip(lower=0) * Dd[di] / 100)
    ip = _P["dapD"].columns
    pc[ip] = 100 * np.exp(-(TX[ip] - _P["dapD"] - 1.5).clip(lower=0) * Dd[ip] / 100)
    _P["pcb"] = pc
    return pc


def distressed(thr=75, modo="sem_rj", custo_mult=1, lag=0):
    p = painel()
    Pf, dias = p["Pf"], p["dias"]
    ev = eventos_rj().reindex(Pf.columns)
    em_rj = pd.DataFrame({k: dias >= ev.rj[k] if pd.notna(ev.rj[k]) else np.zeros(len(dias), bool) for k in Pf.columns}, index=dias)
    plano = pd.DataFrame({k: dias >= ev.plano[k] if pd.notna(ev.plano[k]) else np.zeros(len(dias), bool) for k in Pf.columns}, index=dias)
    # "preço de crédito": DI -> %PU da curva; IPCA+ -> o que o spread sobre a NTN-B (acima de 1,5 pp) tira do PU. Um IPCA+ longo a
    # 75% da curva pode ser só juro real que subiu (CSN Mineração 2024), não calote.
    pc = Pf.copy()
    ipc = p["ind"].eq("IPCA").reindex(Pf.columns).to_numpy()
    pc.loc[:, ipc] = 100 * np.exp(-(p["S"].loc[:, ipc] - 1.5).clip(lower=0) * p["D"].loc[:, ipc] / 100)
    pc = pc.where(p["ind"].isin(["DI", "IPCA"]).reindex(Pf.columns).to_numpy()[None, :].repeat(len(dias), 0))
    caiu = pc.where(p["obs"]).rolling(252, min_periods=1).max().shift(1) >= 90
    quer = p["obs"] & (pc <= thr) & (pc >= 10) & caiu & (p["T"] > .25) & (p["fin21"] >= 5e5)
    # confirmação pelo balcão B3 (2023-04+): a TAXA negociada também tem de implicar preço de crédito <= thr+5. O %PU da curva do
    # SND erra em amortização (UNIP15 "66%" com PU par não amortizado; TAEE17 alterna 79/57 com PU estável) — sem isso o livro
    # "ganhava" 50% em Unipar e 33% em Taesa, que nunca estiveram estressadas.
    quer &= (dias < pd.Timestamp("2023-04-01"))[:, None] | (preco_balcao() <= thr + 5)
    sai = pc >= 95
    if modo == "sem_rj":
        quer &= ~em_rj
        sai |= em_rj
    elif modo == "sem_rj_ou_plano":
        quer &= ~em_rj | plano
        sai |= em_rj & ~plano
    return livro(quer, sai, -pc, 10, C_HY * custo_mult, lag, max_dias=504, chave=_chave("distressed", custo_mult, lag, thr=thr, modo=modo))


# =============================================================================== 5. fluxo no balcão (2023+)
def fluxo_balcao():
    if "fluxo" in _P:
        return _P["fluxo"]
    f = D / "credito_fluxo_balcao.parquet"
    if f.exists():
        _P["fluxo"] = pd.read_parquet(f)
        return _P["fluxo"]
    b = pd.read_parquet(DQ / "balcao.parquet", columns=["date", "tipo", "codigo", "qtd", "pu", "vol", "taxa"], filters=[("tipo", "==", "DEB")])
    b = b.drop_duplicates(["date", "codigo", "qtd", "pu", "taxa"])
    b = b[(b.taxa > -5) & (b.taxa < 300) & (b.vol > 0)]
    dia = b.groupby(["codigo", "date"]).agg(tx_med=("taxa", "median"), vol=("vol", "sum"), n=("taxa", "size")).reset_index().sort_values(["codigo", "date"])
    dia["ref"] = dia.groupby("codigo").tx_med.shift(1)                     # taxa mediana do pregão ANTERIOR do papel
    b = b.merge(dia[["codigo", "date", "ref"]], on=["codigo", "date"])
    sg = np.sign(b.ref - b.taxa).where((b.ref - b.taxa).abs() > .01, 0)   # taxa abaixo da referência = comprador pagou
    b["vs"] = b.vol * sg
    g = b.groupby(["date", "codigo"]).agg(vs=("vs", "sum"), vol=("vol", "sum"), n=("vs", "size"), tx=("taxa", "median")).reset_index()
    g.to_parquet(f)
    _P["fluxo"] = g
    return g


def fluxo(lado="momento", n=20, janela=21, custo_mult=1, lag=0):
    p = painel()
    g = fluxo_balcao()
    dias, cols = p["dias"], p["P"].columns
    VS = g.pivot_table(index="date", columns="codigo", values="vs").reindex(index=dias, columns=cols).fillna(0)
    VO = g.pivot_table(index="date", columns="codigo", values="vol").reindex(index=dias, columns=cols).fillna(0)
    NN = g.pivot_table(index="date", columns="codigo", values="n").reindex(index=dias, columns=cols).fillna(0)
    pr = VS.rolling(janela).sum() / VO.rolling(janela).sum().replace(0, np.nan)
    ok = (NN.rolling(janela).sum() >= 10) & p["elig"] & (p["Pf"] >= 85)
    pr = pr.where(ok)
    if lado == "momento":
        quer, sai, pri = pr >= .3, pr.fillna(0) < 0, pr
    else:
        quer, sai, pri = pr <= -.3, pr.fillna(0) > 0, -pr
    return livro(quer, sai, pri, n, C_DEB * custo_mult, lag, max_dias=63, chave=_chave("fluxo", custo_mult, lag, lado=lado, n=n, janela=janela))


# =============================================================================== 6/7. crédito x ação do mesmo emissor
def _acoes():
    if "acoes" in _P:
        return _P["acoes"]
    p = painel()
    a = pd.read_parquet(DQ / "acoes_diario.parquet").reindex(p["dias"]).ffill(limit=5)
    a.columns = [str(c).zfill(14) for c in a.columns]
    ra = limpa(a.pct_change(fill_method=None)).fillna(0)
    bova = pd.read_parquet(DQ / "eq_idx.parquet")["BOVA11.SA"].reindex(p["dias"]).ffill(limit=5).pct_change(fill_method=None).fillna(0)
    rel = ra.sub(bova, axis=0).where(a.notna())                             # ação contra BOVA11 (beta 1, neutro em dinheiro)
    raiz = {c[:8]: c for c in a.columns}
    # sinal de crédito por emissor listado: mediana da variação do spread em 21 dias dos papéis negociados
    dprem = (p["prem"] - p["prem"].shift(21)).where(p["elig"] & (p["Pf"] >= 80) & (p["Pf"].shift(21) >= 80)).clip(-3, 3)
    m = {}
    for k, r8 in p["raiz"].items():
        if r8 in raiz and k in dprem.columns:
            m.setdefault(raiz[r8], []).append(k)
    cs = pd.DataFrame({c: dprem[ks].median(axis=1) for c, ks in m.items()}).reindex(p["dias"])
    _P["acoes"] = (rel, cs, m)
    return _P["acoes"]


def credito_acao(x=.5, h=21, lado="ambos", custo_mult=1, lag=0):
    """Spread do emissor abriu e a ação ainda não caiu -> vende a ação contra BOVA11 por h dias (e o espelho comprado)."""
    rel, cs, _ = _acoes()
    cr = np.log1p(rel.fillna(0)).rolling(21).sum().where(rel.notna())
    cs = cs.reindex(columns=rel.columns)
    venda = (cs >= x) & (cr > -.05)
    compra = (cs <= -x) & (cr < .05)
    sig = venda.astype(float) * -1 + (compra.astype(float) if lado == "ambos" else 0)
    ev = sig.where(sig != 0)
    W = ev.ffill(limit=h - 1).fillna(0) * .1                               # 10% do PL por ideia, mantém h dias
    W = W.div((W.abs().sum(axis=1) / 1.0).clip(lower=1), axis=0)           # bruto máximo 100%
    R = rel.reindex(DIAS).fillna(0)
    Wd = semanal(W.reindex(DIAS).fillna(0))                                # revisa às sextas: menos giro
    serie = carteira(Wd, R, C_ACAO * custo_mult, lag, aluguel=.02)
    ch = _chave("credito_acao", custo_mult, lag, x=x, h=h, lado=lado)
    if ch:
        _episodios(Wd, R, ch, cs, cr)
    return serie


def _episodios(W, R, chave, cs, cr):
    We = W.shift(1).fillna(0)                                               # peso executado (carteira() desloca 1 dia)
    C = We.shift(1).fillna(0) * R - We.diff().abs().fillna(0) * C_ACAO
    usados = C.columns[C.abs().sum() > 0]
    C = C[usados]
    nomes = dc.cad_cia().drop_duplicates("cnpj").set_index("cnpj").DENOM_SOCIAL
    tr = []
    for c in usados:
        s = np.sign(We[c])
        blocos = (s != s.shift()).cumsum()
        for _, seg in s[s != 0].groupby(blocos[s != 0]):
            i0, i1 = seg.index[0], seg.index[-1]
            r = R[c].loc[i0:i1].iloc[1:]
            tr.append((c, nomes.get(c, c), "vendido" if seg.iloc[0] < 0 else "comprado", i0, i1, len(seg),
                       float(np.prod(1 + np.sign(seg.iloc[0]) * r) - 1), C[c].loc[i0:i1].sum() + C[c].shift(-1).loc[i1:i1].sum(),
                       cs[c].loc[:i0].iloc[-2] if c in cs and len(cs[c].loc[:i0]) > 1 else np.nan))
    CACHE[chave] = (C, pd.DataFrame(tr, columns=["ativo", "emissor", "lado", "entrada", "saida", "dias", "retorno", "contrib", "dspread_21d_pp"]))


def acao_credito(thr=.15, h=126, custo_mult=1, lag=0):
    """A ação do emissor subiu forte contra o Ibovespa e o spread das debêntures ainda não fechou -> compra a debênture."""
    p = painel()
    rel, cs, m = _acoes()
    cr63 = np.log1p(rel.fillna(0)).rolling(63).sum().where(rel.notna())
    cs63 = {}
    dprem63 = (p["prem"] - p["prem"].shift(63))
    quer = pd.DataFrame(False, index=p["dias"], columns=p["P"].columns)
    for c, ks in m.items():
        sinal = (cr63[c] >= thr)
        q = p["elig"][ks] & (dprem63[ks] > -.1) & (p["Pf"][ks] >= 85)
        quer[ks] = q.mul(sinal, axis=0)
    sai = dprem63 < -.3
    return livro(quer, sai, p["S"], 10, C_DEB * custo_mult, lag, max_dias=h, chave=_chave("acao_credito", custo_mult, lag, thr=thr, h=h))


# =============================================================================== 8. incentivadas IPCA+ contra NTN-B (hedge DAP)
def ipca_ntnb(modo="papel", z=1.0, so_incent=1, custo_mult=1, lag=0):
    p = painel()
    S = p["S"]
    ip = p["ind"].eq("IPCA")
    if so_incent:
        ip &= p["cad"].incentivada.reindex(S.columns).fillna(False)
    cols = ip[ip].index
    base = p["elig"][cols] & (p["Pf"][cols] >= 85) & (S[cols] < 6)
    Sx = S[cols]
    if modo == "papel":
        so = Sx.where(p["obs"][cols])                                       # histórico só com dias de negócio
        mu = so.rolling(252, min_periods=30).mean().shift(1)
        sd = so.rolling(252, min_periods=30).std().shift(1)
        zz = ((Sx - mu) / sd).where(base)
        quer, sai, pri = zz >= z, zz <= 0, zz
    else:                                                                   # o mercado todo está largo contra a NTN-B
        M = Sx.where(base).median(axis=1)
        mz = (M - M.expanding(126).mean().shift(1)) / M.expanding(126).std().shift(1)
        top = p["fin63"][cols].where(base).rank(axis=1, ascending=False) <= 15
        quer = top.mul(mz >= z, axis=0)
        sai = pd.DataFrame(np.repeat((mz <= 0).to_numpy()[:, None], len(cols), 1), index=Sx.index, columns=cols)
        pri = p["fin63"][cols]
    return livro(quer, sai, pri, 15, C_DEB * custo_mult, lag, max_dias=252 if modo == "papel" else None,
                 chave=_chave("ipca_ntnb", custo_mult, lag, modo=modo, z=z, so_incent=so_incent))


# =============================================================================== 9. FIIs de papel com desconto ao VP
def fii_painel():
    if "fii" in _P:
        return _P["fii"]
    f = dc.fii()
    f = f[f.Codigo_ISIN.notna() & f.Valor_Patrimonial_Cotas.gt(0)].copy()
    f["tk"] = f.Codigo_ISIN.str[2:6] + "11"
    seg = f.groupby("tk").apply(lambda x: (x.Segmento_Atuacao.eq("Títulos e Val. Mob.") | x.Mandato.eq("Títulos e Valores Mobiliários")).mean())
    papel = seg[seg >= .5].index.tolist()
    f = f[f.tk.isin(papel)]
    v = pd.read_parquet(D / "b3_vista.parquet", columns=["data", "ticker", "fech", "volume"], filters=[("ticker", "in", papel)])
    v = v[v.data >= "2018-01-01"]
    px = v.pivot_table(index="data", columns="ticker", values="fech").reindex(DIAS)
    vol = v.pivot_table(index="data", columns="ticker", values="volume").reindex(DIAS).fillna(0)
    # dividendo do mês M (DY x VP do informe) tem data-ex no 1º pregão de M+1 (confere com KNCR11 no Yahoo)
    f["div"] = f.Percentual_Dividend_Yield_Mes.clip(0, .05) * f.Valor_Patrimonial_Cotas
    prim = pd.Series(DIAS, index=DIAS).groupby(DIAS.to_period("M")).first()
    f["ex"] = (f.Data_Referencia.dt.to_period("M") + 1).map(prim)
    dv = f.dropna(subset=["ex"]).pivot_table(index="ex", columns="tk", values="div", aggfunc="sum").reindex(index=DIAS, columns=px.columns).fillna(0)
    pf = px.ffill(limit=10)
    r = (pf + dv) / pf.shift(1) - 1
    r = r.where(px.notna() & pf.shift(1).notna())
    r = r.where(r.abs() < .2)                                               # grupamentos/erros
    # VP por cota conhecido a partir da data de ENTREGA do informe
    f["disp"] = f.Data_Entrega.where(f.Data_Entrega.notna(), f.Data_Referencia + pd.offsets.MonthEnd(1) + pd.Timedelta(days=30))
    f = f.sort_values("disp")
    vp = f.pivot_table(index="disp", columns="tk", values="Valor_Patrimonial_Cotas", aggfunc="last")
    vp = vp.reindex(vp.index.union(DIAS)).ffill(limit=120).reindex(DIAS).reindex(columns=px.columns)
    pvp = pf / vp
    _P["fii"] = dict(r=r, pvp=pvp, vol21=vol.rolling(21).mean(), px=pf)
    return _P["fii"]


def fii_desconto(modo="barato", thr=.95, n=8, custo_mult=1, lag=0):
    """barato: os n FIIs de papel com menor P/VP (abaixo de thr). panico: só quando a MEDIANA do P/VP do segmento cai abaixo de thr
    (o mercado vendeu tudo), compra os n mais líquidos (os grandes, crédito high grade) que estejam abaixo do VP."""
    d = fii_painel()
    cdi = CDI.reindex(DIAS)
    ex = d["r"].sub(cdi, axis=0).fillna(0)
    ok = (d["vol21"] >= 5e5) & (d["pvp"] >= .4) & (d["pvp"] <= 1.5)
    pv = d["pvp"].where(ok)
    if modo == "barato":
        sel = (pv.rank(axis=1) <= n) & (pv <= thr)
    else:
        med = pv.median(axis=1)
        sel = (d["vol21"].where(ok & (pv <= 1.0)).rank(axis=1, ascending=False) <= n).mul(med <= thr, axis=0)
    W = mensal(sel.astype(float))
    W = W.div(n)                                                            # n vagas; o que sobra fica no CDI
    serie = carteira(W, ex, .002 * custo_mult, lag)
    ch = _chave("fii_desconto", custo_mult, lag, modo=modo, thr=thr, n=n)
    if ch:
        We = W.shift(1).fillna(0)
        C = We.shift(1).fillna(0) * ex - We.diff().abs().fillna(0) * .002
        C = C.loc[:, C.abs().sum() > 0]
        tr = []
        for c in C.columns:
            s = We[c] > 0
            bl = (s != s.shift()).cumsum()
            for _, seg in s[s].groupby(bl[s]):
                i0, i1 = seg.index[0], seg.index[-1]
                tr.append((c, i0, i1, len(seg), d["pvp"][c].loc[:i0].iloc[-2], d["pvp"][c].loc[i1],
                           float(np.prod(1 + ex[c].loc[i0:i1].iloc[1:]) - 1), C[c].loc[i0:i1].sum()))
        CACHE[ch] = (C, pd.DataFrame(tr, columns=["ativo", "entrada", "saida", "dias", "pvp_entrada", "pvp_saida", "retorno", "contrib"]))
    return serie


# =============================================================================== fundos
FUNDOS = [
    Fundo("C1 Valor relativo de spread (pares)", "Crédito", "CDI",
          "CDI+6 é demais: compro o papel cujo spread está muito acima dos pares (mesmo setor ou 'rating' de emissão, mesma duration) "
          "e vendo quando volta para perto da mediana", "Até n debêntures, 1 por emissor, pct da curva >= 85, R$1 mi/21d; sai com resíduo < x/4 ou 1 ano",
          vr_pares, {"pares": ["setor", "emissao"], "x": [1.0, 2.0], "filtro": [0, 1]}, inicio="2019-07-01", corte=CORTE),
    Fundo("C2 Irmãos do mesmo emissor", "Crédito", "CDI",
          "Duas séries do mesmo emissor e indexador, duration parecida, com spreads diferentes: o risco é o mesmo, compro a barata",
          "Compra se spread > média das irmãs + x (0,5-1 pp: abaixo disso é ruído de print); sai quando a diferença < 5 bps; até n papéis", irmaos,
          {"x": [.5, 1.0], "n": [10, 20]}, inicio="2019-07-01", corte=CORTE),
    Fundo("C3 Carry com filtro de faca caindo", "Crédito", "CDI",
          "CDI+spread paga o spread se o emissor não quebra: maiores spreads entre emissores líquidos, fora quem abriu spread recentemente",
          "Top n por spread (DI ou sobre NTN-B) com giro >= liq em 63d e pct >= 90; sai fora do top 2n ou se virar faca", carry,
          {"n": [10, 20], "filtro": [0, 1], "liq": [5e6, 2e7]}, inicio="2019-07-01", corte=CORTE),
    Fundo("C4 Distressed / recuperação", "Crédito estressado", "CDI",
          "PU abaixo de 70-80% do par em emissor sem RJ (ou com plano aprovado) é pânico, não perda: compro e vendo na recuperação (>=95%)",
          "Até 10 papéis, 1 por emissor, custo 1% por lado, sai a 95% ou em 2 anos; zera se o emissor pede RJ (data de entrega na CVM)",
          distressed, {"thr": [70, 80], "modo": ["todos", "sem_rj", "sem_rj_ou_plano"]}, inicio="2019-07-01", corte=CORTE),
    Fundo("C5 Fluxo do balcão (pressão compradora)", "Crédito", "CDI",
          "Negócios com taxa abaixo da do pregão anterior = comprador agredindo; sigo (momento) ou faço o contrário (liquidez para vendedor forçado)",
          "Pressão = volume com taxa abaixo - acima da referência / volume, janela 10-21d, balcão B3 2023+; até n papéis, máx. 63 dias",
          fluxo, {"lado": ["momento", "contrario"], "n": [10, 20], "janela": [10, 21]}, inicio="2023-05-01", corte=CORTE_B),
    Fundo("C6 Crédito antecipa ação (long-short de ações)", "Estrutura de capital", "CDI",
          "Debenturista sabe antes: spread abriu e a ação não caiu -> vendo a ação contra BOVA11; spread fechou e a ação não subiu -> compro",
          "10% do PL por ideia por h dias, ação contra BOVA11, aluguel 2% a.a., custo 20 bps por giro (2 pernas)", credito_acao,
          {"x": [.3, .75], "h": [21, 63], "lado": ["ambos", "venda"]}, inicio="2019-07-01", corte=CORTE),
    Fundo("C7 Ação antecipa crédito", "Crédito", "CDI",
          "Ação disparou contra o Ibovespa e as debêntures não fecharam spread -> compro a debênture antes do mercado de crédito",
          "Até 10 debêntures de emissores listados com ação +thr em 63d vs BOVA11 e spread estável; sai após h dias ou spread -30 bps",
          acao_credito, {"thr": [.10, .20], "h": [63, 126]}, inicio="2019-07-01", corte=CORTE),
    Fundo("C8 Incentivadas IPCA+ contra NTN-B", "Crédito", "CDI",
          "Spread sobre a NTN-B de mesma duration é largo contra o próprio histórico (papel) ou o mercado todo está largo (pós-Americanas)",
          "Debêntures IPCA+ com hedge de duration em DAP; até 15 papéis; z do spread contra 1 ano (papel) ou histórico (mercado)", ipca_ntnb,
          {"modo": ["papel", "mercado"], "z": [1.0, 1.5], "so_incent": [0, 1]}, inicio="2019-07-01", corte=CORTE),
    Fundo("C9 FIIs de papel com desconto ao VP", "Fundos listados", "CDI",
          "Em pânico o mercado vende cota de FII de CRI abaixo do valor patrimonial; compro o desconto e espero fechar (com dividendos)",
          "barato: n FIIs de papel de menor P/VP; pânico: n mais líquidos quando o P/VP mediano do segmento < thr. VP do informe CVM "
          "já entregue, giro >= R$500 mil/dia, mensal, n vagas, resto no CDI; dividendos pelo DY do informe (data-ex 1º pregão do mês)",
          fii_desconto, {"modo": ["barato", "panico"], "thr": [.90, .95], "n": [5, 10]}, inicio="2019-01-01", corte=CORTE),
]


# =============================================================================== análises para o caderno
CASOS = ["AMERICANAS", "LIGHT", "AMBIPAR", "RAIZEN", "CASAS BAHIA", "COMPANHIA BRASILEIRA DE DISTRIBUICAO", "KORA", "DIAGNOSTICOS DA AMERICA",
         "ALLIANCA", "ONCOCLINICAS", "BRASKEM", "SEQUOIA", "AERIS", "CM HOSPITALAR", "UNIPAR", "HOSPITAL ANCHIETA", "VAMOS", "LIGGA",
         "ELFA", "AZUL", "GOL ", "OI S.A", "INTERCEMENT", "UNIGEL"]


def casos_distressed():
    """Para cada emissor famoso: 1º negócio do papel mais líquido abaixo de 80% da curva, mínimo, último, e quanto rendeu
    comprar nesse 1º negócio (excesso sobre CDI, sem custo) até hoje e até o melhor ponto seguinte."""
    p = painel()
    cad, Pf, E, obs = p["cad"], p["Pf"], p["E"], p["obs"]
    ev = eventos_rj()
    lin = []
    for nm in CASOS:
        ks = [k for k in cad.index[cad.empresa.str.upper().str.contains(nm, regex=False, na=False)] if obs[k].sum() >= 5]
        if not ks:
            lin.append((nm, "sem negócios na base (dívida offshore/privada ou papéis sem preço)") + (None,) * 9)
            continue
        caiu = [k for k in ks if (Pf[k].where(obs[k]) < 80).any()]
        if not caiu:
            k = max(ks, key=lambda c: obs[c].sum())
            lin.append((nm, k, None, None, Pf[k].where(obs[k]).min(), None, Pf[k].where(obs[k]).dropna().iloc[-1], None, None,
                        ev.rj.get(k), "nunca negociou < 80%"))
            continue
        k = max(caiu, key=lambda c: obs[c].sum())
        x = Pf[k].where(obs[k])
        d0 = x[x < 80].index[0]
        dmin = x.idxmin()
        cum = (1 + E[k].loc[d0:].iloc[1:].fillna(0)).cumprod()
        lin.append((nm, k, d0.date(), round(x[d0], 1), round(x.min(), 1), dmin.date(), round(x.dropna().iloc[-1], 1),
                    round((cum.iloc[-1] - 1) * 100, 1), round((cum.max() - 1) * 100, 1), ev.rj.get(k), cad.indice[k]))
    return pd.DataFrame(lin, columns=["caso", "papel", "1º <80%", "pct entrada", "pct mínimo", "data mínimo", "pct último",
                                      "excesso até hoje %", "excesso no melhor ponto %", "RJ/RE (CVM)", "indexador"])


def analises():
    p = painel()
    E, el = p["E"], p["elig"].shift(2).fillna(False)
    out = {}
    ano = lambda s: (s.groupby(s.index.year).sum() * 100).round(2)
    out["ew"] = pd.DataFrame({ind: ano(E[c].where(el[c]).mean(axis=1)) for ind in ("DI", "IPCA") for c in [p["ind"].index[p["ind"].eq(ind)]]})
    # prêmio de isenção: spread sobre NTN-B de incentivadas x não incentivadas (IPCA, papéis elegíveis)
    ip = p["ind"].index[p["ind"].eq("IPCA")]
    inc = p["cad"].incentivada.reindex(ip).fillna(False)
    S = p["S"][ip].where(p["elig"][ip] & (p["Pf"][ip] >= 85))
    out["isencao"] = pd.DataFrame({"incentivada": S.loc[:, inc.values].median(axis=1), "não incentivada": S.loc[:, ~inc.values].median(axis=1),
                                   "n inc": S.loc[:, inc.values].notna().sum(axis=1), "n não": S.loc[:, ~inc.values].notna().sum(axis=1)}
                                  ).resample("QE").mean().round(2)
    di = p["ind"].index[p["ind"].eq("DI")]
    out["spread_di"] = p["S"][di].where(p["elig"][di] & (p["Pf"][di] >= 85)).median(axis=1).resample("QE").mean().round(2)
    # fluxo do balcão por tipo e indexador (R$ bi por trimestre)
    b = pd.read_parquet(DQ / "balcao.parquet", columns=["date", "tipo", "codigo", "vol"])
    b = b[b.tipo.isin(["DEB", "CRA", "CRI", "LF"])]
    b["grupo"] = b.tipo
    b.loc[b.tipo.eq("DEB"), "grupo"] = "DEB " + b.loc[b.tipo.eq("DEB"), "codigo"].map(p["cad"].indice).fillna("?") +         b.loc[b.tipo.eq("DEB"), "codigo"].map(p["cad"].incentivada).map({True: " incent.", False: ""}).fillna("")
    out["fluxo"] = (b.groupby([b.date.dt.to_period("Q"), "grupo"]).vol.sum().unstack() / 1e9).round(1)
    # lead-lag crédito x ação (correlações em janelas de 21 dias, sem sobreposição)
    rel, cs, m = _acoes()
    cr = np.log1p(rel.fillna(0)).rolling(21).sum().where(rel.notna())
    pts = []
    for c in cs.columns:
        if c not in cr:
            continue
        z = pd.DataFrame({"ds": cs[c], "ac": cr[c], "ds_f": cs[c].shift(-21), "ac_f": cr[c].shift(-21)}).iloc[::21].dropna()
        pts.append(z)
    z = pd.concat(pts)
    out["leadlag"] = pd.Series({"corr(Δspread 21d, ação 21d) mesmo período": z.ds.corr(z.ac),
                                "corr(Δspread passado, ação futura)  [crédito antecipa]": z.ds.corr(z.ac_f),
                                "corr(ação passada, Δspread futuro)  [ação antecipa]": z.ac.corr(z.ds_f),
                                "n janelas": len(z), "emissores": z.index.nunique()}).round(3)
    out["casos"] = casos_distressed()
    return out


def detalhe(res, arq=OUT / "ideias_credito_detalhe.txt"):
    """Relatório texto para o caderno: variantes IS/OOS, métricas, por ano, 10 melhores e 10 piores negócios."""
    p = painel()
    el, E = p["elig"].shift(2).fillna(False), p["E"]
    m = p["ind"].isin(["DI", "IPCA"]).to_numpy()
    pas = E.loc[:, m].where(el.loc[:, m]).mean(axis=1).reindex(DIAS).fillna(0)       # passivo: média dos elegíveis, sem custo
    f = lambda x: ((1 + x).prod() ** (252 / len(x)) - 1) * 100
    L = []
    for c in (CORTE, CORTE_B):
        x = pas[pas.index >= c]
        L.append(f"passivo EW elegíveis (hedge, sem custo) excesso desde {c}: {f(x):.2f}% a.a., vol {x.std() * 252 ** .5 * 100:.2f}%")
    for r in res:
        if "fundo" not in r:
            continue
        fd, A = r["fundo"], r["ativos"]
        c = pd.Timestamp(fd.corte)
        L.append(f"\n###### {fd.nome} {r['params']}")
        L.append(pd.DataFrame({"IS pp": A[A.index < c].apply(f), "OOS pp": A[A.index >= c].apply(f)}).round(1).to_string())
        ex = r["bruto"] - CDI.reindex(r["bruto"].index)
        xo, pz = ex[ex.index >= c], pas.reindex(ex[ex.index >= c].index)
        o, rb = r["oos"], r["rob"]
        L.append(f"OOS: ret {o['retorno a.a. %']:.1f} CDI {o['benchmark a.a. %']:.1f} IR {o['IR vs bench']:.2f} vol {o['vol a.a. %']:.1f} "
                 f"DD {o['pior queda %']:.1f} | P {rb['P(bater bench OOS) %']:.0f} PBO {rb['PBO %']:.0f} DSR {rb['Sharpe deflac. OOS %']:.0f} | "
                 f"beta ao passivo {np.polyfit(pz, xo, 1)[0]:.2f} corr {xo.corr(pz):.2f} | IR IS {r['is_ir']:.2f}")
        lq = r["liquido"]
        L.append("por ano (líquido - CDI, pp): " + str({y: round(float(f(g) - f(CDI.reindex(g.index))), 1) for y, g in lq.groupby(lq.index.year)}))
        t = r.get("trades")
        if t is None or not len(t):
            continue
        L.append(f"n negócios {len(t)} | acerto {(t.retorno > 0).mean() * 100:.0f}% | mediana dias {t.dias.median():.0f}")
        tt = t[[x for x in t.columns if x != "sinal"]].copy()
        for k in ("retorno", "contrib"):
            tt[k] = (tt[k] * 100).round(2)
        if "emissor" in tt:
            tt["emissor"] = tt.emissor.astype(str).str[:28]
        L.append("TOP 10\n" + tt.sort_values("contrib", ascending=False).head(10).round(2).to_string(index=False))
        L.append("PIORES 10\n" + tt.sort_values("contrib").head(10).round(2).to_string(index=False))
    open(arq, "w", encoding="utf-8").write("\n".join(L))


if __name__ == "__main__":
    from rodar import BENCH
    LOG = open(OUT / "ideias_credito_log.txt", "w", encoding="utf-8")

    def log(*a):
        s = " ".join(str(x) for x in a)
        print(s, flush=True)
        LOG.write(s + "\n")
        LOG.flush()

    so = sys.argv[1:]
    res = []
    for f in FUNDOS:
        if so and f.nome[:2] not in so:
            continue
        t = time.time()
        log(f"\n== {f.nome}")
        r = roda(f, CDI, BENCH[f.benchmark], log)
        if r is None:
            log("   sem resultado")
            continue
        CACHE.clear()
        f.func(**r["params"])                                              # refaz a escolhida só para guardar contrib/trades
        r["contrib"], r["trades"] = next(iter(CACHE.values()), (None, None))
        o, rb = r["oos"], r["rob"]
        log(f"   escolhido {r['params']} | IR IS {r['is_ir']:.2f} | OOS: {o['retorno a.a. %']:.1f}% vs CDI {o['benchmark a.a. %']:.1f}% "
            f"(IR {o['IR vs bench']:.2f}) | P(bater) {rb['P(bater bench OOS) %']:.0f}% | PBO {rb['PBO %']:.0f}% | "
            f"custo x2 {rb['OOS custo x2 (pp)']:.1f}pp | +1d {rb['OOS execução +1 dia (pp)']:.1f}pp | mediana variantes {rb['mediana OOS das variantes (pp)']:.1f}pp | {time.time() - t:.0f}s")
        res.append(r)
    for r in res:
        r["fundo"].func = None
    if not so:
        an = analises()
        with open(OUT / "ideias_credito_analises.txt", "w", encoding="utf-8") as fa:
            for k, v in an.items():
                fa.write(f"\n### {k}\n{v.to_string()}\n")
        detalhe(res)
        pickle.dump(an, open(OUT / "ideias_credito_analises.pkl", "wb"))
    nome = "ideias_credito.pkl" if not so else f"ideias_credito_{'_'.join(so)}.pkl"
    pickle.dump(res, open(OUT / nome, "wb"))
    log("pronto")
