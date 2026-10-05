"""
Painel de fundos (CVM + ANBIMA + Tesouro Direto + Banco Central + IBGE) - backend FastAPI.
Rodar local:  uvicorn server:app --port 7860      (abre http://localhost:7860)
Na partida baixa/processa TODOS os fundos (NOSSOS_FUNDOS + PEERS em lookthrough_cvm.py) e salva o resultado do dia
em dados_painel/painel/<data>/. O navegador mostra o progresso e abre quando termina.
"""
import json
import math
import os
import re
import threading
from datetime import date

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import lookthrough_cvm as lt

AQUI = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Painel de fundos")
app.mount("/static", StaticFiles(directory=os.path.join(AQUI, "static")), name="static")

CAT_CORES = ["#2a78d6", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7", "#008300", "#e34948", "#7ba7d9"]
NOSSAS_CORES = ["#eb6834", "#c24f1d", "#f29a6b", "#a8401a", "#f5b38d"]
GENERICO = (r"(?i)\b(FUNDO DE INVESTIMENTO|FUNDO|EM DIREITOS CREDIT[OÓ]RIOS|DE INVESTIMENTO|FIDC|FIC|FI|COTAS|MULTIMERCADO|"
            r"RENDA FIXA|CR[EÉ]DITO PRIVADO|RESPONSABILIDADE LIMITADA|RESP LTDA|N[AÃ]O PADRONIZADO|NP|LONGO PRAZO|LP)\b")
METODO = 5                                     # suba quando mudar o calculo -> refaz o cache do dia
CAIXA = ("Caixa e provisões", "Operações Compromissadas")
CREDITO = ("Debêntures", "Títulos de Crédito Privado", "Títulos ligados ao agronegócio",
           "Outros valores mobiliários registrados na CVM objeto de oferta pública", "Investimento no Exterior", "Outras aplicações")
MESES_COD = "FGHJKMNQUVXZ"
PRE = {"status": "parado", "log": [], "erro": None, "pasta": None}


# ------------------------------------------------------------------ utilidades
def limpo(o):
    if isinstance(o, dict):
        return {str(k): limpo(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [limpo(v) for v in o]
    if isinstance(o, np.integer):
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


def wavg(v, w):
    v, w = np.asarray(v, float), np.asarray(w, float)
    ok = ~np.isnan(v) & (w > 0)
    return float(np.average(v[ok], weights=w[ok])) if ok.any() else None


def fim_mes(m):
    return pd.Timestamp(m) + pd.offsets.MonthEnd(0)


def contrato(texto):
    """Tipo, vencimento (ano, mes) de um futuro a partir do codigo/descricao da CDA (ex.: DI1FUTF29, FUT DAP/Q30)."""
    t = lt._sem_acento(texto)
    tipo = ("DAP" if re.search(r"DAP|CUPOM DE IPCA|DI X IPCA", t) else "DI1" if re.search(r"DI1|DI DE 1 DIA", t)
            else "WDO" if "WDO" in t else "DOL" if re.search(r"DOL|DOLAR", t) else "DDI" if re.search(r"DDI|FRC|CUPOM CAMBIAL", t)
            else "IND" if re.search(r"\bIND|WIN|IBOV", t) else "OUTRO")
    m = re.search(r"(?:DI1|DAP|DOL|WDO|DDI|FRC|IND|WIN)\s*(?:FUT)?\s*/?\s*([FGHJKMNQUVXZ])(\d{2})\b", t)
    return tipo, ((2000 + int(m.group(2)), MESES_COD.index(m.group(1)) + 1) if m else None)


# ------------------------------------------------------------------ calculo por fundo
class Contexto:
    """Dados de mercado compartilhados por todos os fundos."""

    def __init__(self, log):
        log("Baixando curvas (Tesouro Direto), IPCA (IBGE), PTAX e CDI (Banco Central) e marcação ANBIMA...")
        self.curvas = lt.tesouro()
        self.ipca = lt.ipca_indice()
        self.ptax = lt.sgs(1, lt.DESDE)
        self.cdi_d = lt.cdi_mensal(lt.DESDE, diario=True)
        self.cdi_m = (1 + self.cdi_d).groupby(self.cdi_d.index.strftime("%Y-%m")).prod() - 1
        self.an_u, self.an_h = lt.anbima_debentures()
        self.an_dias = sorted(self.an_h.data.unique()) if len(self.an_h) else []

    def cdi_aa(self, m):
        x = self.cdi_d[self.cdi_d.index <= fim_mes(m)]
        return float(((1 + x.iloc[-1]) ** 252 - 1) * 100) if len(x) else np.nan

    def ptax_em(self, m):
        x = self.ptax[self.ptax.index <= fim_mes(m)]
        return float(x.iloc[-1]) if len(x) else np.nan

    def anbima_mes(self, m, recentes):
        """Marcacao ANBIMA para a carteira do mes: o dia guardado mais proximo do fim do mes (ate 10 dias);
        nos meses mais recentes, o ultimo dia disponivel."""
        if not self.an_dias:
            return None, None
        alvo = fim_mes(m)
        perto = [d for d in self.an_dias if abs((pd.Timestamp(d) - alvo).days) <= 10]
        d = min(perto, key=lambda d: abs((pd.Timestamp(d) - alvo).days)) if perto else (self.an_dias[-1] if m in recentes else None)
        return (d, self.an_h[self.an_h.data == d].drop_duplicates("codigo").set_index("codigo")) if d is not None else (None, None)


def enriquece(g, m, ctx, recentes):
    """Spread sobre o CDI (% a.a., equivalente) e duration (anos) de cada linha da carteira do mes."""
    g = g.copy()
    anos = ((pd.to_datetime(g.vencimento, errors="coerce") - fim_mes(m)).dt.days / 365.25).clip(lower=0)
    cdi = ctx.cdi_aa(m)
    sp, du = pd.Series(np.nan, index=g.index), pd.Series(np.nan, index=g.index)
    idx = g.indexador.fillna("")
    cup = g.cupom.where(g.cupom.fillna(0) != 0)
    pct_i = g.pct_indexador
    # informado na CDA (depositos bancarios, credito privado)
    di = idx.str.contains("DI de um dia|Selic")
    sp[di] = cup[di].fillna((pct_i[di] - 100) / 100 * cdi)
    du[di] = anos[di]
    ip = idx.str.contains("IPCA")
    sp[ip] = cup[ip] - lt.curva(ctx.curvas, "IPCA", fim_mes(m), anos[ip].fillna(3).values)
    du[ip] = anos[ip]
    pr = idx.str.contains("prefixada")
    sp[pr] = g.taxa_pre[pr].fillna(cup[pr]) - lt.curva(ctx.curvas, "PRE", fim_mes(m), anos[pr].fillna(1).values)
    du[pr] = anos[pr]
    # titulos publicos e caixa
    tp = g.categoria.eq("Títulos Públicos")
    lft = tp & g.ativo.str.contains("FINANCEIRAS DO TESOURO|LFT", na=False)
    sp[tp], du[tp] = 0.0, anos[tp]
    du[lft] = 0.0
    cx = g.categoria.isin(CAIXA)
    sp[cx], du[cx] = 0.0, 0.0
    # debentures: marcacao ANBIMA
    dia, an = ctx.anbima_mes(m, recentes)
    deb = g.categoria.eq("Debêntures") & g.codigo.notna()
    if an is not None and deb.any():
        a = an.reindex(g.codigo[deb])
        tx, tipo, dur = a.taxa_ind.values, a.tipo.values, a.duration_anos.values
        s = np.where(tipo == "DI +", tx, np.where(tipo == "% do DI", (tx - 100) / 100 * cdi, np.nan))
        real = np.isin(tipo, ["IPCA +", "IGP-M +"])
        s = np.where(real, tx - lt.curva(ctx.curvas, "IPCA", pd.Timestamp(dia), np.nan_to_num(dur, nan=3)), s)
        pre = tipo == "Outros"
        s = np.where(pre, tx - lt.curva(ctx.curvas, "PRE", pd.Timestamp(dia), np.nan_to_num(dur, nan=2)), s)
        sp[deb], du[deb] = s, dur
    g["spread"], g["duration"] = sp, du
    tipo_an = g.codigo.map(ctx.an_u.drop_duplicates("codigo").set_index("codigo").tipo) if len(ctx.an_u) else pd.Series(np.nan, index=g.index)
    g["ipca"] = tipo_an.isin(["IPCA +", "IGP-M +"]) | ip | g.ativo.str.contains("SERIE B|NTN-B", na=False)
    g["pre"] = (tipo_an.eq("Outros") & g.categoria.eq("Debêntures")) | pr | (tp & g.ativo.str.contains(r"LETRAS DO TESOURO NACIONAL|SERIE F|LTN|NTN-F", na=False) & ~lft)
    g["usd"] = g.categoria.eq("Investimento no Exterior") | idx.str.contains("Dólar")
    return g, dia


def derivativos_mes(gd, m, ctx, dur_ipca, dur_pre):
    """Contratos futuros do mes: tipo, lado, contratos, prazo e nocional estimado (R$)."""
    out = []
    for r in gd.itertuples():
        tipo, venc = contrato(f"{r.codigo or ''} {r.ativo or ''} {r.tipo_ativo or ''}")
        if "mercado futuro" not in str(r.categoria).lower():   # termo/opcao/swap: sem P&L de futuro
            tipo, venc = "OUTRO", None
        lado = -1 if "vendida" in str(r.categoria).lower() else 1
        n = abs(r.quantidade) if pd.notna(r.quantidade) else np.nan
        if venc:
            anos = max((pd.Timestamp(venc[0], venc[1], 15 if tipo == "DAP" else 1) - fim_mes(m)).days / 365.25, 1 / 252)
        else:
            anos = dur_ipca if tipo == "DAP" else dur_pre if tipo == "DI1" else 1.0
        out.append(dict(i=r.Index, tipo=tipo, lado=lado, n=n, anos=anos, fator=r.fator, categoria=r.categoria,
                        ativo=r.ativo, perc_cda=r.perc_pl))
    return out


def valor_ponto(tipo, m, ctx):
    if tipo == "DI1":
        return 1.0
    if tipo == "DAP":
        x = ctx.ipca[ctx.ipca.index <= m]
        return 0.00025 * float(x.iloc[-1]) if len(x) else np.nan
    return np.nan


def pu(tipo, m, anos, ctx):
    t = "PRE" if tipo == "DI1" else "IPCA"
    y = float(lt.curva(ctx.curvas, t, fim_mes(m), np.array([anos]))[0])
    return 1e5 / (1 + y / 100) ** anos


def nocional(c, m, ctx, pl_fundo):
    if c["tipo"] in ("DI1", "DAP") and pd.notna(c["n"]):
        return c["lado"] * c["n"] * pu(c["tipo"], m, c["anos"], ctx) * valor_ponto(c["tipo"], m, ctx)
    if c["tipo"] in ("DOL", "WDO") and pd.notna(c["n"]):
        return c["lado"] * c["n"] * (50000 if c["tipo"] == "DOL" else 10000) * ctx.ptax_em(m)
    return c["perc_cda"] / 100 * pl_fundo if pd.notna(c["perc_cda"]) else np.nan


def pnl_futuro(c, p, m, ctx):
    """P&L estimado (R$) do contrato entre o fim do mes p e o fim do mes m, com a posicao de p."""
    if pd.isna(c["n"]):
        return 0.0
    cdi = float(ctx.cdi_m.get(m, 0.0))
    if c["tipo"] in ("DI1", "DAP"):
        a1 = max(c["anos"] - (fim_mes(m) - fim_mes(p)).days / 365.25, 1 / 252)
        pu0, pu1 = pu(c["tipo"], p, c["anos"], ctx), pu(c["tipo"], m, a1, ctx)
        if c["tipo"] == "DI1":
            return c["lado"] * c["n"] * (pu1 - pu0 * (1 + cdi))
        i0, i1 = ctx.ipca[ctx.ipca.index <= p], ctx.ipca[ctx.ipca.index <= m]
        inf = float(i1.iloc[-1] / i0.iloc[-1] - 1) if len(i0) and len(i1) else 0.0
        return c["lado"] * c["n"] * valor_ponto("DAP", m, ctx) * (pu1 - pu0 * (1 + cdi) / (1 + inf))
    if c["tipo"] in ("DOL", "WDO"):
        return c["lado"] * c["n"] * (50000 if c["tipo"] == "DOL" else 10000) * (ctx.ptax_em(m) - ctx.ptax_em(p))
    return 0.0


def detalhe(nome, cnpj, df, ctx, pl, rent):
    """Tudo que as abas Carteira e Retorno mostram para um fundo."""
    df = df.copy()
    if ctx.an_h is not None and len(ctx.an_h):         # debenture sem emissor na CDA: nome do emissor pela ANBIMA
        df["emissor"] = df.emissor.fillna(df.codigo.map(ctx.an_h.drop_duplicates("codigo", keep="last").set_index("codigo").nome))
    emis = df[["emissor", "categoria"]].drop_duplicates()
    gmap = {(e, c): lt.grupo(e, c) for e, c in zip(emis.emissor, emis.categoria)}
    df["grupo"] = [gmap[(e, c)] for e, c in zip(df.emissor, df.categoria)]
    curto = df.ativo.str.replace(GENERICO, " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip().str.slice(0, 40)
    df["grupo"] = df.grupo.fillna(curto)
    contabil = df.categoria.isin(["Disponibilidades", "Valores a receber", "Valores a pagar", lt.AJUSTE]) | (
        df.categoria.str.contains(lt.PASSIVO, na=False) & ~df.derivativo)
    df["categoria"] = df.categoria.mask(contabil, "Caixa e provisões")   # linhas contabeis numa so categoria
    meses = sorted(df.mes.unique())
    recentes = set(meses[-4:])
    pl_f = {m: float(pl.get((m, cnpj), np.nan)) for m in meses}
    cart_meses, ricos = [], {}
    for m in meses:
        g = df[df.mes == m]
        nd, gd = g[~g.derivativo], g[g.derivativo]
        e, dia = enriquece(nd, m, ctx, recentes)
        ricos[m] = (e, gd)
        e["fin"] = e.perc_pl / 100 * pl_f[m] / 1e6
        cats = []
        for c, x in e.groupby("categoria"):
            com = x.spread.notna() & x.perc_pl.gt(0)
            cats.append({"categoria": c, "perc": x.perc_pl.sum(), "fin": x.fin.sum(), "spread": wavg(x.spread, x.perc_pl),
                         "duration": wavg(x.duration, x.perc_pl), "cobertura": x.perc_pl[com].sum() / x.perc_pl[x.perc_pl > 0].sum() * 100
                         if x.perc_pl.gt(0).any() else None})
        cats.sort(key=lambda r: -r["perc"])
        total = {"categoria": "Total", "perc": e.perc_pl.sum(), "fin": e.fin.sum(), "spread": wavg(e.spread, e.perc_pl),
                 "duration": wavg(e.duration, e.perc_pl)}
        ip = e[e.ipca & e.perc_pl.gt(0)]
        dur_ipca = wavg(ip.duration, ip.perc_pl) or 3.0
        pr = e[e.pre & e.perc_pl.gt(0)]
        dur_pre = wavg(pr.duration, pr.perc_pl) or 1.0
        der = []
        for c in derivativos_mes(gd, m, ctx, dur_ipca, dur_pre):
            v = nocional(c, m, ctx, pl_f[m])
            der.append({"contrato": c["tipo"] if c["tipo"] != "OUTRO" else (c["ativo"] or c["categoria"])[:40],
                        "lado": "comprado" if c["lado"] > 0 else "vendido", "contratos": c["n"], "fin": v / 1e6 if pd.notna(v) else None,
                        "prazo": c["anos"]})
        dd = pd.DataFrame(der)
        if len(dd):
            dd = dd.groupby(["contrato", "lado"], dropna=False).agg(contratos=("contratos", "sum"), fin=("fin", "sum"),
                                                                     prazo=("prazo", "mean")).reset_index()
        x = e[(e.perc_pl > 0) & ~e.categoria.isin(CAIXA + ("Valores a receber", "Valores a pagar", lt.AJUSTE))]
        x = x.assign(sw=(x.spread * x.perc_pl).fillna(0), sp=x.perc_pl.where(x.spread.notna(), 0),
                     dw=(x.duration * x.perc_pl).fillna(0), dp=x.perc_pl.where(x.duration.notna(), 0))
        top = (x.groupby(["ativo", "codigo"], dropna=False)
               .agg(grupo=("grupo", "first"), categoria=("categoria", "first"), perc=("perc_pl", "sum"), sw=("sw", "sum"),
                    sp=("sp", "sum"), dw=("dw", "sum"), dp=("dp", "sum")).reset_index().nlargest(10, "perc"))
        top["spread"] = (top.sw / top.sp).where(top.sp > 0)
        top["duration"] = (top.dw / top.dp).where(top.dp > 0)
        top = top.drop(columns=["sw", "sp", "dw", "dp"])
        gr = x.groupby("grupo").perc_pl.sum().nlargest(10).reset_index()
        cart_meses.append({"mes": m, "pl_mm": pl_f[m] / 1e6, "anbima": dia, "conf": e[e.confidencial].perc_pl.sum(),
                           "cats": cats, "total": total, "deriv": dd.to_dict("records") if len(dd) else [],
                           "top": top.to_dict("records"), "grupos": gr.rename(columns={"perc_pl": "perc"}).to_dict("records")})

    # ---- atribuicao mensal (retorno por categoria, hedges alocados nos ativos protegidos)
    real = rent[rent.fundo == nome].set_index("mes").retorno
    k = lt.contribuicao(df)
    if len(k):                                   # variacao do preco unitario de cada posicao mantida (v/qt)
        k = k[(k.qt > 0) & (k.qt_ant > 0) & (k.v_ant > 0)]
        k = k.assign(rp=(k.v / k.qt) / (k.v_ant / k.qt_ant) - 1)
        preco = k.groupby(["mes", "chave"]).rp.first()
    else:
        preco = pd.Series(dtype=float)
    atr_meses, cats_atr, ativos, contrib = [], {}, {}, []
    id_ativo = lambda a, c, gr: ativos.setdefault((a, c), {"i": len(ativos), "ativo": a, "categoria": c, "grupo": gr})["i"]
    for j in range(1, len(meses)):
        p, m = meses[j - 1], meses[j]
        if m not in real.index or pd.isna(real.get(m)):
            continue
        e0, gd0 = ricos[p]
        w = e0[~e0.confidencial].copy()
        w = w[w.perc_pl.abs() > 0]
        cdi_m = float(ctx.cdi_m.get(m, 0.0))
        # 1) retorno de cada ativo: esperado = CDI + spread proprio; usa a variacao real de preco quando ela e critica
        #    (queda maior que 1,5 p.p. abaixo do esperado = pagamento de cupom/amortizacao -> fica o esperado)
        esperado = (1 + cdi_m) * (1 + w.spread.fillna(0).clip(-5, 30) / 100) ** (1 / 12) - 1
        rp = w.chave.map(preco.loc[m]) if len(preco) and m in preco.index.get_level_values(0) else pd.Series(np.nan, index=w.index)
        r = rp.where(rp.notna() & (rp >= esperado - 0.015) & (rp <= esperado + 0.03), esperado)
        cx = w.categoria.isin(CAIXA)
        r[cx] = cdi_m
        ativo_c = w.perc_pl * r
        # 3) derivativos -> ativos protegidos
        ip = w[w.ipca & w.perc_pl.gt(0)]
        dur_ipca = wavg(ip.duration, ip.perc_pl) or 3.0
        pr = w[w.pre & w.perc_pl.gt(0)]
        dur_pre = wavg(pr.duration, pr.perc_pl) or 1.0
        hedge = 0.0
        for c in derivativos_mes(gd0, p, ctx, dur_ipca, dur_pre):
            v = pnl_futuro(c, p, m, ctx) * c["fator"] / 100 * 100 if pd.notna(c["fator"]) else 0.0  # % do PL do fundo
            if not v or np.isnan(v):
                continue
            alvo = (w.ipca if c["tipo"] == "DAP" else w.pre if c["tipo"] == "DI1" and w.pre.any() else w.ipca
                    if c["tipo"] == "DI1" else w.usd if c["tipo"] in ("DOL", "WDO", "DDI") else pd.Series(False, index=w.index))
            alvo = alvo & w.perc_pl.gt(0)
            if not alvo.any():
                alvo = w.perc_pl.gt(0) & ~cx
            ativo_c[alvo] += v * w.perc_pl[alvo] / w.perc_pl[alvo].sum()
            hedge += v
        # 4) resto (taxas, negociacao, marcacao fora do esperado) -> todas as categorias que nao sao caixa, pelo peso
        resid = float(real[m]) * 100 - ativo_c.sum()
        cr = w.perc_pl.gt(0) & ~cx
        ativo_c[cr] += resid * w.perc_pl[cr] / w.perc_pl[cr].sum()
        atr_meses.append({"mes": m, "real": float(real[m]) * 100, "cdi": float(ctx.cdi_m.get(m, np.nan)) * 100,
                          "hedge": hedge, "resid": resid})
        jm = len(atr_meses) - 1
        por_cat = ativo_c.groupby(w.categoria).sum()
        peso = w.groupby("categoria").perc_pl.sum()
        for c in set(por_cat.index) | set(cats_atr):
            cats_atr.setdefault(c, {"contrib": [None] * jm, "peso": [None] * jm})
            cats_atr[c]["contrib"].append(float(por_cat.get(c, 0.0)))
            cats_atr[c]["peso"].append(float(peso.get(c, 0.0)))
        pa = ativo_c[~cx].groupby([w.ativo[~cx], w.categoria[~cx], w.grupo[~cx]]).sum()   # caixa/compromissada fora do ranking
        for (a, c, gr), v in pa.items():
            if abs(v) > 1e-5:
                contrib.append([id_ativo(a, c, gr), jm, float(v)])
    for c in cats_atr.values():
        for key in ("contrib", "peso"):
            c[key] += [None] * (len(atr_meses) - len(c[key]))
    return limpo({"nome": nome, "cnpj": cnpj, "carteira": cart_meses,
                  "retorno": {"meses": atr_meses, "categorias": cats_atr,
                              "ativos": sorted(ativos.values(), key=lambda x: x["i"]), "contrib": contrib}})


# ------------------------------------------------------------------ pre-carga de todos os fundos
def pasta_dia():
    return lt.CACHE / "painel" / str(date.today())


def precarrega(log=None):
    escreve = log or PRE["log"].append
    PRE["status"] = "rodando"
    try:
        fundos = [(n, lt.cnpj_of(x), True) for n, x in lt.NOSSOS_FUNDOS.items()] + \
                 [(n, lt.cnpj_of(x), False) for n, x in lt.PEERS.items()]
        dest = pasta_dia()
        chave = "|".join(sorted(c for _, c, _ in fundos)) + "|" + lt.DESDE + f"|m{METODO}"
        if (dest / "visao.json").exists() and json.loads((dest / "visao.json").read_text(encoding="utf-8")).get("chave") == chave:
            escreve("Usando o painel já processado hoje.")
            PRE.update(status="ok", pasta=str(dest))
            return
        dest.mkdir(parents=True, exist_ok=True)
        for velho in (lt.CACHE / "painel").glob("*"):
            if velho != dest and velho.is_dir():
                for f in velho.glob("*"):
                    f.unlink(missing_ok=True)
                velho.rmdir()
        escreve(f"Baixando/atualizando dados da CVM de {len(fundos)} fundos desde {lt.DESDE}...")
        workers = max(1, min(4, (os.cpu_count() or 2)))
        meses, dia = lt.prepara(sorted(c for _, c, _ in fundos), lt.DESDE, workers=workers, log=escreve)
        ctx = Contexto(escreve)
        escreve("Carregando carteiras...")
        carga = lt.carrega_pos(meses)
        pl = carga[1]
        nomes = {n: c for n, c, _ in fundos}
        d = lt.diario(nomes, dia)
        rent = lt.rentabilidade(d, ctx.cdi_m) if len(d) else pd.DataFrame(columns=["fundo", "mes", "retorno"])
        for i, (n, c, _) in enumerate(fundos, 1):
            escreve(f"[{i}/{len(fundos)}] {n}: look-through, carteira e atribuição...")
            df = lt.lookthrough({n: c}, meses, carga)
            fid = re.sub(r"\D", "", c)
            if len(df):
                (dest / (fid + ".json")).write_text(json.dumps(detalhe(n, c, df, ctx, pl, rent)), encoding="utf-8")
                df.drop(columns=["chave", "fator"], errors="ignore").to_parquet(dest / (fid + ".parquet"), index=False)
        # visao geral: cotas diarias de todos (para retorno em qualquer periodo, consolidado e risco x retorno)
        datas = sorted(d.data.unique())
        idx = pd.DatetimeIndex(datas)
        q = d.pivot_table(index="data", columns="fundo", values="VL_QUOTA").reindex(idx)
        plf = d.pivot_table(index="data", columns="fundo", values="VL_PATRIM_LIQ").reindex(idx)
        cdi_idx = (1 + ctx.cdi_d.reindex(idx).fillna(0)).cumprod()
        cores, k_nosso = {}, 0
        for n, c, nosso in fundos:
            cores[n] = NOSSAS_CORES[k_nosso % len(NOSSAS_CORES)] if nosso else "#9aa0a6"
            k_nosso += nosso
        visao = {"chave": chave, "gerado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "desde": lt.DESDE,
                 "ult_carteira": max(meses) if meses else None, "anbima": ctx.an_dias[-1] if ctx.an_dias else None,
                 "datas": [t.strftime("%Y-%m-%d") for t in idx], "cdi": cdi_idx.tolist(),
                 "fundos": [{"nome": n, "cnpj": c, "id": re.sub(r"\D", "", c), "nosso": nosso, "cor": cores[n],
                             "tem_carteira": (dest / (re.sub(r"\D", "", c) + ".json")).exists(),
                             "cota": q[n].tolist() if n in q else [], "pl": float(plf[n].dropna().iloc[-1]) / 1e6 if n in plf and plf[n].notna().any() else None}
                            for n, c, nosso in fundos],
                 "cat_cores": CAT_CORES}
        (dest / "visao.json").write_text(json.dumps(limpo(visao)), encoding="utf-8")
        escreve("Pronto.")
        PRE.update(status="ok", pasta=str(dest))
    except Exception as e:
        import traceback
        PRE.update(status="erro", erro=f"{type(e).__name__}: {e}")
        escreve("ERRO: " + PRE["erro"])
        escreve(traceback.format_exc()[-1500:])


def _inicio():                              # servidor (pasta/Docker): pre-carga em segundo plano
    if PRE["status"] == "parado":
        threading.Thread(target=precarrega, daemon=True).start()


app.add_event_handler("startup", _inicio)


# ------------------------------------------------------------------ API
@app.get("/api/inicial")
def inicial():
    return {"status": PRE["status"], "log": PRE["log"][-8:], "erro": PRE["erro"]}


def _arquivo(nome):
    if PRE["status"] != "ok":
        raise HTTPException(503, "painel ainda carregando")
    f = os.path.join(PRE["pasta"], nome)
    if not os.path.exists(f):
        raise HTTPException(404, "sem dados")
    return f


@app.get("/api/visao")
def visao():
    return FileResponse(_arquivo("visao.json"), media_type="application/json")


@app.get("/api/fundo/{fid}")
def fundo(fid: str):
    return FileResponse(_arquivo(re.sub(r"\D", "", fid) + ".json"), media_type="application/json")


@app.get("/api/csv/{fid}")
def csv(fid: str):
    df = pd.read_parquet(_arquivo(re.sub(r"\D", "", fid) + ".parquet"))
    return Response(df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="carteira_{fid}.csv"'})


@app.get("/")
def index():
    return FileResponse(os.path.join(AQUI, "static", "index.html"))
