"""
Dados novos da frente ARBITRAGEM (cache em quant/fundos/dados/arb_*.parquet; nunca re-baixa o que já existe).
  python arb_dados.py [bdr|cripto|yahoo|proventos|ind|tudo]
  arb_bdr_vista   : BDRs (CODBDI 34/35/36 a partir de out/2022 não estavam em b3_vista) re-lidos dos COTAHIST locais
  arb_us          : fechamento EUA (não ajustado por dividendos) dos ativos-objeto dos BDRs + ETFs de referência + futuros CME de cripto
  arb_cripto_1h   : BTC/ETH hora a hora (Binance, público) para casar com o fechamento da B3 e da CME
  arb_proventos   : proventos em dinheiro B3 (data de aprovação = divulgação, data-com, valor, DIVIDENDO/JCP)
  arb_ind         : ajustes do futuro de Ibovespa (IND/WIN) nos 12 pregões antes de cada vencimento (boletim BVBG.086)
"""
import base64
import io
import json
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

from base import D, DIAS, DQ

H = {"User-Agent": "Mozilla/5.0 (pesquisa academica)"}
COT_ZIP = DQ / "cotahist"


def get(url, tent=4, **kw):
    for t in range(tent):
        try:
            r = requests.get(url, headers=H, timeout=kw.pop("timeout", 120), **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if t == tent - 1:
                raise
            time.sleep(3 * (t + 1))


# ----------------------------------------------------------------- BDRs do COTAHIST
def _bdr_ano(f):
    out = []
    n = lambda l, a, b: int(l[a:b]) / 100
    with zipfile.ZipFile(f) as z, z.open(z.namelist()[0]) as fh:
        for l in io.TextIOWrapper(fh, encoding="latin1"):
            if l[:2] != "01" or l[24:27] != "010":
                continue
            tk = l[12:24].strip()
            if l[10:12] in ("34", "35", "36") or re.fullmatch(r"[A-Z][A-Z0-9]{3}3[2-59]", tk):
                out.append((l[2:10], tk, l[10:12], l[39:49].strip(), n(l, 108, 121), n(l, 121, 134), n(l, 134, 147), int(l[147:152]),
                            int(l[152:170]), int(l[170:188]) / 100, int(l[210:217])))
    print("  ", f.name, len(out), flush=True)
    return out


def bdr():
    f = D / "arb_bdr_vista.parquet"
    if f.exists():
        return
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(_bdr_ano, sorted(COT_ZIP.glob("COTAHIST_A*.ZIP"))))
    v = pd.DataFrame([x for r in res for x in r], columns=["data", "ticker", "codbdi", "especi", "fech", "oferta_compra", "oferta_venda",
                                                           "negocios", "quantidade", "volume", "fatcot"])
    v["data"] = pd.to_datetime(v.data, format="%Y%m%d")
    v.to_parquet(f)
    print("BDRs:", len(v), v.ticker.nunique(), flush=True)


# ----------------------------------------------------------------- Binance hora a hora
def cripto():
    f = D / "arb_cripto_1h.parquet"
    if f.exists():
        return
    partes = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        t0 = int(pd.Timestamp("2017-08-17").timestamp() * 1000)
        while True:
            k = get("https://api.binance.com/api/v3/klines", params={"symbol": sym, "interval": "1h", "startTime": t0, "limit": 1000}).json()
            if not k:
                break
            partes.append(pd.DataFrame({"sym": sym, "t": pd.to_datetime([x[0] for x in k], unit="ms"), "fech": [float(x[4]) for x in k],
                                        "vol_usd": [float(x[7]) for x in k]}))
            t0 = k[-1][0] + 3600_000
            if len(k) < 1000:
                break
        print("  ", sym, flush=True)
    pd.concat(partes, ignore_index=True).to_parquet(f)


def cripto_fut():
    """Futuros trimestrais COIN-M da Binance (contínuo trimestre atual/próximo), diário 00:00 UTC."""
    f = D / "arb_cripto_fut.parquet"
    if f.exists():
        return
    partes = []
    for par in ("BTCUSD", "ETHUSD"):
        for ct in ("CURRENT_QUARTER", "NEXT_QUARTER"):
            t0 = int(pd.Timestamp("2020-08-01").timestamp() * 1000)
            while True:
                k = get("https://dapi.binance.com/dapi/v1/continuousKlines", params={"pair": par, "contractType": ct, "interval": "1d",
                                                                                  "startTime": t0, "limit": 1000}).json()
                if not k:
                    break
                partes.append(pd.DataFrame({"par": par, "ct": ct, "t": pd.to_datetime([x[0] for x in k], unit="ms"),
                                            "fech": [float(x[4]) for x in k], "vol": [float(x[5]) for x in k]}))
                t0 = k[-1][0] + 86400_000
                if len(k) < 1000:
                    break
    pd.concat(partes, ignore_index=True).to_parquet(f)
    print("  futuros cripto ok", flush=True)


# ----------------------------------------------------------------- Yahoo (EUA)
def yahoo(tickers):
    import yfinance as yf
    f = D / "arb_us.parquet"
    velho = pd.read_parquet(f) if f.exists() else pd.DataFrame()
    falta = sorted(set(tickers) - set(velho.columns))
    if not falta:
        return velho
    out = []
    for i in range(0, len(falta), 80):
        d = yf.download(falta[i:i + 80], start="2013-12-01", auto_adjust=False, progress=False, threads=True)["Close"]
        if isinstance(d, pd.Series):
            d = d.to_frame(falta[i])
        out.append(d)
    novo = pd.concat(out, axis=1)
    novo.index = pd.DatetimeIndex(novo.index).tz_localize(None).normalize()
    for t in falta:                                   # marca os que não existem para não tentar de novo
        if t not in novo:
            novo[t] = np.nan
    tudo = pd.concat([velho, novo], axis=1) if len(velho) else novo
    tudo = tudo.loc[:, ~tudo.columns.duplicated()].sort_index()
    tudo.to_parquet(f)
    print("  yahoo:", len(falta), "novos;", novo.notna().any().sum(), "com dados", flush=True)
    return tudo


# ----------------------------------------------------------------- proventos B3
def _b64(d):
    return base64.b64encode(json.dumps(d).encode()).decode()


def _prov_emp(code4):
    try:
        u = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/"
        nome = get(u + "GetListedSupplementCompany/" + _b64({"issuingCompany": code4, "language": "pt-br"})).json()[0]["tradingName"].strip()
        res, p = [], 1
        while True:
            j = get(u + "GetListedCashDividends/" + _b64({"language": "pt-br", "pageNumber": p, "pageSize": 120, "tradingName": nome})).json()
            res += j.get("results") or []
            if p >= j["page"]["totalPages"]:
                break
            p += 1
        d = pd.DataFrame(res)
        d["code4"] = code4
        return d
    except Exception as e:
        print("   proventos", code4, e, flush=True)
        return None


def proventos(codes):
    f = D / "arb_proventos.parquet"
    velho = pd.read_parquet(f) if f.exists() else pd.DataFrame({"code4": []})
    falta = sorted(set(codes) - set(velho.code4))
    if not falta:
        return velho
    with ThreadPoolExecutor(4) as ex:
        novos = [x for x in ex.map(_prov_emp, falta) if x is not None]
    vazios = pd.DataFrame({"code4": [c for c in falta if c not in {x.code4.iloc[0] for x in novos if len(x)}]})
    tudo = pd.concat([velho] + novos + [vazios], ignore_index=True)
    tudo.to_parquet(f)
    print("  proventos:", len(falta), "empresas", flush=True)
    return tudo


# ----------------------------------------------------------------- ajustes IND/WIN perto do vencimento
IND_RE = re.compile(rb"<TckrSymb>((?:IND|WIN)[GJMQVZ]\d\d)</TckrSymb>")


def venc_ind():
    """IND vence na quarta-feira mais próxima do dia 15 dos meses pares."""
    out = []
    for a in range(2019, 2027):
        for m in (2, 4, 6, 8, 10, 12):
            d15 = pd.Timestamp(a, m, 15)
            q = d15 + pd.Timedelta(days=(2 - d15.weekday() + 3) % 7 - 3)
            out.append(q)
    return out


def _ind_dia(d):
    pasta = D / "arb_ind_dias"
    pasta.mkdir(exist_ok=True)
    f = pasta / f"{d:%Y%m%d}.parquet"
    if f.exists():
        return
    try:
        z = zipfile.ZipFile(io.BytesIO(get(f"https://www.b3.com.br/pesquisapregao/download?filelist=PR{d:%y%m%d}.zip,", timeout=300).content))
        z2 = zipfile.ZipFile(io.BytesIO(z.read(z.namelist()[0])))
    except Exception:
        pd.DataFrame({"date": [], "ticker": []}).to_parquet(f)
        return
    linhas = []
    for n in z2.namelist():
        t = z2.read(n)
        for m in IND_RE.finditer(t):
            bloco = t[m.end(): t.find(b"</PricRpt>", m.end())]
            r = {"date": d, "ticker": m.group(1).decode()}
            for c in ("AdjstdQt", "PrvsAdjstdQt", "OpnIntrst", "NtlFinVol", "FinInstrmQty", "LastPric"):
                v = re.search(rb"<" + c.encode() + rb"[^>]*>([-\d.]+)<", bloco)
                r[c] = float(v.group(1)) if v else np.nan
            linhas.append(r)
    pd.DataFrame(linhas).to_parquet(f)


def ind():
    dias = []
    for v in venc_ind():
        if v > DIAS[-1]:
            continue
        p = DIAS[DIAS <= v][-13:]
        dias += list(p) + list(DIAS[DIAS > v][:1])
    dias = sorted(set(dias))
    with ThreadPoolExecutor(5) as ex:
        list(ex.map(_ind_dia, dias))
    fs = sorted((D / "arb_ind_dias").glob("*.parquet"))
    x = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    x = x.dropna(subset=["AdjstdQt"]).drop_duplicates(["date", "ticker"], keep="last")
    x.to_parquet(D / "arb_ind.parquet")
    print("  IND:", len(x), "linhas", x.date.nunique(), "dias", flush=True)


if __name__ == "__main__":
    e = sys.argv[1] if len(sys.argv) > 1 else "tudo"
    if e in ("bdr", "tudo"):
        bdr()
    if e in ("cripto", "tudo"):
        cripto()
        cripto_fut()
    if e in ("ind", "tudo"):
        ind()
    print("pronto", e)
