"""
Dados extras para os modelos (tudo gratuito, guardado em quant/dados):
  focus_ipca   expectativa mediana do IPCA de cada mês (Focus/BCB) -> surpresa de inflação
  embi         risco-país Brasil (EMBI, Ipeadata)
  fluxos       captação líquida mensal dos fundos de crédito privado (informe diário da CVM)
  acoes        retorno mensal das ações dos emissores de debêntures (B3 + Yahoo)
  eurobonds    preço diário (FINRA/TRACE) dos bonds de emissores brasileiros listados no TradingView
  globais      ETFs de crédito EUA/Europa/emergentes (Yahoo) + €STR (BCE) para o hedge do euro
Uso: python dados_extra.py
"""
import base64
import io
import json
import re
import time
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from dados import DESDE, HOJE, PASTA, S, lt

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}"


def yahoo_mensal(t):
    try:
        j = S.get(YAHOO.format(t), params={"period1": int(pd.Timestamp("2018-01-01").timestamp()), "period2": int(time.time()),
                                            "interval": "1mo"}, timeout=10).json()["chart"]["result"][0]
        adj = j["indicators"].get("adjclose", [{}])[0].get("adjclose") or j["indicators"]["quote"][0]["close"]
        s = pd.Series(adj, index=pd.to_datetime(j["timestamp"], unit="s").to_period("M"), dtype=float).dropna()
        return s[~s.index.duplicated(keep="last")]
    except (requests.RequestException, KeyError, TypeError, IndexError, ValueError):
        return pd.Series(dtype=float)


def focus_ipca():
    u = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativaMercadoMensais?"
         + urllib.parse.quote("$filter=Indicador eq 'IPCA' and baseCalculo eq 0 and Data ge '2018-06-01'", safe="=$&'")
         + "&$format=json&$select=Data,DataReferencia,Mediana")
    d = pd.DataFrame(S.get(u, timeout=300).json()["value"])
    d["Data"] = pd.to_datetime(d.Data)
    d["ref"] = pd.PeriodIndex(pd.to_datetime(d.DataReferencia, format="%m/%Y"), freq="M")
    d = d[d.Data <= (d.ref + 1).dt.to_timestamp() + pd.Timedelta(days=8)]       # última pesquisa antes da divulgação
    return d.sort_values("Data").groupby("ref").Mediana.last().rename("focus_ipca") / 100


def embi():
    j = S.get("http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='JPM366_EMBI366')", timeout=120).json()["value"]
    s = pd.Series({pd.Timestamp(x["VALDATA"][:10]): x["VALVALOR"] for x in j if x["VALVALOR"] is not None}).sort_index()
    return s.groupby(s.index.to_period("M")).last().rename("embi")


def fluxos():
    """Captação líquida e PL dos fundos de crédito privado (nome com crédito/debênture/infra/incentivado), por mês."""
    cad = pd.read_csv(io.BytesIO(S.get("https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv", timeout=300).content),
                      sep=";", encoding="latin1", usecols=["CNPJ_FUNDO", "DENOM_SOCIAL"], dtype=str)
    nomes = dict(zip(cad.CNPJ_FUNDO, cad.DENOM_SOCIAL))
    try:
        z = zipfile.ZipFile(io.BytesIO(S.get("https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip", timeout=300).content))
        reg = pd.read_csv(z.open("registro_classe.csv"), sep=";", encoding="latin1", dtype=str)
        nomes.update(dict(zip(reg.CNPJ_Classe, reg.Denominacao_Social)))
    except (requests.RequestException, KeyError, ValueError, zipfile.BadZipFile):
        pass
    alvo = {c for c, n in nomes.items() if isinstance(n, str) and re.search(r"(?i)cr[eé]d|debent|infra|incentiv|\bCP\b", n)}
    infra = {c for c in alvo if re.search(r"(?i)infra|incentiv|12\.?431", nomes[c])}
    pasta = Path(lt.CACHE)
    out = []
    for f in sorted(pasta.glob("inf_diario_fi_*.zip")):
        z = zipfile.ZipFile(f)
        for n in z.namelist():
            x = pd.read_csv(z.open(n), sep=";", dtype=str, encoding="latin1")
            c = next(k for k in x.columns if k.startswith("CNPJ"))
            x = x[x[c].isin(alvo)]
            for k in ["VL_PATRIM_LIQ", "CAPTC_DIA", "RESG_DIA"]:
                x[k] = pd.to_numeric(x[k], errors="coerce")
            x["mes"] = pd.to_datetime(x.DT_COMPTC).dt.to_period("M")
            x["infra"] = x[c].isin(infra)
            x["liq"] = x.CAPTC_DIA - x.RESG_DIA
            pl = x.sort_values("DT_COMPTC").groupby(["mes", c, "infra"]).VL_PATRIM_LIQ.last().groupby(["mes", "infra"]).sum()
            out.append(pd.DataFrame({"liq": x.groupby(["mes", "infra"]).liq.sum(), "pl": pl}))
    d = pd.concat(out).groupby(level=[0, 1]).sum().unstack()
    return pd.DataFrame({"fluxo_credito": (d.liq.sum(axis=1) / d.pl.sum(axis=1)), "fluxo_infra": d.liq[True] / d.pl[True]})


def acoes():
    """Retorno mensal da ação de cada emissor de debênture listado na B3 (ligação pelo CNPJ)."""
    cad = pd.read_parquet(PASTA / "snd_cadastro.parquet")
    emp = []
    for pg in range(1, 40):
        p = base64.b64encode(json.dumps({"language": "pt-br", "pageNumber": pg, "pageSize": 120}).encode()).decode()
        r = S.get("https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetInitialCompanies/" + p, timeout=60).json()
        emp += r["results"]
        if pg >= (r["page"]["totalPages"] or 0):
            break
    emp = pd.DataFrame(emp)
    cnpjs = set(cad.cnpj.dropna().str.replace(r"\D", "", regex=True))
    emp = emp[emp.cnpj.isin(cnpjs) & emp.issuingCompany.str.len().eq(4)]
    def uma(e):
        for suf in ("3", "4", "11", "5", "6"):
            s = yahoo_mensal(f"{e.issuingCompany}{suf}.SA")
            if len(s) > 12:
                return e.cnpj, s
        return e.cnpj, None
    with ThreadPoolExecutor(8) as ex:
        series = {c: s for c, s in ex.map(uma, [e for _, e in emp.iterrows()]) if s is not None}
    print(f"  {len(series)} de {len(emp)} emissores com ação", flush=True)
    return pd.DataFrame(series).sort_index().pct_change()


def eurobonds():
    H = {"Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/", "User-Agent": "Mozilla/5.0"}
    q = {"filter": [{"left": "country", "operation": "equal", "right": "Brazil"}], "columns": ["name", "description", "maturity_date"], "range": [0, 3000]}
    tv = requests.post("https://scanner.tradingview.com/bond/scan", json=q, headers=H, timeout=60).json()["data"]
    lista = {}
    for x in tv:
        isin, desc, venc = x["d"]
        m = re.search(r"(\d+(?:\.\d+)?)%", desc or "")
        if isin and len(isin) == 12 and m and venc and not isin.startswith("BR"):
            lista[isin] = {"isin": isin, "emissor": re.sub(r"\s+\d.*$", "", desc), "cupom": float(m.group(1)),
                           "venc": pd.to_datetime(str(int(venc)), format="%Y%m%d"), "soberano": "Government of Brazil" in desc}
    cad = pd.DataFrame(lista.values())
    B = "https://services-dynarep.ddwa.finra.org/public/reporting/v2/"
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"})
    sess.get(B + "group/Firm/name/ActiveIndividual/dynamiclookup/examCode", timeout=60)
    sess.headers["X-XSRF-TOKEN"] = sess.cookies.get("XSRF-TOKEN", "")

    def um(i):
        b = {"fields": ["tradeDate", "closingPrice", "lastSalePrice"], "compareFilters": [{"fieldName": "cusip", "fieldValue": i[2:11], "compareType": "EQUAL"}],
             "dateRangeFilters": [{"startDate": f"{DESDE:%Y-%m-%d}", "endDate": f"{HOJE:%Y-%m-%d}", "fieldName": "tradeDate"}],
             "sortFields": ["tradeDate"], "offset": 0, "limit": 5000}
        for _ in range(3):
            try:
                d = pd.DataFrame(json.loads(sess.post(B + "data/group/FixedIncomeMarket/name/EndOfDayPriceYield", data=json.dumps(b), timeout=60).json()["returnBody"]["data"] or "[]"))
                if d.empty:
                    return None
                d = d.reindex(columns=["tradeDate", "closingPrice", "lastSalePrice"])
                p = pd.to_numeric(d.closingPrice, errors="coerce").fillna(pd.to_numeric(d.lastSalePrice, errors="coerce"))
                return pd.DataFrame({"isin": i, "date": pd.to_datetime(d.tradeDate), "preco": p}).dropna()
            except (requests.RequestException, ValueError, KeyError, TypeError):
                time.sleep(3)
        return None

    with ThreadPoolExecutor(4) as ex:
        precos = [x for x in ex.map(um, cad["isin"]) if x is not None]
    return cad, pd.concat(precos, ignore_index=True)


def globais():
    s = {t: yahoo_mensal(t) for t in ["LQD", "HYG", "CEMB", "EMB", "IHYG.L", "IEAC.L", "EURUSD=X"]}
    d = pd.DataFrame(s)
    try:
        e = pd.read_csv(io.StringIO(S.get("https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT?format=csvdata", timeout=120).text))
        e = e.set_index(pd.to_datetime(e.TIME_PERIOD)).OBS_VALUE
        d["estr"] = e.groupby(e.index.to_period("M")).mean() / 100
    except (requests.RequestException, KeyError, ValueError):
        d["estr"] = np.nan
    return d


if __name__ == "__main__":
    import sys
    t = time.time()
    etapas = sys.argv[1:] or ["focus_ipca", "embi", "globais", "acoes", "fluxos", "eurobonds"]
    for nome, fn in [(n, f) for n, f in [("focus_ipca", focus_ipca), ("embi", embi), ("globais", globais), ("acoes", acoes), ("fluxos", fluxos)] if n in etapas]:
        print(nome, "...", flush=True)
        x = fn()
        (x.to_frame() if isinstance(x, pd.Series) else x).to_parquet(PASTA / f"{nome}.parquet")
    if "eurobonds" in etapas:
        print("eurobonds ...", flush=True)
        cad, px = eurobonds()
        cad.to_parquet(PASTA / "eurobonds_cadastro.parquet")
        px.to_parquet(PASTA / "eurobonds_precos.parquet")
    print(f"pronto em {(time.time() - t) / 60:.0f} min", flush=True)
