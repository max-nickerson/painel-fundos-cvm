"""
Frente i_credito_juros (fase 2): as estratégias de crédito e juros do Brasil replicadas em EUA, Europa, Reino Unido, Japão,
Austrália/Canadá e emergentes, só com dados gratuitos (FRED, BIS, Banco da Inglaterra, Yahoo) e com os eurobonds que já temos.
  I1 Juro real de valor (TIPS / linkers UK)            I6 Crédito antecipa ação (vende IWM/SPY)
  I2 Inflação implícita x expectativas (TIP x IEF)      I7 Eurobonds BR em stress (safra, compra-e-segura)
  I3 Prêmio do 2 anos sobre o fed funds                 I8 Juros globais relativos (10 anos, carry + reversão)
  I4 Inclinação 2s10s pelo ciclo do Fed                 I9 Carry G10+LatAm realista / real tático EM (regime e hedge de cauda)
  I5 Crédito HY EUA/Europa/EM: carry e "comprar o pânico" (com hedge de Treasury)
Uso: PYTHONIOENCODING=utf-8 python -W ignore ideias_i_credito_juros.py dados   (baixa, com cache)
     PYTHONIOENCODING=utf-8 python -W ignore ideias_i_credito_juros.py         (roda tudo -> resultado/ideias_i_credito_juros.pkl)
"""
import io
import pickle
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy.stats import norm

import atribuicao_fundos as af
import fundos_global as fg
from base import BIS, CDI, D, DIAS, DIAS_US, ETF, IDX, TB_US, brl, limpa, mensal, vol_alvo
from motor import Fundo, roda

OUT = Path(__file__).resolve().parent / "resultado"
CORTE = pd.Timestamp("2021-01-01")

# ======================================================================= dados (cache em dados/icj_*.parquet)
FRED_D = ["DFII5", "DFII7", "DFII10", "DFII20", "DFII30", "DGS1", "DGS2", "DGS3", "DGS5", "DGS7", "DGS10", "DGS20", "DGS30", "DFF",
          "T5YIE", "T10YIE", "T5YIFR", "DTB3"]
PAISES_10A = ["US", "DE", "GB", "JP", "CA", "FR", "IT", "ES", "AU", "CH", "SE", "NZ", "NO"]
FRED_M = ["MICH", "EXPINF1YR", "EXPINF5YR", "EXPINF10YR"] + [f"IRLTLT01{p}M156N" for p in PAISES_10A]
YAHOO = ["LTPZ", "STIP", "SCHP", "INXG.L", "SJNK", "ANGL", "FALN", "IHYG.L", "IEAC.L", "EMHY", "CEMB", "HYEM", "PCY", "VWOB", "IGOV",
         "BWX", "ZQ=F", "GOVT", "VCIT", "IHYU.L"]
CPI_PAISES = ["US", "GB", "XM", "JP", "AU", "NZ", "CA", "CH", "NO", "SE", "MX", "ZA", "TR", "IN", "ID", "KR", "CL", "CO", "PL", "HU",
              "CZ", "IL", "BR", "CN", "TH", "PH"]


def _fred(series):
    out = {}
    for s in series:
        t = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}", timeout=60).text
        d = pd.read_csv(io.StringIO(t))
        out[s] = pd.to_numeric(d.iloc[:, 1], errors="coerce").set_axis(pd.to_datetime(d.iloc[:, 0]))
    return pd.DataFrame(out).sort_index()


def _boe_real():
    """Curva real (spot) do Banco da Inglaterra, diária, vértices de 5, 10 e 20 anos (zip com xlsx por período)."""
    z = zipfile.ZipFile(io.BytesIO(requests.get("https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/glcrealddata.zip",
                                                headers={"User-Agent": "Mozilla/5.0"}, timeout=300).content))
    partes = []
    for n in z.namelist():
        if any(a in n for a in ("2005", "2016", "2025")):
            x = pd.read_excel(z.open(n), "4. spot curve", header=None)
            anos = x.iloc[3, 1:].astype(float).values
            d = x.iloc[5:].set_index(0)
            d.columns = anos
            d.index = pd.to_datetime(d.index)
            partes.append(d[[5.0, 10.0, 20.0]].astype(float).rename(columns=lambda c: f"UK_REAL{int(c)}"))
    return pd.concat(partes).sort_index().dropna(how="all")


def _bis_cpi():
    u = f"https://stats.bis.org/api/v1/data/WS_LONG_CPI/M.{'+'.join(CPI_PAISES)}.771/all?format=csv"
    d = pd.read_csv(io.StringIO(requests.get(u, timeout=120).text))
    return d.pivot_table(index=pd.to_datetime(d.TIME_PERIOD), columns="REF_AREA", values="OBS_VALUE").sort_index()


def baixa():
    import yfinance as yf
    tarefas = {"icj_fred_d": lambda: _fred(FRED_D), "icj_fred_m": lambda: _fred(FRED_M), "icj_boe_real": _boe_real, "icj_cpi": _bis_cpi,
               "icj_yahoo": lambda: yf.download(YAHOO, start="2005-01-01", progress=False, auto_adjust=True)["Close"]}
    for nome, f in tarefas.items():
        arq = D / f"{nome}.parquet"
        if arq.exists():
            print(nome, "já existe")
            continue
        x = f()
        x.to_parquet(arq)
        print(nome, x.shape, x.index.min().date(), x.index.max().date())


def _ld(nome):
    return pd.read_parquet(D / f"{nome}.parquet")


# ======================================================================= insumos comuns (calendário EUA)
C_UST, C_HY, C_FUT, C_G10, C_EM = .0003, .00075, .0001, .0002, .0015
_CACHE = {}


def ins():
    if _CACHE:
        return _CACHE
    fd0 = _ld("icj_fred_d").reindex(DIAS_US).ffill(limit=5)                 # taxas do dia (para o RETORNO dos Treasuries sintéticos)
    fd = fd0.shift(1)                                                     # H.15 sai no dia seguinte: SINAL com 1 dia de defasagem
    fm = _ld("icj_fred_m")
    px = pd.concat([ETF, _ld("icj_yahoo")], axis=1)
    px = px.loc[:, ~px.columns.duplicated()].reindex(DIAS_US).ffill(limit=5)
    r = limpa(px.pct_change(fill_method=None))
    caixa = BIS.reindex(DIAS_US).ffill() / 100 / 252
    rx = r.sub(TB_US, axis=0)
    for t, moeda in (("INXG.L", "GB"), ("IHYG.L", "XM"), ("IEAC.L", "XM")):       # ETFs em libra/euro: excesso sobre o caixa local (= hedge cambial)
        rx[t] = r[t] - caixa[moeda]
    _CACHE.update(fd=fd, fd0=fd0, fm=fm, px=px, rx=rx, caixa=caixa, boe=_ld("icj_boe_real").reindex(DIAS_US).ffill(limit=5).shift(1),
                  cpi=_ld("icj_cpi"))
    return _CACHE


def mes_disp(s, meses=1):
    """Série mensal (data = 1º dia do mês de referência) -> diária, disponível só a partir do início do mês m+meses."""
    s = s.copy()
    s.index = s.index + pd.offsets.MonthBegin(meses)
    return s.reindex(DIAS_US.union(s.index)).ffill().reindex(DIAS_US)


def ust(y, T):
    """Excesso diário (sobre o T-bill) de um Treasury sintético de prazo T a partir da taxa par FRED (%): carry - D*dy + conv."""
    yy = y / 100
    Dm = (1 - (1 + yy / 2) ** (-2 * T)) / yy.clip(lower=1e-4)
    dy = yy.diff()
    return (yy.shift(1) / 252 - Dm.shift(1) * dy + .5 * Dm.shift(1) ** 2 * dy ** 2 - TB_US).fillna(0), Dm


def estado(entra, sai):
    """1 enquanto a posição está aberta: abre quando `entra`, fecha quando `sai` (avaliados com informação de t)."""
    e, s = entra.fillna(False).values, sai.fillna(False).values
    x, on = np.zeros(len(e)), False
    for i in range(len(e)):
        on = (not s[i]) if on else bool(e[i])
        x[i] = on
    return pd.Series(x, index=entra.index)


def estado2(ent_c, ent_v, sai_c, sai_v):
    """+1 / -1 / 0 com histerese."""
    a, b, c, d = (z.fillna(False).values for z in (ent_c, ent_v, sai_c, sai_v))
    x, pos = np.zeros(len(a)), 0
    for i in range(len(a)):
        if pos == 1 and c[i]:
            pos = 0
        elif pos == -1 and d[i]:
            pos = 0
        if pos == 0:
            pos = 1 if a[i] else -1 if b[i] else 0
        x[i] = pos
    return pd.Series(x, index=ent_c.index)


def fecha(W, R, cst, lag, custo_mult, detalhe, alav=.005, aluguel=0.0, extra=None):
    """Mesma conta do `carteira` (decide em t, executa em t+1+lag), por ativo. Excesso em USD -> R$ com hedge (brl).
    alav: custo a.a. sobre o bruto acima de 100% do PL (0 para pernas em futuros). extra: P&L diário adicional em USD (hedge de cauda)."""
    W = W.reindex(R.index).fillna(0)
    C, Wh, al = af.partes(W, R, cst, lag, custo_mult)
    al = al / .005 * alav
    C = C - Wh.clip(upper=0).abs() * aluguel / 252
    if extra is not None:
        C["hedge_cauda"] = extra.reindex(C.index).fillna(0).shift(lag).fillna(0)
    tot = C.sum(axis=1) - al
    e = brl(tot)
    if not detalhe:
        return e
    contrib = C.apply(brl)
    contrib["custo_alavancagem"] = -brl(al)
    Rr = R.copy()
    if extra is not None:
        Rr["hedge_cauda"] = 0.0
        Wh = Wh.assign(hedge_cauda=(C["hedge_cauda"] != 0).astype(float))
    return e, contrib, af.episodios(Wh, C, Rr)


# ======================================================================= I1 juro real de valor (TIPS / linkers)
VEIC = {"EUA-TIP": {"TIP": 1.0}, "EUA-LTPZ": {"LTPZ": .35}, "EUA+UK": {"TIP": .5, "INXG.L": .175}}
NIVEL = {"n1": {"US": 1.0, "UK": 0.0}, "n2": {"US": 2.0, "UK": 1.0}}       # linkers UK (RPI) têm juro real ~1 pp abaixo por causa da cunha RPI-CPI


def _sinal_real(s, regra, pais):
    if regra in NIVEL:
        thr = NIVEL[regra][pais]
        return estado(s > thr, s < thr - 1.0)                            # como o JF1: entra no extremo, sai 1 pp abaixo
    q = int(regra[1:]) / 100
    hi = s.rolling(1260, min_periods=750).quantile(q)
    med = s.rolling(1260, min_periods=750).median()
    return estado(s > hi, s < med)


def juro_real(regra="n2", mercado="EUA-TIP", custo_mult=1, lag=0, detalhe=False):
    """Compra duração real quando o juro real de 10 anos está no extremo (nível ou percentil de 5 anos); financiado a T-bill/caixa local."""
    I = ins()
    sinais = {"US": I["fd"].DFII10, "UK": I["boe"].UK_REAL10}
    W = pd.DataFrame(index=DIAS_US)
    for t, w in VEIC[mercado].items():
        W[t] = _sinal_real(sinais["UK" if t.endswith(".L") else "US"], regra, "UK" if t.endswith(".L") else "US") * w
    R = I["rx"][W.columns].fillna(0)
    return fecha(W, R, C_UST, lag, custo_mult, detalhe)


# ======================================================================= I2 inflação implícita x expectativas
H_TIP = 7.0 / 7.7                                                         # duration TIP / IEF: DV01 neutro


def inflacao(lado="vende", z_in=1.0, ancora="cleveland", custo_mult=1, lag=0, detalhe=False):
    """gap = breakeven 5a (T5YIE) - expectativa (Cleveland Fed 5a, ou Michigan 1a), z de 3 anos.
    vende: gap alto -> vende inflação (vendido TIP, comprado IEF DV01-neutro); ambos: também compra quando z < -z_in;
    segue: o contrário (o gap é informação, lição do JF2)."""
    I = ins()
    exp = mes_disp(I["fm"]["EXPINF5YR" if ancora == "cleveland" else "MICH"].dropna())
    gap = I["fd"].T5YIE - exp
    z = (gap - gap.rolling(756, min_periods=500).mean()) / gap.rolling(756, min_periods=500).std()
    s = -1 if lado != "segue" else 1
    ent_alto, ent_baixo = z > z_in, z < -z_in
    if lado == "vende":
        pos = -estado(ent_alto, z < 0)
    elif lado == "ambos":
        pos = estado2(ent_baixo, ent_alto, z > 0, z < 0)
    else:
        pos = estado2(ent_alto, ent_baixo, z < 0, z > 0)
    R = pd.DataFrame({"breakeven": I["rx"].TIP - H_TIP * I["rx"].IEF}).fillna(0)
    W = pd.DataFrame({"breakeven": pos * 1.5})
    return fecha(W, R, C_UST * (1 + H_TIP), lag, custo_mult, detalhe, alav=.0025)


# ======================================================================= I3 prêmio do 2 anos sobre o fed funds
def premio_2a(thr=1.0, filtro=1, lado="recebe", custo_mult=1, lag=0, detalhe=False):
    """Prêmio = DGS2 - fed funds efetivo. Acima de thr: o mercado cobra demais por proteção contra alta -> recebe 2 anos (comprado no
    Treasury de 2 anos sintético, 2x o PL = DV01 de ~4 anos). Sai abaixo de thr/3. filtro=1: não recebe se o breakeven 5a subiu > 25 bps
    em 3 meses (choque de inflação = BC atrás da curva; lição do JF3, 2021/2024 no Brasil). ambos: paga quando o prêmio < -thr (cortes demais)."""
    I = ins()
    fd = I["fd"]
    p = fd.DGS2 - fd.DFF
    choque = (fd.T5YIE - fd.T5YIE.shift(63)) > .25 if filtro else pd.Series(False, index=p.index)
    if lado == "recebe":
        pos = estado((p > thr) & ~choque, (p < thr / 3) | choque)
    else:
        pos = estado2((p > thr) & ~choque, p < -thr, (p < thr / 3) | choque, p > -thr / 3)
    r2, _ = ust(I["fd0"].DGS2, 2)
    R = pd.DataFrame({"UST2": r2})
    W = pd.DataFrame({"UST2": pos * 2.0})
    return fecha(W, R, C_FUT, lag, custo_mult, detalhe, alav=0)


# ======================================================================= I4 inclinação 2s10s pelo ciclo do Fed
def inclinacao(sinal="esperado", thr=.5, lado="ambos", custo_mult=1, lag=0, detalhe=False):
    """Steepener (comprado 2a, vendido 10a, DV01 neutro, DV01 de 5 anos por PL) quando o ciclo é de corte; flattener quando é de alta.
    esperado: DGS1 - DFF (< -thr = cortes precificados); realizado: variação do fed funds em 6 meses."""
    I = ins()
    fd = I["fd"]
    c = (fd.DGS1 - fd.DFF) if sinal == "esperado" else (fd.DFF - fd.DFF.shift(126))
    pos = estado2(c < -thr, c > thr, c > -thr / 2, c < thr / 2)
    if lado == "so_steep":
        pos = pos.clip(lower=0)
    r2, D2 = ust(I["fd0"].DGS2, 2)
    r10, D10 = ust(I["fd0"].DGS10, 10)
    R = pd.DataFrame({"steepener": (r2 / D2.shift(1) - r10 / D10.shift(1)) * 5}).fillna(0)   # por unidade de DV01 de 5 anos
    W = pd.DataFrame({"steepener": pos})
    return fecha(W, R, C_FUT * 2, lag, custo_mult, detalhe, alav=0)


# ======================================================================= I5 crédito HY EUA/Europa/EM: carry e pânico
UNIV_HY = {"hy_eua": ["HYG", "JNK"], "hy_global": ["HYG", "JNK", "IHYG.L", "EMHY"], "anjos": ["ANGL"]}


def _hedgeado(cols):
    """Retorno de crédito sem juro: ETF - beta móvel (126d, defasado, 0-1) x IEF (perna em futuro de Treasury)."""
    rx = ins()["rx"]
    out = {}
    for c in cols:
        r = rx[c]
        b = (r.rolling(126, min_periods=60).cov(rx.IEF) / rx.IEF.rolling(126, min_periods=60).var()).shift(1).clip(0, 1).fillna(.5)
        out[c] = (r - b * rx.IEF).where(r.notna())
    return pd.DataFrame(out)


def credito(modo="carry", universo="hy_eua", custo_mult=1, lag=0, detalhe=False):
    """carry: sempre comprado, peso igual (o 'índice' de crédito com hedge, como o C3/índice EW do Brasil);
    carry_faca: sai quando o índice hedgeado caiu nos últimos 63 dias (filtro de faca caindo — no Brasil piorou);
    panico: só compra quando o índice hedgeado está > 6% abaixo do máximo de 1 ano (mar/2020, 2022, 2015-16) e segura até voltar a -1%
    ou 1 ano; panico+carry: 50% sempre + 100% adicional no pânico."""
    R = _hedgeado(UNIV_HY[universo])
    idx = np.exp(np.log1p(R.mean(axis=1).fillna(0)).cumsum())
    dd = idx / idx.rolling(252, min_periods=126).max() - 1
    disp = R.notna().astype(float)
    base = disp.div(disp.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    if modo == "carry":
        k = pd.Series(1.0, index=R.index)
    elif modo == "carry_faca":
        k = (np.log(idx) - np.log(idx).shift(63) > 0).astype(float)
    else:
        pan = estado(dd < -.06, dd > -.01)
        dur = pan.groupby((pan.diff() != 0).cumsum()).cumcount()
        pan = pan.where(dur < 252, 0)                                     # prazo máximo de 1 ano por episódio
        k = pan * 1.0 if modo == "panico" else .5 + pan
    W = mensal(base.mul(k, axis=0)) if modo == "carry" else base.mul(k, axis=0)
    return fecha(W, R.fillna(0), C_HY + C_FUT, lag, custo_mult, detalhe)


# ======================================================================= I6 crédito antecipa ação (só vendido)
def credito_acao(x=.015, alvo="IWM", h=21, custo_mult=1, lag=0, detalhe=False):
    """O mercado de crédito vê o problema antes: índice HY hedgeado (HYG/JNK - beta IEF) caiu mais que x em 21 dias e a ação ainda não
    (alvo > -2% em 21d) -> vende o alvo (IWM: small caps alavancadas, ou SPY) por h dias. Só o lado vendido (o C6 brasileiro só funcionou assim)."""
    I = ins()
    R0 = _hedgeado(["HYG", "JNK"]).mean(axis=1).fillna(0)
    cred21 = np.exp(np.log1p(R0).rolling(21).sum()) - 1
    eq21 = I["px"][alvo] / I["px"][alvo].shift(21) - 1
    gat = (cred21 < -x) & (eq21 > -.02)
    pos = gat.astype(float).rolling(h, min_periods=1).max()                # fica vendido h dias após o último gatilho
    R = I["rx"][[alvo]].fillna(0)
    W = pd.DataFrame({alvo: -pos * .5})                                   # 50% do PL vendido
    return fecha(W, R, C_UST, lag, custo_mult, detalhe, aluguel=.005)


# ======================================================================= I7 eurobonds BR em stress (safra)
def _eb_gatilho(I):
    """Stress sistêmico do HY BR em dólar: spread mediano dos bonds corporativos negociados (preço 50-110) abriu > 75 bps em 3 meses
    ou está acima do percentil 80 desde 2019 (dado mensal; vale a partir do mês seguinte)."""
    s = I["sprd"].copy()
    s.index = s.index.to_timestamp() if hasattr(s.index, "to_timestamp") else pd.to_datetime(s.index)
    P = I["PE"]
    pm = P.resample("MS").last().reindex(s.index)
    sob = [c for c in s.columns if "Government" in str(I["nome"].get(c, ""))]
    corp = s.drop(columns=sob, errors="ignore").where((pm >= 50) & (pm <= 110))
    med = corp.median(axis=1)
    ev = ((med - med.shift(3)) > .75) | (med > med.expanding(12).quantile(.8))
    ev.index = ev.index + pd.offsets.MonthBegin(1)
    return ev.reindex(pd.DatetimeIndex(I["dias"]).union(ev.index)).ffill().reindex(I["dias"]).fillna(False).astype(bool), med


def _eb_livro(gatilho="evento", lo=40, hi=80, n=10, saida=97, prazo=504, custo_mult=1):
    """Compra-e-segura (sem venda por 'sumiu': marca no último preço). Entrada em bonds com preço entre lo e hi, 1 por emissor, n vagas
    de 1/n do PL; sai em >= saida ou após prazo dias úteis. gatilho=evento: só compra nos 6 meses seguintes a um stress sistêmico."""
    I = af.eb_insumos()
    dias, P, X = I["dias"], I["PE"].ffill(limit=21), I["exc"]
    cols = np.array(X.columns)
    P = P.reindex(columns=cols)
    R, Pv = X.to_numpy(), P.to_numpy()
    em = np.array([I["emis"].get(c, c) for c in cols])
    ok_t = np.ones(len(dias), bool)
    if gatilho == "evento":
        ev, _ = _eb_gatilho(I)
        ok_t = ev.astype(float).rolling(126, min_periods=1).max().values > 0
    custo = I["custo"] * custo_mult
    val, info, Cm, out, nav, trades = {}, {}, np.zeros((len(dias), len(cols))), np.zeros(len(dias)), 1.0, []
    for t in range(1, len(dias)):
        i, cd = t - 1, 0.0
        for k in list(val):
            px = Pv[i, k]
            if (px == px and px >= saida) or t - info[k]["t0"] >= prazo or (np.isnan(Pv[max(i - 63, 0):i + 1, k]).all()):
                c_ = val.pop(k) * custo
                cd += c_
                Cm[t, k] -= c_ / nav
                a = info.pop(k)
                a.update(saida=dias[t], px_saida=px, motivo="par" if px >= saida else "prazo" if t - a["t0"] >= prazo else "sem preço 3m")
                trades.append(a)
        if ok_t[i] and len(val) < n:
            emis_h = {em[k] for k in val}
            cand = np.where((Pv[i] >= lo) & (Pv[i] <= hi) & ~np.isnan(R[i]))[0]
            for k in cand[np.argsort(Pv[i, cand])[::-1]]:                 # do mais alto para o mais baixo: stress, não falência
                livre = nav - sum(val.values())
                if len(val) >= n or livre <= 1e-9:
                    break
                if k in val or em[k] in emis_h:
                    continue
                val[k] = min(nav / n, livre)
                emis_h.add(em[k])
                cd += val[k] * custo
                Cm[t, k] -= val[k] * custo / nav
                info[k] = {"ativo": cols[k], "emissor": em[k], "entrada": dias[t], "px_entrada": Pv[i, k], "t0": t}
        g = 0.0
        for k in val:
            r = R[t, k] if not np.isnan(R[t, k]) else 0.0
            g += val[k] * r
            Cm[t, k] += val[k] * r / nav
            val[k] *= 1 + r
        out[t] = (g - cd) / nav
        nav *= 1 + out[t]
    for k, a in info.items():
        a.update(saida=dias[-1], px_saida=Pv[-1, k], motivo="em carteira")
        trades.append(a)
    C = pd.DataFrame(Cm, index=dias, columns=cols)
    T = pd.DataFrame(trades)
    if len(T):
        T["dias"] = [((dias > a) & (dias <= b)).sum() for a, b in zip(T.entrada, T.saida)]
        T["retorno %"] = (T.px_saida / T.px_entrada - 1) * 100
        T["contrib pp"] = [C.loc[(C.index >= a) & (C.index <= b), k].sum() * 100 for k, a, b in zip(T.ativo, T.entrada, T.saida)]
        T = T.drop(columns="t0")
    return pd.Series(out, index=dias), C.loc[:, C.abs().sum() > 0], T


def eurobonds(gatilho="evento", lo=40, hi=80, custo_mult=1, lag=0, detalhe=False):
    r, C, T = _eb_livro(gatilho, lo, hi, custo_mult=custo_mult)
    e = r.reindex(DIAS).fillna(0)
    e = e.shift(lag).fillna(0) if lag else e
    return (e, C.reindex(DIAS).fillna(0), T) if detalhe else e


# ======================================================================= I8 juros globais relativos (10 anos, mensal)
CAIXA_PAIS = {"US": "US", "DE": "XM", "FR": "XM", "IT": "XM", "ES": "XM", "GB": "GB", "JP": "JP", "CA": "CA", "AU": "AU", "CH": "CH",
              "SE": "SE", "NZ": "NZ", "NO": "NO"}
G7 = ["US", "DE", "GB", "JP", "CA", "FR", "IT"]


def juros_globais(sinal="carry", n=2, universo="G7", custo_mult=1, lag=0, detalhe=False):
    """Títulos de 10 anos com hedge cambial (excesso local = (y10 - caixa)/12 - D x dy), mensal (OECD/FRED: média do mês).
    Sinal com dado até o mês m (publicado em m+1), posição no mês m+2: o retorno usa médias de m+1 e m+2 — sem sobreposição.
    carry: inclinação local (y10 - juro de política); reversao: spread do país contra a média, z de 36 meses (spread largo -> compra);
    carry+reversao: soma dos postos. Comprado nos n melhores, vendido nos n piores, mesmo notional (duration ~ igual), 1x por perna."""
    I = ins()
    paises = G7 if universo == "G7" else PAISES_10A
    y = pd.DataFrame({p: I["fm"][f"IRLTLT01{p}M156N"] for p in paises}).dropna(how="all")
    y = y[y.index >= "2000-01-01"]
    pol = BIS.resample("MS").mean()
    cx = pd.DataFrame({p: pol[CAIXA_PAIS[p]] for p in paises}).reindex(y.index).ffill()
    yy = y / 100
    Dm = (1 - (1 + yy / 2) ** -20) / yy.clip(lower=1e-3)
    Rm = ((y.shift(1) - cx.shift(1)) / 1200 - Dm.shift(1) * yy.diff())    # retorno local em excesso do mês
    carry = (y - cx)
    spr = y.sub(y.mean(axis=1), axis=0)
    zr = (spr - spr.rolling(36, min_periods=24).mean()) / spr.rolling(36, min_periods=24).std()
    sc = {"carry": carry.rank(axis=1), "reversao": zr.rank(axis=1), "carry+reversao": carry.rank(axis=1) + zr.rank(axis=1)}[sinal]
    sc = sc.where(Rm.notna() & sc.notna())
    rk = sc.rank(axis=1, ascending=False, method="first")
    m = sc.notna().sum(axis=1)
    W = ((rk <= n).astype(float) - (rk > m.values[:, None] - n).astype(float).where(sc.notna(), 0)) / n
    W = W.shift(2).fillna(0)                                              # sinal de m -> posição em m+2
    custo = .0002 * custo_mult
    Cm = W * Rm.fillna(0) - W.diff().abs().fillna(0) * custo
    # mensal -> diário: o retorno do mês entra no último dia útil do mês (espalhar pelos dias subestimaria a vol em ~4,6x)
    mes = pd.Series(DIAS_US.to_period("M"), index=DIAS_US)
    ult = mes.ne(mes.shift(-1)).values
    Cm.index = Cm.index.to_period("M")
    Cd = pd.DataFrame({p: Cm[p].reindex(mes.values).values * ult for p in paises}, index=DIAS_US).fillna(0)
    Cd = Cd.shift(lag).fillna(0)
    e = brl(Cd.sum(axis=1))
    if not detalhe:
        return e
    Wd = pd.DataFrame(W.set_axis(W.index.to_period("M")).reindex(mes.values).values, index=DIAS_US, columns=W.columns).fillna(0)
    Rp = Rm.set_axis(Rm.index.to_period("M"))
    Rd = pd.DataFrame({p: Rp[p].reindex(mes.values).values * ult for p in paises}, index=DIAS_US).fillna(0)
    return e, Cd.apply(brl), af.episodios(Wd, Cd, Rd)


# ======================================================================= I9 carry G10+LatAm realista / real tático EM
LATAM = ["MXN=X", "BRL=X", "CLP=X", "COP=X"]
EM10 = ["MXN=X", "ZAR=X", "INR=X", "IDR=X", "KRW=X", "TRY=X", "CLP=X", "COP=X", "PLN=X", "HUF=X"]
G10 = ["EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X", "JPY=X", "CAD=X", "CHF=X", "NOK=X", "SEK=X"]


_FXC = []


def limpa_nivel(v, lim=.08, k_max=8):
    """Erros de cotação do Yahoo que duram mais de 1 dia (COP 04-05/jun/2015 = 26,2 em vez de 2.600, rendia +9.800% num dia; IDR
    nov-dez/2013; NOK 20/mar/2020; EURUSD 08/dez/2008): em log, zera o salto > lim que é desfeito em até k_max dias (|soma| < 15% do salto).
    O `limpa_fx` da base só pega reversão no dia seguinte. Desvalorizações de verdade (CHF jan/2015, TRY) ficam."""
    lr = np.log(v.ffill()).diff()
    for c in lr.columns:
        x = lr[c].to_numpy().copy()
        for i in range(1, len(x)):
            if np.isfinite(x[i]) and abs(x[i]) > lim:
                for k in range(1, k_max + 1):
                    if i + k < len(x) and abs(x[i] + np.nansum(x[i + 1:i + k + 1])) < .15 * abs(x[i]):
                        x[i:i + k + 1] = 0.0
                        break
        lr[c] = x
    return lr.where(v.notna()).pipe(np.expm1)


def _fx_limpo():
    if not _FXC:
        v, _, dif = fg._fx()
        _FXC.extend([v, limpa_nivel(v), dif])
    return _FXC


def _put_audjpy():
    """Put de 1 mês 5% fora do dinheiro em AUDJPY, comprada no fim de cada mês (Black-Scholes, vol = 1,15 x vol realizada de 63d,
    mínimo +1 pp: prêmio de vol implícita). Devolve (prêmio pago por unidade de notional na data de compra, payoff no vencimento)."""
    sp = _fx_limpo()[1]
    s = np.exp(np.log1p(((1 + sp["AUDUSD=X"]) / (1 + sp["JPY=X"]) - 1).fillna(0)).cumsum())   # AUDJPY (JPY=X já está em USD por JPY)
    rv = np.log(s).diff().rolling(63, min_periods=40).std() * np.sqrt(252)
    per = pd.Series(DIAS_US.to_period("M"), index=DIAS_US)
    fims = DIAS_US[per.ne(per.shift(-1)).values]
    premio, payoff = pd.Series(0.0, index=DIAS_US), pd.Series(0.0, index=DIAS_US)
    for a, b in zip(fims[:-1], fims[1:]):
        sig = max(rv.get(a, np.nan) * 1.15, rv.get(a, np.nan) + .01)
        if not np.isfinite(sig):
            continue
        T, K = 1 / 12, .95
        d1 = (np.log(1 / K) + .5 * sig ** 2 * T) / (sig * np.sqrt(T))
        premio[a] = K * norm.cdf(-(d1 - sig * np.sqrt(T))) - norm.cdf(-d1)
        payoff[b] = max(K - s[b] / s[a], 0)
    return premio, payoff


def carry_fx(sinal="carry", regime="nenhum", cauda=0, n=3, alvo=.08, teto=.2, custo_mult=1, lag=0, detalhe=False):
    """carry: G10+LatAm por diferencial nominal (BIS; NDF com 70% do carry). carry_real: G10+LatAm+EM10, não compra moeda com juro real
    negativo (TRY 2021-23; regra ex-ante do JF7). real_tatico: EM10, ranqueia o diferencial de juro real (política - CPI 12m BIS defasado
    2 meses, contra o dos EUA) pelo z de 5 anos (a VARIAÇÃO do juro real relativo, como o JF6). L/S n x n, inverso da vol, vol-alvo 8%,
    teto 20% por moeda DEPOIS do vol-alvo, mensal. regime vix_contango: zera com VIX > VIX3M. cauda: put AUDJPY sobre o comprado."""
    I = ins()
    v, spot, dif = _fx_limpo()
    pol = BIS.reindex(DIAS_US).ffill()
    cpi = mes_disp(I["cpi"], 2)
    real = pd.DataFrame({k: (pol[c] - cpi[c]) - (pol["US"] - cpi["US"]) for k, (c, s) in fg.MOEDA.items()
                         if c in cpi and c in pol}).reindex(DIAS_US) / 100
    univ = {"carry": G10 + LATAM, "carry_real": G10 + [m for m in dict.fromkeys(LATAM + EM10)], "real_tatico": EM10}[sinal]
    cols = [c for c in univ if c in dif]
    if sinal == "real_tatico":
        sc = (real[cols] - real[cols].rolling(1260, min_periods=750).mean()) / real[cols].rolling(1260, min_periods=750).std()
    else:
        sc = dif[cols].copy()
    if sinal == "carry_real":
        sc = sc.where(~((real[cols] < 0) & (sc.rank(axis=1, ascending=False) <= n)), np.nan)   # não entra comprado com juro real < 0
    R = (spot[cols] + dif[cols].shift(1) / 252)
    rk = sc.rank(axis=1, ascending=False)
    m = sc.notna().sum(axis=1)
    W = (rk <= n).astype(float) - ((rk > m.values[:, None] - n) & sc.notna()).astype(float)
    vol = spot[cols].rolling(63, min_periods=40).std()
    W = (W / vol).div((W / vol).abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    W = mensal(vol_alvo(W, R.fillna(0), alvo)).clip(-teto, teto)
    if regime == "vix_contango":
        vx, v3 = IDX["^VIX"].reindex(DIAS_US).ffill(), IDX["^VIX3M"].reindex(DIAS_US).ffill()
        W = W.mul((vx <= v3).astype(float).shift(0), axis=0)
    extra = None
    if cauda:
        premio, payoff = _put_audjpy()
        notional = W.clip(lower=0).sum(axis=1)
        nt = notional.reindex(DIAS_US).fillna(0)
        fims = premio[premio != 0].index
        noc = pd.Series(np.nan, index=DIAS_US)
        noc[fims] = nt[fims]
        noc = noc.ffill().fillna(0)
        extra = -premio * nt + payoff * noc.shift(1).fillna(0)          # paga no fim do mês a, recebe no fim do mês b sobre o notional de a
    cst = pd.Series({c: C_G10 if c in G10 else (.003 if c == "TRY=X" else C_EM) for c in cols})
    return fecha(W, R.fillna(0), cst, lag, custo_mult, detalhe, extra=extra)


# ======================================================================= fundos
FUNDOS = [
    Fundo("I1 Juro real de valor (TIPS/linkers)", "Juros global", "CDI",
          "Juro real de 10 anos no extremo (nível vs neutro ou percentil de 5 anos) é prêmio de risco/fiscal que volta: compro duração real e espero",
          "TIP (1x), LTPZ (0,35x) ou TIP+INXG (UK, sinal na curva real do BoE); sai 1 pp abaixo (nível) ou na mediana (percentil); hedge cambial",
          juro_real, {"regra": ["n1", "n2", "p80", "p90"], "mercado": list(VEIC)}, inicio="2010-01-01"),
    Fundo("I2 Inflação implícita x expectativas (EUA)", "Juros global", "CDI",
          "Breakeven 5a muito acima do que a pesquisa (Cleveland/Michigan) espera = prêmio de inflação caro -> vendo inflação; ou o contrário (o gap é informação)",
          "TIP vendido x IEF comprado DV01-neutro (1,5x), z de 3 anos do gap", inflacao,
          {"lado": ["vende", "ambos", "segue"], "z_in": [1.0, 1.5], "ancora": ["cleveland", "mich"]}, inicio="2010-01-01"),
    Fundo("I3 Prêmio do 2 anos x fed funds", "Juros global", "CDI",
          "Quando o 2 anos paga muito acima do fed funds o mercado está pagando demais por proteção contra alta: recebo (exceto em choque de inflação)",
          "Treasury 2a sintético (taxa FRED), 2x o PL, futuros", premio_2a, {"thr": [.5, 1.0], "filtro": [0, 1], "lado": ["recebe", "ambos"]},
          inicio="2010-01-01"),
    Fundo("I4 Inclinação 2s10s pelo ciclo do Fed", "Juros global", "CDI",
          "Ciclo de corte inclina a curva, ciclo de alta achata: steepener/flattener DV01-neutro pelo ciclo esperado (DGS1-DFF) ou realizado",
          "2a x 10a sintéticos, DV01 de 5 anos por PL, futuros", inclinacao,
          {"sinal": ["esperado", "realizado"], "thr": [.25, .5], "lado": ["ambos", "so_steep"]}, inicio="2010-01-01"),
    Fundo("I5 Crédito HY: carry e pânico (EUA/Europa/EM)", "Crédito global", "CDI",
          "O prêmio de crédito existe (índice EW brasileiro +2,3 pp); comprar HY com hedge de Treasury sempre, só no pânico, ou nos fallen angels",
          "HYG/JNK, +IHYG.L/EMHY, ou ANGL; hedge de beta em IEF (futuro); pânico = índice hedgeado > 6% abaixo do máximo de 1 ano",
          credito, {"modo": ["carry", "carry_faca", "panico", "panico+carry"], "universo": list(UNIV_HY)}, inicio="2010-01-01"),
    Fundo("I6 Crédito antecipa ação (vendido, EUA)", "Long-short", "CDI",
          "O mercado de HY vê o problema antes da bolsa: crédito hedgeado caindo e ação parada -> vendo small caps/S&P",
          "50% do PL vendido em IWM ou SPY por h dias, aluguel 0,5%", credito_acao,
          {"x": [.015, .025], "alvo": ["IWM", "SPY"], "h": [21, 63]}, inicio="2010-01-01"),
    Fundo("I7 Eurobonds BR em stress (safra)", "Crédito", "CDI",
          "No stress sistêmico o mercado vende a 60-80 empresas que não quebram: compro a safra com hedge de câmbio e Treasury e carrego até o par",
          "Até 10 bonds, 1 por emissor, preço entre lo e hi, compra-e-segura até 97 ou 2 anos; gatilho = spread mediano abriu ou no p80", eurobonds,
          {"gatilho": ["evento", "sempre"], "lo": [40, 60], "hi": [80, 85]}, inicio="2019-06-01", corte="2023-01-01"),
    Fundo("I8 Juros globais relativos (10 anos)", "Juros global", "CDI",
          "Carry (inclinação local) e reversão do spread entre países: comprado no 10 anos que paga mais/está barato, vendido no caro, com hedge cambial",
          "G7 ou 13 países, n x n, mensal (OECD), 1x por perna", juros_globais,
          {"sinal": ["carry", "reversao", "carry+reversao"], "n": [2, 3], "universo": ["G7", "todos"]}, inicio="2010-01-01"),
    Fundo("I9 Carry de moedas realista / real tático EM", "Macro", "CDI",
          "Carry G10+LatAm é o prêmio que pagou na atribuição; com regime (VIX em contango), sem juro real negativo e com put de AUDJPY; ou o real tático em 10 EM",
          "n=3 x 3, inverso da vol, vol-alvo 8%, teto 20% depois do vol-alvo, mensal; custo G10 2 bps, EM 15 bps, TRY 30 bps", carry_fx,
          {"sinal": ["carry", "carry_real", "real_tatico"], "regime": ["nenhum", "vix_contango"], "cauda": [0, 1]}, inicio="2010-01-01"),
]


def detalhe(f, p):
    r = f.func(**p, detalhe=True)
    return r[1], r[2]


if __name__ == "__main__":
    if sys.argv[1:] == ["dados"]:
        baixa()
        sys.exit()
    from rodar import BENCH
    so = sys.argv[1:]
    res = []
    for f in FUNDOS:
        if so and f.nome.split()[0] not in so:
            continue
        r = roda(f, CDI, BENCH[f.benchmark], print)
        if r is None:
            print(f.nome, "sem resultado")
            continue
        o, rb = r["oos"], r["rob"]
        print(f"{f.nome}: {r['params']} | IR IS {r['is_ir']:.2f} | OOS {o['retorno a.a. %']:.1f}% vs {o['benchmark a.a. %']:.1f}% (IR {o['IR vs bench']:.2f}) | "
              f"vol {o['vol a.a. %']:.1f} DD {o['pior queda %']:.1f} | P(bater) {rb['P(bater bench OOS) %']:.0f}% | PBO {rb['PBO %']:.0f}% | "
              f"custo x2 {rb['OOS custo x2 (pp)']:.2f} | +1 dia {rb['OOS execução +1 dia (pp)']:.2f} | mediana var {rb['mediana OOS das variantes (pp)']:.2f} "
              f"| %var>bench {rb['% variantes > bench OOS']:.0f}", flush=True)
        r["contrib"], r["trades"] = detalhe(f, r["params"])
        r["fundo"].func = None
        res.append(r)
    if not so:
        pickle.dump(res, open(OUT / "ideias_i_credito_juros.pkl", "wb"))
    print("pronto")
