"""
Relatório dos fundos na data de ontem (hoje - 1 dia útil):
  PDF, uma página por fundo: retorno x CDI, carteira por categoria, retorno por categoria e por setor em % do CDI
       (derivativos alocados aos ativos que protegem), distribuição do % do CDI diário e % do CDI acumulado (até 12 meses).
  Excel de conferência, últimos 5 dias: dados das views + as 4 tabelas em fórmulas simples.
Uso: python relatorio_fundos.py
"""
import re

import matplotlib
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

CONEXAO = "mssql+pyodbc://SERVIDOR/BANCO?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
FUNDOS = []                    # vazio = todos
INDEXADOR = "indexador"        # coluna da view com PRE / IPCA / DI / USD
ESCALA = 100                   # colunas *_perc em % (0,05 = 0,05%)
D = pd.Timestamp.today().normalize() - pd.offsets.BDay(1)
INICIO = D - pd.DateOffset(months=36)
FUT = re.compile(r"^(DI1|DAP|DDI|FRC|DOL|WDO)[FGHJKMNQUVXZ]\d{2}")
CATEGORIAS = ["DEBIN", "DEB", "LFSC", "LFSN", "LF", "CRI", "CRA", "NC", "CDB", "FIDC", "Fiagro", "Bonds", "LFT", "NTN-B"]
USD = r"(?i)\bbonds?\b|usd|treasury|collateral"
HEDGE = {                      # derivativo: (ativos que protege, pondera pela duration?)
    "DI1": (lambda p: p[INDEXADOR].eq("PRE"), True),
    "DAP": (lambda p: p[INDEXADOR].eq("IPCA"), True),
    "DDI": (lambda p: p.categoria.eq("Bonds"), True),
    "FRC": (lambda p: p.categoria.eq("Bonds"), True),
    "DOL": (lambda p: p.ativo.str.contains(USD, na=False), False),
    "WDO": (lambda p: p.ativo.str.contains(USD, na=False), False),
}
LARANJA, AZUL, TEXTO, CINZA, CLARO, AZUL_CLARO = "#EC7000", "#003399", "#2B2B2B", "#8C8C8C", "#FFF4EA", "#BFCDEB"
plt.rcParams.update({"font.family": ["Segoe UI", "Arial", "DejaVu Sans"], "font.size": 8.5, "axes.edgecolor": CINZA,
                     "axes.spines.top": False, "axes.spines.right": False, "xtick.color": TEXTO, "ytick.color": TEXTO})


# ------------------------------------------------------------------ dados
def le_banco():
    filtro = f" AND codigo_IAM_fundo IN ({','.join(repr(f) for f in FUNDOS)})" if FUNDOS else ""
    pos = (f"SELECT codigo_IAM_fundo, date, ativo, {INDEXADOR}, perc_nav, pnl_total_perc, pnl_benchmark_perc, spread_cdi, "
           f"macaulay_duration, setor_iam, total_nav_moeda_fundo FROM {{}} WHERE date > :a AND date <= :b{filtro}")
    corte = D - pd.DateOffset(months=6)
    with create_engine(CONEXAO).connect() as c:
        p = pd.concat([pd.read_sql(text(pos.format("VW_FUNDOS_POSICAO_EXPLODIDA_DOWN")), c, params={"a": corte, "b": D}),
                       pd.read_sql(text(pos.format("VW_FUNDOS_POSICAO_EXPLODIDA_DOWN_HIST")), c, params={"a": INICIO, "b": corte})])
        q = pd.read_sql(text("SELECT codigo_IAM_fundo, date, pnl_fundo_perc, pnl_benchmark_fundo_perc FROM VIEW_FUNDOS_COTAS_PL "
                             f"WHERE date > :a AND date <= :b{filtro}"), c, params={"a": INICIO, "b": D})
    return p, q


def categoria(a):
    a = str(a)
    if FUT.match(a):
        return "Derivativos"
    w = a.split()[0].upper() if a.split() else ""
    return next((c for c in CATEGORIAS if w == c.upper()), "Caixa" if re.search(r"(?i)caixa|cash|zeragem|compromiss|over", a) else "Outros")


def prepara(p, q):
    """Categoria de cada linha e pnl_com_hedge: o P&L de cada derivativo vai, no mesmo dia, para os ativos que ele protege,
    proporcional ao risco (%PL x duration; %PL para dólar)."""
    p = p.assign(date=pd.to_datetime(p.date), categoria=p.ativo.map(categoria))
    q = q.assign(date=pd.to_datetime(q.date), r=q.pnl_fundo_perc / ESCALA, b=q.pnl_benchmark_fundo_perc / ESCALA).sort_values("date")
    k = [p.codigo_IAM_fundo, p.date]
    idx = pd.MultiIndex.from_arrays(k)
    fut = p.categoria.eq("Derivativos")
    classe = p.ativo.str[:3].where(fut, "")
    p["pnl_com_hedge"] = p.pnl_total_perc.fillna(0)
    for cls, (alvo, dur) in HEDGE.items():
        h = p.pnl_total_perc.where(classe.eq(cls), 0).groupby(k).sum()
        w = (p.perc_nav.abs() * (p.macaulay_duration.fillna(0) if dur else 1)).where(~fut & alvo(p), 0)
        W = w.groupby(k).transform("sum")
        p["pnl_com_hedge"] += np.where(W > 0, h.reindex(idx).fillna(0).to_numpy() * w / W.where(W > 0, 1), 0)
        p.loc[classe.eq(cls) & (w.groupby(k).sum().reindex(idx).fillna(0).to_numpy() > 0), "pnl_com_hedge"] = 0
    return p, q


# ------------------------------------------------------------------ tabelas
def janelas(datas):
    """Períodos que o histórico do fundo cobre: {nome: data inicial}."""
    ini, out = datas.min(), {"5d": datas[-5] if len(datas) >= 5 else None, "Mês": datas[datas >= D.replace(day=1)].min()}
    for m in (6, 12, 24, 36):
        if ini <= D - pd.DateOffset(months=m):
            out[f"{m}m"] = datas[datas > D - pd.DateOffset(months=m)].min()
    if ini > D - pd.DateOffset(months=36) and ini not in out.values():
        out[f"Início ({ini:%d/%m/%y})"] = ini
    return {n: d for n, d in out.items() if pd.notna(d)}


def tabela1(q, jan):
    nomes = {"5d": "5 dias", "Mês": "No mês", "6m": "6 meses", "12m": "12 meses", "24m": "24 meses", "36m": "36 meses"}
    linhas = []
    for n, ini in jan.items():
        x = q[q.date >= ini]
        r, c = (1 + x.r).prod() - 1, (1 + x.b).prod() - 1
        linhas.append([nomes.get(n, n), r * 100, c * 100, r / c * 100, (((1 + r) / (1 + c)) ** (252 / len(x)) - 1) * 100])
    return pd.DataFrame(linhas, columns=["Período", "Fundo\n(%)", "CDI\n(%)", "% do\nCDI", "CDI +\n(% a.a.)"])


def tabela2(hoje):
    a = hoje[~hoje.categoria.eq("Derivativos")].assign(fin=lambda x: x.perc_nav / ESCALA * x.total_nav_moeda_fundo / 1e6)
    pond = lambda g, c: (g.perc_nav * g[c]).sum() / g.perc_nav.where(g[c].notna()).sum()
    linha = lambda n, g: [n, g.perc_nav.sum(), g.fin.sum(), pond(g, "spread_cdi"), pond(g, "macaulay_duration")]
    t = sorted((linha(n, g) for n, g in a.groupby("categoria")), key=lambda x: -x[1]) + [linha("Total", a)]
    return pd.DataFrame(t, columns=["Categoria", "%PL", "Financeiro\n(R$ mi)", "Spread CDI\n(%)", "Duration\n(anos)"])


def tabela_cdi(p, jan, hoje, col):
    """% do CDI por grupo: soma do pnl_com_hedge / soma do pnl_benchmark_perc das mesmas linhas."""
    a = p[~p.categoria.eq("Derivativos")]
    pl = hoje.groupby(col).perc_nav.sum().sort_values(ascending=False)
    out = pd.DataFrame(index=list(pl.index) + ["Total"])
    for n, ini in jan.items():
        x = a[a.date >= ini]
        g = x.groupby(col)[["pnl_com_hedge", "pnl_benchmark_perc"]].sum()
        out[n.split(" (")[0]] = pd.concat([g.pnl_com_hedge / g.pnl_benchmark_perc, pd.Series({"Total": x.pnl_com_hedge.sum() / x.pnl_benchmark_perc.sum()})]) * 100
    return out.rename_axis("Categoria" if col == "categoria" else "Setor").reset_index()


# ------------------------------------------------------------------ PDF: uma página A4 por fundo
#   [ Retorno x CDI          | Distribuição do % do CDI ]
#   [ Carteira por categoria | % do CDI acumulado        ]
#   [ Retorno por categoria  | Retorno por setor         ]
W, H, M, G = 8.27, 11.69, 0.4, 0.3
CW = (W - 2 * M - G) / 2
TIT, GAP = 0.3, 0.3


def br(x, d):
    return "–" if pd.isna(x) else f"{round(x, d) + 0:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def eixo(fig, x, y, w, h):
    return fig.add_axes([x / W, y / H, w / W, h / H])


def titulo(fig, x, y, txt, nota="", centro=False):
    fig.text((x + CW / 2 if centro else x) / W, y / H, txt, fontsize=10, fontweight="bold", color=AZUL, va="bottom",
             ha="center" if centro else "left")
    if nota:
        fig.text((x + CW) / W, y / H, nota, fontsize=6.5, color=CINZA, va="bottom", ha="right")


def tabela(fig, x, ytop, rh, df, txt, casas, nota="", total=False, cor_sinal=()):
    titulo(fig, x, ytop - TIT + 0.08, txt, nota)
    h = rh * (len(df) + 2)                                            # cabeçalho em duas linhas
    ax = eixo(fig, x, ytop - TIT - h, CW, h)
    ax.axis("off")
    cel = [[str(v) if j == 0 else br(v, casas[j]) for j, v in enumerate(r)] for r in df.itertuples(index=False)]
    t = ax.table(cellText=cel, colLabels=list(df.columns), bbox=[0, 0, 1, 1], cellLoc="right", colLoc="right",
                 colWidths=[0.28] + [0.72 / (df.shape[1] - 1)] * (df.shape[1] - 1))
    t.auto_set_font_size(False)
    for (i, j), c in t.get_celld().items():
        c.set_linewidth(0)
        c.PAD = 0.04
        c.set_height((2 if i == 0 else 1) / (len(df) + 2))
        c.set_text_props(fontsize=7.5, color=TEXTO, ha="left" if j == 0 else "right")
        if i == 0:
            c.set_facecolor(AZUL)
            c.set_text_props(color="white", fontweight="bold")
        elif total and i == len(df):
            c.set_facecolor("#FCD9B8")
            c.set_text_props(fontweight="bold", color=AZUL)
        else:
            c.set_facecolor(CLARO if i % 2 == 0 else "white")
        if i and j in cor_sinal and cel[i - 1][j].startswith("-"):
            c.get_text().set_color("#B42318")


def grafico_dist(ax, q):
    v = (q.r / q.b * 100).replace([np.inf, -np.inf], np.nan).dropna()
    lo, hi = np.percentile(v, [1, 99])
    ax.hist(v.clip(lo, hi), bins=int(np.clip(len(v) // 3, 8, 30)), color=AZUL_CLARO, edgecolor="white")
    ax.axvline(100, color=CINZA, ls="--", lw=1)
    hoje = np.clip(v.iloc[-1], lo, hi)
    ax.axvline(hoje, color=LARANJA, lw=2.2)
    ax.text(hoje, ax.get_ylim()[1] * 0.97, f" {br(v.iloc[-1], 0)}% ", color=LARANJA, fontsize=8.5, fontweight="bold",
            va="top", ha="left" if hoje < (lo + hi) / 2 else "right")
    ax.set(xlabel="% do CDI no dia", ylabel="dias")
    ax.yaxis.get_major_locator().set_params(integer=True)


def grafico_media(ax, q):
    m = q.groupby(q.date.dt.to_period("M"))[["r", "b"]].agg(lambda s: (1 + s).prod() - 1).iloc[-12:]
    pct = m.r / m.b * 100
    media = pct.expanding().mean()
    xs = np.arange(len(pct))
    ax.bar(xs, pct, color=AZUL_CLARO, width=0.7)
    ax.plot(xs, media, color=LARANJA, lw=2.2, marker="o", ms=3.5)
    ax.axhline(100, color=CINZA, ls="--", lw=1)
    ax.annotate(f"{br(media.iloc[-1], 0)}%", (xs[-1], media.iloc[-1]), xytext=(0, 7), textcoords="offset points",
                ha="center", color=LARANJA, fontweight="bold", fontsize=8.5)
    meses = "jan fev mar abr mai jun jul ago set out nov dez".split()
    ax.set_xticks(xs, [f"{meses[p.month - 1]}\n{p.year % 100}" for p in pct.index], fontsize=6.5)
    ax.set_ylim(max(0, min(pct.min(), media.min()) - 10), max(108, pct.max() + 8))
    ax.set_ylabel("% do CDI")
    return len(pct)


def pagina(pdf, f, sub, t1, t2, t3, t4, qf, hist):
    fig = plt.figure(figsize=(W, H))
    fig.patches += [plt.Rectangle((0, 1 - 0.65 / H), 1, 0.65 / H, transform=fig.transFigure, color=LARANJA),
                    plt.Rectangle((0, 1 - 0.69 / H), 1, 0.04 / H, transform=fig.transFigure, color=AZUL)]
    fig.text(M / W, 1 - 0.33 / H, f, color="white", fontsize=15, fontweight="bold", va="center")
    fig.text(1 - M / W, 1 - 0.33 / H, sub, color="white", fontsize=8.5, va="center", ha="right")
    topo, base = H - 0.95, 0.35
    linhas = lambda rh: [max(rh * (len(t1) + 2), 1.9), max(rh * (len(t2) + 2), 2.2), rh * (max(len(t3), len(t4)) + 2)]
    rh = 0.23
    while sum(linhas(rh)) + 3 * TIT + 2 * GAP > topo - base and rh > 0.12:   # encolhe as linhas até caber
        rh -= 0.005
    h1, h2, _ = linhas(rh)
    xd, y = M + CW + G, topo
    tabela(fig, M, y, rh, t1, "Retorno x CDI", [0, 2, 2, 0, 2], hist, cor_sinal=(1, 4))
    titulo(fig, xd, y - TIT + 0.08, "Retorno diário em % do CDI", centro=True)
    a1 = eixo(fig, xd + 0.35, y - TIT - h1 + 0.35, CW - 0.35, h1 - 0.35)
    grafico_dist(a1, qf)
    y -= TIT + h1 + GAP
    tabela(fig, M, y, rh, t2, "Carteira por categoria", [0, 1, 1, 2, 1], total=True)
    a2 = eixo(fig, xd + 0.35, y - TIT - h2 + 0.3, CW - 0.35, h2 - 0.3)
    titulo(fig, xd, y - TIT + 0.08, f"% do CDI acumulado · {grafico_media(a2, qf)} meses", centro=True)
    y -= TIT + h2 + GAP
    for x, t, n in [(M, t3, "Retorno por categoria"), (xd, t4, "Retorno por setor")]:
        tabela(fig, x, y, rh, t, n, [0] * t.shape[1], "% do CDI, com derivativos", True, range(1, t.shape[1]))
    for a in (a1, a2):
        a.tick_params(labelsize=7)
        a.xaxis.label.set_size(7.5)
        a.yaxis.label.set_size(7.5)
    pdf.savefig(fig)
    plt.close(fig)


def relatorio(p, q, saida):
    with PdfPages(saida) as pdf:
        for f, qf in q[q.date <= D].groupby("codigo_IAM_fundo"):
            pf = p[(p.codigo_IAM_fundo == f) & (p.date <= D)]
            if pf.empty:
                continue
            hoje = pf[pf.date == pf.date.max()]
            hoje = hoje[~hoje.categoria.eq("Derivativos")]
            jan = janelas(pd.DatetimeIndex(qf.date))
            ini = qf.date.min()
            hist = "" if ini <= INICIO + pd.Timedelta(days=7) else f"desde {ini:%d/%m/%Y}"
            sub = f"Posição de {pf.date.max():%d/%m/%Y}  ·  PL R$ {br(hoje.total_nav_moeda_fundo.iloc[0] / 1e6, 1)} mi"
            pagina(pdf, f, sub, tabela1(qf, jan), tabela2(hoje), tabela_cdi(pf, jan, hoje, "categoria"),
                   tabela_cdi(pf, jan, hoje, "setor_iam"), qf, hist)


# ------------------------------------------------------------------ Excel de conferência (últimos 5 dias)
def excel(p, q, saida):
    dias = sorted(q.date[q.date <= D].unique())[-5:]
    e = p[p.date.isin(dias)].assign(
        hedge_alocado=lambda x: x.pnl_com_hedge - x.pnl_total_perc.fillna(0),
        financeiro_mi=lambda x: x.perc_nav / ESCALA * x.total_nav_moeda_fundo / 1e6,
        pl_com_spread=lambda x: x.perc_nav.where(x.spread_cdi.notna()), spread_x_pl=lambda x: x.perc_nav * x.spread_cdi,
        pl_com_duration=lambda x: x.perc_nav.where(x.macaulay_duration.notna()), duration_x_pl=lambda x: x.perc_nav * x.macaulay_duration)
    c = q[q.date.isin(dias)].assign(ln_fundo=lambda x: np.log1p(x.r), ln_cdi=lambda x: np.log1p(x.b)).drop(columns=["r", "b"])
    fundos = sorted(c.codigo_IAM_fundo.unique())
    ult = e.groupby("codigo_IAM_fundo").date.max()
    grupos = lambda col: [(f, g) for f in fundos if f in ult.index for g in
                          list(e[(e.codigo_IAM_fundo == f) & (e.date == ult[f]) & ~e.categoria.eq("Derivativos")][col].dropna().unique()) + ["Total"]]
    filtro = lambda col, g, r: (f'Explodida[{col}],B{r}' if g != "Total" else 'Explodida[categoria],"<>Derivativos"')
    soma = lambda campo, col, g, r, data="": f"SUMIFS(Explodida[{campo}],Explodida[codigo_IAM_fundo],A{r},{data}{filtro(col, g, r)})"

    t1 = pd.DataFrame([[f, f"=COUNTIFS(Cotas[codigo_IAM_fundo],A{r})",
                        f"=(EXP(SUMIFS(Cotas[ln_fundo],Cotas[codigo_IAM_fundo],A{r}))-1)*100",
                        f"=(EXP(SUMIFS(Cotas[ln_cdi],Cotas[codigo_IAM_fundo],A{r}))-1)*100",
                        f"=C{r}/D{r}*100", f"=(((1+C{r}/100)/(1+D{r}/100))^(252/B{r})-1)*100"] for r, f in enumerate(fundos, 2)],
                      columns=["fundo", "dias", "fundo_pct", "cdi_pct", "pct_cdi", "cdi_mais_aa"])
    dt = lambda r: f"Explodida[date],C{r},"
    t2 = pd.DataFrame([[f, g, ult[f]] + [f"={soma(x, 'categoria', g, r, dt(r))}" for x in ("perc_nav", "financeiro_mi")] +
                       [f'=IFERROR({soma(a, "categoria", g, r, dt(r))}/{soma(b, "categoria", g, r, dt(r))},"")'
                        for a, b in (("spread_x_pl", "pl_com_spread"), ("duration_x_pl", "pl_com_duration"))]
                       for r, (f, g) in enumerate(grupos("categoria"), 2)],
                      columns=["fundo", "categoria", "data", "pl", "financeiro_mi", "spread_cdi", "duration_anos"])
    t34 = {col: pd.DataFrame([[f, g, f"={soma('pnl_com_hedge', col, g, r)}", f"={soma('pnl_benchmark_perc', col, g, r)}",
                               f'=IFERROR(C{r}/D{r}*100,"")'] for r, (f, g) in enumerate(grupos(col), 2)],
                             columns=["fundo", col, "pnl_com_hedge", "pnl_benchmark", "pct_cdi"]) for col in ("categoria", "setor_iam")}
    conf = pd.DataFrame([[f, d, f"=SUMIFS(Explodida[pnl_total_perc],Explodida[codigo_IAM_fundo],H{r},Explodida[date],I{r})",
                          f"=SUMIFS(Cotas[pnl_fundo_perc],Cotas[codigo_IAM_fundo],H{r},Cotas[date],I{r})", f"=J{r}-K{r}"]
                         for r, (f, d) in enumerate([(f, d) for f in fundos for d in dias], 2)],
                        columns=["fundo", "data", "pnl_explodida", "pnl_cotas_pl", "diferenca"])

    with pd.ExcelWriter(saida, engine="xlsxwriter", datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy") as xw:
        def aba(df, folha, nome, col=0):
            df.to_excel(xw, sheet_name=folha, index=False, startcol=col)
            ws = xw.sheets[folha]
            ws.add_table(0, col, len(df), col + df.shape[1] - 1,
                         {"name": nome, "style": "Table Style Medium 7", "columns": [{"header": h} for h in df.columns]})
            ws.set_column(col, col + df.shape[1] - 1, 16)
        aba(e, "explodida_down", "Explodida")
        aba(c, "cotas_pl", "Cotas")
        aba(t1, "tabela1_retorno", "Retorno")
        aba(t2, "tabela2_carteira", "Carteira")
        aba(t34["categoria"], "tabela3_categoria", "PorCategoria")
        aba(conf, "tabela3_categoria", "Conferencia", col=7)
        aba(t34["setor_iam"], "tabela4_setor", "PorSetor")


if __name__ == "__main__":
    p, q = prepara(*le_banco())
    relatorio(p, q, f"relatorio_fundos_{D:%Y%m%d}.pdf")
    excel(p, q, f"conferencia_fundos_{D:%Y%m%d}.xlsx")
