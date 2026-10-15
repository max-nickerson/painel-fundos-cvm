"""
Roda os 20 fundos: escolhe parâmetros só dentro da amostra, avalia fora dela, mede robustez e ranqueia.
Saídas (quant/fundos/resultado): fundos.csv, fundos_diario.csv, curvas_fundos.png, robustez_fundos.png, ranking.csv
"""
import pickle
import sys
import time
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
import fundos_br as fb
import fundos_global as fg
from base import CDI, DIAS, DIAS_US, ETF, R_IBOV, SPX_USD, TB_US, brl
from motor import Fundo, aplica_taxas, anual, bootstrap_prob, metricas, roda

OUT = Path(__file__).resolve().parent / "resultado"
OUT.mkdir(exist_ok=True)
LOG = open(OUT / "log.txt", "a", encoding="utf-8")


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.write(s + "\n")
    LOG.flush()


acwi = (ETF["ACWI"].reindex(DIAS_US).ffill().pct_change(fill_method=None) - TB_US)
BENCH = {"CDI": CDI * 0, "Ibovespa": R_IBOV, "ACWI (R$ c/ hedge)": CDI + brl(acwi), "S&P 500 (R$ c/ hedge)": CDI + brl(SPX_USD - TB_US)}
BENCH["CDI"] = CDI

RF, MM, CR, AC = dict(adm=.005, perf=.20), dict(adm=.02, perf=.20), dict(adm=.008, perf=.20), dict(adm=.02, perf=.20)
FUNDOS = [
    Fundo("01 Caixa sintético (box de 4 pontas)", "Arbitragem B3", "CDI",
          "Emprestar via box de opções quando a taxa travada supera o CDI", "Caixa em LFT; até 100% do PL em boxes de opções líquidas (BOVA11, PETR4, VALE3...) "
          "com pernas perto do dinheiro, compradas nas ofertas do fechamento; mantidos até o vencimento", fb.box,
          {"thr": [.003, .005, .01], "peso": [.1, .2], "lado": ["compra", "ambos"]}, inicio="2015-01-01", **RF),
    Fundo("02 Financiador a termo", "Arbitragem B3", "CDI", "Comprar à vista e vender a termo quando a taxa implícita (mediana do dia) supera o CDI",
          "Caixa em LFT; posições de 5-10% do PL por ação/prazo (60-400 dias), sem risco de mercado (garantia B3)", fb.termo,
          {"thr": [.005, .01, .02], "peso": [.05, .1]}, inicio="2015-01-01", **RF),
    Fundo("03 Conversão BOVA11 (box de 3 pontas)", "Arbitragem B3", "CDI", "Ativo + put - call do mesmo strike = renda fixa; entra quando paga mais que o CDI",
          "Caixa em LFT; até 100% em conversões de BOVA11/SMAL11", fb.conversao, {"thr": [.003, .005, .01], "peso": [.1, .2]}, inicio="2015-01-01", **RF),
    Fundo("04 Arbitragem ADR x local", "Valor relativo", "CDI", "Diferença de preço entre ADR e ação local volta à média",
          "Pares comprado/vendido com hedge cambial (dólar futuro), até 20% do PL por par, aluguel na ponta vendida", fb.adr,
          {"z_in": [1.5, 2.0, 2.5], "janela": [20, 60, 120]}, inicio="2019-03-01", corte="2023-01-01", **MM),
    Fundo("05 Long-short ON x PN", "Valor relativo", "CDI", "A diferença entre classes da mesma empresa volta à média",
          "12 pares (PETR, ITUB, BBDC, GGBR, ELET, CMIG...), até 25% por par, neutro em dinheiro", fb.on_pn,
          {"z_in": [1.5, 2.0, 2.5], "janela": [20, 60, 120]}, inicio="2012-01-01", **MM),
    Fundo("06 Crédito offshore com hedge (cupom cambial)", "Crédito", "CDI", "Eurobonds de empresas brasileiras com hedge cambial e de Treasury: CDI + spread",
          "15-25 bonds escolhidos por sinal, hedge em dólar futuro; alavancagem até 1,5x a CDI+1%", fb.eurobonds, {"n": [10, 15, 25], "alav": [1.0, 1.5]},
          inicio="2021-01-01", corte="2024-01-01", **CR),
    Fundo("07 Valor relativo em juros (DI/DAP)", "Juros", "CDI", "Borboleta 2-5-10 e inflação implícita voltam à média",
          "Futuros de DI1 e DAP neutros em DV01, vol-alvo 5%; caixa em LFT (margem)", fb.juros_rv,
          {"z_in": [1.0, 1.5, 2.0], "janela": [63, 126, 252]}, inicio="2019-06-01", corte="2023-01-01", **MM),
    Fundo("08 Crédito privado ML", "Crédito", "CDI", "Seleção diária de debêntures por machine learning, com hedge de juros",
          "25-30 debêntures por faixa de risco, execução institucional; alavancagem até 1,3x", fb.credito,
          {"faixa": ["conservador", "moderado", "high yield"], "alav": [1.0, 1.3]}, inicio="2021-01-01", corte="2024-01-01", **CR),
    Fundo("09 Crédito com hedge de ações (estrutura de capital)", "Crédito", "CDI", "Debêntures + venda de índice para proteger o risco de crédito ligado a ações",
          "Livro de crédito ML vendido em h x Ibovespa futuro", fb.estrutura_capital, {"h": [0, .1, .2, .3], "faixa": ["moderado", "high yield"]},
          inicio="2021-01-01", corte="2024-01-01", **CR),
    Fundo("10 Crédito EUA com hedge de juros", "Crédito global", "CDI", "High yield e EM em dólar, sem risco de juros americanos, com filtro de tendência/VIX",
          "HYG/JNK e EMB contra IEF (beta móvel), vol-alvo; hedge cambial (R$ = CDI + excesso)", fg.credito_eua,
          {"timing": ["nenhum", "tendencia", "vix"], "alvo": [.04, .06, .08]}, inicio="2010-01-01", **MM),
    Fundo("11 Carry de moedas global", "Macro", "CDI", "Comprar moedas de juros altos e vender as de juros baixos (25 moedas, G10 + emergentes)",
          "Top/bottom n por diferencial de juros (BIS), filtro de momento, peso por inverso da vol, teto 25% por moeda, vol-alvo 8%", fg.carry_fx,
          {"n": [3, 5], "filtro": [0, 1], "lado": ["ls", "long"]}, inicio="2010-01-01", **MM),
    Fundo("12 Commodities sistemático", "Macro", "CDI", "Tendência e momento relativo em commodities, reduzindo posição quando especuladores estão lotados (CFTC)",
          "14 ETFs de commodities, vol-alvo, semanal", fg.commodities, {"tipo": ["ts", "xs", "ts+cot"], "alvo": [.08, .12]}, inicio="2010-01-01", **MM),
    Fundo("13 Tendência multiativos (CTA)", "Macro", "CDI", "Seguir tendências em ações, juros, crédito, commodities e moedas",
          "21 ETFs + 8 moedas, sinal 1-3-12 meses, peso pelo inverso da vol, vol-alvo", fg.cta,
          {"janelas": ["1-3-12", "3-12", "12"], "alvo": [.10, .15], "freq": ["W", "M"], "fx": [0, 1]}, inicio="2010-01-01", **MM),
    Fundo("14 Paridade de risco global", "Multiativos", "CDI", "Risco igual entre ações, juros, crédito, ouro e commodities, com alavancagem",
          "10 ETFs pelo inverso da vol, filtro de tendência de 10 meses opcional, vol-alvo", fg.paridade,
          {"tendencia": [0, 1], "alvo": [.06, .10, .14]}, inicio="2010-01-01", **MM),
    Fundo("15 Prêmio de volatilidade", "Volatilidade", "CDI", "Vender seguro de volatilidade: put-write no S&P e VIX vendido só com curva em contango",
          "Índice PutWrite da CBOE + SVXY com filtro VIX/VIX3M (e VVIX)", fg.vol_premio,
          {"peso_svxy": [0, .25, .5, .75], "filtro": ["vix3m", "vix3m+vvix"]}, inicio="2012-01-01", **MM),
    Fundo("16 Ações Brasil neutro (ML)", "Ações long-short", "CDI", "Fatores e ML nas 100 ações mais líquidas de cada data (sem viés de sobrevivência)",
          "Comprado/vendido nos decis extremos, semanal, vol-alvo 10% (máx. 100%/100%), aluguel 1% a.a.", fb.acoes_neutro,
          {"modelo": ["combo", "lgbm"], "quantil": [.1, .2]}, inicio="2015-01-01", **MM),
    Fundo("17 Ações Brasil com proteção (collar)", "Ações", "Ibovespa", "BOVA11 com put protetora financiada por call, ligada pela tendência",
          "100% BOVA11 + opções mensais da B3 a preço de oferta", fb.collar,
          {"put_otm": [.05, .10], "call_otm": [.05, .10, None], "regra": ["sempre", "tendencia"]}, inicio="2016-01-01", **AC),
    Fundo("18 Rotação de países (ML)", "Ações globais", "ACWI (R$ c/ hedge)", "Escolher os países mais baratos/com melhor momento e carry",
          "26 ETFs de países, top n por score (combinação ou LightGBM), mensal, hedge cambial", fg.paises,
          {"modelo": ["combo", "lgbm"], "n": [4, 6, 8]}, inicio="2013-01-01", adm=.015, perf=.20),
    Fundo("19 Macro com dados alternativos", "Macro", "CDI", "Posicionamento CFTC no real, tom das notícias (GDELT) e analistas Top 5 do Focus",
          "Ibovespa, dólar e DI 2 anos em um único fator de risco Brasil, semanal, vol-alvo", fb.macro_alt,
          {"sinal_cot": [-1, 1], "alvo": [.05, .08, .12]}, inicio="2019-06-01", corte="2023-01-01", **MM),
]


def multi(res):
    """Fundo 20: multiestratégia com as estratégias que tiveram IR > 0 dentro da amostra, peso pelo inverso da vol (só IS)."""
    livros, pesos = {}, {}
    for r in res:
        f = r["fundo"]
        if f.benchmark != "CDI" or r["is_ir"] <= 0:
            continue
        ex = r["bruto"] - CDI.reindex(r["bruto"].index)
        is_ = ex[ex.index < pd.Timestamp(f.corte)]
        if is_.std() == 0 or len(is_) < 120:
            continue
        livros[f.nome], pesos[f.nome] = ex, 1 / (is_.std() * np.sqrt(252))
    E = pd.DataFrame(livros).reindex(DIAS)
    w = pd.Series(pesos)
    ativo = E.notna()
    Wd = ativo.mul(w, axis=1)
    Wd = Wd.div(Wd.sum(axis=1).replace(0, np.nan), axis=0)
    for _ in range(5):                                                    # nenhum livro com mais de 25% do PL
        Wd = Wd.clip(upper=.25)
        Wd = Wd.div(Wd.sum(axis=1).replace(0, np.nan), axis=0)
    ex = (E.fillna(0) * Wd.fillna(0)).sum(axis=1)
    v = ex.rolling(126, min_periods=60).std().shift(1) * np.sqrt(252)
    esc = (.06 / v).clip(upper=3).fillna(1)
    return lambda escala=1.0, custo_mult=1, lag=0: (ex * esc * escala).shift(lag).fillna(0), list(livros)


if __name__ == "__main__":
    so = sys.argv[1:]                                                     # opcional: números dos fundos
    res = []
    for f in FUNDOS:
        if so and f.nome[:2] not in so:
            continue
        t = time.time()
        log(f"\n== {f.nome}")
        r = roda(f, CDI, BENCH[f.benchmark], log)
        if r is None:
            log("   sem resultado")
            continue
        res.append(r)
        o, rb = r["oos"], r["rob"]
        log(f"   escolhido {r['params']} | IR IS {r['is_ir']:.2f} | OOS: {o['retorno a.a. %']:.1f}% vs bench {o['benchmark a.a. %']:.1f}% "
            f"(IR {o['IR vs bench']:.2f}) | P(bater) {rb['P(bater bench OOS) %']:.0f}% | PBO {rb['PBO %']:.0f}% | {time.time() - t:.0f}s")
    if not so:
        fn, livros = multi(res)
        f20 = Fundo("20 Multiestratégia (pods)", "Multiestratégia", "CDI", "Juntar as estratégias que funcionaram dentro da amostra, com risco equilibrado",
                    f"{len(livros)} livros com IR > 0 no IS, peso pelo inverso da vol (IS), vol-alvo 6%", fn, {"escala": [.75, 1.0, 1.25]},
                    inicio="2015-01-01", corte="2023-01-01", **MM)
        r = roda(f20, CDI, BENCH["CDI"], log)
        r["livros"] = livros
        res.append(r)
        log(f"\n== {f20.nome}: {livros}")
    for r in res:
        r["fundo"].func = None                                            # funções não vão para o arquivo
    pickle.dump(res, open(OUT / "resultados.pkl", "wb"))
    log("pronto")
