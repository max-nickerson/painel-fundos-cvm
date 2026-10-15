"""
Frente GLOBAL — eventos, fluxo e mercados de fronteira (rodada 2).
  python ideias_global.py dados   -> baixa/atualiza os dados novos (cache em dados/, nunca re-baixa)
  python ideias_global.py         -> roda os fundos e salva resultado/ideias_global.pkl
Fontes: SEC EDGAR (índices form.gz, Form 3/4/5 data sets), yfinance. User-Agent genérico de pesquisa.
"""
import gzip
import io
import pickle
import re
import sys
import time
import zipfile

import numpy as np
import pandas as pd
import requests

from base import CDI, DIAS, DIAS_US, ETF, FXY, IDX, TB_US, brl, carteira, limpa, mensal, semanal, D

H = {"User-Agent": "pesquisa-quant contato@example.com"}
SEC = "https://www.sec.gov"
_ult = [0.0]


def _get(url, tent=6, **kw):
    for t in range(tent):
        espera = .12 - (time.time() - _ult[0])                     # <= ~8 req/s
        if espera > 0:
            time.sleep(espera)
        _ult[0] = time.time()
        try:
            r = requests.get(url, headers=H, timeout=180, **kw)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(3 * (t + 1))
    return None


# =============================================================== DADOS
FORMAS = {"SC TO-T", "SC TO-T/A", "SC 14D9", "DEFM14A", "PREM14A", "10-12B", "10-12B/A", "SC 13E3", "DEFM14C", "S-4", "25-NSE", "15-12B", "15-12G", "15-15D", "SC TO-C", "SC 14D9-C"}


def baixa_indices(ini=2006):
    """EDGAR full-index (form.gz) -> só as formas de eventos corporativos. dados/sec_indice.parquet"""
    f = D / "sec_indice.parquet"
    velho = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["forma", "nome", "cik", "data", "arq", "trim"])
    feitos = set(velho.trim)
    hoje = pd.Timestamp.today()
    novos = []
    for a in range(ini, hoje.year + 1):
        for q in range(1, 5):
            tq = f"{a}Q{q}"
            if pd.Timestamp(a, 3 * q - 2, 1) > hoje or (tq in feitos and pd.Timestamp(a, 3 * q, 28) < hoje - pd.Timedelta(days=10)):
                continue
            r = _get(f"{SEC}/Archives/edgar/full-index/{a}/QTR{q}/form.gz")
            if r is None:
                continue
            linhas = gzip.decompress(r.content).decode("latin-1").splitlines()
            for l in linhas:
                fm = l[:17].strip()
                if fm in FORMAS:
                    p = l[17:].rsplit(None, 3)
                    if len(p) == 4:
                        novos.append((fm, p[0].strip(), int(p[1]), p[2], p[3], tq))
            print("indice", tq, len(novos), flush=True)
    if novos:
        n = pd.DataFrame(novos, columns=["forma", "nome", "cik", "data", "arq", "trim"])
        velho = pd.concat([velho[~velho.trim.isin(n.trim.unique())], n])
        velho["data"] = pd.to_datetime(velho.data)
        velho.to_parquet(f)
    return velho


def baixa_form345(ini=2006):
    """Insider Transactions Data Sets: compras em mercado aberto (código P) + mapa CIK->ticker do emissor.
    dados/sec_insider_compras.parquet, dados/sec_emissores.parquet"""
    fc, fe = D / "sec_insider_compras.parquet", D / "sec_emissores.parquet"
    comp = pd.read_parquet(fc) if fc.exists() else pd.DataFrame()
    emi = pd.read_parquet(fe) if fe.exists() else pd.DataFrame()
    feitos = set(comp.trim) if len(comp) else set()
    pag = _get(f"{SEC}/dera/data/form-345").text
    links = sorted(set(re.findall(r'href="([^"]+?(\d{4}q\d)_form345\.zip)"', pag)), key=lambda x: x[1])
    for url, tq in links:
        if int(tq[:4]) < ini or tq in feitos:
            continue
        r = _get(SEC + url)
        if r is None:
            print("falhou", tq)
            continue
        z = zipfile.ZipFile(io.BytesIO(r.content))
        rd = lambda n, c: pd.read_csv(z.open(n), sep="\t", dtype=str, usecols=c, quoting=3, on_bad_lines="skip")
        sub = rd("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK", "ISSUERNAME", "ISSUERTRADINGSYMBOL"])
        sub["FILING_DATE"] = pd.to_datetime(sub.FILING_DATE, format="%d-%b-%Y", errors="coerce")
        e = sub.groupby(["ISSUERCIK", "ISSUERTRADINGSYMBOL"]).agg(nome=("ISSUERNAME", "last"), d0=("FILING_DATE", "min"),
                                                                  d1=("FILING_DATE", "max"), n=("ACCESSION_NUMBER", "size")).reset_index()
        e["trim"] = tq
        nt = rd("NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE",
                                       "TRANS_ACQUIRED_DISP_CD", "SHRS_OWND_FOLWNG_TRANS", "DIRECT_INDIRECT_OWNERSHIP"])
        nt = nt[nt.TRANS_CODE == "P"]
        own = rd("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"])
        own = own.groupby("ACCESSION_NUMBER").first().reset_index()                 # 1 dono por formulário (o 1º)
        c = nt.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER", how="left")
        c["trim"] = tq
        comp = pd.concat([comp, c])
        emi = pd.concat([emi, e])
        comp.to_parquet(fc)
        emi.to_parquet(fe)
        print("form345", tq, len(c), len(comp), flush=True)
    return comp, emi


def cik_ticker():
    """CIK -> (ticker, d0, d1) usando os tickers que os próprios insiders informaram (inclui empresas já deslistadas)."""
    e = pd.read_parquet(D / "sec_emissores.parquet")
    e["cik"] = e.ISSUERCIK.astype(int)
    e["tk"] = e.ISSUERTRADINGSYMBOL.str.upper().str.strip().str.replace(".", "-", regex=False)
    e = e[e.tk.str.fullmatch(r"[A-Z][A-Z\-]{0,5}", na=False) & ~e.tk.isin(["NONE", "NA", "N-A"])]
    return e.groupby(["cik", "tk"]).agg(d0=("d0", "min"), d1=("d1", "max"), n=("n", "sum")).reset_index()


def baixa_precos(tickers, nome, ini="2005-01-01", extra=None, lote_n=100, pausa=0):
    """yfinance em lotes, com cache por ticker já tentado (dados/y_<nome>.parquet + y_<nome>_tentados.txt)."""
    import yfinance as yf
    f, ft = D / f"y_{nome}.parquet", D / f"y_{nome}_tentados.txt"
    P = pd.read_parquet(f) if f.exists() else pd.DataFrame()
    tent = set(ft.read_text().split()) if ft.exists() else set()
    falta = [t for t in dict.fromkeys(tickers) if t not in tent]
    campos = extra or ["Close"]
    for i in range(0, len(falta), lote_n):
        lote = falta[i:i + lote_n]
        time.sleep(pausa)
        try:
            d = yf.download(lote, start=ini, progress=False, auto_adjust=True, threads=True, group_by="column")
        except Exception as ex:
            print("erro yf", ex)
            continue
        if len(d):
            if len(campos) == 1:
                x = d[campos[0]] if isinstance(d.columns, pd.MultiIndex) else d[[campos[0]]].set_axis(lote, axis=1)
            else:
                x = d[campos] if isinstance(d.columns, pd.MultiIndex) else pd.concat({c: d[[c]].set_axis(lote, axis=1) for c in campos}, axis=1)
                x.columns = [f"{t}|{c}" for c, t in x.columns]
            x = x.dropna(axis=1, how="all")
            P = pd.concat([P, x[[c for c in x.columns if c not in P.columns]]], axis=1)
        try:
            from yfinance import shared
            lim = {t for t, e in shared._ERRORS.items() if "RateLimit" in str(e) or "Too Many" in str(e)}
        except Exception:
            lim = set()
        tent |= set(lote) - lim
        if len(lim & set(lote)) > len(lote) / 2:
            print("limitado pelo Yahoo; esperando 120 s", flush=True)
            time.sleep(120)
        P.to_parquet(f.with_suffix(".tmp"))
        f.with_suffix(".tmp").replace(f)                                   # escrita atômica (processo interrompido não corrompe o cache)
        ft.write_text(" ".join(sorted(tent)))
        print(nome, i + len(lote), "/", len(falta), P.shape, flush=True)
    return P


FRONT = ["GREK", "EGPT", "NGE", "PAK", "GXG", "ICOL", "FM", "FRN", "EPOL", "EWM", "UAE", "KWT", "ERUS", "RSX", "EIS", "NORW", "ENZL", "ECNS",
         "VNM", "AFK", "KSA", "QAT", "ARGT", "TUR", "EIDO", "EPHE", "EPU", "ECH", "EZA", "INDA", "THD", "EWZ", "EWW", "MNA", "MRGR", "IWM", "SPY",
         "ARS=X", "EGP=X", "NGN=X", "PKR=X", "VND=X", "TRY=X", "SAR=X", "COP=X", "PEN=X", "PHP=X", "IDR=X", "INR=X", "THB=X", "MYR=X", "PLN=X",
         "CLP=X", "ZAR=X", "MXN=X", "BRL=X"]
# ADR -> (ação local, moeda Yahoo por USD (None = local em USD), imposto/custo extra por ida-e-volta intradiária em bps)
PARES = {"TSM": ("2330.TW", "TWD=X", 15), "BABA": ("9988.HK", "HKD=X", 26), "JD": ("9618.HK", "HKD=X", 26), "BIDU": ("9888.HK", "HKD=X", 26),
         "NTES": ("9999.HK", "HKD=X", 26), "INFY": ("INFY.NS", "INR=X", 5), "WIT": ("WIPRO.NS", "INR=X", 5), "HDB": ("HDFCBANK.NS", "INR=X", 5),
         "IBN": ("ICICIBANK.NS", "INR=X", 5), "RDY": ("DRREDDY.NS", "INR=X", 5), "TM": ("7203.T", "JPY=X", 0), "SONY": ("6758.T", "JPY=X", 0),
         "MUFG": ("8306.T", "JPY=X", 0), "HMC": ("7267.T", "JPY=X", 0), "SMFG": ("8316.T", "JPY=X", 0), "NMR": ("8604.T", "JPY=X", 0),
         "KB": ("105560.KS", "KRW=X", 20), "SHG": ("055550.KS", "KRW=X", 20), "PKX": ("005490.KS", "KRW=X", 20),
         "ASML": ("ASML.AS", "EURUSD=X", 0), "SAP": ("SAP.DE", "EURUSD=X", 0), "NVO": ("NOVO-B.CO", "DKK=X", 0), "SNY": ("SAN.PA", "EURUSD=X", 30),
         "TTE": ("TTE.PA", "EURUSD=X", 30), "BP": ("BP.L", "GBPUSD=X", 50), "SHEL": ("SHEL.L", "GBPUSD=X", 50), "AZN": ("AZN.L", "GBPUSD=X", 50),
         "GSK": ("GSK.L", "GBPUSD=X", 50), "UL": ("ULVR.L", "GBPUSD=X", 50), "HSBC": ("HSBA.L", "GBPUSD=X", 50), "NVS": ("NOVN.SW", "CHF=X", 0),
         "UBS": ("UBSG.SW", "CHF=X", 0), "ING": ("INGA.AS", "EURUSD=X", 0), "PHG": ("PHIA.AS", "EURUSD=X", 0), "E": ("ENI.MI", "EURUSD=X", 10),
         "SAN": ("SAN.MC", "EURUSD=X", 20), "BBVA": ("BBVA.MC", "EURUSD=X", 20), "ERIC": ("ERIC-B.ST", "SEK=X", 0), "NOK": ("NOKIA.HE", "EURUSD=X", 0),
         "EQNR": ("EQNR.OL", "NOK=X", 0)}
ARG = {"YPF": "YPFD.BA", "GGAL": "GGAL.BA", "BMA": "BMA.BA", "PAM": "PAMP.BA", "TEO": "TECO2.BA", "CRESY": "CRES.BA", "LOMA": "LOMA.BA",
       "SUPV": "SUPV.BA", "TGS": "TGSU2.BA", "CEPU": "CEPU.BA", "EDN": "EDN.BA", "IRS": "IRSA.BA", "BBAR": "BBAR.BA"}                    # TX (Ternium SA) x TXAR.BA (Ternium Argentina) NÃO é o mesmo papel: removido


# =============================================================== MOTOR LOCAL (custos por ativo + detalhe por negócio)
C_ETF = .0003


def cart(W, R, custo, lag=0, aluguel=0.0):
    """Igual a base.carteira, mas com custo/aluguel por ativo (dict) e devolvendo a contribuição por ativo e os pesos executados."""
    W = W.reindex(R.index).fillna(0).shift(1 + lag).fillna(0)
    c = custo if np.isscalar(custo) else pd.Series(custo).reindex(W.columns).fillna(max(custo.values()))
    al = aluguel if np.isscalar(aluguel) else pd.Series(aluguel).reindex(W.columns).fillna(0)
    contrib = (W.shift(1) * R.fillna(0) - W.diff().abs() * c - W.clip(upper=0).abs() * al / 252).fillna(0)
    return contrib.sum(axis=1), contrib, W


def episodios(Wx, R, contrib):
    """Negócios = trechos contínuos com posição != 0 (pesos já executados). Retorno do ativo com o sinal da posição."""
    out = []
    for c in Wx.columns:
        w = Wx[c].fillna(0)
        lado = np.sign(w)
        mud = lado.ne(lado.shift(fill_value=0))
        g = mud.cumsum()[lado != 0]
        for _, idx in g.groupby(g).groups.items():
            ent, sai = idx[0], idx[-1]
            seg = R[c].loc[ent:sai].iloc[1:].fillna(0)
            if len(Wx.loc[sai:]) > 1:
                seg = pd.concat([seg, R[c].loc[sai:].iloc[1:2].fillna(0)])
            l = lado.loc[ent]
            out.append({"ativo": c, "lado": "compra" if l > 0 else "venda", "entrada": ent, "saida": seg.index[-1] if len(seg) else sai,
                        "dias": len(seg), "peso médio": w.loc[ent:sai].abs().mean(),
                        "retorno %": np.expm1(np.log1p((seg * l).clip(lower=-.99)).sum()) * 100,
                        "contrib %": contrib[c].loc[ent:seg.index[-1] if len(seg) else sai].sum() * 100})
    return pd.DataFrame(out).sort_values("contrib %").reset_index(drop=True) if out else pd.DataFrame()


def fecha(r_usd, contrib, Wx, R, detalhe, trades=None):
    e = brl(r_usd)
    if not detalhe:
        return e
    return e, contrib, (trades if trades is not None else episodios(Wx, R, contrib))


def _px(cols, fonte="fronteira"):
    F = pd.read_parquet(D / f"y_{fonte}.parquet")
    return F[[c for c in cols if c in F]]


def fim_mes_us():
    p = pd.Series(DIAS_US.to_period("M"), index=DIAS_US)
    return p.ne(p.shift(-1))


PX = _px(FRONT + list(ARG) + list(ARG.values()))
P_US = PX.reindex(DIAS_US).ffill(limit=5)
RX_US = limpa(P_US.pct_change(fill_method=None), .4).sub(TB_US, axis=0)
for _e in ("TLT", "EEM", "ACWI"):
    RX_US[_e] = ETF[_e].reindex(DIAS_US).ffill(limit=5).pct_change(fill_method=None) - TB_US
    P_US[_e] = ETF[_e].reindex(DIAS_US).ffill(limit=5)


# =============================================================== 1. MERGER ARB via ETF (MNA/MRGR) com hedge de beta
def merger_etf(veiculo="MNA", hedge=1, alvo=None, custo_mult=1, lag=0, detalhe=False):
    """Comprado no ETF de merger arb; vende SPY no beta móvel (126d, só passado), rebalanceio mensal. Opcional: vol-alvo."""
    v = ["MNA", "MRGR"] if veiculo == "ambos" else [veiculo]
    r = RX_US[v].mean(axis=1, skipna=True)
    sp = RX_US["SPY"]
    beta = (r.rolling(126, min_periods=60).cov(sp) / sp.rolling(126, min_periods=60).var()).clip(0, 1).shift(1).fillna(.3)
    R = pd.DataFrame({"arb": r, "SPY": sp})
    W = pd.DataFrame({"arb": r.notna().astype(float), "SPY": -beta * hedge}, index=R.index)
    if alvo:
        rp = (W.shift(2) * R).sum(axis=1)
        vv = rp.rolling(126, min_periods=60).std().shift(1) * np.sqrt(252)
        W = W.mul((alvo / vv).clip(upper=3).fillna(0), axis=0)
    W = mensal(W)
    ex, ct, Wx = cart(W, R.fillna(0), C_ETF * custo_mult, lag, aluguel=.003)
    return fecha(ex, ct, Wx, R, detalhe)


# =============================================================== 4. CALENDÁRIO DE FLUXO (EUA)
def _cal():
    s = pd.Series(np.arange(len(DIAS_US)), index=DIAS_US)
    m = DIAS_US.to_period("M")
    pos = s.groupby(m).rank(method="first").astype(int)                       # 1 = 1º pregão do mês
    neg = s.groupby(m).rank(method="first", ascending=False).astype(int)      # 1 = último pregão do mês
    return pos, neg


def calendario(comp="todos", alvo=.08, custo_mult=1, lag=0, detalhe=False):
    """tom: SPY nos pregões -1, +1, +2, +3 da virada do mês (fluxo de salários/aportes de previdência).
    taxloss: IWM - SPY de 16/dez a 15/jan (fim da venda de small caps perdedoras para abater IR, e recompra em janeiro).
    rebal: pregões -4..-1 do mês: se ações bateram títulos (SPY x TLT) no mês até o dia -6, vende SPY e compra TLT (fundos balanceados/pensão
    rebalanceando no fim do mês), e vice-versa.
    As datas são conhecidas de antemão: W(t) = posição desejada no pregão t+2 (motor executa no fechamento de t+1)."""
    pos, neg = _cal()
    idx = DIAS_US
    R = RX_US[["SPY", "IWM", "TLT"]]
    H = pd.DataFrame(0.0, index=idx, columns=R.columns)
    if comp in ("tom", "todos"):
        H["SPY"] += ((neg == 1) | (pos <= 3)).astype(float)
    if comp in ("taxloss", "todos"):
        md = pd.Series(idx.month * 100 + idx.day, index=idx)
        h = ((md >= 1216) | (md <= 115)).astype(float)
        H["IWM"] += h
        H["SPY"] -= h
    if comp in ("rebal", "todos"):
        lp = np.log(P_US["SPY"]) - np.log(P_US["TLT"])
        mtd = lp - lp.shift(1).where(pos == 1).ffill()
        sinal = -np.sign(mtd.where(neg == 6)).ffill().where(neg <= 4, 0).fillna(0)   # sabido no dia -6; H(t) = posição que rende o pregão t
        H["SPY"] += .5 * sinal
        H["TLT"] -= .5 * sinal
    W = H.shift(-2).fillna(0)                                                    # H nos dias -4..-1 vira W nos dias -6..-3: tudo sabido
    if alvo:
        rp = (H * R.fillna(0)).sum(axis=1)                                      # retorno da regra quando posicionada
        on = H.abs().sum(axis=1) > 0
        vv = rp[on].rolling(250, min_periods=60).std().reindex(idx).ffill().shift(1) * np.sqrt(252)
        W = W.mul((alvo / vv).clip(upper=4).fillna(0), axis=0)
    ex, ct, Wx = cart(W, R.fillna(0), C_ETF * custo_mult, lag)
    return fecha(ex, ct, Wx, R, detalhe)


# =============================================================== 5. FRONTEIRA: momentum com filtro de câmbio / reversão pós-crise
FR = {"VNM": ("VND=X", 50), "AFK": ("NGN=X", 50), "KSA": ("SAR=X", 20), "QAT": (None, 40), "UAE": (None, 40), "KWT": (None, 50),
      "ARGT": ("ARS=X", 40), "TUR": ("TRY=X", 20), "GREK": (None, 20), "EIDO": ("IDR=X", 20), "EPHE": ("PHP=X", 25), "EPU": ("PEN=X", 30),
      "ECH": ("CLP=X", 20), "EZA": ("ZAR=X", 15), "INDA": ("INR=X", 10), "THD": ("THB=X", 20), "EWM": ("MYR=X", 20), "EPOL": ("PLN=X", 20),
      "EWZ": ("BRL=X", 5), "EWW": ("MXN=X", 8), "ECNS": (None, 40)}                 # (moeda, custo por perna em bps)


def _fx_mom(j=63):
    return pd.DataFrame({e: -(np.log(P_US[m]) - np.log(P_US[m].shift(j))) for e, (m, _) in FR.items() if m and m in P_US})


def fronteira_mom(n=4, filtro_fx=1, hedge="EEM", custo_mult=1, lag=0, detalhe=False):
    """Mensal: compra os n ETFs de fronteira/EM pequenos com maior retorno 12-1m; com filtro, só se a moeda não caiu em 3m.
    Hedge: vende EEM (beta 1) -> long-short contra os emergentes grandes."""
    c = [e for e in FR if e in P_US]
    lp = np.log(P_US[c])
    mom = (lp.shift(21) - lp.shift(252)).where(P_US[c].notna().rolling(252).sum() > 230)
    if filtro_fx:
        mom = mom.where(~(_fx_mom().reindex(columns=c) < 0))
    rk = mom.rank(axis=1, ascending=False)
    W = (rk <= n).astype(float).div((rk <= n).sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    R = RX_US[c + ["EEM"]]
    W["EEM"] = -W.sum(axis=1) if hedge == "EEM" else 0.0
    W = mensal(W)
    custo = {e: FR[e][1] / 1e4 * custo_mult for e in c} | {"EEM": .0003 * custo_mult}
    ex, ct, Wx = cart(W, R.fillna(0), custo, lag, aluguel={"EEM": .005})
    return fecha(ex, ct, Wx, R, detalhe)


def fronteira_crise(queda=.5, meses=12, custo_mult=1, lag=0, detalhe=False):
    """No fim do mês, compra o ETF que caiu mais que `queda` do topo de 3 anos assim que o retorno de 1 mês vira positivo; segura `meses`.
    Comprado (benchmark ACWI c/ hedge): o resto do fundo fica no ACWI. 20% do PL por país."""
    c = [e for e in FR if e in P_US]
    Pm = P_US[c]
    dd = Pm / Pm.rolling(756, min_periods=250).max() - 1
    r1 = np.log(Pm) - np.log(Pm.shift(21))
    gat = ((dd < -queda) & (r1 > 0)).astype(float).where(fim_mes_us(), np.nan)
    gat = gat.where(gat > 0)
    hold = gat.ffill(limit=int(meses * 21)).fillna(0)
    W = hold * .2
    W["ACWI"] = (1 - W.sum(axis=1)).clip(lower=0)
    R = RX_US[c + ["ACWI"]]
    W = mensal(W)
    custo = {e: FR[e][1] / 1e4 * custo_mult for e in c} | {"ACWI": .0003 * custo_mult}
    ex, ct, Wx = cart(W, R.fillna(0), custo, lag)
    return fecha(ex, ct, Wx, R, detalhe)


# =============================================================== 6. ARGENTINA: CCL implícito por ação (local/ADR)
def argentina(sinal="dispersao", janela=20, freq="D", custo_mult=1, lag=0, detalhe=False):
    """dispersao: cada ADR tem um CCL implícito (preço local x ratio / ADR). Se o CCL de uma ação sobe acima da mediana das outras (contra a
    própria média de `janela` dias) a local está cara / o ADR barato: compra esse ADR e vende os de CCL abaixo (neutro em dólar). Só a perna NY.
    brecha: comprado na cesta de ADRs quando a brecha (CCL implícito / oficial) caiu no último mês (normalização), caixa caso contrário."""
    a = [x for x in ARG if x in PX and ARG[x] in PX]
    A = PX[a].reindex(DIAS_US)
    L = PX[[ARG[x] for x in a]].set_axis(a, axis=1).reindex(DIAS_US)
    ok = A.notna() & L.notna()
    A, L = A.ffill(limit=2), L.ffill(limit=2)
    R = limpa(A.pct_change(fill_method=None), .35).sub(TB_US, axis=0)
    c = np.log(L / A)
    salto = (c.diff().abs() > .25).astype(float)                         # troca de ratio / erro de base: descarta o sinal por uma janela
    if sinal == "dispersao":
        d = c - c.rolling(janela, min_periods=janela // 2).mean().shift(1)
        d = d.where(salto.rolling(janela, min_periods=1).max() == 0).where(ok)
        s = d.sub(d.median(axis=1), axis=0)
        W = s.div(s.abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0).clip(-.25, .25)
    else:
        rel = c - c.rolling(500, min_periods=100).median().shift(1)
        br = rel.median(axis=1) - np.log(P_US["ARS=X"]) + np.log(P_US["ARS=X"]).rolling(500, min_periods=100).median().shift(1)
        sig = ((br - br.shift(21)) < 0).astype(float)
        W = ok.astype(float).mul(sig, axis=0)
        W = W.div(W.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    W = {"D": W, "W": semanal(W), "M": mensal(W)}[freq]                        # o efeito dura poucos dias; o giro diário custa caro
    ex, ct, Wx = cart(W, R.where(ok).fillna(0), .0015 * custo_mult, lag, aluguel=.03)
    return fecha(ex, ct, Wx, R, detalhe)


# =============================================================== 7. ADR x LOCAL por fuso: o ADR negocia depois do fechamento local
def _leadlag():
    P = pd.read_parquet(D / "y_pares.parquet")
    g = lambda t, c: P[f"{t}|{c}"] if f"{t}|{c}" in P else None
    S, I, G, T = {}, {}, {}, {}
    for a, (l, fx, tx) in PARES.items():
        if g(l, "Close") is None or g(a, "Close") is None:
            continue
        X = g(fx, "Close")
        X = 1 / X if fx in ("EURUSD=X", "GBPUSD=X") else X
        A, L = g(a, "Close").dropna(), g(l, "Close").dropna()
        O = g(l, "Open").reindex(L.index)
        df = pd.DataFrame({"A": A}).join(L.rename("L"), how="left").join(X.rename("X"), how="left").ffill(limit=3).dropna()
        p = np.log(df.A) - np.log(df.L / df.X)
        s = p - p.rolling(20, min_periods=10).mean().shift(1)            # prêmio do ADR sobre a local (em USD) contra a média recente
        su = s.copy()
        su.index = su.index + pd.Timedelta(days=1)                       # o fechamento de NY em t só serve para a abertura local de t+1 em diante
        S[l] = su.reindex(L.index, method="ffill", tolerance=pd.Timedelta(days=4))
        gap = O / L.shift(1) - 1
        ruim = gap.abs() < 5e-4                                          # Yahoo antigo (JP 2005-09) grava abertura = fechamento anterior: dia descartado
        I[l] = (L / O - 1).where((O > 0) & ((L / O - 1).abs() < .2) & ~ruim)
        G[l] = (O / L.shift(1) - 1).where(lambda x: x.abs() < .3)
        T[l] = tx
    return pd.DataFrame(S), pd.DataFrame(I), pd.DataFrame(G), pd.Series(T)


LL = None


def adr_fuso(regiao="asia", thr=.02, custo_mult=1, lag=0, detalhe=False):
    """No pregão local seguinte, opera a ação LOCAL da abertura ao fechamento na direção do prêmio do ADR (o ADR andou depois que a local fechou).
    A abertura já corrige a maior parte (gap) - isso NÃO é capturável; o teste é se o resto continua durante o dia.
    Custo = 2 x 5 bps (spread/corretagem) + imposto local (TW 0,15% day-trade, HK 0,26%, KR 0,2%, Londres 0,5%, Paris 0,3%).
    10% do PL por sinal, máx. 100% bruto."""
    global LL
    if LL is None:
        LL = _leadlag()
    S, I, G, T = LL
    suf = {"asia": ("TW", "HK", "NS", "T", "KS"), "india+coreia": ("NS", "KS"), "japao": ("T",)}
    eur = [c for c in S if c.split(".")[-1] not in suf["asia"]]
    cols = eur if regiao == "europa" else [c for c in S if c.split(".")[-1] in suf[regiao]]
    S, I = S[cols], I[cols]
    if lag:
        S = S.shift(lag)
    W = np.sign(S).where(S.abs() > thr, 0) * .10
    W = W.div(np.maximum(W.abs().sum(axis=1), 1.0), axis=0)
    ct = (W * I.fillna(0)) - W.abs() * ((10 + T[cols]) / 1e4 * custo_mult)
    ex = ct.sum(axis=1)
    if not detalhe:
        return brl(ex)
    tr = []
    for c in cols:
        x = pd.DataFrame({"w": W[c], "r": I[c], "s": S[c], "ct": ct[c]}).dropna()
        x = x[x.w != 0]
        tr.append(pd.DataFrame({"ativo": c, "lado": np.where(x.w > 0, "compra", "venda"), "entrada": x.index, "saida": x.index, "dias": 1,
                                "sinal %": x.s * 100, "retorno %": np.sign(x.w) * x.r * 100, "contrib %": x.ct * 100}))
    return brl(ex), ct, pd.concat(tr).sort_values("contrib %").reset_index(drop=True)


# =============================================================== EVENTOS: carteira de eventos com hedge
def _precos_ev(nome):
    f = D / f"y_{nome}.parquet"
    if not f.exists():
        return pd.DataFrame(index=DIAS_US)
    P = pd.read_parquet(f)
    P.index = pd.DatetimeIndex(P.index).tz_localize(None).normalize()
    P = P[~P.index.duplicated()]
    return P.reindex(DIAS_US.union(P.index[P.index >= DIAS_US[0]])).reindex(DIAS_US)


def carteira_eventos(ev, P, dias, maxw=.05, hedge="IWM", custo=.004, custo_mult=1, lag=0, aluguel_h=.003, detalhe=False):
    """ev: DataFrame com ticker, data (dia da INFORMAÇÃO pública). Decide no fechamento da data, executa no fechamento seguinte, segura `dias` pregões
    (ou até o preço sumir: deslistagem). Peso igual entre posições ativas, máx. `maxw` por nome (o resto fica no caixa); vende o hedge na soma dos pesos."""
    ev = ev[ev.ticker.isin(P.columns)]
    pos = DIAS_US.searchsorted(pd.DatetimeIndex(ev.data))
    I = np.zeros((len(DIAS_US), P.shape[1]))
    col = {c: i for i, c in enumerate(P.columns)}
    for p0, tk in zip(pos, ev.ticker):
        if p0 < len(DIAS_US):
            I[p0:p0 + dias, col[tk]] = 1
    I = pd.DataFrame(I, index=DIAS_US, columns=P.columns)
    vivo = P.notna() & P.shift(-1).notna()                                   # só enquanto o preço existir
    I = I * vivo
    I = I.loc[:, I.sum() > 0]
    n = I.sum(axis=1)
    W = I.mul(np.minimum(maxw, 1 / n.replace(0, np.nan)), axis=0).fillna(0)
    R = limpa(P[I.columns].pct_change(fill_method=None), .8).sub(TB_US, axis=0)
    if hedge:
        R[hedge] = RX_US[hedge] if hedge in RX_US else ETF[hedge].reindex(DIAS_US).pct_change(fill_method=None) - TB_US
        W[hedge] = -W.sum(axis=1)
    cs = {c: custo * custo_mult for c in I.columns} | ({hedge: .0003 * custo_mult} if hedge else {})
    ex, ct, Wx = cart(W, R.fillna(0), cs, lag, aluguel={hedge: aluguel_h} if hedge else 0.0)
    if not detalhe:
        return brl(ex)
    tr = episodios(Wx.drop(columns=[hedge] if hedge else []), R, ct)
    if hedge and len(tr):                                                     # retorno do nome contra o hedge no mesmo período
        lh = np.log1p(R[hedge].fillna(0)).cumsum()
        tr["hedge %"] = [np.expm1(lh.loc[s] - lh.loc[e]) * 100 for e, s in zip(tr.entrada, tr.saida)]
        tr["ret - hedge %"] = tr["retorno %"] - tr["hedge %"]
    return brl(ex), ct, tr


# =============================================================== 2. INSIDERS EUA (Form 4, código P)
EXCL = r"FUND|PORTFOLIO|MUNICIPAL|INCOME TRUST|CLOSED|ETF|BDC|CAPITAL CORP|ACQUISITION|SPAC|INVESTMENT CORP|FINANCE CORP|HOLDINGS TRUST|ROYALTY"


def insiders_eventos():
    c = pd.read_parquet(D / "sec_insider_compras.parquet")
    c = c[c.DOCUMENT_TYPE.isin(["4", "4/A"]) & (c.TRANS_ACQUIRED_DISP_CD == "A")]
    c["valor"] = pd.to_numeric(c.TRANS_SHARES, errors="coerce") * pd.to_numeric(c.TRANS_PRICEPERSHARE, errors="coerce")
    c["preco"] = pd.to_numeric(c.TRANS_PRICEPERSHARE, errors="coerce")
    c["dt_neg"] = pd.to_datetime(c.TRANS_DATE, format="%d-%b-%Y", errors="coerce")
    c = c[(c.valor >= 10_000) & (c.preco >= 2) & c.FILING_DATE.notna()]
    c = c[(c.FILING_DATE - c.dt_neg).dt.days.between(0, 60)]                  # descarta arquivamentos muito atrasados/errados
    rel = c.RPTOWNER_RELATIONSHIP.fillna("")
    c = c[rel.str.contains("Officer|Director", regex=True)]                    # sem fundos/10% owners puros
    c = c[~c.ISSUERNAME.str.upper().str.contains(EXCL, regex=True, na=False)]
    tit = c.RPTOWNER_TITLE.fillna("").str.upper()
    c["chefe"] = tit.str.contains(r"\bCEO\b|CHIEF EXECUTIVE|\bCFO\b|CHIEF FINANCIAL|PRESIDENT", regex=True)
    c["tk"] = c.ISSUERTRADINGSYMBOL.str.upper().str.strip().str.replace(".", "-", regex=False)
    c = c[c.tk.str.fullmatch(r"[A-Z][A-Z\-]{0,5}", na=False)]
    g = c.groupby(["tk", "FILING_DATE", "RPTOWNERCIK"]).agg(valor=("valor", "sum"), chefe=("chefe", "max"), preco=("preco", "median"),
                                                            nome=("ISSUERNAME", "last")).reset_index()
    return g


def insiders_clusters(min_ins=3, janela=30, chefe_min=0):
    f = D / f"sec_insider_clusters_{min_ins}_{janela}_{chefe_min}.parquet"
    if f.exists() and f.stat().st_mtime > (D / "sec_insider_compras.parquet").stat().st_mtime:
        return pd.read_parquet(f)
    r = _clusters(min_ins, janela, chefe_min)
    r.to_parquet(f)
    return r


def _clusters(min_ins=3, janela=30, chefe_min=0):
    """Dia de arquivamento em que o emissor completa `min_ins` insiders distintos comprando em `janela` dias corridos.
    chefe_min>0: exige pelo menos um CEO/CFO/presidente entre eles e soma >= chefe_min dólares."""
    g = insiders_eventos().sort_values(["tk", "FILING_DATE"])
    out = []
    for tk, x in g.groupby("tk"):
        d = x.FILING_DATE.values
        ult = None
        for i in range(len(x)):
            ini = d[i] - np.timedelta64(janela, "D")
            jan = x.iloc[:i + 1][x.FILING_DATE.iloc[:i + 1].values > ini]
            if jan.RPTOWNERCIK.nunique() >= min_ins and (chefe_min == 0 or (jan.chefe.any() and jan.valor.sum() >= chefe_min)):
                if ult is None or (d[i] - ult) > np.timedelta64(180, "D"):     # um evento por emissor a cada 6 meses
                    out.append({"ticker": tk, "data": pd.Timestamp(d[i]), "n": jan.RPTOWNERCIK.nunique(), "valor": jan.valor.sum(),
                                "preco": jan.preco.median(), "nome": jan.nome.iloc[-1]})
                    ult = d[i]
    return pd.DataFrame(out)


_EV = {}


def insiders(min_ins=3, dias=126, chefe=0, custo_mult=1, lag=0, detalhe=False):
    """Compra o 'cluster' de insiders (>= min_ins diretores/executivos comprando no mercado em 30 dias) no dia seguinte ao arquivamento do
    Form 4 que completa o grupo; segura `dias`; vende IWM na mesma soma. 5% por nome, custo 40 bps por perna (small/mid caps)."""
    k = ("ins", min_ins, chefe)
    if k not in _EV:
        _EV[k] = insiders_clusters(min_ins, 30, 250_000 if chefe else 0)
    ev = _EV[k]
    P = _precos_ev("insiders")
    ok = []
    for t, d, p in zip(ev.ticker, ev.data, ev.preco):                         # ticker reaproveitado / outra empresa: preço tem de bater com o Form 4
        if t in P:
            x = P[t].loc[:d].dropna()
            ok.append(len(x) > 0 and (x.index[-1] >= d - pd.Timedelta(days=7)) and 1 / 3 < x.iloc[-1] / p < 3)
        else:
            ok.append(False)
    ev = ev[np.array(ok, dtype=bool)]
    return carteira_eventos(ev, P, dias, .05, "IWM", .004, custo_mult, lag, detalhe=detalhe)


# =============================================================== 3. SPIN-OFFS (Form 10-12B)
def spin_eventos():
    ix = pd.read_parquet(D / "sec_indice.parquet")
    s = ix[ix.forma.isin(["10-12B", "10-12B/A"])].groupby("cik").data.min().rename("d10")
    tk = cik_ticker()
    tk = tk[tk.cik.isin(s.index)].merge(s, left_on="cik", right_index=True)
    tk = tk[(tk.d1 >= tk.d10) & (tk.d0 <= tk.d10 + pd.Timedelta(days=900))]
    tk = tk.sort_values("n").groupby("cik").tail(1)
    return tk[["cik", "tk", "d10"]].rename(columns={"tk": "ticker"})


def spinoffs(espera=20, dias=252, hedge="IWM", custo_mult=1, lag=0, detalhe=False):
    """A separada começa a negociar; fundos de índice da controladora e gestores que não querem a empresa pequena vendem nas primeiras semanas.
    Compra `espera` pregões após o 1º preço (só se o 1º preço vier até 1 ano depois do Form 10-12B), segura `dias`, hedge IWM. 5% por nome."""
    s = spin_eventos()
    P = _precos_ev("spinoffs")
    ev = []
    for c, t, d in zip(s.cik, s.ticker, s.d10):
        if t not in P:
            continue
        x = P[t].dropna()
        x = x[x.index >= d - pd.Timedelta(days=30)]
        if len(x) > espera + 5 and x.index[0] <= d + pd.Timedelta(days=365) and (P[t].loc[:d - pd.Timedelta(days=30)].notna().sum() == 0):
            ev.append({"ticker": t, "data": x.index[espera], "inicio": x.index[0], "d10": d})
    ev = pd.DataFrame(ev)
    return carteira_eventos(ev, P, dias, .05, hedge, .002, custo_mult, lag, detalhe=detalhe)


# =============================================================== 1b. MERGER ARB por evento (SC 14D9 = alvo de oferta pública) — teste de viés
def alvos_ofertas():
    """Alvos de tender offer (SC 14D9 arquivado pelo alvo) + se o alvo arquivou deslistagem (25-NSE / 15-12B/G / 15-15D) em até 1 ano."""
    ix = pd.read_parquet(D / "sec_indice.parquet")
    a = ix[ix.forma == "SC 14D9"].sort_values("data").groupby("cik").agg(data=("data", "first"), nome=("nome", "first")).reset_index()
    # várias ofertas por alvo ao longo do tempo: usa cada 1º SC 14D9 separado por > 1 ano
    x = ix[ix.forma == "SC 14D9"].sort_values(["cik", "data"])
    x = x[x.groupby("cik").data.diff().dt.days.fillna(9999) > 365][["cik", "data", "nome"]]
    dl = ix[ix.forma.isin(["25-NSE", "15-12B", "15-12G", "15-15D"])][["cik", "data"]].rename(columns={"data": "dl"})
    m = x.merge(dl, on="cik", how="left")
    m = m[(m.dl.isna()) | (m.dl >= m.data - pd.Timedelta(days=30))]
    m["dias_ate_saida"] = (m.dl - m.data).dt.days
    m = m.sort_values("dias_ate_saida").groupby(["cik", "data"]).first().reset_index()
    m["concluiu_1a"] = m.dias_ate_saida.le(365)
    tk = cik_ticker()
    t = tk.sort_values("d1").groupby("cik").tail(1)[["cik", "tk"]]
    return m.merge(t, on="cik", how="left").rename(columns={"tk": "ticker"})


def preco_oferta(ciks):
    """Lê o preço da oferta ("$xx.xx per share ... in cash") no SC TO-T original arquivado sob o CIK do alvo. Cache: dados/sec_ofertas_preco.parquet"""
    f = D / "sec_ofertas_preco.parquet"
    velho = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["cik", "arq", "data", "oferta"])
    ix = pd.read_parquet(D / "sec_indice.parquet")
    to = ix[(ix.forma == "SC TO-T") & ix.cik.isin(ciks) & ~ix.arq.isin(velho.arq)]
    novos = []
    for c, a, d in zip(to.cik, to.arq, to.data):
        r = _get(f"{SEC}/Archives/{a}", stream=True)
        txt = ""
        if r is not None:
            for ch in r.iter_content(65536):
                txt += ch.decode("latin-1", "ignore")
                if len(txt) > 400_000:
                    break
            r.close()
        txt = re.sub(r"<[^>]+>|&nbsp;|&#160;", " ", txt)
        m = re.findall(r"\$\s?(\d{1,4}(?:\.\d{1,4})?)\s*(?:net\s+)?per\s+(?:share|unit|ordinary)", txt, flags=re.I)
        novos.append({"cik": c, "arq": a, "data": d, "oferta": float(pd.Series(m[:20]).astype(float).mode().iloc[0]) if m else np.nan})
    if novos:
        velho = pd.concat([velho, pd.DataFrame(novos)])
        velho.to_parquet(f)
    return velho


def estudo_merger(dias=252):
    """Negócio a negócio: compra o alvo no fechamento seguinte ao SC 14D9; sai no último preço disponível (deslistagem) ou após `dias`."""
    a = alvos_ofertas().dropna(subset=["ticker"])
    P = _precos_ev("alvos")
    ofe = preco_oferta(set(a.cik[a.ticker.isin(P.columns)]))
    out = []
    for _, x in a[a.ticker.isin(P.columns)].iterrows():
        p = P[x.ticker].dropna()
        p0 = p[p.index > x.data]
        antes = p[p.index <= x.data]
        if len(p0) < 2 or len(antes) == 0 or (x.data - antes.index[-1]).days > 10:
            continue                                                          # sem preço na data do evento: ticker de outra empresa
        seg = p0.iloc[:dias]
        o = ofe[(ofe.cik == x.cik) & ((ofe.data - x.data).dt.days.between(-60, 30))].oferta.dropna()
        o = o.iloc[0] if len(o) else np.nan
        out.append({"alvo": x.nome, "ticker": x.ticker, "SC 14D9": x.data.date(), "entrada": seg.index[0].date(), "preço entrada": seg.iloc[0],
                    "oferta": o, "spread %": (o / seg.iloc[0] - 1) * 100 if o == o else np.nan, "saída": seg.index[-1].date(),
                    "preço saída": seg.iloc[-1], "dias": len(seg), "retorno %": (seg.iloc[-1] / seg.iloc[0] - 1) * 100,
                    "deslistou em 1 ano (EDGAR)": bool(x.concluiu_1a), "ainda negocia": p.index[-1] >= DIAS_US[-5]})
    return pd.DataFrame(out)


def merger_eventos(dias=126, custo_mult=1, lag=0, detalhe=False):
    """Compra o alvo no dia seguinte ao SC 14D9 e segura até deslistar (ou `dias`). Hedge: nenhum (oferta em dinheiro).
    VIÉS: o Yahoo apaga o histórico de quem foi comprado -> sobram quase só ofertas que fracassaram ou alvos ainda listados."""
    ev = alvos_ofertas().dropna(subset=["ticker"])
    P = _precos_ev("alvos")
    return carteira_eventos(ev[["ticker", "data"]], P, dias, .05, None, .002, custo_mult, lag, detalhe=detalhe)


if __name__ == "__main__" and sys.argv[1:2] == ["dados"]:
    o = sys.argv[2:] or ["indice", "form345"]
    if "yahoo" in o:
        baixa_precos(FRONT + list(ARG) + list(ARG.values()), "fronteira")
        fx = sorted({m for _, m, _ in PARES.values()})
        baixa_precos(list(PARES) + [l for l, _, _ in PARES.values()] + fx, "pares", extra=["Open", "Close"])
    if "eventos" in o:
        ev = pd.concat([insiders_clusters(3, 30), insiders_clusters(2, 30, 250_000)])
        baixa_precos(sorted(set(ev.ticker)), "insiders", lote_n=50, pausa=2)
        baixa_precos(sorted(set(spin_eventos().ticker)), "spinoffs")
        baixa_precos(sorted(set(alvos_ofertas().ticker.dropna())), "alvos")
    if "retry" in o:                                                    # Yahoo limita a taxa: tenta de novo, devagar, quem falhou
        for nome, ev in (("insiders", pd.concat([insiders_clusters(3, 30), insiders_clusters(2, 30, 250_000)])), ("spinoffs", spin_eventos()),
                         ("alvos", alvos_ofertas().dropna(subset=["ticker"]))):
            ft = D / f"y_{nome}_tentados.txt"
            P = pd.read_parquet(D / f"y_{nome}.parquet")
            falta = set(ev.ticker) - set(P.columns)
            ft.write_text(" ".join(sorted(set(ft.read_text().split()) - falta)))
            baixa_precos(sorted(falta), nome, lote_n=25, pausa=4)
    if "indice" in o:
        baixa_indices()
    if "form345" in o:
        baixa_form345()
    sys.exit()


# =============================================================== FUNDOS
FUNDOS = None


def _fundos():
    from motor import Fundo
    MM = dict(adm=0.0, perf=0.0)
    return [
        Fundo("G1 Merger arb (ETF) com hedge de beta", "Event-driven", "CDI",
              "Arbitragem de fusões paga um prêmio de seguro contra quebra do negócio; como não temos preços de alvos já comprados (Yahoo apaga), "
              "compramos o prêmio via ETF de merger arb (MNA/MRGR) e vendemos o beta residual em SPY",
              "100% no ETF, venda de SPY no beta móvel de 126d, rebalanceio mensal", merger_etf,
              {"veiculo": ["MNA", "MRGR", "ambos"], "hedge": [0, 1]}, inicio="2013-01-01", corte="2021-01-01", **MM),
        Fundo("G2 Insiders em grupo (Form 4) x IWM", "Event-driven", "CDI",
              "Quando 3+ diretores/executivos compram ações da própria empresa com dinheiro do bolso em 30 dias, sabem algo que o mercado não precifica",
              "Compra no dia seguinte ao Form 4 que completa o grupo, 5% por nome, segura 3-6 meses, vende IWM na mesma soma; custo 40 bps/perna",
              insiders, {"min_ins": [2, 3], "dias": [63, 126], "chefe": [0, 1]}, inicio="2008-01-01", corte="2021-01-01", **MM),
        Fundo("G3 Spin-offs após a venda forçada", "Event-driven", "CDI",
              "A empresa separada é vendida por fundos de índice e gestores da controladora nas 1as semanas; o preço volta quando a venda acaba",
              "Compra 10-40 pregões após o 1º preço, segura 6-12 meses, 5% por nome, hedge IWM", spinoffs,
              {"espera": [10, 20, 40], "dias": [126, 252]}, inicio="2008-01-01", corte="2021-01-01", **MM),
        Fundo("G4 Calendário de fluxo EUA", "Fluxo", "CDI",
              "Fluxos previsíveis: aportes na virada do mês, venda fiscal de small caps em dezembro, rebalanceamento de fundos balanceados no fim do mês",
              "SPY/IWM/TLT só nas janelas do calendário, vol-alvo", calendario,
              {"comp": ["tom", "taxloss", "rebal", "todos"], "alvo": [.05, .10]}, inicio="2008-01-01", corte="2021-01-01", **MM),
        Fundo("G5 Fronteira: momentum com filtro de câmbio", "Ações globais", "CDI",
              "Mercados de fronteira têm tendência longa (fluxo estrangeiro lento, pouca arbitragem); a moeda caindo antecipa saída de capital",
              "Top n de 21 ETFs de fronteira/EM pequenos por retorno 12-1m, mensal, custo 5-50 bps por perna; vende EEM na mesma soma", fronteira_mom,
              {"n": [3, 5], "filtro_fx": [0, 1], "hedge": ["EEM"]}, inicio="2012-01-01", corte="2021-01-01", **MM),
        Fundo("G6 Fronteira: compra depois da crise", "Ações globais", "ACWI (R$ c/ hedge)",
              "Depois de queda > 40-60% (crise cambial/política) o país fica barato e o estrangeiro já saiu; compra quando o preço para de cair",
              "Até 20% do PL por país por 6-12 meses, resto em ACWI", fronteira_crise,
              {"queda": [.4, .5, .6], "meses": [6, 12]}, inicio="2012-01-01", corte="2021-01-01", **MM),
        Fundo("G7 Argentina: CCL implícito por ação", "Valor relativo", "CDI",
              "Cada ADR argentino implica um dólar CCL (preço local / ADR); quando o CCL de uma ação se afasta dos outros, o ADR é que ajusta",
              "Long-short só em ADRs (NY), neutro em dólar, custo 15 bps/perna e aluguel 3% a.a.; variante 'brecha' = cesta comprada quando a brecha cai",
              argentina, {"sinal": ["dispersao"], "janela": [20, 60], "freq": ["D", "W", "M"]}, inicio="2010-01-01", corte="2021-01-01", **MM),
        Fundo("G8 ADR x local por fuso (Ásia/Europa)", "Valor relativo", "CDI",
              "O ADR negocia horas depois do fechamento local; a parte do movimento que a abertura local não corrige continua no pregão",
              "Ação local comprada/vendida da abertura ao fechamento quando o prêmio do ADR passa de thr; 10% por sinal; imposto local + 10 bps",
              adr_fuso, {"regiao": ["asia", "india+coreia", "japao", "europa"], "thr": [.01, .02]}, inicio="2011-01-01", corte="2021-01-01", **MM),
    ]


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    from motor import roda
    from rodar import BENCH
    from pathlib import Path
    out = Path(__file__).resolve().parent / "resultado"
    so = sys.argv[1:]
    FUNDOS = _fundos()
    res = []
    for f in FUNDOS:
        if so and f.nome[:2] not in so:
            continue
        t0 = time.time()
        r = roda(f, CDI, BENCH[f.benchmark], print)
        if r is None:
            print(f.nome, "sem resultado")
            continue
        e, ct, tr = f.func(**r["params"], detalhe=True)
        if ct.shape[1] > 60:                                                   # muitos nomes: formato longo (data, ativo, contrib) só com valores != 0
            ct = ct.stack().rename("contrib").loc[lambda x: x != 0].reset_index().set_axis(["data", "ativo", "contrib"], axis=1)
        r["contrib"], r["trades"] = ct, tr
        if f.nome.startswith("G1"):
            r["eventos_alvos"] = estudo_merger()                                 # alvos de oferta com preço no Yahoo (viés: só sobreviventes)
        o, rb = r["oos"], r["rob"]
        print(f"{f.nome[:45]:45s} {str(r['params']):55s} IR IS {r['is_ir']:5.2f} | OOS {o['retorno a.a. %']:5.1f}% vs {o['benchmark a.a. %']:5.1f}% "
              f"IR {o['IR vs bench']:5.2f} | P {rb['P(bater bench OOS) %']:3.0f}% PBO {rb['PBO %']:3.0f}% | c2 {rb['OOS custo x2 (pp)']:5.1f} "
              f"l1 {rb['OOS execução +1 dia (pp)']:5.1f} | {time.time() - t0:.0f}s", flush=True)
        r["fundo"].func = None
        res.append(r)
    nome = "ideias_global.pkl" if not so else f"ideias_global_{'_'.join(so)}.pkl"
    pickle.dump(res, open(out / nome, "wb"))
