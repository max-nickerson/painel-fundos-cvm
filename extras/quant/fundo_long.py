"""
Fundo comprado (long-biased) que só vende em convicção muito alta. Regras fixadas antes de rodar.
  Comprado: 2x (70% crédito moderado ML com hedge dinâmico + 30% eurobonds com regras de risco), financiado a CDI+1%;
            juros: recebe DAP 5a (1,5x) e DI1 2a (1x) na proporção do sinal quando ele é positivo.
  Vendido (só se TUDO valer):
    ação do emissor: 5% piores do modelo de crédito no mês + spread abriu > 1 pp em 3m + ação caiu > 15% em 3m;
                     2% do PL por nome, no máximo 10%, carrega 3 meses (tranches), custo 0,10% + aluguel 2% a.a.
    juros: paga DAP/DI1 só quando os três sinais (tendência 1m, inclinação, ML) concordam em alta (sinal = -1).
Uso: python fundo_long.py   (depois de estrategias.py)
"""
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import estrategias as e
from long_short import futuro_mes

S = e.SAIDA
PESO_ACAO, MAX_ACOES, ALUGUEL_ACAO = .02, 5, .02 / 12

pn, Hd, mx, pj, fret, ult, fm = pd.read_pickle(S / "cache_estrategias.pkl")
meses, cdi_m = pn["meses"], pn["cdi_m"]
C = pd.read_csv(S / "excessos_mensais.csv", index_col=0)
C.index = pd.PeriodIndex(C.index, freq="M")
sig = pd.read_csv(S / "sinal_juros.csv", index_col=0)
sig.index = pd.PeriodIndex(sig.index, freq="M")
b = pd.read_parquet(S / "credito_ml.parquet")
acoes = pd.read_parquet(e.DADOS / "acoes.parquet").reindex(meses)
cnpj = pn["cad"].cnpj.astype(str).str.replace(r"\D", "", regex=True)

# ---- livro comprado de crédito (já calculado em estrategias.py)
credito = 2 * (.7 * C["Crédito moderado ML (hedge dinâmico)"] + .3 * C["Eurobonds hedgeados (maior carrego)"]) - .01 / 12

# ---- juros: retorno mensal de receber (comprado em PU) DAP 5a e DI1 2a
rdap, _ = futuro_mes(ult, fret, fm, meses, "DAP", 5)
rdi, _ = futuro_mes(ult, fret, fm, meses, "DI1", 2)
s_dap, s_di = sig.p_dap.shift(1), sig.p_di1.shift(1)                          # decisão no fim do mês anterior
juros = lambda pos_dap, pos_di: (1.5 * pos_dap.reindex(C.index) * rdap.reindex(C.index)
                                 + 1.0 * pos_di.reindex(C.index) * rdi.reindex(C.index)).fillna(0) - e.CUSTO_FUT
recebe = lambda s: s.clip(lower=0)
paga_obvio = lambda s: s.where(s <= -.99, 0).clip(upper=0)                     # só quando os 3 sinais concordam
juros_long = juros(recebe(s_dap), recebe(s_di))
juros_short = juros(paga_obvio(s_dap), paga_obvio(s_di)) + e.CUSTO_FUT
juros_sim = juros(s_dap, s_di)                                                 # versão anterior: vende sem filtro

# ---- vendas de ações em convicção muito alta
b["pior5"] = b.groupby("mes").score.rank(pct=True) <= .05
cand = b[b.pior5 & (b.ds3 > 1) & (b.acao_3m < -.15)].copy()
cand["cnpj"] = cand.codigo.map(cnpj)
sinais = {m: list(dict.fromkeys(x.sort_values("score").cnpj))[:MAX_ACOES] for m, x in cand.groupby("mes") if m >= e.INICIO_ML}
exc_acao = acoes.sub(cdi_m, axis=0)
vendas = pd.Series(0.0, index=C.index)
detalhe = []
for i, n in enumerate(C.index):
    tot = 0.0
    for s in range(1, e.H + 1):                                               # sinal em j, vende no fim de j+1, carrega 3 meses
        j = list(meses).index(n) - 1 - s
        if j < 0 or meses[j] not in sinais:
            continue
        for c in sinais[meses[j]]:
            r = exc_acao.at[n, c] if c in exc_acao.columns else np.nan
            if pd.notna(r):
                ganho = -PESO_ACAO / e.H * r - PESO_ACAO / e.H * ALUGUEL_ACAO - (PESO_ACAO / e.H * .001 * 2 if s == 1 else 0)
                tot += ganho
                detalhe.append({"mes": n, "sinal": meses[j], "cnpj": c, "retorno_acao_vs_cdi": r, "contribuicao": ganho})
    vendas[n] = tot

fundos = {
    "Só comprado": credito + juros_long,
    "Comprado + vendas de alta convicção": credito + juros_long + juros_short + vendas,
    "CDI+5 anterior (vende juros sem filtro)": credito + juros_sim,
}
cdi = cdi_m.reindex(C.index)
linhas = []
for k, x in {**fundos, "  só as vendas de juros (pagar quando unânime)": juros_short, "  só as vendas de ações": vendas}.items():
    r = 1 + cdi + x
    eq = r.cumprod()
    a, c = r.prod() ** (12 / len(r)) - 1, (1 + cdi).prod() ** (12 / len(r)) - 1
    linhas.append({"fundo": k, "retorno a.a. (%)": a * 100, "CDI + (pp)": (a - c) * 100, "vol a.a. (%)": (cdi + x).std() * np.sqrt(12) * 100,
                   "Sharpe": x.mean() / x.std() * np.sqrt(12) if x.std() else np.nan, "pior queda (%)": (eq / eq.cummax() - 1).min() * 100,
                   "meses com venda": int((x != 0).sum()) if k.startswith("  ") else ""})
tab = pd.DataFrame(linhas).set_index("fundo")
pd.set_option("display.width", 220)
print(tab.round(2).to_string())
d = pd.DataFrame(detalhe)
if len(d):
    v = d.groupby(["sinal", "cnpj"]).agg(acao=("retorno_acao_vs_cdi", lambda s: (1 + s).prod() - 1)).reset_index()
    nomes = pn["cad"].assign(c=cnpj).drop_duplicates("c").set_index("c").empresa
    v["empresa"] = v.cnpj.map(nomes)
    print(f"\nvendas de ações: {len(v)} operações; acerto (ação caiu vs CDI) {(v.acao < 0).mean() * 100:.0f}%; "
          f"retorno médio da ação vendida em 3m {v.acao.mean() * 100:.1f}%")
    print(v.sort_values("sinal").assign(acao=lambda x: (x.acao * 100).round(1)).to_string(index=False))
print("\nmeses pagando juros (unânime):", {"DAP": int((paga_obvio(s_dap) < 0).sum()), "DI1": int((paga_obvio(s_di) < 0).sum())},
      "acerto:", {"DAP": f"{((paga_obvio(s_dap) * rdap) > 0)[paga_obvio(s_dap) < 0].mean() * 100:.0f}%",
                  "DI1": f"{((paga_obvio(s_di) * rdi) > 0)[paga_obvio(s_di) < 0].mean() * 100:.0f}%"})
tab.to_csv(S / "metricas_fundo_long.csv")

fig, ax = plt.subplots(2, 1, figsize=(12, 9), gridspec_kw={"height_ratios": [3, 1.3]})
x = C.index.to_timestamp()
ax[0].plot(x, (1 + cdi).cumprod() * 100, "k--", lw=2, label="CDI")
for (k, v), cor in zip(fundos.items(), ["#003399", "#EC7000", "#8C8C8C"]):
    ax[0].plot(x, (1 + cdi + v).cumprod() * 100, color=cor, lw=2.4 if "vendas" in k else 1.6, label=k)
ax[0].set_title("Fundo comprado com vendas só em convicção muito alta: patrimônio (base 100)", loc="left", fontweight="bold")
ax[0].legend(frameon=False, loc="upper left")
ax[1].bar(x, (juros_short + vendas) * 100, width=20, color=np.where(juros_short + vendas >= 0, "#2E9E5B", "#C0392B"))
ax[1].set_title("Contribuição mensal das vendas (pp)", loc="left", fontweight="bold")
for a in ax:
    a.grid(alpha=.25)
    a.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(S / "fundo_long.png", dpi=140)
