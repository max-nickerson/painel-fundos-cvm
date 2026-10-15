"""Dados da frente i_arb_comm (fase 2: arbitragens estruturais, vol e ações x commodity fora do Brasil). Cache: nunca re-baixa.
  dados/i_arb_px.parquet     Yahoo: fechamento AJUSTADO (proventos) de classes de ações, dual-listed, holdings, A/H, preferenciais coreanas,
                             ações x commodities, futuros contínuos, ETFs de vol
  dados/i_arb_close.parquet  Yahoo: fechamento NÃO ajustado (mesmos tickers) e i_arb_vol.parquet: volume financeiro (moeda local)
  dados/i_arb_cboe.parquet   CBOE: índices de estratégia de opções (PUT, BXM, BXMD, BXY, CNDR, BFLY, CLL, PPUT, WPUT, PUTR, CMBO, VXTH...)
  dados/i_arb_v2x.parquet    STOXX: VSTOXX (V2TX) diário 1999+
  dados/i_arb_funding.parquet Binance: taxa de financiamento dos perpétuos USDT-M (8h) de BTC, ETH, SOL, BNB, XRP, DOGE
  dados/i_arb_cripto_d.parquet Binance: diário 00h UTC spot e perpétuo dos mesmos
"""
import io
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from base import D

H = {"User-Agent": "Mozilla/5.0 (pesquisa academica)"}

CLASSES = ["GOOG", "GOOGL", "BRK-A", "BRK-B", "FOX", "FOXA", "NWS", "NWSA", "FWONA", "FWONK", "LBRDA", "LBRDK", "BATRA", "BATRK",
           "LSXMA", "LSXMK", "UA", "UAA", "LEN", "LEN-B", "HEI", "HEI-A", "MOG-A", "MOG-B", "BF-A", "BF-B", "Z", "ZG", "GEF", "GEF-B",
           "LGF-A", "LGF-B", "CCL", "CUK", "CCL.L", "RIO", "UL", "UN",
           "HEIA.AS", "HEIO.AS", "LISN.SW", "LISP.SW", "VOW.DE", "VOW3.DE", "HEN.DE", "HEN3.DE", "BMW.DE", "BMW3.DE", "SRT.DE", "SRT3.DE",
           "FPE.DE", "FPE3.DE", "ATCO-A.ST", "ATCO-B.ST", "ERIC-A.ST", "ERIC-B.ST", "INVE-A.ST", "INVE-B.ST", "VOLV-A.ST", "VOLV-B.ST",
           "SKF-A.ST", "SKF-B.ST", "ESSITY-A.ST", "ESSITY-B.ST", "TIT.MI", "TITR.MI", "SCHN.SW", "SCHP.SW", "CARL-A.CO", "CARL-B.CO",
           "MAERSK-A.CO", "MAERSK-B.CO", "UHR.SW", "UHRN.SW", "RO.SW", "ROG.SW", "UNA.AS", "ULVR.L", "RIO.L", "RIO.AX", "BHP.L", "BHP.AX",
           "005930.KS", "005935.KS", "005380.KS", "005385.KS", "005387.KS", "051910.KS", "051915.KS", "066570.KS", "066575.KS",
           "000810.KS", "000815.KS", "090430.KS", "090435.KS", "003550.KS", "003555.KS", "051900.KS", "051905.KS", "006400.KS", "006405.KS",
           "009150.KS", "009155.KS"]
AH = {"ICBC": ("601398.SS", "1398.HK"), "CCB": ("601939.SS", "0939.HK"), "BOC": ("601988.SS", "3988.HK"), "ABC": ("601288.SS", "1288.HK"),
      "PingAn": ("601318.SS", "2318.HK"), "Sinopec": ("600028.SS", "0386.HK"), "PetroChina": ("601857.SS", "0857.HK"),
      "CMB": ("600036.SS", "3968.HK"), "ChinaLife": ("601628.SS", "2628.HK"), "Conch": ("600585.SS", "0914.HK"),
      "Shenhua": ("601088.SS", "1088.HK"), "Zijin": ("601899.SS", "2899.HK"), "Vanke": ("000002.SZ", "2202.HK"),
      "CITICSec": ("600030.SS", "6030.HK"), "BoCom": ("601328.SS", "3328.HK"), "Minsheng": ("600016.SS", "1988.HK"),
      "CPIC": ("601601.SS", "2601.HK"), "CRCC": ("601186.SS", "1186.HK"), "CREC": ("601390.SS", "0390.HK"), "CRRC": ("601766.SS", "1766.HK"),
      "AirChina": ("601111.SS", "0753.HK"), "ChinaShenhuaCoal": ("601898.SS", "1898.HK"), "Weichai": ("000338.SZ", "2338.HK"),
      "GreatWall": ("601633.SS", "2333.HK"), "Jiangxi Copper": ("600362.SS", "0358.HK"), "Chalco": ("601600.SS", "2600.HK")}
HOLD = ["NPN.JO", "PRX.AS", "0700.HK", "TCEHY", "PAH3.DE", "EXO.AS", "RACE.MI", "STLAM.MI", "RACE", "STLA", "FCAU", "CNH", "PHIA.AS", "PHG",
        "ABBN.SW", "AZN.L", "SEB-A.ST", "SAAB-B.ST", "EQT.ST", "NDA-SE.ST", "WRT1V.HE", "EPI-A.ST", "HUSQ-B.ST", "INDU-C.ST", "SAND.ST",
        "SHB-A.ST", "SCA-B.ST", "SKA-B.ST", "HM-B.ST", "GBLB.BR", "SGSN.SW", "RI.PA", "ADS.DE", "NK.PA", "UMI.BR", "MF.PA", "BVI.PA",
        "9984.T", "BABA", "TMUS", "ARM", "9434.T", "SFTBY", "J36.SI", "H78.SI", "C07.SI", "CDI.PA", "MC.PA", "KINV-B.ST", "TEL2-B.ST",
        "ZAL.DE", "SOF.BR", "HAL.AS", "BRK-B"]
COMM = ["VLO", "MPC", "PSX", "PBF", "DK", "DINO", "XOM", "CVX", "SHEL", "BP", "TTE", "PBR", "COP", "EQNR", "E", "SHEL.L", "BP.L", "TTE.PA",
        "BHP", "RIO", "FMG.AX", "VALE", "FCX", "SCCO", "GLEN.L", "AAL.L", "ANTO.L", "TECK", "GDX", "GDXJ", "NEM", "AEM", "NST.AX", "EVN.AX",
        "GOLD", "KGC", "CCJ", "NXE", "KAP.L", "URA", "URNM", "UEC", "DNN", "YCA.L", "U-U.TO", "SRUUF", "NTR", "MOS", "CF", "YAR.OL",
        "AAL", "DAL", "UAL", "LUV", "JETS", "RYAAY", "LHA.DE", "AF.PA", "X", "NUE", "STLD", "CLF", "MT", "TSN", "PPC", "HRL", "BTU", "AMR",
        "ARCH", "CEIX", "WHC.AX", "NHC.AX", "YAL.AX", "S32.AX", "CL=F", "BZ=F", "RB=F", "HO=F", "NG=F", "TIO=F", "HG=F", "GC=F", "SI=F",
        "HRC=F", "MTF=F", "LE=F", "GF=F", "HE=F", "ZC=F", "ZS=F", "ZM=F", "ZL=F", "ZW=F", "KE=F", "KC=F", "SB=F", "CT=F", "CC=F", "PL=F",
        "PA=F", "ALI=F", "OJ=F", "ZO=F", "ZR=F", "LBS=F", "GLD", "SLV", "USO", "BNO", "UNG", "CPER", "UGA", "CORN", "WEAT", "SOYB"]
VOL = ["SPY", "QQQ", "^GSPC", "^NDX", "^STOXX50E", "^N225", "^VIX", "^VIX3M", "^VIX9D", "^VVIX", "VXX", "VIXY", "SVXY", "SVIX", "UVXY",
       "VIXM", "ES=F", "NQ=F", "YM=F", "RTY=F", "NKD=F", "NIY=F", "^DJI", "^RUT", "IWM", "DIA", "EWJ", "^IRX"]
FX = ["HKD=X", "CNY=X", "KRW=X", "GBPUSD=X", "AUDUSD=X", "EURUSD=X", "CHF=X", "SEK=X", "ZAR=X", "JPY=X", "DKK=X", "SGD=X", "CAD=X", "NOK=X"]
ADRS_IN = ["INFY", "INFY.NS", "WIT", "WIPRO.NS", "HDB", "HDFCBANK.NS", "IBN", "ICICIBANK.NS", "RDY", "DRREDDY.NS", "INR=X"]


def yahoo3(tk, ini="2000-01-01"):
    for t in range(3):
        try:
            j = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}", headers={"User-Agent": "Mozilla/5.0"}, timeout=60,
                             params={"period1": int(pd.Timestamp(ini).timestamp()), "period2": int(time.time()), "interval": "1d",
                                     "events": "div,splits"}).json()["chart"]["result"][0]
            ind = j["indicators"]
            q = ind["quote"][0]
            ix = pd.to_datetime(j["timestamp"], unit="s").normalize()
            c = pd.Series(q["close"], index=ix, dtype=float)
            a = pd.Series(ind["adjclose"][0]["adjclose"], index=ix, dtype=float) if "adjclose" in ind else c
            v = pd.Series(q.get("volume"), index=ix, dtype=float) * c
            df = pd.DataFrame({"adj": a, "close": c, "vol": v})
            df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"])
            return tk, df if len(df) > 30 else None
        except (requests.RequestException, KeyError, TypeError, IndexError, ValueError):
            time.sleep(2 * (t + 1))
    return tk, None


def yahoo_todos():
    """Baixa só o que falta (tickers novos na lista e ainda não tentados); acrescenta às três tabelas."""
    tks = list(dict.fromkeys(CLASSES + [x for p in AH.values() for x in p] + HOLD + COMM + VOL + FX + ADRS_IN))
    ft = D / "i_arb_tentados.txt"
    feitos = dict(l.split("\t") for l in ft.read_text(encoding="utf-8").splitlines()) if ft.exists() else {}
    falta = [t for t in tks if t not in feitos]
    if not falta:
        return
    with ThreadPoolExecutor(8) as ex:
        res = [x for x in ex.map(yahoo3, falta)]
    ok = {k: v for k, v in res if v is not None}
    for col, nome in (("adj", "i_arb_px"), ("close", "i_arb_close"), ("vol", "i_arb_vol")):
        novo = pd.DataFrame({k: v[col] for k, v in ok.items()})
        f = D / f"{nome}.parquet"
        if f.exists():
            novo = pd.concat([pd.read_parquet(f), novo], axis=1)
        novo.sort_index().to_parquet(f)
    feitos.update({k: "ok" if v is not None else "sem dados" for k, v in res})
    ft.write_text("\n".join(f"{k}\t{v}" for k, v in feitos.items()), encoding="utf-8")
    print(f"  yahoo: {len(ok)}/{len(falta)}; sem dados: {[k for k, v in res if v is None]}", flush=True)


def cboe():
    f = D / "i_arb_cboe.parquet"
    if f.exists():
        return
    out = {}
    for x in ["PUT", "BXM", "BXMD", "BXY", "PPUT", "CNDR", "CLL", "BFLY", "WPUT", "PUTR", "CMBO", "VXTH", "BXMW", "SPEN"]:
        try:
            t = requests.get(f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{x}_History.csv", headers=H, timeout=60).text
            d = pd.read_csv(io.StringIO(t))
            out[x] = pd.Series(d.iloc[:, 1].astype(float).values, index=pd.to_datetime(d.iloc[:, 0], format="mixed"))
        except Exception as e:
            print("  cboe sem", x, e)
    pd.DataFrame(out).sort_index().to_parquet(f)


def v2x():
    f = D / "i_arb_v2x.parquet"
    if f.exists():
        return
    import subprocess                                    # requests falha na cadeia SSL do stoxx.com nesta máquina; curl usa o repositório do Windows
    t = subprocess.run(["curl", "-sL", "-m", "60", "-A", "Mozilla/5.0", "https://www.stoxx.com/document/Indices/Current/HistoricalData/h_v2tx.txt"],
                       capture_output=True, text=True).stdout
    d = pd.read_csv(io.StringIO(t), sep=";")
    s = pd.Series(d.iloc[:, 2].astype(float).values, index=pd.to_datetime(d.iloc[:, 0], dayfirst=True), name="V2TX")
    s[~s.index.duplicated()].to_frame().to_parquet(f)


CRIPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]


def binance():
    f1, f2 = D / "i_arb_funding.parquet", D / "i_arb_cripto_d.parquet"
    if not f1.exists():
        parts = []
        for s in CRIPTO:
            t0 = int(pd.Timestamp("2019-09-01").timestamp() * 1000)
            while True:
                k = requests.get("https://fapi.binance.com/fapi/v1/fundingRate", params={"symbol": s, "startTime": t0, "limit": 1000}, timeout=60).json()
                if not k:
                    break
                parts.append(pd.DataFrame({"sym": s, "t": pd.to_datetime([x["fundingTime"] for x in k], unit="ms"),
                                           "taxa": [float(x["fundingRate"]) for x in k]}))
                t0 = k[-1]["fundingTime"] + 1
                if len(k) < 1000:
                    break
            print("   funding", s, flush=True)
        pd.concat(parts, ignore_index=True).to_parquet(f1)
    if not f2.exists():
        parts = []
        for s in CRIPTO:
            for nome, url in (("spot", "https://api.binance.com/api/v3/klines"), ("perp", "https://fapi.binance.com/fapi/v1/klines")):
                t0 = int(pd.Timestamp("2017-08-01").timestamp() * 1000)
                while True:
                    k = requests.get(url, params={"symbol": s, "interval": "1d", "startTime": t0, "limit": 1000}, timeout=60).json()
                    if not k or not isinstance(k, list):
                        break
                    parts.append(pd.DataFrame({"sym": s, "mkt": nome, "t": pd.to_datetime([x[0] for x in k], unit="ms"),
                                               "abre": [float(x[1]) for x in k], "fech": [float(x[4]) for x in k],
                                               "vol_usd": [float(x[7]) for x in k]}))
                    t0 = k[-1][0] + 86400_000
                    if len(k) < 1000:
                        break
        pd.concat(parts, ignore_index=True).to_parquet(f2)


if __name__ == "__main__":
    for fn in (cboe, v2x, binance, yahoo_todos):
        fn()
        print(fn.__name__, "ok", flush=True)
