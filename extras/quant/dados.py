"""
Coleta (e guarda em cache) todo o histórico público necessário para os backtests de crédito e juros:
  futuros B3 (DI1, DAP, DDI, FRC, DOL, WDO): ajuste, taxa e P&L por contrato, diário desde 2019 (boletim BVBG.086)
  debêntures: negócios diários da SND desde 2019 (PU médio, % do PU da curva, quantidade, nº de negócios) + cadastro
  balcão B3: negócio a negócio (DEB, CRI, CRA, LF, NC) com taxa, desde 2023
  índices: CDI, IPCA, PTAX (BCB), curvas pré e IPCA+ (Tesouro Direto), Treasury (treasury.gov)
Uso: python dados.py      (a 1a vez leva ~30-60 min; depois só baixa o que falta)
"""
import io
import os
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PASTA = Path(__file__).resolve().parent / "dados"
(PASTA / "futuros").mkdir(parents=True, exist_ok=True)
(PASTA / "balcao").mkdir(exist_ok=True)
(PASTA / "snd").mkdir(exist_ok=True)
DESDE = pd.Timestamp("2019-01-01")
HOJE = pd.Timestamp.today().normalize()
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"
os.environ.setdefault("PAINEL_DADOS", str(Path(os.environ.get("LOCALAPPDATA", ".")) / "cvm_cache"))
sys.path.insert(0, r"C:\Users\maxpn\OneDrive\Documents\Personal\itau_database")
import lookthrough_cvm as lt          # noqa: E402  (SND, Tesouro, BCB, treasury já prontos no painel)

FUT = re.compile(rb"<TckrSymb>((?:DI1|DAP|DDI|FRC|DOL|WDO)[FGHJKMNQUVXZ]\d\d)</TckrSymb>")
CAMPOS = ["AdjstdQt", "AdjstdQtTax", "PrvsAdjstdQt", "PrvsAdjstdQtTax", "AdjstdValCtrct", "OpnIntrst", "NtlFinVol", "FinInstrmQty"]


def get(url, tent=4, **kw):
    for i in range(tent):
        try:
            r = S.get(url, timeout=180, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == tent - 1:
                raise
            time.sleep(5 * (i + 1))


def dias_uteis():
    cdi = lt.sgs(12, f"{DESDE:%Y-%m}")
    return [d for d in cdi.index if d >= DESDE] + ([HOJE] if HOJE.weekday() < 5 and HOJE not in cdi.index else [])


# ------------------------------------------------------------------ futuros (boletim de preços B3)
def futuros_dia(d):
    f = PASTA / "futuros" / f"{d:%Y%m%d}.parquet"
    if f.exists():
        return
    try:
        z = zipfile.ZipFile(io.BytesIO(get(f"https://www.b3.com.br/pesquisapregao/download?filelist=PR{d:%y%m%d}.zip,").content))
        z2 = zipfile.ZipFile(io.BytesIO(z.read(z.namelist()[0])))
    except (requests.RequestException, zipfile.BadZipFile, IndexError):
        return
    linhas = []
    for n in z2.namelist():
        t = z2.read(n)
        for m in FUT.finditer(t):
            bloco = t[m.end(): t.find(b"</PricRpt>", m.end())]
            r = {"date": d, "ticker": m.group(1).decode()}
            for c in CAMPOS:
                v = re.search(rb"<" + c.encode() + rb"[^>]*>([-\d.]+)<", bloco)
                r[c] = float(v.group(1)) if v else np.nan
            linhas.append(r)
    pd.DataFrame(linhas).to_parquet(f)


def futuros():
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(futuros_dia, dias_uteis()[:-1]))
    fs = sorted((PASTA / "futuros").glob("*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)


# ------------------------------------------------------------------ debêntures: negócios SND (mensal)
def snd_mes(m):
    ini, fim = m, min(m + pd.offsets.MonthEnd(0), HOJE)
    f = PASTA / "snd" / f"{m:%Y%m}.parquet"
    if f.exists() and (fim < HOJE - pd.Timedelta(days=5)):
        return
    def baixa(a, b):                                   # mês inteiro; se o servidor falhar (500), semana a semana
        try:
            t = get("https://www.debentures.com.br/exploreosnd/consultaadados/mercadosecundario/precosdenegociacao_e.asp", tent=2,
                    params={"op_exc": "False", "emissor": "", "isin": "", "ativo": "", "dt_ini": f"{a:%Y%m%d}", "dt_fim": f"{b:%Y%m%d}"})
        except requests.RequestException:
            if (b - a).days <= 7:
                return []
            return [x for w in pd.date_range(a, b, freq="7D") for x in baixa(w, min(w + pd.Timedelta(days=6), b))]
        L = t.content.decode("latin1").splitlines()
        i = next((k for k, l in enumerate(L) if l.startswith("Data\t")), None)
        return [] if i is None else L[i + 1:]

    corpo = baixa(ini, fim)
    if not corpo:
        return
    d = pd.read_csv(io.StringIO("\n".join(corpo)), sep="\t", dtype=str, header=None).iloc[:, :10]
    d.columns = ["date", "emissor", "codigo", "isin", "qtd", "negocios", "pu_min", "pu_med", "pu_max", "pct_curva"]
    num = lambda s: pd.to_numeric(s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")
    d = d.assign(date=pd.to_datetime(d.date, dayfirst=True, errors="coerce"), **{c: num(d[c]) for c in ["qtd", "negocios", "pu_min", "pu_med", "pu_max", "pct_curva"]})
    d.dropna(subset=["date"]).to_parquet(f)


def snd():
    meses = pd.date_range(DESDE, HOJE, freq="MS")
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(snd_mes, meses))
    return pd.concat([pd.read_parquet(f) for f in sorted((PASTA / "snd").glob("*.parquet"))], ignore_index=True)


# ------------------------------------------------------------------ balcão B3: negócio a negócio com taxa
def balcao_dia(d):
    f = PASTA / "balcao" / f"{d:%Y%m%d}.parquet"
    if f.exists() and pd.Timestamp(f.stat().st_mtime, unit="s") > d + pd.Timedelta(days=1, hours=12):
        return
    r = S.post("https://arquivos.b3.com.br/bdi/table/export/csv?lang=pt-BR", timeout=300,
               json={"Name": "Trade", "Date": f"{d:%Y-%m-%d}", "FinalDate": f"{d:%Y-%m-%d}", "ClientId": "", "Filters": {}})
    t = r.content.decode("latin1").splitlines()
    i = next((k for k, l in enumerate(t) if l.count(";") > 5), None)
    if i is None:
        pd.DataFrame().to_parquet(f)
        return
    x = pd.read_csv(io.StringIO("\n".join(t[i:])), sep=";", dtype=str).iloc[:, :14]
    x.columns = ["tipo", "emissor", "codigo", "qtd", "pu", "vol", "taxa", "origem", "hora", "data", "id", "isin", "liq", "situacao"]
    x = x[x.tipo.isin(["DEB", "CRI", "CRA", "LF", "LFSN", "LFSC", "NC"]) & x.situacao.ne("Cancelado")]
    num = lambda s: pd.to_numeric(s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")
    x.assign(qtd=num(x.qtd), pu=num(x.pu), vol=num(x.vol), taxa=num(x.taxa), date=d)[
        ["date", "tipo", "emissor", "codigo", "isin", "qtd", "pu", "vol", "taxa", "origem"]].to_parquet(f)


def balcao():
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda d: balcao_dia(d) if d >= pd.Timestamp("2023-03-01") else None, dias_uteis()))
    fs = [f for f in sorted((PASTA / "balcao").glob("*.parquet")) if f.stat().st_size > 2000]
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)


# ------------------------------------------------------------------ índices e curvas
def indices():
    cdi = lt.sgs(12, f"{DESDE:%Y-%m}") / 100
    ptax = lt.sgs(1, f"{DESDE:%Y-%m}")
    ipca = lt.sgs(433, f"{DESDE - pd.DateOffset(months=2):%Y-%m}") / 100
    return pd.DataFrame({"cdi": cdi, "ptax": ptax.reindex(cdi.index).ffill()}), ipca


if __name__ == "__main__":
    t = time.time()
    print("índices...", flush=True)
    ind, ipca = indices()
    ind.to_parquet(PASTA / "indices.parquet")
    ipca.to_frame("ipca").to_parquet(PASTA / "ipca.parquet")
    print("cadastro SND...", flush=True)
    lt.snd_caracteristicas().reset_index().to_parquet(PASTA / "snd_cadastro.parquet")
    print("negócios SND (debêntures desde 2019)...", flush=True)
    snd().to_parquet(PASTA / "snd_negocios.parquet")
    print("futuros B3 desde 2019...", flush=True)
    futuros().to_parquet(PASTA / "futuros.parquet")
    print("balcão B3 desde 2023...", flush=True)
    balcao().to_parquet(PASTA / "balcao.parquet")
    print(f"pronto em {(time.time() - t) / 60:.0f} min", flush=True)
