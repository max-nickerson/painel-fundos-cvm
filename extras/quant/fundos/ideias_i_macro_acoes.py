"""
Rodada 2 / FASE 2 — frente I_MACRO_ACOES: estratégias de AÇÕES e MACRO do Brasil/rodada 1 replicadas em EUA, Europa e Ásia.
  IM1 Pares intra-setor com tese (KO x PEP, V x MA, HD x LOW, bancos, teles europeias, Toyota x Honda, TSMC x UMC, Samsung x Hynix...)
  IM2 Reversão semanal de large caps neutra por setor/país (EUA, Japão, Europa) — o "ML semanal" do Brasil, em versão de mesa
  IM3 Vende ações sensíveis a crédito quando o high yield abre (preço/volume: beta ao HY)
  IM4 Rotação de países: valor (REER do BIS + reversão de 5 anos) + momento + carry, L/S contra o ACWI
  IM5 Moedas EM/G10 por valor (PPP/REER) + juro real, com stop
  IM6 CTA global com vol-alvo por ativo e stop de crise / "tendência de crises" (vende ações só quando o crédito abre)
  IM7 Calendário global: virada de mês (Japão/Europa/Brasil), pré-feriado EUA, Golden Week, Ano-Novo Lunar, Ramadã no Golfo, "Sell in May"
  IM8 Eleições: compra o índice do país depois do pânico eleitoral, com hedge cambial
Uso: python ideias_i_macro_acoes.py dados   (baixa o que falta, com cache)
     python ideias_i_macro_acoes.py [IM1 IM2 ...]   (roda e salva resultado/ideias_i_macro_acoes.pkl)
Tudo em USD (excesso sobre o T-bill ou sobre o juro local quando hedgeado) e convertido para R$ com hedge via brl(): fundo = CDI + excesso.
"""
import io
import pickle
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

from base import BIS, CDI, DIAS, DIAS_US, ETF, FXY, IDX, R_IBOV, TB_US, D, brl, limpa, vol_alvo
from motor import Fundo, roda

# =============================================================== DADOS
F_ACOES, F_IDX, F_CPI, F_REER = D / "y_imacro_acoes.parquet", D / "y_imacro_idx.parquet", D / "bis_cpi.parquet", D / "bis_reer.parquet"

PARES = {  # nome: (A, B, mercado) — custos/impostos/aluguel por mercado em MERC
    # EUA (custo 3 bps, aluguel 0,3%)
    "KO x PEP": ("KO", "PEP", "US"), "V x MA": ("V", "MA", "US"), "HD x LOW": ("HD", "LOW", "US"), "JPM x BAC": ("JPM", "BAC", "US"),
    "WFC x C": ("WFC", "C", "US"), "GS x MS": ("GS", "MS", "US"), "XOM x CVX": ("XOM", "CVX", "US"), "UPS x FDX": ("UPS", "FDX", "US"),
    "LMT x NOC": ("LMT", "NOC", "US"), "UNP x CSX": ("UNP", "CSX", "US"), "T x VZ": ("T", "VZ", "US"), "PG x CL": ("PG", "CL", "US"),
    "CAT x DE": ("CAT", "DE", "US"), "NEM x AEM": ("NEM", "AEM", "US"), "MCD x YUM": ("MCD", "YUM", "US"), "MO x PM": ("MO", "PM", "US"),
    # Europa (5 bps; imposto: UK 0,5% compra, FR 0,3%, IT 0,1%, ES 0,2%)
    "SHEL x BP (Londres)": ("SHEL.L", "BP.L", "UK"), "BARC x LLOY": ("BARC.L", "LLOY.L", "UK"), "HSBA x STAN": ("HSBA.L", "STAN.L", "UK"),
    "VOD x BT": ("VOD.L", "BT-A.L", "UK"), "DTE x ORA": ("DTE.DE", "ORA.PA", "EU"), "TEF x ORA": ("TEF.MC", "ORA.PA", "EU"),
    "BNP x GLE": ("BNP.PA", "GLE.PA", "FR"), "SAN x BBVA": ("SAN.MC", "BBVA.MC", "ES"), "ISP x UCG": ("ISP.MI", "UCG.MI", "IT"),
    "ALV x CS": ("ALV.DE", "CS.PA", "EU"), "BMW x MBG": ("BMW.DE", "MBG.DE", "DE"), "EOAN x RWE": ("EOAN.DE", "RWE.DE", "DE"),
"MC x KER": ("MC.PA", "KER.PA", "FR"),
    # Ásia (Japão 5 bps sem imposto; Coreia 0,2% na venda; Taiwan 0,3% na venda; HK 0,1% cada lado; Austrália 5 bps; Índia 0,1% cada lado)
    "Toyota x Honda": ("7203.T", "7267.T", "JP"), "MUFG x SMFG": ("8306.T", "8316.T", "JP"), "Mitsubishi x Mitsui": ("8058.T", "8031.T", "JP"),
    "NTT x KDDI": ("9432.T", "9433.T", "JP"), "Takeda x Astellas": ("4502.T", "4503.T", "JP"), "Sony x Panasonic": ("6758.T", "6752.T", "JP"),
    "TSMC x UMC": ("2330.TW", "2303.TW", "TW"), "Samsung x Hynix": ("005930.KS", "000660.KS", "KR"), "KB x Shinhan": ("105560.KS", "055550.KS", "KR"),
    "Hyundai x Kia": ("005380.KS", "000270.KS", "KR"), "CCB x ICBC": ("0939.HK", "1398.HK", "HK"), "CMob x Unicom": ("0941.HK", "0762.HK", "HK"),
    "BHP x RIO (ASX)": ("BHP.AX", "RIO.AX", "AU"), "CBA x WBC": ("CBA.AX", "WBC.AX", "AU"), "NAB x ANZ": ("NAB.AX", "ANZ.AX", "AU"),
    "HDFC x ICICI": ("HDFCBANK.NS", "ICICIBANK.NS", "IN"), "INFY x TCS": ("INFY.NS", "TCS.NS", "IN"),
}
# custo por perna (corretagem+spread), aluguel a.a., imposto na compra, imposto na venda — por mercado
MERC = {"US": (.0003, .003, 0, 0), "UK": (.0005, .005, .005, 0), "EU": (.0005, .005, .0015, 0), "FR": (.0005, .005, .003, 0),
        "ES": (.0005, .005, .002, 0), "IT": (.0005, .005, .001, 0), "DE": (.0005, .005, 0, 0), "CH": (.0005, .005, 0, 0),
        "JP": (.0005, .006, 0, 0), "TW": (.0008, .02, 0, .003), "KR": (.0008, .02, 0, .002), "HK": (.0008, .015, .001, .001),
        "AU": (.0005, .006, 0, 0), "IN": (.0008, .03, .001, .001)}

# universos de large caps (lista ATUAL -> viés de sobrevivência, documentado no caderno)
US100 = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "BRK-B", "JPM", "JNJ", "V", "PG", "UNH", "HD", "MA", "XOM", "CVX", "PFE", "KO", "PEP",
         "MRK", "ABBV", "BAC", "WMT", "COST", "DIS", "CSCO", "INTC", "ORCL", "IBM", "T", "VZ", "CMCSA", "MCD", "NKE", "WFC", "C", "GS", "MS",
         "AXP", "BLK", "CAT", "DE", "HON", "GE", "MMM", "BA", "LMT", "RTX", "UPS", "FDX", "UNP", "CSX", "NSC", "LOW", "TGT", "SBUX", "MO",
         "PM", "CL", "KMB", "GIS", "MDLZ", "TXN", "QCOM", "AMGN", "GILD", "BMY", "LLY", "ABT", "TMO", "DHR", "MDT", "CVS", "SO", "DUK",
         "NEE", "D", "AEP", "EXC", "SPG", "AMT", "USB", "PNC", "COF", "MET", "AIG", "ALL", "TRV", "ADP", "ACN", "EMR", "ITW", "F", "GM",
         "COP", "OXY", "SLB", "EOG", "NEM", "FCX", "DOW", "LIN", "APD", "ECL", "SHW"]
JP60 = ["7203.T", "7267.T", "6758.T", "6752.T", "8306.T", "8316.T", "8411.T", "8058.T", "8031.T", "8001.T", "8053.T", "9432.T", "9433.T",
        "9984.T", "4502.T", "4503.T", "4568.T", "4519.T", "6501.T", "6502.T", "6503.T", "6701.T", "6702.T", "6861.T", "6954.T", "6981.T",
        "7751.T", "7741.T", "8035.T", "6367.T", "6301.T", "7011.T", "7201.T", "7269.T", "7270.T", "5108.T", "4063.T", "4452.T", "2914.T",
        "2502.T", "2802.T", "3382.T", "8267.T", "9020.T", "9022.T", "9501.T", "9503.T", "5401.T", "5411.T", "8766.T", "8725.T", "8604.T",
        "8802.T", "8801.T", "1925.T", "1928.T", "4901.T", "6902.T", "7974.T", "9983.T"]
EU60 = ["SAP.DE", "SIE.DE", "ALV.DE", "DTE.DE", "BAS.DE", "BAYN.DE", "BMW.DE", "MBG.DE", "VOW3.DE", "EOAN.DE", "RWE.DE", "MUV2.DE", "DBK.DE",
        "ADS.DE", "IFX.DE", "MC.PA", "OR.PA", "TTE.PA", "SAN.PA", "BNP.PA", "GLE.PA", "AI.PA", "SU.PA", "CS.PA", "ORA.PA", "KER.PA", "RI.PA",
        "BN.PA", "DG.PA", "SGO.PA", "AIR.PA", "EL.PA", "ENGI.PA", "SAN.MC", "BBVA.MC", "IBE.MC", "TEF.MC", "ITX.MC", "REP.MC", "ISP.MI",
        "UCG.MI", "ENEL.MI", "ENI.MI", "G.MI", "ASML.AS", "INGA.AS", "PHIA.AS", "AD.AS", "UNA.AS", "NOVN.SW", "ROG.SW", "NESN.SW", "UBSG.SW",
        "ABBN.SW", "ZURN.SW", "NOKIA.HE", "ERIC-B.ST", "VOLV-B.ST", "NOVO-B.CO", "ABI.BR"]
# índices locais (preço) para calendário/eleições: retorno em moeda local = posição com hedge cambial (futuro de índice)
INDICES = ["^N225", "^GDAXI", "^FTSE", "^FCHI", "FTSEMIB.MI", "^IBEX", "^SSMI", "^AEX", "^OMX", "^AXJO", "^GSPTSE", "^MXX", "^MERV",
           "XU100.IS", "^NSEI", "^BSESN", "^JKSE", "^KS11", "^TWII", "^HSI", "^KLSE", "^SET.BK", "PSEI.PS", "^JN0U.JO", "^IPSA",
           "^SPBLPGPT", "WIG20.WA", "^TASI.SR", "^STOXX50E", "000001.SS", "^STI", "^NZ50", "^BVSP", "GD.AT", "^BUX.BD"]


def _yahoo_lote(tks):
    from dados_fundos import yahoo
    with ThreadPoolExecutor(8) as ex:
        s = [x for x in ex.map(yahoo, tks) if x is not None]
    return pd.concat(s, axis=1)


def _bis(flow, chave):
    u = f"https://stats.bis.org/api/v1/data/{flow}/{chave}/all?startPeriod=1995-01&format=csv"
    d = pd.read_csv(io.StringIO(requests.get(u, timeout=180).text))
    return d.pivot_table(index="TIME_PERIOD", columns="REF_AREA", values="OBS_VALUE")


def baixa():
    if not F_ACOES.exists():
        tks = sorted({t for a, b, _ in PARES.values() for t in (a, b)} | set(US100) | set(JP60) | set(EU60) | {"GOLD", "B", "KGC", "GDX"})
        _yahoo_lote(tks).to_parquet(F_ACOES)
    if not F_IDX.exists():
        _yahoo_lote(INDICES).to_parquet(F_IDX)
    if not F_CPI.exists():
        c = _bis("WS_LONG_CPI", "M..628")
        c.index = pd.PeriodIndex(c.index, freq="M").to_timestamp("M")
        c.to_parquet(F_CPI)
    if not F_REER.exists():
        r = _bis("WS_EER", "M.R.B.")
        r.index = pd.PeriodIndex(r.index, freq="M").to_timestamp("M")
        r.to_parquet(F_REER)
    for f in (F_ACOES, F_IDX, F_CPI, F_REER):
        d = pd.read_parquet(f)
        print(f.name, d.shape, d.index.min(), d.index.max(), flush=True)


if __name__ == "__main__" and sys.argv[1:2] == ["dados"]:
    baixa()
    sys.exit()

# =============================================================== MÁQUINA COMUM
PX = pd.read_parquet(F_ACOES)
IX = pd.read_parquet(F_IDX)
EXT = pd.concat([ETF, pd.read_parquet(D / "y_fronteira.parquet")], axis=1)
EXT = EXT.loc[:, ~EXT.columns.duplicated()]


def rf_dia(idx, cc="US"):
    """Juro de política (BIS) do país cc ao dia, no calendário idx (aproxima o custo do hedge/financiamento)."""
    i = BIS[cc] if cc in BIS else BIS["US"]
    return (i.reindex(pd.DatetimeIndex(idx).union(i.index)).ffill().reindex(idx) / 100 / 252).fillna(0)


def tb_dia(idx):
    return TB_US.reindex(pd.DatetimeIndex(idx).union(TB_US.index)).ffill().reindex(idx).fillna(0)


def contrib(W, R, custo, alug=0.0, lag=0, cm=1):
    """Igual a base.carteira, mas devolve a contribuição por ativo. W decidido no fechamento de t (calendário de R),
    executado no fechamento de t+1+lag. custo/alug: escalar ou Series por coluna (custo = por unidade de giro, já com impostos)."""
    R = R.fillna(0)
    We = W.reindex(R.index).fillna(0).shift(1 + lag).fillna(0)
    cs = lambda x: pd.Series(x, index=R.columns) if np.isscalar(x) else pd.Series(x).reindex(R.columns).fillna(0)
    return (We.shift(1) * R - We.diff().abs() * cs(custo) * cm - (-We.shift(1)).clip(lower=0) * cs(alug) / 252).fillna(0), We


def negocios(S, C, R=None, extra=None):
    """S: posição executada (sinal) por ativo/par; C: contribuição diária. Uma linha por período com sinal constante."""
    lin = []
    for c in S.columns:
        s = np.sign(S[c].fillna(0).values)
        mud = np.flatnonzero(np.diff(np.r_[0, s]) != 0)
        for k, i0 in enumerate(mud):
            if s[i0] == 0:
                continue
            i1 = mud[k + 1] if k + 1 < len(mud) else len(s)
            seg = slice(i0 + 1, min(i1 + 1, len(s)))
            d = {"ativo": c, "lado": "comprado" if s[i0] > 0 else "vendido", "entrada": S.index[i0], "saida": S.index[min(i1, len(s) - 1)],
                 "dias": int(i1 - i0), "contrib": float(C[c].values[seg].sum())}
            if R is not None and c in R:
                d["retorno"] = float(np.prod(1 + s[i0] * R[c].fillna(0).values[seg]) - 1)
            if extra is not None and c in extra:
                v = extra[c].values[i0]
                d["sinal_entrada"] = float(v) if np.isfinite(v) else np.nan
            lin.append(d)
    return pd.DataFrame(lin)


def fim_sem(idx):
    p = pd.Series(pd.DatetimeIndex(idx).to_period("W-FRI"), index=idx)
    return p.ne(p.shift(-1)).values


def fim_mes(idx):
    p = pd.Series(pd.DatetimeIndex(idx).to_period("M"), index=idx)
    return p.ne(p.shift(-1)).values


# =============================================================== IM1 PARES INTRA-SETOR
KR_BAN = [("2008-10-01", "2009-06-01"), ("2011-08-10", "2011-11-10"), ("2020-03-16", "2021-05-03"), ("2023-11-06", "2025-03-31")]
RF_MERC = {"US": "US", "JP": "JP", "AU": "AU", "KR": "KR", "IN": "IN", "UK": "GB", "CH": "CH", "HK": "US", "TW": "US"}


def _estado(z, ok, z_in, z_stop=3.5, tmax=126, bloqueio=63):
    """Histerese: entra contra o desvio quando |z|>z_in (e ok), sai em z=0, stop em |z|>z_stop (quebra estrutural:
    bloqueia o par por `bloqueio` dias), ou depois de tmax dias."""
    out = np.zeros(len(z))
    pos, t, blq = 0, 0, 0
    for i in range(len(z)):
        zi = z[i]
        blq = max(blq - 1, 0)
        if pos != 0:
            t += 1
            if not np.isfinite(zi) or t >= tmax or (pos == 1 and zi > 0) or (pos == -1 and zi < 0):
                pos, t = 0, 0
            elif abs(zi) > z_stop:
                pos, t, blq = 0, 0, bloqueio
        if pos == 0 and blq == 0 and np.isfinite(zi) and ok[i] and z_in < abs(zi) < z_stop:
            pos, t = (-1 if zi > 0 else 1), 0
        out[i] = pos
    return out


def _par(nome, jan, z_in, filtro, alvo, lag, cm):
    a, b, mk = PARES[nome]
    if a not in PX or b not in PX:
        return None
    p = PX[[a, b]].dropna()
    r = p.pct_change(fill_method=None)
    ruim = (r.abs() > .25).any(axis=1)                                     # limpa o PAR (não perna a perna)
    r = r.where(~ruim, 0.0).fillna(0)
    a5, b5 = r[a].rolling(5).sum(), r[b].rolling(5).sum()
    beta = (a5.rolling(252, min_periods=126).cov(b5) / b5.rolling(252, min_periods=126).var()).clip(.3, 2).shift(1)
    e = (r[a] - beta * r[b]).fillna(0)
    X = e.cumsum()
    z = (X - X.rolling(jan, min_periods=jan // 2).mean()) / X.rolling(jan, min_periods=jan // 2).std()
    # filtro de cointegração / quebra estrutural: estatística t (Dickey-Fuller sem defasagens) do resíduo acumulado nos últimos 252 dias
    dX, Xl = X.diff(), X.shift(1)
    vx = Xl.rolling(252, min_periods=200).var()
    bb = dX.rolling(252, min_periods=200).cov(Xl) / vx
    se = np.sqrt(((dX.rolling(252, min_periods=200).var() - bb ** 2 * vx) / (252 * vx)).clip(lower=1e-12))
    tdf = bb / se
    corr = r[a].rolling(252, min_periods=200).corr(r[b])
    ok = (corr > .3) & beta.notna()
    if filtro == "coint":
        ok &= tdf < -2.0
    if mk == "KR":                                                          # proibição de venda a descoberto na Coreia
        for i0, i1 in KR_BAN:
            ok &= ~((z.index >= i0) & (z.index < i1))
    sem = fim_sem(z.index)
    zs = z.where(sem).ffill()                                              # decisão só no fechamento de sexta
    oks = ok.where(sem).ffill().fillna(False).astype(bool)
    s = pd.Series(_estado(zs.values, oks.values, z_in), index=z.index)
    vol = (e.rolling(63, min_periods=40).std() * np.sqrt(252)).where(sem).ffill()
    w = (s * (alvo / vol).clip(upper=3)).where(s != 0, 0).fillna(0)
    W = pd.DataFrame({a: w, b: -w * beta.where(sem).ffill().fillna(1)})
    cus, alu, tc, tv = MERC[mk]
    C, We = contrib(W, r[[a, b]], cus + (tc + tv) / 2, alu, lag, cm)
    rf = rf_dia(C.index, RF_MERC.get(mk, "XM"))
    C[a] -= (We[a].shift(1).fillna(0) + We[b].shift(1).fillna(0)) * rf  # caixa: comprado financiado, vendido aplica
    pc = C.sum(axis=1).rename(nome)
    T = negocios(pd.DataFrame({nome: np.sign(We[a])}), pc.to_frame(), extra=pd.DataFrame({nome: z.shift(1 + lag)}))
    T["mercado"] = mk
    return pc, T


def pares(jan=126, z_in=2.0, filtro="coint", regiao="todas", alvo=.10, custo_mult=1, lag=0, detalhe=False):
    viz = {"todas": None, "eua": {"US"}, "europa": {"UK", "EU", "FR", "ES", "IT", "DE", "CH"}, "asia": {"JP", "TW", "KR", "HK", "AU", "IN"}}[regiao]
    nomes = [k for k, v in PARES.items() if viz is None or v[2] in viz]
    al = alvo / np.sqrt(len(nomes) * .4)                                     # ~40% dos pares ativos em média
    res = [x for x in (_par(k, jan, z_in, filtro, al, lag, custo_mult) for k in nomes) if x is not None]
    C = pd.concat([x[0] for x in res], axis=1).fillna(0)
    ex = brl(C.sum(axis=1))
    if not detalhe:
        return ex
    return ex, C, pd.concat([x[1] for x in res], ignore_index=True)

# =============================================================== IM2 REVERSÃO SEMANAL DE LARGE CAPS (neutra por mercado/país)
UNIV = {"us": US100, "jp": JP60, "eu": EU60}
CUSTO_REG = {"us": (.0003, .003), "jp": (.0005, .006), "eu": (.0005, .006)}
TAXA_EU = {".PA": .003, ".MI": .001, ".MC": .002}                          # imposto sobre compra (FTT) — só na compra


def _vix_alto(idx, q=.5):
    v = IDX["^VIX"].dropna()
    a = (v > v.rolling(252, min_periods=126).quantile(q))
    return a.reindex(pd.DatetimeIndex(idx).union(a.index)).ffill().reindex(idx).fillna(False).values


def _reversao(reg, q, vix, alvo, lag, cm, L=5):
    tks = [t for t in UNIV[reg] if t in PX]
    p = PX[tks]
    cal = p[p.notna().sum(axis=1) >= len(tks) * .6].index                  # dias de pregão do mercado
    p = p.reindex(cal)
    r = limpa(p.pct_change(fill_method=None), .25)
    r5 = np.log(p.ffill(limit=3)).diff(L)
    if reg == "eu":                                                         # neutro por país (o fator dominante na Europa)
        pais = pd.Series({t: t.split(".")[-1] for t in tks})
        x = r5.copy()
        for c in pais.unique():
            cc = pais.index[pais == c]
            x[cc] = r5[cc].sub(r5[cc].mean(axis=1), axis=0) if len(cc) > 2 else r5[cc].sub(r5.mean(axis=1), axis=0)
    else:
        x = r5.sub(r5.mean(axis=1), axis=0)
    rk = x.rank(axis=1, pct=True)
    n_ok = x.notna().sum(axis=1)
    W = ((rk <= q).astype(float) - (rk > 1 - q).astype(float)).where(n_ok >= 20)
    W = W.div(W.abs().sum(axis=1).replace(0, np.nan), axis=0) * 2           # 100% comprado + 100% vendido
    sem = fim_sem(cal) if L <= 5 else fim_mes(cal)
    if vix:
        W = W.mul(_vix_alto(cal), axis=0)
    W = W.where(pd.Series(sem, index=cal), np.nan).ffill().fillna(0)
    W = vol_alvo(W, r.fillna(0), alvo, teto=2.0)
    W = W.where(pd.Series(sem, index=cal), np.nan).ffill().fillna(0)
    cus, alu = CUSTO_REG[reg]
    custo = pd.Series(cus, index=tks) + pd.Series({t: TAXA_EU.get("." + t.split(".")[-1], 0) / 2 for t in tks})
    C, We = contrib(W, r, custo, alu, lag, cm)
    return C, We, r


def reversao(regiao="todas", L=21, q=.2, vix=0, alvo=.08, custo_mult=1, lag=0, detalhe=False):
    regs = ["us", "jp", "eu"] if regiao == "todas" else regiao.split("+")
    out, Cs, Ts = [], [], []
    for g in regs:
        C, We, r = _reversao(g, q, vix, alvo / np.sqrt(len(regs)), lag, custo_mult, L)
        out.append(C.sum(axis=1))
        if detalhe:
            Cs.append(C.add_prefix(g + ":"))
            T = negocios(np.sign(We), C, r)
            T["mercado"] = g
            Ts.append(T)
    ex = sum(brl(s) for s in out)
    if not detalhe:
        return ex
    return ex, pd.concat(Cs, axis=1).fillna(0), pd.concat(Ts, ignore_index=True)

# =============================================================== IM3 VENDE AÇÕES SENSÍVEIS A CRÉDITO QUANDO O HY ABRE
def _fator_credito(idx):
    """Retorno diário do fator crédito: HYG - beta*IEF (beta de 126 dias, só passado). Positivo = spread fechando.
    (O OAS do ICE no FRED só tem os últimos 3 anos — ver caderno.)"""
    r = ETF[["HYG", "IEF"]].reindex(idx).pct_change(fill_method=None)
    b = (r.HYG.rolling(126, min_periods=60).cov(r.IEF) / r.IEF.rolling(126, min_periods=60).var()).clip(0, 1).shift(1)
    return (r.HYG - b * r.IEF)


def credito_acoes(thr=.02, n=15, saida="aperta", lado="vende", custo_mult=1, lag=0, alvo=.10, detalhe=False):
    tks = [t for t in US100 if t in PX]
    cal = DIAS_US[DIAS_US >= "2005-01-01"]
    p = PX[tks].reindex(cal)
    r = limpa(p.pct_change(fill_method=None), .25)
    m = ETF["SPY"].reindex(cal).pct_change(fill_method=None)
    do = _fator_credito(cal)
    S = do.fillna(0).cumsum()
    # sensibilidade ao crédito ortogonal ao mercado: r_i = a + bm*SPY + bc*dOAS (janela de 1 ano, só passado)
    J, mp = 252, 180
    vm, vo, cmo = m.rolling(J, mp).var(), do.rolling(J, mp).var(), m.rolling(J, mp).cov(do)
    cim = r.rolling(J, mp).cov(m)
    cio = r.apply(lambda s: s.rolling(J, mp).cov(do))
    det = vm * vo - cmo ** 2
    bc = (cio.mul(vm, axis=0) - cim.mul(cmo, axis=0)).div(det, axis=0)       # mais positivo = cai mais quando o crédito abre
    bm = (cim.mul(vo, axis=0) - cio.mul(cmo, axis=0)).div(det, axis=0)
    rk = bc.rank(axis=1)
    k = bc.notna().sum(axis=1)
    compra = (rk <= n) & (k >= 40).values[:, None]
    venda = rk.gt(k - n, axis=0) & (k >= 40).values[:, None]
    # gatilho: o fator crédito caiu > thr do topo de 21 dias e está abaixo da média de 63 dias; sai quando volta a subir (ou após 63 dias)
    abre = (S - S.rolling(21).max() < -thr) & (S < S.rolling(63).mean())
    on = np.zeros(len(cal))
    st, t = 0, 0
    fecha = (S > S.rolling(10).mean()).values if saida == "aperta" else np.zeros(len(cal), bool)
    for i in range(len(cal)):
        if st:
            t += 1
            if (t >= 21 and fecha[i]) or t >= 63:
                st, t = 0, 0
        if not st and abre.iloc[i]:
            st, t = 1, 0
        on[i] = st
    on = pd.Series(on, index=cal)
    Wc = (compra.astype(float) / n - venda.astype(float) / n) * (1 if lado == "vende" else -1)   # candidata (todo dia)
    b_tot = cim.div(vm, axis=0)                                               # beta TOTAL ao S&P (o parcial bm deixava o livro comprado em mercado)
    Wc["SPY"] = -(Wc * b_tot.ffill()).sum(axis=1)                            # neutraliza beta com SPY
    R = pd.concat([r, m.rename("SPY")], axis=1)
    vol = (Wc.shift(1) * R.fillna(0)).sum(axis=1).rolling(63, min_periods=20).std() * np.sqrt(252)
    Wc = Wc.mul((alvo / vol).clip(upper=2), axis=0)
    ent = on.diff().fillna(0) > 0
    W = Wc.where(ent).ffill().fillna(0).mul(on, axis=0)                      # carteira congelada na entrada do episódio
    alu = pd.Series(.003, index=R.columns)
    C, We = contrib(W, R, .0003, alu, lag, custo_mult)
    ex = brl(C.sum(axis=1))
    if not detalhe:
        return ex
    T = negocios(np.sign(We), C, R, extra=bc.shift(1 + lag))
    T["mercado"] = "US"
    return ex, C, T

# =============================================================== IM4 ROTAÇÃO DE PAÍSES: VALOR + MOMENTO + CARRY, L/S CONTRA O ACWI
PAISES = {  # ETF: (código BIS do REER/CPI, código BIS do juro de política, custo por perna)
    "EWJ": ("JP", "JP", .0003), "EWG": ("DE", "XM", .0003), "EWU": ("GB", "GB", .0003), "EWQ": ("FR", "XM", .0005), "EWI": ("IT", "XM", .0005),
    "EWP": ("ES", "XM", .0005), "EWL": ("CH", "CH", .0005), "EWN": ("NL", "XM", .0005), "EWD": ("SE", "SE", .0005), "EWA": ("AU", "AU", .0003),
    "EWC": ("CA", "CA", .0003), "EWZ": ("BR", "BR", .0003), "EWW": ("MX", "MX", .0003), "ECH": ("CL", "CL", .0010), "EPU": ("PE", "PE", .0015),
    "EWY": ("KR", "KR", .0003), "EWT": ("TW", "US", .0003), "EWH": ("HK", "US", .0003), "MCHI": ("CN", "CN", .0003), "INDA": ("IN", "IN", .0005),
    "EIDO": ("ID", "ID", .0015), "EWM": ("MY", "US", .0015), "THD": ("TH", "TH", .0015), "EPHE": ("PH", "PH", .0020), "TUR": ("TR", "TR", .0015),
    "EZA": ("ZA", "ZA", .0005), "KSA": ("SA", "SA", .0030), "QAT": ("QA", "US", .0050), "UAE": ("AE", "US", .0050), "VNM": ("VN", "US", .0040),
    "ARGT": ("AR", "US", .0040), "GREK": ("GR", "XM", .0020), "EPOL": ("PL", "PL", .0015), "SPY": ("US", "US", .0001)}


def _mensal(df):
    return df.resample("ME").last()


def paises_valor(sinal="valor+mom", n=6, hedge="acwi", custo_mult=1, lag=0, detalhe=False):
    c = [k for k in PAISES if k in EXT]
    cal = DIAS_US[DIAS_US >= "2005-01-01"]
    P = EXT[c + ["ACWI"]].reindex(cal).ffill(limit=5)
    R = limpa(P.pct_change(fill_method=None), .25)
    pm = np.log(_mensal(P[c]))
    reer = pd.read_parquet(F_REER)
    reer.index = reer.index + pd.offsets.MonthEnd(2)                         # REER do mês m sai em meados de m+1: usa no fim de m+2
    lr = np.log(pd.DataFrame({k: reer[v[0]] for k, v in PAISES.items() if v[0] in reer}).reindex(pm.index, method="ffill"))
    f = {"reer": -(lr - lr.rolling(120, min_periods=60).mean()),             # moeda real barata contra 10 anos
         "rev5": -(pm.shift(12) - pm.shift(60)),                             # reversão de longo prazo (3-5 anos atrás, pula o último ano)
         "mom": pm.shift(1) - pm.shift(12)}                                  # momento 12-1
    i = BIS.resample("ME").last()
    f["carry"] = pd.DataFrame({k: i[v[1]] - i["US"] for k, v in PAISES.items() if v[1] in i}).reindex(pm.index)
    rk = {k: v.reindex(columns=c).rank(axis=1, pct=True) for k, v in f.items()}
    comp = {"valor": ["reer", "rev5"], "valor+mom": ["reer", "rev5", "mom"], "valor+mom+carry": ["reer", "rev5", "mom", "carry"],
            "mom": ["mom"]}[sinal]
    S = sum(rk[k].fillna(.5) for k in comp) / len(comp)
    S = S.where(pm.notna() & pm.shift(12).notna())
    k = S.rank(axis=1, ascending=False)
    Wm = (k <= n).astype(float).div(n).where(S.notna().sum(axis=1) >= 15, 0)
    vol = R[c].rolling(63, min_periods=40).std().resample("ME").last()
    # risco: cada país com peso inverso à vol relativa ao ACWI (limita EM de 35% de vol), soma = 1; vende ACWI pelo beta
    va = R["ACWI"].rolling(63, min_periods=40).std().resample("ME").last()
    Wm = Wm.mul((1 / vol).div(1 / va, axis=0).clip(upper=1.5).reindex(columns=c).fillna(0))
    Wm = Wm.div(Wm.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    Rx = R[c].sub(R["ACWI"], axis=0)                                          # cada país contra o ACWI (vendido)
    if hedge == "piores":                                                     # vende os n piores em vez do ACWI
        Wv = (k > S.notna().sum(axis=1).values[:, None] - n).astype(float).where(S.notna(), 0)
        Wv = Wv.mul((1 / vol).div(1 / va, axis=0).clip(upper=1.5).reindex(columns=c).fillna(0))
        Wm = Wm - Wv.div(Wv.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
        Rx = R[c]
    W = Wm.reindex(cal, method="ffill").fillna(0)
    W = W.where(pd.Series(fim_mes(cal), index=cal)).ffill().fillna(0)
    custo = pd.Series({k: PAISES[k][2] + .0003 * (hedge == "acwi") for k in c})   # país (+ ACWI)
    C, We = contrib(W, Rx, custo, .003, lag, custo_mult)
    ex = brl(C.sum(axis=1))
    if not detalhe:
        return ex
    T = negocios(np.sign(We), C, Rx, extra=S.reindex(cal, method="ffill").shift(1 + lag))
    return ex, C, T

# =============================================================== IM5 MOEDAS: VALOR (PPP) + JURO REAL, COM STOP
MOEDAS = {  # yahoo: (país BIS, sinal p/ virar USD por moeda local, custo por perna, NDF)
    "MXN=X": ("MX", -1, .0008, 0), "ZAR=X": ("ZA", -1, .0010, 0), "INR=X": ("IN", -1, .0012, 1), "IDR=X": ("ID", -1, .0015, 1),
    "KRW=X": ("KR", -1, .0010, 1), "TRY=X": ("TR", -1, .0025, 0), "CLP=X": ("CL", -1, .0012, 1), "COP=X": ("CO", -1, .0015, 1),
    "PLN=X": ("PL", -1, .0008, 0), "HUF=X": ("HU", -1, .0008, 0), "CZK=X": ("CZ", -1, .0008, 0), "JPY=X": ("JP", -1, .0002, 0),
    "AUDUSD=X": ("AU", 1, .0002, 0)}


def _cpi():
    c = pd.read_parquet(F_CPI)
    c.index = c.index + pd.offsets.MonthEnd(1)                               # CPI do mês m publicado ao longo de m+1
    return c


def limpa_fx3(r, lim=.04, janela=3):
    """Erros de cotação do Yahoo que se desfazem em até `janela` dias (COP jul/2013 e jun/2015 = 100x; IDR dez/2013 alternando):
    zera o salto e a volta. base.limpa_fx só olha o dia seguinte."""
    l = np.log1p(r.clip(lower=-.999)).fillna(0)
    out = r.copy()
    for k in range(1, janela + 1):
        volta = l.rolling(k).sum().shift(-k)                                  # soma dos k dias seguintes
        vira = (l.abs() > np.log1p(lim)) & ((l + volta).abs() < .3 * l.abs())
        for j in range(k + 1):
            out = out.where(~vira.shift(j, fill_value=False), 0.0)
    return out.where(r.notna())


def _fx_base(cal):
    v = pd.DataFrame({k: FXY[k] ** s for k, (cc, s, cu, nd) in MOEDAS.items()}).reindex(cal).ffill(limit=5)   # USD por moeda local
    spot = limpa_fx3(v.pct_change(fill_method=None))
    i = BIS.reindex(pd.DatetimeIndex(cal).union(BIS.index)).ffill().reindex(cal)
    dif = pd.DataFrame({k: (i[cc] - i["US"]) / 100 * (.7 if nd else 1) for k, (cc, s, cu, nd) in MOEDAS.items()})
    return v, spot, dif, i


def fx_valor(sinal="ppp+juro_real", stop=.05, alvo=.08, custo_mult=1, lag=0, detalhe=False, teto=.25):
    cal = DIAS_US[DIAS_US >= "2005-01-01"]
    v, spot, dif, i = _fx_base(cal)
    cpi = _cpi()
    vm = np.log(_mensal(v))
    cps = {k: cc for k, (cc, s, cu, nd) in MOEDAS.items()}
    lcpi = np.log(pd.DataFrame({k: cpi[cc] for k, cc in cps.items()}).reindex(vm.index, method="ffill"))
    lus = np.log(cpi["US"].reindex(vm.index, method="ffill"))
    q = vm + lcpi.sub(lus, axis=0)                                           # câmbio real bilateral (alto = moeda cara)
    f = {"ppp": -(q - q.rolling(120, min_periods=60).mean()) / q.diff(12).rolling(120, min_periods=60).std()}
    infl = lcpi.diff(12) * 100
    infl_us = lus.diff(12) * 100
    im = i.resample("ME").last()
    rr = pd.DataFrame({k: im[cc] for k, cc in cps.items()}).reindex(vm.index) - infl
    rr_us = im["US"].reindex(vm.index) - infl_us
    f["juro_real"] = rr.sub(rr_us, axis=0)
    comp = {"ppp": ["ppp"], "juro_real": ["juro_real"], "ppp+juro_real": ["ppp", "juro_real"]}[sinal]
    S = sum(f[k].rank(axis=1, pct=True).sub(.5).where(f[k].notna()).fillna(0) for k in comp) / len(comp)
    S = S.where(S.abs() > 0)
    Wm = S.sub(S.mean(axis=1), axis=0)                                       # neutro ao dólar
    volm = spot.rolling(63, min_periods=40).std().resample("ME").last()
    Wm = (Wm / volm).div((Wm / volm).abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0) * 2
    W = Wm.reindex(cal, method="ffill").fillna(0)
    W = W.where(pd.Series(fim_mes(cal), index=cal)).ffill().fillna(0)
    R = (spot + dif.shift(1) / 252).reindex(columns=W.columns)
    W = vol_alvo(W, R.fillna(0), alvo).where(pd.Series(fim_mes(cal), index=cal)).ffill().fillna(0).clip(-teto, teto)
    # stop por moeda: perda de `stop` desde a entrada (sinal na moeda) -> zera até o fim do mês seguinte
    if stop:
        Wv, Rv = W.values.copy(), R.fillna(0).values
        fm = fim_mes(cal)
        acum = np.zeros(Wv.shape[1])
        blq = np.zeros(Wv.shape[1])
        ult = np.zeros(Wv.shape[1])
        for t in range(1, len(cal)):
            nova = np.sign(Wv[t]) != np.sign(ult)
            acum = np.where(nova, 0, acum + np.sign(ult) * Rv[t])           # P&L do sinal desde a entrada (decisão com o fechamento de t)
            bate = acum < -stop
            blq = np.where(bate, 2, blq)
            if fm[t]:
                blq = np.maximum(blq - 1, 0)
            Wv[t] = np.where(blq > 0, 0, Wv[t])
            ult = Wv[t]
            acum = np.where(blq > 0, 0, acum)
        W = pd.DataFrame(Wv, index=cal, columns=W.columns)
    custo = pd.Series({k: MOEDAS[k][2] for k in W.columns})
    C, We = contrib(W, R, custo, 0, lag, custo_mult)
    ex = brl(C.sum(axis=1))
    if not detalhe:
        return ex
    T = negocios(np.sign(We), C, R, extra=S.reindex(cal, method="ffill").shift(1 + lag))
    return ex, C, T

# =============================================================== IM6 CTA GLOBAL COM RISCO DE MESA / TENDÊNCIA DE CRISES
CTA_ETF = ["SPY", "IWM", "QQQ", "EFA", "EEM", "EWJ", "EWG", "EWU", "FXI", "EWZ", "EWY", "EWT", "INDA", "EWA", "EWC", "TLT", "IEF", "TIP",
           "LQD", "HYG", "EMB", "GLD", "SLV", "USO", "UNG", "DBA", "CPER", "DBB"]
CTA_FX = {"EURUSD=X": ("XM", 1), "GBPUSD=X": ("GB", 1), "AUDUSD=X": ("AU", 1), "JPY=X": ("JP", -1), "CAD=X": ("CA", -1), "CHF=X": ("CH", -1),
          "MXN=X": ("MX", -1), "ZAR=X": ("ZA", -1), "KRW=X": ("KR", -1)}


def _cta_R(cal):
    P = ETF[CTA_ETF].reindex(cal).ffill(limit=5)
    R = limpa(P.pct_change(fill_method=None), .25).sub(tb_dia(cal), axis=0)
    v = pd.DataFrame({k: FXY[k] ** s for k, (c, s) in CTA_FX.items()}).reindex(cal).ffill(limit=5)
    i = BIS.reindex(pd.DatetimeIndex(cal).union(BIS.index)).ffill().reindex(cal)
    Rf = limpa_fx3(v.pct_change(fill_method=None)) + pd.DataFrame({k: (i[c] - i["US"]) / 100 / 252 for k, (c, s) in CTA_FX.items()}).shift(1)
    lp = np.log(pd.concat([P, v], axis=1))
    return pd.concat([R, Rf], axis=1), lp


def _sinal_tend(lp, R, jan):
    vd = R.rolling(63, min_periods=40).std()
    return sum((lp.diff(L) / (vd * np.sqrt(L))).clip(-2, 2) for L in jan) / (2 * len(jan))   # em [-1, 1]


def _crise(cal, thr=.02):
    """Crédito abrindo: fator HYG-IEF caiu > thr do topo de 21 dias e está abaixo da média de 63 dias."""
    S = _fator_credito(cal).fillna(0).cumsum()
    return ((S - S.rolling(21).max() < -thr) & (S < S.rolling(63).mean())).astype(float)


def _crise_W(cal, R, lp, thr, tlt):
    eq = ["SPY", "EFA", "EEM"]
    lpe = lp[eq]
    abaixo = (lpe < lpe.rolling(200, min_periods=150).mean()).astype(float)
    vol = R[eq].rolling(63, min_periods=40).std() * np.sqrt(252)
    on = _crise(cal, thr)
    W = -(abaixo * (.10 / vol)).clip(upper=1).mul(on, axis=0) / np.sqrt(3)    # ~10% de vol no livro vendido
    if tlt:                                                                  # e compra Treasury longo (fuga para qualidade)
        W["TLT"] = (.05 / (R["TLT"].rolling(63, min_periods=40).std() * np.sqrt(252))).clip(upper=1) * on
    return W.where(pd.Series(fim_sem(cal), index=cal) | (on.diff() != 0)).ffill().fillna(0)


def tend_crises(thr=.02, tlt=0, custo_mult=1, lag=0, detalhe=False):
    """Só vendido em ações (SPY/EFA/EEM abaixo da média de 200 dias) enquanto o crédito está abrindo; senão, caixa."""
    cal = DIAS_US[DIAS_US >= "2005-01-01"]
    R, lp = _cta_R(cal)
    W = _crise_W(cal, R, lp, thr, tlt)
    R = R[W.columns]
    C, We = contrib(W, R, .0003, .003, lag, custo_mult)
    ex = brl(C.sum(axis=1))
    if not detalhe:
        return ex
    return ex, C, negocios(np.sign(We), C, R)


def cta_global(modo="cta+stop", janelas="lento", alvo=.10, dd=.08, custo_mult=1, lag=0, detalhe=False):
    cal = DIAS_US[DIAS_US >= "2005-01-01"]
    R, lp = _cta_R(cal)
    jan = {"rapido": (21, 63, 126), "lento": (63, 126, 252)}[janelas]
    sem = pd.Series(fim_sem(cal), index=cal)
    W = pd.DataFrame(0.0, index=cal, columns=R.columns)
    if "cta" in modo:
        s = _sinal_tend(lp, R, jan)
        vol = R.rolling(63, min_periods=40).std() * np.sqrt(252)
        W = (s * (.10 / vol)).clip(-.5, .5).fillna(0)                        # vol-alvo por ativo (10%), teto 50% do PL por ativo
        W = W / np.sqrt(R.shape[1])
    W = W.where(sem).ffill().fillna(0)
    W = vol_alvo(W, R.fillna(0), alvo, teto=3).where(sem).ffill().fillna(0)
    if "crise" in modo:                                                       # camada extra: vende ações quando o crédito abre
        W = W.add(_crise_W(cal, R, lp, .02, 0), fill_value=0)
    if "stop" in modo:                                                        # stop de crise: drawdown > dd em 63 dias corta pela metade
        p = (W.shift(2) * R.fillna(0)).sum(axis=1)                            # P&L que o livro cheio teria (até t)
        eqc = p.cumsum()
        dd_ = eqc - eqc.rolling(63, min_periods=1).max()
        corta = pd.Series(np.where(dd_ < -dd, .5, np.nan), index=cal)
        corta[dd_ > -dd / 2] = 1.0
        W = W.mul(corta.ffill().fillna(1), axis=0)
    custo = pd.Series(.0003, index=R.columns)
    custo[[c for c in R.columns if c.endswith("=X")]] = .0002
    custo[["MXN=X", "ZAR=X", "KRW=X"]] = .0008
    for c in ("UNG", "CPER", "DBB", "DBA", "INDA", "EWT", "EWY"):
        custo[c] = .0005
    C, We = contrib(W, R, custo, .003, lag, custo_mult)
    alav = (We.shift(1).abs().sum(axis=1) - 1).clip(lower=0) * .005 / 252   # alavancagem acima de 1x paga T-bill + 0,5%
    ex = brl(C.sum(axis=1) - alav)
    if not detalhe:
        return ex
    return ex, C, negocios(np.sign(We), C, R)

# =============================================================== IM7 CALENDÁRIO GLOBAL
RAMADA = ["2005-10-04", "2006-09-23", "2007-09-13", "2008-09-01", "2009-08-22", "2010-08-11", "2011-08-01", "2012-07-20", "2013-07-09",
          "2014-06-28", "2015-06-18", "2016-06-06", "2017-05-27", "2018-05-16", "2019-05-06", "2020-04-24", "2021-04-13", "2022-04-02",
          "2023-03-23", "2024-03-11", "2025-03-01", "2026-02-18"]
ANO_LUNAR = ["2005-02-09", "2006-01-29", "2007-02-18", "2008-02-07", "2009-01-26", "2010-02-14", "2011-02-03", "2012-01-23", "2013-02-10",
             "2014-01-31", "2015-02-19", "2016-02-08", "2017-01-28", "2018-02-16", "2019-02-05", "2020-01-25", "2021-02-12", "2022-02-01",
             "2023-01-22", "2024-02-10", "2025-01-29", "2026-02-17"]
FECHA_IMPREVISTO = ["2007-01-02", "2012-10-29", "2012-10-30", "2018-12-05", "2025-01-09"]   # luto/furacão: não eram conhecidos antes


def _serie_local(tk, cc):
    """Índice local (preço) com hedge cambial = retorno local - juro local; no calendário do próprio mercado."""
    p = IX[tk].dropna()
    p = p[p.index >= "2005-01-01"]
    r = limpa(p.pct_change(fill_method=None), .15)
    return (r - rf_dia(r.index, cc)).dropna()


def _vespera(idx, extras_fora=()):
    """Último pregão antes de um feriado (dia útil sem pregão) — calendário conhecido de antemão."""
    idx = pd.DatetimeIndex(idx)
    bd = pd.bdate_range(idx[0], idx[-1])
    fer = bd.difference(idx).difference(pd.DatetimeIndex(extras_fora))
    pos = idx.searchsorted(fer) - 1
    v = pd.Series(0.0, index=idx)
    v.iloc[np.unique(pos[pos >= 0])] = 1.0
    return v


def _tom(idx, a=-1, b=3):
    idx = pd.DatetimeIndex(idx)
    m = pd.Series(idx.to_period("M"), index=idx)
    k_ini = m.groupby(m).cumcount() + 1                                     # 1 = 1º pregão do mês
    k_fim = m.groupby(m).cumcount(ascending=False) + 1                      # 1 = último pregão do mês
    return (((k_fim <= -a) & (a < 0)) | (k_ini <= b)).astype(float)


def _janela(idx, datas, antes=0, dur=0, depois=0):
    """1 nos `antes` pregões anteriores a cada data (exclusive) e/ou durante [data, data+dur dias corridos]."""
    idx = pd.DatetimeIndex(idx)
    h = pd.Series(0.0, index=idx)
    for d in pd.to_datetime(datas):
        k = idx.searchsorted(d)
        if antes:
            h.iloc[max(k - antes, 0):k] = 1.0
        if dur:
            h[(idx >= d) & (idx <= d + pd.Timedelta(days=dur))] = 1.0
    return h


def _manga(r, H, alvo, lag, cm, custo, nome):
    """Uma 'manga' do calendário: segura o ativo nos dias H (H[d]=1 => ganha o retorno de d). Datas conhecidas antes:
    a ordem é dada 2 pregões antes (W_t = H_{t+2}) para executar no fechamento da véspera."""
    vol = (r.rolling(126, min_periods=60).std() * np.sqrt(252)).shift(1)
    W = (H.shift(-2).fillna(0) * (alvo / vol).clip(upper=1.5)).fillna(0).to_frame(nome)
    C, We = contrib(W, r.to_frame(nome), custo, 0, lag, cm)
    return C, We


def calendario(comp="tudo", alvo=.08, custo_mult=1, lag=0, detalhe=False):
    a, b = (-3, 3) if comp == "tom-3+3" else (-1, 3)
    mangas = []                                                                # (nome, retorno, H, custo, em_reais)
    cal = DIAS_US[DIAS_US >= "2005-01-01"]
    spy = (ETF["SPY"].reindex(cal).pct_change(fill_method=None) - tb_dia(cal)).dropna()
    n225, sx5 = _serie_local("^N225", "JP"), _serie_local("^GDAXI", "XM")
    bova = (R_IBOV - CDI)[DIAS >= "2008-01-01"]
    if comp in ("tom", "tom-3+3", "tudo"):
        mangas += [("TOM Japão", n225, _tom(n225.index, a, b), .0002, 0), ("TOM Alemanha", sx5, _tom(sx5.index, a, b), .0002, 0),
                   ("TOM Brasil", bova, _tom(bova.index, a, b), .0003, 1)]
    if comp in ("feriados", "tudo"):
        jp = _vespera(n225.index)
        gw = _janela(n225.index, [f"{y}-04-29" for y in range(2005, 2027)], antes=3)
        mangas += [("véspera feriado EUA", spy, _vespera(spy.index, FECHA_IMPREVISTO), .0001, 0),
                   ("véspera feriado/Golden Week Japão", n225, ((jp + gw) > 0).astype(float), .0002, 0)]
        for tk, cc in (("^HSI", "US"), ("^TWII", "US"), ("^KS11", "KR")):
            s = _serie_local(tk, cc)
            mangas.append((f"Ano-Novo Lunar {tk}", s, _janela(s.index, ANO_LUNAR, antes=5), .0003, 0))
    if comp in ("religioso", "tudo"):
        for tk in ("KSA", "UAE", "QAT", "TUR", "EIDO", "EWM"):
            p = EXT[tk].reindex(cal).dropna()
            s = (limpa(p.pct_change(fill_method=None), .2) - tb_dia(p.index)).dropna()
            mangas.append((f"Ramadã {tk}", s, _janela(s.index, RAMADA, dur=29), PAISES[tk][2] * 2, 0))
    if comp in ("halloween", "tudo"):
        for nome, s, br in (("Halloween S&P", spy, 0), ("Halloween Japão", n225, 0), ("Halloween Alemanha", sx5, 0), ("Halloween Brasil", bova, 1)):
            inv = s.index.month.isin([11, 12, 1, 2, 3, 4])                    # comprado no inverno, vendido no verão (testa a sazonalidade, não o prêmio)
            mangas.append((nome, s, pd.Series(np.where(inv, 1.0, -1.0), index=s.index), .0002, br))
    al = alvo * 2 / np.sqrt(len(mangas)) if comp != "halloween" else alvo / 2.5  # mangas eventuais: ~vol-alvo quando posicionadas
    ex = pd.Series(0.0, index=DIAS)
    Cs, Ts = [], []
    for nome, r, H, cu, br in mangas:
        C, We = _manga(r, H, al, lag, custo_mult, cu, nome)
        ex = ex + (C[nome].reindex(DIAS).fillna(0) if br else brl(C[nome]))
        if detalhe:
            Cs.append(C)
            Ts.append(negocios(np.sign(We), C, r.to_frame(nome)))
    if not detalhe:
        return ex
    return ex, pd.concat(Cs, axis=1).fillna(0), pd.concat(Ts, ignore_index=True)

# =============================================================== IM8 ELEIÇÕES: COMPRA DEPOIS DO PÂNICO, COM HEDGE CAMBIAL
# TODAS as eleições nacionais/referendos relevantes 2006-2026 dos países com índice/ETF (não só as que tiveram pânico): a regra decide.
ELEICOES = {
    "BR": ["2006-10-01", "2006-10-29", "2010-10-03", "2010-10-31", "2014-10-05", "2014-10-26", "2018-10-07", "2018-10-28", "2022-10-02",
           "2022-10-30", "2026-10-04"],
    "MX": ["2006-07-02", "2012-07-01", "2018-07-01", "2021-06-06", "2024-06-02"],
    "AR": ["2011-08-14", "2011-10-23", "2013-08-11", "2013-10-27", "2015-08-09", "2015-10-25", "2015-11-22", "2017-08-13", "2017-10-22",
           "2019-08-11", "2019-10-27", "2021-09-12", "2021-11-14", "2023-08-13", "2023-10-22", "2023-11-19", "2025-09-07", "2025-10-26"],
    "TR": ["2007-07-22", "2011-06-12", "2014-08-10", "2015-06-07", "2015-11-01", "2017-04-16", "2018-06-24", "2019-03-31", "2019-06-23",
           "2023-05-14", "2023-05-28", "2024-03-31"],
    "IN": ["2009-05-16", "2014-05-16", "2019-05-23", "2024-06-04"],
    "ZA": ["2009-04-22", "2014-05-07", "2019-05-08", "2024-05-29"],
    "ID": ["2009-07-08", "2014-07-09", "2019-04-17", "2024-02-14"],
    "KR": ["2007-12-19", "2012-12-19", "2017-05-09", "2022-03-09", "2024-12-03", "2025-06-03"],
    "TW": ["2008-03-22", "2012-01-14", "2016-01-16", "2020-01-11", "2024-01-13"],
    "MY": ["2008-03-08", "2013-05-05", "2018-05-09", "2022-11-19"],
    "TH": ["2011-07-03", "2014-05-22", "2019-03-24", "2023-05-14"],
    "PH": ["2010-05-10", "2016-05-09", "2022-05-09"],
    "CL": ["2009-12-13", "2010-01-17", "2013-12-15", "2017-12-17", "2019-10-18", "2021-11-21", "2021-12-19", "2022-09-04", "2025-12-14"],
    "PE": ["2011-06-05", "2016-06-05", "2021-06-06"],
    "PL": ["2015-10-25", "2019-10-13", "2023-10-15"],
    "GB": ["2010-05-06", "2015-05-07", "2016-06-23", "2017-06-08", "2019-12-12", "2024-07-04"],
    "FR": ["2007-05-06", "2012-05-06", "2017-04-23", "2017-05-07", "2022-04-24", "2024-06-09", "2024-06-30"],
    "IT": ["2008-04-13", "2013-02-24", "2016-12-04", "2018-03-04", "2018-05-28", "2022-09-25"],
    "ES": ["2008-03-09", "2011-11-20", "2015-12-20", "2016-06-26", "2017-10-01", "2019-04-28", "2019-11-10", "2023-07-23"],
    "GR": ["2009-10-04", "2012-05-06", "2012-06-17", "2015-01-25", "2015-07-05", "2015-09-20", "2019-07-07", "2023-06-25"],
}
# índice local (hedge = retorno local - juro local) e ETF em dólar (sem hedge)
# Turquia e Argentina só via ETF: o hedge pelo juro de política subestima o custo do forward (TRY 2023: política 8,5%, offshore 30%+)
VEIC = {"BR": ("^BVSP", "BR", "EWZ"), "MX": ("^MXX", "MX", "EWW"), "AR": (None, None, "ARGT"), "TR": (None, None, "TUR"),
        "IN": ("^BSESN", "IN", "INDA"), "ZA": (None, None, "EZA"), "ID": ("^JKSE", "ID", "EIDO"), "KR": ("^KS11", "KR", "EWY"),
        "TW": ("^TWII", "US", "EWT"), "MY": ("^KLSE", "US", "EWM"), "TH": (None, None, "THD"), "PH": (None, None, "EPHE"),
        "CL": (None, None, "ECH"), "PE": (None, None, "EPU"), "PL": (None, None, "EPOL"), "GB": ("^FTSE", "GB", "EWU"),
        "FR": ("^FCHI", "XM", "EWQ"), "IT": ("FTSEMIB.MI", "XM", "EWI"), "ES": ("^IBEX", "XM", "EWP"), "GR": ("GD.AT", "XM", "GREK")}


def _ret_pais(pais, veiculo):
    tk, cc, etf = VEIC[pais]
    if veiculo == "hedge" and tk is not None and tk in IX:
        return _serie_local(tk, cc), .0005                                     # futuro de índice / swap: ~5 bps
    p = EXT[etf].dropna()
    r = limpa(p.pct_change(fill_method=None), .3)
    return (r - tb_dia(r.index)).dropna(), PAISES.get(etf, (0, 0, .001))[2]


def eleicoes(queda=.05, dias=63, veiculo="hedge", espera=1, custo_mult=1, lag=0, detalhe=False):
    """Pânico = queda > `queda` do fechamento anterior à eleição até `espera` pregões depois do 1º pregão pós-eleição.
    Compra (ordem no fechamento desse dia, execução no seguinte) e segura `dias` pregões. Tamanho 10% de vol por evento."""
    Cs, Ts, ex = [], [], pd.Series(0.0, index=DIAS)
    for pais, datas in ELEICOES.items():
        r, cu = _ret_pais(pais, veiculo)
        if r.empty:
            continue
        idx = r.index
        lp = np.log1p(r).cumsum()                                               # índice de excesso (o preço também serviria)
        vol = (r.rolling(126, min_periods=60).std() * np.sqrt(252))
        W = pd.Series(0.0, index=idx)
        sinal = pd.Series(np.nan, index=idx)
        for d in pd.to_datetime(datas):
            k1 = idx.searchsorted(d)                                            # 1º pregão no dia ou depois da eleição
            if k1 == 0 or k1 + espera >= len(idx):
                continue
            k0, kd = k1 - 1, k1 + espera - 1                                    # véspera; dia da decisão
            mov = np.expm1(lp.iloc[kd] - lp.iloc[k0])
            if mov < -queda:
                w = min(.10 / vol.iloc[kd], 1.0) if np.isfinite(vol.iloc[kd]) else .5
                W.iloc[kd:kd + dias] = np.maximum(W.iloc[kd:kd + dias], w)
                sinal.iloc[kd] = mov
        if (W == 0).all():
            continue
        C, We = contrib(W.to_frame(pais), r.to_frame(pais), cu, 0, lag, custo_mult)
        ex = ex + brl(C[pais])
        if detalhe:
            Cs.append(C)
            Ts.append(negocios(np.sign(We), C, r.to_frame(pais), extra=sinal.ffill(limit=dias).shift(1 + lag).to_frame(pais)))
    if not detalhe:
        return ex
    return ex, pd.concat(Cs, axis=1).fillna(0), pd.concat(Ts, ignore_index=True)

# =============================================================== FUNDOS
_CDI = "CDI"
FUNDOS = [
    Fundo("IM1 Pares intra-setor globais (KO/PEP, V/MA, bancos, Toyota/Honda, TSMC/UMC...)", "Valor relativo", _CDI,
          "Duas empresas com o mesmo negócio (mesmos clientes, custos, regulação) não divergem por muito tempo sem notícia: quando o "
          "resíduo do par (beta de 1 ano) se afasta 1,5-2 desvios, compro a barata e vendo a cara; se o desvio passa de 3,5 é quebra "
          "estrutural (M&A, fraude, troca de modelo de negócio) e saio e bloqueio o par por 3 meses",
          "46 pares em 13 mercados (EUA, Londres, zona do euro, Suíça, Japão, Coreia, Taiwan, HK, Austrália, Índia), cada par no seu "
          "calendário, decisão na sexta, risco igual por par; custos por mercado + imposto (UK 0,5% compra, FR 0,3%, TW 0,3% venda, "
          "KR 0,2%, HK 0,1%x2), aluguel 0,3-3%, proibição de venda descoberta na Coreia respeitada",
          pares, {"jan": [63, 126], "z_in": [1.5, 2.0], "filtro": ["coint", "nenhum"]}, inicio="2009-01-01"),
    Fundo("IM2 Reversão de curto prazo em large caps (EUA/Japão/Europa)", "Ações neutro", _CDI,
          "Quem fornece liquidez a quem precisa vender rápido é pago: a large cap que caiu muito contra o mercado na semana/mês "
          "(sem notícia de longo prazo) devolve parte; no Japão a reversão de 1 semana é documentada. Variante: só com VIX alto, quando "
          "a liquidez é escassa (Nagel 2012)",
          "100 large caps EUA, 60 Japão, 60 Europa (neutro por país), comprado no quintil que mais caiu, vendido no que mais subiu, "
          "dinheiro neutro, vol-alvo 8%; custos 3/5/5 bps + FTT França/Itália/Espanha, aluguel 0,3-0,6%",
          reversao, {"L": [5, 21], "vix": [0, 1], "regiao": ["jp", "todas"]}, inicio="2009-01-01"),
    Fundo("IM3 Ações sensíveis a crédito quando o HY abre (EUA)", "Ações neutro", _CDI,
          "Sem balanço gratuito com histórico, a alavancagem é medida pelo preço: as ações que mais caem quando o high yield cai "
          "(beta ao fator HYG-IEF, ortogonal ao S&P) são as alavancadas. Quando o crédito abre, vendo essas e compro as menos sensíveis "
          "(tese de mesa); variante oposta = fornecer liquidez no pânico",
          "100 large caps EUA, 15 de cada lado, beta-neutro com SPY, só durante episódios (fator crédito -1,5%/-3% do topo de 21 dias), "
          "carteira congelada na entrada, sai quando o crédito volta a subir ou em 63 dias",
          credito_acoes, {"thr": [.015, .03], "saida": ["aperta", "63d"], "lado": ["vende", "compra"]}, inicio="2009-01-01"),
    Fundo("IM4 Rotação de países: valor + momento + carry (L/S)", "Macro ações", _CDI,
          "País com moeda real barata (REER do BIS abaixo da média de 10 anos) e que caiu muito em 3-5 anos tem prêmio de risco alto; "
          "o momento de 12 meses diz quando o estrangeiro voltou; o carry paga a espera",
          "34 ETFs de país (incl. SPY, Golfo, Vietnã, Argentina, Grécia, Polônia), top 6 por ranking com peso inverso à vol, vendido no "
          "ACWI ou nos 6 piores; mensal; custos 1-50 bps por ETF + ACWI, aluguel 0,3%",
          paises_valor, {"sinal": ["valor", "valor+mom", "valor+mom+carry", "mom"], "hedge": ["acwi", "piores"]}, inicio="2010-01-01"),
    Fundo("IM5 Moedas EM/G10 por valor (PPP) e juro real, com stop", "Macro moedas", _CDI,
          "Moeda barata em termos reais (câmbio real bilateral vs 10 anos) e com juro real alto contra os EUA tende a apreciar; "
          "o stop corta quando o barato continua ficando mais barato (o erro clássico de valor em moeda: lira, iene)",
          "13 moedas (MXN, ZAR, INR, IDR, KRW, TRY, CLP, COP, PLN, HUF, CZK, JPY, AUD), CPI e juro do BIS com defasagem de publicação, "
          "neutro ao dólar, vol-alvo 8%, teto 25% por moeda, mensal; stop de 3/5% por moeda com bloqueio até o fim do mês seguinte",
          fx_valor, {"sinal": ["ppp", "juro_real", "ppp+juro_real"], "stop": [0, .03, .05]}, inicio="2009-01-01"),
    Fundo("IM6 CTA global com risco de mesa (vol por ativo, stop de crise)", "Macro tendência", _CDI,
          "Tendências de 3-12 meses persistem porque hedgers e bancos centrais ajustam devagar; versão melhorada da rodada 1 com sinal "
          "contínuo (retorno/vol), vol-alvo por ativo, stop de drawdown e camada de crise (vende ações quando o crédito abre)",
          "28 ETFs (ações EUA/países, Treasuries, crédito, commodities) + 9 moedas com carry, semanal, vol-alvo 10% por ativo e 10% no "
          "livro, teto 50% por ativo; stop: drawdown de 8% em 63 dias corta pela metade",
          cta_global, {"modo": ["cta", "cta+stop", "cta+crise", "cta+crise+stop"], "janelas": ["rapido", "lento"]}, inicio="2009-01-01"),
    Fundo("IM7 Tendência de crises (vendido em ações só quando o crédito abre)", "Macro tendência", _CDI,
          "O crédito anda antes da ação no início das crises: quando o high yield cai e S&P/EAFE/EM estão abaixo da média de 200 dias, "
          "vendo ações; fora disso fico em caixa (não paga o custo de carregar CTA o tempo todo)",
          "SPY, EFA, EEM vendidos (~10% de vol), opcionalmente TLT comprado; gatilho: fator HYG-IEF caiu 1,5/2,5/4% do topo de 21 dias",
          tend_crises, {"thr": [.015, .025, .04], "tlt": [0, 1]}, inicio="2009-01-01"),
    Fundo("IM8 Calendário global (virada de mês, feriados, Ano-Novo Lunar, Ramadã, inverno x verão)", "Macro calendário", _CDI,
          "Fluxos com data marcada que não olham preço: salários/aportes na virada do mês (Japão, Alemanha, Brasil), quem zera risco "
          "antes de feriado longo e volta depois (EUA, Golden Week, Ano-Novo Lunar), otimismo/fluxo local no Ramadã (Golfo, Turquia, "
          "Indonésia, Malásia), e Sell in May testado como L/S no tempo (comprado nov-abr, vendido mai-out)",
          "Índices locais com hedge (futuros: Nikkei, DAX, Hang Seng, Taiex, Kospi) e ETFs do Golfo (30-50 bps), BOVA11 no calendário B3; "
          "datas conhecidas de antemão: ordem 2 pregões antes",
          calendario, {"comp": ["tom", "tom-3+3", "feriados", "religioso", "halloween", "tudo"]}, inicio="2009-01-01"),
    Fundo("IM9 Eleições: compra depois do pânico, com hedge cambial", "Macro eventos", _CDI,
          "Na eleição o estrangeiro vende primeiro e pergunta depois; o pânico de 3-6% no dia seguinte costuma exagerar a mudança de "
          "política (o governo eleito modera); compro o índice com hedge de moeda e seguro 1-3 meses",
          "TODAS as eleições nacionais/referendos de 20 países 2006-2026 (a regra escolhe); índice local - juro local (futuro) ou ETF "
          "em dólar; 10% de vol por evento",
          eleicoes, {"queda": [.03, .06], "dias": [21, 63], "veiculo": ["hedge", "etf"]}, inicio="2009-01-01"),
]


def roda_tudo(so=None):
    from rodar import BENCH
    res = []
    LOG = open(D.parent / "resultado" / "ideias_i_macro_acoes_log.txt", "a", encoding="utf-8")

    def log(*a):
        print(*a, flush=True)
        LOG.write(" ".join(map(str, a)) + "\n")
        LOG.flush()
    for f in FUNDOS:
        if so and f.nome.split()[0] not in so:
            continue
        r = roda(f, CDI, BENCH[f.benchmark], log)
        if r is None:
            log(f"{f.nome}: sem resultado")
            continue
        ex, C, T = f.func(**r["params"], detalhe=True)
        r["contrib"] = C[C.index >= f.inicio]
        r["trades"] = T[T.entrada >= f.inicio].sort_values("contrib").reset_index(drop=True) if len(T) else T
        o, rb = r["oos"], r["rob"]
        log(f"{f.nome[:60]:60s} {str(r['params']):58s} IS IR {r['is_ir']:5.2f} | OOS {o['retorno a.a. %']:5.1f}% vs {o['benchmark a.a. %']:5.1f}% "
            f"IR {o['IR vs bench']:5.2f} vol {o['vol a.a. %']:4.1f} | P {rb['P(bater bench OOS) %']:3.0f}% | PBO {rb['PBO %']:3.0f}% | "
            f"x2 {rb['OOS custo x2 (pp)']:5.1f} | lag {rb['OOS execução +1 dia (pp)']:5.1f} | med var {rb['mediana OOS das variantes (pp)']:5.1f} "
            f"| %var>b {rb['% variantes > bench OOS']:3.0f}")
        res.append(r)
    for r in res:
        r["fundo"].func = None
    return res


if __name__ == "__main__":
    so = sys.argv[1:]
    res = roda_tudo(so)
    out = D.parent / "resultado" / ("ideias_i_macro_acoes.pkl" if not so else f"ideias_i_macro_acoes_{'_'.join(so)}.pkl")
    pickle.dump(res, open(out, "wb"))
    print("salvo", out)
