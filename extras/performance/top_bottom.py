"""
Top 15 / Bottom 15 contribuições de PnL (hedgeado) por fundo -> PDF (1 página por fundo) + Excel.
Uso:  python top_bottom.py 2026-10-01 2026-10-06
"""
import os, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from performance import (FUNDOS, FORA, NAVY, LARANJA, COLS_BASE, FORMULAS_BASE, carrega_posicoes, br,
                         desenha_tabela, formatos, tabela_excel, escreve_df)

# ============================== CONFIG ==============================
# FUNDOS vem do performance.py (edite lá). Para usar outra lista só aqui:
# FUNDOS = {"FICFI54347": "Dual"}
N = 15
PASTA_SAIDA = "saida_top_bottom"
# ====================================================================

COLUNAS = {"ticker_venc": "Código do ativo", "categoria": "Categoria", "grupo_economico_iam": "Grupo econômico",
           "subsetor_iam": "Subsetor", "bruto": "PnL bruto (bps)", "hedge": "PnL hedge + câmbio (bps)",
           "total": "PnL total (bps)", "financeiro": "Financeiro (mm)"}


def ranking(pos, cod):
    """Contribuição composta por ticker_venc no período. Hedges e Outros ficam fora (já alocados)."""
    p = pos[(pos.codigo_IAM_fundo == cod) & ~pos.categoria.isin(FORA)]
    dia = p.groupby(["ticker_venc", "date"])[["pnl_total_perc", "PnL Hedgeado"]].sum()
    out = np.expm1(np.log1p(dia).groupby(level=0).sum()).rename(columns={"pnl_total_perc": "bruto",
                                                                         "PnL Hedgeado": "total"})
    out["hedge"] = out.total - out.bruto
    out[["bruto", "hedge", "total"]] *= 1e4
    info = p.sort_values("date").groupby("ticker_venc")[["categoria", "grupo_economico_iam", "subsetor_iam"]].last()
    fim = p[p.date == p.date.max()]
    fin = fim.total_nav_moeda_fundo.groupby(fim.ticker_venc).sum() / 1e6
    out = out.join(info).join(fin.rename("financeiro")).fillna({"financeiro": 0}).reset_index()
    out = out[list(COLUNAS)].fillna("n.a.")
    top = out[out.total > 0].nlargest(N, "total").reset_index(drop=True)
    bot = out[out.total < 0].nsmallest(N, "total").reset_index(drop=True)
    return top, bot


def texto(df):
    t = df.rename(columns=COLUNAS)
    for c in ["PnL bruto (bps)", "PnL hedge + câmbio (bps)", "PnL total (bps)", "Financeiro (mm)"]:
        t[c] = t[c].map(br)
    t.insert(0, "#", range(1, len(t) + 1))
    return t


def pagina_pdf(pdf, nome, ini, fim, top, bot):
    fig = plt.figure(figsize=(16.5, 11.7))
    fig.text(0.04, 0.955, f"{nome} - Período: {ini:%d/%m/%Y} a {fim:%d/%m/%Y}", fontsize=18, fontweight="bold",
             color=NAVY)
    fig.add_artist(plt.Line2D([0.04, 0.96], [0.94, 0.94], color=LARANJA, lw=1.5))
    for df, eixo, titulo in [(top, [0.04, 0.50, 0.92, 0.40], f"Top {N} contribuições positivas"),
                             (bot, [0.04, 0.04, 0.92, 0.40], f"Bottom {N} contribuições")]:
        ax = fig.add_axes(eixo)
        soma = f"   |   soma: {br(df.total.sum())} bps" if len(df) else "   |   sem ativos"
        tot = list(COLUNAS).index("total") + 1
        cores = {(i + 1, tot): ("#F4F4F4" if (i + 1) % 2 == 0 else "white", "red") for i in range(len(df))} \
            if df is bot else None
        if len(df):
            desenha_tabela(ax, texto(df), titulo + soma, cores, fonte=8)
        else:
            ax.axis("off")
            ax.set_title(titulo + soma, loc="left", fontsize=10, fontweight="bold", color=NAVY)
    pdf.savefig(fig)
    plt.close(fig)


def main():
    if len(sys.argv) < 3:
        sys.exit("Uso: python top_bottom.py <data_ini> <data_fim>   ex: python top_bottom.py 2026-10-01 2026-10-06")
    ini, fim = [pd.to_datetime(a, dayfirst="/" in a) for a in sys.argv[1:3]]
    print(f"Período {ini:%d/%m/%Y} a {fim:%d/%m/%Y} | carregando posições...")
    pos = carrega_posicoes(FUNDOS, ini, fim)

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    arq = os.path.join(PASTA_SAIDA, f"top_bottom_{ini:%Y%m%d}_{fim:%Y%m%d}")
    fmts = {"PnL bruto (bps)": "num2", "PnL hedge + câmbio (bps)": "num2", "PnL total (bps)": "num2",
            "Financeiro (mm)": "num2"}
    with PdfPages(arq + ".pdf") as pdf, pd.ExcelWriter(arq + ".xlsx", engine="xlsxwriter") as xw:
        wb = xw.book
        F = formatos(wb)
        for cod, nome in FUNDOS.items():
            if not (pos.codigo_IAM_fundo == cod).any():
                print(f"  {nome}: sem posições, pulando")
                continue
            top, bot = ranking(pos, cod)
            pagina_pdf(pdf, nome, ini, fim, top, bot)
            ws = wb.add_worksheet(nome[:31])
            ws.set_column(0, 8, 18)
            ws.write(0, 0, f"{nome} - Período: {ini:%d/%m/%Y} a {fim:%d/%m/%Y}", F["titulo"])
            r = escreve_df(ws, 2, 0, top.rename(columns=COLUNAS), fmts, F,
                           f"Top {N} contribuições positivas | soma: {br(top.total.sum())} bps")
            escreve_df(ws, r, 0, bot.rename(columns=COLUNAS), fmts, F,
                       f"Bottom {N} contribuições | soma: {br(bot.total.sum())} bps")
            print(f"  {nome} ok")
        tabela_excel(wb, "base", pos[COLS_BASE], FORMULAS_BASE, F)
    print(f"Gerado: {arq}.pdf / .xlsx")


if __name__ == "__main__":
    main()
