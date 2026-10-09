"""
Alpha ou sorte? Testes de robustez das três carteiras (CDI+1, CDI+5, CDI+10).
  1. Bootstrap em blocos (6 meses) dos excessos mensais: faixa de 5-95%, P(abaixo do CDI), P(abaixo da meta)
  2. Carteiras aleatórias: mesmo universo, mesmas regras, mesmo nº de papéis, sorteados -> a seleção tem habilidade?
  3. Sinais de juros aleatórios: posições embaralhadas no tempo -> o timing vale mais que o acaso?
  4. Grade de parâmetros (nº de papéis, carregamento, defasagem, custos, financiamento, sinal de juros, ML, eurobonds)
  5. Sharpe deflacionado (Bailey & López de Prado) pelo nº de tentativas da grade
  6. 2019-07 a 2021-02 (antes do período usado para desenhar as regras) para as partes sem ML
Uso: python robustez.py   (depois de estrategias.py)
"""
import itertools
import time

import matplotlib
import numpy as np
import pandas as pd
from scipy.stats import norm

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import HistGradientBoostingRegressor

import estrategias as e
from long_short import futuro_mes

S = e.SAIDA
RNG = np.random.default_rng(0)
t0 = time.time()
pn, Hd, mx, pj, fret, ult, fm = pd.read_pickle(S / "cache_estrategias.pkl")
meses, cdi_m, cad = pn["meses"], pn["cdi_m"], pn["cad"]
b = pd.read_parquet(S / "credito_ml.parquet")
exc_eb, sprd_eb, cad_eb, exc_etf, dol = pd.read_pickle(S / "cache_ext.pkl")
R = pn["R"]
exc_hed = (R + Hd.fillna(0)).sub(cdi_m, axis=0)


# ------------------------------------------------------------------ peças parametrizadas
def tranches(sel, ret, H=3, lag=1, custo=0.0):
    """Sinal em j, entra no fim de j+lag, carrega H meses; 1/H do livro renovado por mês."""
    out, ant = {}, {}
    idx = list(ret.index)
    for i, n in enumerate(idx):
        rs = []
        for s in range(1, H + 1):
            j = i - lag - s
            if j < 0 or idx[j] not in sel:
                continue
            nomes = [k for k in sel[idx[j]] if k in ret.columns]
            r = ret.loc[n, nomes].dropna()
            if len(r):
                g = len(set(nomes) ^ ant.get(j % H, set())) / max(len(nomes), 1) if s == 1 else 0
                if s == 1:
                    ant[j % H] = set(nomes)
                rs.append(r.mean() - g * custo)
        if rs:
            out[n] = np.mean(rs)
    return pd.Series(out)


def elegiveis(lo, hi, dmax=10, inicio=e.INICIO_ML):
    ok = b.spread.between(lo, hi) & (b.D <= dmax) & (b.fin > 2e5) & ~(b.ds3 > 1) & ~(b.acao_3m.fillna(0) < -.25) & (b.mes >= inicio)
    return b[ok]


def escolhe(base, n, col):
    return {m: list(x.sort_values(col, ascending=False).drop_duplicates("empresa").head(n).codigo) for m, x in base.groupby("mes")}


def sorteia(base, n):
    return {m: list(x.drop_duplicates("empresa").sample(min(n, x.empresa.nunique()), random_state=int(RNG.integers(1e9))).codigo)
            for m, x in base.groupby("mes")}


px = pd.read_parquet(e.DADOS / "eurobonds_precos.parquet").assign(mes=lambda x: x.date.dt.to_period("M"))
dP3 = np.log(px.sort_values("date").groupby(["mes", "isin"]).preco.last().unstack().reindex(meses)).diff(3)
emis = cad_eb.emissor.str.replace(r"(?i)\s+(netherlands|finance|fuels|europe|lux|international|s\.?a\.?.*|bv|sapi|ltd|gmbh|trading|downstream).*$",
                                  "", regex=True).str.strip()
corp = [k for k in cad_eb.index[~cad_eb.soberano] if k in sprd_eb.columns]


def sel_eb(n, teto=None, aleatorio=False, inicio=e.INICIO_ML):
    out = {}
    for m in meses:
        if m < inicio:
            continue
        x = sprd_eb.loc[m, corp].dropna().sort_values(ascending=False)
        x = x[~(dP3.loc[m, x.index].fillna(0) < -.10)]
        x = x[~emis.loc[x.index].duplicated()]
        if teto:
            x = x[x < teto]
        if len(x):
            out[m] = list(x.sample(min(n, len(x)), random_state=int(RNG.integers(1e9))).index) if aleatorio else list(x.head(n).index)
    return out


# sinais de juros: voto de 3 (padrão) e cada componente sozinho
def sinal(tipo, alvo, col):
    t = np.sign(-mx[f"d_{alvo}_1m"]).fillna(0)
    i = np.sign(mx.inclinacao - mx.inclinacao.expanding().median()).fillna(0)
    m = np.sign(pj[col] - .5).fillna(0)
    t3 = np.sign(-mx[f"d_{alvo}_3m"]).fillna(0)
    s = {"voto3": (t + i + m) / 3, "tendencia_1m": t, "tendencia_3m": t3, "inclinacao": i, "ml": m, "voto_sem_ml": (t + i) / 2}[tipo]
    return s.where(pj[col].notna() | (tipo in ("tendencia_1m", "tendencia_3m", "inclinacao", "voto_sem_ml")))


rdap, _ = futuro_mes(ult, fret, fm, meses, "DAP", 5)
rdi, _ = futuro_mes(ult, fret, fm, meses, "DI1", 2)


def juros(tipo, lag=1):
    sd, si = sinal(tipo, "dap_5a", "p_dap").shift(lag), sinal(tipo, "di1_2a", "p_di1").shift(lag)
    return (sd * rdap).reindex(meses), (si * rdi).reindex(meses), sd, si


def hedge_din(tipo="voto3"):
    hr = pd.DataFrame(1.0, index=meses, columns=R.columns)
    for idx, alvo, col in (("IPCA", "dap_5a", "p_dap"), ("PRE", "di1_2a", "p_di1")):
        h = (.5 - .75 * sinal(tipo, alvo, col).shift(1)).clip(0, 1).fillna(1)
        cols = cad.index[cad.indice.eq(idx)]
        hr.loc[:, cols] = np.outer(h, np.ones(len(cols)))
    return (R + Hd.fillna(0) * hr).sub(cdi_m, axis=0)


def carteiras(c, fin=.01, a5=(1.5, 1.0), a10=(3.0, 2.0)):
    return {"CDI+1 conservador": .8 * c["cons"] + .2 * c["eb_ig"],
            "CDI+5 moderado": 2 * (.7 * c["mod"] + .3 * c["eb"]) - fin / 12 + a5[0] * c["dap"] + a5[1] * c["di1"],
            "CDI+10 arrojado": 3 * (.7 * c["hy"] + .3 * c["eb"]) - 2 * (fin + .005) / 12 + a10[0] * c["dap"] + a10[1] * c["di1"]}


def anual(x):
    x = x.dropna()
    cdi = cdi_m.reindex(x.index)
    return ((1 + cdi + x).prod() ** (12 / len(x)) - (1 + cdi).prod() ** (12 / len(x))) * 100


def sharpe(x):
    x = x.dropna()
    return x.mean() / x.std() * np.sqrt(12) if x.std() > 0 else np.nan


def componentes(n=1.0, H=3, lag=1, custo=e.CUSTO_CRED, sig="voto3", n_eb=15, col_ml="score", inicio=e.INICIO_ML, base_df=None):
    exc_din = hedge_din(sig)
    cons, mod, hy = elegiveis(-1, 3, 5, inicio), elegiveis(-1, 8, 10, inicio), elegiveis(2, 40, 10, inicio)
    c = {"cons": tranches(escolhe(cons, int(30 * n), col_ml), exc_hed, H, lag, custo),
         "mod": tranches(escolhe(mod, int(25 * n), col_ml), exc_din, H, lag, custo),
         "hy": tranches(escolhe(hy, int(20 * n), "spread"), exc_din, H, lag, custo * 2),
         "eb": tranches(sel_eb(n_eb, inicio=inicio), exc_eb, H, lag, e.CUSTO_EXT),
         "eb_ig": tranches(sel_eb(n_eb, 3, inicio=inicio), exc_eb, H, lag, e.CUSTO_EXT)}
    c["dap"], c["di1"], _, _ = juros(sig, lag)
    C = pd.DataFrame(c).reindex(meses)
    return C[C.index >= inicio + 1 + lag].fillna(0)


# ------------------------------------------------------------------ 0. base
base = componentes()
port = carteiras(base)
alvo = {"CDI+1 conservador": 1, "CDI+5 moderado": 5, "CDI+10 arrojado": 10}
print("base:", {k: round(anual(v), 2) for k, v in port.items()}, f"{time.time() - t0:.0f}s", flush=True)

# ------------------------------------------------------------------ 1. bootstrap em blocos
def bootstrap(x, n=5000, bloco=6):
    x = x.dropna().values
    T = len(x)
    out = np.empty((n, T))
    for i in range(n):
        idx = np.concatenate([np.arange(s, s + bloco) % T for s in RNG.integers(0, T, T // bloco + 1)])[:T]
        out[i] = x[idx]
    return out


cdi_b = cdi_m.reindex(base.index).values
boot = {}
for k, v in port.items():
    bt = bootstrap(v)
    a = ((1 + cdi_b + bt).prod(1) ** (12 / bt.shape[1]) - (1 + cdi_b).prod() ** (12 / bt.shape[1])) * 100
    boot[k] = {"excesso a.a. (pp)": anual(v), "IC 5%": np.percentile(a, 5), "IC 95%": np.percentile(a, 95),
               "P(abaixo do CDI)": (a < 0).mean() * 100, f"P(abaixo da meta)": (a < alvo[k]).mean() * 100, "_caminhos": bt}
print("bootstrap ok", f"{time.time() - t0:.0f}s", flush=True)

# ------------------------------------------------------------------ 2. carteiras aleatórias (habilidade de seleção)
def nulo_credito(chave, n_sim=200):
    sims = []
    for _ in range(n_sim):
        if chave == "cons":
            r = tranches(sorteia(elegiveis(-1, 3, 5), 30), exc_hed, 3, 1, e.CUSTO_CRED)
        elif chave == "mod":
            r = tranches(sorteia(elegiveis(-1, 8, 10), 25), hedge_cache, 3, 1, e.CUSTO_CRED)
        elif chave == "hy":
            r = tranches(sorteia(elegiveis(2, 40, 10), 20), hedge_cache, 3, 1, e.CUSTO_CRED * 2)
        else:
            r = tranches(sel_eb(15, aleatorio=True), exc_eb, 3, 1, e.CUSTO_EXT)
        sims.append(anual(r.reindex(base.index).fillna(0)))
    return np.array(sims)


hedge_cache = hedge_din()
nulo = {k: nulo_credito(k) for k in ["cons", "mod", "hy", "eb"]}
skill = {k: {"real (pp a.a.)": anual(base[k]), "média aleatória": nulo[k].mean(), "percentil do real": (nulo[k] < anual(base[k])).mean() * 100}
         for k in nulo}
print("aleatórias ok", f"{time.time() - t0:.0f}s", flush=True)

# ------------------------------------------------------------------ 3. sinais de juros embaralhados
def nulo_juros(r, pos, n_sim=2000):
    ok = pos.notna() & r.notna()
    r, p = r[ok].values, pos[ok].values
    real = sharpe(pd.Series(p * r))
    sims = np.array([sharpe(pd.Series(RNG.permutation(p) * r)) for _ in range(n_sim)])
    return real, sims


_, _, sd, si = juros("voto3")
nj = {"DAP 5a": nulo_juros(rdap.reindex(meses), sd), "DI1 2a": nulo_juros(rdi.reindex(meses), si)}
skill.update({k: {"real (pp a.a.)": np.nan, "Sharpe real": v[0], "Sharpe médio aleatório": v[1].mean(), "percentil do real": (v[1] < v[0]).mean() * 100}
              for k, v in nj.items()})
print("juros embaralhados ok", f"{time.time() - t0:.0f}s", flush=True)

# ------------------------------------------------------------------ 4. grade de parâmetros
# variantes do modelo de crédito (mesmo método, outros hiperparâmetros) para não depender de um ajuste específico
feats = [f for f in e.FEATS_CRED if f in b.columns]
ms = sorted(b.mes.unique())
for nome, (folha, lr) in {"score_b": (80, .06), "score_c": (300, .02)}.items():
    b[nome] = np.nan
    mod = None
    for i, m in enumerate(ms):
        if m < e.INICIO_ML:
            continue
        if mod is None or i % 3 == 0:
            tr = b[(b.mes <= ms[i - 5]) & b.limpo & b.alvo_dm.notna()]
            mod = HistGradientBoostingRegressor(loss="absolute_error", max_iter=300, learning_rate=lr, max_leaf_nodes=15,
                                                min_samples_leaf=folha, l2_regularization=1.0, random_state=1).fit(tr[feats], tr.alvo_dm.clip(-.1, .1))
        b.loc[b.mes == m, nome] = mod.predict(b.loc[b.mes == m, feats])
print("variantes de ML ok", f"{time.time() - t0:.0f}s", flush=True)

grade = {"n": [.6, 1.0, 1.6], "H": [1, 3, 6], "lag": [1, 2], "custo": [.0015, .003], "fin": [.01, .02],
         "sig": ["voto3", "tendencia_1m", "tendencia_3m", "inclinacao", "ml", "voto_sem_ml"], "n_eb": [10, 15, 25],
         "ml": ["score", "score_b", "score_c"]}
# cada peça só depende de alguns parâmetros: calcula uma vez e combina (o hedge dinâmico do crédito usa o sinal padrão)
cons_b, mod_b, hy_b = elegiveis(-1, 3, 5), elegiveis(-1, 8, 10), elegiveis(2, 40, 10)
cred = {}
for n, H, lag, custo, ml in itertools.product(grade["n"], grade["H"], grade["lag"], grade["custo"], grade["ml"]):
    cred[(n, H, lag, custo, ml)] = (tranches(escolhe(cons_b, int(30 * n), ml), exc_hed, H, lag, custo),
                                    tranches(escolhe(mod_b, int(25 * n), ml), hedge_cache, H, lag, custo),
                                    tranches(escolhe(hy_b, int(20 * n), "spread"), hedge_cache, H, lag, custo * 2))
print("  crédito da grade ok", f"{time.time() - t0:.0f}s", flush=True)
ebs = {(H, lag, k): (tranches(sel_eb(k), exc_eb, H, lag, e.CUSTO_EXT), tranches(sel_eb(k, 3), exc_eb, H, lag, e.CUSTO_EXT))
       for H, lag, k in itertools.product(grade["H"], grade["lag"], grade["n_eb"])}
jur = {(sg, lag): juros(sg, lag)[:2] for sg, lag in itertools.product(grade["sig"], grade["lag"])}
idx = base.index
linhas = []
for (n, H, lag, custo, ml), (c1, c2, c3) in cred.items():
    for k_eb in grade["n_eb"]:
        e1, e2 = ebs[(H, lag, k_eb)]
        for sg in grade["sig"]:
            d1, d2 = jur[(sg, lag)]
            C = pd.DataFrame({"cons": c1, "mod": c2, "hy": c3, "eb": e1, "eb_ig": e2, "dap": d1, "di1": d2}).reindex(idx).fillna(0)
            for fin in grade["fin"]:
                for k, v in carteiras(C, fin).items():
                    q = (1 + cdi_m.reindex(idx) + v).cumprod()
                    linhas.append({"carteira": k, "n": n, "H": H, "lag": lag, "custo": custo, "ml": ml, "sinal_juros": sg, "n_eb": k_eb,
                                   "fin": fin, "excesso": anual(v), "sharpe": sharpe(v), "pior_queda": (q / q.cummax() - 1).min() * 100})
print(f"  grade {len(linhas)} linhas, {time.time() - t0:.0f}s", flush=True)
G = pd.DataFrame(linhas)
G.to_csv(S / "robustez_grade.csv", index=False)

# ------------------------------------------------------------------ 5. Sharpe deflacionado
def dsr(x, sr_trials):
    x = x.dropna()
    T, sr = len(x), x.mean() / x.std()
    sk, ku = x.skew(), x.kurt() + 3
    N, V, g = len(sr_trials), np.var(sr_trials / np.sqrt(12)), 0.5772
    sr0 = np.sqrt(V) * ((1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * np.e)))
    psr = norm.cdf(sr * np.sqrt(T - 1) / np.sqrt(1 - sk * sr + (ku - 1) / 4 * sr ** 2))
    return psr * 100, norm.cdf((sr - sr0) * np.sqrt(T - 1) / np.sqrt(1 - sk * sr + (ku - 1) / 4 * sr ** 2)) * 100, N


# ------------------------------------------------------------------ 6. antes do período de desenho (sem ML)
pre = componentes(inicio=pd.Period("2019-07", "M"), sig="voto_sem_ml", col_ml="spread")
pre = pre[pre.index < pd.Period("2021-03", "M")]
pre_tab = {k: {"excesso a.a. (pp)": anual(pre[k]), "Sharpe": sharpe(pre[k]), "meses": len(pre)} for k in ["cons", "mod", "hy", "eb", "dap", "di1"]}

# ------------------------------------------------------------------ relatório
pd.set_option("display.width", 240)
res = pd.DataFrame({k: {kk: vv for kk, vv in v.items() if kk != "_caminhos"} for k, v in boot.items()}).T
for k in port:
    g = G[G.carteira == k]
    res.loc[k, "grade: % variantes > CDI"] = (g.excesso > 0).mean() * 100
    res.loc[k, f"grade: % variantes > meta"] = (g.excesso > alvo[k]).mean() * 100
    res.loc[k, "grade: mediana (pp)"] = g.excesso.median()
    res.loc[k, "grade: pior 10% (pp)"] = g.excesso.quantile(.1)
    p, d, N = dsr(port[k], G[G.carteira == k].sharpe.dropna().values)
    res.loc[k, "PSR (%)"], res.loc[k, "Sharpe deflacionado (%)"], res.loc[k, "nº tentativas"] = p, d, N
print("\n=== CARTEIRAS ===\n", res.round(1).to_string())
print("\n=== HABILIDADE DE SELEÇÃO (vs 200 carteiras aleatórias do mesmo universo) e TIMING DE JUROS (vs 2000 sinais embaralhados) ===\n",
      pd.DataFrame(skill).T.round(2).to_string())
print("\n=== SENSIBILIDADE POR PARÂMETRO (mediana do excesso, pp a.a.) ===")
for p_ in ["n", "H", "lag", "custo", "fin", "sinal_juros", "n_eb", "ml"]:
    print(p_, G.groupby([p_, "carteira"]).excesso.median().unstack().round(1).to_dict("index"))
print("\n=== 2019-07 a 2021-02 (antes do período de desenho; crédito por spread, juros sem ML) ===\n", pd.DataFrame(pre_tab).T.round(2).to_string())
res.to_csv(S / "robustez_resumo.csv")
pd.DataFrame(skill).T.to_csv(S / "robustez_habilidade.csv")

# gráficos
fig, ax = plt.subplots(2, 3, figsize=(17, 10))
cores = {"CDI+1 conservador": "#003399", "CDI+5 moderado": "#EC7000", "CDI+10 arrojado": "#C0392B"}
x = base.index.to_timestamp()
for i, (k, v) in enumerate(port.items()):
    a = ax[0, i]
    cam = np.cumprod(1 + cdi_b + boot[k]["_caminhos"], axis=1) * 100
    lo, md, hi = np.percentile(cam, [5, 50, 95], axis=0)
    a.fill_between(x, lo, hi, color=cores[k], alpha=.15, label="bootstrap 5-95%")
    a.plot(x, (1 + cdi_b + v.values).cumprod() * 100, color=cores[k], lw=2.4, label=k)
    a.plot(x, np.cumprod(1 + cdi_b) * 100, "k--", lw=1.6, label="CDI")
    a.plot(x, np.cumprod((1 + cdi_b) * (1 + alvo[k] / 100) ** (1 / 12)) * 100, color=cores[k], ls=":", lw=1.2, label=f"meta CDI+{alvo[k]}")
    a.set_title(f"{k}: {anual(v):+.1f} pp a.a. | P(< CDI) {boot[k]['P(abaixo do CDI)']:.0f}%", loc="left", fontweight="bold", fontsize=10)
    a.legend(frameon=False, fontsize=8, loc="upper left")
    g = G[G.carteira == k].excesso
    b_ = ax[1, i]
    b_.hist(g, bins=40, color=cores[k], alpha=.7)
    b_.axvline(0, color="k", lw=1)
    b_.axvline(alvo[k], color=cores[k], ls=":", lw=1.5)
    b_.axvline(anual(v), color="k", ls="--", lw=1.5)
    b_.set_title(f"{len(g)} variantes de parâmetros: {(g > 0).mean() * 100:.0f}% acima do CDI, {(g > alvo[k]).mean() * 100:.0f}% acima da meta",
                 loc="left", fontsize=9.5, fontweight="bold")
    b_.set_xlabel("excesso sobre o CDI (pp a.a.)  — tracejado = versão base, pontilhado = meta")
for a in ax.flat:
    a.grid(alpha=.25)
    a.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(S / "robustez_carteiras.png", dpi=130)

fig, ax = plt.subplots(1, 6, figsize=(20, 3.6))
for a, (k, v) in zip(ax, list(nulo.items()) + list(nj.items())):
    if k in nulo:
        a.hist(v, bins=30, color="#BFCDEB")
        a.axvline(anual(base[k]), color="#EC7000", lw=2.5)
        a.set_title({"cons": "Crédito conservador (ML)", "mod": "Crédito moderado (ML)", "hy": "High yield (spread)", "eb": "Eurobonds (carrego)"}[k]
                    + f"\npercentil {skill[k]['percentil do real']:.0f}", fontsize=9.5, fontweight="bold")
        a.set_xlabel("pp a.a. sobre o CDI")
    else:
        a.hist(v[1], bins=30, color="#BFCDEB")
        a.axvline(v[0], color="#EC7000", lw=2.5)
        a.set_title(f"Timing {k}\npercentil {skill[k]['percentil do real']:.0f}", fontsize=9.5, fontweight="bold")
        a.set_xlabel("Sharpe")
    a.spines[["top", "right"]].set_visible(False)
fig.suptitle("Real (laranja) contra o acaso (azul): carteiras sorteadas do mesmo universo e sinais de juros embaralhados", x=.01, ha="left", fontweight="bold")
fig.tight_layout()
fig.savefig(S / "robustez_acaso.png", dpi=130)
print(f"pronto em {(time.time() - t0) / 60:.0f} min")
