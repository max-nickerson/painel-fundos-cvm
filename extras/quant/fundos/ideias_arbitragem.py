"""
Rodada 2 — frente ARBITRAGENS ESTRUTURAIS E OPÇÕES (mesa proprietária B3).
Cada estratégia: func(**params, custo_mult=1, lag=0, detalhe=False) -> excesso diário sobre o CDI (DIAS), líquido de custos.
detalhe=True devolve (excesso, contrib, trades) para o caderno.
Dados novos: arb_dados.py (BDRs do COTAHIST, Binance, Yahoo EUA, proventos B3, ajustes IND). Mapa BDR->EUA: arb_mapa.py.
  01 BDR x ação nos EUA (prêmio/desconto com hedge)       05 Vol de evento (straddle em resultados)
  02 ETFs da B3 x NAV (IVVB11, NASD11, GOLD11, cripto)    06 Covered call PETR4/VALE3 (bench Ibovespa)
  03 Units x ações componentes                             07 Cash-and-carry cripto (futuro trimestral x spot)
  04 Venda de vol (put/strangle/put spread, delta hedge)   08 Dividendos/JCP na data-ex
                                                           09 Base IND x BOVA11 perto do vencimento
"""
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

warnings.filterwarnings("ignore")
import arb_mapa as AM
from base import CDI, CDI_AA, D, DIAS, DQ, IDX, R_IBOV, TB_US, brl, limpa

_C = {}


def _cache(k, f):
    if k not in _C:
        _C[k] = f()
    return _C[k]


# =============================================================== utilitários
def vista(tickers):
    cols = ["data", "ticker", "fech", "oferta_compra", "oferta_venda", "negocios", "volume", "fatcot"]
    tickers = list(tickers)
    v = pd.concat([pd.read_parquet(D / "b3_vista.parquet", columns=cols, filters=[("ticker", "in", tickers)]),
                   pd.read_parquet(D / "arb_bdr_vista.parquet", columns=cols, filters=[("ticker", "in", tickers)])])
    v = v.drop_duplicates(["data", "ticker"], keep="last")
    for c in ("fech", "oferta_compra", "oferta_venda"):
        v[c] = v[c] / v.fatcot.clip(lower=1)
    return {c: v.pivot_table(index="data", columns="ticker", values=c, aggfunc="last").reindex(DIAS)
            for c in ("fech", "oferta_compra", "oferta_venda", "negocios", "volume")}


def meio_spread(V, padrao=.01):
    """Meio spread relativo do fechamento (melhor oferta); sem as duas ofertas, mediana dos últimos 20 dias."""
    b, a = V["oferta_compra"], V["oferta_venda"]
    hs = ((a - b) / (a + b)).where((b > 0) & (a > 0) & (a >= b))
    hs = hs.fillna(hs.rolling(20, min_periods=1).median()).fillna(padrao)
    return hs.clip(.0001, .05)


def ret(P, lim=.25):
    return limpa(P.ffill(limit=5).pct_change(fill_method=None), lim).fillna(0)


def cart(W, R, C, lag=0, alug=0.0, neg=None):
    """W decidido em t, executado no fechamento t+1+lag SE o ativo negociou (senão mantém a posição anterior).
    C = custo por unidade de giro (DataFrame ou escalar). Devolve excesso, contribuição por ativo e pesos executados."""
    W = W.reindex(index=R.index, columns=R.columns).fillna(0).shift(1 + lag).fillna(0)
    if neg is not None:
        ok = neg.reindex(index=W.index, columns=W.columns).fillna(False).astype(bool)
        W = W.where(ok).ffill().fillna(0)
    giro = W.diff().abs().fillna(W.abs())
    C = C.reindex(index=W.index, columns=W.columns).ffill().fillna(.01) if isinstance(C, pd.DataFrame) else C
    contrib = W.shift(1).fillna(0) * R.fillna(0) - giro * C - W.clip(upper=0).abs() * alug / 252
    return contrib.sum(axis=1), contrib, W


def negocios_de(W, R, contrib, info=None):
    """Lista de negócios a partir dos pesos executados (trechos com o mesmo sinal)."""
    out = []
    for c in W.columns:
        w = W[c].values
        s = np.sign(w)
        r = R[c].fillna(0).values
        k_ = contrib[c].values
        n, i = len(w), 0
        while i < n:
            if s[i] == 0:
                i += 1
                continue
            j = i
            while j + 1 < n and s[j + 1] == s[i]:
                j += 1
            k = min(j + 1, n - 1)
            d = dict(ativo=c, lado="compra" if s[i] > 0 else "venda", entrada=W.index[i], saida=W.index[k], dias=k - i,
                     retorno=np.prod(1 + s[i] * r[i + 1:k + 1]) - 1, contrib=k_[i:k + 1].sum(), peso=abs(w[i:j + 1]).mean())
            if info is not None and c in info:
                d.update({nm: x.get(W.index[i], np.nan) for nm, x in info[c].items()})
            out.append(d)
            i = j + 1
    return pd.DataFrame(out)


def maquina(entra_l, sai_l, entra_s=None, sai_s=None, max_dias=30):
    """Estado da posição (+1/-1/0) por ativo, com saída por reversão ou prazo máximo."""
    E, X = entra_l.fillna(False).values, sai_l.fillna(True).values
    Es = entra_s.fillna(False).values if entra_s is not None else np.zeros_like(E)
    Xs = sai_s.fillna(True).values if sai_s is not None else np.ones_like(E)
    P = np.zeros(E.shape)
    for j in range(E.shape[1]):
        p, dd = 0, 0
        for t in range(E.shape[0]):
            if p == 1 and (X[t, j] or dd >= max_dias):
                p = 0
            elif p == -1 and (Xs[t, j] or dd >= max_dias):
                p = 0
            if p == 0:
                p, dd = (1, 0) if E[t, j] else (-1, 0) if Es[t, j] else (0, 0)
            else:
                dd += 1
            P[t, j] = p
    return pd.DataFrame(P, index=entra_l.index, columns=entra_l.columns)


def _dol():
    """Dólar futuro de 1º vencimento: nível (R$/US$) e retorno do mesmo contrato (sem salto de rolagem)."""
    f = pd.read_parquet(DQ / "futuros.parquet", filters=[("ticker", ">=", "DOL"), ("ticker", "<", "DOM")])
    meses = {c: i + 1 for i, c in enumerate("FGHJKMNQUVXZ")}
    f["venc"] = pd.to_datetime(dict(year=2000 + f.ticker.str[-2:].astype(int), month=f.ticker.str[3].map(meses), day=1))
    f = f[f.venc > f.date].sort_values(["date", "venc"]).drop_duplicates("date").set_index("date")
    nivel = (f.AdjstdQt / 1000).reindex(DIAS)
    r = (f.AdjstdQt / f.PrvsAdjstdQt - 1).reindex(DIAS)
    brlx = IDX.get("BRL=X")
    if brlx is None:
        brlx = pd.read_parquet(D / "y_fx.parquet")["BRL=X"]
    brlx = brlx.reindex(DIAS).ffill(limit=3)
    tb = TB_US.reindex(DIAS).ffill().fillna(0)
    r = r.fillna(brlx.pct_change(fill_method=None) - (CDI - tb))           # antes de 2019: spot Yahoo menos o carrego
    return nivel.fillna(brlx), limpa(r, .1).fillna(0), tb


def _fech_b3_utc(d):
    """Hora do fechamento da B3 em UTC: 20h com horário de verão nos EUA, 21h sem."""
    ny = pd.Timestamp(d).tz_localize("America/New_York")
    return 20 if ny.dst().total_seconds() > 0 else 21


def cripto_b3():
    """BTC e ETH no horário do fechamento da B3 (Binance, candle de 1h)."""
    c = pd.read_parquet(D / "arb_cripto_1h.parquet")
    out = {}
    for s in ("BTCUSDT", "ETHUSDT"):
        x = c[c.sym == s].set_index("t").fech
        x = x[~x.index.duplicated()]
        alvo = pd.DatetimeIndex([d + pd.Timedelta(hours=_fech_b3_utc(d) - 1) for d in DIAS])
        out[s[:3]] = pd.Series(x.reindex(alvo).values, index=DIAS)
    return pd.DataFrame(out)


# =============================================================== 01/02 BDRs e ETFs x ativo-objeto
def painel_bdr():
    def f():
        us = pd.read_parquet(D / "arb_us.parquet")
        us_ok = us.reindex(DIAS).notna()
        usd = us.reindex(DIAS).ffill(limit=3)
        cr = cripto_b3()
        ref = {}
        for b, u in AM.MAPA.items():
            if u in usd and usd[u].notna().sum() > 120:
                ref[b] = (usd[u], us_ok[u])
        for e, u in AM.ETF_B3.items():
            if u == "BTC":
                ref[e] = (cr.BTC, cr.BTC.notna())
            elif u == "ETH":
                ref[e] = (cr.ETH, cr.ETH.notna())
            elif u == "CRIPTO":                                            # HASH11 ~ índice Nasdaq Crypto: 80% BTC, 20% ETH
                lr = .8 * np.log(cr.BTC).diff() + .2 * np.log(cr.ETH).diff().fillna(np.log(cr.BTC).diff())
                ref[e] = (np.exp(lr.fillna(0).cumsum()).where(cr.BTC.notna()), cr.BTC.notna())
            else:
                ref[e] = (usd[u], us_ok[u])
        V = vista(ref)
        tk = [t for t in ref if t in V["fech"]]
        fx, rfx, tb = _dol()
        Pref = pd.DataFrame({t: ref[t][0] for t in tk})
        ok_ref = pd.DataFrame({t: ref[t][1] for t in tk})
        V = {k: x.reindex(columns=tk) for k, x in V.items()}
        q = np.log(V["fech"]) - np.log(Pref.mul(fx, axis=0))
        qa = np.log(V["oferta_venda"].where(V["oferta_venda"] > 0)) - np.log(Pref.mul(fx, axis=0))
        qb = np.log(V["oferta_compra"].where(V["oferta_compra"] > 0)) - np.log(Pref.mul(fx, axis=0))
        rb = ret(V["fech"], 9)                                           # sem limpar perna a perna: o filtro é no PAR (abaixo)
        rr = ret(Pref, 9)
        R = rb.sub(CDI, axis=0) - rr.sub(tb, axis=0) - pd.DataFrame({t: rfx for t in tk})    # BDR - ação EUA em R$ c/ hedge cambial
        R = R.where(R.abs() < .15, 0)                                    # >15% num dia no par = mudança de razão/desdobramento
        cripto = [t for t in tk if AM.ETF_B3.get(t) in ("BTC", "ETH", "CRIPTO")]
        adv = V["volume"].fillna(0).rolling(20, min_periods=5).median()
        hs = meio_spread(V, .01)
        # validação do mapa BDR->EUA (limpeza de cadastro): razão estável e retorno coerente; fora disso é mapeamento errado
        d = q.where(V["negocios"].fillna(0) > 0)
        mad = (d - d.rolling(60, min_periods=20).median()).abs().median()
        cor = rb.corr(rr.add(rfx, axis=0)) if False else pd.Series({t: rb[t].corr(rr[t] + rfx) for t in tk})
        tk = [t for t in tk if mad.get(t, 1) < .03 and cor.get(t, 0) > .3]
        q, qa, qb, R = q[tk], qa[tk], qb[tk], R[tk]
        V = {k: x[tk] for k, x in V.items()}
        ok_ref = ok_ref[tk]
        cripto = [t for t in cripto if t in tk]
        return dict(q=q, qa=qa, qb=qb, R=R, adv=adv, hs=hs, neg=V["negocios"].fillna(0) > 0, ok=ok_ref.fillna(False), V=V, tk=tk,
                    cripto=cripto)
    return _cache("bdr", f)


def premios(janela):
    def f():
        P = painel_bdr()
        q = P["q"].where(P["ok"] & P["neg"])
        salto = q.ffill().diff().abs() > .15                             # mudança de razão / desdobramento
        bloq = salto.rolling(janela, min_periods=1).max().astype(bool)
        med = q.rolling(janela, min_periods=max(10, janela // 2)).median().shift(1)
        pm = (q - med).where(~bloq)
        liq = [t for t in P["tk"] if t in AM.MAPA]
        fator = pm[liq].where(P["adv"][liq] > 1e6).median(axis=1)       # fator comum (câmbio/horário) dos BDRs líquidos
        fator = fator.where(pm[liq].where(P["adv"][liq] > 1e6).notna().sum(axis=1) >= 8, 0).fillna(0)
        pa = (P["qa"] - med).where(~bloq).sub(fator, axis=0)
        pb = (P["qb"] - med).where(~bloq).sub(fator, axis=0)
        return pm.sub(fator, axis=0), pa, pb, fator
    return _cache(("prem", janela), f)


def bdr(thr=.02, janela=60, lado="compra", universo="bdr", adv_min=5e5, custo_mult=1, lag=0, detalhe=False):
    """Compra o BDR (ou ETF da B3) com desconto sobre (ativo nos EUA x dólar), vende a ação/ETF lá fora e o dólar futuro; sai quando o
    desconto volta. Sinal no preço de oferta de venda (o que eu pagaria) do fechamento; execução no fechamento seguinte."""
    P = painel_bdr()
    pm, pa, pb, _ = premios(janela)
    if universo == "bdr":
        tk = [t for t in P["tk"] if t in AM.MAPA]
    elif universo == "etf":
        tk = [t for t in P["tk"] if t in AM.ETF_B3 and t not in P["cripto"]]
    elif universo == "cripto":
        tk = P["cripto"]
    else:
        tk = [t for t in P["tk"] if t in AM.ETF_B3]
    liq = (P["adv"][tk] > adv_min) & P["neg"][tk]
    E = (pa[tk] < -thr) & liq
    X = pm[tk] > -thr * .25
    Es = ((pb[tk] > thr) & liq) if lado == "ambos" else None
    Xs = (pm[tk] < thr * .25) if lado == "ambos" else None
    pos = maquina(E, X, Es, Xs, max_dias=20)
    W = pos.div(np.maximum(pos.abs().sum(axis=1), 10), axis=0)          # até 10% do PL por posição
    custo = (P["hs"][tk] + .0004) * custo_mult                           # meio spread do BDR + 3 bps EUA + 1 bp dólar
    alug = .04 if universo == "bdr" else .02
    exc, contrib, We = cart(W, P["R"][tk], custo, lag, alug, P["neg"][tk])
    if not detalhe:
        return exc
    info = {t: {"premio_entrada": pa[t], "adv_R$": P["adv"][t]} for t in tk}
    return exc, contrib.loc[:, contrib.abs().sum() > 0], negocios_de(We, P["R"][tk], contrib, info)


# =============================================================== 03 Units x componentes
UNITS = {"TAEE11": ("TAEE3", 1, "TAEE4", 2), "KLBN11": ("KLBN3", 1, "KLBN4", 4), "SAPR11": ("SAPR3", 1, "SAPR4", 4),
         "ENGI11": ("ENGI3", 1, "ENGI4", 4), "ALUP11": ("ALUP3", 1, "ALUP4", 2), "SANB11": ("SANB3", 1, "SANB4", 1),
         "BPAC11": ("BPAC3", 1, "BPAC5", 2), "TIET11": ("TIET3", 1, "TIET4", 4), "IGTI11": ("IGTI3", 1, "IGTI4", 2),
         "SULA11": ("SULA3", 1, "SULA4", 2), "CPLE11": ("CPLE3", 1, "CPLE6", 4), "BIDI11": ("BIDI3", 1, "BIDI4", 2),
         "MODL11": ("MODL3", 1, "MODL4", 2)}


def painel_units():
    def f():
        tks = set(UNITS) | {x[0] for x in UNITS.values()} | {x[2] for x in UNITS.values()}
        V = vista(tks)
        hs = meio_spread(V, .01)
        r = ret(V["fech"], 9)
        out = {}
        for u, (on, n, pn, m) in UNITS.items():
            if on not in V["fech"] or pn not in V["fech"]:
                continue
            F, B_, A_ = V["fech"], V["oferta_compra"].where(V["oferta_compra"] > 0), V["oferta_venda"].where(V["oferta_venda"] > 0)
            cesta = n * F[on] + m * F[pn]
            neg = (V["negocios"][[u, on, pn]].fillna(0) > 0).all(axis=1)
            a = (n * F[on] / cesta).shift(1)
            out[u] = dict(dev=np.log(F[u] / cesta).where(neg), barato=np.log(A_[u] / (n * B_[on] + m * B_[pn])),
                          caro=np.log(B_[u] / (n * A_[on] + m * A_[pn])), R=(r[u] - a * r[on] - (1 - a) * r[pn]).where(lambda x: x.abs() < .15, 0),
                          C=hs[u] + a.fillna(.5) * hs[on] + (1 - a.fillna(.5)) * hs[pn] + .001, neg=neg,
                          adv=V["volume"][[u, on, pn]].fillna(0).rolling(20, min_periods=5).median().min(axis=1))
        return out
    return _cache("units", f)


def units(thr=.01, janela=60, custo_mult=1, lag=0, detalhe=False):
    """Unit barata contra a cesta (n ON + m PN, preços de oferta executáveis): compra a unit e vende a cesta (ou o inverso).
    A diferença tem âncora física: a unit pode ser montada/desmontada no escriturador."""
    P = painel_units()
    nomes = list(P)
    df = lambda k: pd.DataFrame({u: P[u][k] for u in nomes})
    dev, R, C, neg = df("dev"), df("R"), df("C"), df("neg")
    med = dev.rolling(janela, min_periods=20).median().shift(1)
    E = (df("barato") - med < -thr) & neg & (df("adv") > 2e5)
    Es = (df("caro") - med > thr) & neg & (df("adv") > 2e5)
    X = (dev - med) > -thr * .25
    Xs = (dev - med) < thr * .25
    pos = maquina(E, X, Es, Xs, max_dias=40)
    W = pos.div(np.maximum(pos.abs().sum(axis=1), 4), axis=0)
    exc, contrib, We = cart(W, R, C * custo_mult, lag, .02, neg)        # aluguel 2% a.a. sobre a ponta vendida (aprox. pelo peso)
    exc = exc - We.clip(lower=0).sum(axis=1) * .02 / 252                # comprado na unit = vendido na cesta: também paga aluguel
    if not detalhe:
        return exc
    info = {u: {"desvio_entrada": dev[u] - med[u], "adv_R$": P[u]["adv"]} for u in nomes}
    return exc, contrib.loc[:, contrib.abs().sum() > 0], negocios_de(We, R, contrib, info)


# =============================================================== opções: base comum
SPOT_OPC = {"BOVA": "BOVA11", "PETR": "PETR4", "VALE": "VALE3", "ITUB": "ITUB4", "BBDC": "BBDC4", "BBAS": "BBAS3", "B3SA": "B3SA3",
            "ABEV": "ABEV3", "MGLU": "MGLU3", "PRIO": "PRIO3", "USIM": "USIM5", "GGBR": "GGBR4", "CSNA": "CSNA3", "WEGE": "WEGE3",
            "SUZB": "SUZB3", "COGN": "COGN3", "ITSA": "ITSA4", "LREN": "LREN3", "RENT": "RENT3", "BPAC": "BPAC11", "JBSS": "JBSS3"}


def spot_opc():
    def f():
        V = vista(SPOT_OPC.values())
        S = V["fech"].rename(columns={v: k for k, v in SPOT_OPC.items()})
        rs = ret(S)
        # retorno total (com proventos) do Yahoo quando existe; senão o preço do COTAHIST
        yl = pd.read_parquet(D / "y_br_local.parquet")
        ra = rs.copy()
        for k, v in SPOT_OPC.items():
            if v + ".SA" in yl:
                ra[k] = limpa(yl[v + ".SA"].reindex(DIAS).ffill(limit=5).pct_change(fill_method=None)).fillna(rs[k])
        return S, rs, ra
    return _cache("spot", f)


def opcoes_raiz(raiz):
    def f():
        o = pd.read_parquet(D / "b3_opcoes.parquet", filters=[("raiz", "=", raiz)])
        o = o[(o.strike > 0) & (o.venc.notna())]
        o["mensal"] = ~o.serie.str.contains("W")
        bid, ask = o.oferta_compra.where(o.oferta_compra > 0), o.oferta_venda.where(o.oferta_venda > 0)
        ask = ask.where(ask >= bid.fillna(0))
        sano = (ask - bid) <= .5 * (ask + bid) / 2 + .05                 # oferta sem sentido (ex.: venda a 99,99) não marca
        o["bid"], o["ask"] = bid, ask
        o["mid"] = ((bid + ask) / 2).where(sano).fillna(o.fech.where(o.negocios > 0))
        o["spr"] = ((ask - bid) / ((ask + bid) / 2)).where(bid.notna() & ask.notna())
        # a raiz mistura classes (VALE5 até 2017, BBDC3, PETR3...): série cujo preço viola o intrínseco do NOSSO ativo-objeto
        # em >= 20% dos dias é de outro ativo -> descartada; dias isolados com violação perdem a marcação
        S = spot_opc()[0][raiz]
        s = o.data.map(S)
        intr = np.where(o.tipo == "C", s - o.strike, o.strike - s)
        ref = np.fmax(o.mid.values, o.bid.fillna(0).values)
        bad = pd.Series(ref < intr - .03 * s, index=o.index)
        frac = bad.groupby([o.serie, o.venc]).transform("mean")
        o = o[frac < .2].copy()
        o.loc[bad[o.index], "mid"] = np.nan
        return o
    return _cache(("opc", raiz), f)


def opc_venc(raiz, v):
    """Opções mensais de um vencimento (índice pequeno para buscas rápidas)."""
    def f():
        o = opcoes_raiz(raiz)
        return {k: g for k, g in o[o.mensal].groupby("venc")}
    return _cache(("opcv", raiz), f).get(pd.Timestamp(v), pd.DataFrame(columns=opcoes_raiz(raiz).columns))


def vencs_mensais(raiz):
    def f():
        o = opcoes_raiz(raiz)
        m = o[o.mensal].groupby("venc").volume.sum()
        m = m[m > 0]
        m = m.groupby(m.index.to_period("M")).idxmax()
        return sorted(m.values)
    return _cache(("venc", raiz), f)


def _r_aa(d):
    return np.log1p(CDI_AA.get(d, .1))


def bs(S, K, T, r, s, tipo):
    s = max(s, 1e-4)
    T = max(T, 1 / 252)
    d1 = (np.log(S / K) + (r + s * s / 2) * T) / (s * np.sqrt(T))
    d2 = d1 - s * np.sqrt(T)
    if tipo == "C":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2), norm.cdf(d1)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1), norm.cdf(d1) - 1


def iv(p, S, K, T, r, tipo):
    intr = max(S - K * np.exp(-r * T), 0) if tipo == "C" else max(K * np.exp(-r * T) - S, 0)
    if not (p > intr + 1e-6) or not np.isfinite(p):
        return np.nan
    try:
        return brentq(lambda s: bs(S, K, T, r, s, tipo)[0] - p, 1e-3, 5.0, xtol=1e-5)
    except ValueError:
        return np.nan


def du(a, b):
    return int(np.busday_count(np.datetime64(a, "D"), np.datetime64(b, "D")))


def escolhe(g, alvo, tipo, lado):
    """Opção do tipo com strike mais perto de alvo que tenha oferta do lado em que vou agredir."""
    col = "bid" if lado < 0 else "ask"
    x = g[(g.tipo == tipo) & g[col].notna() & (g.spr <= .25)]           # só agride livro com spread razoável (<= 25% do meio)
    if x.empty:
        return None
    return x.iloc[(x.strike - alvo).abs().argsort().iloc[0]]


def iv_atm(g, S, T, r):
    vs = []
    for tp in ("C", "P"):
        x = g[(g.tipo == tp) & g.mid.notna()]
        if len(x):
            y = x.iloc[(x.strike - S).abs().argsort().iloc[0]]
            if abs(y.strike / S - 1) < .05:
                vs.append(iv(y.mid, S, y.strike, T, r, tp))
    vs = [v for v in vs if v == v]
    return np.mean(vs) if vs else np.nan


def ciclo_opcoes(raiz, d0, v, pernas, nocional, hedge, custo_mult, S, ra):
    """Simula um ciclo: pernas = [(tipo, strike-alvo/S0, sinal -1 vende/+1 compra)]. Devolve P&L diário (fração do PL) e resumo."""
    o = opc_venc(raiz, v)
    g = o[o.data == d0]
    S0 = S[raiz].get(d0, np.nan)
    if g.empty or not S0 == S0:
        return None
    r = _r_aa(d0)
    T0 = max(du(d0, v), 1) / 252
    dias = DIAS[(DIAS >= d0) & (DIAS <= v)]
    if len(dias) < 3:
        return None
    St = S[raiz].reindex(dias).ffill()
    pnl = pd.Series(0.0, index=dias)
    delta_tot = pd.Series(0.0, index=dias)
    resumo = dict(raiz=raiz, entrada=d0, venc=v, S0=S0, pernas=[], premio=0.0, payoff=0.0)
    q = nocional / S0
    for tipo, k_rel, sg in pernas:
        x = escolhe(g, S0 * k_rel, tipo, sg)
        if x is None:
            return None
        mid = x.mid if x.mid == x.mid else x.fech
        exe = x.bid if sg < 0 else x.ask
        preco = mid - custo_mult * (mid - exe) if mid == mid else exe
        taxa = .001 * preco * custo_mult                                 # emolumentos/corretagem sobre o prêmio
        hist = o[o.serie == x.serie].drop_duplicates("data").set_index("data")
        mk = hist.mid.reindex(dias).ffill()
        mk.iloc[0] = preco
        Kf = hist.strike.reindex(dias).ffill().iloc[-1]
        ST = St.iloc[-1]
        intr = max(ST - Kf, 0) if tipo == "C" else max(Kf - ST, 0)
        mk.iloc[-1] = intr
        Kt = hist.strike.reindex(dias).ffill().fillna(x.strike)
        mk = mk.ffill()
        teto = St.values if tipo == "C" else Kt.values                     # call <= S, put <= K
        mk = pd.Series(np.minimum(np.maximum(mk.values, np.clip((St - Kt).values if tipo == "C" else (Kt - St).values, 0, None)), teto),
                       index=dias)
        mk.iloc[0] = preco
        pnl += sg * q * mk.diff().fillna(0)
        pnl.iloc[0] -= q * taxa
        if intr > 0:
            pnl.iloc[-1] -= q * .0005 * ST * custo_mult                   # exercício: liquida o ativo
        s_iv = iv(mid if mid == mid else preco, S0, x.strike, T0, r, tipo)
        if hedge:
            sig = s_iv if s_iv == s_iv else .3
            for i, d in enumerate(dias[:-1]):
                T = max(du(d, v), 1) / 252
                delta_tot.iloc[i] += sg * q * bs(St.iloc[i], Kt.iloc[i], T, r, sig, tipo)[1]
        resumo["pernas"].append(f"{'V' if sg < 0 else 'C'} {tipo} {x.strike:.2f} ({x.serie}) @ {preco:.2f} iv {s_iv:.0%}")
        resumo["premio"] += -sg * q * preco
        resumo["payoff"] += sg * q * intr
    if hedge:
        H = -delta_tot                                                   # ações para neutralizar o delta (em quantidade)
        expo = (H * St).shift(1).fillna(0)                               # R$ por PL
        rr = ra[raiz].reindex(dias).fillna(0) - CDI.reindex(dias).fillna(0)
        pnl += expo * rr - (H * St).diff().abs().fillna((H * St).abs()) * .0005 * custo_mult - expo.clip(upper=0).abs() * .01 / 252
        pnl.iloc[-1] -= abs(H.iloc[-2] * St.iloc[-1]) * .0005 * custo_mult if len(H) > 1 else 0
    resumo["pnl"] = pnl.sum()
    return pnl, resumo


def _sinais_ciclo(raiz, ds, v, S, ra):
    o = opc_venc(raiz, v)
    g = o[o.data == ds]
    S0 = S[raiz].get(ds, np.nan)
    if g.empty or not S0 == S0:
        return np.nan, np.nan, np.nan
    T, r = max(du(ds, v), 1) / 252, _r_aa(ds)
    a = iv_atm(g, S0, T, r)
    x = g[(g.tipo == "P") & g.mid.notna()]
    sk = np.nan
    if len(x):
        y = x.iloc[(x.strike - .9 * S0).abs().argsort().iloc[0]]
        if abs(y.strike / S0 - .9) < .03:
            sk = iv(y.mid, S0, y.strike, T, r, "P") - a
    rv = ra[raiz].loc[:ds].tail(21).std() * np.sqrt(252)
    return a, rv, sk


def ciclos(raiz):
    """Datas de sinal (1º pregão após o vencimento mensal) e o próximo vencimento mensal, com IV ATM, RV 21d e skew 90%."""
    def f():
        S, rs, ra = spot_opc()
        vs = [v for v in vencs_mensais(raiz) if v >= pd.Timestamp("2014-02-01")]
        out = []
        for v0, v1 in zip(vs[:-1], vs[1:]):
            d = DIAS[DIAS > v0]
            if len(d) < 2 or d[0] >= v1:
                continue
            a, rv, sk = _sinais_ciclo(raiz, d[0], v1, S, ra)
            out.append(dict(raiz=raiz, ds=d[0], v=v1, iv=a, rv=rv, skew90=sk))
        c = pd.DataFrame(out)
        c["iv_rv"] = c.iv - c.rv
        c["iv_med"] = c.iv.rolling(12, min_periods=6).median().shift(1)
        c["skew_med"] = c.skew90.rolling(12, min_periods=6).median().shift(1)
        c["ivrv_med"] = c.iv_rv.rolling(12, min_periods=6).median().shift(1)
        return c
    return _cache(("ciclos", raiz), f)


def _executa_ciclos(ativos, pernas_f, filtro_f, nocional, hedge, custo_mult, lag):
    S, rs, ra = spot_opc()
    exc = pd.Series(0.0, index=DIAS)
    contrib, trades = {}, []
    for raiz in ativos:
        c = ciclos(raiz)
        cs = pd.Series(0.0, index=DIAS)
        for _, z in c.iterrows():
            if not filtro_f(z):
                continue
            d = DIAS[DIAS > z.ds]
            if len(d) <= lag:
                continue
            d0 = d[lag]                                                  # executa no pregão seguinte ao sinal
            if d0 >= z.v:
                continue
            res = ciclo_opcoes(raiz, d0, z.v, pernas_f(z), nocional / len(ativos), hedge, custo_mult, S, ra)
            if res is None:
                continue
            pnl, rsm = res
            cs.loc[pnl.index[1:]] += pnl.iloc[1:].values
            cs.loc[pnl.index[0]] += pnl.iloc[0]
            rsm.update(iv=z.iv, rv=z.rv, skew=z.skew90, pernas=" | ".join(rsm["pernas"]))
            trades.append(rsm)
        contrib[raiz] = cs
        exc += cs
    tr = pd.DataFrame(trades)
    if len(tr):
        tr = tr.rename(columns={"raiz": "ativo", "venc": "saida", "pnl": "contrib"})
        tr["dias"] = [du(a, b) for a, b in zip(tr.entrada, tr.saida)]
        tr["retorno"] = tr.contrib
    return exc, pd.DataFrame(contrib), tr


VOL_ATIVOS = ["BOVA", "PETR", "VALE", "ITUB", "BBDC"]


def venda_vol(estrutura="put", otm=.05, filtro="sempre", hedge=False, nocional=1.0, custo_mult=1, lag=0, detalhe=False):
    """Vende opções de ~1 mês (preço de oferta de compra) em BOVA11, PETR4, VALE3, ITUB4, BBDC4; segura até o vencimento.
    put: vende put (1-otm); strangle: + call (1+otm); put_spread: vende put (1-otm) e compra put (1-2*otm).
    filtro: sempre | iv_rv (IV-RV acima da mediana dos 12 ciclos anteriores) | skew (skew 90% acima da mediana)."""
    pernas = {"put": [("P", 1 - otm, -1)], "strangle": [("P", 1 - otm, -1), ("C", 1 + otm, -1)],
              "put_spread": [("P", 1 - otm, -1), ("P", 1 - 2 * otm, 1)]}[estrutura]
    filt = {"sempre": lambda z: True, "iv_rv": lambda z: z.iv_rv > z.ivrv_med, "skew": lambda z: z.skew90 > z.skew_med}[filtro]
    exc, contrib, tr = _executa_ciclos(VOL_ATIVOS, lambda z: pernas, filt, nocional, hedge, custo_mult, lag)
    return (exc, contrib, tr) if detalhe else exc


def covered_call(otm=.05, filtro="sempre", custo_mult=1, lag=0, detalhe=False):
    """Comprado em PETR4 e VALE3 (50/50, retorno total) vendendo call de ~1 mês (1+otm) no bid; filtro iv_alta = só quando a IV
    ATM está acima da mediana dos 12 ciclos anteriores."""
    S, rs, ra = spot_opc()
    filt = {"sempre": lambda z: True, "iv_alta": lambda z: z.iv > z.iv_med}[filtro]
    ov, contrib, tr = _executa_ciclos(["PETR", "VALE"], lambda z: [("C", 1 + otm, -1)], filt, 1.0, False, custo_mult, lag)
    acoes = (ra[["PETR", "VALE"]].mean(axis=1) - CDI)
    ini = contrib.index[(contrib.abs().sum(axis=1) > 0)][0]
    exc = (acoes + ov).where(DIAS >= ini, 0)
    if not detalhe:
        return exc
    contrib["acoes"] = acoes.where(DIAS >= ini, 0)
    return exc, contrib, tr


# =============================================================== 05 Vol de evento (resultados trimestrais)
CVM_RAIZ = {"009512": "PETR", "004170": "VALE", "019348": "ITUB", "000906": "BBDC", "001023": "BBAS", "021610": "B3SA", "023264": "ABEV",
            "022470": "MGLU", "022187": "PRIO", "014320": "USIM", "003980": "GGBR", "004030": "CSNA", "005410": "WEGE", "013986": "SUZB",
            "017973": "COGN", "007617": "ITSA", "008133": "LREN", "019739": "RENT", "022616": "BPAC", "020575": "JBSS"}


def eventos():
    def f():
        x = pd.read_parquet(D / "cvm_itr_dfp.parquet", columns=["CD_CVM", "DT_REFER", "DT_RECEB"])
        x["CD_CVM"] = x.CD_CVM.astype(str).str.zfill(6)
        x = x[x.CD_CVM.isin(CVM_RAIZ)]
        x["E"] = pd.to_datetime(x.DT_RECEB)
        e = x.groupby(["CD_CVM", "DT_REFER"]).E.min().reset_index()      # 1ª entrega = divulgação do resultado
        e["raiz"] = e.CD_CVM.map(CVM_RAIZ)
        e = e[e.E >= "2014-01-01"]
        # dia útil do evento (se cair em feriado, o pregão seguinte)
        e["E"] = [DIAS[DIAS >= d][0] if (DIAS >= d).any() else pd.NaT for d in e.E]
        return e.dropna().drop_duplicates(["raiz", "E"]).sort_values("E")
    return _cache("eventos", f)


def evento(lado="ambos", margem=.15, nocional=.2, custo_mult=1, lag=0, detalhe=False):
    """Straddle ATM no fechamento da véspera do resultado (CVM: data de entrega do ITR/DFP), desmontado 1 pregão depois.
    IV 'justa' = sqrt((RV21² (T - 2/252) + m²)/T), m = RMS dos 8 últimos movimentos de 2 dias em resultados da mesma empresa.
    Compra se IV < justa x (1-margem); vende se IV > justa x (1+margem)."""
    S, rs, ra = spot_opc()
    ev = eventos()
    lr = np.log1p(rs)
    exc = pd.Series(0.0, index=DIAS)
    trades, contrib = [], {}
    for raiz, g in ev.groupby("raiz"):
        if raiz not in S:
            continue
        o = opcoes_raiz(raiz)
        pordia = _cache(("opcd", raiz), lambda: {k: x for k, x in o[o.mensal].groupby("data")})
        hist_m = []
        cs = pd.Series(0.0, index=DIAS)
        for E in g.E:
            i = DIAS.get_loc(E)
            if i < 22 or i + 1 + lag >= len(DIAS):
                continue
            d_in, d_mid, d_out = DIAS[i - 1 + lag], DIAS[i + lag], DIAS[i + 1 + lag]
            mov = lr[raiz].iloc[i:i + 2].sum()                           # fecha(E-1) -> fecha(E+1)
            m_rms = np.sqrt(np.mean(np.square(hist_m[-8:]))) if len(hist_m) >= 4 else np.nan
            hist_m.append(mov)
            S0 = S[raiz].get(d_in, np.nan)
            if not (m_rms == m_rms and S0 == S0):
                continue
            ch = pordia.get(d_in)
            if ch is None:
                continue
            ch = ch[ch.venc >= d_out + pd.Timedelta(days=5)]
            if ch.empty:
                continue
            v = ch.venc.min()
            ch = ch[ch.venc == v]
            T, r = max(du(d_in, v), 1) / 252, _r_aa(d_in)
            rv = rs[raiz].iloc[i - 22:i - 1].std() * np.sqrt(252)
            justa = np.sqrt(max(rv ** 2 * (T - 2 / 252) + m_rms ** 2, 1e-6) / T)
            sig = iv_atm(ch, S0, T, r)
            if not sig == sig:
                continue
            sg = 1 if sig < justa * (1 - margem) else -1 if sig > justa * (1 + margem) else 0
            if sg == 0 or (lado == "comprar" and sg < 0) or (lado == "vender" and sg > 0):
                continue
            c, p = escolhe(ch, S0, "C", sg), escolhe(ch, S0, "P", sg)
            if c is None or p is None or c.strike != p.strike:
                p = escolhe(ch[ch.strike == c.strike], S0, "P", sg) if c is not None else None
                if p is None:
                    continue
            q = nocional / S0
            tot = []
            for x in (c, p):
                exe = x.ask if sg > 0 else x.bid
                mid = x.mid if x.mid == x.mid else exe
                ent = mid - custo_mult * (mid - exe)
                ov = opc_venc(raiz, v)
                hs_ = ov[ov.serie == x.serie].drop_duplicates("data").set_index("data")
                y_mid, y_out = hs_.reindex([d_mid, d_out]).iloc[0], hs_.reindex([d_mid, d_out]).iloc[1]
                K, Sx = x.strike, S[raiz].get(d_out, S0)
                intr = max(Sx - K, 0) if x.tipo == "C" else max(K - Sx, 0)
                if y_out.mid == y_out.mid:                                 # sai no meio menos o meio spread (no máx. 10% do meio)
                    sp = min(abs(y_out.mid - (y_out.bid if sg > 0 else y_out.ask)), .1 * y_out.mid)                         if (y_out.bid if sg > 0 else y_out.ask) == (y_out.bid if sg > 0 else y_out.ask) else .1 * y_out.mid
                    sai = max(y_out.mid - sg * custo_mult * sp, intr if sg > 0 else 0)
                else:
                    sai = intr if sg > 0 else max(mid * 1.1, intr)
                meio = y_mid.mid if y_mid.mid == y_mid.mid else np.nan
                tot.append((ent, meio, sai))
            ent, meio, sai = [sum(z[k] for z in tot) for k in range(3)]
            taxa = .001 * (ent + sai) * q * custo_mult
            if meio == meio:
                cs[d_mid] += sg * q * (meio - ent)
                cs[d_out] += sg * q * (sai - meio) - taxa
            else:
                cs[d_out] += sg * q * (sai - ent) - taxa
            trades.append(dict(ativo=raiz, lado="compra" if sg > 0 else "venda", entrada=d_in, saida=d_out, dias=2, evento=E,
                               iv=sig, iv_justa=justa, mov_2d=mov, straddle_pct=ent / S0, ent=ent, meio=meio, sai=sai, K=c.strike, S0=S0,
                               S1=S[raiz].get(d_out), venc=v, contrib=sg * q * (sai - ent) - taxa,
                               retorno=sg * (sai - ent) / ent))
        contrib[raiz] = cs
        exc += cs
    tr = pd.DataFrame(trades)
    return (exc, pd.DataFrame(contrib), tr) if detalhe else exc


# =============================================================== 07 Cash-and-carry cripto (futuro trimestral x spot)
def _ult_sexta(a, m):
    d = pd.Timestamp(a, m, 1) + pd.offsets.MonthEnd(0)
    return d - pd.Timedelta(days=(d.weekday() - 4) % 7)


def painel_carry():
    def f():
        fu = pd.read_parquet(D / "arb_cripto_fut.parquet")
        c = pd.read_parquet(D / "arb_cripto_1h.parquet")
        out = {}
        venc = sorted(_ult_sexta(a, m) for a in range(2020, 2028) for m in (3, 6, 9, 12))
        for par, s in (("BTCUSD", "BTCUSDT"), ("ETHUSD", "ETHUSDT")):
            F = fu[(fu.par == par) & (fu.ct == "CURRENT_QUARTER")].set_index("t").fech
            F = F[~F.index.duplicated()]
            x = c[c.sym == s].set_index("t").fech
            x = x[~x.index.duplicated()]
            Sd = x[x.index.hour == 23].copy()                            # candle 23h fecha 00:00 UTC = fechamento diário
            Sd.index = Sd.index.normalize()
            df = pd.DataFrame({"F": F, "S": Sd}).dropna()
            df["venc"] = [next(v for v in venc if v > d) for d in df.index]
            df["dias"] = (df.venc - df.index).dt.days
            df["base_aa"] = (df.F / df.S - 1) * 365 / df.dias.clip(lower=1)
            # exclui o dia em que o contínuo troca de contrato (variação de F de contratos diferentes)
            df["mesmo"] = df.venc.eq(df.venc.shift(1))
            out[par[:3]] = df
        tb = (IDX["^IRX"] / 100).resample("D").last().ffill()
        return out, tb
    return _cache("carry", f)


def carry_cripto(ativo="BTC", thr=.05, capital=1.25, custo_mult=1, lag=0, detalhe=False):
    """Compra spot e vende o futuro trimestral quando a base anualizada supera o T-bill + thr; segura até a véspera do vencimento
    (base ~0). Capital = spot + margem (capital x nocional). Excesso em US$ sobre o T-bill -> R$ com hedge (brl)."""
    P, tb = painel_carry()
    nomes = ["BTC", "ETH"] if ativo == "ambos" else [ativo]
    exc_us, contrib, trades = {}, {}, []
    for a in nomes:
        df = P[a].copy()
        df["tb"] = tb.reindex(df.index).ffill()
        sinal = (df.base_aa - df.tb > thr) & (df.dias > 7 + lag)
        pos = pd.Series(0.0, index=df.index)
        aberto, ent = False, None
        idx = df.index
        for k in range(len(idx) - 1):
            d = idx[k]
            if aberto and df.dias.iloc[k] <= 1:                           # sai na véspera do vencimento
                aberto = False
                trades.append(dict(ativo=a, lado="carry", entrada=ent, saida=d, base_entrada=df.base_aa.get(ent)))
            if not aberto and k - lag >= 0 and sinal.iloc[k - lag] and df.mesmo.iloc[k]:
                aberto, ent = True, d
            pos.iloc[k] = 1.0 if aberto else 0.0
        S, F = df.S, df.F
        s0 = S.where(pos.diff().fillna(pos) > 0).ffill()                 # nocional fixo em moedas: P&L sobre o spot da entrada
        pnl = ((S.diff() - F.diff()) / s0.shift(1)).where(df.mesmo, 0).fillna(0)
        p1 = pos.shift(1).fillna(0)
        giro = pos.diff().abs().fillna(pos)
        e = (p1 * pnl - giro * .0014 * custo_mult) / capital - p1 * df.tb / 365
        exc_us[a] = e / len(nomes)
    ex = pd.DataFrame(exc_us).fillna(0)
    exc = brl(ex.sum(axis=1))
    if not detalhe:
        return exc
    contrib = pd.DataFrame({a: brl(ex[a]) for a in ex})
    tr = pd.DataFrame(trades)
    if len(tr):
        tr["dias"] = (tr.saida - tr.entrada).dt.days
        tr["contrib"] = [contrib[r.ativo].loc[r.entrada:r.saida].sum() for r in tr.itertuples()]
        tr["retorno"] = tr.contrib
    return exc, contrib, tr


# =============================================================== 08 Dividendos/JCP na data-ex
SUF = {"ON": "3", "PN": "4", "PNA": "5", "PNB": "6", "UNT": "11"}


def painel_div():
    def f():
        p = pd.read_parquet(D / "arb_proventos.parquet").dropna(subset=["lastDatePriorEx"])
        p["ticker"] = p.code4 + p.typeStock.map(SUF).fillna("?")
        p["valor"] = p.valueCash.str.replace(".", "", regex=False).str.replace(",", ".").astype(float) / \
            p.quotedPerShares.astype(float).clip(lower=1)
        p["com"] = pd.to_datetime(p.lastDatePriorEx, dayfirst=True)
        p["aprov"] = pd.to_datetime(p.dateApproval, dayfirst=True, errors="coerce")
        p["jcp"] = p.corporateAction.str.contains("JRS|JUROS", regex=True)
        p = p[p.corporateAction.str.contains("DIVIDENDO|JRS|JUROS|RENDIMENTO", regex=True) & (p.com >= "2014-01-01")]
        g = p.groupby(["ticker", "com"]).apply(lambda x: pd.Series({"div": x.valor[~x.jcp].sum(), "jcp": x.valor[x.jcp].sum(),
                                                                     "aprov": x.aprov.max()})).reset_index()
        V = vista(g.ticker.unique())
        return g, V, meio_spread(V, .003)
    return _cache("div", f)


def dividendos(lado="compra", tipo="todos", yield_min=.005, ir_jcp=.15, custo_mult=1, lag=0, detalhe=False):
    """Fica comprado (ou vendido) do fechamento da data-com ao fechamento da data-ex. Só eventos APROVADOS até o pregão anterior
    à data-com (decisão em t, execução em t+1 = data-com); lag=1 exige a aprovação um pregão antes. Recebe dividendo + JCP x (1-IR);
    vendido reembolsa o mesmo valor ao doador."""
    g, V, hs = painel_div()
    F = V["fech"]
    W = pd.DataFrame(0.0, index=DIAS, columns=F.columns)
    R = pd.DataFrame(0.0, index=DIAS, columns=F.columns)
    sg = 1 if lado == "compra" else -1
    yb = {}
    for x in g.itertuples():
        if x.ticker not in F or x.com not in DIAS:
            continue
        i = DIAS.get_loc(x.com)
        if i < 3 or i + 1 >= len(DIAS):
            continue
        dec, ex = DIAS[i - 1], DIAS[i + 1]
        if not (x.aprov <= DIAS[i - 1 - lag]):
            continue
        P0, P1 = F[x.ticker].get(x.com), F[x.ticker].get(ex)
        if not (P0 > 0 and P1 > 0):
            continue
        liq, bruto = x.div + x.jcp * (1 - ir_jcp), x.div + x.jcp
        if (tipo == "JCP" and x.jcp <= x.div) or (tipo == "DIV" and x.div <= x.jcp) or bruto / P0 < yield_min:
            continue
        if V["volume"][x.ticker].iloc[max(i - 21, 0):i].median() < 2e6:
            continue
        W.loc[dec, x.ticker] = sg
        R.loc[ex, x.ticker] += (P1 + liq) / P0 - 1 if abs(P1 / P0 - 1) < .25 else liq / P0
        yb[(x.ticker, x.com)] = bruto / P0
    R = R.sub(R_IBOV, axis=0)                                           # hedge com mini-índice (beta 1): isola o efeito da data-ex
    W = W.loc[:, W.abs().sum() > 0]
    R = R[W.columns]
    W = W.div(np.maximum(W.abs().sum(axis=1), 5), axis=0)              # até 20% do PL por evento
    custo = (hs[W.columns] + .0004) * custo_mult                       # meio spread + 3 bps + 1 bp do WIN
    exc, contrib, We = cart(W, R, custo, lag=0, alug=.02 if sg < 0 else 0, neg=V["negocios"][W.columns].fillna(0) > 0)
    if not detalhe:
        return exc
    tr = negocios_de(We, R, contrib)
    if len(tr):
        tr["yield_bruto"] = [yb.get((a, e), np.nan) for a, e in zip(tr.ativo, tr.entrada)]
        tr["adv_R$"] = [V["volume"][a].rolling(20, min_periods=5).median().get(e, np.nan) for a, e in zip(tr.ativo, tr.entrada)]
    return exc, contrib.loc[:, contrib.abs().sum() > 0], tr


# =============================================================== 09 Base IND x BOVA11 perto do vencimento
def painel_ind():
    def f():
        x = pd.read_parquet(D / "arb_ind.parquet")
        x = x[x.ticker.str.startswith("IND")]
        meses = {c: i + 1 for i, c in enumerate("FGHJKMNQUVXZ")}
        from arb_dados import venc_ind
        vs = {(v.year, v.month): v for v in venc_ind()}
        x["venc"] = [vs.get((2000 + int(t[-2:]), meses[t[3]])) for t in x.ticker]
        x = x.dropna(subset=["venc"])
        x = x[x.date <= x.venc].sort_values(["date", "venc"]).drop_duplicates("date")      # 1º vencimento
        V = vista(["BOVA11"])
        ib = IDX["^BVSP"].reindex(DIAS).ffill(limit=3)
        return x.set_index("date"), V, ib
    return _cache("ind", f)


def base_ind(thr=.01, dias_antes=10, custo_mult=1, lag=0, detalhe=False):
    """Compra BOVA11 e vende IND quando a taxa implícita (IND / Ibovespa) supera o CDI + thr (ou o inverso se < CDI - thr);
    segura até o vencimento do IND (ajuste final ~ Ibovespa). Excesso = taxa travada - CDI, mais o erro de rastreio BOVA11/Ibov."""
    x, V, ib = painel_ind()
    bova = V["fech"]["BOVA11"]
    rb = ret(bova)
    exc = pd.Series(0.0, index=DIAS)
    trades = []
    for v, g in x.groupby("venc"):
        g = g[g.index.isin(DIAS)]
        dd = [d for d in g.index if 1 <= du(d, v) <= dias_antes]
        if not dd:
            continue
        d_s = dd[0]
        k = DIAS.get_loc(d_s) + 1 + lag
        if k >= len(DIAS) or DIAS[k] >= v or DIAS[k] not in g.index:
            continue
        d0 = DIAS[k]
        n = max(du(d_s, v), 1)
        imp = (g.AdjstdQt[d_s] / ib.get(d_s, np.nan)) ** (252 / n) - 1
        edge = imp - CDI_AA.get(d_s, np.nan)
        sg = 1 if edge > thr else -1 if edge < -thr else 0
        if sg == 0 or not edge == edge:
            continue
        per = DIAS[(DIAS > d0) & (DIAS <= v)]
        F = g.AdjstdQt.reindex(DIAS[(DIAS >= d0) & (DIAS <= v)]).ffill()
        rf = (F.diff() / F.shift(1)).reindex(per).fillna(0)              # futuro: retorno já é excesso (ajuste diário)
        e = sg * ((rb.reindex(per) - CDI.reindex(per)) - rf)
        e.iloc[0] -= .0006 * custo_mult
        e.iloc[-1] -= .0006 * custo_mult
        if sg < 0:
            e -= .01 / 252
        exc.loc[per] += e.values
        trades.append(dict(ativo="BOVA11/IND", lado="caixa" if sg > 0 else "reverso", entrada=d0, saida=v, dias=len(per),
                           taxa_impl=imp, cdi=CDI_AA.get(d_s), contrib=e.sum(), retorno=e.sum()))
    tr = pd.DataFrame(trades)
    return (exc, exc.to_frame("BOVA11/IND"), tr) if detalhe else exc


# =============================================================== fundos
from motor import Fundo, roda  # noqa: E402

FUNDOS = [
    Fundo("A1 BDR x ação nos EUA (prêmio/desconto)", "Arbitragem", "CDI",
          "Compro o BDR quando ele negocia com desconto sobre (ação nos EUA x dólar / razão) e vendo a ação lá fora + dólar futuro; "
          "o desconto vem de liquidez ruim / falta de formador no BDR não patrocinado e volta em dias.",
          "Até 10% do PL por BDR (no máx. 10 posições), sinal no preço de oferta de venda do fechamento, fator comum de câmbio/horário "
          "removido (mediana do prêmio de todos os BDRs líquidos), saída na reversão ou em 20 dias; custo = meio spread real + 4 bps",
          bdr, {"thr": [.01, .02, .03], "janela": [20, 60], "lado": ["compra", "ambos"]}, inicio="2019-01-01", corte="2023-01-01"),
    Fundo("A2 ETFs da B3 x NAV (IVVB11, NASD11, GOLD11, cripto)", "Arbitragem", "CDI",
          "ETFs listados na B3 se afastam do NAV teórico (ETF/índice lá fora x dólar, ou BTC/ETH no horário da B3) e voltam; "
          "o formador arbitra, mas com atraso quando o fluxo de varejo é forte (cripto, ouro).",
          "Mesmo motor do A1, universo ETFs (IVVB11, SPXI11, NASD11, GOLD11, XINA11, EURP11, ACWI11) e/ou ETFs de cripto "
          "(HASH11, BITH11, QBTC11, ETHE11, QETH11) com hedge no ativo lá fora", bdr,
          {"thr": [.005, .01, .02], "universo": ["etf", "cripto"], "lado": ["ambos"], "janela": [20], "adv_min": [2e5]},
          inicio="2019-01-01", corte="2023-01-01"),
    Fundo("A3 Units x ações componentes", "Arbitragem", "CDI",
          "A unit (n ON + m PN) é conversível nas ações; quando a diferença de preço executável passa do custo, compro o barato e "
          "vendo o caro esperando a convergência (âncora física: montagem/desmontagem da unit).",
          "13 units (TAEE, KLBN, SAPR, ENGI, ALUP, SANB, BPAC, TIET, IGTI, SULA, CPLE, BIDI, MODL); até 25% do PL por par; "
          "preços de oferta reais; aluguel 2% a.a.; saída na reversão ou 40 dias", units,
          {"thr": [.005, .01, .02], "janela": [20, 60]}, inicio="2014-06-01"),
    Fundo("A4 Venda de volatilidade B3 (put/strangle/put spread)", "Volatilidade", "CDI",
          "O brasileiro paga caro por proteção: a IV de 1 mês fica acima da vol realizada. Vendo puts/strangles/put spreads de "
          "~1 mês no bid, com ou sem hedge de delta diário, filtrando por IV-RV ou skew alto.",
          "BOVA11, PETR4, VALE3, ITUB4, BBDC4 (20% do nocional cada; nocional total 100% do PL); séries mensais; "
          "segura até o vencimento; marcação no meio das ofertas", venda_vol,
          {"estrutura": ["put", "strangle", "put_spread"], "filtro": ["sempre", "iv_rv"], "hedge": [False, True]},
          inicio="2014-03-01"),
    Fundo("A5 Vol de evento (straddle em resultados)", "Volatilidade", "CDI",
          "Antes do resultado trimestral a IV deveria embutir o movimento típico do evento; quando embute menos, compro straddle "
          "na véspera e vendo depois do resultado; quando embute muito mais, vendo.",
          "20 ações com opções; evento = data de entrega do ITR/DFP na CVM; straddle ATM da série mensal, nocional 20% do PL por "
          "evento; entra no fechamento da véspera (ask/bid), sai 1 pregão depois do evento", evento,
          {"lado": ["comprar", "vender", "ambos"], "margem": [.0, .15, .3]}, inicio="2015-01-01"),
    Fundo("A6 Covered call PETR4/VALE3", "Ações com opções", "Ibovespa",
          "Carregar PETR4/VALE3 vendendo call de 1 mês: nos meses de IV alta o prêmio paga mais que a alta que se entrega.",
          "50% PETR4 + 50% VALE3 (retorno total), call mensal (1+otm) vendida no bid sobre 100% da posição", covered_call,
          {"otm": [.03, .06, .10], "filtro": ["sempre", "iv_alta"]}, inicio="2014-03-01"),
    Fundo("A7 Cash-and-carry cripto (futuro trimestral x spot)", "Arbitragem", "CDI",
          "Base de futuros de cripto paga 5-20% a.a. em mercados de alta (demanda alavancada comprada); compro spot e vendo o "
          "futuro trimestral, recebo a base até o vencimento, sem risco de preço.",
          "BTC/ETH spot (Binance) x futuro trimestral COIN-M; capital 125% do nocional (margem); hedge cambial (R$ = CDI + excesso)",
          carry_cripto, {"ativo": ["BTC", "ETH", "ambos"], "thr": [0.0, .05, .10]}, inicio="2020-09-01", corte="2023-01-01"),
    Fundo("A8 Dividendos/JCP na data-ex", "Evento", "CDI",
          "Se o preço cai menos (ou mais) que o provento líquido na data-ex, há um prêmio a capturar comprando na data-com "
          "(ou vendendo). JCP tem 15% de IR retido: quem é isento ganha o que o mercado desconta.",
          "Ações com proventos aprovados antes da data-com, yield >= mínimo, ADV > R$ 2 mi; até 20% do PL por evento, "
          "hedge com mini-índice (beta 1); meio spread real + 4 bps por perna", dividendos,
          {"lado": ["compra", "venda"], "tipo": ["todos", "JCP"], "yield_min": [.005, .01]}, inicio="2014-03-01"),
    Fundo("A9 Base IND x BOVA11 no vencimento", "Arbitragem", "CDI",
          "Perto do vencimento a taxa implícita do IND contra o Ibovespa às vezes se descola do CDI (fluxo de rolagem); "
          "compro BOVA11 e vendo IND (ou o inverso) e travo a diferença.",
          "100% do PL em BOVA11 contra IND do 1º vencimento, entra até N pregões antes do vencimento", base_ind,
          {"thr": [.005, .01, .02], "dias_antes": [5, 10]}, inicio="2019-02-01", corte="2023-01-01"),
]


def capacidade(tr):
    """R$ por negócio que cabem sem mover o preço: 10% do volume mediano de 20 dias do ativo (quando disponível)."""
    if "adv_R$" not in tr or tr.empty:
        return np.nan
    return float((tr["adv_R$"] * .10).median())


if __name__ == "__main__":
    from rodar import BENCH
    so = sys.argv[1:]
    res = []
    out = open(D.parent / "resultado" / "log_arbitragem.txt", "a", encoding="utf-8")

    def log(*a):
        s = " ".join(str(x) for x in a)
        print(s, flush=True)
        out.write(s + "\n")
        out.flush()

    for f in FUNDOS:
        if so and f.nome[:2] not in so:
            continue
        t = time.time()
        log(f"\n== {f.nome}")
        r = roda(f, CDI, BENCH[f.benchmark], log)
        if r is None:
            log("   sem resultado")
            continue
        _, contrib, tr = f.func(**r["params"], detalhe=True)
        r["contrib"], r["trades"] = contrib, tr
        r["capacidade_R$_por_negocio"] = capacidade(tr)
        o, rb = r["oos"], r["rob"]
        log(f"   escolhido {r['params']} | IR IS {r['is_ir']:.2f} | OOS: {o['retorno a.a. %']:.1f}% vs bench {o['benchmark a.a. %']:.1f}% "
            f"(IR {o['IR vs bench']:.2f}) | P(bater) {rb['P(bater bench OOS) %']:.0f}% | PBO {rb['PBO %']:.0f}% | "
            f"custo x2 {rb['OOS custo x2 (pp)']:.1f}pp | +1 dia {rb['OOS execução +1 dia (pp)']:.1f}pp | negócios {len(tr)} | {time.time() - t:.0f}s")
        res.append(r)
    for r in res:
        r["fundo"].func = None
    nome = "ideias_arbitragem.pkl" if not so else f"ideias_arbitragem_{'_'.join(so)}.pkl"
    pickle.dump(res, open(D.parent / "resultado" / nome, "wb"))
    log("pronto")
