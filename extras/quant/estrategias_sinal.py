"""
As três carteiras operando POR SINAL (qualquer dia, só quando o sinal é forte), contra o rebalanceamento mensal.
Regras fixadas antes de rodar:
  Crédito: força do sinal = percentil do papel no mês (modelo de crédito; spread no high yield), disponível 1 dia útil após o mês.
           compra se força >= 0,90 (top 10%) e há vaga; vende se força < 0,50, se o preço caiu mais de 1,5% em 5 dias
           (bond: 4%) ou se o papel some; vendido por queda fica 21 dias sem voltar; 1 papel por emissor; vaga vazia fica no CDI.
  Juros:   abre recebido/pago só quando os 3 sinais concordam (tendência 21d, inclinação, modelo); fecha quando o voto vira contra.
           O hedge das IPCA+/prefixadas segue a posição (recebido = sem hedge, senão hedge cheio).
Usa os dados e o custo intradiário do estrategias_diario.py.
"""
import numpy as np
import pandas as pd

import estrategias_diario as ed
from estrategias_diario import S, cdi, dias, e, met

ENTRA, SAI, STOP_DEB, STOP_EB, ESPERA = .90, .50, -.015, -.04, 21


def forca(col, filtro):
    """Percentil do papel entre os elegíveis no fim de cada mês, valendo a partir do 1o dia útil seguinte até o próximo mês."""
    out = {}
    for m, x in ed.b.groupby("mes"):
        x = x[filtro(x)]
        if m < e.INICIO_ML or len(x) < 20:
            continue
        r = x.drop_duplicates("codigo").set_index("codigo")[col].rank(pct=True)
        out[m] = r
    F = pd.DataFrame(out).T
    F.index = pd.PeriodIndex(F.index, freq="M")
    i = [dias.searchsorted(ed.fm[m], side="right") + 1 for m in F.index]
    F = F.set_axis([dias[min(k, len(dias) - 1)] for k in i])
    return F[~F.index.duplicated(keep="last")].reindex(dias).ffill(limit=30)


def forca_eb():
    s = ed.sprd_eb[ed.corp].copy()
    s.index = pd.PeriodIndex(s.index, freq="M")
    s = s[s.index >= e.INICIO_ML]
    r = s.rank(axis=1, pct=True)
    i = [dias.searchsorted(ed.fm[m], side="right") + 1 for m in r.index if m in ed.fm.index]
    r = r[[m in ed.fm.index for m in r.index]].set_axis([dias[min(k, len(dias) - 1)] for k in i])
    return r[~r.index.duplicated(keep="last")].reindex(dias).ffill(limit=30)


def livro(forca_, ret, preco, n_max, custo, stop, emissor):
    """Simula a carteira dia a dia. Decide no fechamento de t-1, rende em t. Devolve excesso diário e nº de operações."""
    F = forca_.reindex(columns=[c for c in forca_.columns if c in ret.columns])
    R = ret[F.columns].to_numpy()
    queda = (preco[F.columns] / preco[F.columns].shift(5) - 1).to_numpy()
    Fv = F.to_numpy()
    cols = np.array(F.columns)
    em = np.array([emissor.get(c, c) for c in cols])
    val, proib, out, ops, nav = {}, {}, np.zeros(len(dias)), 0, 1.0         # val: valor de cada papel desde a compra
    for t in range(1, len(dias)):
        f, q, i = Fv[t - 1], queda[t - 1], t - 1
        custo_dia = 0.0
        for k in list(val):                                               # saídas
            fraco = not (f[k] >= SAI)
            caiu = q[k] < stop
            sumiu = np.isnan(R[max(i - 2, 0):i + 1, k]).all()
            if fraco or caiu or sumiu:
                custo_dia += val.pop(k) * custo
                ops += 1
                if caiu:
                    proib[k] = t + ESPERA
        if len(val) < n_max:                                              # entradas só com sinal forte, com o caixa livre
            emis_h = {em[k] for k in val}
            cand = np.where((f >= ENTRA) & ~(q < stop))[0]
            for k in cand[np.argsort(-f[cand])]:
                livre = nav - sum(val.values())
                if len(val) >= n_max or livre <= 1e-9:
                    break
                if k in val or proib.get(k, 0) > t or em[k] in emis_h or np.isnan(R[i, k]):
                    continue
                val[k] = min(nav / n_max, livre)
                emis_h.add(em[k])
                custo_dia += val[k] * custo
                ops += 1
        ganho = 0.0
        for k in val:
            r = R[t, k] if not np.isnan(R[t, k]) else 0.0
            ganho += val[k] * r
            val[k] *= 1 + r
        out[t] = (ganho - custo_dia) / nav
        nav *= 1 + out[t]
    return pd.Series(out, index=dias), ops


def juros_por_sinal():
    """Posição +1/-1/0 com histerese: abre só com voto unânime, fecha quando o voto vira de lado."""
    pos = {}
    for col in ("p_dap", "p_di1"):
        v, p, cur = ed.sig_d[col], [], 0.0
        for x in v.values:
            if np.isnan(x):
                p.append(cur)
                continue
            if abs(x) >= .99:
                cur = np.sign(x)
            elif cur * x < 0:
                cur = 0.0
            p.append(cur)
        pos[col] = pd.Series(p, index=dias).shift(1)
    ov = {"dap": (pos["p_dap"] * ed.r_dap).fillna(0) - (pos["p_dap"].diff().abs() * e.CUSTO_FUT).fillna(0),
          "di1": (pos["p_di1"] * ed.r_di).fillna(0) - (pos["p_di1"].diff().abs() * e.CUSTO_FUT).fillna(0)}
    return ov, pos


ov, pos = juros_por_sinal()
h = pd.DataFrame(1.0, index=dias, columns=ed.P.columns)                      # hedge segue a posição de juros
for idx, col in (("IPCA", "p_dap"), ("PRE", "p_di1")):
    cols = ed.c.index[ed.c.indice.eq(idx)]
    h.loc[:, cols] = np.outer((pos[col] <= 0).astype(float).fillna(1), np.ones(len(cols)))
exc_sinal = (ed.R + ed.Hdd * h).sub(cdi, axis=0)
emis = ed.b.drop_duplicates("codigo").set_index("codigo").empresa.to_dict()
emis_eb = ed.emis.to_dict()

print("simulando os livros por sinal...", flush=True)
cons, n1 = livro(forca("score", ed.lim(-1, 3, 5)), ed.exc_hed, ed.Pi, 30, ed.CUSTO["cons"], STOP_DEB, emis)
mod, n2 = livro(forca("score", ed.lim(-1, 8)), exc_sinal, ed.Pi, 25, ed.CUSTO["mod"], STOP_DEB, emis)
hy, n3 = livro(forca("spread", ed.lim(2, 40)), exc_sinal, ed.Pi, 20, ed.CUSTO["hy"], STOP_DEB, emis)
f_eb = forca_eb()
eb, n4 = livro(f_eb, ed.exc_eb, ed.PE, 15, e.CUSTO_EXT, STOP_EB, emis_eb)
s_ig = ed.sprd_eb[ed.corp]
s_ig.index = pd.PeriodIndex(s_ig.index, freq="M")
ig_ok = (s_ig < 3).astype(float).reindex(dias.to_period("M") - 1).set_axis(dias)
ebig, n5 = livro(f_eb.where(ig_ok.reindex(columns=f_eb.columns).fillna(0) > 0), ed.exc_eb, ed.PE, 15, e.CUSTO_EXT, STOP_EB, emis_eb)
fin = .01
sinal = {"CDI+1 conservador": .8 * cons + .2 * ebig,
         "CDI+5 moderado": 2 * (.7 * mod + .3 * eb) - fin / 252 + 1.5 * ov["dap"] + 1.0 * ov["di1"],
         "CDI+10 arrojado": 3 * (.7 * hy + .3 * eb) - 2 * (fin + .005) / 252 + 3.0 * ov["dap"] + 2.0 * ov["di1"]}
mensal = {"diário (sinal de juros diário)": ed.base, "mensal de juros": ed.carteiras(modo="mensal")}
anos = (dias[-1] - ed.INI).days / 365.25
print(f"operações por ano: conservador {n1 / anos:.0f}, moderado {n2 / anos:.0f}, high yield {n3 / anos:.0f}, eurobonds {n4 / anos:.0f}; "
      f"trocas de posição em juros: DAP {(pos['p_dap'].diff().abs() > 0).sum() / anos:.0f}/ano, DI1 {(pos['p_di1'].diff().abs() > 0).sum() / anos:.0f}/ano")
print(f"tempo com posição em juros: DAP {(pos['p_dap'] != 0).mean() * 100:.0f}%, DI1 {(pos['p_di1'] != 0).mean() * 100:.0f}%")
linhas = []
for nome, cart in [("Rebalanceamento mensal (juros com sinal mensal)", mensal["mensal de juros"]),
                   ("Rebalanceamento mensal (juros com sinal diário)", mensal["diário (sinal de juros diário)"]),
                   ("Por sinal, qualquer dia", sinal)]:
    for k, v in cart.items():
        linhas.append({"modo": nome, "carteira": k, **met(v)})
tab = pd.DataFrame(linhas)
pd.set_option("display.width", 250)
print(tab.set_index(["carteira", "modo"]).sort_index().round(2).to_string())
tab.to_csv(S / "metricas_sinal.csv", index=False)
comp = {"rebal. mensal crédito moderado": ed.tranches(ed.esc(ed.lim(-1, 8), 25, "score"), ed.exc_din("mensal"), 5, ed.CUSTO["mod"]),
        "rebal. mensal eurobonds": ed.tranches(ed.sel_eb(), ed.exc_eb, 5, e.CUSTO_EXT), "crédito conservador": cons, "crédito moderado": mod, "high yield": hy, "eurobonds": eb, "DAP por sinal": ov["dap"], "DI1 por sinal": ov["di1"]}
print({k: round(met(v)["CDI + (pp a.a.)"], 2) for k, v in comp.items()})

import matplotlib.pyplot as plt
x = dias[dias >= ed.INI]
c_ = cdi.reindex(x)
fig, ax = plt.subplots(3, 2, figsize=(14, 12), gridspec_kw={"width_ratios": [3, 1.3]})
cores = {"Rebalanceamento mensal (juros com sinal mensal)": "#8C8C8C", "Rebalanceamento mensal (juros com sinal diário)": "#BFCDEB",
         "Por sinal, qualquer dia": "#EC7000"}
for i, (k, alvo) in enumerate(zip(sinal, (1, 5, 10))):
    a, d = ax[i, 0], ax[i, 1]
    a.plot(x, (1 + c_).cumprod() * 100, "k--", lw=1.6, label="CDI")
    a.plot(x, ((1 + c_) * (1 + alvo / 100) ** (1 / 252)).cumprod() * 100, color="#003399", ls=":", lw=1.2, label=f"meta CDI+{alvo}")
    for nome, cart in [("Rebalanceamento mensal (juros com sinal mensal)", mensal["mensal de juros"]),
                       ("Rebalanceamento mensal (juros com sinal diário)", mensal["diário (sinal de juros diário)"]), ("Por sinal, qualquer dia", sinal)]:
        v = cart[k].reindex(x)
        eq = (1 + c_ + v).cumprod()
        a.plot(x, eq * 100, color=cores[nome], lw=2.2 if "sinal," in nome else 1.5, label=f"{nome}: CDI {met(cart[k])['CDI + (pp a.a.)']:+.1f}")
        d.plot(x, (eq / eq.cummax() - 1) * 100, color=cores[nome], lw=1.2)
    a.set_title(k, loc="left", fontweight="bold")
    d.set_title("queda a partir do pico (%)", loc="left", fontsize=9)
    a.legend(frameon=False, fontsize=8, loc="upper left")
    for z in (a, d):
        z.grid(alpha=.25)
        z.spines[["top", "right"]].set_visible(False)
fig.suptitle("Operar por sinal (qualquer dia, só com sinal forte) x rebalanceamento mensal — marcação diária", x=.01, ha="left", fontweight="bold")
fig.tight_layout()
fig.savefig(S / "carteiras_sinal.png", dpi=140)
print("pronto")
