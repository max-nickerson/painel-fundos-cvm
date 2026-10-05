"""
Painel de fundos (dados abertos CVM + ANBIMA + Banco Central) - backend FastAPI.
Rodar local:  uvicorn server:app --port 7860      (abre http://localhost:7860)
Hugging Face Spaces (Docker): ver Dockerfile.
Cada carga roda em segundo plano (a 1a vez de um fundo/periodo baixa arquivos da CVM) e o navegador acompanha o progresso.
"""
import hashlib
import io
import json
import math
import os
import threading
import unicodedata
import uuid
import zipfile
from collections import OrderedDict
from datetime import date

import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import lookthrough_cvm as lt

CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
CINZA = "#898781"
CONTABIL = r"(?i)pagar|receber|obriga|termo|disponibilidade|exigibilidade|swap|confidencial|ajuste"
AQUI = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Painel de fundos CVM")
app.mount("/static", StaticFiles(directory=os.path.join(AQUI, "static")), name="static")

JOBS, RESULTADOS, LOCK = {}, OrderedDict(), threading.Lock()
CAD = {"df": None, "erro": None}


# ------------------------------------------------------------------ cadastro (busca por nome/CNPJ)
def _sem_acento(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()


def carrega_cadastro():
    try:
        r = requests.get("https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip", timeout=300)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        c = pd.read_csv(z.open("registro_classe.csv"), sep=";", encoding="latin1", dtype=str, quoting=3,
                        usecols=["CNPJ_Classe", "Denominacao_Social", "Situacao"])
        c.columns = ["cnpj", "nome", "situacao"]
        a = pd.read_csv("https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv", sep=";", encoding="latin1", dtype=str,
                        quoting=3, usecols=["CNPJ_FUNDO", "DENOM_SOCIAL", "SIT"])
        a.columns = ["cnpj", "nome", "situacao"]
        c = pd.concat([c, a]).dropna(subset=["cnpj", "nome"])
        c["cnpj"] = c.cnpj.map(lt.fmt)
        c["ativo"] = ~c.situacao.fillna("").str.upper().str.contains("CANCEL")
        c = c.sort_values("ativo", ascending=False).drop_duplicates("cnpj")
        c["chave"] = c.nome.map(_sem_acento) + " " + c.cnpj.str.replace(r"\D", "", regex=True)
        CAD["df"] = c.reset_index(drop=True)
    except Exception as e:                                  # sem cadastro a busca por CNPJ continua funcionando
        CAD["erro"] = f"{type(e).__name__}: {e}"




@app.get("/api/busca")
def busca(q: str = ""):
    q = q.strip()
    dig = "".join(ch for ch in q if ch.isdigit())
    c = CAD["df"]
    if c is None:
        return [{"cnpj": lt.fmt(dig), "nome": "(cadastro carregando) " + lt.fmt(dig), "ativo": True}] if len(dig) == 14 else []
    if len(q) < 2:
        return []
    toks = _sem_acento(q).split()
    m = pd.Series(True, index=c.index)
    for t in toks:
        m &= c.chave.str.contains(t, regex=False)
    r = c[m].head(25)
    return [{"cnpj": x.cnpj, "nome": x.nome, "ativo": bool(x.ativo)} for x in r.itertuples()]


@app.get("/api/padrao")
def padrao():
    nomes = dict(zip(CAD["df"].cnpj, CAD["df"].nome)) if CAD["df"] is not None else {}
    return [{"cnpj": lt.cnpj_of(x), "nome": nomes.get(lt.cnpj_of(x), n), "curto": n} for n, x in lt.PEERS.items()]


# ------------------------------------------------------------------ helpers de serializacao
def limpo(o):
    if isinstance(o, dict):
        return {str(k): limpo(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [limpo(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(o) or math.isinf(o)) else round(float(o), 6)
    if isinstance(o, pd.Timestamp):
        return None if pd.isna(o) else o.strftime("%Y-%m-%d")
    if o is None or isinstance(o, (str, bool)):
        return o
    try:
        return None if pd.isna(o) else o
    except (TypeError, ValueError):
        return o


def registros(df, cols=None):
    df = df if cols is None else df[cols]
    return [dict(zip(df.columns, r)) for r in df.itertuples(index=False)]


def wavg(x, col, w="perc_pl"):
    ok = x[col].notna() & x[w].gt(0)
    return float(np.average(x.loc[ok, col], weights=x.loc[ok, w])) if ok.any() else None


def curto(nome):
    n = nome.upper()
    for a, b in [("FUNDO DE INVESTIMENTO FINANCEIRO", "FIF"), ("FUNDO DE INVESTIMENTO EM COTAS DE FUNDOS DE INVESTIMENTO", "FIC FI"),
                 ("FUNDO DE INVESTIMENTO", "FI"), ("MULTIMERCADO", "MM"), ("CRÉDITO PRIVADO", "CP"), ("RENDA FIXA", "RF"),
                 ("RESPONSABILIDADE LIMITADA", "RL"), ("RESP LIMITADA", "RL"), ("LONGO PRAZO", "LP")]:
        n = n.replace(a, b)
    return n[:30].strip()


# ------------------------------------------------------------------ montagem de tudo que o painel mostra
def monta(fundos, desde, log):
    """fundos: lista de (nome curto, cnpj). Devolve um dicionario JSON com todas as abas."""
    workers = max(1, min(4, (os.cpu_count() or 2)))
    meses, dia = lt.prepara(sorted(c for _, c in fundos), desde, workers=workers, log=log)
    nomes = dict(fundos)
    ordem = [n for n, _ in fundos]
    log("Montando look-through e indicadores...")
    df = lt.lookthrough(nomes, meses) if meses else pd.DataFrame()
    d = lt.diario(nomes, dia)
    cdi = lt.cdi_mensal(desde, diario=True)
    cdi_m = (1 + cdi).groupby(cdi.index.strftime("%Y-%m")).prod() - 1
    an_u, an_h = lt.anbima_debentures()
    out = {"meta": {"desde": desde, "fundos": [{"nome": n, "cnpj": c, "cor": CORES[i % 8]} for i, (n, c) in enumerate(fundos)],
                    "gerado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                    "ult_carteira": max(meses) if meses else None,
                    "ult_cota": d.data.max().strftime("%Y-%m-%d") if len(d) else None,
                    "anbima_data": an_u.data.iloc[0].strftime("%Y-%m-%d") if len(an_u) else None,
                    "anbima_dias": int(an_h.data.nunique()) if len(an_h) else 0}}

    cart = df[~df.derivativo] if len(df) else df
    ult_mes = cart.groupby("fundo").mes.max() if len(cart) else pd.Series(dtype=str)
    ult = cart[cart.mes == cart.fundo.map(ult_mes)] if len(cart) else cart
    aberto = lt.mes_aberto(df) if len(df) else pd.Series(dtype=str)
    media = (cart[~cart.categoria.str.contains(CONTABIL)].groupby(["fundo", "mes", "categoria"]).perc_pl.sum()
             .groupby("categoria").mean().sort_values(ascending=False)) if len(cart) else pd.Series(dtype=float)
    top_cat = media.index[:7].tolist()
    out["categorias"] = {c: CORES[i] for i, c in enumerate(top_cat)} | {"Outros": CINZA}
    cat7 = lambda s: s.where(s.isin(top_cat), "Outros")
    rent = lt.rentabilidade(d, cdi_m) if len(d) else pd.DataFrame(columns=["fundo", "mes", "retorno", "cdi", "pct_cdi"])

    # ---- cotas, KPIs
    kp, cotas = [], {}
    for f in ordem:
        x = d[d.fundo == f]
        q = x.set_index("data").VL_QUOTA.dropna()
        if q.empty:
            continue
        fim = q.index[-1]
        ini = q[q.index <= fim - pd.Timedelta(days=365)]
        base = ini.index[-1] if len(ini) else q.index[0]
        r12, c12 = q.iloc[-1] / q[base] - 1, (1 + cdi[(cdi.index > base) & (cdi.index <= fim)]).prod() - 1
        ano = q[q.index < pd.Timestamp(fim.year, 1, 1)]
        u = ult[ult.fundo == f]
        x12 = x[x.data > base]
        kp.append({"fundo": f, "pl_mi": x.VL_PATRIM_LIQ.iloc[-1] / 1e6, "ret12": r12 * 100, "pct_cdi12": r12 / c12 * 100 if c12 else None,
                   "ret_ano": (q.iloc[-1] / ano.iloc[-1] - 1) * 100 if len(ano) else None,
                   "vol": q[q.index > base].pct_change().std() * np.sqrt(252) * 100, "dd": (q / q.cummax() - 1).min() * 100,
                   "capt12_mi": (x12.CAPTC_DIA.sum() - x12.RESG_DIA.sum()) / 1e6, "cotistas": x.NR_COTST.iloc[-1],
                   "ativos": u.chave.nunique() if len(u) else None,
                   "top10_emissores": u.groupby("emissor").perc_pl.sum().nlargest(10).sum() if len(u) else None,
                   "ult_carteira": ult_mes.get(f), "carteira_aberta": aberto.get(f), "ult_cota": fim.strftime("%Y-%m-%d")})
        cotas[f] = {"datas": [t.strftime("%Y-%m-%d") for t in q.index], "acum": ((q / q.iloc[0] - 1) * 100).tolist(),
                    "dd": ((q / q.cummax() - 1) * 100).tolist(), "pl": (x.set_index("data").VL_PATRIM_LIQ / 1e6).reindex(q.index).tolist(),
                    "cotistas": x.set_index("data").NR_COTST.reindex(q.index).tolist()}
    out["kpis"], out["cotas"] = kp, cotas
    c0 = cdi[cdi.index >= d.data.min()] if len(d) else cdi.iloc[:0]
    out["cdi"] = {"datas": [t.strftime("%Y-%m-%d") for t in c0.index], "acum": (((1 + c0).cumprod() - 1) * 100).tolist()}
    cap = d.groupby(["fundo", "mes"]).apply(lambda x: (x.CAPTC_DIA.sum() - x.RESG_DIA.sum()) / 1e6, include_groups=False).rename("capt_mi")
    out["mensal"] = registros(rent.join(cap, on=["fundo", "mes"])[["fundo", "mes", "retorno", "cdi", "pct_cdi", "capt_mi"]]) if len(rent) else []

    # ---- por fundo: alocacao, carteira, credito, movimentos, derivativos, marcacao
    por = {}
    for f in [f for f in ordem if f in set(cart.fundo)] if len(cart) else []:
        g, gd = cart[cart.fundo == f], df[df.fundo == f]
        u = ult[ult.fundo == f]
        ev = g.assign(c=cat7(g.categoria)).pivot_table(index="mes", columns="c", values="perc_pl", aggfunc="sum", fill_value=0)
        p = {"ult_mes": ult_mes.get(f), "mes_aberto": aberto.get(f),
             "alocacao": {"meses": ev.index.tolist(), "series": {c: ev[c].tolist() for c in top_cat + ["Outros"] if c in ev}},
             "emissores": registros(u.groupby("emissor").perc_pl.sum().nlargest(15).reset_index())}
        cp = (u.groupby(["categoria", "ativo", "codigo", "emissor"], dropna=False)
              .agg(perc_pl=("perc_pl", "sum"), veiculo=("veiculo", "first")).reset_index().sort_values("perc_pl", ascending=False))
        p["carteira"] = registros(cp)

        # credito (ultima carteira aberta) + ANBIMA
        ma = aberto.get(f, ult_mes.get(f))
        ua = g[g.mes == ma]
        deb = ua[ua.categoria.eq("Debêntures")]
        cols = ["codigo", "indice", "tipo", "taxa_ind", "duration_anos", "pct_par", "venc"]
        deb = deb.merge(an_u[cols], on="codigo", how="left") if len(an_u) else deb.assign(**{c: np.nan for c in cols[1:]})
        com = deb[deb.taxa_ind.notna()]
        hist = {}
        if len(an_h) and an_h.data.nunique() > 1 and len(com):
            evh = deb[["codigo", "perc_pl"]].merge(an_h[["data", "codigo", "tipo", "taxa_ind", "duration_anos"]], on="codigo")
            s1 = evh[evh.tipo == "DI +"].groupby("data").apply(lambda x: wavg(x, "taxa_ind"), include_groups=False)
            s2 = evh.groupby("data").apply(lambda x: wavg(x, "duration_anos"), include_groups=False)
            hist = {"datas": [t.strftime("%Y-%m-%d") for t in s2.index], "spread_di": s1.reindex(s2.index).tolist(), "duration": s2.tolist()}
        o = ua[~ua.categoria.str.contains(CONTABIL)].copy()
        venc = pd.to_datetime(o.vencimento, errors="coerce")
        o["prazo"] = (venc - (pd.to_datetime(o.mes) + pd.offsets.MonthEnd(0))).dt.days / 365.25
        faixa = pd.cut(o.prazo, [-1, 1, 2, 3, 5, 100], labels=["até 1a", "1-2a", "2-3a", "3-5a", "5a+"]).astype(str).replace("nan", "s/ venc.")
        resumo = o.groupby("categoria").apply(lambda x: pd.Series({
            "perc_pl": x.perc_pl.sum(), "perc_com_taxa": x[x.pct_indexador.notna() | x.cupom.notna() | x.taxa_pre.notna()].perc_pl.sum(),
            "pct_indexador": wavg(x, "pct_indexador"), "cupom": wavg(x, "cupom"), "taxa_pre": wavg(x, "taxa_pre"),
            "prazo": wavg(x, "prazo")}), include_groups=False).reset_index().sort_values("perc_pl", ascending=False)
        p["credito"] = {
            "mes": ma, "deb_pl": deb.perc_pl.sum(), "cobertura": com.perc_pl.sum() / deb.perc_pl.sum() * 100 if deb.perc_pl.sum() else None,
            "spread_di": wavg(com[com.tipo == "DI +"], "taxa_ind"), "pl_di": com[com.tipo == "DI +"].perc_pl.sum(),
            "taxa_ipca": wavg(com[com.tipo == "IPCA +"], "taxa_ind"), "pl_ipca": com[com.tipo == "IPCA +"].perc_pl.sum(),
            "duration": wavg(com, "duration_anos"),
            "por_tipo": registros(deb.assign(t=deb.tipo.fillna("sem taxa ANBIMA")).groupby("t").perc_pl.sum().reset_index()),
            "debs": registros(deb.sort_values("perc_pl", ascending=False),
                              ["ativo", "codigo", "perc_pl", "indice", "tipo", "taxa_ind", "duration_anos", "pct_par", "venc", "veiculo"]),
            "hist": hist,
            "indexador": registros(o.groupby(o.indexador.fillna("não informado na CDA")).perc_pl.sum().reset_index().rename(columns={"indexador": "k"})),
            "prazo": registros(o.groupby(faixa).perc_pl.sum().reindex(["até 1a", "1-2a", "2-3a", "3-5a", "5a+", "s/ venc."]).fillna(0)
                               .rename_axis("k").reset_index()),
            "rating": registros(o.groupby(o.rating.fillna("sem rating")).perc_pl.sum().rename_axis("k").reset_index()),
            "resumo": registros(resumo)}

        # movimentacoes
        giro = g.groupby("mes").agg(c=("compra_pct", "sum"), v=("venda_pct", "sum"))
        ms = sorted(g.mes.unique())
        mv = {}
        for i, m in enumerate(ms):
            x = g[g.mes == m].groupby(["ativo", "categoria"]).agg(compra=("compra_pct", "sum"), venda=("venda_pct", "sum")).reset_index()
            e = {"compras": registros(x.nlargest(15, "compra")[["ativo", "categoria", "compra"]]),
                 "vendas": registros(x.nlargest(15, "venda")[["ativo", "categoria", "venda"]])}
            if i:
                a, b = set(g[g.mes == ms[i - 1]].chave), set(g[g.mes == m].chave)
                e |= {"novos": len(b - a), "pct_novos": g[(g.mes == m) & g.chave.isin(b - a)].perc_pl.sum(),
                      "zerados": len(a - b), "pct_zerados": g[(g.mes == ms[i - 1]) & g.chave.isin(a - b)].perc_pl.sum()}
            mv[m] = e
        p["movimentos"] = {"meses": giro.index.tolist(), "compras": giro.c.tolist(), "vendas": giro.v.tolist(), "por_mes": mv}

        # derivativos e moeda
        dv = gd[gd.derivativo]
        t = dv.pivot_table(index="mes", columns="tipo_ativo", values="perc_pl", aggfunc="sum", fill_value=0) if len(dv) else pd.DataFrame()
        fx = pd.DataFrame({"exterior": gd[gd.categoria.eq("Investimento no Exterior")].groupby("mes").perc_pl.sum(),
                           "dolar": dv[dv.tipo_ativo.fillna("").str.contains("(?i)dol|dólar")].groupby("mes").perc_pl.sum()}).fillna(0)
        p["derivativos"] = {"meses": t.index.tolist(), "series": {c: t[c].tolist() for c in t.columns},
                            "atual": registros(dv[dv.mes == dv.mes.max()].groupby(["categoria", "tipo_ativo", "ativo", "veiculo"])
                                               .perc_pl.sum().reset_index().sort_values("perc_pl")) if len(dv) else [],
                            "moeda": {"meses": fx.index.tolist(), "exterior": fx.exterior.tolist(), "dolar": fx.dolar.tolist()}}

        # marcacao estimada
        k = lt.contribuicao(g)
        if len(k):
            cc = k.assign(c=cat7(k.categoria)).pivot_table(index="mes", columns="c", values="resultado_pct", aggfunc="sum", fill_value=0)
            rr = rent[rent.fundo == f].set_index("mes").retorno.reindex(cc.index) * 100
            pm = {}
            for m in cc.index:
                km = k[k.mes == m].groupby(["ativo", "categoria"]).resultado_pct.sum().reset_index()
                pm[m] = {"altas": registros(km.nlargest(12, "resultado_pct")), "quedas": registros(km.nsmallest(12, "resultado_pct"))}
            tot = k.groupby(["ativo", "categoria"]).resultado_pct.sum().reset_index()
            p["marcacao"] = {"meses": cc.index.tolist(), "series": {c: cc[c].tolist() for c in top_cat + ["Outros"] if c in cc},
                             "real": rr.tolist(), "por_mes": pm, "periodo": {"altas": registros(tot.nlargest(15, "resultado_pct")),
                                                                            "quedas": registros(tot.nsmallest(15, "resultado_pct"))}}
        por[f] = p
    out["por_fundo"] = por

    # ---- comparacao
    if len(ult):
        pv = ult.pivot_table(index="categoria", columns="fundo", values="perc_pl", aggfunc="sum", fill_value=0)
        pv = pv.reindex(columns=[f for f in ordem if f in pv.columns])
        pv = pv.loc[pv.abs().max(axis=1).sort_values(ascending=False).index]
        e = ult.groupby(["fundo", "emissor"]).perc_pl.sum()
        comum = e.groupby(level=1).filter(lambda s: len(s) > 1).unstack(0).fillna(0)
        comum = comum.loc[comum.sum(axis=1).sort_values(ascending=False).index].head(30) if len(comum) else comum
        out["comparacao"] = {"alocacao": {"fundos": pv.columns.tolist(), "linhas": [[i] + r.tolist() for i, r in pv.iterrows()]},
                             "emissores": {"fundos": comum.columns.tolist(), "linhas": [[i] + r.tolist() for i, r in comum.iterrows()]}}
    else:
        out["comparacao"] = {"alocacao": {"fundos": [], "linhas": []}, "emissores": {"fundos": [], "linhas": []}}
    RESULTADOS_DF[_chave(fundos, desde)] = (df, d)
    while len(RESULTADOS_DF) > 6:
        RESULTADOS_DF.pop(next(iter(RESULTADOS_DF)))
    log("Pronto.")
    return limpo(out)


RESULTADOS_DF = {}


def _chave(fundos, desde):
    return hashlib.md5((desde + "|" + "|".join(sorted(c for _, c in fundos))).encode()).hexdigest()


def _roda(job, fundos, desde):
    try:
        res = monta(fundos, desde, JOBS[job]["log"].append)
        with LOCK:
            RESULTADOS[_chave(fundos, desde)] = res
            while len(RESULTADOS) > 12:
                velho = next(k for k in RESULTADOS if k != PRE.get("chave"))
                RESULTADOS.pop(velho)
        JOBS[job]["status"] = "ok"
    except Exception as e:
        JOBS[job] |= {"status": "erro", "erro": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------------ pre-carga: todos os peers antes de abrir o painel
DESDE_PAINEL = os.environ.get("PAINEL_DESDE", lt.DESDE)
PRE = {"status": "parado", "log": [], "chave": None, "erro": None}


def precarrega(log=None):
    """Baixa/processa todos os peers (PEERS, desde DESDE_PAINEL). Resultado do dia fica salvo em disco: reinicio rapido."""
    escreve = log or PRE["log"].append
    PRE["status"] = "rodando"
    try:
        fundos = [(n, lt.cnpj_of(x)) for n, x in lt.PEERS.items()]
        k = _chave(fundos, DESDE_PAINEL)
        f = lt.CACHE / f"painel_{k}_{date.today()}.json"
        if f.exists():
            escreve("Usando o painel já processado hoje (cache).")
            res = json.loads(f.read_text(encoding="utf-8"))
        else:
            escreve(f"Baixando e processando {len(fundos)} fundos desde {DESDE_PAINEL} (1a vez no dia pode levar minutos)...")
            res = monta(fundos, DESDE_PAINEL, escreve)
            for velho in lt.CACHE.glob(f"painel_{k}_*.json"):
                velho.unlink(missing_ok=True)
            f.write_text(json.dumps(res), encoding="utf-8")
        with LOCK:
            RESULTADOS[k] = res
        PRE.update(status="ok", chave=k)
    except Exception as e:
        PRE.update(status="erro", erro=f"{type(e).__name__}: {e}")
        escreve("ERRO: " + PRE["erro"])


def _inicio():                              # servidor (pasta/Docker): cadastro e pre-carga em segundo plano
    if not CAD.get("iniciado"):
        CAD["iniciado"] = True
        threading.Thread(target=carrega_cadastro, daemon=True).start()
    if PRE["status"] == "parado":
        threading.Thread(target=precarrega, daemon=True).start()


app.add_event_handler("startup", _inicio)


@app.get("/api/inicial")
def inicial():
    return {"status": PRE["status"], "chave": PRE["chave"], "log": PRE["log"][-8:], "erro": PRE["erro"]}


@app.post("/api/carregar")
def carregar(body: dict):
    fundos = [(curto(x.get("curto") or x["nome"]), lt.fmt(x["cnpj"])) for x in body.get("fundos", [])][:8]
    if not fundos:
        raise HTTPException(400, "escolha ao menos um fundo")
    vistos, unicos = set(), []
    for n, c in fundos:                              # nomes curtos repetidos ganham sufixo
        while n in vistos:
            n += "*"
        vistos.add(n)
        unicos.append((n, c))
    desde = body.get("desde") or "2024-01"
    k = _chave(unicos, desde)
    if k in RESULTADOS:
        return {"job": None, "chave": k, "status": "ok"}
    job = uuid.uuid4().hex[:10]
    JOBS[job] = {"status": "rodando", "log": [], "chave": k}
    threading.Thread(target=_roda, args=(job, unicos, desde), daemon=True).start()
    return {"job": job, "chave": k, "status": "rodando"}


@app.get("/api/status/{job}")
def status(job: str):
    j = JOBS.get(job) or HTTPException(404)
    if isinstance(j, HTTPException):
        raise j
    return {"status": j["status"], "log": j["log"][-6:], "erro": j.get("erro"), "chave": j["chave"]}


@app.get("/api/resultado/{chave}")
def resultado(chave: str):
    if chave not in RESULTADOS:
        raise HTTPException(404, "resultado expirou; carregue de novo")
    return JSONResponse(RESULTADOS[chave])


@app.get("/api/csv/{chave}/{tipo}")
def csv(chave: str, tipo: str):
    if chave not in RESULTADOS_DF:
        if chave not in RESULTADOS:
            raise HTTPException(404)
        m = RESULTADOS[chave]["meta"]
        fundos = [(f["nome"], f["cnpj"]) for f in m["fundos"]]
        meses, dia = lt.prepara(sorted(c for _, c in fundos), m["desde"], workers=1, log=lambda *_: None)
        RESULTADOS_DF[chave] = (lt.lookthrough(dict(fundos), meses), lt.diario(dict(fundos), dia))
    df, d = RESULTADOS_DF[chave]
    x = df.drop(columns=["chave", "fator"], errors="ignore") if tipo == "carteira" else d
    return Response(x.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{tipo}.csv"'})


@app.get("/")
def index():
    return FileResponse(os.path.join(AQUI, "static", "index.html"))
