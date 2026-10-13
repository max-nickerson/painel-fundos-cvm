"""
Relatório de performance por fundo -> PDF (1 página por fundo) + Excel.
Uso:  python performance.py 2026-10-08      (sem data = D-1 útil)
"""
import io, os, re, sys
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


# ----------------------------- dados -----------------------------
def sql_data(d):
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def carrega_cdi(ini, fim):
    df = try_retry(f"SELECT date, pnl_perc FROM FUNDOS_DADOS_INDICES WHERE codigo_IAM_indice = 'CDI' "
                   f"AND date BETWEEN '{sql_data(ini)}' AND '{sql_data(fim)}'")
    return df.assign(date=pd.to_datetime(df.date)).set_index("date")["pnl_perc"].astype(float).sort_index()


def carrega_cotas(fundos, ini, fim):
    df = try_retry(f"SELECT date, codigo_IAM_fundo, fundo_pnl_perc FROM VIEW_FUNDOS_COTAS_PL "
                   f"WHERE codigo_IAM_fundo IN ({lista(fundos)}) AND date BETWEEN '{sql_data(ini)}' AND '{sql_data(fim)}'")
    return df.assign(date=pd.to_datetime(df.date), fundo_pnl_perc=df.fundo_pnl_perc.astype(float))


def lista(fundos):
    return ", ".join(f"'{f}'" for f in fundos)


def carrega_posicoes(fundos, ini, fim):
    """Explodida: últimos 6M na _DOWN, o resto na _DOWN_HIST. Já devolve as colunas de hedge."""
    ini, fim = pd.Timestamp(ini), pd.Timestamp(fim)
    corte = pd.Timestamp.today().normalize() - pd.DateOffset(months=6)
    partes = []
    if ini < corte:
        partes.append(("VW_FUNDOS_POSICAO_EXPLODIDA_DOWN_HIST", ini, min(fim, corte - pd.Timedelta(days=1))))
    if fim >= corte:
        partes.append(("VW_FUNDOS_POSICAO_EXPLODIDA_DOWN", max(ini, corte), fim))
    df = pd.concat([try_retry(SQL_POSICAO.format(view=v, ini=sql_data(a), fim=sql_data(b), fundos=lista(fundos)))
                    for v, a, b in partes], ignore_index=True)
    df["date"] = pd.to_datetime(df.date)
    for c in ["perc_nav", "total_nav_moeda_fundo", "spread_cdi", "macaulay_duration", "pnl_total_perc", "pnl_cambio"]:
        df[c] = pd.to_numeric(df[c]).fillna(0)
    return calcula_hedge(df.sort_values(["date", "codigo_IAM_fundo"]).reset_index(drop=True))


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
    """Oficial (cotas PL), exceto: últimos 2 dias -> calculado; até 1M com |dif| > 5 bps -> calculado."""
    calc = pos.groupby(["codigo_IAM_fundo", "date"])["PnL Hedgeado"].sum().rename("pnl_calc")
    ofic = cotas.groupby(["codigo_IAM_fundo", "date"])["fundo_pnl_perc"].sum().rename("pnl_oficial")
    df = pd.concat([calc, ofic], axis=1).reset_index()
    df = df[df.date.isin(datas)]
    df["ultimos_2d"] = df.date.isin(datas[-2:])
    recente = df.date > base - pd.DateOffset(months=1)
    usa_calc = df.pnl_oficial.isna() | df.ultimos_2d | (recente & ((df.pnl_calc - df.pnl_oficial).abs() > 0.0005))
    df["pnl_usado"] = np.where(usa_calc, df.pnl_calc, df.pnl_oficial)
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
    hoje = p[p.date == p.date.max()].assign(fin=lambda d: d.perc_nav * d.total_nav_moeda_fundo / 1e6)
    media = lambda g, col: np.average(g[col], weights=g.perc_nav) if g.perc_nav.sum() else 0
    linhas = []
    for nome, g in list(hoje.groupby("categoria")) + [("Total", hoje)]:
        linhas.append([nome, g.perc_nav.sum() / hoje.perc_nav.sum(), g.fin.sum(), media(g, "spread_cdi"),
                       media(g, "macaulay_duration")])
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
    mes = r12.index.to_period("M")
    mensal = r12.groupby(mes).apply(comp) / cdi.reindex(r12.index).groupby(mes).apply(comp)
    return {"t1": t1, "t2": t2, "t3": t3, "t4": t4, "diario": diario, "acum": mensal.expanding().mean()}


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
    estilo_eixo(ax, "Fundo acumulado em % CDI (média expansível, 12M)")


def estilo_eixo(ax, titulo):
    ax.set_title(titulo, loc="left", fontsize=10, fontweight="bold", color=NAVY)
    ax.tick_params(labelsize=7)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)


def png(func, *args):
    fig, ax = plt.subplots(figsize=(6.5, 3))
    func(ax, *args)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


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


def escreve_df(ws, r, c, df, fmts, F, titulo):
    """Escreve um bloco (título + cabeçalho + valores). fmts: {coluna: chave de formato}."""
    ws.write(r, c, titulo, F["sub"])
    for j, col in enumerate(df.columns):
        ws.write(r + 1, c + j, col, F["head"])
        for i, v in enumerate(df[col]):
            ws.write(r + 2 + i, c + j, "-" if pd.isna(v) else v, F[fmts.get(col, "txt")])
        if fmts.get(col) == "cdi":
            ws.conditional_format(r + 2, c + j, r + 1 + len(df), c + j,
                                  {"type": "cell", "criteria": "<", "value": 1, "format": F["verm"]})
    return r + len(df) + 4


def aba_relatorio(wb, nome, base, T, F):
    ws = wb.add_worksheet(nome[:31])
    ws.set_column(0, 7, 14)
    ws.write(0, 0, nome, F["titulo"])
    ws.write(1, 0, f"Data base: {base:%d/%m/%Y}", F["txt"])
    r = escreve_df(ws, 3, 0, T["t1"], {"Fundo": "pct2", "CDI": "pct2", "% CDI": "cdi", "CDI+": "sinal"}, F,
                   "1. Performance por janela")
    r = escreve_df(ws, r, 0, T["t2"], {"Exposição": "pct1", "Financeiro (mm)": "num2", "Spread CDI+": "num2",
                                       "Duration (anos)": "num1"}, F, "2. Estoque por categoria")
    r = escreve_df(ws, r, 0, T["t3"], {j: "cdi" for j in JANELAS}, F, "3. % CDI por tipo")
    escreve_df(ws, r, 0, T["t4"], {"% PL": "pct1", **{j: "cdi" for j in JANELAS}}, F, "4. % CDI por setor")
    ws.insert_image(3, 9, "hist.png", {"image_data": png(grafico_hist, T["diario"]), "x_scale": 0.7, "y_scale": 0.7})
    ws.insert_image(25, 9, "acum.png", {"image_data": png(grafico_acum, T["acum"]), "x_scale": 0.7, "y_scale": 0.7})


def excel_rentabilidade(wb, pos5, ret5, cdi, F):
    """Rentabilidade por data com SUMIFS sobre a tabela base (fundo, categoria, setor)."""
    tabela_excel(wb, "rent_fundo", ret5[["date", "codigo_IAM_fundo", "pnl_oficial", "cdi", "ultimos_2d"]], [
        ("pnl_calc", "SUMIFS(base[PnL Hedgeado],base[date],[@date],base[codigo_IAM_fundo],[@codigo_IAM_fundo])"),
        ("dif_bps", 'IF([@pnl_oficial]="","",([@pnl_calc]-[@pnl_oficial])*10000)'),
        ("pnl_usado", 'IF(OR([@pnl_oficial]="",[@ultimos_2d],ABS([@pnl_calc]-[@pnl_oficial])>0.0005),'
                      '[@pnl_calc],[@pnl_oficial])'),
        ("pct_cdi", "IFERROR([@pnl_usado]/[@cdi],0)")], F)
    p = pos5[~pos5.categoria.isin(FORA)]
    for nome, col in [("rent_categoria", "categoria"), ("rent_setor", "setor_iam")]:
        chaves = p.dropna(subset=[col])[["date", "codigo_IAM_fundo", col]].drop_duplicates()
        chaves = chaves.assign(cdi=chaves.date.map(cdi)).sort_values(["codigo_IAM_fundo", col, "date"])
        filtro = f"base[date],[@date],base[codigo_IAM_fundo],[@codigo_IAM_fundo],base[{col}],[@{col}]"
        tabela_excel(wb, nome, chaves, [
            ("pnl", f"SUMIFS(base[PnL Hedgeado],{filtro})"), ("perc_nav", f"SUMIFS(base[perc_nav],{filtro})"),
            ("retorno", "IFERROR([@pnl]/[@perc_nav],0)"), ("pct_cdi", "IFERROR([@retorno]/[@cdi],0)")], F)


COLS_BASE = ["date", "codigo_IAM_fundo", "codigo_IAM_ativo", "ticker_venc", "categoria", "indexador", "moeda_ativo",
             "grupo_economico_iam", "setor_iam", "subsetor_iam", "perc_nav", "total_nav_moeda_fundo", "spread_cdi",
             "macaulay_duration", "pnl_total_perc", "pnl_cambio"]


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
    ret = retorno_fundo(pos, carrega_cotas(FUNDOS, datas[0], base), cdi, datas, base)

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    arq = os.path.join(PASTA_SAIDA, f"performance_{base:%Y%m%d}")
    with PdfPages(arq + ".pdf") as pdf, pd.ExcelWriter(arq + ".xlsx", engine="xlsxwriter") as xw:
        wb = xw.book
        F = formatos(wb)
        for cod, nome in FUNDOS.items():
            if not (pos.codigo_IAM_fundo == cod).any():
                print(f"  {nome}: sem posições, pulando")
                continue
            T = tabelas_fundo(cod, pos, ret, cdi, datas, base)
            pagina_pdf(pdf, nome, base, T)
            aba_relatorio(wb, nome, base, T, F)
            print(f"  {nome} ok")
        pos5 = pos[pos.date.isin(datas[-5:])]
        tabela_excel(wb, "base", pos5[COLS_BASE], FORMULAS_BASE, F)
        excel_rentabilidade(wb, pos5, ret[ret.date.isin(datas[-5:])], cdi, F)
    print(f"Gerado: {arq}.pdf / .xlsx")


if __name__ == "__main__":
    main()
