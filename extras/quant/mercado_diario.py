"""Dados diarios de mercado (2018-06-01 -> hoje). Cache em dados/cache_mercado/, resumivel.
Uso: python mercado_diario.py [global|fred|acoes|all]"""
import sys, json, time, base64, io, os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd, requests

BASE = Path(__file__).parent / "dados"
CACHE = BASE / "cache_mercado"; CACHE.mkdir(parents=True, exist_ok=True)
INI = "2018-06-01"
UA = {"User-Agent": "Mozilla/5.0"}

def cached(name, fn):
    """Grava resultado bruto (json) no cache."""
    f = CACHE / f"{name}.json"
    if f.exists():
        return json.loads(f.read_text())
    try:
        out = fn()
    except Exception as e:
        print("falha", name, type(e).__name__); return None   # nao grava: tenta de novo na proxima
    f.write_text(json.dumps(out)); return out

# ---------- Yahoo ----------
def yahoo(tk):
    def get():
        p1 = int(pd.Timestamp(INI).timestamp()); p2 = int(time.time())
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}",
                         params=dict(period1=p1, period2=p2, interval="1d", events="div,splits"),
                         headers=UA, timeout=15)
        if r.status_code == 404: return {}
        r.raise_for_status()
        res = r.json()["chart"]["result"]
        if not res or "timestamp" not in res[0]: return {}
        res = res[0]; q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
        return dict(t=res["timestamp"], close=adj or q["close"], volume=q.get("volume"))
    d = cached("yh_" + tk.replace("^", "_").replace("=", "_"), get)
    if not d: return None
    idx = pd.to_datetime(d["t"], unit="s").shift(3, "h").normalize()  # BRL=X vem 23h UTC do dia anterior
    df = pd.DataFrame({"close": d["close"], "volume": d["volume"]}, index=idx)
    return df[~df.index.duplicated(keep="last")].dropna(subset=["close"])

GLOBAL = ["^BVSP", "^VIX", "^MOVE", "EWZ", "BRL=X", "DX-Y.NYB", "BZ=F", "CL=F", "GC=F", "HG=F",
          "^TNX", "^IRX", "^FVX", "^TYX", "HYG", "LQD", "EMB", "CEMB", "JNK", "^GSPC",
          "BOVA11.SA", "IMAB11.SA", "IRFM11.SA", "B5P211.SA", "DEBB11.SA"]

def run_global():
    with ThreadPoolExecutor(8) as ex: dfs = dict(zip(GLOBAL, ex.map(yahoo, GLOBAL)))
    ok = {k: v for k, v in dfs.items() if v is not None and len(v)}
    print("yahoo sem dados:", [k for k in GLOBAL if k not in ok])
    px = pd.DataFrame({k: v.close for k, v in ok.items()}).sort_index()
    vol = pd.DataFrame({k: v.volume for k, v in ok.items()}).sort_index()
    px.index.name = vol.index.name = "date"
    px.to_parquet(BASE / "mercado_global.parquet")
    vol.loc[:, vol.fillna(0).sum() > 0].to_parquet(BASE / "mercado_global_volume.parquet")
    print("mercado_global", px.shape, px.index.min().date(), px.index.max().date())

# ---------- FRED (sem User-Agent de browser: FRED derruba a conexao) ----------
FRED = ["DGS2", "DGS5", "DGS10", "DGS30", "T10Y2Y", "BAMLH0A0HYM2", "BAMLC0A0CM",
        "BAMLEMCBPIOAS", "BAMLEMHBHYCRPIOAS", "VIXCLS", "DTWEXBGS"]

def run_fred():
    def one(s):
        txt = cached("fred_" + s, lambda: requests.get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv", params=dict(id=s, cosd=INI), timeout=60).text)
        if not txt: return None
        d = pd.read_csv(io.StringIO(txt), index_col=0, parse_dates=True, na_values=".")
        return d.iloc[:, 0].rename(s)
    with ThreadPoolExecutor(4) as ex: ss = [s for s in ex.map(one, FRED) if s is not None]
    df = pd.concat(ss, axis=1).sort_index(); df.index.name = "date"
    df.to_parquet(BASE / "fred.parquet")
    print("fred", df.shape, df.index.min().date(), df.index.max().date())

# ---------- Acoes dos emissores ----------
def b3_empresas():
    def page(n):
        p = base64.b64encode(json.dumps({"language": "pt-br", "pageNumber": n, "pageSize": 120}).encode()).decode()
        r = requests.get("https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetInitialCompanies/" + p,
                         headers=UA, timeout=30); r.raise_for_status(); return r.json()
    first = cached("b3_p1", lambda: page(1))
    rows = list(first["results"])
    for n in range(2, first["page"]["totalPages"] + 1):
        rows += cached(f"b3_p{n}", lambda: page(n))["results"]
    return pd.DataFrame(rows)

def run_acoes():
    cad = pd.read_parquet(BASE / "snd_cadastro.parquet")
    cnpjs = cad.cnpj.astype(str).str.zfill(14).drop_duplicates()
    b3 = b3_empresas()
    b3 = b3[b3.cnpj.str.len() > 0].assign(cnpj=lambda d: d.cnpj.str.zfill(14))
    # match por CNPJ exato e, se nao houver, pela raiz (8 digitos: matriz/filial)
    exato = b3.drop_duplicates("cnpj").set_index("cnpj").issuingCompany
    raiz = b3.assign(r=b3.cnpj.str[:8]).drop_duplicates("r").set_index("r").issuingCompany
    cod = cnpjs.map(exato).fillna(cnpjs.str[:8].map(raiz))
    m = pd.DataFrame({"cnpj": cnpjs, "codigo": cod}).dropna()
    print("emissores", len(cnpjs), "| com codigo B3", len(m))

    tks = [f"{c}{s}.SA" for c in m.codigo.unique() for s in ("3", "4", "11")]
    with ThreadPoolExecutor(8) as ex: dfs = dict(zip(tks, ex.map(yahoo, tks)))
    def melhor(c):
        cand = {t: d for t in (f"{c}3.SA", f"{c}4.SA", f"{c}11.SA")
                if (d := dfs.get(t)) is not None and len(d) > 20}
        return max(cand, key=lambda t: (cand[t].volume * cand[t].close).sum()) if cand else None
    m["ticker"] = m.codigo.map({c: melhor(c) for c in m.codigo.unique()})
    m = m.dropna(subset=["ticker"])
    m[["cnpj", "ticker"]].to_csv(BASE / "acoes_mapa.csv", index=False)
    px = pd.DataFrame({r.cnpj: dfs[r.ticker].close for r in m.itertuples()}).sort_index()
    px.index.name = "date"; px.to_parquet(BASE / "acoes_diario.parquet")
    print("acoes: emissores com acao", px.shape[1], "| tickers", m.ticker.nunique(),
          px.index.min().date(), px.index.max().date())

# ---------- B3: superficie de vol de dolar (so publica o ultimo dia; sem historico) ----------
def run_voldolar():
    """Snapshot diario: rodar todo dia util para acumular historico em dados/b3_vol_dolar/."""
    import zipfile
    r = requests.get("https://www.b3.com.br/data/files/16/35/6A/F9/623589100A29E189AC094EA8/"
                     "Superficie-de-volatilidade-de-dolar.zip", headers=UA, timeout=60)
    z = zipfile.ZipFile(io.BytesIO(r.content)); d = BASE / "b3_vol_dolar"; d.mkdir(exist_ok=True)
    for n in z.namelist(): (d / n).write_bytes(z.read(n)); print("vol dolar:", n)

if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else "all"
    for nome, f in [("global", run_global), ("fred", run_fred), ("acoes", run_acoes), ("voldolar", run_voldolar)]:
        if alvo in (nome, "all"): f()
