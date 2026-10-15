"""
Coleta para os 20 fundos (tudo grátis). Uso: python dados_fundos.py [cotahist|yahoo|fred|cot|poly|tudo]
  cotahist : B3 COTAHIST 2014+ completo -> vista (todas as ações), opções (25 ativos com mais opções), termo
  yahoo    : ADRs e ações locais, moedas G10/EM, ETFs de países, renda fixa EUA, commodities, volatilidade, cripto
  fred     : juros curtos (3 meses) por país para o carry, curva dos EUA, inflação implícita, spreads, condições financeiras
  cot      : posicionamento CFTC (relatórios de futuros financeiros e de commodities), 2010+
  poly     : histórico de preços de mercados de previsão (Polymarket) sobre Fed, eleições e recessão
Saída: quant/fundos/dados/*.parquet
"""
import io
import json
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

AQUI = Path(__file__).resolve().parent
D = AQUI / "dados"
D.mkdir(exist_ok=True)
COT_ZIP = AQUI.parent / "dados" / "cotahist"
H = {"User-Agent": "Mozilla/5.0"}


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


# ----------------------------------------------------------------- B3 COTAHIST completo
def cotahist(ano):
    f = COT_ZIP / f"COTAHIST_A{ano}.ZIP"
    if not f.exists():
        f.write_bytes(get(f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{ano}.ZIP", timeout=600).content)
    z = zipfile.ZipFile(f)
    vista, opc, termo = [], [], []
    n = lambda l, a, b: int(l[a:b]) / 100
    with z.open(z.namelist()[0]) as fh:
        for l in io.TextIOWrapper(fh, encoding="latin1"):
            if l[:2] != "01":
                continue
            tp = l[24:27]
            if tp == "010" and l[10:12] in ("02", "12", "14"):            # lote padrão, FII, ETF/BDR (CODBDI)
                vista.append((l[2:10], l[12:24].strip(), l[39:49].strip(), n(l, 56, 69), n(l, 108, 121), n(l, 121, 134), n(l, 134, 147),
                              int(l[147:152]), int(l[152:170]), int(l[170:188]) / 100, int(l[210:217])))
            elif tp in ("070", "080"):
                opc.append((l[2:10], l[12:24].strip(), l[12:16], "C" if tp == "070" else "P", n(l, 108, 121), n(l, 121, 134), n(l, 134, 147),
                            int(l[147:152]), int(l[170:188]) / 100, n(l, 188, 201), l[202:210], l[201]))
            elif tp == "030":
                termo.append((l[2:10], l[12:24].strip(), int(l[49:52]) if l[49:52].strip().isdigit() else np.nan, n(l, 108, 121),
                               int(l[147:152]), int(l[170:188]) / 100))
    v = pd.DataFrame(vista, columns=["data", "ticker", "especi", "abertura", "fech", "oferta_compra", "oferta_venda", "negocios", "quantidade",
                                     "volume", "fatcot"])
    o = pd.DataFrame(opc, columns=["data", "serie", "raiz", "tipo", "fech", "oferta_compra", "oferta_venda", "negocios", "volume", "strike",
                                   "venc", "estilo"])
    t = pd.DataFrame(termo, columns=["data", "ticker", "prazo", "fech", "negocios", "volume"])
    for d in (v, o, t):
        d["data"] = pd.to_datetime(d.data, format="%Y%m%d")
    o["venc"] = pd.to_datetime(o.venc, format="%Y%m%d", errors="coerce")
    print(f"  {ano}: vista {len(v)}, opções {len(o)}, termo {len(t)}", flush=True)
    return v, o, t


def etapa_cotahist():
    anos = range(2014, pd.Timestamp.today().year + 1)
    with ThreadPoolExecutor(3) as ex:
        res = list(ex.map(cotahist, anos))
    v = pd.concat([r[0] for r in res], ignore_index=True)
    o = pd.concat([r[1] for r in res], ignore_index=True)
    t = pd.concat([r[2] for r in res], ignore_index=True)
    top = o.groupby("raiz").volume.sum().nlargest(25).index                # 25 ativos-objeto com mais volume em opções
    v.to_parquet(D / "b3_vista.parquet")
    o[o.raiz.isin(top)].to_parquet(D / "b3_opcoes.parquet")
    t.to_parquet(D / "b3_termo.parquet")
    print(f"vista {len(v)} | opções {o.raiz.isin(top).sum()} ({', '.join(top)}) | termo {len(t)}", flush=True)


# ----------------------------------------------------------------- Yahoo
ADR = {"PBR": "PETR3", "PBR-A": "PETR4", "VALE": "VALE3", "ITUB": "ITUB4", "BBD": "BBDC4", "ABEV": "ABEV3", "GGB": "GGBR4", "SBS": "SBSP3",
       "ERJ": "EMBJ3", "SID": "CSNA3", "CIG": "CMIG4", "BSBR": "SANB11", "UGP": "UGPA3", "SUZ": "SUZB3", "TIMB": "TIMS3", "BRFS": "BRFS3",
       "EBR": "ELET3", "BDORY": "BBAS3", "NU": None, "XP": None, "STNE": None, "PAGS": None}
LOCAIS = sorted({v for v in ADR.values() if v} | {"PETR3", "PETR4", "ITUB3", "ITUB4", "BBDC3", "BBDC4", "GGBR3", "GGBR4", "ELET3", "ELET6",
                                                   "CMIG3", "CMIG4", "USIM3", "USIM5", "TAEE3", "TAEE4", "SAPR3", "SAPR4", "KLBN3", "KLBN4",
                                                   "BRAP3", "BRAP4", "GOAU3", "GOAU4", "EMBR3", "BOVA11", "SMAL11", "IVVB11", "DIVO11"})
FX = ["EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X", "JPY=X", "CAD=X", "CHF=X", "NOK=X", "SEK=X", "MXN=X", "ZAR=X", "TRY=X", "INR=X",
      "IDR=X", "KRW=X", "CLP=X", "COP=X", "PLN=X", "HUF=X", "CZK=X", "SGD=X", "THB=X", "PHP=X", "ILS=X", "CNY=X", "BRL=X"]
ETF = ["SPY", "QQQ", "IWM", "EFA", "EEM", "ACWI", "VT", "EWZ", "EWW", "EZA", "EWJ", "EWY", "FXI", "MCHI", "INDA", "EWG", "EWU", "EWC", "EWA",
       "EWT", "EWH", "EWS", "EWL", "EWP", "EWI", "EWQ", "EWN", "EWD", "ECH", "EPU", "TUR", "EIDO", "THD", "EPHE", "KSA", "QAT", "AFK", "NGE",
       "VNM", "ARGT", "SHY", "IEI", "IEF", "TLT", "TIP", "LQD", "HYG", "JNK", "EMB", "EMLC", "BKLN", "MUB", "AGG", "BIL", "SGOV",
       "GLD", "SLV", "USO", "BNO", "UNG", "CPER", "DBA", "CORN", "SOYB", "WEAT", "DBB", "DBC", "PDBC", "URA", "PALL", "PPLT",
       "XLE", "XLF", "XLK", "XLV", "XLI", "XLU", "XLP", "XLY", "XLB", "XLRE", "XLC", "MNA", "SVXY", "VIXY", "VXX", "UVXY"]
IDX = ["^GSPC", "^VIX", "^VIX3M", "^VIX9D", "^VVIX", "^SKEW", "^PUT", "^BXM", "^IRX", "^TNX", "^FVX", "^TYX", "^BVSP", "^MOVE", "DX-Y.NYB",
       "BTC-USD", "ETH-USD", "CL=F", "GC=F", "HG=F", "NG=F", "ZC=F", "ZS=F", "ZW=F", "KC=F", "SB=F", "CT=F", "LE=F", "SI=F", "BZ=F"]


def yahoo(tk, ini="2005-01-01"):
    for t in range(3):
        try:
            j = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}", headers=H, timeout=60,
                             params={"period1": int(pd.Timestamp(ini).timestamp()), "period2": int(time.time()), "interval": "1d",
                                     "events": "div,splits"}).json()["chart"]["result"][0]
            ind = j["indicators"]
            c = ind["adjclose"][0]["adjclose"] if "adjclose" in ind else ind["quote"][0]["close"]
            s = pd.Series(c, index=pd.to_datetime(j["timestamp"], unit="s").normalize(), name=tk, dtype=float)
            return s[~s.index.duplicated(keep="last")].dropna()
        except (requests.RequestException, KeyError, TypeError, IndexError, ValueError):
            time.sleep(2 * (t + 1))
    print(f"  sem dados: {tk}", flush=True)
    return None


def etapa_yahoo():
    grupos = {"adr": [a for a in ADR], "br_local": [x + ".SA" for x in LOCAIS], "fx": FX, "etf": ETF, "idx": IDX}
    for nome, tks in grupos.items():
        with ThreadPoolExecutor(8) as ex:
            s = [x for x in ex.map(yahoo, tks) if x is not None]
        pd.concat(s, axis=1).to_parquet(D / f"y_{nome}.parquet")
        print(f"  yahoo {nome}: {len(s)}/{len(tks)}", flush=True)


# ----------------------------------------------------------------- FRED
PAISES = {"US": "USA", "EZ": "EZ", "GB": "GBR", "JP": "JPN", "AU": "AUS", "NZ": "NZL", "CA": "CAN", "CH": "CHE", "NO": "NOR", "SE": "SWE",
          "MX": "MEX", "ZA": "ZAF", "TR": "TUR", "IN": "IND", "ID": "IDN", "KR": "KOR", "CL": "CHL", "CO": "COL", "PL": "POL", "HU": "HUN",
          "CZ": "CZE", "IL": "ISR", "BR": "BRA", "CN": "CHN"}


def fred(serie):
    try:
        t = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={serie}", timeout=60).text
        d = pd.read_csv(io.StringIO(t))
        return pd.Series(pd.to_numeric(d.iloc[:, 1], errors="coerce").values, index=pd.to_datetime(d.iloc[:, 0]), name=serie).dropna()
    except Exception:
        return None


def etapa_fred():
    curtos = {k: f"IR3TIB01{v}M156N" for k, v in PAISES.items()}
    with ThreadPoolExecutor(6) as ex:
        s = dict(zip(curtos, ex.map(fred, curtos.values())))
    m = pd.DataFrame({k: v for k, v in s.items() if v is not None})
    m.to_parquet(D / "fred_juros_curtos.parquet")
    print(f"  juros curtos: {list(m.columns)} (faltam {[k for k, v in s.items() if v is None]})", flush=True)
    diarias = ["DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30", "T10Y2Y", "T10YIE", "T5YIE", "DFII10", "DFF", "SOFR", "BAMLH0A0HYM2",
               "BAMLC0A0CM", "BAMLEMCBPIOAS", "VIXCLS", "DTWEXBGS", "NFCI", "STLFSI4", "ICSA", "WALCL", "DCOILWTICO", "DEXBZUS"]
    with ThreadPoolExecutor(6) as ex:
        s = [x for x in ex.map(fred, diarias) if x is not None]
    pd.concat(s, axis=1).to_parquet(D / "fred_diario.parquet")
    print(f"  fred diário: {len(s)}/{len(diarias)}", flush=True)


# ----------------------------------------------------------------- CFTC COT
def etapa_cot():
    partes = []
    for ano in range(2010, pd.Timestamp.today().year + 1):
        for tipo, url in (("fin", f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{ano}.zip"),
                          ("com", f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{ano}.zip")):
            try:
                z = zipfile.ZipFile(io.BytesIO(get(url, timeout=180).content))
                d = pd.read_csv(z.open(z.namelist()[0]), low_memory=False)
                d["relatorio"] = tipo
                partes.append(d)
            except Exception as e:
                print(f"  COT {tipo} {ano}: {e}", flush=True)
    c = pd.concat(partes, ignore_index=True)
    keep = [x for x in c.columns if any(k in x for k in ("Market_and_Exchange", "Report_Date_as_YYYY-MM-DD", "CFTC_Contract_Market_Code",
                                                          "Open_Interest_All", "Lev_Money_Positions", "Asset_Mgr_Positions",
                                                          "M_Money_Positions", "Prod_Merc_Positions", "Dealer_Positions", "relatorio"))]
    c[keep].to_parquet(D / "cot.parquet")
    print(f"  COT: {len(c)} linhas, {c.filter(like='Market_and_Exchange').iloc[:, 0].nunique()} contratos", flush=True)


# ----------------------------------------------------------------- Polymarket
def etapa_poly():
    termos = ["fed", "interest rate", "recession", "brazil", "lula", "election", "inflation", "bitcoin", "oil", "tariff"]
    mercados = []
    for t in termos:
        try:
            r = get("https://gamma-api.polymarket.com/markets", params={"limit": 200, "order": "volumeNum", "ascending": "false",
                                                                         "closed": "true", "search": t}).json()
            r += get("https://gamma-api.polymarket.com/markets", params={"limit": 200, "order": "volumeNum", "ascending": "false",
                                                                          "closed": "false", "search": t}).json()
            mercados += r
        except Exception as e:
            print(f"  poly {t}: {e}", flush=True)
    m = pd.DataFrame(mercados).drop_duplicates("id")
    m = m[[c for c in ("id", "question", "slug", "volumeNum", "startDate", "endDate", "closed", "clobTokenIds", "outcomes") if c in m]]
    m = m.sort_values("volumeNum", ascending=False).head(400)
    hist = []
    for _, r in m.iterrows():
        try:
            tok = json.loads(r.clobTokenIds)[0]
            h = get("https://clob.polymarket.com/prices-history", params={"market": tok, "interval": "max", "fidelity": 1440}).json()["history"]
            if h:
                hist.append(pd.DataFrame(h).assign(id=r.id))
        except Exception:
            pass
    m.to_parquet(D / "poly_mercados.parquet")
    if hist:
        h = pd.concat(hist)
        h["data"] = pd.to_datetime(h.t, unit="s").dt.normalize()
        h.to_parquet(D / "poly_precos.parquet")
        print(f"  polymarket: {len(m)} mercados, {h.id.nunique()} com histórico, {h.data.min():%Y-%m} a {h.data.max():%Y-%m}", flush=True)


if __name__ == "__main__":
    e = sys.argv[1] if len(sys.argv) > 1 else "tudo"
    for nome, f in (("yahoo", etapa_yahoo), ("fred", etapa_fred), ("cot", etapa_cot), ("poly", etapa_poly), ("cotahist", etapa_cotahist)):
        if e in (nome, "tudo"):
            print(f"== {nome}", flush=True)
            try:
                f()
            except Exception as ex:
                print(f"  ERRO {nome}: {ex}", flush=True)
    print("pronto")
