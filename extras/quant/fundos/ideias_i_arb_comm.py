"""
Fase 2 — frente i_arb_comm: ARBITRAGENS ESTRUTURAIS, OPÇÕES/VOL E AÇÕES x COMMODITY fora do Brasil (EUA, Europa, Ásia).
Réplica internacional de: units x componentes / ON x PN (A3, 05), venda de vol (A4, 15), base IND x BOVA e cripto (A7, A9),
mineradoras x metal / PETR4 x Brent / spreads físicos (C1, C4, C6).

Convenções:
  - tudo calculado em dólar (excesso sobre o T-bill) num calendário de dias úteis (seg-sex) com preços do último fechamento
    (ffill até 5 dias); convertido para R$ com hedge cambial por base.brl() -> excesso diário sobre o CDI no calendário B3.
  - decisão no fechamento de t (todas as bolsas do par já fecharam no dia t), execução no fechamento de t+1+lag DE CADA perna
    (Ásia primeiro, Europa depois, EUA por último) — nunca no mesmo fechamento que gerou o sinal.
  - preços Yahoo AJUSTADOS por proventos (dividendo do lado vendido é custo); pares limpos no PAR (|r_A - r_B| > 15% num dia = quebra, zera).
  - custos por perna (uma via) pela liquidez (volume financeiro mediano) + impostos de bolsa: selo UK 0,5% na compra (.L),
    stamp duty HK 0,1-0,13%, imposto de venda Coreia ~0,2%, China A 0,05-0,1% na venda, FTT França 0,3% e Itália 0,1% na compra;
    aluguel 0,5% a.a. (líquidas) a 2-3% (ilíquidas); A-share 8% a.a.; Coreia: proibição de venda a descoberto nas janelas oficiais.
Dados: dados_i_arb_comm.py (Yahoo, CBOE, STOXX, Binance) + arb_cripto_* (frente de arbitragem).
"""
import pickle
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
from base import CDI, D, DIAS, TB_US, brl
from motor import Fundo, roda

PX = pd.read_parquet(D / "i_arb_px.parquet")
CLO = pd.read_parquet(D / "i_arb_close.parquet")
VOLF = pd.read_parquet(D / "i_arb_vol.parquet")
ETFS = pd.read_parquet(D / "y_etf.parquet")
CAL = pd.bdate_range("2005-01-03", PX.index.max())
_C = {}


def _cache(k, f):
    if k not in _C:
        _C[k] = f()
    return _C[k]


def _cal(s, lim=5, cal=None):
    cal = CAL if cal is None else cal
    s = s.dropna()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(cal.union(s.index)).ffill(limit=lim).reindex(cal)


TB = _cal(TB_US).fillna(0)                                    # T-bill diário (fração por dia útil)
TB_AA = _cal(PX["^IRX"] / 100).ffill()


def px(tk, adj=True):
    src = PX if adj else CLO
    if tk not in src:
        src = ETFS
    return _cache(("px", tk, adj), lambda: _cal(src[tk]))


MOEDA = {".L": ("GBPUSD=X", 1), ".AX": ("AUDUSD=X", 1), ".AS": ("EURUSD=X", 1), ".DE": ("EURUSD=X", 1), ".PA": ("EURUSD=X", 1),
         ".MI": ("EURUSD=X", 1), ".BR": ("EURUSD=X", 1), ".HE": ("EURUSD=X", 1), ".HK": ("HKD=X", -1), ".SS": ("CNY=X", -1),
         ".SZ": ("CNY=X", -1), ".KS": ("KRW=X", -1), ".T": ("JPY=X", -1), ".SW": ("CHF=X", -1), ".ST": ("SEK=X", -1),
         ".CO": ("DKK=X", -1), ".JO": ("ZAR=X", -1), ".OL": ("NOK=X", -1), ".SI": ("SGD=X", -1), ".TO": ("CAD=X", -1)}


def suf(tk):
    return "." + tk.split(".")[-1] if "." in tk and not tk.startswith("^") else ""


def usd(tk):
    """Preço em dólar (ajustado)."""
    def f():
        p = px(tk)
        m = MOEDA.get(suf(tk))
        if m is None:
            return p
        fx = px(m[0])
        return p * fx if m[1] > 0 else p / fx
    return _cache(("usd", tk), f)


def r_(s):
    return s.pct_change(fill_method=None)


def r_fut(tk, k=5):
    """Futuro contínuo Yahoo: zera saltos de rolagem (|r| > k desvios robustos) e erros > 30%."""
    def f():
        r = r_(px(tk))
        s = r.abs().rolling(63, min_periods=20).median().shift(1) * 1.4826
        return r.where(~(r.abs() > k * s), 0.0).where(r.abs() < .3, 0.0).where(r.notna())
    return _cache(("fut", tk), f)


def ex_us(tk):
    """Excesso sobre o T-bill de uma ação/ETF em dólar (sem câmbio: hedge), ou futuro (sem caixa)."""
    if "=F" in tk:
        return r_fut(tk)
    return (r_(usd(tk)) - TB).where(r_(usd(tk)).notna())


# ------------------------------------------------------------------ custos
def adv_usd(tk):
    v = VOLF[tk].dropna() if tk in VOLF else pd.Series(dtype=float)
    if v.empty:
        return np.nan
    m = MOEDA.get(suf(tk))
    fx = 1.0
    if m is not None:
        f = PX[m[0]].dropna()
        fx = f.iloc[-500:].median() if len(f) else 1.0
        fx = fx if m[1] > 0 else 1 / fx
    if suf(tk) == ".L":
        fx /= 100                                                 # Londres cota em pence
    return float(v.iloc[-750:].median() * fx)


def custo(tk):
    """Custo de uma via (meio spread + impacto) pela liquidez + imposto/selo médio por via."""
    a = adv_usd(tk)
    base = (.0003 if a > 5e8 else .0005 if a > 1e8 else .0010 if a > 2e7 else .0020 if a > 5e6 else .0035 if a > 1e6 else .0060) \
        if a == a else .0030
    imp = {".L": .0025, ".HK": .0006, ".SS": .0004, ".SZ": .0004, ".KS": .0010, ".PA": .0015, ".MI": .0005}.get(suf(tk), 0)
    return base + imp


def aluguel(tk):
    if suf(tk) in (".SS", ".SZ"):
        return .08
    return .005 if custo(tk) - {".L": .0025, ".HK": .0006, ".KS": .0010, ".PA": .0015, ".MI": .0005}.get(suf(tk), 0) <= .0010 else .02


# janelas de proibição de venda a descoberto na Coreia (FSC): 2008-10/2009-05; 2011-08/11; 2020-03-16 em diante para fora do KOSPI200
# (preferenciais incluídas) até 30/03/2025; ações do KOSPI200 voltaram em 03/05/2021 e foram proibidas de novo de 06/11/2023 a 30/03/2025.
BAN_KR = [("2008-10-01", "2009-05-31"), ("2011-08-10", "2011-11-09"), ("2023-11-06", "2025-03-30")]
BAN_KR_PREF = BAN_KR + [("2020-03-16", "2025-03-30")]
BAN_KR_ORD = BAN_KR + [("2020-03-16", "2021-05-02")]


def pode_vender(tk):
    s = pd.Series(True, index=CAL)
    if suf(tk) == ".KS":
        pref = tk[5] != "0"
        for a, b in (BAN_KR_PREF if pref else BAN_KR_ORD):
            s[a:b] = False
    return s


# ------------------------------------------------------------------ máquina comum
def maquina(Z, z_in, z_out=0.0, z_stop=4.0, tmax=120, pode_l=None, pode_s=None, ok_l=None, ok_s=None):
    """Reversão à média: +1 quando z < -z_in (compra o lado barato), -1 quando z > z_in; sai em z_out, stop |z|>z_stop ou tmax.
    pode_l/pode_s: máscaras (DataFrame bool) que permitem ABRIR o lado comprado/vendido do par; ok_*: filtros extras de entrada."""
    Zv = Z.values
    n, m = Zv.shape
    PL = np.ones((n, m), bool) if pode_l is None else pode_l.reindex(index=Z.index, columns=Z.columns).fillna(False).values.astype(bool)
    PS = np.ones((n, m), bool) if pode_s is None else pode_s.reindex(index=Z.index, columns=Z.columns).fillna(False).values.astype(bool)
    OL = np.ones((n, m), bool) if ok_l is None else ok_l.reindex(index=Z.index, columns=Z.columns).fillna(False).values.astype(bool)
    OS = np.ones((n, m), bool) if ok_s is None else ok_s.reindex(index=Z.index, columns=Z.columns).fillna(False).values.astype(bool)
    out = np.zeros((n, m))
    pos, t = np.zeros(m), np.zeros(m)
    bloq = np.zeros(m, bool)                                    # depois de saída por prazo/stop: só reentra após |z| voltar abaixo de z_in
    for i in range(n):
        z = Zv[i]
        ok = np.isfinite(z)
        bloq &= ~(ok & (np.abs(z) < z_in))
        forcada = (pos != 0) & ((t >= tmax) | (ok & (np.abs(z) > z_stop)))
        sai = ((pos == 1) & ok & (z > -z_out)) | ((pos == -1) & ok & (z < z_out)) | forcada | ~ok
        bloq |= forcada
        pos[sai], t[sai] = 0, 0
        pos[(pos == 0) & ~bloq & ok & (z < -z_in) & (z > -z_stop) & PL[i] & OL[i]] = 1
        pos[(pos == 0) & ~bloq & ok & (z > z_in) & (z < z_stop) & PS[i] & OS[i]] = -1
        t[pos != 0] += 1
        out[i] = pos
    return pd.DataFrame(out, index=Z.index, columns=Z.columns)


def executa(W, R, cust, al_l=0.0, al_s=0.0, lag=0, cm=1, detalhe=False, fin=.01):
    """W decidido no fechamento de t, executado em t+1+lag, rende a partir de t+2+lag (igual a base.carteira).
    R: excesso diário do PAR (perna comprada - perna vendida, ou resíduo). cust/al_*: escalar ou dict por coluna.
    Notional comprado acima de 1x o PL paga T-bill + fin."""
    R = R.fillna(0)
    W = W.reindex(index=R.index, columns=R.columns).fillna(0)
    We = W.shift(1 + lag).fillna(0)
    cs = lambda x: pd.Series(x, index=R.columns) if np.isscalar(x) else pd.Series(x).reindex(R.columns).fillna(0)
    W1 = We.shift(1).fillna(0)
    C = (W1 * R - We.diff().abs().fillna(We.abs()) * cs(cust) * cm
         - W1.clip(lower=0) * cs(al_l) / 252 - (-W1).clip(lower=0) * cs(al_s) / 252)
    ex = C.sum(axis=1) - (W1.abs().sum(axis=1) - 1).clip(lower=0) * fin / 252
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
                        "dias": int(i1 - i0), "peso_medio": float(np.abs(We[c].values[i0:i1]).mean()),
                        "retorno": float(np.prod(1 + s[i0] * R[c].fillna(0).values[seg]) - 1), "contrib": float(C[c].values[seg].sum())})
    return pd.DataFrame(lin)


def para_brl(res, detalhe):
    """(ex_usd, C_usd, trades) -> R$ com hedge (excesso sobre o CDI)."""
    if not detalhe:
        return brl(res)
    ex, C, T = res
    Cb = pd.DataFrame({c: brl(C[c]) for c in C.columns if C[c].abs().sum() > 0})
    return brl(ex), Cb, T


def zs(S, jan):
    m, s = S.rolling(jan, min_periods=jan // 2).mean(), S.rolling(jan, min_periods=jan // 2).std()
    return (S - m) / s, S - m


def tamanho(Wsig, R, alvo, teto, gross=3.0, jan=63):
    """Risco igual por par (vol-alvo alvo/sqrt(n)), teto por par e bruto total (soma |w|) <= gross (estimado só com o passado)."""
    v = R.rolling(jan, min_periods=40).std().shift(1) * np.sqrt(252)
    W = (Wsig * (alvo / np.sqrt(R.shape[1])) / v).replace([np.inf, -np.inf], 0).fillna(0).clip(-teto, teto)
    W = trava(W, Wsig)
    g = W.abs().sum(axis=1)
    return W.mul((gross / g).clip(upper=1).fillna(1), axis=0)


def trava(W, sig):
    """Tamanho fixado na entrada e mantido durante o negócio (sem giro diário de rebalanceamento por vol)."""
    novo = sig.ne(sig.shift(1)) & sig.ne(0)
    return W.where(novo).ffill().where(sig != 0, 0).fillna(0)


# ================================================================== I1/I2 classes de ações, dual-listed, preferenciais, A/H
def livro_spread(pares, jan, z_in, alvo=.10, teto=.5, gross=3.0, tmax=120, k_custo=3.0, lado=None, custo_mult=1, lag=0, detalhe=False,
                 extra_l=None, extra_s=None, neutro=False):
    """pares: {nome: (A, B)}; spread = log(A_usd) - log(B_usd) (mesma empresa / mesmo fluxo: razão de hedge 1).
    +1 = compra A e vende B (A barato). Entra só se |desvio| > k_custo x custo de ida e volta das duas pernas."""
    S, R, cust, al_l, al_s, PLm, PSm = {}, {}, {}, {}, {}, {}, {}
    for k, (a, b) in pares.items():
        pa, pb = usd(a), usd(b)
        ok = pa.notna() & pb.notna()
        S[k] = (np.log(pa) - np.log(pb)).where(ok)
        ra, rb = r_(px(a)), r_(px(b))                                 # retorno em moeda local (perna com hedge cambial)
        rr = (ra - rb).where(ok)
        R[k] = rr.where(rr.abs() < .15, 0.0)                            # quebra no PAR (fusão de classes, erro de base)
        cust[k] = custo(a) + custo(b)
        al_l[k], al_s[k] = aluguel(b), aluguel(a)
        PLm[k], PSm[k] = pode_vender(b), pode_vender(a)
    S, R = pd.DataFrame(S), pd.DataFrame(R)
    if neutro:                                                      # tira o fator comum (prêmio A/H do mercado, desconto médio das pref.)
        S = S.sub(S.mean(axis=1), axis=0)                           # e faz o hedge com a carteira igual de todos os pares do grupo
        R = R.sub(R.mean(axis=1), axis=0).where(R.notna())
        cm_ = np.mean(list(cust.values()))
        cust = {k: v + cm_ for k, v in cust.items()}
    Z, dev = zs(S, jan)
    rt = pd.Series(cust) * 2
    grande = dev.abs().gt(k_custo * rt, axis=1)
    PL, PS = pd.DataFrame(PLm), pd.DataFrame(PSm)
    if lado is not None:
        for k, ld in lado.items():
            if ld == "so_l":
                PS[k] = False
            elif ld == "so_s":
                PL[k] = False
    sig = maquina(Z, z_in, tmax=tmax, pode_l=PL & grande, pode_s=PS & grande,
                  ok_l=extra_l, ok_s=extra_s)
    W = tamanho(sig, R, alvo, teto, gross)
    W = W.where(sig != 0, 0)
    return para_brl(executa(W, R, cust, al_l, al_s, lag, custo_mult, detalhe), detalhe)


CLASSES_EUA = {"GOOG x GOOGL": ("GOOG", "GOOGL"), "BRK-B x BRK-A": ("BRK-B", "BRK-A"), "FOX x FOXA": ("FOX", "FOXA"),
               "NWS x NWSA": ("NWS", "NWSA"), "FWONK x FWONA": ("FWONK", "FWONA"), "BATRK x BATRA": ("BATRK", "BATRA"),
               "UA x UAA": ("UA", "UAA"), "LEN-B x LEN": ("LEN-B", "LEN"), "HEI-A x HEI": ("HEI-A", "HEI"), "MOG-B x MOG-A": ("MOG-B", "MOG-A"),
               "BF-A x BF-B": ("BF-A", "BF-B"), "Z x ZG": ("Z", "ZG"), "GEF-B x GEF": ("GEF-B", "GEF")}
CLASSES_EUR = {"HEIO x HEIA (Heineken Holding)": ("HEIO.AS", "HEIA.AS"), "LISN x LISP (Lindt)": ("LISN.SW", "LISP.SW"),
               "VOW x VOW3": ("VOW.DE", "VOW3.DE"), "HEN x HEN3": ("HEN.DE", "HEN3.DE"), "SRT x SRT3": ("SRT.DE", "SRT3.DE"),
               "FPE x FPE3": ("FPE.DE", "FPE3.DE"), "ATCO A x B": ("ATCO-A.ST", "ATCO-B.ST"), "ERIC A x B": ("ERIC-A.ST", "ERIC-B.ST"),
               "INVE A x B": ("INVE-A.ST", "INVE-B.ST"), "VOLV A x B": ("VOLV-A.ST", "VOLV-B.ST"), "SKF A x B": ("SKF-A.ST", "SKF-B.ST"),
               "ESSITY A x B": ("ESSITY-A.ST", "ESSITY-B.ST"), "SCHN x SCHP": ("SCHN.SW", "SCHP.SW"), "CARL A x B": ("CARL-A.CO", "CARL-B.CO"),
               "MAERSK A x B": ("MAERSK-A.CO", "MAERSK-B.CO"), "UHR x UHRN (Swatch)": ("UHR.SW", "UHRN.SW")}
DLC = {"RIO.L x RIO.AX (DLC)": ("RIO.L", "RIO.AX"), "BHP.L x BHP.AX (DLC até jan/22)": ("BHP.L", "BHP.AX"),
       "UNA.AS x ULVR.L (dupla listagem)": ("UNA.AS", "ULVR.L")}
COREIA = {"Samsung Elec pref x ord": ("005935.KS", "005930.KS"), "Hyundai Motor pref x ord": ("005385.KS", "005380.KS"),
          "Hyundai Motor 2pref x ord": ("005387.KS", "005380.KS"), "LG Chem pref x ord": ("051915.KS", "051910.KS"),
          "LG Elec pref x ord": ("066575.KS", "066570.KS"), "Samsung Fire pref x ord": ("000815.KS", "000810.KS"),
          "Amorepacific pref x ord": ("090435.KS", "090430.KS"), "LG Corp pref x ord": ("003555.KS", "003550.KS"),
          "LG H&H pref x ord": ("051905.KS", "051900.KS"), "Samsung SDI pref x ord": ("006405.KS", "006400.KS"),
          "Samsung EM pref x ord": ("009155.KS", "009150.KS")}
from dados_i_arb_comm import AH                                     # {nome: (A-share, H-share)}


def classes(conj="eua+eur+dlc", jan=63, z_in=2.0, k_custo=3.0, tmax=120, custo_mult=1, lag=0, detalhe=False):
    pares = {}
    if "eua" in conj:
        pares.update(CLASSES_EUA)
    if "eur" in conj:
        pares.update(CLASSES_EUR)
    if "dlc" in conj:
        pares.update(DLC)
    return livro_spread(pares, jan, z_in, tmax=tmax, k_custo=k_custo, custo_mult=custo_mult, lag=lag, detalhe=detalhe)


def soma(partes, detalhe):
    if not detalhe:
        return sum(partes)
    ex = sum(p[0] for p in partes)
    C = pd.concat([p[1] for p in partes], axis=1).fillna(0)
    T = pd.concat([p[2] for p in partes if len(p[2])], ignore_index=True)
    return ex, C, T


def asia(conj="coreia+ah", jan=126, z_in=2.0, neutro=0, lado_ah="ambos", custo_mult=1, lag=0, detalhe=False):
    partes = []
    if "coreia" in conj:
        partes.append(livro_spread(COREIA, jan, z_in, neutro=bool(neutro), custo_mult=custo_mult, lag=lag, detalhe=detalhe))
    if "ah" in conj:
        pares, lado = {}, {}
        for k, (a, h) in AH.items():
            pares[f"AH {k}"] = (h, a)                                   # +1 = compra H, vende A (prêmio A/H alto)
            if lado_ah == "sem_vender_A":
                lado[f"AH {k}"] = "so_s"                                 # só compra A (via Connect) e vende H
        partes.append(livro_spread(pares, jan, z_in, lado=lado, neutro=bool(neutro), custo_mult=custo_mult, lag=lag, detalhe=detalhe))
    if len(partes) == 2 and not detalhe:
        return .5 * partes[0] + .5 * partes[1]
    if len(partes) == 2:
        partes = [(.5 * p[0], .5 * p[1], p[2].assign(contrib=p[2].contrib * .5) if len(p[2]) else p[2]) for p in partes]
    return soma(partes, detalhe)


# ================================================================== I3 descontos de holdings
HOLDINGS = {"Naspers x Tencent": ("NPN.JO", {"0700.HK": 1.0}),
            "Prosus x Tencent": ("PRX.AS", {"0700.HK": 1.0}),
            "Porsche SE x VW pref": ("PAH3.DE", {"VOW3.DE": 1.0}),
            "Dior x LVMH": ("CDI.PA", {"MC.PA": 1.0}),
            "Wendel x Bureau Veritas": ("MF.PA", {"BVI.PA": 1.0}),
            "Heineken Holding x Heineken": ("HEIO.AS", {"HEIA.AS": 1.0}),
            "Exor x Ferrari/Stellantis/Philips": ("EXO.AS", {"RACE.MI": .55, "STLAM.MI": .15, "PHIA.AS": .15, "CNH": .15}),
            "Investor AB x carteira": ("INVE-B.ST", {"ABBN.SW": .17, "ATCO-A.ST": .22, "AZN.L": .16, "SEB-A.ST": .10, "SAAB-B.ST": .08,
                                                     "EQT.ST": .07, "EPI-A.ST": .07, "ERIC-B.ST": .05, "WRT1V.HE": .05, "HUSQ-B.ST": .03}),
            "Industrivarden x carteira": ("INDU-C.ST", {"VOLV-B.ST": .25, "SAND.ST": .25, "SHB-A.ST": .2, "ESSITY-B.ST": .1, "ERIC-B.ST": .05,
                                                         "SCA-B.ST": .08, "SKA-B.ST": .07}),
            "GBL x carteira": ("GBLB.BR", {"SGSN.SW": .3, "RI.PA": .2, "ADS.DE": .2, "NK.PA": .15, "UMI.BR": .15}),
            "SoftBank x BABA/TMUS/ARM/SB Corp": ("9984.T", {"BABA": .4, "TMUS": .2, "ARM": .25, "9434.T": .15}),
            "Jardine Matheson x HK Land/JC&C": ("J36.SI", {"H78.SI": .5, "C07.SI": .5})}


def cesta(pesos):
    """Retorno em dólar da carteira listada (pesos renormalizados entre os ativos com preço no dia)."""
    R = pd.DataFrame({t: r_(usd(t)) for t in pesos})
    w = pd.DataFrame({t: R[t].notna() * p for t, p in pesos.items()})
    w = w.div(w.sum(axis=1), axis=0)
    return (R.fillna(0) * w).sum(axis=1).where(w.sum(axis=1) > 0)


def beta_n(y, X, jan=252):
    """Betas rolantes (retornos de 5 dias, só passado) de y contra as colunas de X, por mínimos quadrados."""
    y5 = y.rolling(5).sum()
    X5 = X.rolling(5).sum()
    cols = list(X.columns)
    mp = jan // 2
    Cxy = pd.DataFrame({c: y5.rolling(jan, min_periods=mp).cov(X5[c]) for c in cols})
    Cxx = {(a, b): X5[a].rolling(jan, min_periods=mp).cov(X5[b]) for a in cols for b in cols}
    B = np.full((len(y), len(cols)), np.nan)
    M = np.stack([np.stack([Cxx[(a, b)].values for b in cols], -1) for a in cols], -2)     # T x k x k
    v = Cxy.values
    for i in range(len(y)):
        if np.isfinite(M[i]).all() and np.isfinite(v[i]).all():
            try:
                B[i] = np.linalg.solve(M[i] + 1e-12 * np.eye(len(cols)), v[i])
            except np.linalg.LinAlgError:
                pass
    return pd.DataFrame(B, index=y.index, columns=cols).shift(1)


def holdings(jan=126, z_in=2.0, lado="ambos", alvo=.10, custo_mult=1, lag=0, detalhe=False):
    """Compra a holding e vende a carteira listada (beta rolante) quando o resíduo acumulado (desconto) abre demais; o inverso se lado='ambos'."""
    R, cust, al_l, al_s, Z = {}, {}, {}, {}, {}
    for k, (h, pesos) in HOLDINGS.items():
        rh, rb = r_(usd(h)), cesta(pesos)
        b = beta_n(rh, rb.to_frame("b"))["b"].clip(0, 2)
        e = (rh - b * rb).where(rh.notna() & rb.notna())
        e = e.where(e.abs() < .15, 0.0)
        R[k] = e
        cust[k] = custo(h) + np.mean([custo(t) for t in pesos])
        al_l[k] = np.mean([aluguel(t) for t in pesos])
        al_s[k] = aluguel(h)
    R = pd.DataFrame(R)
    X = R.fillna(0).cumsum().where(R.notna())
    Zs, _ = zs(X, jan)
    PS = None if lado == "ambos" else pd.DataFrame(False, index=R.index, columns=R.columns)
    sig = maquina(Zs, z_in, pode_s=PS)
    W = tamanho(sig, R, alvo, teto=1.0, gross=2.0)
    W = W.where(sig != 0, 0)
    return para_brl(executa(W, R, cust, al_l, al_s, lag, custo_mult, detalhe), detalhe)


# ================================================================== I4 prêmio de vol com hedge de beta (CBOE + swaps de variância)
def cboe():
    def f():
        c = pd.read_parquet(D / "i_arb_cboe.parquet")
        c = c[~c.index.duplicated()]
        c.loc[:, "PUT"] = c["PUT"].combine_first(PX["^PUT"] if "^PUT" in PX else pd.read_parquet(D / "y_idx.parquet")["^PUT"])
        return c
    return _cache("cboe", f)


# custo de rolagem por mês (fração do nocional): meio spread das opções de SPX vendidas (PUT/BXM ~2-3% do prêmio de ~1,5-2%)
ROLA = {"PUT": (.0005, 12), "BXM": (.0005, 12), "BXMD": (.0004, 12), "BXY": (.0005, 12), "CNDR": (.0010, 12), "BFLY": (.0010, 12),
        "WPUT": (.0003, 52), "PUTR": (.0005, 12), "CMBO": (.0010, 12), "CLL": (.0008, 12)}


def var_swap(vol_idx, ativo, cal, n=21, custo_vol=.005, cap=2.5):
    """Vendido em swap de variância de 1 mês (strike = índice de vol² no dia da entrada, menos o custo em pontos de vol), rolado a cada n dias,
    marcado diariamente: valor = K - [i/n RV_i + (n-i)/n IV_t²]; teto de 2,5x o strike em vol (padrão de mercado).
    Nocional de vega: P&L em pontos de vol (fração) por 1 de vega."""
    iv = (vol_idx / 100).reindex(cal).ffill(limit=3)
    r = np.log(ativo.reindex(cal).ffill(limit=3)).diff()
    out = pd.Series(0.0, index=cal)
    ivv, rv = iv.values, r.values
    i0 = 0
    while i0 + 1 < len(cal):
        if not np.isfinite(ivv[i0]):
            i0 += 1
            continue
        K_vol = max(ivv[i0] - custo_vol, .01)
        K = K_vol ** 2
        vega = 1 / (2 * K_vol)
        v_ant, soma = 0.0, 0.0
        for i in range(1, n + 1):
            j = i0 + i
            if j >= len(cal):
                break
            soma += (rv[j] if np.isfinite(rv[j]) else 0.0) ** 2
            rv_i = min(soma * 252 / i, (cap * K_vol) ** 2)
            ivt = ivv[j] if np.isfinite(ivv[j]) else ivv[i0]
            val = K - (i / n * rv_i + (n - i) / n * ivt ** 2) if i < n else K - rv_i
            out.iloc[j] = (val - v_ant) * vega
            v_ant = val
        i0 += n
    return out


def vol_series():
    """Excesso diário (US$) de cada estrutura de venda de vol, antes do hedge de beta, e o retorno do índice para o hedge."""
    def f():
        c = cboe()
        out, hed = {}, {}
        spx_tr = r_(px("SPY"))                                          # S&P com dividendos
        for k, (cr, n) in ROLA.items():
            if k not in c:
                continue
            s = _cal(c[k], lim=3)
            out[k] = r_(s) - TB - cr * n / 252
            hed[k] = spx_tr - TB
        vix, v2x = px("^VIX"), _cal(pd.read_parquet(D / "i_arb_v2x.parquet")["V2TX"])
        out["VS_EUA"] = var_swap(vix, px("^GSPC"), CAL, custo_vol=.010)
        hed["VS_EUA"] = r_(px("^GSPC"))
        out["VS_EUR"] = var_swap(v2x, px("^STOXX50E"), CAL, custo_vol=.015)
        hed["VS_EUR"] = r_(px("^STOXX50E"))
        return pd.DataFrame(out), pd.DataFrame(hed)
    return _cache("volser", f)


def filtro_vol(tipo):
    vix, v3, vv = px("^VIX"), px("^VIX3M"), px("^VVIX")
    if tipo == "contango":
        return (v3 / vix > 1.0)
    if tipo == "vvix":
        return (vv < vv.rolling(252, min_periods=120).quantile(.8)) & (v3 / vix > 1.0)
    return pd.Series(True, index=CAL)


def premio_vol(estrutura="PUT", filtro="sempre", hedge=1, alvo=.08, custo_mult=1, lag=0, detalhe=False):
    """Vende vol (índice CBOE, ou swap de variância sintético EUA/Europa) e vende beta x índice para tirar o beta.
    Tamanho: vol-alvo (estimada com o passado, teto 3x) para comparar estruturas. Filtro: só ligado com curva do VIX em contango (e VVIX < p80)."""
    O, Hd = vol_series()
    ests = estrutura.split("+")
    R = {}
    for e in ests:
        x, h = O[e], Hd[e]
        if hedge:
            b = beta_n(x, h.to_frame("h"), 252)["h"].clip(-1, 2)
            x = x - b * h
        R[e] = x.where(O[e].index >= O[e].ne(0).idxmax())
    R = pd.DataFrame(R)
    sig = pd.DataFrame({e: filtro_vol(filtro).astype(float) for e in ests}).reindex(R.index).fillna(0)
    v = (R.where(sig.shift(1) > 0)).rolling(126, min_periods=40).std().shift(1) * np.sqrt(252)
    v = v.fillna(R.rolling(126, min_periods=40).std().shift(1) * np.sqrt(252))
    W = (sig * alvo / np.sqrt(len(ests)) / v).clip(upper=3).fillna(0)
    W = W.where(R.notna().cumsum() > 40, 0)
    # o índice CBOE já é o resultado da estrutura; custo de ligar/desligar = 1 rolagem extra (meio spread da opção) + hedge 1 bp
    cst = {e: ROLA.get(e, (.004 if e == "VS_EUA" else .008, 0))[0] + .0001 for e in ests}
    return para_brl(executa(W, R, cst, 0, 0, lag, custo_mult, detalhe, fin=0.0), detalhe)


# ================================================================== I5 futuros de VIX vendidos (roll do contango)
def vix_curto(perna="VIXY", filtro="contango", hedge=0, peso=.25, custo_mult=1, lag=0, detalhe=False):
    """Vendido 1x em futuros de VIX de curto prazo (= vender VIXY/VXX; aluguel 3% a.a.) ou médio prazo (VIXM), com filtro de contango/VVIX
    e hedge opcional do beta ao S&P. Sem o bug do SVXY: VIXY é o índice de futuros 1x; vendê-lo é exatamente o antigo SVXY -1x."""
    r = r_(px(perna))
    x = (-r + TB - .03 / 252).where(r.notna())
    if hedge:
        h = r_(px("SPY")) - TB
        b = beta_n(x, h.to_frame("h"), 252)["h"].clip(-1, 3)
        x = x - b * h
    sig = filtro_vol(filtro).astype(float).reindex(CAL).fillna(0) * peso
    W = sig.to_frame(perna).where(x.notna().cumsum().to_frame(perna) > 60, 0)
    R = x.to_frame(perna)
    return para_brl(executa(W, R, .0005 + .0001 * hedge, 0, 0, lag, custo_mult, detalhe, fin=0.0), detalhe)


def svxy_bug():
    """Mostra o problema: SVXY era -1x até 27/02/2018 e -0,5x depois. Série 'corrigida' = r_SVXY x 2 depois da troca."""
    s, v = r_(px("SVXY")), r_(px("VIXY"))
    corr = s.copy()
    corr[corr.index > "2018-02-27"] *= 2
    return pd.DataFrame({"SVXY": s, "SVXY_corrigido_-1x": corr, "-VIXY": -v})


# ================================================================== I6/I7 ações x commodity com hedge (2 fatores: commodity + mercado)
ENERGIA = {**{f"{t} x crack": (t, "CRACK") for t in ["VLO", "MPC", "PSX", "PBF", "DINO", "DK"]},
           **{f"{t} x Brent": (t, "BZ=F") for t in ["XOM", "CVX", "SHEL", "BP", "TTE", "COP", "EQNR", "PBR"]},
           **{f"{t} x diesel/QAV": (t, "HO=F") for t in ["AAL", "DAL", "UAL", "LUV", "RYAAY", "LHA.DE", "AF.PA"]},
           **{f"{t} x carvão": (t, "MTF=F") for t in ["BTU", "AMR", "WHC.AX", "NHC.AX", "YAL.AX"]}}
METAIS = {**{f"{t} x minério": (t, "TIO=F") for t in ["BHP", "RIO", "FMG.AX", "VALE"]},
          **{f"{t} x cobre": (t, "HG=F") for t in ["FCX", "SCCO", "ANTO.L", "TECK", "GLEN.L", "AAL.L"]},
          **{f"{t} x ouro": (t, "GC=F") for t in ["NEM", "AEM", "KGC", "GOLD", "NST.AX", "EVN.AX"]},
          **{f"{t} x urânio físico": (t, "YCA.L") for t in ["CCJ", "NXE", "UEC", "DNN"]},
          **{f"{t} x HRC": (t, "HRC=F") for t in ["NUE", "STLD", "CLF", "MT"]},
          **{f"{t} x milho": (t, "ZC=F") for t in ["CF", "MOS", "NTR", "YAR.OL"]},
          "TSN x boi": ("TSN", "LE=F"), "PPC x milho": ("PPC", "ZC=F"), "HRL x porco": ("HRL", "HE=F"), "S32.AX x alumínio": ("S32.AX", "ALI=F")}


def r_comm(tk):
    if tk == "CRACK":
        return (2 / 3 * r_fut("RB=F") + 1 / 3 * r_fut("HO=F") - r_fut("CL=F"))
    if "=F" in tk:
        return r_fut(tk)
    return ex_us(tk)


def mercado(tk):
    return ex_us("SPY") if suf(tk) == "" else (r_(px("EFA")) - TB)


def residuos(pares, jb=252):
    def f():
        R, Vc = {}, {}
        for k, (a, c) in pares.items():
            y = ex_us(a)
            X = pd.DataFrame({"c": r_comm(c), "m": mercado(a)})
            B = beta_n(y, X, jb)
            B["c"] = B["c"].clip(-3, 3)
            B["m"] = B["m"].clip(0, 3)
            e = y - B["c"] * X["c"] - B["m"] * X["m"]
            ok = y.notna() & X["c"].notna()
            R[k] = e.where(ok)
            Vc[k] = X["c"].rolling(21, min_periods=15).std()
        R = pd.DataFrame(R)
        R = R.where(R.abs() < .25, 0.0)
        return R, pd.DataFrame(Vc)
    return _cache(("res", tuple(pares)), f)


def livro_comm(pares, jan=126, z_in=2.0, filtro="nenhum", modo="reversao", alvo=.10, custo_mult=1, lag=0, detalhe=False):
    """modo='reversao': compra o resíduo barato (tese de mesa); 'momentum': segue o resíduo (a ação que executa melhor que a commodity continua)."""
    R, Vc = residuos(pares)
    X = R.fillna(0).cumsum().where(R.notna())
    Z, _ = zs(X, jan)
    if modo == "momentum":
        Z = -Z
    Z = Z.where(pd.Series(CAL.weekday == 4, index=CAL), np.nan).ffill(limit=4)      # decisão semanal (sexta)
    ok = None
    if filtro == "panico":                                      # só entra quando a commodity está em estresse (vol 21d > p75 de 1 ano)
        ok = Vc > Vc.rolling(252, min_periods=120).quantile(.75)
    sig = maquina(Z, z_in, ok_l=ok, ok_s=ok)
    W = tamanho(sig, R, alvo, teto=1.0, gross=4.0)
    W = W.where(sig != 0, 0)
    cust = {k: custo(a) + .0003 + .0002 for k, (a, c) in pares.items()}           # ação + futuro da commodity + futuro de índice
    al_s = {k: aluguel(a) for k, (a, c) in pares.items()}
    rola = {k: .004 for k in pares}                                               # rolagem mensal do futuro da commodity
    return para_brl(executa(W, R, cust, rola, {k: al_s[k] + .004 for k in pares}, lag, custo_mult, detalhe), detalhe)


def energia(jan=126, z_in=2.0, filtro="nenhum", modo="reversao", custo_mult=1, lag=0, detalhe=False):
    return livro_comm(ENERGIA, jan, z_in, filtro, modo, custo_mult=custo_mult, lag=lag, detalhe=detalhe)


def metais(jan=126, z_in=2.0, filtro="nenhum", modo="reversao", custo_mult=1, lag=0, detalhe=False):
    return livro_comm(METAIS, jan, z_in, filtro, modo, custo_mult=custo_mult, lag=lag, detalhe=detalhe)


# ================================================================== I8 spreads de commodities com arbitragem física
def _crush_prod():
    zm, zl = px("ZM=F"), px("ZL=F")
    vm, vo = zm * .022 * 100, zl * 11                                 # ¢ por bushel de farelo e de óleo (prancha de esmagamento)
    wm = (vm / (vm + vo)).shift(1)
    return wm * r_fut("ZM=F") + (1 - wm) * r_fut("ZL=F")


def spreads(jan=126, z_in=2.0, conj="fisicos", gas=1, alvo=.10, custo_mult=1, lag=0, detalhe=False):
    """Pares de futuros: resíduo (beta 1 ano) do lado A contra o lado B; z-score do resíduo acumulado; decisão semanal."""
    P = {"crack 3:2:1": (2 / 3 * r_fut("RB=F") + 1 / 3 * r_fut("HO=F"), r_fut("CL=F")),
         "crush soja": (_crush_prod(), r_fut("ZS=F")),
         "trigo KC x Chicago": (r_fut("KE=F"), r_fut("ZW=F")),
         "boi gordo x bezerro": (r_fut("LE=F"), r_fut("GF=F")),
         "porco x milho": (r_fut("HE=F"), r_fut("ZC=F")),
         "diesel x gasolina": (r_fut("HO=F"), r_fut("RB=F")),
         "Brent x WTI": (r_fut("BZ=F"), r_fut("CL=F"))}
    if conj == "todos":
        P.update({"prata x ouro": (r_fut("SI=F"), r_fut("GC=F")), "platina x paládio": (r_fut("PL=F"), r_fut("PA=F")),
                  "trigo x milho": (r_fut("ZW=F"), r_fut("ZC=F")), "soja x milho": (r_fut("ZS=F"), r_fut("ZC=F")),
                  "café x açúcar": (r_fut("KC=F"), r_fut("SB=F"))})
    R = {}
    for k, (a, b) in P.items():
        bt = beta_n(a, b.to_frame("b"), 252)["b"].clip(0, 3)
        R[k] = (a - bt * b).where(a.notna() & b.notna())
    R = pd.DataFrame(R)
    X = R.fillna(0).cumsum().where(R.notna())
    Z, _ = zs(X, jan)
    Z = Z.where(pd.Series(CAL.weekday == 4, index=CAL), np.nan).ffill(limit=4)
    sig = maquina(Z, z_in)
    W = tamanho(sig, R, alvo, teto=2.0, gross=6.0)
    W = W.where(sig != 0, 0)
    if gas:                                                          # gás natural vendido out-fev (prêmio de inverno + contango)
        g = r_(px("UNG")) - TB
        R["UNG vendido (inverno)"] = -g + 2 * TB                     # vendido: -r + rebate (T-bill) ; excesso sobre T-bill
        m = pd.Series(CAL.month, index=CAL)
        sg = (m.isin([10, 11, 12, 1, 2])).astype(float)
        vv = g.rolling(63, min_periods=40).std().shift(1) * np.sqrt(252)
        W["UNG vendido (inverno)"] = (sg * (alvo / np.sqrt(R.shape[1])) / vv).clip(upper=.5).fillna(0) * 1.0
        R["UNG vendido (inverno)"] = -g - .01 / 252                  # aluguel 1% a.a.; peso positivo = vendido
    cust = {k: .0006 for k in R.columns}
    cust["UNG vendido (inverno)"] = .0003
    rola = {k: .005 for k in R.columns}
    rola["UNG vendido (inverno)"] = 0
    return para_brl(executa(W, R, cust, rola, rola, lag, custo_mult, detalhe), detalhe)


# ================================================================== I9 base: cripto (trimestral + perpétuo) e S&P (ES x SPY)
def painel_perp():
    def f():
        fu = pd.read_parquet(D / "i_arb_funding.parquet")
        fu["dia"] = (fu.t - pd.Timedelta(milliseconds=1)).dt.normalize() + pd.Timedelta(days=1)    # pago em (d-1 00h, d 00h] -> dia d
        F = fu.groupby(["dia", "sym"]).taxa.sum().unstack()
        k = pd.read_parquet(D / "i_arb_cripto_d.parquet")
        k["dia"] = k.t + pd.Timedelta(days=1)                         # fechamento do candle = 00h UTC do dia seguinte
        S = k[k.mkt == "spot"].pivot_table(index="dia", columns="sym", values="fech")
        P = k[k.mkt == "perp"].pivot_table(index="dia", columns="sym", values="fech")
        V = k[k.mkt == "perp"].pivot_table(index="dia", columns="sym", values="vol_usd")
        cal = pd.date_range("2019-09-10", F.index.max(), freq="D")
        return F.reindex(cal).fillna(0), S.reindex(cal), P.reindex(cal), V.reindex(cal)
    return _cache("perp", f)


def carry_perp(thr=.10, capital=1.25, custo_mult=1, lag=0, detalhe=False):
    """Compra spot e vende o perpétuo quando o financiamento médio de 7 dias (anualizado) supera o T-bill + thr; sai quando cai abaixo do T-bill.
    Capital por moeda = 1,25 x nocional; peso igual entre as moedas ligadas (máx. 40% cada)."""
    F, S, P, V = painel_perp()
    tb = TB_AA.reindex(F.index, method="ffill").fillna(0)
    f7 = F.rolling(7, min_periods=7).sum() / 7 * 365
    liga = f7.sub(tb, axis=0) > thr
    desl = f7.sub(tb, axis=0) < 0
    st = pd.DataFrame(0.0, index=F.index, columns=F.columns)
    for c in F.columns:
        on, v = False, np.zeros(len(F))
        L, Dl = liga[c].values, desl[c].values
        ok = (S[c].notna() & P[c].notna() & (V[c].rolling(30).median() > 5e7)).values      # perpétuo líquido (> US$50 mi/dia)
        for i in range(len(F)):
            if on and (Dl[i] or not ok[i]):
                on = False
            elif not on and L[i] and ok[i]:
                on = True
            v[i] = on
        st[c] = v
    n = st.sum(axis=1)
    W = st.div(n.clip(lower=1), axis=0).clip(upper=.4)
    # por unidade de PL na moeda: 1/capital em spot comprado + margem parada; excesso sobre o T-bill do PL inteiro
    R = (S / S.shift(1) - P / P.shift(1) + F) / capital
    R = R.sub(tb / 365, axis=0).mask(S.isna() | P.isna() | S.shift(1).isna() | P.shift(1).isna(), 0.0)
    ex = executa(W, R, .0015 / capital, 0, 0, lag, custo_mult, detalhe, fin=0.0)
    return ex


def base_es(thr=.004, custo_mult=1, lag=0, detalhe=False):
    """Compra SPY (com dividendos) e vende ES quando a taxa implícita do futuro (ln(F/S)/T + dividend yield) supera o T-bill + thr;
    segura até a véspera do vencimento (3ª sexta de mar/jun/set/dez). Excesso = r_SPY - r_ES - T-bill (custo 1 bp SPY + 0,5 bp ES por via)."""
    F, S = _cal(CLO["ES=F"], 1), px("^GSPC", adj=False)
    spy_tr, spy_px = r_(px("SPY")), r_(px("SPY", adj=False))
    q = (spy_tr - spy_px).rolling(252, min_periods=200).sum()
    venc = [d + pd.Timedelta(days=(4 - d.weekday()) % 7) for d in (pd.Timestamp(a, m, 15) for a in range(2005, 2028) for m in (3, 6, 9, 12))]
    vs = pd.Series(venc)
    prox = pd.Series([vs[vs > d].iloc[0] for d in CAL], index=CAL)
    T = (prox - CAL).dt.days / 365
    impl = np.log(F / S) / T + q
    edge = impl - TB_AA
    dias = (prox - CAL).dt.days
    rF = r_(F).where(prox.eq(prox.shift(1)), 0.0)                   # não atravessa a rolagem do contínuo
    R = (spy_tr - TB - rF).to_frame("SPY x ES")
    on, st = False, np.zeros(len(CAL))
    E, Dd = edge.values, dias.values
    for i in range(len(CAL)):
        if on and Dd[i] <= 3:
            on = False
        elif not on and np.isfinite(E[i]) and E[i] > thr and Dd[i] > 10:
            on = True
        st[i] = on
    W = pd.DataFrame({"SPY x ES": st}, index=CAL)
    return executa(W, R, .00015, 0, 0, lag, custo_mult, detalhe, fin=0.0), edge


def base(livro="perp", thr=.10, custo_mult=1, lag=0, detalhe=False):
    from ideias_arbitragem import carry_cripto
    partes = []
    if "trim" in livro:
        partes.append(("trim", carry_cripto("ambos", thr, 1.25, custo_mult, lag, detalhe=True)))
    if "perp" in livro:
        partes.append(("perp", para_brl(carry_perp(thr, 1.25, custo_mult, lag, detalhe=True), True)))
    if "es" in livro:
        (res, _) = base_es(.004, custo_mult, lag, detalhe=True)
        partes.append(("es", para_brl(res, True)))
    w = 1 / len(partes)
    ex = sum(p[1][0] for p in partes) * w
    if not detalhe:
        return ex
    C = pd.concat([p[1][1].add_prefix(f"{p[0]}:") * w for p in partes], axis=1).fillna(0)
    T = pd.concat([p[1][2].assign(ativo=lambda d, nm=p[0]: nm + ":" + d.ativo.astype(str)) for p in partes if len(p[1][2])], ignore_index=True)
    if "contrib" in T:
        T["contrib"] *= w
    return ex, C, T


# ================================================================== análises para o caderno
def analises(log=print):
    pd.set_option("display.width", 250)
    def st(x, a, b):
        x = x[(x.index >= a) & (x.index < b)].dropna()
        return pd.Series({"a.a.%": x.mean() * 252 * 100, "vol%": x.std() * np.sqrt(252) * 100,
                          "SR": x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan})
    O, Hd = vol_series()
    lin = []
    for e in O.columns:
        x, h = O[e], Hd[e]
        b = beta_n(x, h.to_frame("h"), 252)["h"].clip(-1, 2)
        xh = x - b * h
        bb = np.cov(x.dropna().align(h, join="inner")[0], x.dropna().align(h, join="inner")[1].fillna(0))[0, 1] / h.var()
        for nm, y in (("sem hedge", x), ("com hedge", xh)):
            a1, a2 = st(y, "2008-01-01", "2021-01-01"), st(y, "2021-01-01", "2030")
            lin.append({"estrutura": e, "versão": nm, "beta": bb if nm == "sem hedge" else np.nan, "IS a.a.%": a1["a.a.%"], "IS SR": a1.SR,
                        "OOS a.a.%": a2["a.a.%"], "OOS SR": a2.SR, "vol%": st(y, "2008-01-01", "2030")["vol%"]})
    log("\n## Venda de vol: excesso sobre o T-bill (US$, sem alavancagem; swaps em pontos de vol por 1 de vega), antes e depois do hedge de beta")
    log(pd.DataFrame(lin).round(2).to_string(index=False))
    vix, v2x = px("^VIX") / 100, _cal(pd.read_parquet(D / "i_arb_v2x.parquet")["V2TX"]) / 100
    for nm, iv, a in (("S&P/VIX", vix, px("^GSPC")), ("SX5E/VSTOXX", v2x, px("^STOXX50E"))):
        r = np.log(a).diff()
        rv = np.sqrt((r ** 2).rolling(21).sum().shift(-21) * 252 / 21)
        d = (iv - rv).dropna()
        log(f"\nPrêmio de vol {nm} (IV hoje - RV dos próximos 21 dias, pontos): média {d.mean()*100:.2f}, mediana {d.median()*100:.2f}, "
            f"% dias IV>RV {(d > 0).mean()*100:.0f}%; por ano (mediana):")
        log((d.groupby(d.index.year).median() * 100).round(1).to_frame("pts").T.to_string())
    sv = svxy_bug()
    a, b = sv[sv.index < "2018-02-27"].dropna(), sv[sv.index > "2018-03-05"].dropna()
    log("\n## SVXY: alavancagem mudou de -1x para -0,5x em 27/02/2018")
    log(f"antes: desvio SVXY/(-VIXY) = {a.SVXY.std()/a['-VIXY'].std():.2f}, corr {a.SVXY.corr(a['-VIXY']):.3f}; depois: {b.SVXY.std()/b['-VIXY'].std():.2f}, "
        f"corr {b.SVXY.corr(b['-VIXY']):.3f}. 05/02/2018: SVXY {sv.loc['2018-02-05','SVXY']*100:.1f}%, -VIXY {sv.loc['2018-02-05','-VIXY']*100:.1f}%; "
        f"06/02: SVXY {sv.loc['2018-02-06','SVXY']*100:.1f}%")
    acum = (1 + sv.fillna(0)).cumprod()
    log("acumulado 2012-2026: " + ", ".join(f"{c} {acum[c].iloc[-1]:.2f}x" for c in sv))
    # prêmio A/H e desconto das preferenciais coreanas (preço não ajustado)
    ah = {}
    for k, (a_, h_) in AH.items():
        pa, ph = _cal(CLO[a_]) / px("CNY=X"), _cal(CLO[h_]) / px("HKD=X")
        ah[k] = pa / ph - 1
    ah = pd.DataFrame(ah)
    log("\n## Prêmio A/H (A em US$ / H em US$ - 1), mediana entre os 26 pares, por ano (%)")
    m = ah.median(axis=1)
    log((m.groupby(m.index.year).agg(["median", "min", "max"]) * 100).round(0).T.to_string())
    kr = {}
    for k, (p_, o_) in COREIA.items():
        kr[k] = 1 - _cal(CLO[p_]) / _cal(CLO[o_])
    kr = pd.DataFrame(kr)
    log("\n## Desconto da preferencial coreana (1 - pref/ord, %), mediana por ano")
    log((kr.groupby(kr.index.year).median() * 100).round(0).T.to_string())
    hl = {}
    for k, (h_, pesos) in HOLDINGS.items():
        if len(pesos) == 1:
            u = list(pesos)[0]
            hl[k] = np.log(usd(h_) / usd(u))
    hl = pd.DataFrame(hl)
    log("\n## Holdings 1:1 — log(holding/ativo) em US$, variação desde o início (pp): queda = desconto abriu (ou dividendos diferentes)")
    log((hl.groupby(hl.index.year).last() - hl.apply(lambda s: s.dropna().iloc[0])).mul(100).round(0).T.to_string())
    F, S, P, V = painel_perp()
    log("\n## Financiamento dos perpétuos (soma em 12 meses, %)")
    log((F.rolling(365).sum().resample("YE").last() * 100).round(1).T.to_string())
    (_, edge) = base_es(.004, detalhe=True)
    log("\n## S&P: taxa implícita do ES (ln(F/S)/T + dividend yield) menos T-bill, mediana por ano (pp)")
    log((edge.groupby(edge.index.year).median() * 100).round(2).to_frame("pp").T.to_string())


# ================================================================== fundos
FUNDOS = [
    Fundo("IAC1 Classes de ações e dual-listed EUA/Europa", "Arbitragem global", "CDI",
          "Duas classes da mesma empresa (GOOG/GOOGL, BRK-A/B, Heineken/Heineken Holding, Lindt PS/NR, VW ON/PN, A/B suecas) e a mesma "
          "empresa em duas bolsas (Rio Tinto plc x Ltd, BHP plc x Ltd até 2022, Unilever Amsterdã x Londres) têm o mesmo fluxo; quando a "
          "diferença de preço sai de 2 desvios E paga 3x o custo de ida e volta, compro a barata e vendo a cara.",
          "Spread log (em US$) com média/desvio móveis; entra |z|>z_in, sai em z=0 ou em tmax dias, stop |z|>4; risco igual por par, teto 50% "
          "por par, bruto <= 3x; custos por liquidez + selo UK/FTT", classes,
          {"conj": ["eua+eur+dlc", "eur+dlc"], "z_in": [2.0, 2.5], "k_custo": [3.0, 5.0]}, inicio="2008-01-01"),
    Fundo("IAC2 Ásia: preferenciais coreanas e prêmio A/H", "Arbitragem global", "CDI",
          "A preferencial coreana (Samsung, Hyundai, LG) negocia com desconto de 10-50% sobre a ordinária com mais dividendo e o mesmo lucro; "
          "o A-share chinês negocia com prêmio sobre o H-share da mesma empresa por causa do controle de capital. Os dois spreads têm "
          "âncora (dividendos, Stock Connect) e voltam à média: compro o lado barato quando o desconto/prêmio sai do normal.",
          "Spread log em US$ (A com CNY, H com HKD); proibições de venda a descoberto da Coreia (2008-09, 2011, 2020-25) e aluguel de A-share "
          "8% a.a.; variante sem vender A-share (só compra A via Connect e vende H)", asia,
          {"conj": ["coreia+ah", "ah"], "neutro": [0, 1], "lado_ah": ["ambos", "sem_vender_A"]}, inicio="2008-01-01"),
    Fundo("IAC3 Descontos de holdings", "Arbitragem global", "CDI",
          "Holding listada (Naspers/Prosus, Porsche SE, Exor, Investor, Industrivärden, GBL, SoftBank, Dior, Wendel, Jardine) = carteira "
          "listada x (1 - desconto). Quando o desconto abre demais (resíduo da regressão contra a carteira muito negativo), compro a holding "
          "e vendo a carteira; quando fecha demais, o inverso.",
          "Resíduo diário (US$) da holding contra a cesta das participações listadas (beta 1 ano em retornos de 5 dias); z do resíduo "
          "acumulado; histerese; risco igual; variante só comprada no desconto", holdings,
          {"jan": [252, 504], "z_in": [2.0, 2.5], "lado": ["ambos", "desconto"]}, inicio="2008-01-01"),
    Fundo("IAC4 Prêmio de vol com hedge de beta (CBOE + variância EUA/Europa)", "Volatilidade global", "CDI",
          "Vender proteção paga um prêmio (IV > RV) — mas a rodada 1 mostrou que o put-write era beta de S&P. Aqui o beta é SEMPRE vendido: "
          "o que sobra é o prêmio de vol puro. Estruturas: put-write (PUT, WPUT), buy-write (BXMD), condor (CNDR) e swap de variância "
          "sintético de 1 mês no S&P (VIX²) e no Euro Stoxx 50 (VSTOXX²).",
          "Índices CBOE (desde 1986) com custo de rolagem; swap de variância marcado diariamente com teto de 2,5x; hedge = beta rolante x "
          "índice; vol-alvo 8%; filtro de curva do VIX em contango", premio_vol,
          {"estrutura": ["PUT", "BXMD", "CNDR", "WPUT", "VS_EUA", "VS_EUR"], "filtro": ["sempre", "contango"]}, inicio="2008-01-01"),
    Fundo("IAC5 Futuros de VIX vendidos (roll do contango)", "Volatilidade global", "CDI",
          "A curva do VIX fica em contango ~80% do tempo: quem vende o 1º/2º futuro e rola recebe o roll (5-10% ao mês em calmaria). "
          "Vendo VIXY (futuros de curto prazo) ou VIXM (médio) só quando a curva está em contango e o VVIX não está esticado.",
          "Vendido 25% do PL em VIXY/VIXM (aluguel 3% a.a.), filtro VIX3M/VIX > 1 (e VVIX < p80); hedge opcional do beta ao S&P", vix_curto,
          {"perna": ["VIXY", "VIXM"], "filtro": ["contango", "vvix", "sempre"], "hedge": [0, 1]}, inicio="2011-06-01"),
    Fundo("IAC6 Energia: refinadoras, petroleiras, aéreas e carvão vs commodity", "Valor relativo commodities", "CDI",
          "A ação de refinadora é o crack spread; a major é o Brent; a aérea é vendida em querosene; a carvoeira é o carvão. Tirando a "
          "commodity e o mercado (regressão de 2 fatores), o resíduo volta à média: compro a ação que ficou para trás da sua commodity.",
          "26 pares (EUA, Europa, Austrália) em US$: resíduo = ação - beta_c x commodity - beta_m x mercado (1 ano, 5 dias); z semanal do "
          "resíduo acumulado; histerese; variante só em estresse da commodity (vol 21d > p75); variante momentum do resíduo", energia,
          {"jan": [63, 126], "filtro": ["nenhum", "panico"], "modo": ["reversao", "momentum"]}, inicio="2008-01-01"),
    Fundo("IAC7 Metais, urânio, aço, fertilizantes e proteína vs commodity", "Valor relativo commodities", "CDI",
          "Mineradora = opção alavancada no metal (minério SGX, cobre, ouro, alumínio), produtora de urânio vs urânio físico (Yellow Cake), "
          "siderúrgica vs HRC, fertilizante vs milho, frigorífico vs boi/porco/milho. Mesma tese do C4 (GDXJ x GDX), em 30 pares globais.",
          "Mesma máquina do IAC6", metais, {"jan": [63, 126], "filtro": ["nenhum", "panico"], "modo": ["reversao", "momentum"]},
          inicio="2008-01-01"),
    Fundo("IAC8 Spreads de commodities com arbitragem física", "Valor relativo commodities", "CDI",
          "Crack 3:2:1, crush da soja, trigo KC x Chicago, boi gordo x bezerro (+ milho), porco x milho, diesel x gasolina e Brent x WTI "
          "voltam à média porque alguém processa/transporta fisicamente; mais gás natural vendido no inverno.",
          "Futuros contínuos com rolagem zerada; resíduo com beta 1 ano; z semanal; histerese; custo 3 bps por perna + rolagem 0,5% a.a.; "
          "variante com pares de 'qualidade' sem arbitragem física (prata/ouro, platina/paládio, trigo/milho, soja/milho, café/açúcar)",
          spreads, {"jan": [63, 126], "z_in": [1.5, 2.0], "conj": ["fisicos", "todos"]}, inicio="2008-01-01"),
    Fundo("IAC9 Base: cripto (trimestral e perpétuo) e S&P (SPY x ES)", "Arbitragem global", "CDI",
          "Quem quer alavancagem comprada paga: o futuro trimestral de BTC/ETH e o financiamento do perpétuo ficam 5-30% a.a. acima do "
          "T-bill em mercado de alta, e o futuro do S&P embute juro acima do T-bill quando os balanços dos bancos estão cheios. Compro o "
          "à vista e vendo o futuro/perpétuo só quando a base paga mais que T-bill + limiar.",
          "Trimestral COIN-M Binance (BTC, ETH), perpétuos USDT-M (BTC, ETH, SOL, BNB, XRP, DOGE; financiamento 8h), SPY x ES até a véspera "
          "do vencimento; capital 1,25x nocional em cripto; custos 15 bps por montagem", base,
          {"livro": ["trim", "perp", "trim+perp", "trim+perp+es"], "thr": [.05, .10]}, inicio="2020-01-01", corte="2023-01-01"),
]


def roda_tudo(so=None, log=print):
    from rodar import BENCH
    res = []
    for f in FUNDOS:
        if so and f.nome.split()[0] not in so:
            continue
        r = roda(f, CDI, BENCH[f.benchmark], lambda *a: log(*a))
        if r is None:
            log(f"{f.nome}: sem resultado")
            continue
        ex, C, T = f.func(**r["params"], detalhe=True)
        C = C[C.index >= f.inicio]
        r["contrib"] = C.loc[:, C.abs().sum() > 0]
        r["trades"] = T[pd.to_datetime(T.entrada) >= f.inicio].reset_index(drop=True) if len(T) else T
        o, rb = r["oos"], r["rob"]
        log(f"{f.nome[:58]:58s} {str(r['params']):62s} IS IR {r['is_ir']:5.2f} | OOS {o['retorno a.a. %']:5.1f}% vs {o['benchmark a.a. %']:5.1f}% "
            f"IR {o['IR vs bench']:5.2f} | P {rb['P(bater bench OOS) %']:3.0f}% | PBO {rb['PBO %']:3.0f}% | x2 {rb['OOS custo x2 (pp)']:5.1f} "
            f"| lag {rb['OOS execução +1 dia (pp)']:5.1f} | med {rb['mediana OOS das variantes (pp)']:5.1f} | %var {rb['% variantes > bench OOS']:3.0f}")
        res.append(r)
    for r in res:
        r["fundo"].func = None
    return res


if __name__ == "__main__":
    so = sys.argv[1:]
    if so == ["analise"]:
        with open(D.parent / "resultado" / "i_arb_comm_analises.txt", "w", encoding="utf-8") as fh:
            def lg(*a):
                s_ = " ".join(str(x) for x in a)
                print(s_, flush=True)
                fh.write(s_ + "\n")
            analises(lg)
        sys.exit()
    out_log = open(D.parent / "resultado" / ("log_i_arb_comm.txt" if not so else f"log_i_arb_comm_{'_'.join(so)}.txt"), "w", encoding="utf-8")

    def log(*a):
        s = " ".join(str(x) for x in a)
        print(s, flush=True)
        out_log.write(s + "\n")
        out_log.flush()

    res = roda_tudo(so, log)
    out = D.parent / "resultado" / ("ideias_i_arb_comm.pkl" if not so else f"ideias_i_arb_comm_{'_'.join(so)}.pkl")
    pickle.dump(res, open(out, "wb"))
    log("salvo", out)
