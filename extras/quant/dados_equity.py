"""
Dados para as estratégias de ações e derivativos (tudo grátis):
  B3 COTAHIST (2014+): opções e à vista de BOVA11, PETR4, VALE3, ITUB4, BBDC4 -> dados/opcoes_b3.parquet, dados/vista_b3.parquet
      (preço de fechamento, melhor oferta de compra e de venda, strike, vencimento, volume)
  Yahoo: ações do S&P 500 (lista atual da Wikipedia) e do Ibovespa (carteira atual da B3), índices, VIX, VIX 3M, SVXY,
      índice PutWrite da CBOE, T-bill -> dados/eq_us.parquet, dados/eq_br.parquet, dados/eq_idx.parquet
Uso: python dados_equity.py [cotahist|yahoo]
"""
import base64
import io
import json
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

D_ = Path(__file__).resolve().parent / "dados"
H = {"User-Agent": "Mozilla/5.0"}
SUBJ = {"BOVA": "BOVA11", "PETR": "PETR4", "VALE": "VALE3", "ITUB": "ITUB4", "BBDC": "BBDC4"}


def cotahist(ano):
    f = D_ / "cotahist" / f"COTAHIST_A{ano}.ZIP"
    f.parent.mkdir(exist_ok=True)
    if not f.exists() or ano >= pd.Timestamp.today().year:
        for t in range(3):
            try:
                r = requests.get(f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP", headers=H, timeout=600)
                r.raise_for_status()
                f.write_bytes(r.content)
                break
            except requests.RequestException:
                time.sleep(10)
    z = zipfile.ZipFile(f)
    vista, opc = [], []
    with z.open(z.namelist()[0]) as fh:
        for raw in io.TextIOWrapper(fh, encoding="latin1"):
            if raw[:2] != "01":
                continue
            tp, cod = raw[24:27], raw[12:24].strip()
            num = lambda a, b: int(raw[a:b]) / 100
            if tp == "010" and cod in SUBJ.values():
                vista.append((raw[2:10], cod, num(56, 69), num(69, 82), num(82, 95), num(108, 121), int(raw[170:188]) / 100))
            elif tp in ("070", "080") and cod[:4] in SUBJ:
                opc.append((raw[2:10], cod, SUBJ[cod[:4]], "C" if tp == "070" else "P", num(108, 121), num(121, 134), num(134, 147),
                            int(raw[147:152]), int(raw[170:188]) / 100, num(188, 201), raw[202:210]))
    v = pd.DataFrame(vista, columns=["data", "ticker", "abertura", "max", "min", "fech", "volume"])
    o = pd.DataFrame(opc, columns=["data", "serie", "ativo", "tipo", "fech", "oferta_compra", "oferta_venda", "negocios", "volume", "strike", "venc"])
    for d in (v, o):
        d["data"] = pd.to_datetime(d.data, format="%Y%m%d")
    o["venc"] = pd.to_datetime(o.venc, format="%Y%m%d", errors="coerce")
    print(f"  {ano}: {len(v)} linhas à vista, {len(o)} de opções", flush=True)
    return v, o


def yahoo(tk, inicio=0):
    for t in range(3):
        try:
            j = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}", params={"period1": inicio, "period2": int(time.time()),
                             "interval": "1d", "events": "div,splits"}, headers=H, timeout=60).json()["chart"]["result"][0]
            ind = j["indicators"]
            c = ind["adjclose"][0]["adjclose"] if "adjclose" in ind else ind["quote"][0]["close"]
            s = pd.Series(c, index=pd.to_datetime(j["timestamp"], unit="s").normalize(), name=tk, dtype=float)
            return s[~s.index.duplicated(keep="last")].dropna()
        except (requests.RequestException, KeyError, TypeError, IndexError, ValueError):
            time.sleep(2 * (t + 1))
    return None


def sp500():
    t = pd.read_html(io.StringIO(requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=H, timeout=60).text))[0]
    return [s.replace(".", "-") for s in t.Symbol]


def ibov():
    p = base64.b64encode(json.dumps({"language": "pt-br", "pageNumber": 1, "pageSize": 120, "index": "IBOV", "segment": "1"}).encode()).decode()
    j = requests.get(f"https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{p}", headers=H, timeout=60).json()
    return [r["cod"] for r in j["results"]]


if __name__ == "__main__":
    etapa = sys.argv[1] if len(sys.argv) > 1 else "tudo"
    if etapa in ("tudo", "cotahist"):
        print("COTAHIST...", flush=True)
        vs, os_ = zip(*[cotahist(a) for a in range(2014, pd.Timestamp.today().year + 1)])
        pd.concat(vs).to_parquet(D_ / "vista_b3.parquet")
        pd.concat(os_).to_parquet(D_ / "opcoes_b3.parquet")
    if etapa in ("tudo", "yahoo"):
        print("Yahoo...", flush=True)
        us, br = sp500(), ibov()
        print(f"  S&P 500: {len(us)} ações | Ibovespa: {len(br)} ações", flush=True)
        ini = int(pd.Timestamp("2005-01-01").timestamp())
        with ThreadPoolExecutor(8) as ex:
            u = [s for s in ex.map(lambda t: yahoo(t, ini), us) if s is not None]
            b = [s for s in ex.map(lambda t: yahoo(t + ".SA", ini), br) if s is not None]
        pd.concat(u, axis=1).to_parquet(D_ / "eq_us.parquet")
        pd.concat(b, axis=1).to_parquet(D_ / "eq_br.parquet")
        idx = [yahoo(t, ini) for t in ("SPY", "BOVA11.SA", "^BVSP", "^VIX", "^VIX3M", "SVXY", "^PUT", "^IRX", "^GSPC")]
        pd.concat([s for s in idx if s is not None], axis=1).to_parquet(D_ / "eq_idx.parquet")
        print(f"  US {len(u)} | BR {len(b)} séries", flush=True)
    print("pronto")
