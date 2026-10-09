"""
Relatório dos fundos na data de ontem (hoje - 1 dia útil):
  PDF, uma página por fundo: retorno x CDI, carteira por categoria, retorno por categoria e por setor em % do CDI
       (hedges e câmbio realocados para os ativos que protegem), distribuição do % do CDI diário e % do CDI acumulado.
  Excel de conferência, últimos 5 dias: base com as colunas de cálculo + as 4 tabelas em fórmulas simples + invariantes.
Uso: python relatorio_fundos.py
"""
import matplotlib
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

CONEXAO = "mssql+pyodbc://SERVIDOR/BANCO?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
NOMES = {"FICFI54347": "Dual", "FICFI58573": "Dual Global", "FICFI57848": "Dual Prev", "FLEFIM59015": "Dual Prev Dist",
         "FICFI56462": "Prev", "ITADFIM57826": "Prev BB", "FICFI54079": "Precision", "FUJIFI59181": "Fuji", "GDRFMOPP_CCI": "GD RF",
         "RPGD_MOPP_CCI": "GD RF Flexprev", "MPGD_MOPPHF_CCI": "GD MM Flexprev", "MOPPHFGD_CCI": "GD MM", "ULMOPPHF_CCI": "GD MM Ultra"}
INTERNOS = ["ADFIM54217", "DOLOMITAS2", "ITAUTITLISSEN", "ZERARF54582", "VERTIOFF53940", "ITADFIM56470", "VERFIM58509", "FLEFIM59015",
            "ITADFIM57826", "ESP_MOPPGDULT", "MOGD_MOPPHF_CCI", "FLEXPREVDI1928", "FICFI57848", "ESP_MOPPGD", "MOPPHFGD_CCI", "ESP_OPPITUB",
            "INITAUPIRIIMEZ", "ITDOLOMITASUB", "ITFIM57865", "ITDFIM57862", "WEALTHMAS53004", "PIRINEUIIIMEZ", "FICFI54079", "FICFI54347",
            "DOLOMITASSUB", "FUJIFI59181", "ROGD_MOPP_CCI", "ESP_GDFIMOPP", "SUBDOLOMITAS2", "RPGD_MOPP_CCI", "PIRINEUSIISUB", "FICFI56462",
            "FICFI58573", "GDRFMOPP_CCI", "MPGD_MOPPHF_CCI", "ULMOPPHF_CCI", "INITAUPIRIISUB", "ITDOLOMITSUB"]
BENCH = "benchmark_pnl_moeda_ativo_perc"
DIAS_ANO = 252                 # macaulay_duration vem em dias úteis
HEDGES = ["Hedge USD", "Hedge Bonds", "Hedge IPCA", "Hedge Pre"]
D = pd.Timestamp.today().normalize() - pd.offsets.BDay(1)
INICIO = D - pd.DateOffset(months=36)
LARANJA, AZUL, TEXTO, CINZA, CLARO, AZUL_CLARO = "#EC7000", "#003399", "#2B2B2B", "#8C8C8C", "#FFF4EA", "#BFCDEB"
plt.rcParams.update({"font.family": ["Segoe UI", "Arial", "DejaVu Sans"], "font.size": 8.5, "axes.edgecolor": CINZA,
                     "axes.spines.top": False, "axes.spines.right": False, "xtick.color": TEXTO, "ytick.color": TEXTO})


# ------------------------------------------------------------------ dados
def le_banco():
    fundos = ",".join(f"'{f}'" for f in NOMES)
    pos = ("SELECT date, codigo_IAM_fundo, codigo_IAM_fundo_origem, codigo_IAM_ativo, ativo, tipo, indexador, moeda_ativo, perc_nav, "
           f"pnl_total_perc, pnl_cambio_explosao_perc, count_cambio, {BENCH}, total_nav_moeda_fundo, setor_iam, spread_cdi, macaulay_duration "
           f"FROM {{}} WHERE date > :a AND date <= :b AND codigo_IAM_fundo IN ({fundos})")
    corte = D - pd.DateOffset(months=6)
    with create_engine(CONEXAO).connect() as c:
        p = pd.concat([pd.read_sql(text(pos.format("VW_FUNDOS_POSICAO_EXPLODIDA_DOWN")), c, params={"a": corte, "b": D}),
                       pd.read_sql(text(pos.format("VW_FUNDOS_POSICAO_EXPLODIDA_DOWN_HIST")), c, params={"a": INICIO, "b": corte})])
        q = pd.read_sql(text("SELECT codigo_IAM_fundo, date, pnl_fundo_perc, pnl_benchmark_fundo_perc FROM VIEW_FUNDOS_COTAS_PL "
                             f"WHERE date > :a AND date <= :b AND codigo_IAM_fundo IN ({fundos})"), c, params={"a": INICIO, "b": D})
    return p, q


def categoria(p):
    """Mesma ordem de regras do PADRAO.sql (CaixaCPR vira Cash antes de Bonds)."""
    a, cod = p.ativo, p.codigo_IAM_ativo
    regras = [(a.isin(["Future Cupom Cambial", "Future FX", "FX Spot"]), "Hedge USD"),
              (p.tipo.eq("CaixaCPR") & cod.ne("CaixaCPROutros"), "Cash"),
              (a.isin(["Bonds", "Bond Collateral"]), "Bonds"), (a.isin(["DEB", "DEBIT"]), "DEB"), (a.eq("Bond Swap"), "Hedge Bonds"),
              (a.eq("Future CPI"), "Hedge IPCA"), (a.eq("Future Interest Rate"), "Hedge Pre"), (a.eq("PL Cota Senior"), "FIDC"),
              (a.isin(["LFT", "Overnight", "Itaú Zeragem", "Cash"]), "Cash"),
              (p.tipo.eq("Despesa") | cod.eq("CaixaCPROutros") | a.eq("CPR Resgate"), "Outros"), (cod.isin(INTERNOS), "FIDC")]
    return pd.Series(np.select([r for r, _ in regras], [c for _, c in regras], default=None), index=p.index).fillna(a)


def prepara(p, q):
    """Realocação que não muda o total do fundo (por fundo e dia):
      livro USD: N = %PL líquido do caixa em USD; recebem Bonds com %PL > 0 e caixa USD só se N > 0;
                 peso_fx = perc_nav / (Bonds positivos + max(N, 0)). Câmbio total do dia e hedges USD/Bonds vão por peso_fx.
      Hedge IPCA / Hedge Pre: para ativos em BRL com indexador IPCA+ / PRE, pelo %PL.
      Linhas de hedge zeradas quando o pool teve quem recebesse. Cotas duplicadas (fundo já explodido) são retiradas."""
    p = p.assign(date=pd.to_datetime(p.date), perc_nav=p.perc_nav.fillna(0), pnl_total_perc=p.pnl_total_perc.fillna(0))
    k = ["codigo_IAM_fundo", "date"]
    origens = set(zip(p.codigo_IAM_fundo, p.date, p.codigo_IAM_fundo_origem))
    dup = pd.Series([(f, d, a) in origens for f, d, a in zip(p.codigo_IAM_fundo, p.date, p.codigo_IAM_ativo)], index=p.index)
    p = p[~dup | p.codigo_IAM_ativo.eq(p.codigo_IAM_fundo_origem)].copy()
    p["categoria"] = categoria(p)
    p.loc[p.tipo.eq("Future"), "indexador"] = None
    idx = p.indexador.fillna("").str.upper().str.replace("+", "", regex=False).str.strip()
    brl, hedge = p.moeda_ativo.fillna("BRL").eq("BRL"), p.categoria.isin(HEDGES)
    usd_cash = p.categoria.eq("Cash") & p.moeda_ativo.eq("USD")
    g = lambda s: s.groupby([p[c] for c in k]).transform("sum")
    N = g(p.perc_nav.where(usd_cash, 0))
    B = g(p.perc_nav.where(p.categoria.eq("Bonds") & (p.perc_nav > 0), 0))
    recebe = (p.categoria.eq("Bonds") & (p.perc_nav > 0)) | (usd_cash & (N > 0))
    den = B + N.clip(lower=0)
    p["peso_fx"] = np.where(recebe & (den > 0), p.perc_nav / den.where(den > 0, 1), 0)
    flag = p.count_cambio.eq(1) if "count_cambio" in p else ~p.duplicated(k)
    p["cambio_linha"] = p.pnl_cambio_explosao_perc.where(flag, 0).fillna(0)       # a única linha de câmbio por fundo e dia
    p["cambio_total"] = g(p.cambio_linha)
    p["fx_alocado"] = p.peso_fx * p.cambio_total
    p["pnl_hedge_usd"] = p.peso_fx * g(p.pnl_total_perc.where(p.categoria.isin(["Hedge USD", "Hedge Bonds"]), 0))
    for nome, cat, ix in (("pnl_hedge_ipca", "Hedge IPCA", "IPCA"), ("pnl_hedge_pre", "Hedge Pre", "PRE")):
        alvo = brl & ~hedge & idx.eq(ix)
        w = g(p.perc_nav.where(alvo, 0))
        p[nome] = np.where(alvo & (w != 0), p.perc_nav / w.where(w != 0, 1), 0) * g(p.pnl_total_perc.where(p.categoria.eq(cat), 0))
        p[f"_rec_{cat}"] = w != 0
    p["_rec_Hedge USD"] = p["_rec_Hedge Bonds"] = den > 0
    zera = pd.Series(False, index=p.index)
    for cat in HEDGES:
        zera |= p.categoria.eq(cat) & p[f"_rec_{cat}"]
    p["pnl_hedgeado"] = np.where(zera, 0, p.pnl_total_perc + p.pnl_hedge_ipca + p.pnl_hedge_pre + p.pnl_hedge_usd + p.fx_alocado)
    p = p.drop(columns=[c for c in p if c.startswith("_rec_")])
    q = q.assign(date=pd.to_datetime(q.date), r=q.pnl_fundo_perc, b=q.pnl_benchmark_fundo_perc).sort_values("date")
    p = p.merge(q[k + ["b"]].rename(columns={"b": "cdi_dia"}), on=k, how="left")
    p["pnl_cdi_ativo"] = p.cdi_dia * p.perc_nav
    p["dur"] = p.macaulay_duration / DIAS_ANO
    p["eh_ativo"] = (~p.categoria.isin(HEDGES + ["Outros"])).astype(int)
    return p, q


def invariantes(p, q):
    """Por fundo e dia: realocado = bruto (nenhum pool sem destino), bruto ≈ cota oficial, soma do %PL ≈ 100%."""
    k = ["codigo_IAM_fundo", "date"]
    x = p.groupby(k).agg(realocado=("pnl_hedgeado", "sum"), pnl=("pnl_total_perc", "sum"), cambio=("cambio_total", "first"),
                         pl=("perc_nav", "sum")).reset_index()
    x = x.merge(q[k + ["r"]], on=k, how="left").assign(bruto=lambda d: d.pnl + d.cambio)
    return x.assign(sem_destino=x.realocado - x.bruto, vs_cota=x.bruto - x.r)


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
    a = hoje.assign(fin=lambda x: x.perc_nav * x.total_nav_moeda_fundo / 1e6)
    pond = lambda g, c: (g.perc_nav * g[c]).sum() / g.perc_nav.where(g[c].notna()).sum()
    linha = lambda n, g: [n, g.perc_nav.sum() * 100, g.fin.sum(), pond(g, "spread_cdi"), pond(g, "dur")]
    t = sorted((linha(n, g) for n, g in a.groupby("categoria")), key=lambda x: -x[1]) + [linha("Total", a)]
    return pd.DataFrame(t, columns=["Categoria", "%PL", "Financeiro\n(R$ mi)", "Spread CDI\n(%)", "Duration\n(anos)"])


def tabela_cdi(p, jan, hoje, col):
    """% do CDI por grupo = P&L composto do grupo / CDI composto do grupo (nunca média de razões).
    Linhas: grupos presentes na data; Total: todas as linhas do fundo (inclui Outros e hedges sem destino)."""
    pl = hoje.groupby(col).perc_nav.sum().sort_values(ascending=False)
    out = pd.DataFrame(index=list(pl.index) + ["Total"])
    comp = lambda s: (1 + s).prod() - 1
    for n, ini in jan.items():
        x = p[p.date >= ini]
        dia = x.groupby([col, "date"])[["pnl_hedgeado", "pnl_cdi_ativo"]].sum().groupby(level=0).agg(comp)
        tot = x.groupby("date")[["pnl_hedgeado", "pnl_cdi_ativo"]].sum().agg(comp)
        dia.loc["Total"] = tot
        out[n.split(" (")[0]] = (dia.pnl_hedgeado / dia.pnl_cdi_ativo.where(dia.pnl_cdi_ativo > 0)).reindex(out.index) * 100
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
            hoje = pf[(pf.date == pf.date.max()) & pf.eh_ativo.eq(1)]
            jan = janelas(pd.DatetimeIndex(qf.date))
            ini = qf.date.min()
            hist = "" if ini <= INICIO + pd.Timedelta(days=7) else f"desde {ini:%d/%m/%Y}"
            sub = f"Posição de {pf.date.max():%d/%m/%Y}  ·  PL R$ {br(pf.total_nav_moeda_fundo.iloc[-1] / 1e6, 1)} mi"
            pagina(pdf, NOMES.get(f, f), sub, tabela1(qf, jan), tabela2(hoje), tabela_cdi(pf, jan, hoje, "categoria"),
                   tabela_cdi(pf, jan, hoje, "setor_iam"), qf, hist)


# ------------------------------------------------------------------ Excel de conferência (últimos 5 dias)
def excel(p, q, saida):
    dias = sorted(q.date[q.date <= D].unique())[-5:]
    cols = ["date", "codigo_IAM_fundo", "codigo_IAM_fundo_origem", "codigo_IAM_ativo", "ativo", "tipo", "categoria", "indexador",
            "moeda_ativo", "setor_iam", "perc_nav", "total_nav_moeda_fundo", "spread_cdi", "dur", "pnl_total_perc", "cambio_linha",
            "peso_fx", "fx_alocado", "pnl_hedge_usd", "pnl_hedge_ipca", "pnl_hedge_pre", "pnl_hedgeado", "cdi_dia", "pnl_cdi_ativo", "eh_ativo"]
    e = p[p.date.isin(dias)][cols].assign(financeiro_mi=lambda x: x.perc_nav * x.total_nav_moeda_fundo / 1e6,
                                         spread_x_pl=lambda x: x.perc_nav * x.spread_cdi, duration_x_pl=lambda x: x.perc_nav * x.dur)
    e["setor_iam"] = e.setor_iam.fillna("-")
    c = q[q.date.isin(dias)][["codigo_IAM_fundo", "date", "pnl_fundo_perc", "pnl_benchmark_fundo_perc"]].assign(
        ln_fundo=lambda x: np.log1p(x.pnl_fundo_perc), ln_cdi=lambda x: np.log1p(x.pnl_benchmark_fundo_perc))
    fundos = sorted(c.codigo_IAM_fundo.unique())
    ult = e.groupby("codigo_IAM_fundo").date.max()
    L = lambda i: "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[i]                                # letra da coluna (0 = A)
    S = lambda campo, *f: f"SUMIFS(Base[{campo}]," + ",".join(f) + ")"

    t1 = pd.DataFrame([[f, f"=COUNTIFS(Cotas[codigo_IAM_fundo],A{r})", f"=(EXP(SUMIFS(Cotas[ln_fundo],Cotas[codigo_IAM_fundo],A{r}))-1)*100",
                        f"=(EXP(SUMIFS(Cotas[ln_cdi],Cotas[codigo_IAM_fundo],A{r}))-1)*100", f"=C{r}/D{r}*100",
                        f"=(((1+C{r}/100)/(1+D{r}/100))^(252/B{r})-1)*100"] for r, f in enumerate(fundos, 2)],
                      columns=["fundo", "dias", "fundo_pct", "cdi_pct", "pct_cdi", "cdi_mais_aa"])
    g2 = [(f, g) for f in fundos if f in ult.index
          for g in list(e[(e.codigo_IAM_fundo == f) & (e.date == ult[f]) & e.eh_ativo.eq(1)].categoria.unique()) + ["Total"]]
    filt = lambda g, r: [f"Base[codigo_IAM_fundo],A{r}", f"Base[date],C{r}", "Base[eh_ativo],1"] + ([f"Base[categoria],B{r}"] if g != "Total" else [])
    t2 = pd.DataFrame([[f, g, ult[f], f"={S('perc_nav', *filt(g, r))}*100", f"={S('financeiro_mi', *filt(g, r))}",
                        f'=IFERROR({S("spread_x_pl", *filt(g, r))}/{S("perc_nav", *filt(g, r))},"")',
                        f'=IFERROR({S("duration_x_pl", *filt(g, r))}/{S("perc_nav", *filt(g, r))},"")'] for r, (f, g) in enumerate(g2, 2)],
                      columns=["fundo", "categoria", "data", "pl", "financeiro_mi", "spread_cdi", "duration_anos"])

    def por_grupo(col, nome):
        """Duas tabelas: diária (SUMIFS + LN) e a de 5 dias (EXP da soma dos LN, depois divide)."""
        grupos = [(f, g) for f in fundos if f in ult.index
                  for g in list(e[(e.codigo_IAM_fundo == f) & (e.date == ult[f]) & e.eh_ativo.eq(1)][col].unique()) + ["Total"]]
        dia = pd.DataFrame([(f, g, d) for f, g in grupos for d in dias], columns=["fundo", col, "data"])
        A, B, C, Dc, E = (L(7 + i) for i in range(5))                            # a tabela diária começa na coluna H
        fd = lambda r: [f"Base[codigo_IAM_fundo],{A}{r}", f"Base[date],{C}{r}"]
        for campo, out in (("pnl_hedgeado", "pnl"), ("pnl_cdi_ativo", "cdi")):
            dia[out] = [f"={S(campo, *fd(r), *([f'Base[{col}],{B}{r}'] if g != 'Total' else []))}" for r, g in enumerate(dia[col], 2)]
        dia["ln_pnl"] = [f"=LN(1+{Dc}{r})" for r in range(2, len(dia) + 2)]
        dia["ln_cdi"] = [f"=LN(1+{E}{r})" for r in range(2, len(dia) + 2)]
        t = pd.DataFrame([[f, g, f"=EXP(SUMIFS({nome}Dia[ln_pnl],{nome}Dia[fundo],A{r},{nome}Dia[{col}],B{r}))-1",
                           f"=EXP(SUMIFS({nome}Dia[ln_cdi],{nome}Dia[fundo],A{r},{nome}Dia[{col}],B{r}))-1", f'=IF(D{r}>0,C{r}/D{r}*100,"")']
                          for r, (f, g) in enumerate(grupos, 2)], columns=["fundo", col, "pnl_5d", "cdi_5d", "pct_cdi"])
        return t, dia

    t3, d3 = por_grupo("categoria", "Cat")
    t4, d4 = por_grupo("setor_iam", "Setor")
    conf = pd.DataFrame([[f, d] for f in fundos for d in dias], columns=["fundo", "data"])
    A, B, C, Dc, E = (L(17 + i) for i in range(5))                                # a conferência começa na coluna R
    fd = lambda r: [f"Base[codigo_IAM_fundo],{A}{r}", f"Base[date],{B}{r}"]
    conf["pnl_realocado"] = [f"={S('pnl_hedgeado', *fd(r))}" for r in range(2, len(conf) + 2)]
    conf["pnl_bruto"] = [f"={S('pnl_total_perc', *fd(r))}+{S('cambio_linha', *fd(r))}" for r in range(2, len(conf) + 2)]
    conf["pnl_cota_oficial"] = [f"=SUMIFS(Cotas[pnl_fundo_perc],Cotas[codigo_IAM_fundo],{A}{r},Cotas[date],{B}{r})" for r in range(2, len(conf) + 2)]
    conf["sem_destino"] = [f"={C}{r}-{Dc}{r}" for r in range(2, len(conf) + 2)]
    conf["bruto_vs_cota"] = [f"={Dc}{r}-{E}{r}" for r in range(2, len(conf) + 2)]
    conf["soma_pl"] = [f"={S('perc_nav', *fd(r))}" for r in range(2, len(conf) + 2)]

    with pd.ExcelWriter(saida, engine="xlsxwriter", datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy") as xw:
        def aba(df, folha, nome, col=0):
            df.to_excel(xw, sheet_name=folha, index=False, startcol=col)
            ws = xw.sheets[folha]
            ws.add_table(0, col, len(df), col + df.shape[1] - 1,
                         {"name": nome, "style": "Table Style Medium 7", "columns": [{"header": h} for h in df.columns]})
            ws.set_column(col, col + df.shape[1] - 1, 15)
        aba(e, "base", "Base")
        aba(c, "cotas_pl", "Cotas")
        aba(t1, "tabela1_retorno", "Retorno")
        aba(t2, "tabela2_carteira", "Carteira")
        aba(t3, "tabela3_categoria", "PorCategoria")
        aba(d3, "tabela3_categoria", "CatDia", col=7)
        aba(conf, "tabela3_categoria", "Conferencia", col=17)
        aba(t4, "tabela4_setor", "PorSetor")
        aba(d4, "tabela4_setor", "SetorDia", col=7)


if __name__ == "__main__":
    p, q = prepara(*le_banco())
    inv = invariantes(p, q)
    print("pior P&L sem destino (pp):", round(inv.sem_destino.abs().max() * 100, 4), "| pior diferença vs cota (pp):",
          round(inv.vs_cota.abs().max() * 100, 4), "| %PL fora de 95-105%:", int((~inv.pl.between(.95, 1.05)).sum()), "dias")
    relatorio(p, q, f"relatorio_fundos_{D:%Y%m%d}.pdf")
    excel(p, q, f"conferencia_fundos_{D:%Y%m%d}.xlsx")
