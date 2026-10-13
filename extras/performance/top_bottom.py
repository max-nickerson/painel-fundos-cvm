"""
Top 15 / Bottom 15 contribuições de PnL (hedgeado) por fundo -> PDF (1 página por fundo) + Excel.
Excel: só a base é dado (como vem do SQL); o ranking e tudo o mais são fórmulas.
Uso:  python top_bottom.py 2026-10-01 2026-10-06   [--sem-cache | --limpa-cache]  (mesmo cache do performance.py)
"""
import os, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from performance import (FUNDOS, FORA, NAVY, LARANJA, COLS_BASE, FORMULAS_BASE, FORMULAS_PERF, _ID, carrega_posicoes,
                         br, desenha_tabela, formatos, tabela_excel)

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


_TK = f"{_ID},base[ticker_venc],[@ticker_venc],base[eh_ativo],1"
_ATE_O_FIM = lambda c: f"[@{c}]:INDEX(base[{c}],ROWS(base[{c}]))"            # desta linha até o fim da tabela
# por ativo (ticker_venc): retorno composto no período, rateado pelas linhas do ativo em cada dia; a ÚLTIMA linha
# de cada (fundo, ativo) carrega o total, e as colunas rank_* permitem pegar o maior/menor com AGGREGATE
FORMULAS_TB = [
    FORMULAS_PERF[0],                                                       # eh_ativo
    ("n_tk", f"IF([@eh_ativo]=0,0,COUNTIFS({_TK}))"),
    ("ln_total", f"IF([@n_tk]=0,0,LN(1+SUMIFS(base[PnL Hedgeado],{_TK}))/[@n_tk])"),
    ("ln_bruto", f"IF([@n_tk]=0,0,LN(1+SUMIFS(base[pnl_total_perc],{_TK}))/[@n_tk])"),
    ("ultima", f"IF([@eh_ativo]=0,0,IF(COUNTIFS({_ATE_O_FIM('codigo_IAM_fundo')},[@codigo_IAM_fundo],"
               f"{_ATE_O_FIM('ticker_venc')},[@ticker_venc],{_ATE_O_FIM('eh_ativo')},1)=1,1,0))"),
    ("total_tk", 'IF([@ultima]=1,(EXP(SUMIFS(base[ln_total],base[codigo_IAM_fundo],[@codigo_IAM_fundo],'
                 'base[ticker_venc],[@ticker_venc]))-1)*10000,"")'),
    ("bruto_tk", 'IF([@ultima]=1,(EXP(SUMIFS(base[ln_bruto],base[codigo_IAM_fundo],[@codigo_IAM_fundo],'
                 'base[ticker_venc],[@ticker_venc]))-1)*10000,"")'),
    ("fin_tk", 'IF([@ultima]=1,SUMIFS(base[total_nav_moeda_fundo],base[codigo_IAM_fundo],[@codigo_IAM_fundo],'
               'base[ticker_venc],[@ticker_venc],base[date],MAX(base[date]),base[eh_ativo],1)/10^6,"")'),
    ("rank_pos", 'IF([@ultima]=1,IF([@total_tk]>0,[@total_tk]+ROW()/10^9,""),"")'),
    ("rank_neg", 'IF([@ultima]=1,IF([@total_tk]<0,[@total_tk]-ROW()/10^9,""),"")'),
]


def aba_excel(wb, cod, nome, F):
    """Top e bottom por fórmulas: AGGREGATE (maior/menor ignorando erros) + MATCH/INDEX na base."""
    ws = wb.add_worksheet(nome[:31])
    ws.set_column(0, 0, 5)
    ws.set_column(1, 1, 28)
    ws.set_column(2, 9, 16)
    ws.write(0, 0, nome, F["titulo"])
    ws.write(1, 0, "Fundo", F["sub"])
    ws.write(1, 1, cod)
    ws.write(1, 3, "Período", F["sub"])
    ws.write_formula(1, 4, "=MIN(base[date])", F["data"])
    ws.write(1, 5, "a", F["sub"])
    ws.write_formula(1, 6, "=MAX(base[date])", F["data"])
    cab = ["#", "Código do ativo", "Categoria", "Grupo econômico", "Subsetor", "PnL bruto (bps)",
           "PnL hedge + câmbio (bps)", "PnL total (bps)", "Financeiro (mm)", "linha na base"]
    r0 = 3
    for titulo, func, col in ((f"Top {N} contribuições positivas", 14, "rank_pos"), (f"Bottom {N} contribuições", 15, "rank_neg")):
        ws.write(r0, 0, titulo, F["sub"])
        for j, h in enumerate(cab):
            ws.write(r0 + 1, j, h, F["head"])
        for k in range(1, N + 1):
            r, n = r0 + 1 + k, r0 + 2 + k
            idx = f"$J{n}"
            ws.write(r, 0, k)
            ws.write_formula(r, 9, f'=IFERROR(MATCH(_xlfn.AGGREGATE({func},6,base[{col}]/(base[codigo_IAM_fundo]=$B$2),{k}),'
                                   f'base[{col}],0),"")')
            for j, c in enumerate(["ticker_venc", "categoria", "grupo_economico_iam", "subsetor_iam"], 1):
                ws.write_formula(r, j, f'=IF({idx}="","",INDEX(base[{c}],{idx})&"")')
            ws.write_formula(r, 5, f'=IF({idx}="","",INDEX(base[bruto_tk],{idx}))', F["num2"])
            ws.write_formula(r, 6, f'=IF({idx}="","",H{n}-F{n})', F["num2"])
            ws.write_formula(r, 7, f'=IF({idx}="","",INDEX(base[total_tk],{idx}))', F["num2"])
            ws.write_formula(r, 8, f'=IF({idx}="","",INDEX(base[fin_tk],{idx}))', F["num2"])
        ws.write(r0 + N + 2, 6, "Soma (bps)", F["sub"])
        ws.write_formula(r0 + N + 2, 7, f"=SUM(H{r0 + 3}:H{r0 + N + 2})", F["num2"])
        r0 += N + 5


def main():
    if len(sys.argv) < 3:
        sys.exit("Uso: python top_bottom.py <data_ini> <data_fim>   ex: python top_bottom.py 2026-10-01 2026-10-06")
    ini, fim = [pd.to_datetime(a, dayfirst="/" in a) for a in sys.argv[1:3]]
    print(f"Período {ini:%d/%m/%Y} a {fim:%d/%m/%Y} | carregando posições...")
    pos = carrega_posicoes(FUNDOS, ini, fim)

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    arq = os.path.join(PASTA_SAIDA, f"top_bottom_{ini:%Y%m%d}_{fim:%Y%m%d}")
    with PdfPages(arq + ".pdf") as pdf, pd.ExcelWriter(arq + ".xlsx", engine="xlsxwriter") as xw:
        F = formatos(xw.book)
        for cod, nome in FUNDOS.items():
            if not (pos.codigo_IAM_fundo == cod).any():
                print(f"  {nome}: sem posições, pulando")
                continue
            top, bot = ranking(pos, cod)
            pagina_pdf(pdf, nome, ini, fim, top, bot)
            aba_excel(xw.book, cod, nome, F)
            print(f"  {nome} ok")
        tabela_excel(xw.book, "base", pos[COLS_BASE], FORMULAS_BASE + FORMULAS_TB, F)
    print(f"Gerado: {arq}.pdf / .xlsx")


if __name__ == "__main__":
    main()
