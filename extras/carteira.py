"""
Carteira de crédito (lista ativos_iam.xlsx): P&L de cada ativo em 1 semana, 1 mês e 6 meses, com os derivativos
aplicados aos ativos que eles protegem (DAP -> IPCA+, DI1 -> prefixado, DOL/DDI -> dólar). Só dados públicos grátis:
  B3 (negócios de balcão a cada 15 min, cadastro, ISINs, futuros ao vivo), ANBIMA (debêntures), Tesouro Direto (curvas),
  Banco Central (CDI, PTAX, IPCA), treasury.gov (curva americana), FINRA e TradingView (eurobonds).
Sem pesos: cada ativo vale o mesmo na carteira.
Uso:  python carteira.py      ->  http://localhost:7870   (a 1a vez baixa ~6 meses de negócios da B3: alguns minutos)
"""
import base64
import bisect
import io
import json
import os
import re
import threading
import time
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

PASTA = Path(__file__).resolve().parent
LISTA = Path(os.environ.get("CARTEIRA_LISTA") or next(
    (p for p in [PASTA / "ativos_iam.xlsx", PASTA / "ativos_iam.txt"] if p.exists()), PASTA / "ativos_iam.xlsx"))
CACHE = Path(os.environ.get("CARTEIRA_DADOS") or PASTA / "dados_carteira")
PORTA = int(os.environ.get("PORT", 7870))
DIAS = 130                                     # dias úteis de histórico (6 meses + folga)
PERIODOS = {"Hoje": 1, "1 semana": 5, "1 mês": 21, "6 meses": 126}
DERIV = re.compile(r"^(DI1|DAP|DDI|DOL|WDO|FRC)([FGHJKMNQUVXZ])(\d\d)$")
MESES = "FGHJKMNQUVXZ"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"
(CACHE / "b3").mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ utilidades
def get(url, metodo="GET", tent=3, timeout=120, **kw):
    for i in range(tent):
        try:
            r = S.request(metodo, url, timeout=timeout, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if i == tent - 1:
                raise
            time.sleep(3 * (i + 1))


def velho(f, horas=20):
    return not f.exists() or time.time() - f.stat().st_mtime > horas * 3600


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")


def b3_csv(nome, dia):
    """Tabela do Boletim Diário da B3 (arquivos.b3.com.br/bdi) exportada em CSV."""
    r = get("https://arquivos.b3.com.br/bdi/table/export/csv?lang=pt-BR", "POST", timeout=300,
            json={"Name": nome, "Date": f"{dia:%Y-%m-%d}", "FinalDate": f"{dia:%Y-%m-%d}", "ClientId": "", "Filters": {}})
    t = r.content.decode("latin1").splitlines()
    i = next((k for k, l in enumerate(t) if l.count(";") > 5), None)
    return pd.DataFrame() if i is None else pd.read_csv(io.StringIO("\n".join(t[i:])), sep=";", dtype=str)


# ------------------------------------------------------------------ índices, curvas e câmbio
def sgs(cod, desde):
    f = CACHE / f"sgs{cod}_{desde:%Y%m%d}.json"
    if velho(f, 6):
        f.write_text(get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados",
                         params={"formato": "json", "dataInicial": f"{desde:%d/%m/%Y}"}).text)
    d = pd.DataFrame(json.loads(f.read_text()))
    return pd.Series(d.valor.astype(float).values, index=pd.to_datetime(d.data, dayfirst=True)).sort_index()


def tesouro():
    """Curvas do Tesouro Direto (prefixado e IPCA+), taxa x prazo por dia."""
    f = CACHE / "tesouro.csv"
    if velho(f):
        f.write_bytes(get("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/"
                          "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv", timeout=300).content)
    d = pd.read_csv(f, sep=";", decimal=",")
    d = d[d["Tipo Titulo"].isin(["Tesouro Prefixado", "Tesouro IPCA+"])].copy()
    d["data"] = pd.to_datetime(d["Data Base"], dayfirst=True)
    d = d[d.data >= pd.Timestamp.today() - pd.Timedelta(days=400)]
    d["anos"] = (pd.to_datetime(d["Data Vencimento"], dayfirst=True) - d.data).dt.days / 365.25
    d["taxa"] = d[["Taxa Compra Manha", "Taxa Venda Manha"]].replace(0, np.nan).mean(axis=1)
    d["tipo"] = np.where(d["Tipo Titulo"].eq("Tesouro Prefixado"), "PRE", "IPCA")
    d = d.dropna(subset=["taxa"])
    d = d[d.anos >= 0.5].sort_values(["tipo", "data", "anos"])
    return {t: {k: (x.anos.values, x.taxa.values) for k, x in g.groupby("data")} for t, g in d.groupby("tipo")}


def treasury():
    ten = {"1 Mo": 1 / 12, "3 Mo": .25, "6 Mo": .5, "1 Yr": 1, "2 Yr": 2, "3 Yr": 3, "5 Yr": 5, "7 Yr": 7, "10 Yr": 10, "20 Yr": 20, "30 Yr": 30}
    partes = []
    for a in range(pd.Timestamp.today().year - 1, pd.Timestamp.today().year + 1):
        f = CACHE / f"ust_{a}.csv"
        if velho(f) and not (f.exists() and a < pd.Timestamp.today().year):
            try:
                f.write_bytes(get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                                  f"{a}/all?type=daily_treasury_yield_curve&field_tdr_date_value={a}&page&_format=csv").content)
            except requests.RequestException:
                pass
        if f.exists():
            partes.append(pd.read_csv(f))
    d = pd.concat(partes).assign(data=lambda x: pd.to_datetime(x.Date, format="%m/%d/%Y")).drop_duplicates("data")
    cols = [c for c in ten if c in d.columns]
    x = np.array([ten[c] for c in cols])
    return {r.data: (x[~np.isnan(v)], v[~np.isnan(v)]) for r, v in zip(d.itertuples(), d[cols].to_numpy(float)) if (~np.isnan(v)).sum() > 2}


class Curvas:
    """Taxa (% a.a.) da curva PRE, IPCA ou UST num dia, interpolada no prazo (anos). Depois do último fechamento,
    soma o deslocamento ao vivo dos futuros da B3 (DI1 -> PRE, DAP -> IPCA)."""

    def __init__(self, tes, ust, vivo):
        self.c = {**tes, "UST": ust}
        self.k = {t: sorted(v) for t, v in self.c.items()}
        self.vivo = vivo                                  # {tipo: (anos, delta em pp)}

    def __call__(self, tipo, dia, anos):
        ks = self.k.get(tipo)
        if not ks:
            return np.nan
        i = bisect.bisect_right(ks, dia) - 1
        if i < 0:
            return np.nan
        x, y = self.c[tipo][ks[i]]
        v = float(np.interp(np.clip(anos, x.min(), x.max()), x, y))
        if dia > ks[-1] and tipo in self.vivo:
            vx, vy = self.vivo[tipo]
            v += float(np.interp(anos, vx, vy))
        return v


def futuros_b3():
    """Futuros da B3 (15 min de atraso): taxa atual e ajuste anterior por contrato -> vencimentos e deslocamento de hoje."""
    venc, vivo = {}, {}
    for t in ["DI1", "DAP", "DDI", "DOL", "WDO"]:
        try:
            j = get(f"https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/{t}", timeout=30, tent=2).json()
        except (requests.RequestException, ValueError):
            continue
        xs = []
        for s in j.get("Scty", []):
            m = s.get("asset", {}).get("AsstSummry", {}).get("mtrtyCode")
            q = s.get("SctyQtn", {})
            if m:
                venc[s["symb"]] = pd.Timestamp(m)
                if t in ("DI1", "DAP") and q.get("curPrc") and q.get("prvsDayAdjstmntPric"):
                    xs.append(((pd.Timestamp(m) - pd.Timestamp.today()).days / 365.25, q["curPrc"] - q["prvsDayAdjstmntPric"]))
        if len(xs) > 2:
            xs.sort()
            vivo["PRE" if t == "DI1" else "IPCA"] = (np.array([a for a, _ in xs]), np.array([b for _, b in xs]))
    return venc, vivo


# ------------------------------------------------------------------ B3: cadastro, ISINs e negócios
def cadastro():
    f = CACHE / "cadastro.parquet"
    if velho(f):
        for k in range(8):                                                # o arquivo do dia às vezes vem incompleto
            d = b3_csv("InstrumentRegistration", pd.Timestamp.today() - pd.Timedelta(days=k))
            if len(d) > 1000 and (d.iloc[:, 3] == "DEB").sum() > 1000 and (d.iloc[:, 3] == "LF").sum() > 1000:
                break
        else:
            return pd.read_parquet(f) if f.exists() else d
        d.columns = ["cod", "isn", "emissor", "tipo", "incent", "serie", "emissao_n", "idx", "pct", "taxa", "base", "venc", "qtd",
                     "pu_emis", "restrito", "temis", "oferta"]
        d = d[d.tipo != "COE"]
        d.to_parquet(f)
    return pd.read_parquet(f)


def isins():
    """Base de ISINs da B3 (gratuita, diária): data de emissão, valor nominal, taxa e indexador."""
    f = CACHE / "isin.parquet"
    if velho(f, 24):
        i = get("https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetTextDownload/").json()["geralPt"]["id"]
        z = zipfile.ZipFile(io.BytesIO(get("https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetFileDownload/"
                                           + base64.b64encode(str(i).encode()).decode(), timeout=300).content))
        d = pd.read_csv(z.open("NUMERACA.TXT"), header=None, dtype=str, encoding="latin1", usecols=[2, 3, 5, 7, 9, 10, 12, 14, 15, 20, 40])
        d.columns = ["isn", "emi", "desc", "emissao", "venc", "taxa", "vn", "idx", "pct", "tipo", "mes"]
        d.to_parquet(f)
    return pd.read_parquet(f)


def negocios(dias):
    """Negócio a negócio do balcão B3 (atualiza a cada 15 min). Um arquivo por dia; o dia corrente é rebaixado após 15 min."""
    cols = ["tipo", "emissor", "cod", "qtd", "pu", "vol", "taxa", "origem", "hora", "data", "id", "isn", "liq", "situacao"]
    hoje = pd.Timestamp.today().normalize()

    def um(d):
        f = CACHE / "b3" / f"neg_{d:%Y%m%d}.parquet"
        fresco = f.exists() and (pd.Timestamp(f.stat().st_mtime, unit="s") > d + pd.Timedelta(days=1, hours=12)
                                 or (d == hoje and time.time() - f.stat().st_mtime < 900))
        if not fresco:
            try:
                x = b3_csv("Trade", d)
            except requests.RequestException:
                return pd.read_parquet(f) if f.exists() else None
            if len(x):
                x.columns = cols[:x.shape[1]]
                x = x[x.tipo.isin(["DEB", "CRI", "CRA", "LF", "LFSN", "LFSC", "NC", "CFF"]) & x.situacao.ne("Cancelado")]
                x = x.assign(qtd=num(x.qtd), pu=num(x.pu), vol=num(x.vol), taxa=num(x.taxa), data=pd.to_datetime(x.data, dayfirst=True))
            else:
                x = pd.DataFrame(columns=cols)
            x[["tipo", "cod", "isn", "qtd", "pu", "vol", "taxa", "origem", "data"]].to_parquet(f)
        return pd.read_parquet(f)

    with ThreadPoolExecutor(6) as ex:
        partes = [p for p in ex.map(um, dias) if p is not None and len(p)]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=["cod", "isn", "data", "taxa", "pu", "vol"])


def anbima():
    """Taxa indicativa ANBIMA das debêntures (o site guarda ~15 dias; o histórico local cresce a cada execução)."""
    hoje = pd.Timestamp.today().normalize()
    for d in pd.bdate_range(hoje - pd.Timedelta(days=25), hoje):
        f = CACHE / f"anbima_db{d:%y%m%d}.txt"
        if not f.exists():
            try:
                r = S.get(f"https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/db{d:%y%m%d}.txt", timeout=60)
                if r.status_code == 200 and "Código@".encode("latin1") in r.content:
                    f.write_bytes(r.content)
            except requests.RequestException:
                pass
    out = []
    for f in sorted(CACHE.glob("anbima_db*.txt")):
        l = f.read_bytes().decode("latin1").splitlines()
        i = next(j for j, x in enumerate(l) if x.startswith("Código@"))
        a = pd.read_csv(io.StringIO("\n".join(l[i:])), sep="@", dtype=str, usecols=[0, 6, 12]).set_axis(["cod", "taxa", "dur"], axis=1)
        out.append(a.assign(taxa=num(a.taxa), dur=num(a.dur) / 252, data=pd.Timestamp(f"20{f.stem[-6:-4]}-{f.stem[-4:-2]}-{f.stem[-2:]}")))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["cod", "taxa", "dur", "data"])


# ------------------------------------------------------------------ eurobonds: FINRA (histórico) + TradingView (agora)
def tradingview(isins_):
    if not isins_:
        return {}
    q = {"symbols": {"tickers": [f"BONDSCOM:{i}" for i in isins_]},
         "columns": ["description", "close", "yield_to_maturity", "modified_duration", "maturity_date"]}
    try:
        j = get("https://scanner.tradingview.com/bond/scan", "POST", json=q, timeout=60,
                headers={"Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"}).json()
    except (requests.RequestException, ValueError):
        return {}
    return {x["s"].split(":")[1]: dict(zip(q["columns"], x["d"])) for x in j.get("data", [])}


def finra(isins_, desde):
    f = CACHE / f"finra_{pd.Timestamp.today():%Y%m%d}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    B = "https://services-dynarep.ddwa.finra.org/public/reporting/v2/"
    out = []
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"})
        s.get(B + "group/Firm/name/ActiveIndividual/dynamiclookup/examCode", timeout=60)
        s.headers["X-XSRF-TOKEN"] = s.cookies.get("XSRF-TOKEN", "")
        for i in isins_:
            b = {"fields": ["cusip", "tradeDate", "lastSalePrice", "closingPrice"],
                 "compareFilters": [{"fieldName": "cusip", "fieldValue": i[2:11], "compareType": "EQUAL"}],
                 "dateRangeFilters": [{"startDate": f"{desde:%Y-%m-%d}", "endDate": f"{pd.Timestamp.today():%Y-%m-%d}", "fieldName": "tradeDate"}],
                 "sortFields": ["tradeDate"], "offset": 0, "limit": 5000}
            r = s.post(B + "data/group/FixedIncomeMarket/name/EndOfDayPriceYield", data=json.dumps(b), timeout=60)
            d = pd.DataFrame(json.loads(r.json()["returnBody"]["data"] or "[]"))
            if len(d):
                d = d.reindex(columns=["tradeDate", "closingPrice", "lastSalePrice"])
                p = pd.to_numeric(d.closingPrice, errors="coerce").fillna(pd.to_numeric(d.lastSalePrice, errors="coerce"))
                out.append(pd.DataFrame({"isn": i, "data": pd.to_datetime(d.tradeDate).dt.normalize(), "preco": p}))
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pass
    d = pd.concat(out, ignore_index=True).dropna() if out else pd.DataFrame(columns=["isn", "data", "preco"])
    d.to_parquet(f)
    return d


# ------------------------------------------------------------------ lista -> ativos identificados
def le_lista():
    """Códigos da planilha: colunas 'codigo'/'ISIN' de todas as abas (ou a 1a coluna de um .txt/.csv/.xlsx simples)."""
    if LISTA.suffix.lower() == ".txt":
        cod = LISTA.read_text(encoding="utf-8", errors="ignore").split()
    else:
        cod = []
        abas = pd.read_excel(LISTA, sheet_name=None, dtype=str)
        for df in abas.values():
            for c in df.columns:
                if str(c).strip().lower() in ("codigo", "isin", "ticker") or str(c).lower().startswith("isin ou"):
                    cod += df[c].dropna().tolist()
        if not cod:
            cod = next(iter(abas.values())).iloc[:, 0].dropna().tolist()
    vistos = []
    for c in (str(x).strip() for x in cod):
        if c and c not in vistos and "_" not in c and c.upper() == c and c.upper() not in ("NULL", "-"):
            vistos.append(c)
    return vistos


def venc_deriv(tk, vencs):
    if tk in vencs:
        return vencs[tk]
    t, m, a = DERIV.match(tk).groups()
    d = pd.Timestamp(2000 + int(a), MESES.index(m) + 1, 15 if t == "DAP" else 1)
    return d + pd.offsets.BDay(0)


def identifica(codigos, cad, isn, vencs):
    cad_cod = cad.drop_duplicates("cod").set_index("cod")
    cad_isin = cad[cad.isn.str.startswith("BR", na=False)].drop_duplicates("isn").set_index("isn")
    isn_i = isn.drop_duplicates("isn").set_index("isn")
    ativos, deriv, sem = {}, {}, []

    def taxa_idx(idx, pct, taxa, base_isin=False):
        idx = str(idx).upper()
        pct, taxa = pd.to_numeric(pct, errors="coerce"), pd.to_numeric(taxa, errors="coerce")
        if "DI" in idx or "SELIC" in idx:
            if pd.notna(taxa) and taxa > 50:                     # base de ISINs: 118 = 118% do CDI
                return "%DI", taxa
            if base_isin and pd.notna(taxa) and taxa > 15:       # base de ISINs: 23 num papel DI = 123% do CDI
                return "%DI", 100 + taxa
            if base_isin and pd.notna(taxa) and taxa > 5:        # base de ISINs: 13,4 numa LF "DI" = prefixada
                return "PRE", taxa
            if pd.notna(pct) and pct != 100 and (pd.isna(taxa) or taxa == 0):
                return "%DI", pct
            return "DI", (0.0 if pd.isna(taxa) else taxa)
        if "IPC" in idx:
            return "IPCA", taxa
        if "PRE" in idx:                                         # "pré" de 5,5% com CDI de 14% e PU no par = IPCA + 5,5%
            return ("IPCA", taxa) if pd.notna(taxa) and taxa < 8 else ("PRE", taxa)
        if "DOL" in idx:
            return "USD", taxa
        return "", taxa

    for c in codigos:
        m = DERIV.match(c)
        if m:
            deriv[c] = {"id": c, "classe": m.group(1), "venc": venc_deriv(c, vencs)}
            continue
        if c.startswith("BRBMEF") and c in isn_i.index:              # futuro identificado pelo ISIN -> vira o ticker
            r = isn_i.loc[c]
            if str(r.tipo) in ("DI1", "DAP", "DDI", "DOL", "WDO") and isinstance(r.mes, str) and len(r.mes) == 3:
                tk = f"{r.tipo}{r.mes}"
                if DERIV.match(tk):
                    deriv.setdefault(tk, {"id": tk, "classe": r.tipo, "venc": venc_deriv(tk, vencs)})
            continue
        if re.match(r"^(US|XS|US912)[A-Z0-9]{9}\d$", c) or re.match(r"^(USL|USN|USG|USP)[A-Z0-9]{8}\d$", c):
            tb = c.startswith("US912797") or c.startswith("US912796")
            ativos[c] = {"id": c, "isin": c, "cod": c, "cat": "T-bill" if tb else "Bond", "idx": "USD", "emissor": "", "taxa": np.nan,
                         "venc": pd.NaT, "emissao": pd.NaT, "vn": np.nan}
            continue
        r = cad_cod.loc[c] if c in cad_cod.index else (cad_isin.loc[c] if c in cad_isin.index else None)
        if r is not None:
            cod = c if c in cad_cod.index else cad[cad.isn == c].cod.iloc[0]
            isin = r.get("isn", r.name) if str(r.get("isn", r.name)).startswith("BR") else (c if c.startswith("BR") else "")
            idx, tx = taxa_idx(r.idx, num(pd.Series([r.pct])).iloc[0], num(pd.Series([r.taxa])).iloc[0])
            info = isn_i.loc[isin] if isin in isn_i.index else None
            cat = {"CFF": "Cota FIDC"}.get(r.tipo, r.tipo)
            if cat == "DEB" and str(r.incent).lower() == "true":
                cat = "DEBIN"
            ativos.setdefault(isin or cod, {
                "id": cod, "isin": isin, "cod": cod, "cat": cat, "idx": idx, "taxa": tx, "emissor": r.emissor,
                "venc": pd.to_datetime(r.venc, dayfirst=True, errors="coerce"),
                "emissao": pd.to_datetime(info.emissao, format="%Y%m%d", errors="coerce") if info is not None else pd.NaT,
                "vn": num(pd.Series([r.pu_emis])).iloc[0]})
            continue
        if c in isn_i.index:
            r = isn_i.loc[c]
            if c.startswith("BRSTN"):
                cat, idx, tx = "Título público", "SELIC", 0.0
            else:
                idx, tx = taxa_idx(r.idx, r.pct, r.taxa, base_isin=True)
                d = str(r.desc).upper()
                cat = ("LFSC" if "PERP" in d or str(r.venc)[:4] >= "2049" else "LFSN") if "LETRA FIN" in d and "SUBORD" in d else \
                      "LF" if "LETRA FIN" in d else "CDB" if "DEPOSITO" in d else "NC" if "NOTA COMERCIAL" in d else \
                      "Cota FIDC" if str(r.tipo) == "CTF" else "DEB" if str(r.tipo) == "DBS" else str(r.tipo)
            ativos.setdefault(c, {"id": c, "isin": c, "cod": "", "cat": cat, "idx": idx, "taxa": tx, "emissor": str(r.emi),
                                  "venc": pd.to_datetime(r.venc, format="%Y%m%d", errors="coerce"),
                                  "emissao": pd.to_datetime(r.emissao, format="%Y%m%d", errors="coerce"),
                                  "vn": pd.to_numeric(r.vn, errors="coerce")})
            continue
        sem.append(c)
    # LF só com ISIN: acha o código de negociação no cadastro (mesmo vencimento, taxa e emissor)
    lf = cad[cad.tipo.isin(["LF", "LFSN", "LFSC"])].assign(v=lambda x: pd.to_datetime(x.venc, dayfirst=True, errors="coerce"),
                                                           t=lambda x: num(x.taxa), p=lambda x: num(x.pct))
    usados = {a["cod"] for a in ativos.values()}
    for a in ativos.values():
        if a["cod"] or a["cat"] not in ("LF", "LFSN", "LFSC"):
            continue
        k = lf[(lf.v == a["venc"]) & ((lf.t - a["taxa"]).abs() < 1e-6) | (lf.v == a["venc"]) & ((lf.p - a["taxa"]).abs() < 1e-6)]
        k = k[~k.cod.isin(usados)]
        if k.emissor.nunique() == 1:
            a["cod"], a["emissor"] = k.cod.iloc[0], k.emissor.iloc[0]
            usados.add(a["cod"])
    return ativos, deriv, sem


# ------------------------------------------------------------------ modelo de retorno diário
def duracao(cat, anos, r):
    """Duration aproximada (anos) quando a ANBIMA não informa: título bullet = prazo/(1+r); com cupom/amortização = anuidade."""
    anos = min(max(anos, 0.0), 10.0)
    r = max(r, 1e-4)
    if cat in ("LF", "LFSN", "LFSC", "CDB", "NC", "Cota FIDC", "T-bill"):
        return anos / (1 + r)
    return (1 - (1 + r) ** -anos) / r


def ytm(preco, cupom, anos):
    """Yield (% a.a., semestral) de um bond com cupom pelo preço limpo, por bisseção (vetorizado)."""
    lo, hi = np.full(len(preco), -20.0), np.full(len(preco), 200.0)
    n = np.ceil(np.asarray(anos) * 2)
    for _ in range(60):
        y = (lo + hi) / 2
        k = np.arange(1, n.max() + 1)[None, :]
        t = k - (n[:, None] - np.asarray(anos)[:, None] * 2)            # períodos até cada pagamento
        fl = (1 + y[:, None] / 200) ** -t * (k <= n[:, None])
        pv = cupom / 2 * fl.sum(1) + 100 * (1 + y / 200) ** -(np.asarray(anos) * 2) - cupom / 2 * (n - np.asarray(anos) * 2)   # - juros corridos
        alto = pv > preco
        lo, hi = np.where(alto, y, lo), np.where(alto, hi, y)
    return (lo + hi) / 2


def mediana_pond(v, w):
    o = np.argsort(v)
    v, w = np.asarray(v)[o], np.asarray(w)[o]
    return v[np.searchsorted(np.cumsum(w), w.sum() / 2)]


def limpa(obs):
    """Tira picos isolados (negócio fora da curva do próprio ativo) e suaviza com a mediana das últimas 5 observações
    (papel ilíquido negocia a preços muito diferentes no mesmo dia)."""
    if len(obs) >= 3:
        x = obs.to_numpy()
        a, b = x[1:-1] - x[:-2], x[1:-1] - x[2:]
        th = np.maximum(0.5, 0.15 * np.abs(x[1:-1]))
        obs = obs[~np.r_[False, (np.abs(a) > th) & (np.abs(b) > th) & (np.sign(a) == np.sign(b)), False]]
    return obs.rolling(5, min_periods=1).median()


def calcula(ctx):
    dias, cdi, ptax, infl, cur = ctx["dias"], ctx["cdi"], ctx["ptax"], ctx["infl"], ctx["curvas"]
    hoje = dias[-1]
    cdi_aa = (1 + cdi) ** 252 - 1
    neg, an, tv, fin = ctx["neg"], ctx["anbima"], ctx["tv"], ctx["finra"]
    cdi_hist = ctx["cdi_hist"]
    acum = (1 + cdi_hist / 100).cumprod()
    res = {}
    for k, a in ctx["ativos"].items():
        cat, idx = a["cat"], a["idx"]
        T = (a["venc"] - hoje).days / 365.25 if pd.notna(a["venc"]) else np.nan
        out = pd.DataFrame(0.0, index=dias, columns=["base", "spread", "juros", "credito", "cambio", "hedge"])
        info = {"fonte": "", "obs": []}
        if cat == "Título público" or idx == "SELIC":
            out["base"] = cdi
            info["fonte"] = "rende o CDI (Tesouro Selic)"
            res[k] = (out, pd.Series(0.0, index=dias), 0.0, info)
            continue
        if idx in ("", None) or (np.isnan(T) and idx != "USD"):
            ctx["sem"].append(a["id"])
            continue
        if idx == "USD":
            t = tv.get(a["isin"], {})
            if pd.isna(a["venc"]) and t.get("maturity_date"):
                a["venc"] = pd.to_datetime(str(int(t["maturity_date"])), format="%Y%m%d")
                T = (a["venc"] - hoje).days / 365.25
            if np.isnan(T):
                ctx["sem"].append(a["id"])
                continue
            cup = re.search(r"(\d+(?:\.\d+)?)%", t.get("description") or "")
            cup = float(cup.group(1)) if cup else 0.0
            a["emissor"] = a["emissor"] or re.sub(r"\s+\d.*$", "", t.get("description") or "")
            a["taxa"] = cup
            ust = np.array([cur("UST", d, max(T + (hoje - d).days / 365.25, 0.08)) for d in dias])
            p = fin[(fin.isn == a["isin"]) & (fin.preco > 0)].drop_duplicates("data", keep="last").set_index("data").preco
            if t.get("close"):
                p.loc[hoje] = t["close"]
            p = p.sort_index().reindex(dias).ffill()
            fin_ = lambda v: v is not None and np.isfinite(v)
            y_now = t.get("yield_to_maturity") if fin_(t.get("yield_to_maturity")) else (ust[-1] if cat == "T-bill" else np.nan)
            D = t["modified_duration"] if fin_(t.get("modified_duration")) else duracao(cat, T, (y_now if fin_(y_now) else 5) / 100)
            dt = np.r_[1, np.diff(dias).astype("timedelta64[D]").astype(float)]
            base = (1 + ust / 100) ** (1 / 252) - 1
            juros = -D * np.r_[0, np.diff(ust)] / 100
            if cat == "T-bill" or p.notna().sum() < 5:
                s = (y_now - ust[-1]) if fin_(y_now) and cat != "T-bill" else 0.0
                r_usd = base + s / 100 / 252 + juros
                out["spread"] = s / 100 / 252
                info["fonte"] = "curva americana" if cat == "T-bill" else "TradingView (spread de hoje mantido)"
                sp = pd.Series(s, index=dias)
            else:
                pv = p.bfill().rolling(3, min_periods=1).median().to_numpy()      # fechamento FINRA oscila entre compra e venda
                r_usd = np.r_[0, np.diff(pv) / pv[:-1]] + cup / 100 * dt / 365 * 100 / np.r_[pv[0], pv[:-1]]
                anos = np.array([max(T + (hoje - d).days / 365.25, 0.05) for d in dias])
                sp = pd.Series(ytm(pv, cup, anos) - ust, index=dias)       # yield do preço (cupom semestral) - Treasury
                out["spread"] = (1 + sp / 100) ** (1 / 252) - 1
                out["credito"] = r_usd - base - out["spread"] - juros
                info["fonte"] = "FINRA (fechamento) + TradingView (agora)"
                info["obs"] = [[d.strftime("%Y-%m-%d"), round(float(x), 3)] for d, x in p.dropna().items()]
                info["preco"] = True
            out["base"], out["juros"] = base, juros
            fx = ptax.reindex(dias).ffill().bfill()
            fxr = (fx / fx.shift(1) - 1).fillna(0).to_numpy()
            out["cambio"] = (1 + r_usd) * fxr
            out["hedge"] = (cdi - base) - juros - out["cambio"]
            res[k] = (out, sp, D, info)
            continue
        # ---- renda fixa local: observações de taxa (ANBIMA > negócios B3) convertidas em spread
        taxa0 = a["taxa"] if pd.notna(a["taxa"]) else 0.0
        a_an = an[an.cod == a["cod"]] if a["cod"] else an.iloc[:0]
        D_now = float(a_an.dur.iloc[-1]) if len(a_an) and pd.notna(a_an.dur.iloc[-1]) else np.nan
        r0 = cdi_aa.iloc[-1] + taxa0 / 100 if idx in ("DI",) else (cdi_aa.iloc[-1] * taxa0 / 100 if idx == "%DI" else
                                                                      (taxa0 + (4.5 if idx == "IPCA" else 0)) / 100)
        if np.isnan(D_now):
            D_now = duracao(cat, T, r0)
        Dt = pd.Series([max(D_now + (hoje - d).days / 365.25 * (D_now / T if T > 0 else 1), 0.01) for d in dias], index=dias)

        def para_spread(taxa, d, D):
            if idx == "DI":
                return taxa
            if idx == "%DI":
                return (taxa / 100 - 1) * cdi_aa.get(d, cdi_aa.iloc[-1]) * 100
            return taxa - cur("IPCA" if idx == "IPCA" else "PRE", d, D)

        obs = {}
        n = neg[(neg.cod == a["cod"]) | (neg.isn == a["isin"]) & (a["isin"] != "")] if len(neg) else neg
        n = n[n.data.isin(dias)]
        com_taxa = n[n.taxa.notna() & (n.vol > 0)]
        for d, g in com_taxa.groupby("data"):
            obs[d] = para_spread(mediana_pond(g.taxa.values, g.vol.values), d, Dt[d])
        if not obs and len(n) and pd.notna(a["emissao"]) and pd.notna(a["vn"]) and idx in ("DI", "%DI", "PRE") and cat in ("LF", "LFSN", "LFSC", "CDB"):
            for d, g in n[n.pu > 0].groupby("data"):          # só PU (LF, NC): spread implícito pelo preço x PU par
                pu = mediana_pond(g.pu.values, g.vol.values)
                du = ((acum.index >= a["emissao"]) & (acum.index < d)).sum()
                du_rem = max(np.busday_count(d.date(), a["venc"].date()) * 0.965, 1)
                fat = acum.asof(d - pd.Timedelta(days=1)) / acum.asof(a["emissao"] - pd.Timedelta(days=1)) if du else 1
                if idx == "DI":
                    par = a["vn"] * fat * (1 + taxa0 / 100) ** (du / 252)
                    if abs(pu / par - 1) < 1e-4:
                        continue                                 # registro na curva do emissor: não é preço de mercado
                    obs[d] = ((1 + taxa0 / 100) / (pu / par) ** (252 / du_rem) - 1) * 100
                elif idx == "PRE":
                    du_tot = du + du_rem
                    y = ((a["vn"] * (1 + taxa0 / 100) ** (du_tot / 252) / pu) ** (252 / du_rem) - 1) * 100
                    obs[d] = y - cur("PRE", d, Dt[d])
            obs = {d: v for d, v in obs.items() if -5 < v < 30}
        s_obs = limpa(pd.Series(obs, dtype=float).sort_index())
        info["fonte"] = "negócios B3" if len(s_obs) else ""
        s_an = pd.Series({r.data: para_spread(r.taxa, r.data, Dt[r.data]) for r in a_an.itertuples()
                          if r.data in Dt.index and pd.notna(r.taxa)}, dtype=float)
        if len(s_an):                                             # ANBIMA manda; negócios calibrados pela diferença média para ela
            comum = s_an.index.intersection(s_obs.index)
            if len(comum) >= 2:
                s_obs = s_obs + float((s_an[comum] - s_obs[comum]).median())
            s_obs = pd.concat([s_obs[s_obs.index < s_an.index.min()], s_an]).sort_index() if len(s_obs) else s_an.sort_index()
            info["fonte"] = "ANBIMA + negócios B3" if info["fonte"] else "ANBIMA"
        if len(s_obs):
            sp = s_obs.reindex(dias).ffill().bfill()
        else:
            sp = pd.Series(para_spread(taxa0, hoje, D_now) if idx != "%DI" else (taxa0 / 100 - 1) * cdi_aa.iloc[-1] * 100, index=dias)
            info["fonte"] = "sem negócio: carrega na taxa de emissão"
        info["obs"] = [[d.strftime("%Y-%m-%d"), round(float(v), 3)] for d, v in s_obs.items()]
        out["credito"] = ((1 + sp.shift(1).fillna(sp.iloc[0]) / 100) / (1 + sp / 100)) ** Dt - 1    # forma exata: aguenta saltos grandes (ativo estressado)
        out["spread"] = (1 + sp / 100) ** (1 / 252) - 1
        if idx in ("DI", "%DI"):
            out["base"] = cdi
        else:
            tipo = "IPCA" if idx == "IPCA" else "PRE"
            cv = pd.Series([cur(tipo, d, Dt[d]) for d in dias], index=dias).ffill().bfill()
            out["base"] = (1 + cv / 100) ** (1 / 252) - 1
            if idx == "IPCA":
                out["base"] = (1 + out["base"]) * (1 + infl.reindex(dias).ffill().bfill()) - 1
            out["juros"] = -Dt * cv.diff().fillna(0) / 100
            out["hedge"] = (cdi - out["base"]) - out["juros"]
        res[k] = (out, sp, D_now, info)
    return res


# ------------------------------------------------------------------ hedge: que derivativo protege cada ativo
def protecoes(ativos, deriv, res, hoje):
    classe = {"IPCA": ["DAP"], "PRE": ["DI1"], "USD": ["DOL", "WDO", "DDI"]}
    lig = {}
    for k, (out, sp, D, info) in res.items():
        idx = ativos[k]["idx"]
        if idx not in classe:
            continue
        alvo = hoje + pd.Timedelta(days=365.25 * (max(D, 0.1) if np.isfinite(D) else 3))
        usados = []
        for c in classe[idx]:
            cs = [d for d in deriv.values() if d["classe"] == c]
            if cs:
                usados.append(min(cs, key=lambda d: abs((d["venc"] - alvo).days))["id"])
        if idx == "USD" and usados:
            fx = [u for u in usados if u[:3] in ("DOL", "WDO")][:1]
            usados = fx + [u for u in usados if u.startswith("DDI")]
        lig[k] = usados or [{"IPCA": "DAP", "PRE": "DI1", "USD": "DOL+DDI"}[idx] + " (não está na lista)"]
    return lig


# ------------------------------------------------------------------ montagem e cache em memória
ESTADO = {"status": "carregando", "log": [], "dados": None, "series": {}}


def log(m):
    ESTADO["log"].append(m)
    print("  " + m, flush=True)


def periodo(out, n):
    o = out.iloc[-n:]
    sem = o[["base", "spread", "juros", "credito", "cambio"]].sum(axis=1)
    com = sem + o.hedge
    tsem, tcom = float(np.prod(1 + sem) - 1), float(np.prod(1 + com) - 1)
    comp = o.sum()
    f = tsem / sem.sum() if abs(sem.sum()) > 1e-12 else 1.0
    r = {c: float(comp[c] * f) * 100 for c in ["base", "spread", "juros", "credito", "cambio"]}
    r.update(sem=tsem * 100, com=tcom * 100, hedge=(tcom - tsem) * 100)
    return r


def prepara():
    hoje = pd.Timestamp.today().normalize()
    log(f"Lista: {LISTA}")
    codigos = le_lista()
    log(f"{len(codigos)} códigos na lista")
    desde = hoje - pd.Timedelta(days=400)
    cdi = sgs(12, desde) / 100
    dias = list(cdi.index[-DIAS:])
    if hoje.weekday() < 5 and hoje not in cdi.index:
        dias.append(hoje)
    dias = pd.DatetimeIndex(dias)
    cdi = cdi.reindex(dias).ffill()
    log("Índices (CDI, PTAX, IPCA) e curvas (Tesouro, Treasury)...")
    ptax = sgs(1, desde)
    ipca = sgs(433, hoje - pd.Timedelta(days=500)) / 100
    infl = pd.Series({d: (1 + ipca.asof(d)) ** (1 / 21) - 1 for d in dias})
    vencs, vivo = futuros_b3()
    curvas = Curvas(tesouro(), treasury(), vivo)
    log("Cadastro e base de ISINs da B3...")
    cad, isn = cadastro(), isins()
    ativos, deriv, sem = identifica(codigos, cad, isn, vencs)
    emis = [a["emissao"] for a in ativos.values() if pd.notna(a["emissao"])]
    cdi_hist = sgs(12, max(min(emis), pd.Timestamp("2016-01-01")) if emis else desde)
    log(f"{len(ativos)} ativos, {len(deriv)} derivativos, {len(sem)} sem dado público. Negócios da B3 ({len(dias)} dias)...")
    neg = negocios(dias)
    chaves = {a["cod"] for a in ativos.values()} | {a["isin"] for a in ativos.values()}
    neg = neg[neg.cod.isin(chaves) | neg.isn.isin(chaves - {""})]
    log(f"{len(neg)} negócios dos ativos da lista. ANBIMA, FINRA e TradingView...")
    bonds = [a["isin"] for a in ativos.values() if a["idx"] == "USD"]
    ctx = {"dias": dias, "cdi": cdi, "ptax": ptax, "infl": infl, "curvas": curvas, "ativos": ativos, "neg": neg, "anbima": anbima(),
           "tv": tradingview(bonds), "finra": finra([b for b in bonds if not b.startswith("US912")], dias[0]), "cdi_hist": cdi_hist,
           "sem": sem}
    log("Calculando P&L...")
    res = calcula(ctx)
    lig = protecoes(ativos, deriv, res, dias[-1])
    linhas, series = [], {}
    for k, (out, sp, D, info) in res.items():
        a = ativos[k]
        txt = {"DI": f"CDI + {a['taxa']:.2f}%", "%DI": f"{a['taxa']:.0f}% CDI", "IPCA": f"IPCA + {a['taxa']:.2f}%",
               "PRE": f"{a['taxa']:.2f}% pré", "USD": f"US$ {a['taxa']:.2f}%", "SELIC": "Selic"}.get(a["idx"], "")
        linhas.append({"id": a["id"], "isin": a["isin"], "cat": a["cat"], "emissor": str(a["emissor"] or "").title()[:46], "idx": a["idx"],
                       "taxa": txt, "venc": a["venc"].strftime("%m/%Y") if pd.notna(a["venc"]) else "", "spread": round(float(sp.iloc[-1]), 2),
                       "dur": round(float(D), 2), "fonte": info["fonte"], "hedge_por": lig.get(k, []),
                       "res": {p: {c: round(v, 4) for c, v in periodo(out, n).items()} for p, n in PERIODOS.items()}})
        series[a["id"]] = (out, sp, info, a, lig.get(k, []))
    # carteira (pesos iguais) e derivativos
    todos = pd.DataFrame({k: v[0][["base", "spread", "juros", "credito", "cambio"]].sum(axis=1) for k, v in series.items()})
    hed = pd.DataFrame({k: v[0].hedge for k, v in series.items()})
    cart = {"datas": [d.strftime("%Y-%m-%d") for d in dias], "sem": todos.mean(axis=1).round(7).tolist(),
            "com": (todos + hed).mean(axis=1).round(7).tolist(), "cdi": cdi.round(7).tolist()}
    der = []
    for d in sorted(deriv.values(), key=lambda x: (x["classe"], x["venc"])):
        ks = [k for k, v in series.items() if d["id"] in v[4]]
        der.append({"id": d["id"], "classe": d["classe"], "venc": d["venc"].strftime("%d/%m/%Y"), "ativos": ks,
                    "res": {p: round(sum(periodo(series[k][0], n)["hedge"] for k in ks) / max(len(series), 1), 4) for p, n in PERIODOS.items()}})
    ESTADO["series"] = series
    ESTADO["dados"] = {"gerado": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"), "ate": dias[-1].strftime("%d/%m/%Y"),
                       "vivo": bool(vivo), "periodos": list(PERIODOS), "ativos": linhas, "carteira": cart, "derivativos": der,
                       "sem_dado": sem}
    ESTADO["status"] = "ok"
    log(f"Pronto: {len(linhas)} ativos com P&L.")


def roda():
    try:
        prepara()
    except Exception as e:                                       # mostra o erro na página em vez de travar
        import traceback
        traceback.print_exc()
        ESTADO.update(status="erro", erro=f"{type(e).__name__}: {e}")


app = FastAPI(title="Carteira")


@app.get("/api/dados")
def api_dados():
    if ESTADO["status"] != "ok":
        return JSONResponse({"status": ESTADO["status"], "log": ESTADO["log"][-6:], "erro": ESTADO.get("erro")})
    return JSONResponse({"status": "ok", **ESTADO["dados"]})


@app.get("/api/ativo/{aid}")
def api_ativo(aid: str):
    out, sp, info, a, lig = ESTADO["series"][aid]
    sem = out[["base", "spread", "juros", "credito", "cambio"]].sum(axis=1)
    return JSONResponse({"datas": [d.strftime("%Y-%m-%d") for d in out.index], "sem": sem.round(7).tolist(),
                         "hedge": out.hedge.round(7).tolist(), "cdi": ESTADO["dados"]["carteira"]["cdi"],
                         "comp": {c: out[c].round(7).tolist() for c in out.columns}, "spread": sp.round(3).tolist(),
                         "obs": info["obs"], "preco": info.get("preco", False), "hedge_por": lig})


@app.post("/api/atualizar")
def api_atualizar():
    if ESTADO["status"] != "carregando":
        ESTADO.update(status="carregando", log=[])
        threading.Thread(target=roda, daemon=True).start()
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def pagina():
    return HTML


HTML = r"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Carteira de crédito</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>
:root{--bg:#f5f6f8;--sf:#fff;--sf2:#f0f1f4;--ln:#e3e5ea;--t1:#14161a;--t2:#4d525c;--mu:#8a8f99;--ac:#eb6834;--acs:rgba(235,104,52,.12);
--sem:#8a8f99;--hed:#2a78d6;--com:#eb6834;--cdi:#14161a;--good:#0f7b3f;--bad:#c43d3d;--font:"Segoe UI",-apple-system,Roboto,Arial,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1012;--sf:#17191c;--sf2:#1f2226;--ln:#2a2d32;--t1:#f2f3f5;--t2:#b7bcc6;--mu:#858b96;
--hed:#5a9cf0;--cdi:#f2f3f5;--good:#2fbf6b;--bad:#ef6b6b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t1);font:14px/1.5 var(--font)}
.barra{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:10px 20px;background:var(--sf);border-bottom:1px solid var(--ln)}
.barra h1{font-size:16px;margin:0}.sub{color:var(--t2);font-size:12px}.esp{flex:1}
.chips{display:flex;gap:4px;flex-wrap:wrap}.chip{border:1px solid var(--ln);background:var(--sf);color:var(--t2);border-radius:999px;padding:5px 12px;cursor:pointer;font:inherit;font-size:13px}
.chip.sel{border-color:var(--ac);background:var(--acs);color:var(--ac);font-weight:600}
main{padding:16px 20px;max-width:1400px;margin:0 auto}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:14px}
.kpi,.card{background:var(--sf);border:1px solid var(--ln);border-radius:12px;padding:12px 14px}.kpi b{display:block;font-size:22px}.kpi span{color:var(--t2);font-size:12px}
.grid{display:grid;grid-template-columns:1.3fr 1fr;gap:14px;margin-bottom:14px}@media(max-width:900px){.grid{grid-template-columns:1fr}}
.card h3{margin:0 0 6px;font-size:14px}.card p.nota{margin:4px 0 0;color:var(--t2);font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:6px 8px;border-bottom:1px solid var(--ln);text-align:right;white-space:nowrap}
th{color:var(--t2);font-weight:600;cursor:pointer;position:sticky;top:0;background:var(--sf)}th:nth-child(-n+4),td:nth-child(-n+4){text-align:left}
tbody tr{cursor:pointer}tbody tr:hover{background:var(--sf2)}.pos{color:var(--good)}.neg{color:var(--bad)}.mu{color:var(--mu)}
.tab{max-height:560px;overflow:auto}.filtros{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
input{font:inherit;border:1px solid var(--ln);background:var(--sf);color:var(--t1);border-radius:8px;padding:6px 10px;min-width:220px}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;background:var(--sf2);color:var(--t2);margin-right:3px}
.tag.h{background:rgba(42,120,214,.13);color:var(--hed)}
#det{position:fixed;inset:0;background:rgba(0,0,0,.35);display:none;z-index:10}#det .painel{position:absolute;right:0;top:0;bottom:0;width:min(900px,100%);background:var(--bg);overflow:auto;padding:18px 20px}
.fecha{float:right;border:1px solid var(--ln);background:var(--sf);border-radius:8px;padding:4px 10px;cursor:pointer;color:var(--t1)}
.expl{background:var(--sf);border:1px solid var(--ln);border-left:4px solid var(--hed);border-radius:10px;padding:10px 12px;margin:10px 0;color:var(--t2)}
.leg{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--t2)}.leg i{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px}
#carga{padding:60px 20px;text-align:center;color:var(--t2)}
</style></head><body>
<div class="barra"><div><h1>Carteira de crédito</h1><div class="sub" id="sub">carregando…</div></div><div class="esp"></div>
<div class="chips" id="per"></div><div class="chips" id="modo"></div><button class="chip" id="atualiza" title="Baixa os negócios mais recentes (15 min)">Atualizar</button></div>
<main><div id="carga">Preparando os dados…<div id="log" class="sub"></div></div><div id="app" style="display:none">
<div class="kpis" id="kpis"></div>
<div class="grid"><div class="card"><h3>Carteira (cada ativo com o mesmo peso)</h3><div id="g_cart" style="height:300px"></div>
<div class="leg"><span><i style="background:var(--sem)"></i>sem derivativos</span><span><i style="background:var(--com)"></i>com derivativos</span><span><i style="background:var(--cdi)"></i>CDI</span></div></div>
<div class="card"><h3>De onde veio o retorno, por categoria (média dos ativos)</h3><div id="g_cat" style="height:360px"></div></div></div>
<div class="grid"><div class="card"><h3>Derivativos: o que cada contrato fez</h3><div id="g_der" style="height:280px"></div>
<p class="nota">Contribuição para a carteira = soma do P&L do hedge dos ativos que o contrato protege ÷ nº de ativos. Clique numa barra para ver os ativos.</p></div>
<div class="card"><h3>Spread x duration hoje</h3><div id="g_sd" style="height:300px"></div><p class="nota" id="fora"></p></div></div>
<div class="card"><div class="filtros"><input id="busca" placeholder="Buscar ativo, emissor ou ISIN…"><div class="chips" id="cats"></div></div>
<div class="tab"><table><thead><tr id="cab"></tr></thead><tbody id="corpo"></tbody></table></div>
<p class="nota" id="semdado"></p></div>
<div class="card" style="margin-top:14px"><h3>Como é calculado</h3><p class="nota">
<b>Retorno diário de cada ativo</b> = carrego do indexador (CDI, IPCA + curva real, curva pré ou Treasury) + carrego do spread − duration × variação da curva (juros) − duration × variação do spread (crédito) + variação do dólar (câmbio).
<b>Spread</b>: taxa indicativa da ANBIMA quando existe; senão, mediana (por volume) dos negócios do balcão B3 do dia, sem negócios fora da curva do próprio ativo e suavizada pela mediana das últimas 5 observações; LF e NC sem taxa: spread implícito pelo preço do negócio x PU par (emissão + CDI acumulado); sem negócio: taxa de emissão.
<b>Derivativos</b>: IPCA+ é protegido pelo DAP de vencimento mais próximo da duration, prefixado pelo DI1, dólar pelo DOL/WDO + DDI. O hedge troca o indexador e os juros por CDI: com derivativo = CDI + spread + crédito. Curvas pelo Tesouro Direto e treasury.gov; hoje, deslocadas pelo movimento ao vivo dos futuros da B3. Cupom cambial aproximado pela curva americana.</p></div>
</div></main>
<div id="det"><div class="painel" id="detp"></div></div>
<script>
const $=s=>document.querySelector(s),f2=v=>v==null||isNaN(v)?'–':(v>=0?'+':'')+v.toFixed(2)+'%',cls=v=>v>0.0001?'pos':v<-0.0001?'neg':'';
const COR={base:'#9aa0aa',spread:'#0f7b3f',juros:'#7a5af8',credito:'#c43d3d',cambio:'#d4a017',hedge:'#2a78d6'};
const NOME={base:'Indexador',spread:'Spread (carrego)',juros:'Juros',credito:'Crédito',cambio:'Câmbio',hedge:'Derivativo'};
let D,st={p:'1 mês',modo:'com',cat:'Todas',q:'',ord:'com',dir:-1};
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const lay=(o={})=>Object.assign({margin:{l:48,r:10,t:8,b:30},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{family:css('--font'),size:12,color:css('--t2')},
 xaxis:{gridcolor:css('--ln')},yaxis:{gridcolor:css('--ln'),zerolinecolor:css('--ln'),ticksuffix:'%'},showlegend:false,hovermode:'x unified'},o);
const cfg={displayModeBar:false,responsive:true};
function chips(el,ops,val,fn){el.innerHTML=ops.map(o=>`<button class="chip ${o[0]==val?'sel':''}" data-v="${o[0]}">${o[1]}</button>`).join('');
 el.onclick=e=>{const b=e.target.closest('button');if(b){fn(b.dataset.v)}}}
function acum(r,n){const o=[];let a=1;r.slice(-n).forEach(x=>{a*=1+x;o.push((a-1)*100)});return o}
async function carrega(){const r=await (await fetch('/api/dados')).json();
 if(r.status!=='ok'){ $('#log').innerHTML=(r.log||[]).join('<br>')+(r.erro?'<br><b>Erro: '+r.erro+'</b>':'');if(r.status!=='erro')setTimeout(carrega,2500);return}
 D=r;$('#carga').style.display='none';$('#app').style.display='';
 $('#sub').textContent=`${D.ativos.length} ativos · dados até ${D.ate}${D.vivo?' · futuros B3 ao vivo':''} · gerado ${D.gerado}`;desenha()}
function n(){return D.periodos.includes(st.p)?{'Hoje':1,'1 semana':5,'1 mês':21,'6 meses':126}[st.p]:21}
function desenha(){
 chips($('#per'),D.periodos.map(p=>[p,p]),st.p,v=>{st.p=v;desenha()});
 chips($('#modo'),[['com','Com derivativos'],['sem','Sem derivativos']],st.modo,v=>{st.modo=v;desenha()});
 const N=n(),C=D.carteira,dt=C.datas.slice(-N),cs=acum(C.sem,N),cc=acum(C.com,N),cd=acum(C.cdi,N),last=a=>a[a.length-1];
 const ret=st.modo=='com'?last(cc):last(cs);
 $('#kpis').innerHTML=[[f2(ret),'Carteira '+(st.modo=='com'?'com':'sem')+' derivativos · '+st.p],[f2(last(cd)),'CDI no período'],
  [(ret/last(cd)*100).toFixed(0)+'%','% do CDI'],[f2(last(cc)-last(cs)),'Efeito dos derivativos (pp)'],
  [D.ativos.filter(a=>a.fonte.includes('B3')||a.fonte.includes('ANBIMA')||a.fonte.includes('FINRA')).length+' de '+D.ativos.length,'ativos com preço de mercado']]
  .map(k=>`<div class="kpi"><b class="${k[0].startsWith('+')?'pos':k[0].startsWith('-')?'neg':''}">${k[0]}</b><span>${k[1]}</span></div>`).join('');
 Plotly.react('g_cart',[{x:dt,y:cs,name:'sem derivativos',line:{color:css('--sem'),width:2}},{x:dt,y:cc,name:'com derivativos',line:{color:css('--com'),width:2.5}},
  {x:dt,y:cd,name:'CDI',line:{color:css('--cdi'),width:1.5,dash:'dot'}}],lay({yaxis:{ticksuffix:'%',gridcolor:css('--ln'),tickformat:'.2f'}}),cfg);
 // por categoria: média dos componentes
 const cats=[...new Set(D.ativos.map(a=>a.cat))].sort();const comp=['base','spread','juros','credito','cambio','hedge'];
 const med=(c,k)=>{const xs=D.ativos.filter(a=>a.cat==c).map(a=>a.res[st.p][k]);return xs.reduce((s,x)=>s+x,0)/xs.length};
 Plotly.react('g_cat',comp.filter(k=>st.modo=='com'||k!='hedge').map(k=>({type:'bar',orientation:'h',y:cats,x:cats.map(c=>med(c,k)),name:NOME[k],marker:{color:COR[k]},
  hovertemplate:'%{y} · '+NOME[k]+': %{x:.2f}%<extra></extra>'})),lay({barmode:'relative',showlegend:true,legend:{orientation:'h',y:-0.15},margin:{l:90,r:10,t:8,b:40},
  xaxis:{ticksuffix:'%',gridcolor:css('--ln'),zerolinecolor:css('--t2')},yaxis:{autorange:'reversed',type:'category',dtick:1,automargin:true},hovermode:'closest'}),cfg);
 const der=D.derivativos.filter(d=>d.ativos.length);
 Plotly.react('g_der',[{type:'bar',x:der.map(d=>d.id),y:der.map(d=>d.res[st.p]),marker:{color:der.map(d=>d.res[st.p]>=0?css('--good'):css('--bad'))},
  customdata:der.map(d=>d.ativos.length),hovertemplate:'%{x}: %{y:.3f}% da carteira<br>protege %{customdata} ativos<extra></extra>'}],lay({hovermode:'closest',margin:{l:52,r:10,t:8,b:56},xaxis:{tickangle:-60,tickfont:{size:10},type:'category'},yaxis:{ticksuffix:'%',gridcolor:css('--ln'),tickformat:'.2f'}}),cfg);
 $('#g_der').on('plotly_click',e=>derivativo(der[e.points[0].pointIndex]));
 const sd=D.ativos.filter(a=>a.idx!='SELIC');
 Plotly.react('g_sd',cats.map((c,i)=>{const xs=sd.filter(a=>a.cat==c);return {type:'scatter',mode:'markers',name:c,x:xs.map(a=>a.dur),y:xs.map(a=>a.spread),text:xs.map(a=>a.id+' · '+a.emissor),
  marker:{size:8,opacity:.8},hovertemplate:'%{text}<br>duration %{x:.1f} · spread %{y:.2f}%<extra></extra>'}}),
  lay({showlegend:true,legend:{x:1.02,y:1,font:{size:11}},hovermode:'closest',xaxis:{title:{text:'duration (anos)',standoff:4},gridcolor:css('--ln')},yaxis:{ticksuffix:'%',gridcolor:css('--ln'),range:[-1,12]},margin:{l:44,r:10,t:8,b:40}}),cfg);
 $('#g_sd').on('plotly_click',e=>abre(e.points[0].text.split(' · ')[0]));
 const fora=sd.filter(a=>a.spread>12||a.spread<-1);$('#fora').textContent=fora.length?'Fora da escala (spread > 12%): '+fora.map(a=>a.id+' '+a.spread.toFixed(0)+'%').join(', '):'';
 chips($('#cats'),[['Todas','Todas'],...cats.map(c=>[c,c])],st.cat,v=>{st.cat=v;tabela()});
 $('#busca').oninput=e=>{st.q=e.target.value.toLowerCase();tabela()};tabela();
 $('#semdado').textContent=D.sem_dado.length?`Sem preço público (fora do P&L): ${D.sem_dado.length} códigos — ${D.sem_dado.slice(0,40).join(', ')}${D.sem_dado.length>40?'…':''}`:'';
}
function tabela(){
 const cols=[['id','Ativo'],['cat','Categoria'],['emissor','Emissor'],['taxa','Taxa de emissão'],['spread','Spread hoje'],['dur','Duration'],['sem','Sem deriv.'],['hedge','Derivativo'],['com','Com deriv.'],['xcdi','vs CDI'],['fonte','Fonte']];
 const cdiP=acum(D.carteira.cdi,n()).slice(-1)[0];
 let L=D.ativos.filter(a=>(st.cat=='Todas'||a.cat==st.cat)&&(!st.q||(a.id+a.emissor+a.isin).toLowerCase().includes(st.q)))
  .map(a=>({...a,sem:a.res[st.p].sem,hedge:a.res[st.p].hedge,com:a.res[st.p].com,xcdi:a.res[st.p][st.modo]-cdiP}));
 L.sort((a,b)=>{const x=a[st.ord],y=b[st.ord];return (typeof x=='string'?x.localeCompare(y):x-y)*st.dir});
 $('#cab').innerHTML=cols.map(c=>`<th data-k="${c[0]}">${c[1]}${st.ord==c[0]?(st.dir>0?' ▲':' ▼'):''}</th>`).join('');
 $('#cab').onclick=e=>{const k=e.target.dataset.k;if(!k)return;st.dir=st.ord==k?-st.dir:-1;st.ord=k;tabela()};
 $('#corpo').innerHTML=L.map(a=>`<tr data-id="${a.id}"><td><b>${a.id}</b></td><td><span class="tag">${a.cat}</span></td><td>${a.emissor}</td><td>${a.taxa}</td>
  <td>${a.idx=='SELIC'?'–':a.spread.toFixed(2)+'%'}</td><td>${a.dur.toFixed(1)}</td><td class="${cls(a.sem)}">${f2(a.sem)}</td>
  <td class="${cls(a.hedge)}">${a.hedge_por.length?f2(a.hedge)+' <span class="tag h">'+a.hedge_por.join('+')+'</span>':'<span class="mu">–</span>'}</td>
  <td class="${cls(a.com)}"><b>${f2(a.com)}</b></td><td class="${cls(a.xcdi)}">${f2(a.xcdi)}</td><td class="mu">${a.fonte}</td></tr>`).join('');
 $('#corpo').onclick=e=>{const t=e.target.closest('tr');if(t)abre(t.dataset.id)};
}
function fecha(){$('#det').style.display='none'}
$('#det').onclick=e=>{if(e.target.id=='det')fecha()};document.onkeydown=e=>{if(e.key=='Escape')fecha()};
async function abre(id){
 const a=D.ativos.find(x=>x.id==id);if(!a)return;const s=await (await fetch('/api/ativo/'+encodeURIComponent(id))).json();
 const N=n(),dt=s.datas.slice(-N),cs=acum(s.sem,N),ch=acum(s.sem.map((x,i)=>x+s.hedge[i]),N),hh=ch.map((x,i)=>x-cs[i]),cd=acum(s.cdi,N),r=a.res[st.p];
 const hed=a.hedge_por.length;
 const juros=r.juros,txt=hed?`<b>${a.hedge_por.join(' + ')}</b> protege este ativo. ${a.idx=='IPCA'?'O DAP troca o IPCA + juro real por CDI':a.idx=='PRE'?'O DI1 troca a taxa prefixada por CDI':'O dólar futuro e o DDI trocam o retorno em dólar (juros americanos + câmbio) por CDI'}:
  no período, juros ${f2(juros)} e câmbio ${f2(r.cambio)} no ativo; o derivativo fez <b class="${cls(r.hedge)}">${f2(r.hedge)}</b>, deixando ${f2(r.com)} (CDI ${f2(cd[cd.length-1])} + spread e crédito).`
  :`Ativo pós-fixado (${a.taxa}): já rende CDI + spread, não precisa de derivativo. O risco é o spread de crédito (duration ${a.dur.toFixed(1)}).`;
 $('#detp').innerHTML=`<button class="fecha" onclick="fecha()">Fechar ✕</button><h2 style="margin:0">${a.id} <span class="tag">${a.cat}</span></h2>
  <div class="sub">${a.emissor} · ${a.taxa} · venc. ${a.venc} · ISIN ${a.isin||'–'} · duration ${a.dur.toFixed(2)} · spread hoje ${a.spread.toFixed(2)}% · fonte: ${a.fonte}</div>
  <div class="kpis" style="margin-top:12px">${[[f2(r.sem),'Ativo sem derivativo'],[hed?f2(r.hedge):'–','Derivativo'],[f2(r.com),'Com derivativo'],[f2(r.com-cd[cd.length-1]),'vs CDI ('+st.p+')']]
   .map(k=>`<div class="kpi"><b class="${k[0].startsWith('+')?'pos':k[0].startsWith('-')?'neg':''}">${k[0]}</b><span>${k[1]}</span></div>`).join('')}</div>
  <div class="expl">${txt}</div>
  <div class="card"><h3>Retorno acumulado · ${st.p}</h3><div id="d1" style="height:280px"></div>
  <div class="leg"><span><i style="background:var(--sem)"></i>ativo sem derivativo</span>${hed?'<span><i style="background:var(--hed)"></i>derivativo</span>':''}<span><i style="background:var(--com)"></i>com derivativo</span><span><i style="background:var(--cdi)"></i>CDI</span></div></div>
  <div class="grid" style="margin-top:14px"><div class="card"><h3>De onde veio o P&L</h3><div id="d2" style="height:280px"></div></div>
  <div class="card"><h3>${s.preco?'Preço (US$) e spread':'Spread sobre o indexador'} · 6 meses</h3><div id="d3" style="height:280px"></div><p class="nota">Pontos = negócios/marcações observados; linha = spread usado (sem observação, repete o último).</p></div></div>
  <div class="card"><h3>P&L diário · ${st.p}</h3><div id="d4" style="height:240px"></div></div>`;
 $('#det').style.display='block';
 Plotly.newPlot('d1',[{x:dt,y:cs,name:'sem derivativo',line:{color:css('--sem'),width:2}},...(hed?[{x:dt,y:hh,name:'derivativo',line:{color:css('--hed'),width:2}}]:[]),
  {x:dt,y:ch,name:'com derivativo',line:{color:css('--com'),width:2.5}},{x:dt,y:cd,name:'CDI',line:{color:css('--cdi'),width:1.5,dash:'dot'}}],lay({yaxis:{ticksuffix:'%',gridcolor:css('--ln'),tickformat:'.2f'}}),cfg);
 const ks=['base','spread','juros','credito','cambio','hedge'].filter(k=>Math.abs(r[k])>1e-6);
 Plotly.newPlot('d2',[{type:'waterfall',orientation:'v',x:[...ks.map(k=>NOME[k]),'Total'],measure:[...ks.map(_=>'relative'),'total'],y:[...ks.map(k=>r[k]),0],
  text:[...ks.map(k=>f2(r[k])),f2(r.com)],textposition:'outside',connector:{line:{color:css('--ln')}},increasing:{marker:{color:css('--good')}},decreasing:{marker:{color:css('--bad')}},
  totals:{marker:{color:css('--com')}},cliponaxis:false,hovertemplate:'%{x}: %{y:.3f}%<extra></extra>'}],lay({hovermode:'closest',margin:{l:48,r:10,t:28,b:40},yaxis:{ticksuffix:'%',gridcolor:css('--ln'),automargin:true}}),cfg);
 const tr=[{x:s.datas,y:s.spread,name:'spread usado',line:{color:css('--com'),width:2,shape:'hv'},hovertemplate:'%{x}: %{y:.2f}%<extra></extra>'}];
 if(s.obs.length)tr.push({x:s.obs.map(o=>o[0]),y:s.obs.map(o=>o[1]),mode:'markers',name:s.preco?'preço':'observado',marker:{color:css('--hed'),size:6},yaxis:s.preco?'y2':'y',
  hovertemplate:'%{x}: %{y:.2f}'+(s.preco?'':'%')+'<extra></extra>'});
 Plotly.newPlot('d3',tr,lay({hovermode:'closest',yaxis:{ticksuffix:'%',gridcolor:css('--ln')},...(s.preco?{yaxis2:{overlaying:'y',side:'right',showgrid:false}}:{})}),cfg);
 Plotly.newPlot('d4',['base','spread','juros','credito','cambio','hedge'].filter(k=>s.comp[k].some(x=>Math.abs(x)>1e-9)).map(k=>({type:'bar',x:dt,y:s.comp[k].slice(-N).map(x=>x*100),name:NOME[k],marker:{color:COR[k]},
  hovertemplate:NOME[k]+': %{y:.3f}%<extra></extra>'})),lay({barmode:'relative',showlegend:true,legend:{orientation:'h',y:-0.2},yaxis:{ticksuffix:'%',gridcolor:css('--ln'),tickformat:'.3f'}}),cfg);
}
function derivativo(d){
 const L=D.ativos.filter(a=>d.ativos.includes(a.id)||d.ativos.includes(a.isin));
 $('#detp').innerHTML=`<button class="fecha" onclick="fecha()">Fechar ✕</button><h2 style="margin:0">${d.id} <span class="tag h">${d.classe}</span></h2>
  <div class="sub">vencimento ${d.venc} · protege ${d.ativos.length} ativos · contribuição para a carteira (${st.p}): ${f2(d.res[st.p])}</div>
  <div class="card" style="margin-top:12px"><h3>P&L do hedge em cada ativo protegido · ${st.p}</h3><div id="dd" style="height:${Math.max(240,L.length*22)}px"></div></div>
  <div class="card" style="margin-top:14px"><table><thead><tr><th>Ativo</th><th>Categoria</th><th>Emissor</th><th>Taxa</th><th>Sem deriv.</th><th>Derivativo</th><th>Com deriv.</th></tr></thead><tbody>
  ${L.map(a=>`<tr onclick="abre('${a.id}')"><td><b>${a.id}</b></td><td>${a.cat}</td><td>${a.emissor}</td><td>${a.taxa}</td><td class="${cls(a.res[st.p].sem)}">${f2(a.res[st.p].sem)}</td>
  <td class="${cls(a.res[st.p].hedge)}">${f2(a.res[st.p].hedge)}</td><td class="${cls(a.res[st.p].com)}"><b>${f2(a.res[st.p].com)}</b></td></tr>`).join('')}</tbody></table></div>`;
 $('#det').style.display='block';
 Plotly.newPlot('dd',[{type:'bar',orientation:'h',y:L.map(a=>a.id),x:L.map(a=>a.res[st.p].sem),name:'ativo',marker:{color:css('--sem')}},
  {type:'bar',orientation:'h',y:L.map(a=>a.id),x:L.map(a=>a.res[st.p].hedge),name:'derivativo',marker:{color:css('--hed')}}],
  lay({barmode:'relative',showlegend:true,legend:{orientation:'h',y:-0.1},hovermode:'closest',margin:{l:110,r:10,t:8,b:30},xaxis:{ticksuffix:'%',gridcolor:css('--ln')},yaxis:{autorange:'reversed'}}),cfg);
}
$('#atualiza').onclick=async()=>{await fetch('/api/atualizar',{method:'POST'});$('#app').style.display='none';$('#carga').style.display='';carrega()};
carrega();
</script></body></html>"""


if __name__ == "__main__":
    import uvicorn
    print("Preparando a carteira (a 1a vez baixa ~6 meses de negócios da B3; depois só o que mudou)...")
    threading.Thread(target=roda, daemon=True).start()
    threading.Timer(2, lambda: webbrowser.open(f"http://localhost:{PORTA}")).start()
    print(f"Página em http://localhost:{PORTA}  (deixe esta janela aberta; Ctrl+C para fechar)")
    uvicorn.run(app, host="127.0.0.1", port=PORTA, log_level="warning")
