"""
Relatório de performance por fundo -> PDF (1 página por fundo) + Excel.
Excel: só base, cotas e cdi são dados (como vêm do SQL); tabelas, gráficos e tudo o mais são fórmulas.
Uso:  python performance.py 2026-10-08      (sem data = D-1 útil)
      --sem-cache (busca tudo no SQL) | --limpa-cache (apaga o cache e recomeça). Cache em cache_performance/.
"""
import os, re, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from sql_func import try_retry

# ============================== CONFIG ==============================
FUNDOS = {
    "FICFI54079": "Precision",
    "FICFI54347": "Dual",
    "FICFI58573": "Dual Global",
    "FICFI57848": "Dual Prev",
    "ITADFIM57826": "Prev BB",
}
PASTA_SAIDA = "saida_performance"
# ====================================================================

JANELAS = ["5D", "MTD", "YTD", "12M", "24M", "36M"]
HEDGES = ["Hedge USD", "Hedge IPCA", "Hedge Pre"]          # zerados no PnL Hedgeado
FORA = HEDGES + ["Hedge Bonds", "Outros"]                  # fora de estoque / tipo / ranking
ORDEM = ["Cash", "LF", "LFSN", "LFSC", "DEB", "DEBIN", "Bonds", "CRA", "CR", "CRI", "NC", "FIDC"]
NAVY, LARANJA, VERDE = "#1F2A4D", "#EC7000", "#E2EFDA"

SQL_POSICAO = """
SELECT date, codigo_IAM_fundo, codigo_IAM_ativo,
    CONCAT(CASE WHEN ticker_bolsa IS NULL OR ticker_bolsa = 'B' THEN codigo_IAM_ativo ELSE ticker_bolsa END,
           ' - ', CONVERT(varchar(10), vencimento, 103)) AS ticker_venc,
    CASE
        WHEN ativo IN ('Future Cupom Cambial', 'Future FX', 'FX Spot') THEN 'Hedge USD'
        WHEN tipo = 'CaixaCPR' AND codigo_IAM_ativo <> 'CaixaCPROutros' THEN 'Cash'
        WHEN ativo IN ('Bonds', 'Bond Collateral') THEN 'Bonds'
        WHEN ativo IN ('DEB', 'DEBIT') THEN 'DEB'
        WHEN ativo = 'Bond Swap' THEN 'Hedge Bonds'
        WHEN ativo = 'Future CPI' THEN 'Hedge IPCA'
        WHEN ativo = 'Future Interest Rate' THEN 'Hedge Pre'
        WHEN ativo = 'PL Cota Senior' THEN 'FIDC'
        WHEN ativo IN ('LFT', 'Overnight', 'Itaú Zeragem', 'Cash') THEN 'Cash'
        WHEN tipo = 'Despesa' OR codigo_IAM_ativo = 'CaixaCPROutros' OR ativo = 'CPR Resgate' THEN 'Outros'
        WHEN codigo_IAM_ativo IN ('ADFIM54217','DOLOMITAS2','ITAUTITLISSEN','ZERARF54582','VERTIOFF53940',
            'ITADFIM56470','VERFIM58509','FLEFIM59015','ITADFIM57826','ESP_MOPPGDULT',
            'MOGD_MOPPHF_CCI','FLEXPREVDI1928','FICFI57848','ESP_MOPPGD',
            'MOPPHFGD_CCI','ESP_OPPITUB','INITAUPIRIIMEZ','ITDOLOMITASUB',
            'ITFIM57865','ITDFIM57862','WEALTHMAS53004','PIRINEUIIIMEZ',
            'FICFI54079','FICFI54347','DOLOMITASSUB','FUJIFI59181',
            'ROGD_MOPP_CCI','ESP_GDFIMOPP','SUBDOLOMITAS2','RPGD_MOPP_CCI',
            'PIRINEUSIISUB','FICFI56462','FICFI58573','GDRFMOPP_CCI',
            'MPGD_MOPPHF_CCI','ULMOPPHF_CCI','INITAUPIRIISUB','ITDOLOMITSUB') THEN 'FIDC'
        ELSE ativo
    END AS categoria,
    CASE WHEN tipo = 'Future' THEN NULL ELSE indexador END AS indexador,
    moeda_ativo, grupo_economico_iam, setor_iam, subsetor_iam,
    ISNULL(perc_nav, 0) AS perc_nav, total_nav_moeda_fundo,
    ISNULL(spread_cdi, 0) AS spread_cdi, ISNULL(macaulay_duration, 0) AS macaulay_duration,
    ISNULL(pnl_total_perc, 0) AS pnl_total_perc,
    ISNULL(perc_nav / NULLIF(perc_pl_explosao, 0) * pnl_cambio_explosao_perc, 0) AS pnl_cambio
FROM {view}
WHERE date BETWEEN '{ini}' AND '{fim}' AND codigo_IAM_fundo IN ({fundos})
"""

# Mesmas fórmulas da planilha (tabela "base")
_ID = "base[date],[@date],base[codigo_IAM_fundo],[@codigo_IAM_fundo]"
FORMULAS_BASE = [
    ("Caixa USD liquida", f'SUMIFS(base[perc_nav],{_ID},base[categoria],"Cash",base[moeda_ativo],"USD")'),
    ("peso USD", 'IF(OR(AND([@categoria]="Bonds",[@perc_nav]>0),AND([@categoria]="Cash",[@moeda_ativo]="USD",'
                 f'[@[Caixa USD liquida]]>0)),IFERROR([@perc_nav]/(SUMIFS(base[perc_nav],{_ID},'
                 'base[categoria],"Bonds",base[perc_nav],">0")+MAX([@[Caixa USD liquida]],0)),0),0)'),
    ("PnL Hedge IPCA", f'IF(AND([@indexador]="IPCA+",[@moeda_ativo]="BRL"),IFERROR([@perc_nav]/SUMIFS(base[perc_nav],{_ID},'
                       f'base[indexador],"IPCA+",base[moeda_ativo],"BRL")*SUMIFS(base[pnl_total_perc],{_ID},'
                       'base[categoria],"Hedge IPCA"),0),0)'),
    ("PnL Hedge PRE", f'IF(AND([@indexador]="PRE",[@moeda_ativo]="BRL"),IFERROR([@perc_nav]/SUMIFS(base[perc_nav],{_ID},'
                      f'base[indexador],"PRE",base[moeda_ativo],"BRL")*SUMIFS(base[pnl_total_perc],{_ID},'
                      'base[categoria],"Hedge Pre"),0),0)'),
    ("PnL Hedge USD", f'[@[peso USD]]*SUMIFS(base[pnl_total_perc],{_ID},base[categoria],"Hedge USD")'),
    ("FX USD alocado", f'[@[peso USD]]*SUMIFS(base[pnl_cambio],{_ID})'),
    ("PnL Hedgeado", 'IF(OR([@categoria]="Hedge IPCA",[@categoria]="Hedge Pre",[@categoria]="Hedge USD"),0,'
                     '[@pnl_total_perc]+[@[PnL Hedge IPCA]]+[@[PnL Hedge PRE]]+[@[PnL Hedge USD]]+[@[FX USD alocado]])'),
]


# ----------------------------- dados (com cache) -----------------------------
# Cache em disco: dados com mais de MESES_FRESCOS meses são considerados definitivos e ficam salvos;
# a cada rodada o SQL só busca os últimos MESES_FRESCOS meses (+ o que faltar no cache).
#   cache_performance/<tabela>_<versão do SQL>/<fundo>/<AAAA-MM>.parquet  +  manifesto.json {fundo: {desde, ate}}
#   - versão = hash do texto do SQL: mudou a query, o cache antigo é ignorado sozinho;
#   - gravação atômica (arquivo temporário + rename) e o manifesto só avança depois dos arquivos gravados;
#   - ao regravar um trecho, as linhas daquele intervalo de datas são substituídas (nunca duplica);
#   - arquivo corrompido: o fundo é apagado do cache e baixado de novo.
# Uso: python performance.py [data] [--sem-cache] [--limpa-cache]
PASTA_CACHE = "cache_performance"
MESES_FRESCOS = 2
USA_CACHE = "--sem-cache" not in sys.argv
if "--limpa-cache" in sys.argv and os.path.isdir(PASTA_CACHE):
    import shutil
    shutil.rmtree(PASTA_CACHE)
sys.argv = [a for a in sys.argv if a not in ("--sem-cache", "--limpa-cache")]
UM_DIA = pd.Timedelta(days=1)


def sql_data(d):
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def lista(fundos):
    return ", ".join(f"'{f}'" for f in fundos)


def _versao(*textos):
    import hashlib
    return hashlib.md5("|".join(textos).encode("utf-8")).hexdigest()[:8]


def _grava(df, arq):
    os.makedirs(os.path.dirname(arq), exist_ok=True)
    tmp = arq + ".tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, arq)


def _meses(a, b):
    return pd.period_range(pd.Timestamp(a), pd.Timestamp(b), freq="M")


def com_cache(tabela, versao, chaves, ini, fim, busca):
    """busca(chaves, a, b) -> DataFrame com coluna 'date' (datetime) e 'chave'. Devolve [ini, fim] para as chaves."""
    import json
    ini, fim = pd.Timestamp(ini).normalize(), pd.Timestamp(fim).normalize()
    corte = pd.Timestamp.today().normalize() - pd.DateOffset(months=MESES_FRESCOS)   # antes disso: definitivo
    lim = min(fim, corte - UM_DIA)
    partes = []
    if USA_CACHE and ini <= lim:
        pasta = os.path.join(PASTA_CACHE, f"{tabela}_{versao}")
        arq_man = os.path.join(pasta, "manifesto.json")
        man = json.load(open(arq_man, encoding="utf-8")) if os.path.exists(arq_man) else {}

        def salva_man():
            os.makedirs(pasta, exist_ok=True)
            json.dump(man, open(arq_man + ".tmp", "w", encoding="utf-8"), indent=1, sort_keys=True)
            os.replace(arq_man + ".tmp", arq_man)

        def le(k, a, b):
            out = []
            for m in _meses(a, b):
                arq = os.path.join(pasta, str(k), f"{m}.parquet")
                if os.path.exists(arq):
                    x = pd.read_parquet(arq)
                    out.append(x[x.date.between(a, b)])
            return pd.concat(out, ignore_index=True) if out else None

        def atualiza(k, a, b):
            novo = busca([k], a, b)
            for m in _meses(a, b):
                arq = os.path.join(pasta, str(k), f"{m}.parquet")
                velho = pd.read_parquet(arq) if os.path.exists(arq) else None
                if velho is not None:
                    velho = velho[~velho.date.between(a, b)]               # substitui o intervalo (nunca duplica)
                pedaco = novo[novo.date.dt.to_period("M") == m]
                junto = pd.concat([x for x in (velho, pedaco) if x is not None and len(x)], ignore_index=True) \
                    if (velho is not None and len(velho)) or len(pedaco) else None
                if junto is not None:
                    _grava(junto.sort_values("date"), arq)

        for k in chaves:
            ent = man.get(str(k))
            d, a = (pd.Timestamp(ent["desde"]), pd.Timestamp(ent["ate"])) if ent else (None, None)
            lacunas = [(ini, lim)] if ent is None else \
                [x for x in ((ini, d - UM_DIA), (a + UM_DIA, lim)) if x[0] <= x[1]]
            for x0, x1 in lacunas:
                print(f"  cache {tabela} {k}: buscando {x0:%d/%m/%Y} a {x1:%d/%m/%Y}")
                atualiza(k, x0, x1)
                d = x0 if d is None or x0 < d else d
                a = x1 if a is None or x1 > a else a
                man[str(k)] = {"desde": sql_data(d), "ate": sql_data(a)}
                salva_man()                                                # só depois dos arquivos gravados
            try:
                x = le(k, ini, lim)
            except Exception as e:                                         # arquivo corrompido: refaz este fundo
                print(f"  cache {tabela} {k} com problema ({e}); baixando de novo")
                import shutil
                shutil.rmtree(os.path.join(pasta, str(k)), ignore_errors=True)
                man.pop(str(k), None)
                salva_man()
                atualiza(k, ini, lim)
                man[str(k)] = {"desde": sql_data(ini), "ate": sql_data(lim)}
                salva_man()
                x = le(k, ini, lim)
            if x is not None and len(x):
                partes.append(x)
    elif ini <= lim:
        partes.append(busca(list(chaves), ini, lim))
    if fim >= corte:                                                       # parte recente: sempre do SQL
        partes.append(busca(list(chaves), max(ini, corte), fim))
    partes = [x for x in partes if x is not None and len(x)]
    return pd.concat(partes, ignore_index=True) if partes else busca(list(chaves), fim + UM_DIA, fim)


SQL_CDI = ("SELECT date, pnl_perc FROM FUNDOS_DADOS_INDICES WHERE codigo_IAM_indice = 'CDI' "
           "AND date BETWEEN '{ini}' AND '{fim}'")
SQL_COTAS = ("SELECT date, codigo_IAM_fundo, fundo_pnl_perc FROM VIEW_FUNDOS_COTAS_PL "
             "WHERE codigo_IAM_fundo IN ({fundos}) AND date BETWEEN '{ini}' AND '{fim}'")
VIEW_RECENTE, VIEW_HIST = "VW_FUNDOS_POSICAO_EXPLODIDA_DOWN", "VW_FUNDOS_POSICAO_EXPLODIDA_DOWN_HIST"


def _data(df):
    return df.assign(date=pd.to_datetime(df.date)) if len(df) else df.assign(date=pd.to_datetime(pd.Series([], dtype=object)))


def carrega_cdi(ini, fim):
    busca = lambda ks, a, b: _data(try_retry(SQL_CDI.format(ini=sql_data(a), fim=sql_data(b))))
    df = com_cache("cdi", _versao(SQL_CDI), ["CDI"], ini, fim, busca)
    return df.drop_duplicates("date").set_index("date")["pnl_perc"].astype(float).sort_index()


def carrega_cotas(fundos, ini, fim):
    busca = lambda ks, a, b: _data(try_retry(SQL_COTAS.format(fundos=lista(ks), ini=sql_data(a), fim=sql_data(b))))
    df = com_cache("cotas", _versao(SQL_COTAS), list(fundos), ini, fim, busca)
    return df.assign(fundo_pnl_perc=df.fundo_pnl_perc.astype(float))


def _busca_posicoes(fundos, ini, fim):
    """Explodida: últimos 6M na _DOWN, o resto na _DOWN_HIST."""
    corte = pd.Timestamp.today().normalize() - pd.DateOffset(months=6)
    partes = []
    if ini < corte:
        partes.append((VIEW_HIST, ini, min(fim, corte - UM_DIA)))
    if fim >= corte:
        partes.append((VIEW_RECENTE, max(ini, corte), fim))
    return _data(pd.concat([try_retry(SQL_POSICAO.format(view=v, ini=sql_data(a), fim=sql_data(b), fundos=lista(fundos)))
                            for v, a, b in partes], ignore_index=True))


def carrega_posicoes(fundos, ini, fim):
    """Posições (com cache) já com as colunas de hedge."""
    df = com_cache("posicoes", _versao(SQL_POSICAO, VIEW_RECENTE, VIEW_HIST), list(fundos), ini, fim, _busca_posicoes)
    for c in ["perc_nav", "total_nav_moeda_fundo", "spread_cdi", "macaulay_duration", "pnl_total_perc", "pnl_cambio"]:
        df[c] = pd.to_numeric(df[c]).fillna(0)
    return calcula_hedge(df.sort_values(["date", "codigo_IAM_fundo"], kind="stable").reset_index(drop=True))


def calcula_hedge(df):
    """Mesma lógica das FORMULAS_BASE, em pandas."""
    chave = [df.date, df.codigo_IAM_fundo]
    soma = lambda mask, col: df[col].where(mask, 0).groupby(chave).transform("sum")
    cat, nav, moeda = df.categoria, df.perc_nav, df.moeda_ativo
    df["Caixa USD liquida"] = soma((cat == "Cash") & (moeda == "USD"), "perc_nav")
    eh_usd = ((cat == "Bonds") & (nav > 0)) | ((cat == "Cash") & (moeda == "USD") & (df["Caixa USD liquida"] > 0))
    den = soma((cat == "Bonds") & (nav > 0), "perc_nav") + df["Caixa USD liquida"].clip(lower=0)
    df["peso USD"] = np.where(eh_usd & (den != 0), nav / den.replace(0, np.nan), 0)
    for idx, hedge, col in [("IPCA+", "Hedge IPCA", "PnL Hedge IPCA"), ("PRE", "Hedge Pre", "PnL Hedge PRE")]:
        m = (df.indexador == idx) & (moeda == "BRL")
        s = soma(m, "perc_nav")
        df[col] = np.where(m & (s != 0), nav / s.replace(0, np.nan) * soma(cat == hedge, "pnl_total_perc"), 0)
    df["PnL Hedge USD"] = df["peso USD"] * soma(cat == "Hedge USD", "pnl_total_perc")
    df["FX USD alocado"] = df["peso USD"] * soma(pd.Series(True, index=df.index), "pnl_cambio")
    df["PnL Hedgeado"] = np.where(cat.isin(HEDGES), 0, df.pnl_total_perc + df["PnL Hedge IPCA"] + df["PnL Hedge PRE"]
                                  + df["PnL Hedge USD"] + df["FX USD alocado"])
    return df


def retorno_fundo(pos, cotas, cdi, datas, base):
    """Oficial (cotas PL), exceto D-1 e D-2 -> calculado (e dia sem cota oficial -> calculado)."""
    calc = pos.groupby(["codigo_IAM_fundo", "date"])["PnL Hedgeado"].sum().rename("pnl_calc")
    ofic = cotas.groupby(["codigo_IAM_fundo", "date"])["fundo_pnl_perc"].sum().rename("pnl_oficial")
    df = pd.concat([calc, ofic], axis=1).reset_index()
    df = df[df.date.isin(datas)]
    df["ultimos_2d"] = df.date.isin(datas[-2:])
    df["pnl_usado"] = np.where(df.pnl_oficial.isna() | df.ultimos_2d, df.pnl_calc, df.pnl_oficial)
    df["cdi"] = df.date.map(cdi)
    return df


# ----------------------------- cálculos -----------------------------
def datas_janela(datas, base, j):
    if j == "5D":
        return datas[-5:]
    if j == "MTD":
        return datas[(datas.year == base.year) & (datas.month == base.month)]
    if j == "YTD":
        return datas[datas.year == base.year]
    return datas[datas > base - pd.DateOffset(months=int(j[:-1]))]


def comp(r):
    return float(np.prod(1 + np.asarray(r, dtype=float)) - 1)


def ordena(cats):
    return [c for c in ORDEM if c in cats] + sorted(c for c in cats if c not in ORDEM)


def tabelas_fundo(cod, pos, ret, cdi, datas, base):
    r = ret[ret.codigo_IAM_fundo == cod].set_index("date")["pnl_usado"].sort_index()

    t1 = []
    for j in JANELAS:
        rj = r[r.index.isin(datas_janela(datas, base, j))].dropna()
        f, c = comp(rj), comp(cdi.reindex(rj.index))
        t1.append([j, f, c, f / c if c else np.nan, ((1 + f) / (1 + c)) ** (252 / max(len(rj), 1)) - 1])
    t1 = pd.DataFrame(t1, columns=["Janela", "Fundo", "CDI", "% CDI", "CDI+"])

    p = pos[(pos.codigo_IAM_fundo == cod) & ~pos.categoria.isin(FORA)]
    hoje = p[p.date == p.date.max()].assign(fin=lambda d: d.total_nav_moeda_fundo / 1e6,
                                            dur=lambda d: d.macaulay_duration / 252)
    media = lambda g, col: np.average(g[col], weights=g.perc_nav) if g.perc_nav.sum() else 0
    linhas = []
    for nome, g in list(hoje.groupby("categoria")) + [("Total", hoje)]:
        linhas.append([nome, g.perc_nav.sum(), g.fin.sum(), media(g, "spread_cdi"), media(g, "dur")])
    t2 = pd.DataFrame(linhas, columns=["Categoria", "Exposição", "Financeiro (mm)", "Spread CDI+", "Duration (anos)"])
    t2 = t2.set_index("Categoria").loc[ordena(hoje.categoria.unique()) + ["Total"]].reset_index()

    def por(col, nomes):
        d = p.groupby([col, "date"])[["PnL Hedgeado", "perc_nav"]].sum()
        d = d[d.perc_nav != 0]
        rb = d["PnL Hedgeado"] / d.perc_nav
        out = pd.DataFrame(index=nomes, columns=JANELAS, dtype=float)
        for b in nomes:
            for j in JANELAS:
                serie = rb.loc[b] if b in rb.index.get_level_values(0) else pd.Series(dtype=float)
                rj = serie[serie.index.isin(datas_janela(datas, base, j))]
                out.loc[b, j] = comp(rj) / comp(cdi.reindex(rj.index)) if len(rj) else np.nan
        return out

    cats = ordena(hoje.categoria.unique())
    t3 = por("categoria", cats[1:] + cats[:1] if cats[:1] == ["Cash"] else cats)
    t3 = t3.rename_axis("Categoria").reset_index()
    setores = sorted(hoje.setor_iam.dropna().unique())
    t4 = por("setor_iam", setores)
    t4.insert(0, "% PL", hoje.groupby("setor_iam").perc_nav.sum().reindex(setores))
    t4 = t4.rename_axis("Setor").reset_index()

    r12 = r[r.index.isin(datas_janela(datas, base, "12M"))].dropna()
    diario = (r12 / cdi.reindex(r12.index)).replace([np.inf, -np.inf], np.nan).dropna()
    acum = ((1 + r12).cumprod() - 1) / ((1 + cdi.reindex(r12.index)).cumprod() - 1)   # fundo acumulado / CDI acumulado
    acum = acum.groupby(r12.index.to_period("M")).last()                             # ponto no fim de cada mês
    return {"t1": t1, "t2": t2, "t3": t3, "t4": t4, "diario": diario, "acum": acum}


# ----------------------------- gráficos -----------------------------
def br(x, casas=2, pct=False, sinal=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    x = x * 100 if pct else x
    s = f"{x:{'+' if sinal else ''},.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s + ("%" if pct else "")


def grafico_hist(ax, diario):
    v = diario.values * 100
    lo, hi = min(0, np.floor(np.percentile(v, 1) / 10) * 10), max(200, np.ceil(np.percentile(v, 99) / 10) * 10)
    ax.hist(np.clip(v, lo, hi), bins=np.arange(lo, hi + 5, 5), color=NAVY, edgecolor="white", linewidth=0.3)
    med, hoje = np.median(v), v[-1]
    ax.axvline(med, color="grey", ls="--", lw=1, label=f"mediana: {br(med, 1)}% CDI")
    ax.axvline(np.clip(hoje, lo, hi), color=LARANJA, ls="--", lw=1.5, label=f"hoje: {br(hoje, 1)}% CDI")
    ax.legend(fontsize=7, frameon=False, loc="upper left")
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0f}%")
    estilo_eixo(ax, "Distribuição do PnL diário em % CDI (12M)")


def grafico_acum(ax, acum):
    x = [p.strftime("%m/%Y") for p in acum.index]
    ax.plot(x, acum.values * 100, color=NAVY, marker="o", ms=3, lw=1.2)
    ax.axhline(100, color="grey", ls="--", lw=0.8)
    ax.annotate(f"{br(acum.iloc[-1] * 100, 1)}%", (x[-1], acum.iloc[-1] * 100), textcoords="offset points",
                xytext=(0, 6), ha="center", color=LARANJA, fontsize=8, fontweight="bold")
    ax.yaxis.set_major_formatter(lambda y, _: f"{y:.0f}%")
    ax.tick_params(axis="x", labelrotation=45)
    estilo_eixo(ax, "Fundo acumulado em % do CDI acumulado (12M)")


def estilo_eixo(ax, titulo):
    ax.set_title(titulo, loc="left", fontsize=10, fontweight="bold", color=NAVY)
    ax.tick_params(labelsize=7)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)


# ----------------------------- PDF -----------------------------
def desenha_tabela(ax, df, titulo, cores=None, fonte=7):
    """df já formatado em texto. cores: {(linha, coluna): (fundo, texto)} com linha 1 = 1ª linha de dados."""
    ax.axis("off")
    ax.set_title(titulo, loc="left", fontsize=10, fontweight="bold", color=NAVY)
    alt_pol = ax.get_position().height * ax.figure.get_figheight()          # altura do eixo em polegadas
    h = min(0.95, (len(df) + 1) * 0.24 / alt_pol)                           # ~0.24" por linha
    t = ax.table(cellText=df.values, colLabels=df.columns, cellLoc="center", bbox=[0, 0.95 - h, 1, h])
    t.auto_set_font_size(False)
    t.set_fontsize(fonte)
    for (i, j), cel in t.get_celld().items():
        cel.set_edgecolor("white")
        if i == 0:
            cel.set_facecolor(NAVY)
            cel.get_text().set_color("white")
            cel.get_text().set_fontweight("bold")
        elif i % 2 == 0:
            cel.set_facecolor("#F4F4F4")
        if cores and (i, j) in cores:
            cel.set_facecolor(cores[(i, j)][0])
            cel.get_text().set_color(cores[(i, j)][1])


def cores_cdi(df, cols):
    return {(i + 1, df.columns.get_loc(c)): (VERDE, "red" if v < 1 else "black")
            for c in cols for i, v in enumerate(df[c]) if pd.notna(v)}


def pagina_pdf(pdf, nome, base, T):
    fig = plt.figure(figsize=(16.5, 11.7))
    fig.text(0.04, 0.955, nome, fontsize=20, fontweight="bold", color=NAVY)
    fig.text(0.04, 0.935, f"Relatório oficial | Data base: {base:%d/%m/%Y} | janelas: {', '.join(JANELAS)}",
             fontsize=9, color="grey")
    fig.add_artist(plt.Line2D([0.04, 0.96], [0.928, 0.928], color=LARANJA, lw=1.5))

    t1 = T["t1"]
    desenha_tabela(fig.add_axes([0.04, 0.72, 0.42, 0.18]), pd.DataFrame({
        "Janela": t1.Janela, "Fundo": t1.Fundo.map(lambda x: br(x, pct=True)),
        "CDI": t1.CDI.map(lambda x: br(x, pct=True)), "% CDI": t1["% CDI"].map(lambda x: br(x, 1, pct=True)),
        "CDI+": t1["CDI+"].map(lambda x: br(x, pct=True, sinal=True))}),
        "1. Performance por janela", cores_cdi(t1, ["% CDI"]), fonte=9)
    t2 = T["t2"]
    desenha_tabela(fig.add_axes([0.04, 0.40, 0.42, 0.27]), pd.DataFrame({
        "Categoria": t2.Categoria, "Exposição": t2["Exposição"].map(lambda x: br(x, 1, pct=True)),
        "Financeiro (mm)": t2["Financeiro (mm)"].map(br), "Spread CDI+": t2["Spread CDI+"].map(br),
        "Duration (anos)": t2["Duration (anos)"].map(lambda x: br(x, 1))}), "2. Estoque por categoria")
    for k, eixo, titulo in [("t3", [0.04, 0.03, 0.42, 0.32], "3. % CDI por tipo"),
                            ("t4", [0.52, 0.03, 0.44, 0.32], "4. % CDI por setor")]:
        t = T[k]
        txt = t.copy()
        for c in t.columns[1:]:
            txt[c] = t[c].map(lambda x: br(x, 1, pct=True))
        desenha_tabela(fig.add_axes(eixo), txt, titulo, cores_cdi(t, JANELAS))
    grafico_hist(fig.add_axes([0.54, 0.72, 0.42, 0.18]), T["diario"])
    grafico_acum(fig.add_axes([0.54, 0.43, 0.42, 0.20]), T["acum"])
    pdf.savefig(fig)
    plt.close(fig)


# ----------------------------- Excel -----------------------------
def formatos(wb):
    f = lambda **k: wb.add_format({"font_size": 9, **k})
    return {"head": f(bold=True, font_color="white", bg_color=NAVY, align="center"),
            "titulo": f(bold=True, font_size=14, font_color=NAVY), "sub": f(bold=True, font_color=NAVY),
            "txt": f(), "pct2": f(num_format="0.00%"), "pct1": f(num_format="0.0%"),
            "cdi": f(num_format="0.0%", bg_color=VERDE), "sinal": f(num_format="+0.00%;-0.00%"),
            "num2": f(num_format="#,##0.00"), "num1": f(num_format="0.0"), "data": f(num_format="dd/mm/yyyy"),
            "pct0": f(num_format="0%"), "mes": f(num_format="mm/yyyy"), "num2b": f(num_format="#,##0.00", bold=True),
            "data_head": f(bold=True, font_color="white", bg_color=NAVY, align="center", num_format="dd/mm/yyyy"),
            "verm": wb.add_format({"font_color": "red"})}


def tabela_excel(wb, nome, df, formulas=(), F=None):
    """Escreve df como Tabela do Excel (com colunas-fórmula opcionais)."""
    ws = wb.add_worksheet(nome)
    dados = df.astype(object).where(df.notna(), None).values.tolist() or [[None] * len(df.columns)]
    cols = [{"header": c, **({"format": F["data"]} if c == "date" else {})} for c in df.columns]
    # [@col] -> nome[@[col]]: forma completa que o Excel grava no arquivo
    completa = lambda f: re.sub(r"(?<![\w\]])\[@", f"{nome}[@", re.sub(r"\[@(\w+)\]", r"[@[\1]]", f))
    cols += [{"header": h, "formula": completa(f)} for h, f in formulas]
    ws.add_table(0, 0, len(dados), len(cols) - 1, {"name": nome, "data": dados, "columns": cols,
                                                   "style": "Table Style Light 9"})
    ws.set_column(0, len(cols) - 1, 15)
    ws.freeze_panes(1, 0)
    return ws


EXCEL_DIAS = 5               # dias de posição colados no Excel (base); janelas maiores das tabelas 3 e 4 só se a base cobrir
COLS_BASE = ["date", "codigo_IAM_fundo", "codigo_IAM_ativo", "ticker_venc", "categoria", "indexador", "moeda_ativo",
             "grupo_economico_iam", "setor_iam", "subsetor_iam", "perc_nav", "total_nav_moeda_fundo", "spread_cdi",
             "macaulay_duration", "pnl_total_perc", "pnl_cambio"]
_FORA = "OR(" + ",".join(f'[@categoria]="{c}"' for c in FORA) + ")"
_CAT = f"{_ID},base[categoria],[@categoria]"
_SET = f"{_ID},base[setor_iam],[@setor_iam],base[eh_ativo],1"
# colunas auxiliares da base para as tabelas 2, 3 e 4 (retorno do dia de cada grupo, rateado pelas linhas do grupo)
FORMULAS_PERF = [
    ("eh_ativo", f"IF({_FORA},0,1)"),
    ("spread_x_pl", "[@spread_cdi]*[@perc_nav]"),
    ("dur_x_pl", "[@macaulay_duration]/252*[@perc_nav]"),
    ("cdi", "SUMIFS(cdi[cdi],cdi[date],[@date])"),
    ("n_cat", f"COUNTIFS({_CAT})"),
    ("nav_cat", f"SUMIFS(base[perc_nav],{_CAT})"),
    ("ln_cat", f"IF([@nav_cat]=0,0,LN(1+SUMIFS(base[PnL Hedgeado],{_CAT})/[@nav_cat])/[@n_cat])"),
    ("ln_cdi_cat", "IF([@nav_cat]=0,0,LN(1+[@cdi])/[@n_cat])"),
    ("n_set", f'IF(OR([@eh_ativo]=0,[@setor_iam]=""),0,COUNTIFS({_SET}))'),
    ("nav_set", f"IF([@n_set]=0,0,SUMIFS(base[perc_nav],{_SET}))"),
    ("ln_set", f"IF([@nav_set]=0,0,LN(1+SUMIFS(base[PnL Hedgeado],{_SET})/[@nav_set])/[@n_set])"),
    ("ln_cdi_set", "IF([@nav_set]=0,0,LN(1+[@cdi])/[@n_set])"),
]
FORMULAS_COTAS = [
    ("pnl_calc", "SUMIFS(base[PnL Hedgeado],base[date],[@date],base[codigo_IAM_fundo],[@codigo_IAM_fundo])"),
    ("ultimos_2d", "[@date]>=LARGE(cdi[date],2)"),
    ("pnl_usado", 'IF(OR([@pnl_oficial]="",[@ultimos_2d]),[@pnl_calc],[@pnl_oficial])'),
    ("cdi", "SUMIFS(cdi[cdi],cdi[date],[@date])"),
    ("ln_fundo", "LN(1+[@pnl_usado])"),
    ("ln_cdi", "LN(1+[@cdi])"),
    ("pct_cdi", 'IFERROR([@pnl_usado]/[@cdi],"")'),
]
INICIO = {"5D": "=LARGE(cdi[date],5)", "MTD": "=DATE(YEAR($B$3),MONTH($B$3),1)", "YTD": "=DATE(YEAR($B$3),1,1)",
          "12M": "=EDATE($B$3,-12)+1", "24M": "=EDATE($B$3,-24)+1", "36M": "=EDATE($B$3,-36)+1"}
BINS = [round(-.5 + .1 * i, 2) for i in range(31)]                   # faixas do histograma: -50% a 250% do CDI


def aba_fundo(wb, cod, nome, cats, setores, F, extras=()):
    """Aba do fundo 100% em fórmulas sobre as tabelas base, cotas e cdi. Só o código do fundo e os rótulos são texto."""
    ws = wb.add_worksheet(nome[:31])
    ws.set_column(0, 0, 18)
    ws.set_column(1, 7, 12)
    ws.set_column(9, 13, 12)
    ws.write(0, 0, nome, F["titulo"])
    ws.write(1, 0, "Fundo", F["sub"])
    ws.write(1, 1, cod)
    ws.write(2, 0, "Data base", F["sub"])
    ws.write_formula(2, 1, "=MAX(cdi[date])", F["data"])
    ws.write(3, 0, "Base completa desde", F["sub"])
    ws.write_formula(3, 1, f"=LARGE(cdi[date],{EXCEL_DIAS})", F["data"])
    fc = 'cotas[codigo_IAM_fundo],$B$2,cotas[date],">="&{ini},cotas[date],"<="&$B$3'
    # 1. performance por janela (linhas 8 a 13: a coluna B guarda o início de cada janela)
    ws.write(5, 0, "1. Performance por janela", F["sub"])
    for j, h in enumerate(["Janela", "Início", "Fundo", "CDI", "% CDI", "CDI+", "Dias"]):
        ws.write(6, j, h, F["head"])
    for i, jan in enumerate(JANELAS):
        r, n = 7 + i, 8 + i
        f = fc.format(ini=f"$B{n}")
        ws.write(r, 0, jan)
        ws.write_formula(r, 1, INICIO[jan], F["data"])
        ws.write_formula(r, 2, f"=EXP(SUMIFS(cotas[ln_fundo],{f}))-1", F["pct2"])
        ws.write_formula(r, 3, f"=EXP(SUMIFS(cotas[ln_cdi],{f}))-1", F["pct2"])
        ws.write_formula(r, 4, f'=IFERROR(C{n}/D{n},"-")', F["cdi"])
        ws.write_formula(r, 5, f'=IFERROR(((1+C{n})/(1+D{n}))^(252/G{n})-1,"-")', F["sinal"])
        ws.write_formula(r, 6, f"=COUNTIFS({f})")
    ws.conditional_format(7, 4, 12, 4, {"type": "cell", "criteria": "<", "value": 1, "format": F["verm"]})
    ini = {jan: f"$B${8 + i}" for i, jan in enumerate(JANELAS)}
    # 2. estoque por categoria na data base
    r0 = 15
    ws.write(r0 - 1, 0, "2. Estoque por categoria", F["sub"])
    for j, h in enumerate(["Categoria", "Exposição", "Financeiro (mm)", "Spread CDI+", "Duration (anos)"]):
        ws.write(r0, j, h, F["head"])
    for i, c in enumerate(cats + ["Total"]):
        r, n = r0 + 1 + i, r0 + 2 + i
        crit = "base[codigo_IAM_fundo],$B$2,base[date],$B$3," + ("base[eh_ativo],1" if c == "Total" else f"base[categoria],$A{n}")
        ws.write(r, 0, c, F["sub"] if c == "Total" else F["txt"])
        ws.write_formula(r, 1, f"=SUMIFS(base[perc_nav],{crit})", F["pct1"])
        ws.write_formula(r, 2, f"=SUMIFS(base[total_nav_moeda_fundo],{crit})/10^6", F["num2"])
        ws.write_formula(r, 3, f'=IFERROR(SUMIFS(base[spread_x_pl],{crit})/B{n},"-")', F["num2"])
        ws.write_formula(r, 4, f'=IFERROR(SUMIFS(base[dur_x_pl],{crit})/B{n},"-")', F["num1"])

    # 3 e 4. % CDI por categoria e por setor: (grupo acumulado) / (CDI acumulado nos mesmos dias)
    def bloco(r0, titulo, rotulos, ln, ln_cdi, col, extra_pl):
        ws.write(r0 - 1, 0, titulo, F["sub"])
        cab = [("Categoria" if col == "categoria" else "Setor")] + (["% PL"] if extra_pl else []) + JANELAS
        for j, h in enumerate(cab):
            ws.write(r0, j, h, F["head"])
        k0 = 2 if extra_pl else 1
        for i, g in enumerate(rotulos):
            r, n = r0 + 1 + i, r0 + 2 + i
            filtro = f"base[codigo_IAM_fundo],$B$2,base[{col}],$A{n}" + (",base[eh_ativo],1" if col == "setor_iam" else "")
            ws.write(r, 0, g)
            if extra_pl:
                ws.write_formula(r, 1, f"=SUMIFS(base[perc_nav],{filtro},base[date],$B$3)", F["pct1"])
            for k, jan in enumerate(JANELAS):
                per = f'{filtro},base[date],">="&{ini[jan]},base[date],"<="&$B$3'
                ws.write_formula(r, k0 + k, f'=IF($B$4>{ini[jan]},"-",IFERROR((EXP(SUMIFS(base[{ln}],{per}))-1)/'
                                            f'(EXP(SUMIFS(base[{ln_cdi}],{per}))-1),"-"))', F["cdi"])
        if rotulos:
            ws.conditional_format(r0 + 1, k0, r0 + len(rotulos), k0 + len(JANELAS) - 1,
                                  {"type": "cell", "criteria": "<", "value": 1, "format": F["verm"]})
        return r0 + len(rotulos) + 4

    r0 = bloco(r0 + len(cats) + 5, "3. % CDI por tipo", cats[1:] + cats[:1] if cats[:1] == ["Cash"] else cats,
               "ln_cat", "ln_cdi_cat", "categoria", False)
    r0 = bloco(r0, "4. % CDI por setor", setores, "ln_set", "ln_cdi_set", "setor_iam", True)

    # 5. PnL de cada dia da base por categoria (bps do PL), para diagnóstico
    ws.write(r0 - 1, 0, f"5. PnL diário por categoria (bps do PL) - últimos {EXCEL_DIAS} dias", F["sub"])
    ws.write(r0, 0, "Categoria", F["head"])
    col = lambda k: chr(ord("B") + k)                                      # colunas B.. = dias; última = soma
    for k in range(EXCEL_DIAS):
        ws.write_formula(r0, 1 + k, f"=LARGE(cdi[date],{EXCEL_DIAS - k})", F["data_head"])
    ws.write(r0, 1 + EXCEL_DIAS, f"Soma {EXCEL_DIAS}D", F["head"])
    fd = lambda k: f"base[codigo_IAM_fundo],$B$2,base[date],{col(k)}${r0 + 1}"
    linhas = [(c, f"SUMIFS(base[PnL Hedgeado],{{f}},base[categoria],\"{c}\")*10^4", "num2") for c in cats + extras] + [
        ("Total calculado", "SUMIFS(base[PnL Hedgeado],{f})*10^4", "neg"),
        ("Cota oficial", 'IF(COUNTIFS({fc},cotas[pnl_oficial],"<>")=0,"-",SUMIFS(cotas[pnl_oficial],{fc})*10^4)', "num2"),
        ("Calculado - oficial", 'IFERROR({tot}-{ofi},"-")', "num2"),
        ("Retorno usado", "SUMIFS(cotas[pnl_usado],{fc})*10^4", "neg"),
        ("CDI", "SUMIFS(cdi[cdi],cdi[date],{d})*10^4", "num2"),
        ("% CDI", 'IFERROR({usado}/{cdi},"-")', "cdi"),
        ("Memória (antes da alocação):", None, None)] + [
        (f"  {h} bruto", f"SUMIFS(base[pnl_total_perc],{{f}},base[categoria],\"{h}\")*10^4", "num2") for h in HEDGES] + [
        ("  Câmbio (linha única)", "SUMIFS(base[pnl_cambio],{f})*10^4", "num2")]
    pos_ = {rot: r0 + 2 + i for i, (rot, _, _) in enumerate(linhas)}       # linha Excel (1-based) de cada item
    for i, (rot, form, fmt) in enumerate(linhas):
        r = r0 + 1 + i
        ws.write(r, 0, rot, F["sub"] if form is None or fmt == "neg" else F["txt"])
        if form is None:
            continue
        for k in range(EXCEL_DIAS + 1):
            if k == EXCEL_DIAS:                                            # coluna de soma (não para % CDI e oficial)
                if rot in ("% CDI", "Cota oficial", "Calculado - oficial"):
                    continue
                ws.write_formula(r, 1 + k, f"=SUM(B{r + 1}:{col(k - 1)}{r + 1})", F["num2b"] if fmt == "neg" else F["num2"])
                continue
            c = col(k)
            dref = f"{c}${r0 + 1}"
            ff = form.format(f=fd(k), fc=f"cotas[codigo_IAM_fundo],$B$2,cotas[date],{dref}", d=dref,
                             tot=f"{c}{pos_['Total calculado']}", ofi=f"{c}{pos_['Cota oficial']}",
                             usado=f"{c}{pos_['Retorno usado']}", cdi=f"{c}{pos_['CDI']}")
            ws.write_formula(r, 1 + k, "=" + ff, F["num2b"] if fmt == "neg" else F[fmt])

    # histograma do PnL diário em % CDI (12M), colunas J:K
    f12 = fc.format(ini=ini["12M"])
    ws.write(5, 9, "Distribuição diária em % CDI (12M)", F["sub"])
    ws.write(6, 9, "Faixa (% CDI)", F["head"])
    ws.write(6, 10, "Dias", F["head"])
    for i, b in enumerate(BINS[:-1]):
        r, n = 7 + i, 8 + i
        ws.write(r, 9, b, F["pct0"])
        lo = "" if i == 0 else f',cotas[pct_cdi],">="&J{n}'
        hi = "" if i == len(BINS) - 2 else f',cotas[pct_cdi],"<"&J{n + 1}'
        ws.write_formula(r, 10, f"=COUNTIFS({f12}{lo}{hi})")
    rm = 7 + len(BINS)
    ws.write(rm, 9, "Mediana", F["sub"])
    ws.write_array_formula(rm, 10, rm, 10, "{=MEDIAN(IF((cotas[codigo_IAM_fundo]=$B$2)*(cotas[date]>=" + ini["12M"] +
                           ")*(cotas[date]<=$B$3)*ISNUMBER(cotas[pct_cdi]),cotas[pct_cdi]))}", F["pct1"])
    ws.write(rm + 1, 9, "Hoje", F["sub"])
    ws.write_formula(rm + 1, 10, "=SUMIFS(cotas[pct_cdi],cotas[codigo_IAM_fundo],$B$2,cotas[date],$B$3)", F["pct1"])
    # acumulado: fundo acumulado / CDI acumulado no fim de cada mês da janela de 12M, colunas M:N
    ws.write(5, 12, "Fundo acum. / CDI acum. (12M)", F["sub"])
    ws.write(6, 12, "Mês", F["head"])
    ws.write(6, 13, "% CDI acum.", F["head"])
    for i, k in enumerate(range(12, -1, -1)):
        r, n = 7 + i, 8 + i
        per = f12.replace('"<="&$B$3', f'"<="&MIN(M{n},$B$3)')
        ws.write_formula(r, 12, f"=EOMONTH($B$3,-{k})", F["mes"])
        ws.write_formula(r, 13, f"=IF(M{n}<{ini['12M']},NA(),IFERROR((EXP(SUMIFS(cotas[ln_fundo],{per}))-1)/"
                                f"(EXP(SUMIFS(cotas[ln_cdi],{per}))-1),NA()))", F["pct1"])
    aba = nome[:31].replace("'", "''")
    g = wb.add_chart({"type": "column"})
    g.add_series({"categories": f"='{aba}'!$J$8:$J${6 + len(BINS)}", "values": f"='{aba}'!$K$8:$K${6 + len(BINS)}",
                  "fill": {"color": NAVY}, "gap": 10, "name": "Dias"})
    g.set_title({"name": "Distribuição do PnL diário em % CDI (12M)", "name_font": {"size": 10, "color": NAVY}})
    g.set_legend({"none": True})
    g.set_x_axis({"num_format": "0%"})
    ws.insert_chart(5, 15, g, {"x_scale": 1.3, "y_scale": 1.1})
    g = wb.add_chart({"type": "line"})
    g.add_series({"categories": f"='{aba}'!$M$8:$M$20", "values": f"='{aba}'!$N$8:$N$20", "line": {"color": NAVY},
                  "marker": {"type": "circle", "size": 4, "fill": {"color": LARANJA}}, "name": "% CDI acum."})
    g.set_title({"name": "Fundo acumulado em % do CDI acumulado (12M)", "name_font": {"size": 10, "color": NAVY}})
    g.set_legend({"none": True})
    g.set_y_axis({"num_format": "0%"})
    g.set_x_axis({"num_format": "mm/yyyy"})
    ws.insert_chart(23, 15, g, {"x_scale": 1.3, "y_scale": 1.1})


def excel_formulas(xw, pos, cotas_ofic, cdi, datas, fundos_ok, F):
    """Só três tabelas são dados colados (base, cotas e cdi, como vêm do SQL); todo o resto é fórmula."""
    wb = xw.book
    base_dt = datas[-1]
    for cod in fundos_ok:                                                  # abas dos fundos primeiro
        hoje = pos[(pos.codigo_IAM_fundo == cod) & (pos.date == base_dt) & ~pos.categoria.isin(FORA)]
        cinco = pos[(pos.codigo_IAM_fundo == cod) & pos.date.isin(datas[-EXCEL_DIAS:])]
        extras = [c for c in ["Outros", "Hedge Bonds"] if (cinco.categoria == c).any()]   # entram no total e não são zerados
        aba_fundo(wb, cod, FUNDOS[cod], ordena(hoje.categoria.unique()), sorted(hoje.setor_iam.dropna().unique()), F, extras)
    # cotas: cotas oficiais + (fundo, dia) que só existem na posição (ex.: D-1 ainda sem cota), na janela de 36M
    of = cotas_ofic[cotas_ofic.date.isin(datas)].groupby(["date", "codigo_IAM_fundo"]).fundo_pnl_perc.sum()
    chaves = pd.MultiIndex.from_frame(pos[pos.date.isin(datas)][["date", "codigo_IAM_fundo"]].drop_duplicates())
    ct = of.reindex(of.index.union(chaves)).rename("pnl_oficial").reset_index()
    ct = ct[ct.codigo_IAM_fundo.isin(fundos_ok)].sort_values(["codigo_IAM_fundo", "date"])
    # base: últimos EXCEL_DIAS dias + dias antigos sem cota oficial (o retorno desses dias vem da posição)
    sem_cota = set(ct[ct.pnl_oficial.isna()].date)
    dias_base = set(datas[-EXCEL_DIAS:]) | sem_cota
    tabela_excel(wb, "base", pos[pos.date.isin(dias_base)][COLS_BASE], FORMULAS_BASE + FORMULAS_PERF, F)
    tabela_excel(wb, "cotas", ct, FORMULAS_COTAS, F)
    tabela_excel(wb, "cdi", cdi.loc[datas[0]:base_dt].rename("cdi").rename_axis("date").reset_index(), (), F)


# ----------------------------- main -----------------------------
def main():
    hoje = pd.Timestamp.today().normalize()
    if len(sys.argv) > 1:
        base = pd.to_datetime(sys.argv[1], dayfirst="/" in sys.argv[1])
    else:
        base = carrega_cdi(hoje - pd.Timedelta(days=15), hoje - pd.Timedelta(days=1)).index.max()
    cdi = carrega_cdi(base - pd.DateOffset(months=37), base)
    datas = cdi.index[cdi.index > base - pd.DateOffset(months=36)]
    print(f"Data base {base:%d/%m/%Y} | {len(datas)} dias úteis | carregando posições...")

    pos = carrega_posicoes(FUNDOS, datas[0], base)
    cotas = carrega_cotas(FUNDOS, datas[0], base)
    ret = retorno_fundo(pos, cotas, cdi, datas, base)

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    arq = os.path.join(PASTA_SAIDA, f"performance_{base:%Y%m%d}")
    with PdfPages(arq + ".pdf") as pdf, pd.ExcelWriter(arq + ".xlsx", engine="xlsxwriter") as xw:
        F = formatos(xw.book)
        ok = []
        for cod, nome in FUNDOS.items():
            if not (pos.codigo_IAM_fundo == cod).any():
                print(f"  {nome}: sem posições, pulando")
                continue
            pagina_pdf(pdf, nome, base, tabelas_fundo(cod, pos, ret, cdi, datas, base))
            ok.append(cod)
            print(f"  {nome} ok")
        excel_formulas(xw, pos, cotas, cdi, datas, ok, F)
    print(f"Gerado: {arq}.pdf / .xlsx")


if __name__ == "__main__":
    main()
