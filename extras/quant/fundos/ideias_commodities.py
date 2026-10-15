"""
Rodada 2 — frente COMMODITIES E VALOR RELATIVO ENTRE ATIVOS (hedge de mesa).
Todos os fundos são long-short (benchmark CDI). Tudo no calendário B3 (preços dos EUA = último fechamento disponível no dia).
Pernas:
  ação BR financiada      : r - CDI                                  (Yahoo .SA ajustado por proventos; BRFS3 do COTAHIST)
  ETF/futuro EUA em R$    : (1+r)(1+r_usd) - 1 - CDI                 (exposição a commodity *em reais*, sem hedge cambial)
  ETF/moeda com hedge     : r - T-bill  (= excesso em R$ com hedge, paridade coberta)
  futuro (sem caixa)      : r  (futuros contínuos Yahoo: dias de rolagem detectados como salto > 5 desvios são zerados)
  futuro B3 agro          : retorno do ajuste do 2º vencimento (troca para o seguinte 20 dias corridos antes do mês de vencimento)
Dados novos: dados/y_comm.parquet (dados_comm_yahoo.py), dados/b3_futuros_agro.parquet (dados_agro.py).
"""
import pickle
from functools import lru_cache
import sys

import numpy as np
import pandas as pd

from base import BIS, CDI, CDI_AA, DIAS, ETF, FXY, IDX, ADR, R_IBOV, TB_US, D, limpa, limpa_fx, mensal, semanal, vol_alvo
from motor import Fundo, roda

# ------------------------------------------------------------------ dados no calendário B3
Y = pd.read_parquet(D / "y_comm.parquet")
_ALL = pd.concat([Y, ETF, IDX, ADR, FXY], axis=1)
_ALL = _ALL.loc[:, ~_ALL.columns.duplicated()]


def _dias(df, lim=5):
    df = df[~df.index.duplicated(keep="last")]
    return df.reindex(DIAS.union(df.index)).ffill(limit=lim).reindex(DIAS)


P = _dias(_ALL)
TB = _dias(TB_US.to_frame("tb")).tb.fillna(0)
R_USD = limpa_fx(P["BRL=X"].pct_change(fill_method=None)).fillna(0)        # alta = real desvaloriza


def _vista(tk):
    v = pd.read_parquet(D / "b3_vista.parquet", columns=["data", "ticker", "fech"], filters=[("ticker", "==", tk)])
    return v.groupby("data").fech.last().reindex(DIAS).ffill(limit=5)


P["BRFS3.SA"] = _vista("BRFS3")                                            # BRF saiu do Yahoo após a fusão com Marfrig (set/25)
P.loc[P.index > "2025-09-22", "BRFS3.SA"] = np.nan


def r_(tk, lim=.45):
    r = P[tk].pct_change(fill_method=None)
    ok = r.notna()                                                          # NaN antes da listagem/depois da saída (não vira -CDI)
    if tk.endswith(".SA"):                                                  # ação parada (>30% dos dias sem negócio/sem variação) = ilíquida
        ok &= ~((r == 0).astype(float).rolling(21, min_periods=10).mean().shift(1) > .3)
    return limpa(r, lim).where(ok)


def ex_br(tk):                                   # ação BR comprada com caixa do CDI
    return r_(tk) - CDI


def ex_brl(tk):                                  # ativo em dólar, exposição em reais (sem hedge cambial)
    r = r_fut(tk) if "=F" in tk else r_(tk)
    if "=F" in tk:                               # futuro: não usa caixa; o dólar entra via WDO (paga CDI-Tbill)
        return r + R_USD - (CDI - TB) + r * R_USD
    return (1 + r) * (1 + R_USD) - 1 - CDI


def ex_us(tk):                                   # ativo em dólar com hedge cambial (excesso sobre o T-bill)
    return r_fut(tk) if "=F" in tk else r_(tk) - TB


def r_fut(tk, k=5):
    """Futuro contínuo Yahoo: zera os dias de salto de rolagem (|r| > k desvios robustos)."""
    r = P[tk].pct_change(fill_method=None)
    s = r.abs().rolling(63, min_periods=20).median().shift(1) * 1.4826
    return r.where(~(r.abs() > k * s), 0.0).where(r.abs() < .3, 0.0).where(r.notna())


IBOV = R_IBOV - CDI

# custos por perna (uma via)
C_AC, C_SMALL, C_ETF, C_FX, C_FUT, C_FXEM = .0007, .0020, .0003, .0002, .0002, .0015


# ------------------------------------------------------------------ máquina comum
def beta(ra, rh, jan=252):
    """Beta rolante de ra contra rh (retornos de 5 dias, só passado)."""
    a5, h5 = ra.rolling(5).sum(), rh.rolling(5).sum()
    return (a5.rolling(jan, min_periods=jan // 2).cov(h5) / h5.rolling(jan, min_periods=jan // 2).var()).clip(0, 3).shift(1)


def histerese(Z, z_in, z_out=0.0, z_stop=4.0, tmax=120):
    """Reversão à média do resíduo: entra contra o desvio quando |z|>z_in, sai em z_out, stop em |z|>z_stop ou tmax dias."""
    Zv = Z.values
    out = np.zeros_like(Zv)
    pos, t = np.zeros(Zv.shape[1]), np.zeros(Zv.shape[1])
    for i in range(len(Zv)):
        z = Zv[i]
        ok = np.isfinite(z)
        sai = (pos == 1) & ok & ((z > -z_out) | (z < -z_stop)) | (pos == -1) & ok & ((z < z_out) | (z > z_stop)) | (t >= tmax) | ~ok
        pos[sai], t[sai] = 0, 0
        pos[(pos == 0) & ok & (z < -z_in) & (z > -z_stop)] = 1
        pos[(pos == 0) & ok & (z > z_in) & (z < z_stop)] = -1
        t[pos != 0] += 1
        out[i] = pos
    return pd.DataFrame(out, index=Z.index, columns=Z.columns)


def zscore(R, jan):
    X = R.fillna(0).cumsum()
    return (X - X.rolling(jan, min_periods=jan // 2).mean()) / X.rolling(jan, min_periods=jan // 2).std()


def risco_igual(W, R, alvo=.10, jan=63):
    """Cada posição com vol-alvo alvo/sqrt(nº de pares do livro) (estimada só com o passado)."""
    v = R.rolling(jan, min_periods=40).std().shift(1) * np.sqrt(252)
    return (W * (alvo / np.sqrt(R.shape[1])) / v).replace([np.inf, -np.inf], 0).fillna(0).clip(-2, 2)


def executa(W, R, custo, alug_l=0.0, alug_s=0.0, lag=0, cm=1, detalhe=False):
    """W decidido no fechamento de t; executado em t+1+lag; rende a partir do dia seguinte (igual a base.carteira),
    mas devolve a contribuição por ativo e a lista de negócios. custo e aluguéis podem ser Series por coluna."""
    R = R.fillna(0)
    W = W.reindex(R.index).fillna(0)
    We = W.shift(1 + lag).fillna(0)
    cs = lambda x: pd.Series(x, index=R.columns) if np.isscalar(x) else pd.Series(x).reindex(R.columns).fillna(0)
    C = (We.shift(1) * R - We.diff().abs() * cs(custo) * cm
         - We.shift(1).clip(lower=0) * cs(alug_l) / 252 - (-We.shift(1)).clip(lower=0) * cs(alug_s) / 252).fillna(0)
    alav = (We.shift(1).abs().sum(axis=1) - 2).clip(lower=0) * .01 / 252   # bruto acima de 2x (pares) paga CDI+1%
    ex = C.sum(axis=1) - alav
    if not detalhe:
        return ex
    return ex, C, negocios(We, R, C)


def negocios(We, R, C):
    lin = []
    idx = We.index
    for c in We.columns:
        s = np.sign(We[c].values)
        mud = np.flatnonzero(np.diff(np.r_[0, s]) != 0)
        for k, i0 in enumerate(mud):
            if s[i0] == 0:
                continue
            i1 = mud[k + 1] if k + 1 < len(mud) else len(s)
            seg = slice(i0 + 1, min(i1 + 1, len(s)))
            lin.append({"ativo": c, "lado": "comprado" if s[i0] > 0 else "vendido", "entrada": idx[i0], "saida": idx[min(i1, len(s) - 1)],
                        "dias": i1 - i0, "peso_medio": float(np.abs(We[c].values[i0:i1]).mean()),
                        "retorno": float(np.prod(1 + s[i0] * R[c].values[seg]) - 1), "contrib": float(C[c].values[seg].sum())})
    return pd.DataFrame(lin)


def livro_pares(pares, jan, z_in, alvo, custo, alug_l, alug_s, lag, cm, detalhe, jb=252, inicio=None, semana=True):
    """pares: {nome: (ret_excesso_A, ret_excesso_hedge)} -> compra A/vende beta*hedge quando o resíduo está barato."""
    R, B = {}, {}
    for k, (ra, rh) in pares.items():
        b = beta(ra, rh, jb)
        R[k] = ra - b * rh
        if inicio and k in inicio:
            R[k] = R[k].where(R[k].index >= inicio[k])
    R = pd.DataFrame(R).reindex(DIAS)
    R = R.where(R.notna().cumsum() > 0)
    Z = zscore(R, jan)
    if semana:
        Z = semanal(Z)
    S = histerese(Z, z_in)
    W = risco_igual(S, R, alvo)
    W = W.where(S != 0, 0)
    return executa(W, R, custo, alug_l, alug_s, lag, cm, detalhe)


# ================================================================== F1 petróleo: PETR4/PRIO3 vs Brent em reais
def petroleo(jan=126, z_in=1.5, conj="brent", alvo=.10, custo_mult=1, lag=0, detalhe=False):
    br = ex_brl("BNO")
    pares = {"PETR4 x BNO": (ex_br("PETR4.SA"), br), "PRIO3 x BNO": (ex_br("PRIO3.SA"), br)}
    if "par" in conj:
        pares["PRIO3 x PETR4"] = (ex_br("PRIO3.SA"), ex_br("PETR4.SA"))
    if "3r" in conj:
        pares["RECV3 x BNO"] = (ex_br("RECV3.SA"), br)
        pares["BRAV3 x BNO"] = (ex_br("BRAV3.SA"), br)
    custo = {"PETR4 x BNO": C_AC + C_ETF + C_FX, "PRIO3 x BNO": C_SMALL + C_ETF + C_FX, "PRIO3 x PETR4": C_SMALL + C_AC,
             "RECV3 x BNO": .003 + C_ETF + C_FX, "BRAV3 x BNO": .003 + C_ETF + C_FX}
    al_l = {k: .003 if "BNO" in k else .005 for k in custo}                # comprado no par = vendido no hedge
    al_s = {"PETR4 x BNO": .005, "PRIO3 x BNO": .015, "PRIO3 x PETR4": .015, "RECV3 x BNO": .04, "BRAV3 x BNO": .04}
    ini = {"PRIO3 x BNO": "2016-01-01", "PRIO3 x PETR4": "2016-01-01"}     # antes de 2016 PRIO era penny stock ilíquida
    return livro_pares(pares, jan, z_in, alvo, custo, al_l, al_s, lag, custo_mult, detalhe, inicio=ini)


# ================================================================== F3 açúcar/etanol: SMTO3/RAIZ4/JALL3 vs açúcar (CANE) + gasolina
def acucar(jan=126, z_in=1.5, hedge="acucar", alvo=.10, custo_mult=1, lag=0, detalhe=False):
    h = ex_brl("CANE") if hedge == "acucar" else .6 * ex_brl("CANE") + .4 * ex_brl("UGA")   # etanol segue a paridade com a gasolina
    pares = {"SMTO3 x acucar": (ex_br("SMTO3.SA"), h), "RAIZ4 x acucar": (ex_br("RAIZ4.SA"), h), "JALL3 x acucar": (ex_br("JALL3.SA"), h)}
    custo = {"SMTO3 x acucar": C_AC + .0003 + C_FX, "RAIZ4 x acucar": C_SMALL + .0003 + C_FX, "JALL3 x acucar": .003 + .0003 + C_FX}
    al_s = {"SMTO3 x acucar": .01, "RAIZ4 x acucar": .03, "JALL3 x acucar": .03}
    return livro_pares(pares, jan, z_in, alvo, custo, .005, al_s, lag, custo_mult, detalhe)


# ================================================================== F4 mineradoras vs o metal (mineradora = opção alavancada no metal)
def mineradoras(jan=126, z_in=1.5, vale="pares", alvo=.10, custo_mult=1, lag=0, detalhe=False):
    pares = {"GDX x GLD": (ex_us("GDX"), ex_us("GLD")), "GDXJ x GDX": (ex_us("GDXJ"), ex_us("GDX")), "SIL x SLV": (ex_us("SIL"), ex_us("SLV")),
             "COPX x CPER": (ex_us("COPX"), ex_us("CPER")), "FCX x CPER": (ex_us("FCX"), ex_us("CPER"))}
    if vale == "pares":
        pares["VALE x BHP/RIO"] = (ex_us("VALE"), .5 * ex_us("BHP") + .5 * ex_us("RIO"))
    else:
        pares["VALE3 x minerio"] = (ex_br("VALE3.SA"), ex_brl("TIO=F"))
        pares["CMIN3 x minerio"] = (ex_br("CMIN3.SA"), ex_brl("TIO=F"))
    custo = {k: 2 * C_ETF for k in pares}
    custo.update({"VALE3 x minerio": C_AC + C_FUT + C_FX, "CMIN3 x minerio": C_SMALL + C_FUT + C_FX, "FCX x CPER": .0003 + .0005})
    return livro_pares(pares, jan, z_in, alvo, custo, .003, .005, lag, custo_mult, detalhe)


# ================================================================== F6 spreads clássicos de commodities
def _crack():
    return (2 / 3 * r_fut("RB=F") + 1 / 3 * r_fut("HO=F")), r_fut("CL=F")


def _crush():
    m, o = P["ZM=F"] * .022, P["ZL=F"] * .11
    wm = (m / (m + o)).shift(1)
    return wm * r_fut("ZM=F") + (1 - wm) * r_fut("ZL=F"), r_fut("ZS=F")


def spreads(jan=63, z_in=2.0, gas=1, alvo=.10, custo_mult=1, lag=0, detalhe=False):
    pares = {"BNO x USO (Brent-WTI)": (ex_us("BNO"), ex_us("USO")), "SLV x GLD (prata/ouro)": (ex_us("SLV"), ex_us("GLD")),
             "crack 3:2:1": _crack(), "crush soja": _crush(), "PPLT x GLD (platina/ouro)": (ex_us("PPLT"), ex_us("GLD"))}
    custo = {k: 2 * C_ETF if " x " in k else 2 * C_FUT for k in pares}
    ex = livro_pares(pares, jan, z_in, alvo, custo, .003, .003, lag, custo_mult, detalhe, jb=126)
    if not gas:
        return ex
    # prêmio de inverno do gás: vende UNG de outubro a fevereiro (o contango do inverno se desfaz), fica fora no resto
    m = DIAS.month
    R = pd.DataFrame({"UNG vendido (inverno)": ex_us("UNG")})
    W = pd.DataFrame({"UNG vendido (inverno)": -np.where(np.isin(m, [10, 11, 12, 1, 2]), 1.0, 0.0)}, index=DIAS)
    W = risco_igual(W, R, alvo / 2)
    g = executa(W, R, C_ETF, 0, .01, lag, custo_mult, detalhe)
    if not detalhe:
        return ex + g
    return ex[0] + g[0], pd.concat([ex[1], g[1]], axis=1), pd.concat([ex[2], g[2]], ignore_index=True)


# ================================================================== F7 moedas de commodities vs suas commodities
MOEDAS = {"AUD": ("AUDUSD=X", 1, "AU", {"TIO=F": .4, "CPER": .3, "GLD": .3}), "CAD": ("CAD=X", -1, "CA", {"USO": 1}),
          "NOK": ("NOK=X", -1, "NO", {"BNO": 1}), "CLP": ("CLP=X", -1, "CL", {"CPER": 1}),
          "BRL": ("BRL=X", -1, "BR", {"TIO=F": .35, "SOYB": .35, "BNO": .3})}


def moedas(jan=126, z_in=1.5, alvo=.10, custo_mult=1, lag=0, detalhe=False):
    i = BIS.reindex(DIAS).ffill()
    pares, custo = {}, {}
    for m, (tk, s, pais, cesta) in MOEDAS.items():
        spot = limpa_fx((P[tk] ** s).pct_change(fill_method=None))
        fx = spot + ((i[pais] - i["US"]) / 100 / 252).shift(1)
        hed = sum(w * ex_us(k) for k, w in cesta.items())
        pares[f"{m} x commodities"] = (fx, hed)
        custo[f"{m} x commodities"] = (C_FXEM if m in ("CLP", "BRL") else C_FX) + C_ETF
    return livro_pares(pares, jan, z_in, alvo, custo, .003, .003, lag, custo_mult, detalhe)


# ================================================================== F8 exportadoras BR com hedge de commodity + dólar + Ibovespa
EXPORT = {"VALE3.SA": "TIO=F", "CMIN3.SA": "TIO=F", "CSNA3.SA": "TIO=F", "PETR4.SA": "BNO", "PRIO3.SA": "BNO", "SUZB3.SA": None,
          "KLBN11.SA": None, "JBSS32.SA": "LE=F", "BEEF3.SA": "LE=F", "MBRF3.SA": "LE=F", "SMTO3.SA": "CANE", "SLCE3.SA": "SOYB",
          "GGBR4.SA": None, "BRFS3.SA": "HE=F"}


def _exportadoras(jb=252):
    usd = R_USD - (CDI - TB)
    R, F = {}, {}
    for a, h in EXPORT.items():
        ra = ex_br(a)
        if a == "PRIO3.SA":
            ra = ra.where(ra.index >= "2016-01-01")
        fat = {"ibov": IBOV, "comm": ex_brl(h) if h else usd}
        X = pd.DataFrame(fat)
        y5, X5 = ra.rolling(5).sum(), X.rolling(5).sum()
        c = X5.rolling(jb, min_periods=jb // 2).cov()
        cy = X5.rolling(jb, min_periods=jb // 2).cov(y5)
        b = {}
        n = len(X.columns)
        cv = c.values.reshape(-1, n, n)
        cyv = cy.values
        sol = np.full((len(X), n), np.nan)
        for t in range(len(X)):
            if np.isfinite(cv[t]).all() and np.isfinite(cyv[t]).all():
                try:
                    sol[t] = np.linalg.solve(cv[t], cyv[t])
                except np.linalg.LinAlgError:
                    pass
        bet = pd.DataFrame(sol, index=X.index, columns=X.columns).clip(-.5, 2.5).shift(1)
        R[a.replace(".SA", "")] = ra - (bet * X).sum(axis=1, min_count=2)
    R = pd.DataFrame(R)
    return R.where(R.notna().cumsum() > 0)


_CACHE = {}


def exportadoras(modo="todas", jan=126, alvo=.10, custo_mult=1, lag=0, detalhe=False):
    if "R" not in _CACHE:
        _CACHE["R"] = _exportadoras()
    R = _CACHE["R"]
    X = R.fillna(0).cumsum()
    if modo == "todas":
        S = R.notna().astype(float)
    else:
        mom = (X.shift(5) - X.shift(jan)).where(R.notna())                       # resíduo de jan dias, pulando a última semana
        rk = mom.rank(axis=1, pct=True)
        S = (rk >= 2 / 3).astype(float) - (rk <= 1 / 3).astype(float)
        if modo == "reversao":
            S = -S
    S = mensal(S.fillna(0))
    W = vol_alvo(risco_igual(S, R.fillna(0), alvo), R.fillna(0), alvo, teto=2.0)
    custo = pd.Series(C_AC + C_ETF + C_FX + .0001, index=R.columns)
    custo[["PRIO3", "BEEF3", "SLCE3", "CMIN3", "SMTO3", "MBRF3", "BRFS3"]] += .001
    return executa(W, R, custo, .003, .01, lag, custo_mult, detalhe)


# ================================================================== F9 CFTC: contra o posicionamento extremo dos especuladores
COTC = {"GLD": "088691", "SLV": "084691", "CPER": "085692", "USO": "067651", "UNG": "023651", "CORN": "002602", "SOYB": "005602",
        "WEAT": "001602", "CANE": "080732", "KC=F": "083731", "LE=F": "057642", "CT=F": "033661", "HE=F": "054642"}


def cot_mm():
    if "cot" in _CACHE:
        return _CACHE["cot"]
    c = pd.read_parquet(D / "cot.parquet")
    c = c[c.relatorio == "com"].copy()
    c["dt"] = pd.to_datetime(c["Report_Date_as_YYYY-MM-DD"], errors="coerce")
    c["cod"] = c.CFTC_Contract_Market_Code.astype(str).str.strip()
    c["net"] = (c.M_Money_Positions_Long_All - c.M_Money_Positions_Short_All) / c.Open_Interest_All
    out = {}
    for a, k in COTC.items():
        g = c[c.cod == k].sort_values("Open_Interest_All").groupby("dt").net.last()
        out[a] = g
    m = pd.DataFrame(out).sort_index()
    m.index = m.index + pd.Timedelta(days=3)                               # terça -> publicado sexta 15h30 (ET)
    _CACHE["cot"] = m
    return m


def cftc(lim=.95, saida="50", confirma=0, alvo=.10, custo_mult=1, lag=0, detalhe=False):
    m = cot_mm()
    pct = m.rolling(156, min_periods=104).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
    sinal = pd.DataFrame(0.0, index=pct.index, columns=pct.columns)
    pv = pct.values
    pos = np.zeros(pv.shape[1])
    t = np.zeros(pv.shape[1])
    out = np.zeros_like(pv)
    for i in range(len(pv)):
        p = pv[i]
        ok = np.isfinite(p)
        if saida == "50":
            fecha = ((pos == -1) & (p < .5)) | ((pos == 1) & (p > .5)) | ~ok
        else:
            fecha = (t >= int(saida)) | ~ok
        pos[fecha], t[fecha] = 0, 0
        pos[(pos == 0) & ok & (p >= lim)] = -1
        pos[(pos == 0) & ok & (p <= 1 - lim)] = 1
        t[pos != 0] += 1
        out[i] = pos
    sinal[:] = out
    S = _dias(sinal, lim=7).fillna(0)
    R = pd.DataFrame({a: ex_us(a) for a in COTC})
    if confirma:                                                            # só entra/fica quando o preço já virou contra a multidão (4 semanas)
        m20 = R.fillna(0).rolling(20).sum()
        S = S.where(np.sign(m20) == S, 0)
    W = vol_alvo(risco_igual(S, R, alvo), R.fillna(0), alvo, teto=2.0)          # poucas posições abertas: escala o livro para a vol-alvo
    custo = {a: C_FUT if "=F" in a else C_ETF for a in COTC}
    return executa(W, R, custo, .003, .003, lag, custo_mult, detalhe)


# ================================================================== B3 agro: futuros contínuos e estrutura a termo
MESES = dict(zip("FGHJKMNQUVXZ", range(1, 13)))


def b3_agro():
    if "agro" in _CACHE:
        return _CACHE["agro"]
    x = pd.read_parquet(D / "b3_futuros_agro.parquet")
    x = x[x.AdjstdQt.notna() & (x.AdjstdQt > 0)]
    x = x.sort_values("OpnIntrst").drop_duplicates(["date", "ticker"], keep="last")
    x["prod"] = x.ticker.str[:3]
    x["venc"] = pd.to_datetime(dict(year=2000 + x.ticker.str[4:6].astype(int), month=x.ticker.str[3].map(MESES), day=15))
    x["dias"] = (x.venc - x.date).dt.days
    _CACHE["agro"] = x
    return x


@lru_cache(None)
def agro_serie(prod, ordem=2, rolar=20):
    """Série de retorno de carregar o `ordem`-ésimo vencimento com vencimento > `rolar` dias (decidido em t-1), carry anualizado (F1/F2)."""
    x = b3_agro()
    g = x[(x["prod"] == prod) & (x.dias > rolar) & (x.OpnIntrst.fillna(0) > 50)]
    px = g.pivot(index="date", columns="ticker", values="AdjstdQt").reindex(DIAS)
    dd = g.pivot(index="date", columns="ticker", values="dias").reindex(DIAS)
    ret, carry, seg = pd.Series(np.nan, index=DIAS), pd.Series(np.nan, index=DIAS), pd.Series(None, index=DIAS, dtype=object)
    cols = np.array(px.columns)
    pv, dv = px.values, dd.values
    ant = None
    for i in range(len(DIAS)):
        ok = np.isfinite(pv[i]) & np.isfinite(dv[i])
        if ok.sum() < 2:
            ant = None
            continue
        o = np.argsort(np.where(ok, dv[i], np.inf))
        if ant is not None and np.isfinite(pv[i, ant]) and np.isfinite(pv[i - 1, ant]):
            ret.iloc[i] = pv[i, ant] / pv[i - 1, ant] - 1
        c1, c2 = o[0], o[1]
        carry.iloc[i] = np.log(pv[i, c1] / pv[i, c2]) * 365 / max(dv[i, c2] - dv[i, c1], 20)
        ant = o[min(ordem - 1, ok.sum() - 1)]
        seg.iloc[i] = cols[ant]
    return ret.where(ret.abs() < .25), carry, seg


AGRO = {"BGI": "LE=F", "CCM": "CORN", "ICF": "KC=F", "SJC": "SOYB", "ETH": None}


def _dessazonaliza(K):
    """Carry menos a média do mesmo mês do ano nos anos ANTERIORES (curva agro B3 é dominada por safra/entressafra)."""
    Km = K.resample("ME").mean()
    norma = Km.groupby(Km.index.month).transform(lambda x: x.shift(1).expanding(min_periods=1).mean())
    norma.index = norma.index.to_period("M")
    return K - norma.reindex(K.index.to_period("M")).values


def carry_agro(modo="ts", lim=.0, cot=1, alvo=.10, custo_mult=1, lag=0, detalhe=False):
    """Carry dos futuros agro B3: comprado em backwardation (spot > futuro: estoque apertado), vendido em contango.
    Filtro CFTC (CCM/SJC/ICF/BGI): não fica do mesmo lado de especuladores lotados (percentil > 90 / < 10 de 3 anos)."""
    R, K = {}, {}
    for p in AGRO:
        r, k, _ = agro_serie(p)
        R[p], K[p] = r, k.rolling(5, min_periods=1).mean()
    R, K = pd.DataFrame(R), pd.DataFrame(K)
    # o contango "normal" é o custo de carregar o estoque = juro: F2/F1 ~ e^{(r - y)T}. Somando o juro (CDI p/ contratos em R$,
    # T-bill p/ ICF/SJC em dólar) sobra o rendimento de conveniência y: y > 0 = estoque apertado (o sinal de verdade).
    juro = pd.DataFrame({p: (TB * 252 if p in ("ICF", "SJC") else np.log1p(CDI) * 252) for p in AGRO}).rolling(5, min_periods=1).mean()
    K = K + juro
    if modo.startswith("saz"):
        K = _dessazonaliza(K)
    if modo.endswith("ts"):
        S = np.sign(K.where(K.abs() > lim, 0))
    else:
        rk = K.rank(axis=1, pct=True)
        S = (rk > .6).astype(float) - (rk < .4).astype(float)
    if cot:
        m = cot_mm()
        pct = m.rolling(156, min_periods=104).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
        pct = _dias(pct, 7)
        for p, us in AGRO.items():
            if us and us in pct:
                S[p] = S[p].where(~(((S[p] > 0) & (pct[us] > .9)) | ((S[p] < 0) & (pct[us] < .1))), 0)
    S = semanal(S.fillna(0))
    W = risco_igual(S, R.fillna(0), alvo * np.sqrt(len(AGRO) / 3))
    custo = {"BGI": .0005, "CCM": .0008, "ICF": .0015, "SJC": .0015, "ETH": .003}   # meio spread + emolumentos; ETH/ICF pouco líquidos
    # a troca de vencimento (rolagem) custa mais uma ida e volta: ~1 por mês em média
    ex = executa(W, R, custo, 0, 0, lag, custo_mult, detalhe)
    rol = (W.shift(1 + lag).abs() * pd.Series(custo) * 2 * custo_mult / 21).sum(axis=1)
    if not detalhe:
        return ex - rol
    return ex[0] - rol, ex[1], ex[2]


# ================================================================== F2 proteína: margem dos frigoríficos (boi/milho)
def proteina(jan=63, sinal="margem", alvo=.10, custo_mult=1, lag=0, detalhe=False):
    """Margem do frigorífico = preço da proteína (LE/HE x dólar) - custo (boi gordo BGI / milho CCM, B3).
    Compra o frigorífico cuja margem implícita nos futuros melhorou e vende o que piorou (ou vs Ibovespa)."""
    idx = lambda p: np.log1p(agro_serie(p, ordem=1)[0].fillna(0)).cumsum().where(agro_serie(p, ordem=1)[0].notna().cumsum() > 0)
    boi, milho = idx("BGI"), idx("CCM")                                    # índice rolado (sem saltos de vencimento)
    carne = np.log(P["LE=F"] * P["BRL=X"])
    porco = np.log(P["HE=F"] * P["BRL=X"])
    mb, mf = carne - boi, porco - milho                                    # margem bovina (BR) e de aves/suínos
    dm = lambda m: ((m - m.shift(jan)) / (m.diff(jan).rolling(504, min_periods=126).std())).clip(-2, 2) / 2
    if sinal == "ciclo":                                                   # boi caro subindo = fase de retenção: vende bovino, compra aves/suínos
        dmb = -dm(boi)
        dmf = -dm(milho)
    else:
        dmb, dmf = dm(mb), dm(mf)
    sc = {"BEEF3": dmb, "MBRF3": .5 * dmb + .5 * dmf, "JBSS32": .4 * dmb + .6 * dmf, "BRFS3": dmf}
    R = pd.DataFrame({k: ex_br(k + ".SA") for k in sc})
    b = pd.DataFrame({k: beta(R[k], IBOV) for k in sc})
    R = R - b.mul(IBOV, axis=0)                                            # cada ação com hedge de Ibovespa (WIN)
    S = pd.DataFrame(sc).where(R.notna())
    S = S.sub(S.mean(axis=1), axis=0)                                      # long-short dentro do setor
    S = semanal(S.fillna(0))
    W = vol_alvo(risco_igual(S, R.fillna(0), alvo), R.fillna(0), alvo, teto=3.0)
    custo = {"BEEF3": .0015, "MBRF3": .0012, "JBSS32": .0012, "BRFS3": .0010}
    return executa(W, R.fillna(0), custo, .0, .02, lag, custo_mult, detalhe)


# ================================================================== fundos
FUNDOS = [
    Fundo("C1 Petróleo: PETR4/PRIO3 vs Brent em R$", "Valor relativo commodities", "CDI",
          "A ação de petroleira é o petróleo em reais + o risco da empresa. Quando a ação fica para trás do Brent×dólar (resíduo da "
          "regressão rolante muito negativo), compro a ação e vendo BNO na proporção do beta; quando a ação andou demais, o inverso. "
          "PRIO3 (pura) vs PETR4 (estatal, risco político) como par adicional.",
          "Pares ação x BNO em R$ (sem hedge cambial), beta 1 ano (retornos semanais), z-score do resíduo, entra |z|>z_in, sai em 0, "
          "stop |z|>4 ou 120 dias; risco igual por par, vol-alvo 10%", petroleo,
          {"jan": [63, 126], "z_in": [1.0, 2.0], "conj": ["brent", "brent+par"]}),
    Fundo("C2 Proteína: margem boi/milho nos frigoríficos", "Valor relativo commodities", "CDI",
          "A margem do frigorífico aparece nos futuros antes do balanço: carne (LE×dólar) menos boi gordo (BGI B3) para Minerva/Marfrig, "
          "porco (HE×dólar) menos milho (CCM B3) para BRF. Compro quem tem margem melhorando e vendo quem tem margem piorando.",
          "BEEF3, MBRF3 (Marfrig), JBS, BRFS3 com hedge de Ibovespa; sinal = variação da margem em jan dias / desvio; long-short setorial",
          proteina, {"jan": [63, 126], "sinal": ["margem", "ciclo"]}, inicio="2019-01-01", corte="2023-01-01"),
    Fundo("C3 Açúcar/etanol: usinas vs açúcar", "Valor relativo commodities", "CDI",
          "Usina é açúcar + etanol em reais; quando SMTO3/RAIZ4/JALL3 descolam do açúcar (CANE) em R$, aposto na volta, com hedge em açúcar.",
          "Pares usina x CANE (ou 60% CANE + 40% gasolina UGA) em R$, z-score do resíduo, histerese", acucar,
          {"jan": [63, 126], "z_in": [1.0, 2.0], "hedge": ["acucar", "acucar+gasolina"]}),
    Fundo("C4 Mineradoras vs metal", "Valor relativo commodities", "CDI",
          "Mineradora é uma opção alavancada no metal: GDX/GLD, GDXJ/GDX, SIL/SLV, COPX/CPER, FCX/CPER e Vale (vs BHP/RIO ou vs minério SGX). "
          "Quando a mineradora fica para trás do metal, compro a mineradora e vendo o metal (e vice-versa).",
          "Pares em dólar com hedge cambial; beta 1 ano; z-score do resíduo; histerese", mineradoras,
          {"jan": [63, 126], "z_in": [1.0, 2.0], "vale": ["pares", "minerio"]}),
    Fundo("C5 Carry agro B3 (estrutura a termo) + filtro CFTC", "Commodities", "CDI",
          "Curva invertida (spot > futuro) = estoque apertado; quem carrega o futuro ganha o roll. Compro boi/milho/café/soja/etanol B3 em "
          "backwardation e vendo em contango; não fico do lado dos especuladores lotados nos EUA (CFTC percentil 90/10).",
          "Futuros B3 (2º vencimento), carry = log(F1/F2) anualizado, semanal, risco igual; custo de rolagem mensal", carry_agro,
          {"modo": ["ts", "xs", "saz_ts", "saz_xs"], "cot": [0, 1]}, inicio="2019-03-01", corte="2023-01-01"),
    Fundo("C6 Spreads clássicos de commodities", "Valor relativo commodities", "CDI",
          "Brent-WTI, prata/ouro, platina/ouro, crack 3:2:1 e crush da soja voltam à média (refinaria e esmagadora arbitram); "
          "e vendo o gás natural no inverno (o prêmio de inverno e o contango do UNG se desfazem).",
          "ETFs (BNO/USO, SLV/GLD, PPLT/GLD) e futuros contínuos com rolagem zerada (RB/HO/CL, ZS/ZM/ZL); z 63-126 dias; gás: UNG vendido out-fev",
          spreads, {"jan": [63, 126], "z_in": [1.5, 2.0], "gas": [0, 1]}),
    Fundo("C7 Moedas de commodities vs commodities", "Valor relativo commodities", "CDI",
          "AUD, CAD, NOK, CLP e BRL são commodities disfarçadas; quando a moeda descola da cesta de exportação, compro a moeda barata "
          "e vendo as commodities (carry da moeda incluído).",
          "Pares moeda (spot + diferencial de juro BIS) x cesta (minério SGX, cobre, ouro, petróleo, soja); z-score do resíduo", moedas,
          {"jan": [63, 126, 252], "z_in": [1.0, 1.5, 2.0]}),
    Fundo("C8 Exportadoras BR com hedge de commodity", "Long-short ações", "CDI",
          "Isola o alfa da empresa: compra exportadoras e vende a commodity em R$ (ou o dólar) e o Ibovespa na proporção dos betas; "
          "variante momentum/reversão do resíduo (quem está executando melhor que a commodity continua).",
          "14 exportadoras, betas de 2 fatores (Ibovespa e commodity em R$) de 1 ano; mensal; risco igual", exportadoras,
          {"modo": ["todas", "momentum", "reversao"], "jan": [126, 252]}),
    Fundo("C9 CFTC contrarian (especulador lotado)", "Commodities", "CDI",
          "Quando os managed money estão no percentil 95 de 3 anos de posição líquida, todo mundo já comprou: vendo. No percentil 5, compro.",
          "13 mercados (ETFs e futuros com rolagem zerada), COT publicado sexta, executa na segunda; sai no percentil 50 ou após N semanas",
          cftc, {"lim": [.90, .95], "saida": ["50", "20"], "confirma": [0, 1]}, inicio="2016-01-01"),
]


def roda_tudo(so=None):
    from rodar import BENCH
    res = []
    for f in FUNDOS:
        if so and f.nome[:2] not in so:
            continue
        r = roda(f, CDI, BENCH[f.benchmark], lambda *a: print(*a, flush=True))
        if r is None:
            print(f"{f.nome}: sem resultado", flush=True)
            continue
        ex, C, T = f.func(**r["params"], detalhe=True)
        r["contrib"], r["trades"] = C[C.index >= f.inicio], T[T.entrada >= f.inicio].reset_index(drop=True)
        o, rb = r["oos"], r["rob"]
        print(f"{f.nome[:48]:48s} {str(r['params']):55s} IS IR {r['is_ir']:5.2f} | OOS {o['retorno a.a. %']:5.1f}% vs {o['benchmark a.a. %']:5.1f}% "
              f"IR {o['IR vs bench']:5.2f} | P {rb['P(bater bench OOS) %']:3.0f}% | PBO {rb['PBO %']:3.0f}% | x2 {rb['OOS custo x2 (pp)']:5.1f} "
              f"| lag {rb['OOS execução +1 dia (pp)']:5.1f} | tot IR {r['total']['IR vs bench']:.2f}", flush=True)
        res.append(r)
    for r in res:
        r["fundo"].func = None
    return res


if __name__ == "__main__":
    so = sys.argv[1:]
    res = roda_tudo(so)
    out = D.parent / "resultado" / ("ideias_commodities.pkl" if not so else f"ideias_commodities_{'_'.join(so)}.pkl")
    pickle.dump(res, open(out, "wb"))
    print("salvo", out)
