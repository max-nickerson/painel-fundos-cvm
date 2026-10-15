"""
Fundos globais (calendário dos EUA, convertidos para reais com hedge cambial: excesso sobre o T-bill + CDI).
Custos: ETFs 0,05% por perna; moedas 0,03%; alavancagem paga T-bill + 0,5%.
"""
import numpy as np
import pandas as pd

from base import BIS, DIAS_US, ETF, FXY, IDX, TB_US, brl, carteira, limpa, limpa_fx, mensal, semanal, vol_alvo, D, DQ

C_ETF, C_FX = .0005, .0003
P = ETF.reindex(DIAS_US).ffill(limit=5)
RX = limpa(P.pct_change(fill_method=None)).sub(TB_US, axis=0)          # excesso sobre o T-bill


def _ex(W, R, custo, lag, custo_mult, alvo=None, aluguel=0.0):
    if alvo:
        W = vol_alvo(W, R, alvo)
    alav = (W.abs().sum(axis=1) - 1).clip(lower=0).shift(2).fillna(0) * .005 / 252
    return brl(carteira(W, R, custo * custo_mult, lag, aluguel) - alav)


def tsmom(Pr, janelas=(21, 63, 252)):
    lp = np.log(Pr)
    return sum(np.sign(lp - lp.shift(j)) for j in janelas) / len(janelas)


# ---------------------------------------------------------------- F10 crédito EUA com hedge de juros
def credito_eua(timing="tendencia", alvo=.06, custo_mult=1, lag=0):
    r = RX[["HYG", "JNK", "IEF", "LQD", "EMB"]]
    cred = r[["HYG", "JNK"]].mean(axis=1)
    beta = cred.rolling(126, min_periods=60).cov(r.IEF) / r.IEF.rolling(126, min_periods=60).var()
    R = pd.DataFrame({"credito": cred - beta.shift(1).clip(0, 1) * r.IEF, "emb": r.EMB - .5 * r.IEF}).dropna(how="all")
    W = pd.DataFrame(1.0, index=R.index, columns=R.columns)
    if timing == "tendencia":
        on = (np.log(P[["HYG", "EMB"]]) - np.log(P[["HYG", "EMB"]]).shift(63) > 0).values
        W = W * on
    elif timing == "vix":
        v = IDX["^VIX"].reindex(R.index).ffill()
        W = W.mul((v < v.rolling(252, min_periods=100).median()).astype(float), axis=0)
    return _ex(semanal(W), R, C_ETF, lag, custo_mult, alvo)


# ---------------------------------------------------------------- F11 carry de moedas G10 + emergentes
MOEDA = {"EURUSD=X": ("XM", 1), "GBPUSD=X": ("GB", 1), "AUDUSD=X": ("AU", 1), "NZDUSD=X": ("NZ", 1), "JPY=X": ("JP", -1), "CAD=X": ("CA", -1),
         "CHF=X": ("CH", -1), "NOK=X": ("NO", -1), "SEK=X": ("SE", -1), "MXN=X": ("MX", -1), "ZAR=X": ("ZA", -1), "TRY=X": ("TR", -1),
         "INR=X": ("IN", -1), "IDR=X": ("ID", -1), "KRW=X": ("KR", -1), "CLP=X": ("CL", -1), "COP=X": ("CO", -1), "PLN=X": ("PL", -1),
         "HUF=X": ("HU", -1), "CZK=X": ("CZ", -1), "THB=X": ("TH", -1), "PHP=X": ("PH", -1), "ILS=X": ("IL", -1), "CNY=X": ("CN", -1),
         "BRL=X": ("BR", -1)}
NDF = {"INR=X", "IDR=X", "KRW=X", "CLP=X", "COP=X", "PHP=X", "CNY=X", "BRL=X"}


def _fx():
    v = pd.DataFrame({k: FXY[k] ** s for k, (c, s) in MOEDA.items() if k in FXY}).reindex(DIAS_US).ffill(limit=5)
    spot = limpa_fx(v.pct_change(fill_method=None))
    i = BIS.reindex(DIAS_US).ffill()
    dif = pd.DataFrame({k: (i[c] - i["US"]) / 100 for k, (c, s) in MOEDA.items() if k in v and c in i}).reindex(DIAS_US)
    dif = dif.mul([.7 if k in NDF else 1 for k in dif.columns])           # moedas sem conversibilidade: carry efetivo menor
    return v, spot, dif


def carry_fx(n=3, filtro=1, lado="ls", alvo=.08, custo_mult=1, lag=0, teto=.25):
    v, spot, dif = _fx()
    R = (spot + dif.shift(1) / 252).dropna(how="all")
    rk = dif.rank(axis=1, ascending=False)
    W = (rk <= n).astype(float) - ((rk > dif.notna().sum(axis=1).values[:, None] - n) & dif.notna()).astype(float) * (lado == "ls")
    if filtro:
        mom = np.log(v) - np.log(v).shift(63)
        W = W.where(~((W > 0) & (mom < 0)), 0).where(~((W < 0) & (mom > 0)), 0)
    vol = spot.rolling(63, min_periods=40).std()
    W = (W / vol).div((W / vol).abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    W = mensal(vol_alvo(W, R[W.columns].fillna(0), alvo)).clip(-teto, teto)   # teto por moeda DEPOIS do vol-alvo (antes a TRY chegava a 75% do PL)
    return _ex(W, R[W.columns], C_FX, lag, custo_mult, None)


# ---------------------------------------------------------------- F12 commodities: tendência, momento relativo e posicionamento CFTC
COMM = ["USO", "BNO", "UNG", "GLD", "SLV", "CPER", "DBA", "CORN", "SOYB", "WEAT", "PALL", "PPLT", "URA", "DBB"]
COT_MAP = {"GLD": "GOLD - COMMODITY EXCHANGE", "SLV": "SILVER - COMMODITY EXCHANGE", "CPER": "COPPER", "USO": "CRUDE OIL, LIGHT SWEET",
           "UNG": "NATURAL GAS", "CORN": "CORN - CHICAGO", "SOYB": "SOYBEANS - CHICAGO", "WEAT": "WHEAT-SRW", "PPLT": "PLATINUM",
           "PALL": "PALLADIUM"}


def _cot_mm():
    c = pd.read_parquet(D / "cot.parquet")
    c = c[c.relatorio == "com"]
    nome = [x for x in c.columns if "Market_and_Exchange" in x][0]
    dt = [x for x in c.columns if "YYYY-MM-DD" in x][0]
    lg = [x for x in c.columns if x.startswith("M_Money_Positions_Long_All")][0]
    sh = [x for x in c.columns if x.startswith("M_Money_Positions_Short_All")][0]
    oi = [x for x in c.columns if x.startswith("Open_Interest_All")][0]
    out = {}
    for etf, chave in COT_MAP.items():
        g = c[c[nome].str.upper().str.contains(chave.upper(), regex=False, na=False)]
        if g.empty:
            continue
        g = g.groupby(pd.to_datetime(g[dt])).apply(lambda x: ((x[lg] - x[sh]) / x[oi]).iloc[x[oi].values.argmax()])
        out[etf] = g
    m = pd.DataFrame(out).sort_index()
    m.index = m.index + pd.Timedelta(days=3)                              # relatório de terça publicado na sexta
    return m.reindex(DIAS_US, method="ffill")


def commodities(tipo="ts+cot", alvo=.10, custo_mult=1, lag=0):
    c = [x for x in COMM if x in P]
    R = RX[c]
    ts = tsmom(P[c])
    if tipo == "xs":
        m = np.log(P[c]) - np.log(P[c]).shift(252)
        rk = m.rank(axis=1, pct=True)
        W = (rk >= .7).astype(float) - (rk <= .3).astype(float)
    else:
        W = ts.copy()
    if "cot" in tipo:
        z = _cot_mm()
        z = (z - z.rolling(156, min_periods=52).mean()) / z.rolling(156, min_periods=52).std()
        z = z.reindex(columns=c)
        W = W.where(~((W > 0) & (z > 1.5)), W * .5).where(~((W < 0) & (z < -1.5)), W * .5)   # posição lotada: reduz pela metade
    vol = R.rolling(63, min_periods=40).std()
    W = (W / vol).div((W / vol).abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    return _ex(semanal(W), R, C_ETF, lag, custo_mult, alvo)


# ---------------------------------------------------------------- F13 tendência multiativos (CTA)
CTA = ["SPY", "IWM", "QQQ", "EFA", "EEM", "EWJ", "EWZ", "FXI", "TLT", "IEF", "SHY", "TIP", "LQD", "HYG", "EMB", "GLD", "SLV", "USO", "DBA",
       "DBB", "UNG"]


def cta(janelas="1-3-12", alvo=.10, freq="W", fx=1, custo_mult=1, lag=0):
    jan = {"1-3-12": (21, 63, 252), "12": (252,), "3-12": (63, 252)}[janelas]
    c = [x for x in CTA if x in P]
    R, W = RX[c], tsmom(P[c], jan)
    if fx:
        v, spot, dif = _fx()
        g10 = [k for k in ("EURUSD=X", "GBPUSD=X", "AUDUSD=X", "JPY=X", "CAD=X", "CHF=X", "MXN=X", "BRL=X") if k in v]
        R = pd.concat([R, (spot[g10] + dif[g10].shift(1) / 252)], axis=1)
        W = pd.concat([W, tsmom(v[g10], jan)], axis=1)
    vol = R.rolling(63, min_periods=40).std()
    W = (W / vol).div((W / vol).abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    W = semanal(W) if freq == "W" else mensal(W)
    return _ex(W, R, C_ETF, lag, custo_mult, alvo)


# ---------------------------------------------------------------- F14 paridade de risco (com ou sem filtro de tendência)
RP = ["SPY", "EFA", "EEM", "TLT", "IEF", "TIP", "LQD", "HYG", "GLD", "DBC"]


def paridade(tendencia=1, alvo=.10, custo_mult=1, lag=0):
    R = RX[RP]
    vol = R.rolling(63, min_periods=40).std()
    W = (1 / vol).div((1 / vol).sum(axis=1), axis=0)
    if tendencia:
        on = (np.log(P[RP]) - np.log(P[RP]).rolling(210, min_periods=150).mean() > 0).astype(float)
        W = W * on
    return _ex(mensal(W.fillna(0)), R, C_ETF, lag, custo_mult, alvo)


# ---------------------------------------------------------------- F15 prêmio de volatilidade (VIX e put-write)
def vol_premio(peso_svxy=.5, filtro="vix3m", custo_mult=1, lag=0):
    vix, v3 = IDX["^VIX"].reindex(DIAS_US).ffill(), IDX["^VIX3M"].reindex(DIAS_US).ffill()
    on = (vix / v3 < 1)
    if filtro == "vix3m+vvix":
        vv = IDX["^VVIX"].reindex(DIAS_US).ffill()
        on &= vv < vv.rolling(252, min_periods=100).quantile(.8)
    sv = limpa(ETF["SVXY"].reindex(DIAS_US).pct_change(fill_method=None), .9) - TB_US
    pw = limpa(IDX["^PUT"].reindex(DIAS_US).pct_change(fill_method=None)) - TB_US
    R = pd.DataFrame({"svxy": sv, "put": pw})
    W = pd.DataFrame({"svxy": on.astype(float) * peso_svxy, "put": 1 - peso_svxy}, index=DIAS_US)
    return brl(carteira(W, R, C_ETF * custo_mult, lag))


# ---------------------------------------------------------------- F18 rotação de países (ML)
PAIS = {"EWZ": "BR", "EWW": "MX", "EZA": "ZA", "EWJ": "JP", "EWY": "KR", "FXI": "CN", "INDA": "IN", "EWG": "XM", "EWU": "GB", "EWC": "CA",
        "EWA": "AU", "EWT": "US", "EWH": "US", "EWS": "US", "EWL": "CH", "EWP": "XM", "EWI": "XM", "EWQ": "XM", "EWN": "XM", "EWD": "SE",
        "ECH": "CL", "EPU": "PE", "TUR": "TR", "EIDO": "ID", "THD": "TH", "EPHE": "PH"}


def _features_paises():
    c = [x for x in PAIS if x in P]
    pm = P[c].resample("ME").last()
    lp = np.log(pm)
    r1 = lp.diff()
    f = {"mom12_1": lp.shift(1) - lp.shift(12), "rev1": r1, "vol3": np.log(P[c]).diff().rolling(63).std().resample("ME").last(),
         "dd5a": lp - lp.rolling(60, min_periods=24).max(), "mom3": lp - lp.shift(3)}
    i = BIS.resample("ME").last()
    f["carry"] = pd.DataFrame({k: i[v] - i["US"] for k, v in PAIS.items() if k in c and v in i}).reindex(pm.index)
    ac = np.log(P["ACWI"]).resample("ME").last().diff()
    alvo = (r1.shift(-1)).sub(ac.shift(-1), axis=0)                       # retorno do mês seguinte contra o ACWI
    df = pd.concat({k: v.stack() for k, v in f.items()}, axis=1)
    df["alvo"] = alvo.stack()
    df.index.names = ["mes", "etf"]
    return df.reset_index(), c


def paises(modelo="combo", n=6, custo_mult=1, lag=0):
    df, c = _features_paises()
    feats = ["mom12_1", "rev1", "vol3", "dd5a", "mom3", "carry"]
    df[feats] = df.groupby("mes")[feats].rank(pct=True)
    if modelo == "combo":
        df["score"] = df.mom12_1 + (1 - df.dd5a) * .5 + df.carry * .5 - df.vol3 * .25
    else:
        from lightgbm import LGBMRegressor
        df["score"] = np.nan
        meses = sorted(df.mes.unique())
        for k in range(36, len(meses), 12):
            tr = df[df.mes < meses[k - 1]].dropna(subset=["alvo"])
            te = df.mes.isin(meses[k:k + 12])
            if len(tr) < 200 or not te.any():
                continue
            m = LGBMRegressor(n_estimators=200, learning_rate=.03, num_leaves=8, min_child_samples=40, subsample=.8, subsample_freq=1,
                              verbose=-1, random_state=0).fit(tr[feats].fillna(.5), tr.alvo)
            df.loc[te, "score"] = m.predict(df.loc[te, feats].fillna(.5))
    S = df.pivot(index="mes", columns="etf", values="score")
    rk = S.rank(axis=1, ascending=False)
    Wm = (rk <= n).astype(float).div((rk <= n).sum(axis=1).replace(0, np.nan), axis=0)
    Wm = Wm.where(S.notna().sum(axis=1) >= 10)
    W = Wm.reindex(DIAS_US, method="ffill").fillna(0)                     # decidido no fim do mês, mantido o mês seguinte
    W["ACWI"] = -W.sum(axis=1) * 0                                         # fundo comprado (o benchmark é o ACWI)
    R = RX[list(W.columns)]
    return _ex(W, R, C_ETF, lag, custo_mult)
