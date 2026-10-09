"""
Monitor ao vivo da carteira de um fundo: para cada ativo, spread e PU agora (negócios da B3 a cada 15 min), variação no dia,
na semana e no mês, últimos negócios, ação do emissor, notícias e fatos relevantes, e alertas. Atualiza sozinho.
Fontes (grátis): posição do fundo (VW_FUNDOS_POSICAO_EXPLODIDA_DOWN, data mais recente), B3 (negócio a negócio, cadastro, futuros),
ANBIMA (taxas indicativas), Tesouro (curvas), TradingView (bonds e ações), FINRA (histórico dos bonds), Bing Notícias, CVM (fatos relevantes).
Uso:  python monitor_fundo.py ULMOPPHF_CCI      -> fundo do banco
      python monitor_fundo.py exemplo           -> carteira de exemplo montada com a lista ativos_iam.xlsx
Abre em http://localhost:7880
"""
import io
import re
import sys
import threading
import time
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

import carteira as ct

PORTA, HIST, MIN_ATUALIZA = 7880, 63, 5               # porta, dias úteis de histórico, minutos entre atualizações
CACHE = ct.PASTA / "dados_monitor"
(CACHE / "b3").mkdir(parents=True, exist_ok=True)
RUIM = re.compile(r"(?i)recupera[cç][aã]o judicial|rebaix|default|calote|inadimpl|reestrutura|vencimento antecipado|waiver|"
                  r"credores|fraude|investiga|pol[ií]cia federal|preju[ií]zo|ren[uú]ncia|downgrade|pedido de falência|liquidez")
TV = {"Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/", "User-Agent": "Mozilla/5.0"}
ESTADO = {"status": "carregando", "log": []}


def log(m):
    ESTADO["log"] = (ESTADO["log"] + [m])[-8:]
    print("  " + m, flush=True)


# ------------------------------------------------------------------ posição
def posicao_banco(fundo):
    """Última posição do fundo, já explodida, sem cotas duplicadas, hedges e despesas; somada por ativo."""
    from sqlalchemy import create_engine, text
    import relatorio_fundos as rf
    v = "VW_FUNDOS_POSICAO_EXPLODIDA_DOWN"
    sql = (f"SELECT date, codigo_IAM_fundo_origem, codigo_IAM_ativo, ticker_bolsa, ativo, tipo, indexador, moeda_ativo, perc_nav, "
           f"total_nav_moeda_fundo, spread_cdi, macaulay_duration, setor_iam, grupo_economico_iam FROM {v} "
           f"WHERE codigo_IAM_fundo = :f AND date = (SELECT MAX(date) FROM {v} WHERE codigo_IAM_fundo = :f)")
    with create_engine(rf.CONEXAO).connect() as c:
        p = pd.read_sql(text(sql), c, params={"f": fundo})
    p = p[~p.codigo_IAM_ativo.isin(set(p.codigo_IAM_fundo_origem)) | p.codigo_IAM_ativo.eq(p.codigo_IAM_fundo_origem)].copy()
    p["categoria"] = rf.categoria(p)
    p = p[~p.categoria.isin(rf.HEDGES + ["Outros"])]
    nome = rf.NOMES.get(fundo, fundo)
    pos = p.groupby("codigo_IAM_ativo").agg(ticker=("ticker_bolsa", "first"), categoria=("categoria", "first"), perc_nav=("perc_nav", "sum"),
                                            setor=("setor_iam", "first"), grupo=("grupo_economico_iam", "first")).reset_index()
    return nome, p.date.max(), p.total_nav_moeda_fundo.sum(), pos.rename(columns={"codigo_IAM_ativo": "codigo"})


def posicao_exemplo(ativos, codigos_negociados):
    """Carteira fictícia com ativos reais da lista IAM (pesos sorteados), preferindo os que negociaram no último mês."""
    rng = np.random.default_rng(3)
    plano = {"DEB": (14, .30), "DEBIN": (7, .17), "LF": (5, .10), "LFSN": (1, .02), "CRA": (3, .05), "CRI": (2, .04), "NC": (2, .03), "Bond": (5, .12)}
    linhas = []
    for cat, (n, peso) in plano.items():
        xs = [a for a in ativos.values() if a["cat"] == cat]
        xs.sort(key=lambda a: (a["cod"] not in codigos_negociados and a["isin"] not in codigos_negociados, rng.random()))
        xs = xs[:n]
        for a, w in zip(xs, rng.dirichlet(np.ones(len(xs)) * 2) * peso):
            linhas.append({"codigo": a["cod"] or a["isin"], "ticker": a["cod"], "categoria": "Bonds" if cat == "Bond" else cat,
                           "perc_nav": w, "setor": None, "grupo": None})
    tot = sum(x["perc_nav"] for x in linhas)
    for x in linhas:
        x["perc_nav"] *= .85 / tot                                         # 85% em crédito, 15% em caixa
    linhas.append({"codigo": "caixa", "ticker": "Caixa", "categoria": "Cash", "perc_nav": .15, "setor": "Caixa", "grupo": None})
    return "Exemplo (ativos da lista IAM)", pd.Timestamp.today().normalize() - pd.offsets.BDay(1), 1.5e9, pd.DataFrame(linhas)


# ------------------------------------------------------------------ mercado
def negocios_dia(d, forcar=False):
    """Negócio a negócio do balcão B3 de um dia (com horário). Dia corrente: rebaixa a cada 15 min."""
    f = CACHE / "b3" / f"{d:%Y%m%d}.parquet"
    hoje = d.normalize() == pd.Timestamp.today().normalize()
    if f.exists() and not forcar and (not hoje or time.time() - f.stat().st_mtime < 900):
        return pd.read_parquet(f)
    try:
        x = ct.b3_csv("Trade", d)
    except requests.RequestException:
        return pd.read_parquet(f) if f.exists() else pd.DataFrame()
    if len(x):
        x = x.iloc[:, :14]
        x.columns = ["tipo", "emissor", "cod", "qtd", "pu", "vol", "taxa", "origem", "hora", "data", "id", "isn", "liq", "situacao"]
        x = x[x.tipo.isin(["DEB", "CRI", "CRA", "LF", "LFSN", "LFSC", "NC", "CFF"]) & x.situacao.ne("Cancelado")]
        x = x.assign(qtd=ct.num(x.qtd), pu=ct.num(x.pu), vol=ct.num(x.vol), taxa=ct.num(x.taxa), data=pd.Timestamp(d.normalize()))
        x = x[["data", "hora", "tipo", "cod", "isn", "qtd", "pu", "vol", "taxa", "origem"]]
    x.to_parquet(f)
    return x


def futuros_agora():
    """DI1, DAP e dólar ao vivo (15 min): taxa atual e variação contra o ajuste anterior, nos vértices principais."""
    out = []
    for cls, alvos in (("DI1", [1, 3, 5]), ("DAP", [3, 8]), ("DOL", [0])):
        try:
            sc = ct.get(f"https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/{cls}", timeout=20, tent=2).json().get("Scty", [])
        except (requests.RequestException, ValueError):
            continue
        xs = [(pd.Timestamp(s["asset"]["AsstSummry"]["mtrtyCode"]), s["symb"], s["SctyQtn"].get("curPrc"), s["SctyQtn"].get("prvsDayAdjstmntPric"),
               s["asset"]["AsstSummry"].get("opnCtrcts", 0)) for s in sc if s.get("asset", {}).get("AsstSummry", {}).get("mtrtyCode")]
        xs = [x for x in xs if x[0] > pd.Timestamp.today()]
        for a in alvos:
            if not xs:
                break
            alvo = pd.Timestamp.today() + pd.DateOffset(years=a)
            v, tk, cur, ant, _ = min(xs, key=lambda x: (abs((x[0] - alvo).days), -x[4]))
            if cur and ant:
                out.append({"nome": tk, "valor": cur, "var": (cur - ant) * (100 if cls != "DOL" else 1) if cls != "DOL" else (cur / ant - 1) * 100,
                            "unid": "bps" if cls != "DOL" else "%"})
    try:
        j = requests.post("https://scanner.tradingview.com/brazil/scan", json={"symbols": {"tickers": ["BMFBOVESPA:IBOV"]}, "columns": ["close", "change"]},
                          headers=TV, timeout=20).json()["data"][0]["d"]
        out.append({"nome": "Ibovespa", "valor": j[0], "var": j[1], "unid": "%"})
    except (requests.RequestException, KeyError, IndexError, ValueError):
        pass
    return out


def acoes(emis):
    """Ação de cada emissor listado (código de emissor B3 de 4 letras -> ticker 3/4/11), ao vivo pelo TradingView."""
    tks = [f"BMFBOVESPA:{e}{s}" for e in emis for s in ("3", "4", "11")]
    out = {}
    for i in range(0, len(tks), 300):
        try:
            j = requests.post("https://scanner.tradingview.com/brazil/scan", headers=TV, timeout=30,
                              json={"symbols": {"tickers": tks[i:i + 300]}, "columns": ["close", "change", "Perf.W", "Perf.1M", "volume"]}).json()
        except (requests.RequestException, ValueError):
            continue
        for x in j.get("data", []):
            e = x["s"].split(":")[1][:4]
            if e not in out or (x["d"][4] or 0) > out[e]["volume"]:
                out[e] = dict(zip(["preco", "dia", "semana", "mes", "volume"], x["d"]), ticker=x["s"].split(":")[1])
    return out


def nome_busca(emissor):
    w = [p for p in re.sub(r"[^\w\s']", " ", str(emissor)).split() if p.upper() not in
         {"SA", "S", "A", "CIA", "COMPANHIA", "DE", "DO", "DA", "DOS", "E", "PARTICIPACOES", "PARTICIPAÇÕES", "HOLDING", "LTDA", "BANCO", "FINANCE",
          "SARL", "BV", "NETHERLANDS", "LUX", "EUROPE", "INTERNATIONAL", "SECURITIZADORA", "INVESTIMENTOS", "BRASIL", "GOVERNMENT", "OF"}]
    return " ".join(w[:2]).title() if w and len(w[0]) < 5 else (w[0].title() if w else "")


def noticias(nome):
    """Notícias do emissor: Bing Notícias (agrega Valor, InfoMoney, Estadão, Reuters...) e posts do Reddit que citam o nome."""
    out = []
    item = lambda t, link, d, fonte: {"titulo": t, "link": link, "fonte": fonte, "ruim": bool(RUIM.search(t)),
                                      "data": d.tz_convert("America/Sao_Paulo").strftime("%d/%m %H:%M") if pd.notna(d) else "",
                                      "dias": (pd.Timestamp.now(tz="UTC") - d).days if pd.notna(d) else 99}
    try:
        r = requests.get("https://www.bing.com/news/search", params={"q": f'"{nome}"', "format": "rss", "setlang": "pt-BR", "cc": "BR"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        for i in ET.fromstring(r.content).findall(".//item")[:8]:
            out.append(item(i.findtext("title") or "", i.findtext("link"), pd.to_datetime(i.findtext("pubDate"), errors="coerce", utc=True), "notícia"))
    except (requests.RequestException, ET.ParseError):
        pass
    try:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        r = requests.get("https://www.reddit.com/search.rss", params={"q": f'"{nome}"', "sort": "new", "t": "month"},
                         headers={"User-Agent": "monitor-fundo/0.1"}, timeout=20)
        for e in ET.fromstring(r.content).findall("a:entry", ns):
            link, t = e.find("a:link", ns).get("href"), e.findtext("a:title", namespaces=ns) or ""
            if "/comments/" in link and nome.split()[0].lower() in (t + (e.findtext("a:content", namespaces=ns) or "")).lower():
                sub = e.find("a:category", ns)
                out.append(item(f"{sub.get('label') if sub is not None else 'Reddit'}: {t}", link,
                                pd.to_datetime(e.findtext("a:updated", namespaces=ns), errors="coerce", utc=True), "reddit"))
    except (requests.RequestException, ET.ParseError, AttributeError):
        pass
    return sorted(out, key=lambda x: x["dias"])[:12]


def fatos_relevantes():
    """Fatos relevantes e comunicados ao mercado entregues à CVM nos últimos 30 dias."""
    f = CACHE / "ipe.parquet"
    if ct.velho(f, 6):
        try:
            z = zipfile.ZipFile(io.BytesIO(ct.get(f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{pd.Timestamp.today().year}.zip").content))
            d = pd.read_csv(z.open(z.namelist()[0]), sep=";", encoding="latin1", dtype=str)
            d = d[d.Categoria.isin(["Fato Relevante", "Comunicado ao Mercado"])]
            d.assign(Data_Entrega=pd.to_datetime(d.Data_Entrega)).to_parquet(f)
        except (requests.RequestException, zipfile.BadZipFile, KeyError):
            if not f.exists():
                return pd.DataFrame(columns=["Nome_Companhia", "Data_Entrega", "Categoria", "Assunto", "Link_Download"])
    d = pd.read_parquet(f)
    return d[d.Data_Entrega >= pd.Timestamp.today() - pd.Timedelta(days=30)]


# ------------------------------------------------------------------ cálculo
def emissores():
    """Código de emissor B3 (4 letras) -> nome completo e CNPJ (EMISSOR.TXT da base de ISINs da B3)."""
    import base64
    f = CACHE / "emissores.parquet"
    if ct.velho(f, 72):
        i = ct.get("https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetTextDownload/").json()["geralPt"]["id"]
        z = zipfile.ZipFile(io.BytesIO(ct.get("https://sistemaswebb3-listados.b3.com.br/isinProxy/IsinCall/GetFileDownload/"
                                              + base64.b64encode(str(i).encode()).decode(), timeout=300).content))
        pd.read_csv(z.open("EMISSOR.TXT"), header=None, dtype=str, encoding="utf-8", encoding_errors="replace", usecols=[0, 1, 2],
                    names=["emi", "nome", "cnpj"]).drop_duplicates("emi").to_parquet(f)
    return pd.read_parquet(f).set_index("emi")


def para_spread(a, taxa, dia, D, cur, cdi_aa):
    """Taxa de negócio/ANBIMA -> spread sobre o CDI (pp). DI+: a própria taxa; %DI: (taxa-100)% do CDI; IPCA+/pré: taxa - curva."""
    idx = a["idx"]
    if idx == "DI" and taxa > 40:                                          # negócio informado em % do CDI
        idx = "%DI"
    if idx == "DI":
        return taxa
    if idx == "%DI":
        return (taxa / 100 - 1) * cdi_aa * 100
    if idx in ("IPCA", "PRE"):
        return taxa - cur("IPCA" if idx == "IPCA" else "PRE", dia, max(D, .3))
    return np.nan


def serie_spread(a, neg, an, D, cur, cdi_aa, dias):
    """Spread diário (ANBIMA quando existe; senão mediana ponderada dos negócios do dia) e o valor ao vivo de hoje."""
    obs = {}
    n = neg[neg.taxa.notna() & (neg.vol > 0)]
    for d, g in n.groupby("data"):
        obs[d] = para_spread(a, ct.mediana_pond(g.taxa.values, g.vol.values), d, D, cur, cdi_aa)
    for r in an.itertuples():
        obs[r.data] = para_spread(a, r.taxa, r.data, D, cur, cdi_aa)
    s = pd.Series(obs, dtype=float, index=pd.DatetimeIndex(list(obs))).sort_index()
    s = s[(s > -5) & (s < 60)]
    return s[s.index.isin(dias)]


def monta():
    t0 = time.time()
    hoje = pd.Timestamp.today().normalize()
    ESTADO["status"] = "carregando"
    log("Cadastro B3, base de ISINs, curvas e futuros...")
    vencs, vivo = ct.futuros_b3()
    cad, isn = ct.cadastro(), ct.isins()
    cdi = ct.sgs(12, hoje - pd.Timedelta(days=200)) / 100
    dias = list(cdi.index[-HIST:]) + ([hoje] if hoje.weekday() < 5 and hoje not in cdi.index else [])
    cdi_aa = (1 + cdi.iloc[-1]) ** 252 - 1
    cur = ct.Curvas(ct.tesouro(), ct.treasury(), vivo)
    log(f"Negócios da B3 ({len(dias)} dias)...")
    with ThreadPoolExecutor(6) as ex:
        neg = pd.concat([x for x in ex.map(negocios_dia, dias) if len(x)], ignore_index=True)
    if MODO == "exemplo":
        codigos = ct.le_lista()
        ativos, _, _ = ct.identifica(codigos, cad, isn, vencs)
        nomef, data_pos, pl, pos = posicao_exemplo(ativos, set(neg[neg.data >= dias[-22]].cod) | set(neg[neg.data >= dias[-22]].isn))
    else:
        nomef, data_pos, pl, pos = posicao_banco(MODO)
        ativos, _, _ = ct.identifica(list(pos.codigo) + list(pos.ticker.dropna()), cad, isn, vencs)
    emis_b3 = emissores()
    porcod = {}
    for a in ativos.values():
        e = (a["isin"] or "")[2:6] if str(a["isin"]).startswith("BR") else None
        a["cnpj"] = emis_b3.cnpj.get(e)
        if len(str(a["emissor"] or "")) <= 5 and e in emis_b3.index:      # veio só o código de emissor de 4 letras
            a["emissor"] = emis_b3.at[e, "nome"]
        for k in (a["cod"], a["isin"]):
            if k:
                porcod[k] = a
    an = ct.anbima()
    bonds = [porcod[c]["isin"] for c in pos.codigo if c in porcod and porcod[c]["idx"] == "USD"]
    log("TradingView, FINRA, ações, notícias e fatos relevantes...")
    tv = ct.tradingview(bonds)
    fin = ct.finra([b for b in bonds if not b.startswith("US912")], dias[0])
    isn_i = isn.drop_duplicates("isn").set_index("isn")
    emi = {c: (isn_i.at[porcod[c]["isin"], "emi"] if c in porcod and porcod[c]["isin"] in isn_i.index else None) for c in pos.codigo}
    acs = acoes(sorted({e for e in emi.values() if isinstance(e, str) and len(e) == 4}))
    nomes = {c: nome_busca(porcod[c]["emissor"] or (tv.get(porcod[c]["isin"], {}).get("description") or "")) if c in porcod else "" for c in pos.codigo}
    peso_nome = pos.assign(n=pos.codigo.map(nomes)).groupby("n").perc_nav.sum().sort_values(ascending=False)
    with ThreadPoolExecutor(6) as ex:
        news = dict(zip(peso_nome.index[:35], ex.map(noticias, peso_nome.index[:35])))
    ipe = fatos_relevantes()

    linhas, detalhe = [], {}
    for r in pos.itertuples():
        a = porcod.get(r.codigo) or porcod.get(r.ticker)
        base = {"codigo": r.codigo, "categoria": r.categoria, "pl": r.perc_nav * 100, "emissor": "", "indexador": "", "taxa_emissao": "",
                "venc": "", "spread": None, "d1": None, "d5": None, "d21": None, "dur": None, "pu": None, "ult_hora": "", "ult_taxa": None,
                "neg_hoje": 0, "vol_hoje": 0.0, "acao": None, "acao_tk": "", "noticias": 0, "ruins": 0, "impacto": 0.0, "fonte": ""}
        if a is None:
            linhas.append(base | {"fonte": "sem dado público"})
            continue
        T = (a["venc"] - hoje).days / 365.25 if pd.notna(a["venc"]) else np.nan
        base.update(emissor=str(a["emissor"] or "").title()[:40], indexador=a["idx"], venc=a["venc"].strftime("%m/%Y") if pd.notna(a["venc"]) else "",
                    taxa_emissao={"DI": f"CDI + {a['taxa']:.2f}", "%DI": f"{a['taxa']:.0f}% CDI", "IPCA": f"IPCA + {a['taxa']:.2f}",
                                  "PRE": f"{a['taxa']:.2f}% pré", "USD": f"US$ {a['taxa'] or 0:.2f}%"}.get(a["idx"], ""))
        nm = nomes.get(r.codigo, "")
        nw = news.get(nm, [])
        cnpj = a.get("cnpj") if a else None
        fr = ipe[ipe.CNPJ_Companhia.str.replace(r"\D", "", regex=True).eq(cnpj)] if cnpj else             (ipe[ipe.Nome_Companhia.str.upper().str.contains(nm.upper().split()[0], regex=False, na=False)] if nm else ipe.iloc[:0])
        base.update(noticias=len([x for x in nw if x["dias"] <= 7]), ruins=len([x for x in nw if x["ruim"] and x["dias"] <= 7]) + len(fr[fr.Categoria.eq("Fato Relevante")]))
        e = emi.get(r.codigo)
        if e in acs:
            base.update(acao=acs[e]["dia"], acao_tk=acs[e]["ticker"])
        if a["idx"] == "USD":                                              # bond: preço e yield ao vivo, spread sobre o Treasury
            t = tv.get(a["isin"], {})
            p = fin[fin.isn == a["isin"]].drop_duplicates("data", keep="last").set_index("data").preco.sort_index()
            cup = re.search(r"(\d+(?:\.\d+)?)%", t.get("description") or "")
            cup = float(cup.group(1)) if cup else 0.0
            venc = pd.to_datetime(str(int(t["maturity_date"])), format="%Y%m%d") if t.get("maturity_date") else a["venc"]
            if pd.notna(venc):
                anos = lambda d: max((venc - d).days / 365.25, .05)
                hist = pd.Series(dtype=float, index=pd.DatetimeIndex([])) if p.empty else pd.Series({d: ct.ytm(np.array([v]), np.array([cup]), np.array([anos(d)]))[0] - cur("UST", d, anos(d)) for d, v in p.items()}, dtype=float)
                if t.get("yield_to_maturity"):
                    hist.loc[hoje] = t["yield_to_maturity"] - cur("UST", hoje, anos(hoje))
                hist = hist[hist.index >= dias[0]]
                if len(hist):
                    s = hist
                    base.update(spread=s.iloc[-1], d1=(s.iloc[-1] - s.iloc[-2]) * 100 if len(s) > 1 else None,
                                d5=(s.iloc[-1] - s.iloc[max(-6, -len(s))]) * 100, d21=(s.iloc[-1] - s.iloc[0]) * 100 if len(s) > 15 else None)
                base.update(dur=t.get("modified_duration"), pu=t.get("close"), emissor=re.sub(r"\s+\d.*$", "", t.get("description") or base["emissor"]),
                            venc=venc.strftime("%m/%Y"), fonte="TradingView + FINRA", impacto=(t.get("change") or 0) * r.perc_nav * 100)
                detalhe[r.codigo] = {"serie": [[d.strftime("%Y-%m-%d"), round(v, 3)] for d, v in hist.items()], "pu": [[d.strftime("%Y-%m-%d"), v] for d, v in p.items()],
                                     "negocios": [], "noticias": nw, "fatos": [], "tipo": "bond"}
            linhas.append(base)
            continue
        n = neg[((neg.cod == a["cod"]) & (a["cod"] != "")) | ((neg.isn == a["isin"]) & (a["isin"] != ""))]
        a_an = an[an.cod == a["cod"]] if a["cod"] else an.iloc[:0]
        D = float(a_an.dur.iloc[-1]) if len(a_an) and pd.notna(a_an.dur.iloc[-1]) else \
            ct.duracao(a["cat"], T if np.isfinite(T) else 2, cdi_aa + (a["taxa"] or 0) / 100)
        s = serie_spread(a, n, a_an[a_an.data.isin(dias)], D, cur, cdi_aa, dias)
        nh = n[n.data == hoje]
        ant = s[s.index < hoje]
        if len(s):
            atual = s.iloc[-1]
            ref = lambda k: (atual - ant.iloc[-k]) * 100 if len(ant) >= k else None
            base.update(spread=atual, d1=ref(1) if s.index[-1] == hoje else (atual - ant.iloc[-2]) * 100 if len(ant) >= 2 else None,
                        d5=ref(5), d21=ref(21))
            if s.index[-1] == hoje and len(ant):
                base["impacto"] = -D * (atual - ant.iloc[-1]) * r.perc_nav * 100
        base.update(dur=D, pu=float(n.pu.iloc[-1]) if len(n) else None, neg_hoje=len(nh), vol_hoje=float(nh.vol.sum()),
                    fonte=("ANBIMA + " if len(a_an) else "") + ("negócios B3" if len(n) else "") or "sem negócio recente")
        if len(n):
            u = n.sort_values(["data", "hora"]).iloc[-1]
            base.update(ult_hora=f"{u.data:%d/%m} {u.hora or ''}"[:14], ult_taxa=u.taxa)
        detalhe[r.codigo] = {"serie": [[d.strftime("%Y-%m-%d"), round(v, 3)] for d, v in s.items()],
                             "pu": [[d.strftime("%Y-%m-%d"), float(g.pu.median())] for d, g in n.groupby("data")],
                             "negocios": n.sort_values(["data", "hora"], ascending=False).head(25).assign(data=lambda x: x.data.dt.strftime("%d/%m"))
                             [["data", "hora", "qtd", "pu", "vol", "taxa", "origem"]].fillna("").to_dict("records"),
                             "noticias": nw, "tipo": "local",
                             "fatos": fr.sort_values("Data_Entrega", ascending=False).head(6).assign(d=lambda x: x.Data_Entrega.dt.strftime("%d/%m"))
                             [["d", "Categoria", "Assunto", "Link_Download"]].to_dict("records")}
        linhas.append(base)

    L = pd.DataFrame(linhas)
    alertas = []
    for x in L.itertuples():
        nome = f"{x.codigo} ({x.emissor[:22]})" if x.emissor else x.codigo
        if x.d1 is not None and pd.notna(x.d1) and abs(x.d1) >= 25:
            alertas.append((abs(x.d1) / 25, "spread", f"{nome}: spread {'abriu' if x.d1 > 0 else 'fechou'} {abs(x.d1):.0f} bps no dia", x.codigo, x.d1 > 0))
        if x.d5 is not None and pd.notna(x.d5) and abs(x.d5) >= 50:
            alertas.append((abs(x.d5) / 50, "spread", f"{nome}: spread {'abriu' if x.d5 > 0 else 'fechou'} {abs(x.d5):.0f} bps na semana", x.codigo, x.d5 > 0))
        if x.acao is not None and pd.notna(x.acao) and abs(x.acao) >= 4:
            alertas.append((abs(x.acao) / 4, "ação", f"{nome}: ação {x.acao_tk} {x.acao:+.1f}% hoje", x.codigo, x.acao < 0))
        if x.ruins:
            alertas.append((1.5 + x.ruins / 2, "notícia", f"{nome}: {x.ruins} notícia(s)/fato(s) relevante(s) de atenção", x.codigo, True))
        if x.neg_hoje >= 5:
            alertas.append((.8, "liquidez", f"{nome}: {x.neg_hoje} negócios hoje (R$ {x.vol_hoje / 1e6:.1f} mi)", x.codigo, False))
    alertas.sort(key=lambda z: -z[0] * (1 + .5 * z[4]))
    cred = L[L.spread.notna()]
    w = cred.pl / cred.pl.sum() if len(cred) else cred.pl
    ESTADO.update(status="ok", dados={
        "fundo": nomef, "data_pos": f"{pd.Timestamp(data_pos):%d/%m/%Y}", "pl": pl, "atualizado": pd.Timestamp.now().strftime("%d/%m %H:%M"),
        "b3_hoje": int((neg.data == hoje).sum()), "mercado": futuros_agora(), "ativos": L.replace({np.nan: None}).to_dict("records"),
        "kpi": {"spread": float((cred.spread * w).sum()) if len(cred) else None, "d1": float((cred.d1.fillna(0) * w).sum()) if len(cred) else None,
                "d21": float((cred.d21.fillna(0) * w).sum()) if len(cred) else None, "dur": float((L.dur.fillna(0) * L.pl).sum() / max(L.pl.sum(), 1e-9)),
                "impacto": float(L.impacto.sum()), "negociados": int((L.neg_hoje > 0).sum()), "n": len(L)},
        "alertas": [{"txt": t, "tipo": k, "codigo": c, "ruim": bool(rb)} for _, k, t, c, rb in alertas[:40]]})
    ESTADO["detalhe"] = detalhe
    log(f"Pronto em {time.time() - t0:.0f}s: {len(L)} ativos, {len(alertas)} alertas.")


def laco():
    while True:
        try:
            monta()
        except Exception as e:                                             # mostra o erro na página e tenta de novo depois
            import traceback
            traceback.print_exc()
            ESTADO.update(status="erro" if ESTADO.get("dados") is None else "ok", erro=f"{type(e).__name__}: {e}")
        time.sleep(MIN_ATUALIZA * 60)


app = FastAPI(title="Monitor do fundo")


@app.get("/api/estado")
def api_estado():
    if ESTADO.get("dados") is None:
        return JSONResponse({"status": ESTADO["status"], "log": ESTADO["log"], "erro": ESTADO.get("erro")})
    return JSONResponse({"status": "ok", **ESTADO["dados"]})


@app.get("/api/ativo/{cod}")
def api_ativo(cod: str):
    return JSONResponse(ESTADO.get("detalhe", {}).get(cod, {}))


@app.get("/", response_class=HTMLResponse)
def pagina():
    return HTML


HTML = r"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor do fundo</title><script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>
:root{--bg:#f5f6f8;--sf:#fff;--sf2:#f0f1f4;--ln:#e3e5ea;--t1:#14161a;--t2:#4d525c;--mu:#8a8f99;--lar:#EC7000;--azul:#003399;--good:#0f7b3f;--bad:#c43d3d;
--font:"Segoe UI",-apple-system,Roboto,Arial,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1012;--sf:#17191c;--sf2:#1f2226;--ln:#2a2d32;--t1:#f2f3f5;--t2:#b7bcc6;--mu:#858b96;--azul:#5a8cf0;--good:#2fbf6b;--bad:#ef6b6b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t1);font:14px/1.45 var(--font)}
.topo{background:var(--lar);color:#fff;padding:12px 20px;display:flex;flex-wrap:wrap;gap:14px;align-items:center;border-bottom:4px solid var(--azul)}
.topo h1{margin:0;font-size:19px}.topo .sub{font-size:12px;opacity:.9}.esp{flex:1}
.fita{display:flex;gap:6px;flex-wrap:wrap}.tick{background:rgba(255,255,255,.16);border-radius:8px;padding:4px 9px;font-size:12px}
.tick b{font-size:13px}.up{color:#c8ffd9}.dn{color:#ffd0d0}
main{padding:14px 20px;max-width:1500px;margin:0 auto}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:12px}
.kpi,.card{background:var(--sf);border:1px solid var(--ln);border-radius:12px;padding:11px 13px}.kpi b{display:block;font-size:21px}.kpi span{color:var(--t2);font-size:12px}
.grid{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:12px;margin-bottom:12px}@media(max-width:1000px){.grid{grid-template-columns:1fr}}
.card h3{margin:0 0 6px;font-size:14px;color:var(--azul)}
.alertas{max-height:300px;overflow:auto;margin:0;padding:0;list-style:none}.alertas li{padding:6px 8px;border-bottom:1px solid var(--ln);cursor:pointer;font-size:13px}
.alertas li:hover{background:var(--sf2)}.pill{display:inline-block;font-size:10.5px;border-radius:99px;padding:1px 7px;margin-right:6px;background:var(--sf2);color:var(--t2);text-transform:uppercase}
.pill.r{background:rgba(196,61,61,.13);color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:12.5px}th,td{padding:5px 7px;border-bottom:1px solid var(--ln);text-align:right;white-space:nowrap}
th{color:#fff;background:var(--azul);position:sticky;top:0;cursor:pointer;font-weight:600}th:nth-child(-n+3),td:nth-child(-n+3){text-align:left}
tbody tr{cursor:pointer}tbody tr:hover{background:var(--sf2)}.pos{color:var(--good)}.neg{color:var(--bad)}.mu{color:var(--mu)}
.tab{max-height:620px;overflow:auto}.filtros{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}
input{font:inherit;border:1px solid var(--ln);background:var(--sf);color:var(--t1);border-radius:8px;padding:6px 10px;min-width:240px}
.chip{border:1px solid var(--ln);background:var(--sf);color:var(--t2);border-radius:99px;padding:4px 11px;cursor:pointer;font:inherit;font-size:12.5px}
.chip.sel{border-color:var(--lar);color:var(--lar);font-weight:600}
#det{position:fixed;inset:0;background:rgba(0,0,0,.35);display:none;z-index:10}#det .p{position:absolute;right:0;top:0;bottom:0;width:min(940px,100%);background:var(--bg);overflow:auto;padding:16px 20px}
.fecha{float:right;border:1px solid var(--ln);background:var(--sf);border-radius:8px;padding:4px 10px;cursor:pointer;color:var(--t1)}
.news a{color:var(--t1);text-decoration:none}.news li{margin:5px 0}.news .r{color:var(--bad);font-weight:600}
#carga{padding:60px;text-align:center;color:var(--t2)}
</style></head><body>
<div class="topo"><div><h1 id="nome">Monitor do fundo</h1><div class="sub" id="sub">carregando…</div></div><div class="esp"></div><div class="fita" id="fita"></div></div>
<main><div id="carga">Carregando os dados…<div id="log" class="mu"></div></div><div id="app" style="display:none">
<div class="kpis" id="kpis"></div>
<div class="grid"><div class="card"><h3>Alertas</h3><ul class="alertas" id="alertas"></ul></div>
<div class="card"><h3>Composição e spread por categoria</h3><div id="g_cat" style="height:280px"></div></div>
<div class="card"><h3>Impacto estimado hoje (bps do PL)</h3><div id="g_imp" style="height:280px"></div></div></div>
<div class="card"><div class="filtros"><input id="busca" placeholder="Buscar ativo ou emissor…"><span id="cats"></span></div>
<div class="tab"><table><thead><tr id="cab"></tr></thead><tbody id="corpo"></tbody></table></div>
<p class="mu" style="font-size:12px;margin:6px 0 0">Spread sobre o CDI (bonds: sobre o Treasury). Atual = negócios de hoje na B3 (15 min) ou a última marcação ANBIMA/negócio.
Δ em bps contra 1, 5 e 21 dias úteis. Impacto = −duration × variação do spread de hoje × %PL (bonds: variação do preço × %PL). Atualiza a cada 5 min.</p></div>
</div></main><div id="det"><div class="p" id="detp"></div></div>
<script>
const $=s=>document.querySelector(s),css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const f=(v,d=2)=>v==null||isNaN(v)?'–':(+v).toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d});
const fs=(v,d=0)=>v==null||isNaN(v)?'–':(v>0?'+':'')+f(v,d), cl=(v,inv)=>v==null?'':((inv?-v:v)>0.5?'neg':(inv?-v:v)<-0.5?'pos':'');
let D,st={cat:'Todas',q:'',ord:'pl',dir:-1};
const lay=o=>Object.assign({margin:{l:46,r:10,t:6,b:30},paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(0,0,0,0)',font:{family:css('--font'),size:11.5,color:css('--t2')},
 xaxis:{gridcolor:css('--ln')},yaxis:{gridcolor:css('--ln'),zerolinecolor:css('--ln')},showlegend:false},o),cfg={displayModeBar:false,responsive:true};
async function carrega(){const r=await (await fetch('/api/estado')).json();
 if(r.status!=='ok'){$('#log').innerHTML=(r.log||[]).join('<br>')+(r.erro?'<br><b>'+r.erro+'</b>':'');setTimeout(carrega,3000);return}
 D=r;$('#carga').style.display='none';$('#app').style.display='';desenha();setTimeout(carrega,60000)}
function desenha(){
 $('#nome').textContent=D.fundo;$('#sub').textContent=`Posição de ${D.data_pos} · PL R$ ${f(D.pl/1e6,0)} mi · mercado atualizado ${D.atualizado} · ${D.b3_hoje} negócios na B3 hoje`;
 $('#fita').innerHTML=D.mercado.map(m=>`<span class="tick">${m.nome} <b>${f(m.valor,m.unid=='%'&&m.valor>1000?0:m.unid=='%'?4:3)}</b> <span class="${(m.var>0)==(m.unid=='bps')?'dn':'up'}">${fs(m.var,m.unid=='bps'?0:2)}${m.unid=='bps'?' bps':'%'}</span></span>`).join('');
 const k=D.kpi;
 $('#kpis').innerHTML=[[f(k.spread),'Spread médio ponderado (%)'],[fs(k.d1),'Spread hoje (bps)'],[fs(k.d21),'Spread no mês (bps)'],[f(k.dur,1),'Duration (anos)'],
  [fs(k.impacto,1),'Impacto estimado hoje (bps)'],[`${k.negociados} de ${k.n}`,'Ativos negociados hoje'],[D.alertas.length,'Alertas']]
  .map((x,i)=>`<div class="kpi"><b class="${i==1||i==2?cl(+String(x[0]).replace(',','.'),false):i==4?cl(-k.impacto):''}">${x[0]}</b><span>${x[1]}</span></div>`).join('');
 $('#alertas').innerHTML=D.alertas.length?D.alertas.map(a=>`<li data-c="${a.codigo}"><span class="pill ${a.ruim?'r':''}">${a.tipo}</span>${a.txt}</li>`).join(''):'<li class="mu">Nenhum alerta.</li>';
 $('#alertas').onclick=e=>{const l=e.target.closest('li');if(l&&l.dataset.c)abre(l.dataset.c)};
 const cats=[...new Set(D.ativos.map(a=>a.categoria))];const soma=(c,k)=>D.ativos.filter(a=>a.categoria==c).reduce((s,a)=>s+(a[k]||0),0);
 const sp=c=>{const xs=D.ativos.filter(a=>a.categoria==c&&a.spread!=null);const w=xs.reduce((s,a)=>s+a.pl,0);return w?xs.reduce((s,a)=>s+a.spread*a.pl,0)/w:null};
 cats.sort((a,b)=>soma(b,'pl')-soma(a,'pl'));
 Plotly.react('g_cat',[{type:'bar',x:cats,y:cats.map(c=>soma(c,'pl')),marker:{color:css('--azul')},name:'%PL',hovertemplate:'%{x}: %{y:.1f}% do PL<extra></extra>'},
  {type:'scatter',mode:'markers+text',x:cats,y:cats.map(sp),yaxis:'y2',marker:{color:css('--lar'),size:10},text:cats.map(c=>sp(c)==null?'':f(sp(c))),textposition:'top center',
   hovertemplate:'%{x}: spread %{y:.2f}%<extra></extra>'}],lay({yaxis:{ticksuffix:'%',gridcolor:css('--ln')},yaxis2:{overlaying:'y',side:'right',showgrid:false,ticksuffix:'%'}}),cfg);
 Plotly.react('g_imp',[{type:'bar',orientation:'h',y:cats,x:cats.map(c=>soma(c,'impacto')),marker:{color:cats.map(c=>soma(c,'impacto')>=0?css('--good'):css('--bad'))},
  hovertemplate:'%{y}: %{x:.2f} bps<extra></extra>'}],lay({margin:{l:70,r:10,t:6,b:30},yaxis:{autorange:'reversed'}}),cfg);
 $('#cats').innerHTML=['Todas',...cats].map(c=>`<button class="chip ${c==st.cat?'sel':''}" data-c="${c}">${c}</button>`).join(' ');
 $('#cats').onclick=e=>{const b=e.target.closest('button');if(b){st.cat=b.dataset.c;desenha()}};$('#busca').oninput=e=>{st.q=e.target.value.toLowerCase();tabela()};tabela()}
function tabela(){
 const C=[['codigo','Ativo'],['categoria','Categoria'],['emissor','Emissor'],['pl','%PL'],['taxa_emissao','Emissão'],['spread','Spread (%)'],['d1','Δ dia'],['d5','Δ 5d'],['d21','Δ 21d'],
  ['dur','Duration'],['pu','PU / preço'],['ult_hora','Último negócio'],['ult_taxa','Taxa'],['neg_hoje','Negócios hoje'],['acao','Ação hoje'],['noticias','Notícias 7d'],['impacto','Impacto (bps)']];
 let L=D.ativos.filter(a=>(st.cat=='Todas'||a.categoria==st.cat)&&(!st.q||(a.codigo+a.emissor).toLowerCase().includes(st.q)));
 L.sort((a,b)=>{const x=a[st.ord],y=b[st.ord];return (x==null)-(y==null)||(typeof x=='string'?x.localeCompare(y):x-y)*st.dir});
 $('#cab').innerHTML=C.map(c=>`<th data-k="${c[0]}">${c[1]}${st.ord==c[0]?(st.dir>0?' ▲':' ▼'):''}</th>`).join('');
 $('#cab').onclick=e=>{const k=e.target.dataset.k;if(k){st.dir=st.ord==k?-st.dir:-1;st.ord=k;tabela()}};
 $('#corpo').innerHTML=L.map(a=>`<tr data-c="${a.codigo}"><td><b>${a.codigo}</b></td><td>${a.categoria}</td><td>${a.emissor||'<span class=mu>'+a.fonte+'</span>'}</td><td>${f(a.pl,2)}</td>
  <td>${a.taxa_emissao}</td><td><b>${f(a.spread)}</b></td><td class="${cl(a.d1)}">${fs(a.d1)}</td><td class="${cl(a.d5)}">${fs(a.d5)}</td><td class="${cl(a.d21)}">${fs(a.d21)}</td>
  <td>${f(a.dur,1)}</td><td>${f(a.pu,2)}</td><td>${a.ult_hora||'–'}</td><td>${f(a.ult_taxa,2)}</td><td>${a.neg_hoje||''}</td>
  <td class="${cl(a.acao,true)}">${a.acao==null?'':fs(a.acao,1)+'% '+a.acao_tk}</td><td>${a.noticias?(a.ruins?'<b class=neg>'+a.noticias+' ⚠</b>':a.noticias):''}</td>
  <td class="${cl(-a.impacto)}">${a.impacto?fs(a.impacto,2):''}</td></tr>`).join('');
 $('#corpo').onclick=e=>{const t=e.target.closest('tr');if(t)abre(t.dataset.c)}}
function fecha(){$('#det').style.display='none'}$('#det').onclick=e=>{if(e.target.id=='det')fecha()};document.onkeydown=e=>{if(e.key=='Escape')fecha()};
async function abre(c){const a=D.ativos.find(x=>x.codigo==c);if(!a)return;const s=await (await fetch('/api/ativo/'+encodeURIComponent(c))).json();
 $('#detp').innerHTML=`<button class="fecha" onclick="fecha()">Fechar ✕</button><h2 style="margin:0">${a.codigo} <span class="pill">${a.categoria}</span></h2>
 <div class="mu">${a.emissor} · ${a.taxa_emissao} · venc. ${a.venc} · ${f(a.pl,2)}% do PL · duration ${f(a.dur,1)} · fonte: ${a.fonte}</div>
 <div class="kpis" style="margin-top:10px">${[[f(a.spread),'Spread agora (%)'],[fs(a.d1),'Δ dia (bps)'],[fs(a.d5),'Δ 5 dias (bps)'],[fs(a.d21),'Δ 21 dias (bps)'],
 [a.acao==null?'–':fs(a.acao,1)+'%','Ação '+(a.acao_tk||'')]].map(x=>`<div class="kpi"><b>${x[0]}</b><span>${x[1]}</span></div>`).join('')}</div>
 <div class="card"><h3>Spread (%) · ${s.tipo=='bond'?'sobre o Treasury':'sobre o CDI'}</h3><div id="d1" style="height:250px"></div></div>
 <div class="card" style="margin-top:12px"><h3>${s.tipo=='bond'?'Preço (FINRA)':'PU dos negócios (mediana do dia)'}</h3><div id="d2" style="height:200px"></div></div>
 ${(s.negocios||[]).length?`<div class="card" style="margin-top:12px"><h3>Últimos negócios na B3</h3><div class="tab" style="max-height:260px"><table><thead><tr><th>Data</th><th>Hora</th><th>Origem</th><th>Qtd</th><th>PU</th><th>Volume (R$)</th><th>Taxa</th></tr></thead><tbody>
 ${s.negocios.map(n=>`<tr><td>${n.data}</td><td>${n.hora}</td><td>${n.origem}</td><td>${f(n.qtd,0)}</td><td>${f(n.pu,4)}</td><td>${f(n.vol,0)}</td><td>${f(n.taxa,4)}</td></tr>`).join('')}</tbody></table></div></div>`:''}
 <div class="card news" style="margin-top:12px"><h3>Notícias (Bing), Reddit e fatos relevantes (CVM, 30 dias)</h3><ul>
 ${(s.fatos||[]).map(x=>`<li class="r"><a href="${x.Link_Download}" target="_blank">CVM ${x.d} · ${x.Categoria}: ${x.Assunto||''}</a></li>`).join('')}
 ${(s.noticias||[]).map(x=>`<li${x.ruim?' class="r"':''}><a href="${x.link}" target="_blank"><span class="pill">${x.fonte}</span>${x.data} · ${x.titulo}</a></li>`).join('')||'<li class=mu>Nenhuma notícia.</li>'}</ul></div>`;
 $('#det').style.display='block';
 Plotly.newPlot('d1',[{x:(s.serie||[]).map(p=>p[0]),y:(s.serie||[]).map(p=>p[1]),mode:'lines+markers',line:{color:css('--lar'),width:2.2},marker:{size:4},hovertemplate:'%{x}: %{y:.2f}%<extra></extra>'}],
  lay({yaxis:{ticksuffix:'%',gridcolor:css('--ln')}}),cfg);
 Plotly.newPlot('d2',[{x:(s.pu||[]).map(p=>p[0]),y:(s.pu||[]).map(p=>p[1]),mode:'lines+markers',line:{color:css('--azul'),width:2},marker:{size:4}}],lay({}),cfg)}
carrega();
</script></body></html>"""

if __name__ == "__main__":
    import uvicorn
    MODO = sys.argv[1] if len(sys.argv) > 1 else "exemplo"
    threading.Thread(target=laco, daemon=True).start()
    threading.Timer(2, lambda: webbrowser.open(f"http://localhost:{PORTA}")).start()
    print(f"Monitor em http://localhost:{PORTA}  (deixe esta janela aberta; Ctrl+C para fechar)")
    uvicorn.run(app, host="127.0.0.1", port=PORTA, log_level="warning")
else:
    MODO = "exemplo"
