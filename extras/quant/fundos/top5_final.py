"""
Top 5 final (pós-auditoria): roda os sobreviventes com regimes RESTRITOS ao que tem sentido econômico para cada estratégia
(a auditoria mostrou que regimes genéricos sem relação com o ativo fabricam resultado no IS), custo real de liga/desliga,
e gera o dossiê de cada um (curva, sensibilidade, robustez) + carteira combinada dos 5.
Saídas: resultado/final/top5/ (top5_<k>.png, top5_curvas.png, top5_correlacao.png, top5_carteira.png, top5.csv, top5.pkl)
"""
import pickle

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import ideias_aud_ativos as aa
import ideias_aud_macro as am
import ideias_eventos_br as eb
import top5 as T
from base import CDI, R_IBOV
from motor import Fundo, anual, metricas, roda
from regimes import com_regime
from rodar import BENCH

OUT = T.OUT


def pega(mod, nome):
    fs = getattr(mod, "FUNDOS", None) or mod._fundos()
    return next(f for f in fs if f.nome == nome)


# (fundo, regimes permitidos com a razão econômica, custo de liga/desliga por 100% de troca)
CANDIDATOS = [
    (pega(am, "11 Carry de moedas global [auditado]"), ["nenhum", "risco_global", "vix_contango", "dd_stop"], .001,
     "carry quebra em fuga de risco (VIX/crédito) — o regime de risco é o hedge natural"),
    (pega(am, "IAC4 Variância EUA vendida [auditado]"), ["nenhum", "risco_global", "vix_contango", "dd_stop"], .001,
     "venda de vol só quando a curva de vol está normal"),
    (pega(aa, "C4 Mineradoras vs metal [auditado]"), ["nenhum", "risco_global", "dd_stop"], .001,
     "valor relativo: só proteção genérica de risco/stop"),
    (pega(aa, "06 Crédito offshore com hedge (cupom cambial) [auditado]"), ["nenhum", "credito_ok", "risco_global", "brl_calmo"], .02,
     "high yield BR: crédito global e câmbio; liga/desliga custa ~2 pontos"),
    (pega(eb, "E7 Rebalanceamento do Ibovespa"), ["nenhum", "ibov_tendencia"], .001,
     "fluxo de índice: no máximo tendência do próprio Ibovespa"),
]


def sem_regime(f):
    """mesmo fundo sem regime (para mostrar o efeito do regime lado a lado)."""
    return roda(f, CDI, BENCH[f.benchmark], lambda *a: None)


if __name__ == "__main__":
    res, F, linhas = [], {}, []
    for f, regs, ct, razao in CANDIDATOS:
        g = com_regime(f, regs, ct)
        r = roda(g, CDI, BENCH[f.benchmark], lambda *a: None)
        r0 = sem_regime(f)
        r["razao_regime"] = razao
        r["sem_regime"] = {"params": r0["params"], "oos": r0["oos"], "rob": r0["rob"]}
        res.append(r)
        F[f.nome] = g
        o, rb, o0 = r["oos"], r["rob"], r0["oos"]
        print(f"{f.nome} | {r['params']} | OOS {o['retorno a.a. %']:.1f}% vs {o['benchmark a.a. %']:.1f}% (ativo {o['ativo a.a. pp']:+.1f}, IR {o['IR vs bench']:.2f}) "
              f"| P {rb['P(bater bench OOS) %']:.0f}% PBO {rb['PBO %']:.0f}% | sem regime: ativo {o0['ativo a.a. pp']:+.1f} IR {o0['IR vs bench']:.2f}", flush=True)
        r["origem"] = "top5_final"
    t = T.tabela(res)
    sr = {r["fundo"].nome: r["sem_regime"]["oos"] for r in res}
    t["sem regime: OOS ativo pp"] = t.fundo.map(lambda n: sr[n]["ativo a.a. pp"])
    t["sem regime: IR OOS"] = t.fundo.map(lambda n: sr[n]["IR vs bench"])
    t["regimes permitidos"] = t.fundo.map({c[0].nome: ", ".join(c[1]) for c in CANDIDATOS})
    t["razão do regime"] = t.fundo.map({c[0].nome: c[3] for c in CANDIDATOS})
    t.to_csv(OUT / "top5.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print(t[["fundo", "params", "OOS a.a. %", "bench OOS %", "OOS ativo pp", "IR OOS", "P(bater) %", "PBO %", "DSR %", "% variantes > bench",
             "custo x2 pp", "exec +1 pp", "alfa OOS pp", "t alfa", "sem regime: OOS ativo pp", "nota"]].round(2).to_string())
    ordem = list(t.fundo)
    por = {r["fundo"].nome: r for r in res}
    sens = {}
    for k, n in enumerate(ordem, 1):
        r = por[n]
        sens[n] = T.dossie(k, r, F, BENCH[r["fundo"].benchmark])
        print("dossiê", k, n, sens[n])
    # curvas lado a lado
    fig, axs = plt.subplots(1, 5, figsize=(26, 5))
    for ax, (k, n) in zip(axs, enumerate(ordem, 1)):
        r = por[n]
        liq, f = r["liquido"], r["fundo"]
        b = BENCH[f.benchmark].reindex(liq.index).fillna(0)
        ax.plot(liq.index, (1 + liq).cumprod() * 100, color=T.VERDE, lw=2, label="fundo (líquido de custos)")
        ax.plot(liq.index, (1 + b).cumprod() * 100, color="k", ls="--", lw=1.2, label=f.benchmark)
        ax.plot(liq.index, (1 + R_IBOV.reindex(liq.index).fillna(0)).cumprod() * 100, color="#C9CFD9", lw=1, label="Ibovespa")
        ax.axvspan(pd.Timestamp(f.corte), liq.index[-1], color="#FFF1E3", zorder=0)
        ax.set_yscale("log")
        ax.set_title(f"#{k} {n.replace(' [auditado]', '')[:42]}\nOOS {r['oos']['ativo a.a. pp']:+.1f} pp a.a. vs {f.benchmark} | IR {r['oos']['IR vs bench']:.2f} | P(bater) {r['rob']['P(bater bench OOS) %']:.0f}%",
                     loc="left", fontweight="bold", color=T.NAVY, fontsize=9)
        ax.legend(frameon=False, fontsize=7, loc="upper left")
    fig.suptitle("Top 5 (pós-auditoria) — cota líquida de custos vs benchmark; faixa laranja = fora da amostra", fontsize=14, fontweight="bold", color=T.NAVY, x=.01, ha="left")
    fig.tight_layout(rect=[0, 0, 1, .93])
    fig.savefig(OUT / "top5_curvas.png", dpi=110)
    # correlação e carteira combinada (pesos pelo inverso da vol do IS, sem olhar o OOS)
    A = pd.DataFrame({n.replace(" [auditado]", "")[:30]: por[n]["liquido"] - CDI.reindex(por[n]["liquido"].index) for n in ordem})
    A = A.loc["2012":].fillna(0)
    corte = pd.Timestamp("2021-01-01")
    cortes = {n.replace(" [auditado]", "")[:30]: pd.Timestamp(por[n]["fundo"].corte) for n in ordem}
    w = pd.Series({c: 1 / A[c][(A.index < cortes[c]) & (A[c] != 0)].std() for c in A})     # cada livro: vol do seu próprio IS
    w = (w / w.sum()).fillna(0)
    corte = max(cortes.values())                                                            # carteira avaliada só quando todos já estão fora da amostra
    alvo = .06 / (A[A.index < corte] @ w).std() / np.sqrt(252)
    port = (A @ w) * alvo + CDI.reindex(A.index).fillna(0)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(17, 6), gridspec_kw={"width_ratios": [1.6, 1]})
    a1.plot(port.index, (1 + port).cumprod() * 100, color=T.VERDE, lw=2.2, label="carteira dos 5 (vol-alvo 6%)")
    a1.plot(port.index, (1 + CDI.reindex(port.index).fillna(0)).cumprod() * 100, "k--", lw=1.2, label="CDI")
    a1.plot(port.index, (1 + R_IBOV.reindex(port.index).fillna(0)).cumprod() * 100, color="#C9CFD9", lw=1, label="Ibovespa")
    a1.axvspan(corte, port.index[-1], color="#FFF1E3", zorder=0)
    a1.set_yscale("log")
    mp = metricas(port[port.index >= corte], CDI, CDI)
    a1.set_title(f"Carteira combinada (pesos do IS, alavancagem {alvo:.1f}x): OOS {mp['retorno a.a. %']:.1f}% a.a. vs CDI {anual(CDI.reindex(port[port.index >= corte].index)):.1f}%"
                 f" | Sharpe {mp['Sharpe']:.2f} | pior queda {mp['pior queda %']:.1f}%", loc="left", fontweight="bold", color=T.NAVY, fontsize=10)
    a1.legend(frameon=False, loc="upper left")
    c = A[A.index >= corte].corr()
    a2.imshow(c, cmap="RdBu_r", vmin=-1, vmax=1)
    for i in range(len(c)):
        for j in range(len(c)):
            a2.text(j, i, f"{c.iloc[i, j]:.2f}", ha="center", va="center", fontsize=9)
    a2.set_xticks(range(len(c)), [x[:14] for x in c.columns], rotation=45, ha="right", fontsize=8)
    a2.set_yticks(range(len(c)), c.columns, fontsize=8)
    a2.set_title("Correlação diária OOS dos excessos", loc="left", fontweight="bold", color=T.NAVY)
    fig.tight_layout()
    fig.savefig(OUT / "top5_carteira.png", dpi=110)
    print("pesos IS", (w * alvo).round(3).to_dict(), "carteira OOS", {k: round(v, 2) for k, v in mp.items() if isinstance(v, float)})
    for r in res:
        r["fundo"].func = None
    pickle.dump({"res": res, "sens": sens, "pesos": (w * alvo).to_dict()}, open(OUT / "top5.pkl", "wb"))
    print("pronto")
