"""
Fundos com ativos brasileiros (calendário B3). Cada função devolve o excesso diário sobre o CDI, com custos.
Custos: ações 0,08% por perna (corretagem + emolumentos + impacto), aluguel 1% a.a.; futuros 0,02%; opções pelo preço de oferta.
"""
import contextlib
import io
import sys

import numpy as np
import pandas as pd

import travas as tv
from base import (ADR, BRL_LOC, CDI, CDI_AA, D, DIAS, DQ, R_IBOV, RQ, brl, carteira, limpa, mensal, semanal, vol_alvo, TB_US, DIAS_US)

C_ACAO, ALUG = .0008, .01
_B = None


def B():
    global _B
    if _B is None:
        _B = pd.read_pickle(RQ / "base_diaria.pkl")
    return _B


# ---------------------------------------------------------------- F1, F2, F3: renda fixa sintética (box, termo, conversão)
_CAND = {}


def _cand(tipo):
    if tipo not in _CAND:
        if tipo == "box":
            o = tv.opcoes()
            tv._OPC = o[(o.oferta_compra > 0) & (o.oferta_venda >= o.oferta_compra) & (o.oferta_venda - o.oferta_compra <= .2 * o.oferta_venda)]
            v = pd.read_parquet(D / "b3_vista.parquet", columns=["data", "ticker", "fech"])
            v["raiz"] = v.ticker.str[:4]
            spot = v.groupby(["data", "raiz"]).fech.max()
            c = tv.candidatos_box(folga=0)
            c = c.join(spot.rename("s"), on=["data", "raiz"])
            c = c[(c.k1 / c.s).between(.85, 1.15) & (c.k2 / c.s).between(.85, 1.15)]   # pernas perto do dinheiro
            tv._OPC = None
        elif tipo == "conversao":
            o = tv.opcoes()
            tv._OPC = o[(o.oferta_compra > 0) & (o.oferta_venda >= o.oferta_compra)]
            c = tv.candidatos_conversao(folga=0)
            tv._OPC = None
        else:
            c = tv.candidatos_termo()
        _CAND[tipo] = c
    return _CAND[tipo]


def box(thr=.005, peso=.2, lado="compra", custo_mult=1, lag=0):
    return tv.trava(_cand("box"), thr=thr, peso=peso, teto=1.0, lag=lag, lado=lado, teto_spread=.03, custo_mult=custo_mult)


def termo(thr=.01, peso=.1, custo_mult=1, lag=0):
    return tv.trava(_cand("termo"), thr=thr, peso=peso, teto=1.0, lag=lag, teto_spread=.08, custo_mult=custo_mult)


def conversao(thr=.005, peso=.2, custo_mult=1, lag=0):
    return tv.trava(_cand("conversao"), thr=thr, peso=peso, teto=1.0, lag=lag, teto_spread=.03, custo_mult=custo_mult)


# ---------------------------------------------------------------- F4: ADR x ação local (câmbio pelo dólar futuro de fechamento)
PARES_ADR = {"PBR": ("PETR3", 2), "PBR-A": ("PETR4", 2), "VALE": ("VALE3", 1), "ITUB": ("ITUB4", 1), "BBD": ("BBDC4", 1), "ABEV": ("ABEV3", 1),
             "GGB": ("GGBR4", 1), "SBS": ("SBSP3", 1), "SID": ("CSNA3", 1), "CIG": ("CMIG4", 1), "UGP": ("UGPA3", 1), "SUZ": ("SUZB3", 1),
             "TIMB": ("TIMS3", 5), "BRFS": ("BRFS3", 1), "EBR": ("ELET3", 1)}


def _dol_fech():
    f = pd.read_parquet(DQ / "futuros.parquet", filters=[("ticker", ">=", "DOL"), ("ticker", "<", "DOM")])
    meses = {c: i + 1 for i, c in enumerate("FGHJKMNQUVXZ")}
    f["venc"] = pd.to_datetime(dict(year=2000 + f.ticker.str[-2:].astype(int), month=f.ticker.str[3].map(meses), day=1))
    f = f[f.venc > f.date].sort_values(["date", "venc"]).drop_duplicates("date")
    return (f.set_index("date").AdjstdQt / 1000).reindex(DIAS).ffill(limit=3)


def adr(z_in=2.0, janela=60, custo_mult=1, lag=0):
    fx = _dol_fech()
    loc = BRL_LOC.reindex(DIAS).ffill(limit=3)
    ad = ADR.reindex(DIAS).ffill(limit=1)
    exc_loc = limpa(loc.pct_change(fill_method=None)).sub(CDI, axis=0)
    W, R = {}, {}
    for a, (l, rat) in PARES_ADR.items():
        tl = l + ".SA"
        if a not in ad or tl not in loc:
            continue
        s = np.log(ad[a] * fx / rat) - np.log(loc[tl])
        z = (s - s.rolling(janela, min_periods=min(40, janela)).mean()) / s.rolling(janela, min_periods=min(40, janela)).std()
        pos = pd.Series(np.where(z > z_in, -1.0, np.where(z < -z_in, 1.0, np.where(z.abs() < .5, 0.0, np.nan))), index=DIAS).ffill().fillna(0)
        pos = pos.where(fx.notna(), 0)
        ex_adr = brl(limpa(ADR[a].reindex(DIAS_US).pct_change(fill_method=None)) - TB_US)   # ADR com hedge cambial
        W[a] = pos                                                         # +1: compra o ADR e vende a local
        R[a] = ex_adr - exc_loc[tl]
    W, R = pd.DataFrame(W), pd.DataFrame(R)
    W = W.div(np.maximum(W.abs().sum(axis=1), 5), axis=0)                  # até 20% do PL por par
    return carteira(W, R, 2 * C_ACAO * custo_mult, lag, ALUG / 2)


# ---------------------------------------------------------------- F5: pares ON x PN
PARES_CLASSE = [("PETR3", "PETR4"), ("ITUB3", "ITUB4"), ("BBDC3", "BBDC4"), ("GGBR3", "GGBR4"), ("ELET3", "ELET6"), ("CMIG3", "CMIG4"),
                ("USIM3", "USIM5"), ("TAEE3", "TAEE4"), ("SAPR3", "SAPR4"), ("KLBN3", "KLBN4"), ("BRAP3", "BRAP4"), ("GOAU3", "GOAU4")]


def on_pn(z_in=2.0, janela=60, custo_mult=1, lag=0):
    p = BRL_LOC.reindex(DIAS).ffill(limit=3)
    r = limpa(p.pct_change(fill_method=None))
    W, R = {}, {}
    for a, b in PARES_CLASSE:
        ta, tb = a + ".SA", b + ".SA"
        if ta not in p or tb not in p:
            continue
        s = np.log(p[ta]) - np.log(p[tb])
        z = (s - s.rolling(janela, min_periods=min(40, janela)).mean()) / s.rolling(janela, min_periods=min(40, janela)).std()
        W[a + "/" + b] = pd.Series(np.where(z > z_in, -1.0, np.where(z < -z_in, 1.0, np.where(z.abs() < .5, 0.0, np.nan))),
                                   index=DIAS).ffill().fillna(0)
        R[a + "/" + b] = r[ta] - r[tb]
    W, R = pd.DataFrame(W), pd.DataFrame(R)
    W = W.div(np.maximum(W.abs().sum(axis=1), 4), axis=0)
    return carteira(W, R, 2 * C_ACAO * custo_mult, lag, ALUG / 2)


# ---------------------------------------------------------------- F6: eurobonds brasileiros com hedge (cupom cambial)
_ES = None


def eurobonds(n=15, alav=1.0, custo_mult=1, lag=0):
    global _ES
    if _ES is None:
        sys.path.insert(0, str(RQ.parent))
        with contextlib.redirect_stdout(io.StringIO()):
            import estrategias_sinal as es
        _ES = es
    es = _ES
    r = es.livro(es.forca_eb(), es.ed.exc_eb, es.ed.PE, n, es.e.CUSTO_EXT * 2.5 * custo_mult, -9, es.emis_eb)[0].reindex(DIAS).fillna(0)
    r = r.shift(lag).fillna(0) if lag else r
    return alav * r - (alav - 1) * .01 / 252


# ---------------------------------------------------------------- F7: valor relativo em juros (borboleta e inflação implícita)
def juros_rv(z_in=1.5, janela=126, alvo=.05, custo_mult=1, lag=0):
    """Borboleta 2-5-10 anos neutra em DV01 e inflação implícita (DI 5a x DAP 5a), por reversão à média. Retorno por preço (-D x dy)."""
    c = B()["curvas"].reindex(DIAS)
    dur = lambda col, T: T / (1 + c[col].shift(1) / 100)
    rec = lambda col, T: -dur(col, T) * c[col].diff() / 100
    r2, r5, r10, rd5 = rec("DI1_2a", 2), rec("DI1_5a", 5), rec("DI1_10a", 10), rec("DAP_5a", 5)
    d2, d5, d10 = dur("DI1_2a", 2), dur("DI1_5a", 5), dur("DI1_10a", 10)
    fly = c["DI1_5a"] - (c["DI1_2a"] + c["DI1_10a"]) / 2
    be = c["DI1_5a"] - c["DAP_5a"]
    zz = lambda x: (x - x.rolling(janela, min_periods=60).mean()) / x.rolling(janela, min_periods=60).std()
    est = lambda z: pd.Series(np.where(z > z_in, 1.0, np.where(z < -z_in, -1.0, np.where(z.abs() < .3, 0.0, np.nan))), index=DIAS).ffill().fillna(0)
    R = pd.DataFrame({"fly": r5 - d5 / (2 * d2) * r2 - d5 / (2 * d10) * r10, "be": r5 - rd5}).fillna(0)
    W = pd.DataFrame({"fly": est(zz(fly)), "be": -est(zz(be))})           # fly alto: recebe 5a; inflação implícita alta: paga DI, recebe DAP
    W = vol_alvo(W, R, alvo)
    return carteira(W, R, .0002 * custo_mult, lag)


# ---------------------------------------------------------------- F8, F9: crédito local (ML) e estrutura de capital
CUSTO_LIVRO = {"conservador": .010, "moderado": .024, "high yield": .018}   # arrasto de custo estimado (a.a.) dos livros


def credito(faixa="moderado", alav=1.0, custo_mult=1, lag=0):
    c = pd.read_parquet(RQ / "credito_livros.parquet")
    modelo = {"conservador": "ridge", "moderado": "ridge", "high yield": "xgboost"}[faixa]
    r = c[(faixa, modelo)].reindex(DIAS).fillna(0)
    r = r.shift(lag).fillna(0) if lag else r
    r = r - (custo_mult - 1) * CUSTO_LIVRO[faixa] / 252 * (r != 0)
    return alav * r - (alav - 1) * .01 / 252


def estrutura_capital(h=.2, faixa="moderado", custo_mult=1, lag=0):
    cr = credito(faixa, 1.0, custo_mult, lag)
    ib = (R_IBOV - CDI).fillna(0)
    return cr - h * ib.where(cr != 0, 0) - h * .0002 * custo_mult / 21


# ---------------------------------------------------------------- F16: ações Brasil neutro (ML, universo de cada data pelo COTAHIST)
_PAINEL = None


def _painel_acoes():
    global _PAINEL
    if _PAINEL is None:
        v = pd.read_parquet(D / "b3_vista.parquet", columns=["data", "ticker", "especi", "fech", "volume"])
        v = v[v.especi.str.match(r"^(ON|PN|UNT)") & v.ticker.str.match(r"^[A-Z]{4}(3|4|5|6|11)$")]
        P = v.pivot_table(index="data", columns="ticker", values="fech").reindex(DIAS)
        V = v.pivot_table(index="data", columns="ticker", values="volume").reindex(DIAS).fillna(0)
        r = P.pct_change(fill_method=None)
        r = r.where(r.abs() < .3)                                          # desdobramentos/grupamentos sem ajuste: descarta o dia
        _PAINEL = (P, V, r)
    return _PAINEL


def acoes_neutro(modelo="combo", quantil=.1, custo_mult=1, lag=0, vol=.10):
    P, V, r = _painel_acoes()
    liq = V.rolling(63, min_periods=40).mean()
    univ = liq.rank(axis=1, ascending=False) <= 100
    lr = np.log1p(r.fillna(0))
    cum = lr.cumsum()
    ib = np.log1p(R_IBOV)
    f = {"mom12_1": cum.shift(21) - cum.shift(252), "mom3": cum - cum.shift(63), "rev1s": -(cum - cum.shift(5)), "rev1m": -(cum - cum.shift(21)),
         "vol": -r.rolling(63, min_periods=40).std(), "max21": -r.rolling(21).max(), "liq": np.log(liq + 1),
         "beta": -(r.rolling(126, min_periods=60).cov(R_IBOV) / R_IBOV.rolling(126, min_periods=60).var()),
         "pct52": (P / P.rolling(252, min_periods=150).max()), "volrel": V.rolling(5).mean() / (liq + 1)}
    sexta = DIAS[np.asarray(pd.Series(DIAS.to_period("W-FRI"), index=DIAS).ne(pd.Series(DIAS.to_period("W-FRI"), index=DIAS).shift(-1)))]
    alvo = (cum.shift(-6) - cum.shift(-1)).sub((ib.cumsum().shift(-6) - ib.cumsum().shift(-1)), axis=0)   # semana seguinte (exec t+1)
    linhas = []
    for nome, m in f.items():
        linhas.append(m.loc[sexta].where(univ.loc[sexta]).stack().rename(nome))
    df = pd.concat(linhas, axis=1)
    df["alvo"] = alvo.loc[sexta].stack()
    df = df.dropna(subset=["mom3"])
    df.index.names = ["data", "ticker"]
    feats = list(f)
    df[feats] = df.groupby(level=0)[feats].rank(pct=True)
    if modelo == "combo":
        df["score"] = df.mom12_1 + df.rev1m * .5 + df.vol * .5 + df.pct52 * .5
    else:
        from lightgbm import LGBMRegressor
        df = df.reset_index()
        df["score"] = np.nan
        datas = np.array(sorted(df.data.unique()))
        for k in range(156, len(datas), 26):                               # 3 anos de treino mínimo, re-treina a cada 6 meses
            tr = df[df.data < datas[k - 2]].dropna(subset=["alvo"])
            te = df.data.isin(datas[k:k + 26])
            m = LGBMRegressor(n_estimators=300, learning_rate=.03, num_leaves=16, min_child_samples=200, subsample=.7, subsample_freq=1,
                              colsample_bytree=.8, verbose=-1, random_state=0).fit(tr[feats].fillna(.5), tr.alvo.clip(-.2, .2))
            df.loc[te, "score"] = m.predict(df.loc[te, feats].fillna(.5))
        df = df.set_index(["data", "ticker"])
    S = df.score.unstack()
    rk = S.rank(axis=1, pct=True)
    W = (rk >= 1 - quantil).astype(float) - (rk <= quantil).astype(float)
    W = W.div(W.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0) * 2   # 100% comprado e 100% vendido
    W = W.reindex(DIAS, method="ffill").fillna(0)
    R = r.reindex(columns=W.columns).fillna(0)
    W = vol_alvo(W, R, vol, teto=1.0)                                   # vol-alvo, nunca acima de 100%/100%
    return carteira(W, R, C_ACAO * custo_mult, lag, ALUG)


# ---------------------------------------------------------------- F17: BOVA11 com proteção (collar) contra o Ibovespa
def collar(put_otm=.05, call_otm=.10, regra="tendencia", custo_mult=1, lag=0):
    o = pd.read_parquet(D / "b3_opcoes.parquet", filters=[("raiz", "=", "BOVA")])
    o = o[o.negocios > 0]
    s = BOVA_V = pd.read_parquet(D / "b3_vista.parquet", columns=["data", "ticker", "fech"], filters=[("ticker", "=", "BOVA11")]) \
        .set_index("data").fech.reindex(DIAS).ffill(limit=5)
    mm = s.rolling(200, min_periods=150).mean()
    vencs = sorted(set(pd.Series(sorted(o.venc.unique())).pipe(lambda x: x[(x.dt.day >= 14) & (x.dt.day <= 22)])))
    ov = pd.Series(0.0, index=DIAS)                                        # retorno do overlay (opções) sobre o PL
    for v0, v1 in zip(vencs[:-1], vencs[1:]):
        d0 = DIAS[DIAS > v0]
        if not len(d0) or d0[0] >= v1:
            continue
        d0 = d0[min(lag, len(d0) - 1)]
        if regra == "tendencia" and not (s.get(d0, np.nan) < mm.get(d0, np.nan)):
            continue
        S0 = s.get(d0)
        g = o[(o.data == d0) & (o.venc == v1)]
        if g.empty or not S0 == S0:
            continue
        per = DIAS[(DIAS >= d0) & (DIAS <= v1)]
        val = pd.Series(0.0, index=per)
        ok = False
        for tipo, otm, lado in (("P", put_otm, 1), ("C", call_otm, -1)):
            if otm is None:
                continue
            gg = g[g.tipo == tipo]
            if gg.empty:
                continue
            alvo = S0 * (1 - otm if tipo == "P" else 1 + otm)
            x = gg.iloc[(gg.strike - alvo).abs().argsort().iloc[0]]
            px0 = (x.oferta_venda if lado > 0 and x.oferta_venda > 0 else x.oferta_compra if lado < 0 and x.oferta_compra > 0
                   else x.fech * (1 + .03 * lado))
            hist = o[(o.serie == x.serie)].set_index("data").fech.reindex(per).ffill().fillna(px0)
            hist.iloc[0] = px0
            ST = s.reindex(per).ffill()
            hist.iloc[-1] = max(ST.iloc[-1] - x.strike, 0) if tipo == "C" else max(x.strike - ST.iloc[-1], 0)
            val += lado * (hist - px0) - abs(px0) * .002 * custo_mult * (np.arange(len(per)) == 0)
            ok = True
        if ok:
            ov.loc[per[1:]] = (val.diff().iloc[1:] / s.reindex(per).shift(1).iloc[1:]).values
    rb = limpa(s.pct_change(fill_method=None)).fillna(0)
    return (rb + ov - CDI).where(s.notna(), 0)


# ---------------------------------------------------------------- F19: macro com dados alternativos (CFTC, notícias, analistas)
def _cot_brl():
    c = pd.read_parquet(D / "cot.parquet")
    nome = [x for x in c.columns if "Market_and_Exchange" in x][0]
    dt = [x for x in c.columns if "YYYY-MM-DD" in x][0]
    c = c[c[nome].str.contains("BRAZILIAN REAL", na=False) & (c.relatorio == "fin")]
    lg = [x for x in c.columns if x.startswith("Lev_Money_Positions_Long")][0]
    sh = [x for x in c.columns if x.startswith("Lev_Money_Positions_Short")][0]
    oi = [x for x in c.columns if x.startswith("Open_Interest_All")][0]
    s = ((c[lg] - c[sh]) / c[oi]).groupby(pd.to_datetime(c[dt])).mean()
    s.index = s.index + pd.Timedelta(days=3)
    return s.reindex(DIAS, method="ffill")


def macro_alt(sinal_cot=-1, alvo=.08, custo_mult=1, lag=0):
    z = lambda x, j: (x - x.rolling(j, min_periods=j // 2).mean()) / x.rolling(j, min_periods=j // 2).std()
    cot = z(_cot_brl(), 252)                                              # especuladores comprados em real
    g = pd.read_parquet(DQ / "noticias_gdelt.parquet")
    tom = g[g.chave.str.startswith("macro_")].pivot_table(index="date", columns="chave", values="tom").mean(axis=1).reindex(DIAS).ffill()
    tom = z(tom.rolling(20).mean(), 252)
    an = pd.read_parquet(DQ / "analistas.parquet").reindex(DIAS).ffill()
    gap = -z(an["an_gap_Selic_prox"], 252) if "an_gap_Selic_prox" in an else 0 * tom   # top 5 mais 'dovish' que o consenso -> positivo
    risco = pd.concat([sinal_cot * cot, tom, gap], axis=1).mean(axis=1).clip(-2, 2) / 2   # >0: risco Brasil melhora
    b = B()
    R = pd.DataFrame({"ibov": (R_IBOV - CDI), "dol": b["r_dol"].reindex(DIAS), "di2": b["r_di2"].reindex(DIAS)}).fillna(0)
    W = pd.DataFrame({"ibov": risco, "dol": -risco, "di2": risco}).fillna(0)
    W = semanal(W)
    W = vol_alvo(W, R, alvo)
    custo = pd.Series([.0008, .0002, .0002], index=R.columns) * custo_mult
    Wx = W.shift(1 + lag).fillna(0)
    return ((Wx.shift(1) * R).sum(axis=1) - (Wx.diff().abs() * custo).sum(axis=1)).fillna(0)
