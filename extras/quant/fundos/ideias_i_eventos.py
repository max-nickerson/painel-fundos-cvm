"""
Frente I_EVENTOS (fase 2): as estratégias de EVENTOS do Brasil replicadas nos EUA, Europa e Ásia.
  python ideias_i_eventos.py dados [indice wiki 8k cap11 yahoo]   -> baixa/atualiza (cache em dados/, nunca re-baixa)
  python ideias_i_eventos.py [IE01 IE02 ...]                       -> roda os fundos e salva resultado/ideias_i_eventos.pkl
Fontes: SEC EDGAR (full-index form.gz, submissions JSON com itens do 8-K, busca textual EFTS), Wikipédia (mudanças de índices,
com a data do comunicado lida da referência), yfinance (Close+Volume). User-Agent genérico de pesquisa (nunca e-mail pessoal).
Regra: sinal na data em que a informação ficou PÚBLICA (arquivamento SEC / comunicado do índice); decisão no fechamento desse dia,
execução no fechamento seguinte (o motor desloca 1+lag).
"""
import gzip
import io
import json
import pickle
import re
import sys
import time
import urllib.parse
import warnings

import numpy as np
import pandas as pd
import requests

from base import CDI, D, DIAS, DIAS_US, ETF, IDX, TB_US, brl, limpa
from ideias_global import H, SEC, _get, baixa_precos, cart, cik_ticker, episodios

warnings.filterwarnings("ignore")
OUT = D.parent / "resultado"

# =============================================================== DADOS
FORMAS_IE = {"SC 13D", "SCHEDULE 13D", "SC TO-I", "424B4", "424B5", "424B1", "S-1", "F-1"}


def baixa_indice_ie(ini=2006):
    """EDGAR full-index (form.gz) -> 13D, tender do emissor, prospectos (424B1/4/5) e registros de IPO. dados/sec_indice_ie.parquet"""
    f = D / "sec_indice_ie.parquet"
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
            for l in gzip.decompress(r.content).decode("latin-1").splitlines():
                fm = l[:17].strip()
                if fm in FORMAS_IE:
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


# ---------- Wikipédia: mudanças de índices (data efetiva + data do comunicado lida da referência)
MESES = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                                         "november", "december"])}
MESES_FR = {m: i + 1 for i, m in enumerate(["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
                                            "novembre", "décembre"])}
RX_DATA = r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})"


def _wiki(lang, pag):
    r = requests.get(f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(pag)}", headers=H, timeout=60)
    return r.text


def _refs(html):
    """número da nota -> data de publicação citada (antes de 'Retrieved'/'Archived') = data do comunicado."""
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html, "lxml")
    out = {}
    for li in s.select("ol.references > li"):
        t = li.get_text(" ", strip=True)
        t = re.split(r"Retrieved|Archived", t)[0]
        m = re.findall(RX_DATA, t)
        if m:
            mo, d, y = m[-1]
            out[li.get("id", "")] = pd.Timestamp(int(y), MESES[mo.lower()], int(d))
    return out, s


def _tabela_com_refs(html, n_col_ref, cabecalho):
    """Lê a tabela de mudanças expandindo rowspan, mantendo o vínculo linha -> datas das notas de rodapé (todas as células da linha)."""
    refs, s = _refs(html)
    tab = None
    for t in s.select("table.wikitable"):
        th = " ".join(x.get_text(" ", strip=True) for x in t.select("tr")[0].select("th"))
        if all(c in th for c in cabecalho):
            tab = t
            break
    pend = {}                                                     # coluna -> (linhas restantes, texto, notas)
    linhas = []
    for tr in tab.select("tr"):
        if tr.find("th") and not tr.find("td"):
            continue
        cel, col, it = [], 0, iter(tr.find_all(["td", "th"]))
        while True:
            if col in pend:
                k, txt, nt = pend[col]
                cel.append((txt, nt))
                pend[col] = (k - 1, txt, nt)
                if k - 1 == 0:
                    del pend[col]
                col += 1
                continue
            td = next(it, None)
            if td is None:
                break
            txt = re.sub(r"\[[^\]]*\]", "", td.get_text(" ", strip=True)).strip()
            nt = [a.get("href", "")[1:] for a in td.select("sup.reference a")]
            rs = int(re.sub(r"\D", "", td.get("rowspan", "1")) or 1)
            if rs > 1:
                pend[col] = (rs - 1, txt, nt)
            cel.append((txt, nt))
            col += 1
        an = [refs[n] for _, nt in cel for n in nt if n in refs]
        linhas.append(([c for c, _ in cel], an))
    return linhas


def _anuncio(an, ef):
    """Data do comunicado = a nota mais recente com data <= efetiva e no máximo 60 dias antes (senão NaT: usar só a data efetiva)."""
    ok = [d for d in an if ef == ef and ef - pd.Timedelta(days=60) <= d <= ef]
    return max(ok) if ok else pd.NaT


def wiki_mudancas():
    """dados/wiki_indices.parquet: indice, efetiva, anuncio (do comunicado, quando a referência traz a data), entra, sai, motivo."""
    f = D / "wiki_indices.parquet"
    if f.exists():
        return pd.read_parquet(f)
    out = []
    # S&P 500 ----------------------------------------------------------------
    html = _wiki("en", "Historical components of the S&P 500")
    for txt, an in _tabela_com_refs(html, 6, ["Effective Date", "Added", "Removed"]):
        if len(txt) == 7:
            ef = pd.to_datetime(txt[0], errors="coerce")
            out.append(("SP500", ef, _anuncio(an, ef), txt[1], txt[3], txt[5], txt[2], txt[4]))
    # Nasdaq-100 ---------------------------------------------------------------
    html = _wiki("en", "Historical components of the Nasdaq-100")
    for txt, an in _tabela_com_refs(html, 5, ["Date", "Added", "Removed"]):
        if len(txt) == 6:
            ef = pd.to_datetime(txt[0], errors="coerce")
            out.append(("NDX", ef, _anuncio(an, ef), txt[1], txt[3], txt[5], txt[2], txt[4]))
    # DAX (de) -----------------------------------------------------------------
    t = pd.read_html(io.StringIO(_wiki("de", "DAX")))
    x = [a for a in t if str(a.columns[0]).startswith("Datum") and a.shape[1] == 4][0]
    for _, l in x.iterrows():
        out.append(("DAX", pd.to_datetime(str(l.iloc[0])[:10], format="%d.%m.%Y", errors="coerce"), pd.NaT, "", "", str(l.iloc[3]),
                    str(l.iloc[2]), str(l.iloc[1])))
    # CAC 40 (fr) --------------------------------------------------------------
    t = pd.read_html(io.StringIO(_wiki("fr", "CAC 40")))
    x = [a for a in t if list(a.columns[:3]) == ["Date", "Valeur entrante", "Valeur sortante"]][0]
    for _, l in x.iterrows():
        m = re.match(r"(\d{1,2})(?:er)?\s+(\w+)\s+(\d{4})", str(l.iloc[0]).replace("\xa0", " "))
        ef = pd.Timestamp(int(m.group(3)), MESES_FR.get(m.group(2).lower(), 1), int(m.group(1))) if m and m.group(2).lower() in MESES_FR else pd.NaT
        out.append(("CAC", ef, pd.NaT, "", "", "", re.sub(r"\[.*?\]", "", str(l.iloc[1])), re.sub(r"\[.*?\]", "", str(l.iloc[2]))))
    # NIFTY 50 e SENSEX (en) ------------------------------------------------------
    for pag, nome in (("NIFTY 50", "NIFTY"), ("SENSEX", "SENSEX")):
        t = pd.read_html(io.StringIO(_wiki("en", pag)))
        for a in t:
            cols = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in a.columns]
            if any("excluded" in c or "removed" in c for c in cols) and any("replace" in c.lower() for c in cols):
                ce = [i for i, c in enumerate(cols) if "excluded" in c or "removed" in c][0]
                ci = [i for i, c in enumerate(cols) if "included" in c or "Replaced by" in c][0]
                cd = [i for i, c in enumerate(cols) if "Date" in c][0]
                for _, l in a.iterrows():
                    out.append((nome, pd.to_datetime(str(l.iloc[cd]), errors="coerce"), pd.NaT, "", "", "", str(l.iloc[ci]), str(l.iloc[ce])))
    w = pd.DataFrame(out, columns=["indice", "efetiva", "anuncio", "entra", "sai", "motivo", "entra_nome", "sai_nome"])
    w = w[w.efetiva.notna()]
    for c in ["entra", "sai"]:
        w[c] = w[c].replace({"nan": "", "None": ""}).fillna("").str.replace(".", "-", regex=False).str.strip()
    w.to_parquet(f)
    return w


# ---------- EDGAR busca textual (EFTS, 2001+): devolve, por documento, formulário, data, CIKs e nomes com o ticker ATUAL entre parênteses
def _fts_mes(q, forms, m):
    """Todas as páginas de um mês (sequencial); None se falhou."""
    out, de = [], 0
    while True:
        r = None
        for t in range(8):
            try:
                time.sleep(.3)
                r = requests.get("https://efts.sec.gov/LATEST/search-index", headers=H, timeout=60,
                                 params={"q": q, "forms": forms, "dateRange": "custom", "startdt": str(m.start_time.date()),
                                         "enddt": str(m.end_time.date()), "from": de})
                if r.status_code == 200 and "hits" in r.json():
                    break
            except (requests.RequestException, ValueError):
                pass
            r = None
            time.sleep(5 * (t + 1))
        if r is None:
            return None
        hits = r.json()["hits"]["hits"]
        for h in hits:
            s = h["_source"]
            out.append({"id": h["_id"], "forma": s.get("form", ""), "data": s.get("file_date"), "nomes": " | ".join(s.get("display_names", [])),
                        "ciks": " ".join(s.get("ciks", [])), "itens": ",".join(s.get("items") or []), "mes": str(m)})
        de += len(hits)
        if len(hits) < 100 or de >= 9900:
            return out


def fts(nome, q, forms, ini=2006, nthr=3):
    """Busca textual mês a mês (limite de 10 mil por consulta), 3 meses em paralelo (~4 req/s, abaixo do limite de 10/s da SEC).
    Cache dados/sec_fts_<nome>.parquet (meses já feitos não são refeitos)."""
    from concurrent.futures import ThreadPoolExecutor
    f = D / f"sec_fts_{nome}.parquet"
    velho = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["id", "forma", "data", "nomes", "ciks", "itens", "mes"])
    feitos = set(velho.mes)
    hoje = pd.Timestamp.today()
    meses = [m for m in pd.period_range(f"{ini}-01", hoje.strftime("%Y-%m"), freq="M")
             if not (str(m) in feitos and m.end_time < hoje - pd.Timedelta(days=10))]
    for i in range(0, len(meses), 12):
        lote = meses[i:i + 12]
        with ThreadPoolExecutor(nthr) as ex:
            res = list(ex.map(lambda m: _fts_mes(q, forms, m), lote))
        novos = [x for r in res if r for x in r]
        ok = {str(m) for m, r in zip(lote, res) if r is not None}
        velho = pd.concat([velho[~velho.mes.isin(ok)], pd.DataFrame(novos)])
        velho.to_parquet(f)
        print("fts", nome, lote[-1], len(velho), "falhas", len(lote) - len(ok), flush=True)
    velho["data"] = pd.to_datetime(velho.data)
    return velho


CONSULTAS = {"8k_202": ('"Item 2.02"', "8-K"),
             "13d": ('"purpose of transaction"', "SC 13D,SCHEDULE 13D"),
             "13d_ativista": ('"nominate" OR "strategic alternatives" OR "undervalued" OR "board representation" OR "proxy contest"', "SC 13D,SCHEDULE 13D"),
             "oferta_acoes": ('"common stock"', "424B5,424B4,424B1"),
             "oferta_atm": ('"at-the-market" OR "sales agreement" OR "equity distribution agreement"', "424B5"),
             "oferta_divida": ('"notes due" OR "debentures due" OR "senior notes"', "424B5,424B4,424B1"),
             "cap11": ('"Chapter 11"', "8-K")}


def tickers_sec():
    """Mapa atual CIK -> ticker da SEC (company_tickers.json), em cache."""
    f = D / "sec_tickers_atual.parquet"
    if f.exists():
        return pd.read_parquet(f)
    j = _get(f"{SEC}/files/company_tickers.json").json()
    t = pd.DataFrame(j.values()).rename(columns={"cik_str": "cik", "ticker": "tk", "title": "nome"})
    t["tk"] = t.tk.str.upper().str.replace(".", "-", regex=False)
    t.to_parquet(f)
    return t


def sp500_atual():
    f = D / "wiki_sp500_atual.parquet"
    if f.exists():
        return pd.read_parquet(f)
    t = pd.read_html(io.StringIO(_wiki("en", "List of S&P 500 companies")))[0]
    t = t.rename(columns={"Symbol": "tk", "Security": "nome", "CIK": "cik", "Date added": "desde"})[["tk", "nome", "cik", "desde"]]
    t["tk"] = t.tk.str.replace(".", "-", regex=False)
    t.to_parquet(f)
    return t


_TK = {}


def cik_de(tk, d):
    """ticker da época -> CIK: primeiro pelos Forms 3/4/5 (ticker informado na época, pega deslistadas), senão pelo mapa atual da SEC."""
    if "tk" not in _TK:
        _TK["tk"] = cik_ticker()
        _TK["sec"] = tickers_sec().drop_duplicates("tk").set_index("tk").cik
    T = _TK["tk"]
    x = T[(T.tk == tk) & (T.d0 <= d + pd.Timedelta(days=30)) & (T.d1 >= d - pd.Timedelta(days=400))]
    if len(x):
        return int(x.sort_values("n").cik.iloc[-1])
    return int(_TK["sec"].get(tk, -1))


def px_de(cik, tk):
    """ticker para buscar preço: o ATUAL da SEC se a empresa ainda existe (Yahoo guarda o histórico no ticker atual), senão o da época."""
    if "secc" not in _TK:
        _TK["secc"] = tickers_sec().drop_duplicates("cik").set_index("cik").tk
    return _TK["secc"].get(cik, tk) if cik > 0 else tk


def universo_sp(ini="2007-01-01"):
    """S&P 500 ponto a ponto por CIK (atual + mudanças da Wikipédia desde 2007, desfeitas de trás para frente).
    Devolve (U: cik, px; membros(d) -> conjunto de CIKs vigente na data d)."""
    at = sp500_atual()
    w = wiki_mudancas()
    w = w[(w.indice == "SP500") & (w.efetiva >= ini)].sort_values("efetiva", ascending=False)
    S = set(int(c) for c in at.cik)
    hist = [(pd.Timestamp("2100-01-01"), frozenset(S))]
    for ef, g in w.groupby("efetiva", sort=False):
        ent = {cik_de(t, ef) for t in g.entra if t}
        sai = {cik_de(t, ef) for t in g.sai if t}
        S = (S - ent) | (sai - {-1})
        hist.append((ef, frozenset(S)))                                  # conjunto vigente ANTES de ef
    hist = sorted(hist, key=lambda x: x[0])
    datas = [h[0] for h in hist]

    def membros(d):
        return hist[min(np.searchsorted(datas, d, side="right"), len(hist) - 1)][1]
    todos = set().union(*[h[1] for h in hist])
    era = {int(c): t for t, c in zip(at.tk, at.cik)}
    for t, ef in zip(list(w.sai) + list(w.entra), list(w.efetiva) * 2):
        if t:
            era.setdefault(cik_de(t, ef), t)
    U = pd.DataFrame({"cik": sorted(todos)})
    U["tk"] = [era.get(c, "") for c in U.cik]
    U["px"] = [px_de(c, t) for c, t in zip(U.cik, U.tk)]
    return U, membros


# ---------- Ásia: membros ATUAIS (Wikipédia) e datas de resultado do Yahoo (com EPS estimado e reportado, 2014+)
def membros_asia():
    f = D / "wiki_membros_asia.parquet"
    if f.exists():
        return pd.read_parquet(f)
    out = []
    t = pd.read_html(io.StringIO(_wiki("ja", "日経平均株価")))
    for a in t:
        if "証券コード" in str(a.columns[0]):
            out += [("JP", f"{str(c).strip()[:4]}.T") for c in a.iloc[:, 0] if re.fullmatch(r"\d{4}|\d{3}[A-Z]", str(c).strip()[:4])]
    t = pd.read_html(io.StringIO(_wiki("ko", "코스피 200")), converters={"종목코드": str})
    a = [x for x in t if x.shape[0] > 150][0]
    out += [("KR", f"{str(c).zfill(6)}.KS") for c in a["종목코드"]]
    t = pd.read_html(io.StringIO(_wiki("en", "Hang Seng Index")))
    a = [x for x in t if "Ticker" in x.columns and x.shape[0] > 50][0]
    out += [("HK", f"{int(re.sub(r'\D', '', str(c))):04d}.HK") for c in a.Ticker if re.search(r"\d", str(c))]
    m = pd.DataFrame(out, columns=["mercado", "ticker"]).drop_duplicates("ticker")
    m.to_parquet(f)
    return m


def baixa_resultados_asia():
    import yfinance as yf
    f = D / "y_ie_resultados_asia.parquet"
    velho = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["ticker", "quando", "eps_est", "eps_rep"])
    feitos = set(velho.ticker)
    novos = []
    for i, t in enumerate([t for t in membros_asia().ticker if t not in feitos]):
        try:
            d = yf.Ticker(t).get_earnings_dates(limit=100)
        except Exception as ex:
            d = None
            if "Rate" in str(ex) or "Too Many" in str(ex):
                time.sleep(60)
        if d is not None and len(d):
            novos.append(pd.DataFrame({"ticker": t, "quando": [str(x) for x in d.index], "eps_est": d["EPS Estimate"].values,
                                       "eps_rep": d["Reported EPS"].values}))
        else:
            novos.append(pd.DataFrame({"ticker": [t], "quando": [""], "eps_est": [np.nan], "eps_rep": [np.nan]}))
        time.sleep(.5)
        if i % 25 == 24:
            velho = pd.concat([velho] + novos)
            velho.to_parquet(f)
            novos = []
            print("resultados asia", i + 1, len(velho), flush=True)
    if novos:
        velho = pd.concat([velho] + novos)
        velho.to_parquet(f)
    return velho


# ---------- Europa/Índia: nome na Wikipédia -> candidatos de ticker no Yahoo (o 1º com preço na data vale). None = sem preço gratuito.
YF_NOME = {
    # DAX (.DE)
    "K+S": ["SDF.DE"], "TUI": ["TUI1.DE"], "Beiersdorf": ["BEI.DE"], "Continental": ["CON.DE"], "Salzgitter": ["SZG.DE"],
    "Hypo Real Estate": None, "Fresenius": ["FRE.DE"], "Deutsche Postbank": ["DPB.DE"], "Hannover Rück": ["HNR1.DE"], "Infineon": ["IFX.DE"],
    "Volkswagen Vorzugsaktien": ["VOW3.DE"], "Volkswagen Stammaktien": ["VOW.DE"], "HeidelbergCement": ["HEI.DE"], "MAN": ["MAN.DE"],
    "Lanxess": ["LXS.DE"], "Metro": ["CEC.DE"], "Vonovia": ["VNA.DE"], "ProSiebenSat.1 Media": ["PSM.DE"], "Covestro": ["1COV.DE"],
    "Wirecard": ["WDI.DE"], "Commerzbank": ["CBK.DE"], "MTU Aero Engines": ["MTX.DE"], "Thyssenkrupp": ["TKA.DE"], "Deutsche Wohnen": ["DWNI.DE"],
    "Lufthansa": ["LHA.DE"], "Delivery Hero": ["DHER.DE"], "Siemens Energy": ["ENR.DE"], "Airbus": ["AIR.DE"], "Brenntag": ["BNR.DE"],
    "HelloFresh": ["HFG.DE"], "Porsche Automobil Holding": ["PAH3.DE"], "Puma": ["PUM.DE"], "Qiagen": ["QIA.DE"], "Sartorius": ["SRT3.DE"],
    "Siemens Healthineers": ["SHL.DE"], "Symrise": ["SY1.DE"], "Zalando": ["ZAL.DE"], "Daimler Truck Holding": ["DTG.DE"], "Porsche AG": ["P911.DE"],
    "Rheinmetall": ["RHM.DE"], "Fresenius Medical Care": ["FME.DE"], "GEA Group": ["G1A.DE"], "Scout24": ["G24.DE"], "Hochtief": ["HOT.DE"],
    # CAC 40 (.PA)
    "Eiffage": ["FGR.PA"], "Edenred": ["EDEN.PA"], "Euronext": ["ENX.PA"], "Teleperformance": ["TEP.PA"], "Bureau Veritas": ["BVI.PA"],
    "Vivendi": ["VIV.PA"], "Accor": ["AC.PA"], "Alstom": ["ALO.PA"], "Worldline": ["WLN.PA"], "Sanofi": ["SAN.PA"], "Eurofins Scientific": ["ERF.PA"],
    "Atos": ["ATO.PA"], "Sodexo": ["SW.PA"], "TechnipFMC": ["FTI"], "Thales": ["HO.PA"], "Valeo": ["FR.PA"], "Dassault Systèmes": ["DSY.PA"],
    "Solvay": ["SOLB.BR"], "Hermès": ["RMS.PA"], "LafargeHolcim": ["HOLN.SW"], "STMicroelectronics": ["STMPA.PA"], "Nokia": ["NOKIA.PA", "NOKIA.HE"],
    "Klépierre": ["LI.PA"], "Alcatel-Lucent": ["ALU.PA"], "EDF": ["EDF.PA"], "PSA Peugeot Citroën": ["UG.PA"], "Gemalto": ["GTO.AS"],
    "Vallourec": ["VK.PA"], "Legrand": ["LR.PA"], "Suez Environnement": ["SEV.PA"], "Safran": ["SAF.PA"], "Natixis": ["KN.PA"], "Dexia": ["DEXB.BR"],
    "Publicis": ["PUB.PA"], "Lagardère": ["MMB.PA"], "Technip": ["TEC.PA"], "Air France-KLM": ["AF.PA"], "GDF Suez": ["ENGI.PA"],
    # NIFTY 50 (.NS)
    "DLF": ["DLF.NS"], "Power Grid": ["POWERGRID.NS"], "GlaxoSmithKline Pharmaceuticals": ["GLAXO.NS"], "Reliance Power": ["RPOWER.NS"],
    "Dr. Reddy's Laboratories": ["DRREDDY.NS"], "Reliance Capital": ["RELCAPITAL.NS"], "Satyam Computer Services": None, "Axis Bank": ["AXISBANK.NS"],
    "Zee Entertainment Enterprises": ["ZEEL.NS"], "Jindal Steel & Power": ["JINDALSTEL.NS"], "Reliance Petroleum": None, "IDFC": ["IDFC.NS"],
    "NALCO": ["NATIONALUM.NS"], "Jaiprakash Associates": ["JPASSOCIAT.NS"], "JP Associates": ["JPASSOCIAT.NS"], "Tata Communications": ["TATACOMM.NS"],
    "Kotak Mahindra Bank": ["KOTAKBANK.NS"], "Grasim Industries": ["GRASIM.NS"], "ABB India": ["ABB.NS"], "Idea Cellular": ["IDEA.NS"],
    "Sesa Goa": ["VEDL.NS"], "Unitech": ["UNITECH.NS"], "Suzlon": ["SUZLON.NS"], "Coal India": ["COALINDIA.NS"], "Asian Paints": ["ASIANPAINT.NS"],
    "Reliance Communications": ["RCOM.NS"], "Bank of Baroda": ["BANKBARODA.NS"], "Lupin": ["LUPIN.NS"], "Steel Authority of India": ["SAIL.NS"],
    "UltraTech Cement": ["ULTRACEMCO.NS"], "Sterlite Industries": None, "IndusInd Bank": ["INDUSINDBK.NS"], "NMDC": ["NMDC.NS"],
    "Siemens India": ["SIEMENS.NS"], "Wipro": ["WIPRO.NS"], "Reliance Infrastructure": ["RELINFRA.NS"], "Tech Mahindra": ["TECHM.NS"],
    "United Spirits": ["UNITDSPR.NS", "MCDOWELL-N.NS"], "Ranbaxy Laboratories": None, "Yes Bank": ["YESBANK.NS"], "Bosch India": ["BOSCHLTD.NS"],
    "Adani Ports & SEZ": ["ADANIPORTS.NS"], "Aurobindo Pharma": ["AUROPHARMA.NS"], "Bharti Infratel": ["INDUSTOWER.NS"], "Eicher Motors": ["EICHERMOT.NS"],
    "Cairn India": None, "Punjab National Bank": ["PNB.NS"], "Vedanta": ["VEDL.NS"], "Indiabulls Housing Finance": ["SAMMAANCAP.NS", "IBULHSGFIN.NS"],
    "Indian Oil Corporation": ["IOC.NS"], "BHEL": ["BHEL.NS"], "Bajaj Finance": ["BAJFINANCE.NS"], "Hindustan Petroleum": ["HINDPETRO.NS"], "UPL": ["UPL.NS"],
    "ACC": ["ACC.NS"], "Tata Power": ["TATAPOWER.NS"], "Bajaj Finserv": ["BAJAJFINSV.NS"], "Ambuja Cements": ["AMBUJACEM.NS"], "Titan Company": ["TITAN.NS"],
    "JSW Steel": ["JSWSTEEL.NS"], "Britannia Industries": ["BRITANNIA.NS"], "Nestlé India": ["NESTLEIND.NS"], "Shree Cement": ["SHREECEM.NS"],
    "HDFC Life": ["HDFCLIFE.NS"], "SBI Life Insurance Company": ["SBILIFE.NS"], "Divi's Laboratories": ["DIVISLAB.NS"], "Tata Consumer Products": ["TATACONSUM.NS"],
    "GAIL": ["GAIL.NS"], "Apollo Hospitals": ["APOLLOHOSP.NS"], "Adani Enterprises": ["ADANIENT.NS"], "LTIMindtree": ["LTIM.NS"], "HDFC": None,
    "Shriram Finance": ["SHRIRAMFIN.NS"], "Bharat Electronics": ["BEL.NS"], "Trent": ["TRENT.NS"], "Jio Financial Services": ["JIOFIN.NS"],
    "Bharat Petroleum": ["BPCL.NS"], "Eternal": ["ETERNAL.NS", "ZOMATO.NS"], "IndiGo": ["INDIGO.NS"], "Hero MotoCorp": ["HEROMOTOCO.NS"],
    "Max Healthcare": ["MAXHEALTH.NS"], "BSE": ["BSE.NS"], "Bajaj Auto": ["BAJAJ-AUTO.NS"],
}
IDX_LOCAL = {"DAX": "^GDAXI", "CAC": "^FCHI", "NIFTY": "^NSEI", "JP": "^N225", "KR": "^KS11", "HK": "^HSI"}


# =============================================================== PREÇOS E MOTOR DE EVENTOS
_PX = {}


def precos(nome):
    """dados/y_ie_<nome>.parquet -> (P fechamento ajustado, V volume), float32, índice de datas sem fuso."""
    if nome not in _PX:
        X = pd.read_parquet(D / f"y_ie_{nome}.parquet")
        X.index = pd.DatetimeIndex(X.index).tz_localize(None).normalize()
        X = X[~X.index.duplicated()].sort_index()
        P = X[[c for c in X if c.endswith("|Close")]]
        P.columns = [c[:-6] for c in P]
        V = X[[c for c in X if c.endswith("|Volume")]]
        V.columns = [c[:-7] for c in V]
        _PX[nome] = (P.astype("float32"), V.reindex(columns=P.columns).astype("float32"))
    return _PX[nome]


def px_us(nomes=("sp", "us")):
    """Painel EUA no calendário DIAS_US juntando os caches (sem duplicar tickers)."""
    k = ("us",) + tuple(nomes)
    if k not in _PX:
        Ps, Vs = [], []
        for n in nomes:
            if (D / f"y_ie_{n}.parquet").exists():
                P, V = precos(n)
                novo = [c for c in P.columns if all(c not in x.columns for x in Ps)]
                Ps.append(P[novo].reindex(DIAS_US))
                Vs.append(V[novo].reindex(DIAS_US))
        _PX[k] = (pd.concat(Ps, axis=1), pd.concat(Vs, axis=1))
    return _PX[k]


def retornos(P):
    """Retorno diário com feriados preenchidos (até 5 dias) e erros de base removidos: salto > 50% que se desfaz no dia seguinte."""
    R = P.ffill(limit=5).pct_change(fill_method=None)
    l = np.log1p(R.clip(lower=-.99))
    erro = (l.abs() > np.log(1.5)) & ((l + l.shift(-1)).abs() < .25 * l.abs())
    R = R.mask(erro | erro.shift(1, fill_value=False), 0.0)
    return R.mask(R.abs() > 5, 0.0)


def adv_usd(P, V, j=60):
    return (P * V).rolling(j, min_periods=20).mean().shift(1)


def faixas_us(adv, piso_alug=0.0):
    """Custo por perna e aluguel a.a. por liquidez (giro médio em US$): >=50 mi 3 bps/0,3%; 10-50 mi 10 bps/1%; 2-10 mi 25 bps/3%; < 2 mi 50 bps/5%."""
    a = adv.fillna(0)
    c = np.select([a >= 5e7, a >= 1e7, a >= 2e6], [.0003, .001, .0025], .005)
    al = np.select([a >= 5e7, a >= 1e7, a >= 2e6], [.003, .01, .03], .05)
    return (pd.DataFrame(c, index=adv.index, columns=adv.columns),
            pd.DataFrame(np.maximum(al, piso_alug), index=adv.index, columns=adv.columns))


def posicoes(ev, cal, cols, maxw=.05, bruto=1.0):
    """ev: ticker, i0 (índice no calendário da 1ª decisão com posição), i1 (última, inclusive), lado (+1/-1).
    Peso igual entre as posições ativas de cada lado (máx. maxw por nome; soma de cada lado <= bruto)."""
    col = {c: i for i, c in enumerate(cols)}
    L = np.zeros((len(cal), len(cols)), dtype=np.float32)
    S = np.zeros_like(L)
    for t, a, b, s in zip(ev.ticker, ev.i0, ev.i1, ev.lado):
        if t in col and 0 <= a < len(cal):
            (L if s > 0 else S)[a:min(b, len(cal) - 1) + 1, col[t]] = 1
    return pd.DataFrame(L, index=cal, columns=cols), pd.DataFrame(S, index=cal, columns=cols)


def livro(ev, P, R, hedge, maxw=.05, bruto=1.0, C=None, A=None, custo_mult=1, lag=0, detalhe=False, rf=None, c_hedge=.0003, a_hedge=.003,
          imposto=None):
    """Livro de eventos: pesos decididos no fechamento t (posição só enquanto há preço), executados em t+1+lag (desloca como base.carteira).
    hedge: Series ticker -> coluna de R usada como hedge (vende o líquido de cada grupo) ou str único.
    C/A: DataFrames custo por perna e aluguel a.a. (datas x tickers); rf: série do caixa (excesso = r - rf); imposto: Series ticker -> custo extra por perna."""
    cols = [c for c in dict.fromkeys(ev.ticker) if c in P.columns]
    cal = P.index
    Lg, Sh = posicoes(ev, cal, cols, maxw, bruto)
    vivo = P[cols].ffill(limit=3).notna()                                 # posição só enquanto há preço (deslistou: encerra no último)
    Lg, Sh = Lg * vivo, Sh * vivo
    nl, ns = Lg.sum(axis=1), Sh.sum(axis=1)
    W = Lg.mul(np.minimum(maxw, bruto / nl.replace(0, np.nan)), axis=0).fillna(0) - Sh.mul(np.minimum(maxw, bruto / ns.replace(0, np.nan)), axis=0).fillna(0)
    W = W.loc[:, (W != 0).any()]
    cols = list(W.columns)
    RR = R[cols].copy()
    if rf is not None:
        RR = RR.sub(rf.reindex(cal).fillna(0), axis=0)
    # compra-e-segura: o peso de cada negócio é fixado na entrada e depois varia com o preço (sem rebalanceio diário, que cria ganho falso
    # em preços ruidosos de small caps); custo só na entrada/saída
    sg = np.sign(W)
    ini = sg.ne(sg.shift(fill_value=0)) & sg.ne(0)
    W0 = W.where(ini).ffill().where(sg.ne(0), 0.0)
    Wx0 = W0.shift(1 + lag).fillna(0)
    sx = np.sign(Wx0)
    st = sx.ne(sx.shift(fill_value=0)) & sx.ne(0)
    Pf = P[cols].ffill()
    G = (Pf / Pf.where(st).ffill()).clip(0, 20).fillna(1.0)
    Wx = (Wx0 * G).where(Wx0 != 0, 0.0)
    hmap = pd.Series(hedge, index=cols) if isinstance(hedge, str) else pd.Series(hedge).reindex(cols)
    for h in (hmap.dropna().unique() if hedge is not None else []):
        Wx["H:" + h] = -Wx[hmap[hmap == h].index].sum(axis=1)
        Wx0["H:" + h] = Wx["H:" + h]
        RR["H:" + h] = R[h] - (rf.reindex(cal).fillna(0) if rf is not None else 0)
    Cc = (C.reindex(index=cal, columns=cols) if isinstance(C, pd.DataFrame) else pd.DataFrame(C if C is not None else .001, index=cal, columns=cols))
    if imposto is not None:
        Cc = Cc + pd.Series(imposto).reindex(cols).fillna(0).values
    Aa = (A.reindex(index=cal, columns=cols) if isinstance(A, pd.DataFrame) else pd.DataFrame(A if A is not None else .01, index=cal, columns=cols))
    for h in [c for c in Wx.columns if c.startswith("H:")]:
        Cc[h], Aa[h] = c_hedge, a_hedge
    Cc, Aa = Cc.ffill().fillna(.005), Aa.ffill().fillna(.05)
    contrib = (Wx.shift(1) * RR.fillna(0) - Wx0.diff().abs() * Cc * custo_mult - Wx.clip(upper=0).abs() * Aa / 252).fillna(0)
    ex = contrib.sum(axis=1)
    if not detalhe:
        return brl(ex)
    nomes = [c for c in Wx.columns if not c.startswith("H:")]
    tr = episodios(Wx[nomes], RR[nomes], contrib[nomes])
    if len(tr) and hedge is not None:
        tr["hedge"] = hmap.reindex(tr.ativo).values
        lh = {h: np.log1p(RR["H:" + h].fillna(0)).cumsum() for h in hmap.dropna().unique()}
        tr["hedge %"] = [np.expm1(lh[h].loc[s] - lh[h].loc[e]) * 100 if h == h else 0 for h, e, s in zip(tr.hedge, tr.entrada, tr.saida)]
        tr["ret - hedge %"] = tr["retorno %"] - np.sign(tr.lado.map({"compra": 1, "venda": -1})) * tr["hedge %"]
    ct = contrib.T.groupby(lambda c: "hedge" if c.startswith("H:") else c).sum().T
    if ct.shape[1] > 60:
        ct = ct.stack().rename("contrib").loc[lambda x: x != 0].reset_index().set_axis(["data", "ativo", "contrib"], axis=1)
    return brl(ex), ct, tr


def pos_cal(cal, datas):
    """índice do 1º pregão >= data (evento num fim de semana/feriado vale no pregão seguinte)."""
    return cal.searchsorted(pd.DatetimeIndex(datas))


# =============================================================== EVENTOS EUA
def _fts_ev(nome, formas=None):
    """Resultado da busca textual -> 1 linha por arquivamento: accession, forma, data, cik (1º = empresa-objeto), ticker atual (se houver), nomes."""
    x = pd.read_parquet(D / f"sec_fts_{nome}.parquet")
    x["acc"] = x.id.str.split(":").str[0]
    x = x.drop_duplicates("acc")
    if formas:
        x = x[x.forma.isin(formas)]
    x["data"] = pd.to_datetime(x.data)
    x["cik"] = x.ciks.str.split().str[0].astype(int)
    pri = x.nomes.str.split(r" \| ").str[0]
    x["tk_atual"] = pri.str.extract(r"\(([A-Z][A-Z0-9\.\-]{0,6})(?:,\s*[A-Z0-9\.\-]+)*\)\s+\(CIK")[0].str.replace(".", "-", regex=False)
    return x


def tk_evento(cik, data, tk_atual=None):
    """ticker de preço: o atual (EFTS/SEC) se existir; senão o informado nos Forms 3/4 na época do evento."""
    if isinstance(tk_atual, str) and tk_atual:
        return tk_atual
    if "tk" not in _TK:
        cik_de("X", data)
    T = _TK["tk"]
    x = T[(T.cik == cik) & (T.d0 <= data + pd.Timedelta(days=60)) & (T.d1 >= data - pd.Timedelta(days=400))]
    return px_de(cik, x.sort_values("n").tk.iloc[-1] if len(x) else "")


def ev_8k202():
    x = _fts_ev("8k_202", ["8-K"])
    x = x[x.itens.str.contains("2.02", regex=False)]
    return x[["acc", "data", "cik", "tk_atual"]]


def ev_ofertas():
    """Ofertas de ações (424B5/424B4/424B1 que citam 'common stock'), sem ATM e sem dívida (busca textual), com ticker."""
    a = _fts_ev("oferta_acoes")
    fora = set(_fts_ev("oferta_atm").acc) | set(_fts_ev("oferta_divida").acc)
    a = a[~a.acc.isin(fora)]
    a = a[~a.nomes.str.upper().str.contains(EXCL_IE, regex=True, na=False)]
    a["ticker"] = [tk_evento(c, d, t) for c, d, t in zip(a.cik, a.data, a.tk_atual)]
    return a[a.ticker != ""]


EXCL_IE = (r"FUND\b|PORTFOLIO|MUNICIPAL|INCOME TRUST|CLOSED|\bETF\b|BDC|ACQUISITION CORP|ACQUISITION CO|SPAC|BLANK CHECK|INVESTMENT CORP|"
           r"FINANCE CORP|ROYALTY TRUST|BANK|BANCORP|\bTRUST\b|FUNDING|CAPITAL CORP")


def ev_ipos():
    """IPOs: 1º 424B4/424B1 do CIK; o 1º preço do Yahoo tem de vir entre -3 e +10 dias e não pode haver preço antes (empresa nova)."""
    ix = pd.read_parquet(D / "sec_indice_ie.parquet")
    x = ix[ix.forma.isin(["424B4", "424B1"])].sort_values("data").groupby("cik").first().reset_index()
    x = x[~x.nome.str.upper().str.contains(EXCL_IE, regex=True, na=False)]
    x["ticker"] = [tk_evento(c, d) for c, d in zip(x.cik, x.data)]
    return x[x.ticker != ""]


def ev_13d():
    a = _fts_ev("13d", ["SC 13D", "SCHEDULE 13D"])
    at = set(_fts_ev("13d_ativista").acc)
    a["ativista"] = a.acc.isin(at)
    a = a[~a.nomes.str.split(r" \| ").str[0].str.upper().str.contains(EXCL_IE, regex=True, na=False)]
    a["ticker"] = [tk_evento(c, d, t) for c, d, t in zip(a.cik, a.data, a.tk_atual)]
    return a[a.ticker != ""]


def ev_toi():
    ix = pd.read_parquet(D / "sec_indice_ie.parquet")
    x = ix[ix.forma == "SC TO-I"].copy()
    x = x[~x.nome.str.upper().str.contains(EXCL_IE, regex=True, na=False)]
    x["ticker"] = [tk_evento(c, d) for c, d in zip(x.cik, x.data)]
    return x[x.ticker != ""]


def ev_cap11():
    a = _fts_ev("cap11", ["8-K"])
    a = a[a.itens.str.contains("1.03", regex=False)]
    a["ticker"] = [tk_evento(c, d, t) for c, d, t in zip(a.cik, a.data, a.tk_atual)]
    return a[a.ticker != ""]


def ev_indices_us():
    """Entradas/saídas do S&P 500 e Nasdaq-100 (2008+) com data do comunicado (referência da Wikipédia) e ticker de preço."""
    w = wiki_mudancas()
    w = w[w.indice.isin(["SP500", "NDX"]) & (w.efetiva >= "2008-01-01")]
    out = []
    for _, r in w.iterrows():
        for lado, t in (("entra", r.entra), ("sai", r.sai)):
            if t:
                c = cik_de(t, r.efetiva)
                out.append({"indice": r.indice, "lado": lado, "tk_era": t, "cik": c, "ticker": px_de(c, t), "efetiva": r.efetiva,
                            "anuncio": r.anuncio, "motivo": r.motivo})
    return pd.DataFrame(out)


def tickers_us():
    """Todos os tickers de preço dos eventos EUA (para baixar uma vez só)."""
    t = set()
    for f in (ev_ofertas, ev_ipos, ev_13d, ev_toi, ev_cap11, ev_indices_us):
        try:
            t |= set(f().ticker)
        except Exception as ex:
            print("tickers", f.__name__, ex)
    return sorted(t | {"SPY", "IWM", "QQQ"})


# =============================================================== ESTRATÉGIAS
_EVC = {}


def _cache(k, fn):
    if k not in _EVC:
        _EVC[k] = fn()
    return _EVC[k]


def _us():
    """Painel EUA: P, R, C (custo), A (aluguel), ADV, R dos hedges (SPY/IWM/QQQ do y_etf), caixa = T-bill."""
    if "us" not in _EVC:
        P, V = px_us()
        R = retornos(P)
        adv = adv_usd(P, V)
        C, A = faixas_us(adv)
        for e in ("SPY", "IWM", "QQQ"):
            R[e] = ETF[e].reindex(DIAS_US).pct_change(fill_method=None)
        _EVC["us"] = dict(P=P, R=R, adv=adv, C=C, A=A)
    return _EVC["us"]


def _reacao(P, Ridx, i, d0=-1, d1=1):
    """retorno anormal (ação - índice) do fechamento i+d0 ao i+d1 para listas de (coluna, índice)."""
    out = []
    lp = np.log(P)
    li = np.log1p(Ridx.fillna(0)).cumsum()
    for c, k in i:
        if c not in P.columns or k + d1 >= len(P) or k + d0 < 0:
            out.append(np.nan)
            continue
        a, b = lp[c].iloc[k + d0], lp[c].iloc[k + d1]
        out.append(np.expm1((b - a) - (li.iloc[k + d1] - li.iloc[k + d0])))
    return np.array(out)


# ---------------------------------------------------------------- IE01 PEAD EUA (S&P 500 ponto a ponto)
def eventos_pead_us():
    def f():
        U, membros = universo_sp()
        px = U.set_index("cik").px
        e = ev_8k202()
        e = e[e.data >= "2007-01-01"]
        e = e[[c in membros(d) for c, d in zip(e.cik, e.data)]].copy()
        e["ticker"] = e.cik.map(px)
        e = e.sort_values("data").drop_duplicates(["cik", "data"])
        e = e[e.groupby("cik").data.diff().dt.days.fillna(999) > 20]          # 1 resultado por trimestre (8-K 2.02 repetido/retificado)
        us = _us()
        cal = us["P"].index
        e["k"] = pos_cal(cal, e.data)
        e["reacao"] = _reacao(us["P"], us["R"]["SPY"], list(zip(e.ticker, e.k)), -1, 1)
        e["tem_preco"] = e.ticker.isin(us["P"].columns) & e.reacao.notna()
        return e
    return _cache("pead_us", f)


def pead_us(limiar=.05, hold=60, lado="ambos", custo_mult=1, lag=0, detalhe=False):
    """Resultado (8-K item 2.02) de empresa que ESTAVA no S&P 500 na data; reação anormal (vs SPY) do fech. t-1 ao t+1;
    decide no fechamento t+1 (executa t+2): compra se reação >= limiar, vende se <= -limiar; segura `hold` pregões; hedge SPY no líquido."""
    e = eventos_pead_us()
    e = e[e.tem_preco & (e.reacao.abs() >= limiar)].copy()
    e["lado"] = np.sign(e.reacao)
    if lado == "compra":
        e = e[e.lado > 0]
    elif lado == "venda":
        e = e[e.lado < 0]
    e["i0"] = e.k + 1
    e["i1"] = e.i0 + hold - 1
    us = _us()
    return livro(e, us["P"], us["R"], "SPY", .02, 1.0, us["C"], us["A"], custo_mult, lag, detalhe, rf=TB_US)


# ---------------------------------------------------------------- IE06 inclusão/exclusão S&P 500 e Nasdaq-100
def indices_us(fase="pre", lado="entra", dias=20, custo_mult=1, lag=0, detalhe=False):
    """pre: no fechamento do dia do COMUNICADO (sai depois do fechamento -> executa no seguinte) compra quem entra / vende quem sai;
    zera no fechamento da véspera da data efetiva (quando os fundos de índice negociam). Só eventos com data de comunicado conhecida.
    pos: a partir do fechamento da véspera da efetiva (vende para o fundo de índice), vende quem entrou / compra quem saiu por `dias` pregões.
    hedge SPY (S&P) ou QQQ (Nasdaq-100); 10% por nome."""
    ev = _cache("idx_us", ev_indices_us)
    us = _us()
    cal = us["P"].index
    out = []
    for fz in (["pre", "pos"] if fase == "pre+pos" else [fase]):
        e = ev.copy()
        if lado == "entra":
            e = e[e.lado == "entra"]
        kE = pos_cal(cal, e.efetiva)
        if fz == "pre":
            ok = e.anuncio.notna().values
            kA = pos_cal(cal, e.anuncio.fillna(pd.Timestamp("2100-01-01")))
            e = e.assign(i0=kA, i1=kE - 3)[ok & (kE - 3 >= kA)]
            e["lado"] = np.where(e.lado == "entra", 1, -1)
        else:
            e = e.assign(i0=kE - 2, i1=kE - 3 + dias)
            e["lado"] = np.where(e.lado == "entra", -1, 1)
        out.append(e)
    e = pd.concat(out)
    e = e[e.ticker.isin(us["P"].columns)]
    hg = pd.Series(np.where(e.indice == "NDX", "QQQ", "SPY"), index=e.ticker).groupby(level=0).first()
    return livro(e, us["P"], us["R"], hg.to_dict(), .10, 1.0, us["C"], us["A"], custo_mult, lag, detalhe, rf=TB_US)


# =============================================================== EVENTOS FORA DOS EUA (moeda local; long-short contra o índice local -> brl())
CUSTO_LOCAL = {"JP": (.0010, .01), "KR": (.0020, .02), "HK": (.0022, .02), "DAX": (.0005, .005), "CAC": (.0020, .005), "NIFTY": (.0020, .02)}
# custo por perna = corretagem/spread + imposto médio por perna (KR 0,2% na venda; HK selo 0,1-0,13% nas duas; FR TTF 0,3% na compra;
# Índia STT 0,1% nas duas); aluguel a.a. (Índia = custo de carregar futuro de ação)
DY_IDX = {"^N225": .018, "^KS11": .018, "^HSI": .035, "^FCHI": .03, "^NSEI": .013}   # dividend yield médio a.a. (^GDAXI já é de retorno total)
VETO_VENDA_KR = [("2008-10-01", "2009-05-31"), ("2011-08-10", "2011-11-09"), ("2020-03-16", "2021-05-02"), ("2023-11-06", "2025-03-30")]


def _local(nomes):
    """Painel local (calendário = união dos pregões), retornos com feriados preenchidos, índices locais."""
    k = ("loc",) + tuple(nomes)
    if k not in _EVC:
        Ps = []
        for n in nomes:
            P, _ = precos(n)
            Ps.append(P[[c for c in P.columns if all(c not in x.columns for x in Ps)]])
        P = pd.concat(Ps, axis=1).sort_index()
        P = P[P.index >= "2006-01-01"]
        R = retornos(P)
        for ix, dy in DY_IDX.items():                                    # índice de preço -> retorno total aproximado (ações do Yahoo já
            if ix in R:                                                  # vêm com dividendo; sem isso o comprado ganha o dividendo de graça)
                R[ix] = R[ix] + dy / 252 * R[ix].notna()
        _EVC[k] = dict(P=P, R=R)
    return _EVC[k]


def eventos_pead_asia():
    def f():
        x = pd.read_parquet(D / "y_ie_resultados_asia.parquet")
        x = x[x.quando != ""].copy()
        x["data"] = pd.to_datetime(x.quando.str[:10])
        x["surpresa"] = np.sign(pd.to_numeric(x.eps_rep, errors="coerce") - pd.to_numeric(x.eps_est, errors="coerce"))
        mb = membros_asia().set_index("ticker").mercado
        x["mercado"] = x.ticker.map(mb)
        L = _local(["asia"])
        P, R = L["P"], L["R"]
        out = []
        for mk, g in x.groupby("mercado"):
            cal = P[IDX_LOCAL[mk]].dropna().index                        # pregões do mercado
            Pm = P.loc[cal]
            Rm = Pm.ffill(limit=5).pct_change(fill_method=None)
            g = g[g.data <= cal[-1]].copy()
            g["k"] = pos_cal(cal, g.data)
            g["reacao"] = _reacao(Pm, Rm[IDX_LOCAL[mk]], list(zip(g.ticker, g.k)), -1, 1)
            g["dec"] = [cal[min(k + 1, len(cal) - 1)] for k in g.k]       # decisão no fechamento t+1 (data no calendário do mercado)
            out.append(g)
        e = pd.concat(out)
        e = e[e.data <= pd.Timestamp.today()].sort_values("data").drop_duplicates(["ticker", "data"])
        return e[e.groupby("ticker").data.diff().dt.days.fillna(999) > 20]
    return _cache("pead_asia", f)


def pead_asia(mercados="JP+KR+HK", limiar=.05, hold=60, filtro="reacao", custo_mult=1, lag=0, detalhe=False):
    """PEAD na Ásia (Nikkei 225, KOSPI 200, Hang Seng — membros ATUAIS): data/hora e EPS estimado x reportado do Yahoo (2014+).
    Reação anormal vs índice local fech. t-1 -> t+1; decide em t+1. filtro 'concorda': só se o sinal da surpresa (EPS - consenso) = sinal da reação.
    Hedge: índice local de cada ação. Custo/imposto por mercado; Coreia sem venda a descoberto nos períodos de proibição."""
    e = eventos_pead_asia()
    e = e[e.mercado.isin(mercados.split("+")) & (e.reacao.abs() >= limiar)].copy()
    e["lado"] = np.sign(e.reacao)
    if filtro == "concorda":
        e = e[e.surpresa == e.lado]
    for a, b in VETO_VENDA_KR:
        e = e[~((e.mercado == "KR") & (e.lado < 0) & e.dec.between(a, b))]
    L = _local(["asia"])
    cal = L["P"].index
    e["i0"] = pos_cal(cal, e.dec)
    e["i1"] = e.i0 + hold - 1
    c = e.drop_duplicates("ticker").set_index("ticker").mercado
    C = {t: CUSTO_LOCAL[m][0] for t, m in c.items()}
    A = {t: CUSTO_LOCAL[m][1] for t, m in c.items()}
    Cdf = pd.DataFrame([C] * len(cal), index=cal)
    Adf = pd.DataFrame([A] * len(cal), index=cal)
    return livro(e, L["P"], L["R"], {t: IDX_LOCAL[m] for t, m in c.items()}, .03, 1.0, Cdf, Adf, custo_mult, lag, detalhe, c_hedge=.0003, a_hedge=.005)


def ev_indices_loc():
    """DAX, CAC 40 e NIFTY 50 (2008+): só data efetiva; 'regular' = revisão periódica (exclui cisão, fusão, aquisição, insolvência, deslistagem)."""
    w = wiki_mudancas()
    w = w[w.indice.isin(["DAX", "CAC", "NIFTY"]) & (w.efetiva >= "2008-01-01")]
    P = _local(["asia", "eur"])["P"]
    adhoc = r"abgespalten|Abspaltung|Insolvenz|Delisting|Akquisition|Umtausch|unter 10|fusion|scission|Erweiterung|Börsengang|demerg|merger|acqui"
    out = []
    for _, r in w.iterrows():
        reg = not re.search(adhoc, f"{r.motivo} {r.entra_nome} {r.sai_nome}", flags=re.I)
        for lado, nome in (("entra", r.entra_nome), ("sai", r.sai_nome)):
            nome = re.sub(r"\s*\(.*?\)", "", str(nome)).strip()
            cand = YF_NOME.get(nome)
            tk = ""
            for c in (cand or []):
                if c in P.columns and P[c].loc[:r.efetiva].dropna().index.max() >= r.efetiva - pd.Timedelta(days=10):
                    tk = c
                    break
            out.append({"indice": r.indice, "lado": lado, "nome": nome, "ticker": tk, "efetiva": r.efetiva, "regular": reg,
                        "mapeado": nome in YF_NOME})
    return pd.DataFrame(out)


def indices_loc(fase="pre5", lado="entra", dias=20, custo_mult=1, lag=0, detalhe=False):
    """Europa/Índia (DAX, CAC 40, NIFTY 50). Sem data de comunicado gratuita: pre5/pre10 = compra quem entra (vende quem sai) 5/10 pregões antes
    da efetiva e zera no fechamento da véspera (só revisões REGULARES, anunciadas ~2-4 semanas antes, para não usar informação futura);
    pos = depois da efetiva vende quem entrou / compra quem saiu por `dias`. Hedge: índice local."""
    e = _cache("idx_loc", ev_indices_loc)
    e = e[e.ticker != ""].copy()
    if lado == "entra":
        e = e[e.lado == "entra"]
    L = _local(["asia", "eur"])
    cal = L["P"].index
    out = []
    for fz in (["pre5", "pos"] if fase == "pre+pos" else [fase]):
        x = e.copy()
        out_c = []
        for ix, g in x.groupby("indice"):
            cm = L["P"][IDX_LOCAL[ix]].dropna().index
            kE = pos_cal(cm, g.efetiva)
            if fz.startswith("pre"):
                k = int(fz[3:])
                g = g.assign(d0=[cm[max(i - k - 1, 0)] for i in kE], d1=[cm[max(i - 3, 0)] for i in kE])[g.regular.values]
                g["lado"] = np.where(g.lado == "entra", 1, -1)
            else:
                g = g.assign(d0=[cm[max(i - 2, 0)] for i in kE], d1=[cm[min(i - 3 + dias, len(cm) - 1)] for i in kE])
                g["lado"] = np.where(g.lado == "entra", -1, 1)
            out_c.append(g)
        out.append(pd.concat(out_c))
    e = pd.concat(out)
    e["i0"], e["i1"] = pos_cal(cal, e.d0), pos_cal(cal, e.d1)
    c = e.drop_duplicates("ticker").set_index("ticker").indice
    C = pd.DataFrame([{t: CUSTO_LOCAL[m][0] for t, m in c.items()}] * len(cal), index=cal)
    A = pd.DataFrame([{t: CUSTO_LOCAL[m][1] for t, m in c.items()}] * len(cal), index=cal)
    return livro(e, L["P"], L["R"], {t: IDX_LOCAL[m] for t, m in c.items()}, .15, 1.0, C, A, custo_mult, lag, detalhe, c_hedge=.0003, a_hedge=.005)


# ---------------------------------------------------------------- IE02 follow-on vendido EUA
def eventos_ofertas():
    def f():
        a = ev_ofertas().sort_values("data")
        a = a[a.data >= "2007-01-01"]
        a = a[a.groupby("cik").data.diff().dt.days.fillna(999) > 90]           # 1a oferta do emissor em 90 dias (suplementos repetidos)
        us = _us()
        P, adv = us["P"], us["adv"]
        cal = P.index
        a = a[a.ticker.isin(P.columns)].copy()
        a["k"] = pos_cal(cal, a.data)
        a = a[a.k < len(cal) - 2]
        V = px_us()[1]
        k, t = a.k.values, a.ticker.values
        a["adv"] = [adv[c].iloc[i] for c, i in zip(t, k)]
        a["preco"] = [P[c].iloc[i - 1] if i > 0 else np.nan for c, i in zip(t, k)]
        a["n_hist"] = [P[c].iloc[max(i - 120, 0):i].notna().sum() for c, i in zip(t, k)]      # empresa já listada (não é IPO)
        vv = [np.nanmax([V[c].iloc[i], V[c].iloc[i + 1]]) * P[c].iloc[i] for c, i in zip(t, k)]
        a["pressao"] = np.array(vv) / a.adv.values
        a["reacao"] = _reacao(P, us["R"]["IWM"], list(zip(t, k)), -1, 1)
        return a
    return _cache("ofertas", f)


def follow_on(pressao=0, hold=40, adv_min=5e6, custo_mult=1, lag=0, detalhe=False):
    """Vende a ação depois do prospecto de oferta de ações (424B5/424B4/424B1 com 'common stock', sem ATM nem dívida), empresa já listada há
    >= 100 pregões, preço >= US$5 e giro >= adv_min. pressao = volume do dia do prospecto ou do seguinte / giro médio >= x (confirma que houve
    distribuição de ações; 0 = sem filtro). Decide no fechamento t+1, segura `hold`, hedge IWM, 2% por nome, custo/aluguel por liquidez."""
    a = eventos_ofertas()
    a = a[(a.n_hist >= 100) & (a.preco >= 5) & (a.adv >= adv_min) & (a.pressao >= pressao)].copy()
    a["lado"], a["i0"] = -1, a.k + 1
    a["i1"] = a.i0 + hold - 1
    us = _us()
    return livro(a, us["P"], us["R"], "IWM", .02, 1.0, us["C"], us["A"], custo_mult, lag, detalhe, rf=TB_US)


# ---------------------------------------------------------------- IE03 fim de lock-up EUA (IPOs)
def eventos_ipos():
    def f():
        x = ev_ipos()
        us = _us()
        P = us["P"]
        x = x[x.ticker.isin(P.columns)].copy()
        out = []
        for _, r in x.iterrows():
            s = P[r.ticker].dropna()
            if not len(s):
                continue
            ini = s.index[0]
            if not (r.data - pd.Timedelta(days=3) <= ini <= r.data + pd.Timedelta(days=10)):
                continue                                                    # 1o preço longe do 424B4: não é IPO (ou ticker de outra empresa)
            spac = s.iloc[:60].between(9.5, 10.6).mean() > .8               # SPAC/blank check (preço parado em US$10)
            out.append({"ticker": r.ticker, "nome": r.nome, "ipo": ini, "lockup": ini + pd.Timedelta(days=180), "spac": spac})
        return pd.DataFrame(out)
    return _cache("ipos", f)


def lockup(antes=5, depois=20, custo_mult=1, lag=0, detalhe=False):
    """Vende o IPO `antes` pregões antes do fim do lock-up padrão de 180 dias (data conhecida desde o IPO) e recompra `depois` pregões depois.
    Exclui SPACs. Hedge IWM; aluguel mínimo 3% a.a. (IPO recente é difícil de alugar), 3% por nome."""
    x = eventos_ipos()
    x = x[~x.spac].copy()
    us = _us()
    cal = us["P"].index
    kL = pos_cal(cal, x.lockup)
    x["i0"], x["i1"], x["lado"] = kL - antes - 1, kL - 1 + depois, -1
    x = x[x.i0 < len(cal)]
    Pf = us["P"].ffill(limit=5)
    x["preco"] = [Pf[t].iloc[i] for t, i in zip(x.ticker, x.i0)]
    x["adv"] = [us["adv"][t].iloc[i] for t, i in zip(x.ticker, x.i0)]
    x = x[(x.preco >= 2) & (x.adv >= 1e6)]                                  # papel negociável e alugável na decisão
    C, A = us["C"], us["A"].clip(lower=.03)
    return livro(x, us["P"], us["R"], "IWM", .03, 1.0, C, A, custo_mult, lag, detalhe, rf=TB_US)


# ---------------------------------------------------------------- IE04 13D (ativista) EUA
def eventos_13d():
    def f():
        a = ev_13d().sort_values("data")
        a = a[a.data >= "2007-01-01"]
        a = a[a.groupby("cik").data.diff().dt.days.fillna(999) > 365]
        us = _us()
        P = us["P"]
        a = a[a.ticker.isin(P.columns)].copy()
        a["k"] = pos_cal(P.index, a.data)
        a = a[a.k < len(P) - 1]
        a["adv"] = [us["adv"][c].iloc[i] for c, i in zip(a.ticker, a.k)]
        a["preco"] = [P[c].iloc[i - 1] if i > 0 else np.nan for c, i in zip(a.ticker, a.k)]
        return a
    return _cache("13d", f)


def ativista(filtro="ativista", hold=126, adv_min=1e6, custo_mult=1, lag=0, detalhe=False):
    """Compra a empresa-alvo no fechamento seguinte ao 1o 13D (>5% de um investidor com intenção de influenciar);
    filtro 'ativista' = o texto fala em indicar conselheiros/alternativas estratégicas/subavaliada/disputa de procuração. Hedge IWM, 3% por nome."""
    a = eventos_13d()
    a = a[(a.preco >= 2) & (a.adv >= adv_min)].copy()
    if filtro == "ativista":
        a = a[a.ativista]
    a["lado"], a["i0"] = 1, a.k
    a["i1"] = a.i0 + hold - 1
    us = _us()
    return livro(a, us["P"], us["R"], "IWM", .03, 1.0, us["C"], us["A"], custo_mult, lag, detalhe, rf=TB_US)


# ---------------------------------------------------------------- IE05 recompra por oferta pública (SC TO-I) EUA
def eventos_toi():
    def f():
        a = ev_toi().sort_values("data")
        a = a[a.data >= "2007-01-01"]
        a = a[a.groupby("cik").data.diff().dt.days.fillna(999) > 180]
        us = _us()
        P = us["P"]
        a = a[a.ticker.isin(P.columns)].copy()
        a["k"] = pos_cal(P.index, a.data)
        a = a[a.k < len(P) - 1]
        a["adv"] = [us["adv"][c].iloc[i] for c, i in zip(a.ticker, a.k)]
        a["preco"] = [P[c].iloc[i - 1] if i > 0 else np.nan for c, i in zip(a.ticker, a.k)]
        a["ok"] = [P[c].iloc[max(i - 5, 0):i].notna().any() for c, i in zip(a.ticker, a.k)]   # tinha preço na data (ticker certo)
        return a[a.ok]
    return _cache("toi", f)


def recompra_tender(hold=63, adv_min=1e6, custo_mult=1, lag=0, detalhe=False):
    """Compra a empresa que abre oferta pública de recompra das próprias ações (SC TO-I: leilão holandês/preço fixo): a gestão compra
    um bloco grande com prêmio = sinal forte de subavaliação (diferente do programa brasileiro, que pode nunca ser executado). Hedge IWM."""
    a = eventos_toi()
    a = a[(a.preco >= 2) & (a.adv >= adv_min)].copy()
    a["lado"], a["i0"] = 1, a.k
    a["i1"] = a.i0 + hold - 1
    us = _us()
    return livro(a, us["P"], us["R"], "IWM", .03, 1.0, us["C"], us["A"], custo_mult, lag, detalhe, rf=TB_US)


# ---------------------------------------------------------------- IE09 Chapter 11 (8-K item 1.03)
def eventos_cap11():
    def f():
        a = ev_cap11().sort_values("data")
        a = a[a.data >= "2007-01-01"]
        a = a[a.groupby("cik").data.diff().dt.days.fillna(999) > 365]
        us = _us()
        P = us["P"]
        a["tem_preco"] = False
        b = a[a.ticker.isin(P.columns)].copy()
        b["k"] = pos_cal(P.index, b.data)
        b = b[b.k < len(P) - 1]
        b["ok"] = [P[c].iloc[max(i - 5, 0):i + 1].notna().any() for c, i in zip(b.ticker, b.k)]
        b["adv"] = [us["adv"][c].iloc[i] for c, i in zip(b.ticker, b.k)]
        a.loc[b.index[b.ok], "tem_preco"] = True
        return a, b[b.ok]
    return _cache("cap11", f)


def chapter11(lado="vende", hold=60, custo_mult=1, lag=0, detalhe=False):
    """Pedido de recuperação judicial (8-K item 1.03). vende: a ação continua caindo (credores na frente; equity costuma ser zerada);
    aluguel 20% a.a. + custo mínimo 50 bps. compra: contrarian (no Brasil foi armadilha). Hedge IWM, 5% por nome."""
    _, b = eventos_cap11()
    Pf = _us()["P"].ffill(limit=5)
    b = b.assign(preco=[Pf[t].iloc[i] for t, i in zip(b.ticker, b.k)])
    b = b[(b.preco >= 1) & (b.adv >= 1e6)].copy()                           # só o que dá para negociar/alugar (penny stock fica de fora)
    b["lado"], b["i0"] = (-1 if lado == "vende" else 1), b.k
    b["i1"] = b.i0 + hold - 1
    us = _us()
    C = us["C"].clip(lower=.005)
    A = us["A"].clip(lower=.20)
    return livro(b, us["P"], us["R"], "IWM", .05, 1.0, C, A, custo_mult, lag, detalhe, rf=TB_US)


# =============================================================== FUNDOS
def _fundos():
    from motor import Fundo
    MM = dict(adm=0.0, perf=0.0)
    return [
        Fundo("IE01 PEAD EUA (S&P 500 ponto a ponto)", "Event-driven", "CDI",
              "O mercado subreage ao resultado: a reação dos 2 primeiros dias continua por semanas (no Brasil +5 pp/ano, ganho nas caudas). "
              "Universo = quem ESTAVA no S&P 500 na data (atual + excluídos, pela Wikipédia) -> sem viés de escolher sobreviventes",
              "8-K item 2.02 (data de arquivamento na SEC); reação anormal vs SPY de t-1 a t+1; decide em t+1; 2% por nome; hedge SPY; custo 3-10 bps",
              pead_us, {"limiar": [.04, .07], "hold": [20, 60], "lado": ["ambos", "venda"]}, inicio="2008-01-01", corte="2021-01-01", **MM),
        Fundo("IE02 Follow-on vendido EUA", "Event-driven", "CDI",
              "Emissor e acionista vendedor sabem mais e vendem quando a ação está cara; a oferta adicional pressiona por semanas (Brasil: +10 pp OOS)",
              "424B5/424B4/424B1 com ações (sem ATM/dívida, pela busca textual da SEC), 1ª oferta em 90 dias, vende em t+1 por 20-40 pregões, "
              "2% por nome, hedge IWM, custo/aluguel por liquidez", follow_on,
              {"pressao": [0, 2, 4], "hold": [20, 40]}, inicio="2008-01-01", corte="2021-01-01", **MM),
        Fundo("IE03 Fim de lock-up EUA", "Event-driven", "CDI",
              "No fim do lock-up de 180 dias, PE/VC e fundadores podem vender; a oferta de papel é previsível mas o preço só ajusta perto da data",
              "IPO = 1º 424B4/424B1 + 1º preço; vende 5-10 pregões antes do dia 180 e recompra 10-60 depois; sem SPACs; hedge IWM; aluguel >= 3%",
              lockup, {"antes": [5, 10], "depois": [10, 60]}, inicio="2008-01-01", corte="2021-01-01", **MM),
        Fundo("IE04 13D ativista EUA", "Event-driven", "CDI",
              "Investidor que cruza 5% com intenção de influenciar (conselho, venda da empresa) destrava valor; o mercado subestima a probabilidade de êxito",
              "1º SC 13D (busca textual: 'purpose of transaction'), filtro de texto ativista opcional; compra em t+1, 3-12 meses, 3% por nome, hedge IWM",
              ativista, {"filtro": ["todos", "ativista"], "hold": [63, 126, 252]}, inicio="2008-01-01", corte="2021-01-01", **MM),
        Fundo("IE05 Recompra por oferta pública (SC TO-I) EUA", "Event-driven", "CDI",
              "Recompra por tender (leilão holandês/preço fixo) é compra firme de um bloco com prêmio: sinal de subavaliação de quem sabe mais "
              "(no Brasil o 'programa' de recompra não carregava nada porque muitas vezes não é executado)",
              "Compra no fechamento seguinte ao SC TO-I, 1-6 meses, 3% por nome, hedge IWM; exclui fundos fechados/BDCs/bancos",
              recompra_tender, {"hold": [21, 63, 126], "adv_min": [1e6, 1e7]}, inicio="2008-01-01", corte="2021-01-01", **MM),
        Fundo("IE06 Inclusão/exclusão S&P 500 e Nasdaq-100", "Fluxo", "CDI",
              "Fundos de índice compram quem entra no fechamento da véspera da data efetiva, sem olhar preço; quem antecipa vende para eles "
              "(Brasil: comprar entrantes do Ibovespa antes, vol 1,7%)",
              "pre: compra no fechamento seguinte ao COMUNICADO (data da referência da Wikipédia) e vende na véspera da efetiva; pos: vende quem entrou "
              "depois da efetiva por 20 pregões; 10% por nome, hedge SPY/QQQ", indices_us,
              {"fase": ["pre", "pos", "pre+pos"], "lado": ["entra", "ambos"]}, inicio="2008-01-01", corte="2021-01-01", **MM),
        Fundo("IE07 Rebalanceamento DAX, CAC 40 e NIFTY 50", "Fluxo", "CDI",
              "Mesmo fluxo de índice na Europa e Índia, onde há menos arbitradores de índice que nos EUA",
              "Só data efetiva (Wikipédia); pre5/pre10: compra quem entra / vende quem sai 5-10 pregões antes (só revisões regulares, anunciadas 2-4 semanas "
              "antes); pos: reversão por 20 pregões; hedge índice local; custo com TTF francesa e STT indiana", indices_loc,
              {"fase": ["pre5", "pre10", "pos"], "lado": ["entra", "ambos"]}, inicio="2008-01-01", corte="2021-01-01", **MM),
        Fundo("IE08 PEAD Ásia (Japão, Coreia, Hong Kong)", "Event-driven", "CDI",
              "Subreação a resultado em mercados com menos cobertura de analistas estrangeiros e muito varejo (Coreia) — e com dado de surpresa (EPS x consenso)",
              "Datas e EPS do Yahoo (2014+), membros ATUAIS do Nikkei 225/KOSPI 200/Hang Seng; reação vs índice local t-1..t+1; 3% por nome; hedge índice local; "
              "impostos KR/HK; sem venda na Coreia nas proibições", pead_asia,
              {"mercados": ["JP+KR+HK", "JP"], "limiar": [.05, .08], "hold": [20, 60]}, inicio="2014-06-01", corte="2021-01-01", **MM),
        Fundo("IE09 Chapter 11 EUA", "Event-driven", "CDI",
              "Pedido de recuperação judicial: credores na frente, a ação costuma ir a zero mas o varejo compra 'barato' (no Brasil o contrarian perdeu 15%/ano)",
              "8-K item 1.03 (busca textual), vende (ou compra) no fechamento seguinte, 20-120 pregões, 5% por nome, aluguel 20% a.a., custo >= 50 bps",
              chapter11, {"lado": ["vende", "compra"], "hold": [20, 60, 120]}, inicio="2008-01-01", corte="2021-01-01", **MM),
    ]




def cobertura():
    """Quantos eventos ficaram sem preço, por ano e por estratégia (viés de sobrevivência) — vai para o caderno."""
    out = {}
    us = _us()
    e = eventos_pead_us()
    out["IE01 PEAD (8-K 2.02 de membros do S&P)"] = e.groupby(e.data.dt.year).tem_preco.mean()
    a = ev_ofertas()
    a = a[a.data >= "2007"]
    out["IE02 ofertas de ações (424B)"] = a.ticker.isin(us["P"].columns).groupby(a.data.dt.year).mean()
    x = ev_ipos()
    x = x[x.data >= "2007"]
    out["IE03 IPOs (1º 424B4/B1)"] = x.ticker.isin(us["P"].columns).groupby(x.data.dt.year).mean()
    a = ev_13d()
    a = a[a.data >= "2007"]
    out["IE04 13D"] = a.ticker.isin(us["P"].columns).groupby(a.data.dt.year).mean()
    a = ev_toi()
    a = a[a.data >= "2007"]
    out["IE05 SC TO-I"] = a.ticker.isin(us["P"].columns).groupby(a.data.dt.year).mean()
    a, _ = eventos_cap11()
    out["IE09 Chapter 11"] = a.tem_preco.groupby(a.data.dt.year).mean()
    ev = _cache("idx_us", ev_indices_us)
    for l in ("entra", "sai"):
        z = ev[ev.lado == l]
        out[f"IE06 S&P/NDX {l}"] = z.ticker.isin(us["P"].columns).groupby(z.efetiva.dt.year).mean()
    return (pd.DataFrame(out) * 100).round(0)


if __name__ == "__main__" and sys.argv[1:2] == ["dados"]:
    o = sys.argv[2:] or ["indice", "wiki", "fts", "asia", "yahoo"]
    if "indice" in o:
        baixa_indice_ie()
    if "wiki" in o:
        wiki_mudancas(), sp500_atual(), membros_asia(), tickers_sec()
    if "fts" in o:
        for k in CONSULTAS:
            fts(k, *CONSULTAS[k])
    if "asia" in o:
        baixa_resultados_asia()
        baixa_precos(list(membros_asia().ticker) + list(IDX_LOCAL.values()) + ["^NDX", "^STOXX50E"], "ie_asia", ini="2006-01-01",
                     extra=["Close", "Volume"], lote_n=50, pausa=1)
        baixa_precos(sorted({x for v in YF_NOME.values() if v for x in v}), "ie_eur", ini="2006-01-01", extra=["Close", "Volume"], lote_n=50, pausa=1)
    if "yahoo" in o:
        U, _ = universo_sp()
        baixa_precos(sorted(set(U.px) | set(U.tk)), "ie_sp", ini="2006-01-01", extra=["Close", "Volume"], lote_n=50, pausa=1)
        baixa_precos(tickers_us(), "ie_us", ini="2006-01-01", extra=["Close", "Volume"], lote_n=50, pausa=1)
    sys.exit()


if __name__ == "__main__":
    from motor import roda
    from rodar import BENCH
    so = sys.argv[1:]
    res = []
    for f in _fundos():
        if so and f.nome[:4] not in so:
            continue
        t0 = time.time()
        r = roda(f, CDI, BENCH[f.benchmark], print)
        if r is None:
            print(f.nome, "sem resultado")
            continue
        e, ct, tr = f.func(**r["params"], detalhe=True)
        r["contrib"], r["trades"] = ct, tr
        o, rb = r["oos"], r["rob"]
        print(f"{f.nome[:45]:45s} {str(r['params']):50s} IR IS {r['is_ir']:5.2f} | OOS {o['retorno a.a. %']:5.1f}% vs {o['benchmark a.a. %']:5.1f}% "
              f"IR {o['IR vs bench']:5.2f} | P {rb['P(bater bench OOS) %']:3.0f}% PBO {rb['PBO %']:3.0f}% | c2 {rb['OOS custo x2 (pp)']:5.1f} "
              f"l1 {rb['OOS execução +1 dia (pp)']:5.1f} | vol {o['vol a.a. %']:4.1f} | {time.time() - t0:.0f}s", flush=True)
        r["fundo"].func = None
        res.append(r)
    if not so:
        try:
            res[0]["cobertura"] = cobertura()
        except Exception as ex:
            print("cobertura", ex)
    nome = "ideias_i_eventos.pkl" if not so else f"ideias_i_eventos_{'_'.join(so)}.pkl"
    pickle.dump(res, open(OUT / nome, "wb"))
