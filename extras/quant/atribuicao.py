"""De onde vem o retorno dos finalistas: crédito, eurobonds, juros, custo de alavancagem; validação x teste; regimes; piores quedas."""
import contextlib, io, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
S = "resultado/"
B = pd.read_pickle(S + "base_diaria.pkl"); dias = B["dias"]
cred = pd.read_parquet(S + "credito_livros.parquet"); jur = pd.read_parquet(S + "juros_modelos.parquet")
with contextlib.redirect_stdout(io.StringIO()):
    import estrategias_sinal as es
eb = es.livro(es.forca_eb(), es.ed.exc_eb, es.ed.PE, 15, es.e.CUSTO_EXT, -9, es.emis_eb)[0].reindex(dias).fillna(0)
di2 = jur[("DI2", "tendência 21d")].reindex(dias).fillna(0)
reg = pd.read_parquet(S + "juros_features.parquet"); est = (reg[[c for c in reg if c.startswith("reg")]].iloc[:, -1].reindex(dias).fillna(0) > .5)
F = {"CDI+1": ("conservador", "ridge", 1.0, 0, .2, .5), "CDI+5": ("moderado", "ridge", 1.5, .01, .3, 1), "CDI+10": ("high yield", "xgboost", 2.0, .015, .3, 2)}
per = {"validação 21-23": ("2021-01-04", "2023-12-31"), "teste 24-26": ("2024-01-01", "2026-12-31")}
pd.set_option("display.width", 200)
for p, (fx, m, al, fin, w_eb, w_j) in F.items():
    c = {"crédito local": al * (1 - w_eb) * cred[(fx, m)].reindex(dias).fillna(0), "eurobonds": al * w_eb * eb,
         "juros DI 2a": w_j * di2 / 2, "custo alavancagem": pd.Series(-(al - 1) * fin / 252, index=dias)}
    c = pd.DataFrame(c); c["total"] = c.sum(axis=1)
    t = pd.DataFrame({k: c.loc[a:b].sum() * 252 / len(c.loc[a:b]) * 100 for k, (a, b) in per.items()})
    t["estresse"] = c[est & (c.index >= "2021")].mean() * 252 * 100
    t["normal"] = c[~est & (c.index >= "2021")].mean() * 252 * 100
    print(f"\n==== {p}  (% a.a. acima do CDI, soma simples)\n", t.round(2).to_string())
    eq = (1 + c.total.loc["2021":]).cumprod(); dd = eq / eq.cummax() - 1
    fim = dd.idxmin(); ini = eq.loc[:fim].idxmax()
    print(f"pior queda {dd.min()*100:.1f}% de {ini:%d/%m/%y} a {fim:%d/%m/%y}; contribuição:", (c.loc[ini:fim].sum() * 100).round(2).drop("total").to_dict())
    mes = c.total.loc["2021":].resample("M").sum() * 100
    print("meses negativos:", f"{(mes < 0).mean()*100:.0f}%", "| piores:", mes.nsmallest(3).round(2).to_dict())
# o modelo x carregar o mesmo universo sem modelo
print("\n==== crédito: modelo x 'carrego' (comprar maior prêmio, sem ML) e x score mensal, % a.a.")
for fx, m in (("conservador", "ridge"), ("moderado", "ridge"), ("high yield", "xgboost")):
    for k, (a, b) in per.items():
        print(fx, k, {x: round(cred[(fx, x)].loc[a:b].mean() * 252 * 100, 2) for x in (m, "carrego", "score_mensal")})
