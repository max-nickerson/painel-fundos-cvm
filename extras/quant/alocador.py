"""
Alocador quant diário entre livros de crédito (conservador, moderado, high yield, eurobonds), juros (DI 2a) e CAIXA (rende CDI).
  Carteira de verdade: compra só com caixa (ou com o limite de alavancagem, pago a CDI + spread); venda volta para o caixa.
  Decide no fechamento de t, executa em t+1 (com custo por livro), rende a partir de t+2. Nada fixo: o modelo decide quanto
  vai para cada livro todo dia (com banda para não girar à toa).
  Regimes: HMM filtrado (só passado) sobre os índices dos próprios mercados de crédito + spreads, tendência e volatilidade.
  Testa também as três ideias: (a) tamanho do crédito pelo nível do spread, (b) livros com menos giro, (c) alavancagem no moderado.
  Escolhas só na validação 2021-23; teste intocado 2024-26.
"""
import contextlib
import io
import itertools
import warnings

import matplotlib
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.linear_model import Ridge
from arch.bootstrap import StationaryBootstrap

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import pesquisa_credito as pc

warnings.filterwarnings("ignore")
S, B, dias, cdi = pc.S, pc.B, pc.dias, pc.cdi
INI, VAL_FIM = pc.INI_OOS, pc.VAL_FIM
val, teste = dias[(dias >= INI) & (dias <= VAL_FIM)], dias[dias > VAL_FIM]
sh = lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() else -9
anual = lambda x: ((1 + x).prod() ** (252 / max(len(x), 1)) - 1) * 100
print("carregando...", flush=True)
df = pd.read_parquet(S / "credito_scores.parquet")
exc = pc.excesso_sem_futuro()[0]
emissor = df.drop_duplicates("codigo").set_index("codigo").empresa.dropna().to_dict()
elig = B["P"].notna()
MODELO = {"conservador": "ridge", "moderado": "ridge", "high yield": "xgboost"}   # escolhidos na validação (pesquisa_credito)
CK = {"conservador": "cons", "moderado": "mod", "high yield": "hy"}


# ------------------------------------------------------------------ (b) livro com menos giro
def simula(forca, custo, n_max, sai=.5, segura=0, lag=2):
    """Igual ao pesquisa_credito.simula, mas só vende se o papel cair abaixo de `sai` E já estiver na carteira há `segura` dias."""
    F = forca.reindex(index=dias, columns=exc.columns).shift(lag - 1).to_numpy()
    EC = elig.reindex(index=dias, columns=exc.columns).fillna(False).to_numpy()
    R = exc.to_numpy()
    em = np.array([emissor.get(c, c) for c in exc.columns])
    val_, desde, out, nav, ops = {}, {}, np.zeros(len(dias)), 1.0, 0
    for t in range(1, len(dias)):
        f, cd = F[t - 1], 0.0
        for k in list(val_):
            sumiu = np.isnan(R[max(t - 25, 0):t, k]).all()
            if sumiu or (not (f[k] >= sai) and EC[t - 1, k] and t - desde[k] >= segura):
                cd += val_.pop(k) * custo
                ops += 1
        if len(val_) < n_max:
            eh = {em[k] for k in val_}
            cand = np.where((f >= pc.ENTRA) & EC[t - 1])[0]
            for k in cand[np.argsort(-f[cand])]:
                livre = nav - sum(val_.values())
                if len(val_) >= n_max or livre <= 1e-9:
                    break
                if k in val_ or em[k] in eh:
                    continue
                val_[k], desde[k] = min(nav / n_max, livre), t
                eh.add(em[k])
                cd += val_[k] * custo
                ops += 1
        g = 0.0
        for k in val_:
            r = 0.0 if np.isnan(R[t, k]) else R[t, k]
            g += val_[k] * r
            val_[k] *= 1 + r
        out[t] = (g - cd) / nav
        nav *= 1 + out[t]
    return pd.Series(out, index=dias), ops / ((dias[-1] - INI).days / 365.25)


print("livros de crédito com menos giro...", flush=True)
livros, giro, ref = {}, {}, {}
CACHE = S / "alocador_livros.pkl"
if CACHE.exists():
    livros, giro, ref = pd.read_pickle(CACHE)
for fx, (filtro, n, ck) in ([] if CACHE.exists() else pc.FAIXAS.items()):
    d = df[filtro(df) & (df.date >= INI)]
    forca = d.assign(f=d.groupby("date")[MODELO[fx]].rank(pct=True)).pivot_table(index="date", columns="codigo", values="f")
    res = {}
    for sai, seg in itertools.product((.5, .3), (0, 21, 63)):
        r, ops = simula(forca, B["custo"][ck], n, sai, seg)
        res[(sai, seg)] = (r, ops)
        print(f"  {fx} sai<{sai} segura {seg}d: validação CDI{anual(r.reindex(val)):+.2f} Sharpe {sh(r.reindex(val)):.2f} | "
              f"teste CDI{anual(r.reindex(teste)):+.2f} | {ops:.0f} operações/ano", flush=True)
    melhor = max(res, key=lambda k: sh(res[k][0].reindex(val)))
    livros[fx], giro[fx] = res[melhor]
    ref[fx] = res[(.5, 0)][0]                                              # o livro original
    print(f"  -> {fx}: escolhido sai<{melhor[0]} segura {melhor[1]}d", flush=True)

pd.to_pickle((livros, giro, ref), CACHE)
with contextlib.redirect_stdout(io.StringIO()):
    import estrategias_sinal as es
livros["eurobonds"] = es.livro(es.forca_eb(), es.ed.exc_eb, es.ed.PE, 15, es.e.CUSTO_EXT, -9, es.emis_eb)[0].reindex(dias).fillna(0)
ref["eurobonds"] = livros["eurobonds"]
jur = pd.read_parquet(S / "juros_modelos.parquet")
livros["juros DI 2a"] = jur[("DI2", "tendência 21d")].reindex(dias).fillna(0)
L = pd.DataFrame(livros).fillna(0)
CUSTO = {"conservador": B["custo"]["cons"], "moderado": B["custo"]["mod"], "high yield": B["custo"]["hy"], "eurobonds": es.e.CUSTO_EXT,
         "juros DI 2a": 0.0}
CRED = ["conservador", "moderado", "high yield", "eurobonds"]

# ------------------------------------------------------------------ índices de mercado (sem modelo), desde 2019: o "beta" de cada livro
print("índices de mercado e regimes...", flush=True)
mk = {}
for fx, (filtro, n, ck) in pc.FAIXAS.items():
    m = df[filtro(df)].pivot_table(index="date", columns="codigo", values="prem").notna().reindex(dias).fillna(False)
    mk[fx] = exc.where(m.shift(1, fill_value=False)).mean(axis=1)          # quem era elegível ontem
mk["eurobonds"] = es.ed.exc_eb.where(es.ed.PE.notna()).mean(axis=1).reindex(dias)
mk["juros DI 2a"] = L["juros DI 2a"]
M = pd.DataFrame(mk).fillna(0).clip(-.05, .05)
spr = {fx: df[filtro(df)].groupby("date").spread.median().reindex(dias).ffill() for fx, (filtro, n, ck) in pc.FAIXAS.items()}
spr["eurobonds"] = es.ed.sprd_eb[es.ed.corp].median(axis=1).set_axis(es.ed.fm.reindex(es.ed.sprd_eb.index).values).reindex(dias).ffill() \
    if hasattr(es.ed, "fm") else pd.Series(np.nan, index=dias)
spr = pd.DataFrame(spr)


def hmm_filtrado(X, n=3, refaz=63, min_obs=250):
    """Regimes dos mercados de crédito: probabilidade filtrada (forward, só passado), estado 0 = mais calmo."""
    X = X.dropna()
    out = pd.DataFrame(np.nan, index=X.index, columns=[f"rc{i}" for i in range(n)])
    m = None
    for i in range(min_obs, len(X)):
        if m is None or i % refaz == 0:
            Z = X.iloc[:i]
            mu, sd = Z.mean(), Z.std()
            m = GaussianHMM(n_components=n, covariance_type="diag", n_iter=200, random_state=0).fit(((Z - mu) / sd).to_numpy())
            ordem = np.argsort([c.sum() if np.ndim(c) == 1 else np.trace(c) for c in m.covars_])
            alpha = m.startprob_.copy()
        ll = m._compute_log_likelihood(((X.iloc[[i]] - mu) / sd).to_numpy())[0]
        a = (alpha @ m.transmat_) * np.exp(ll - ll.max())
        alpha = a / a.sum()
        out.iloc[i] = alpha[ordem]
    return out.reindex(dias)


reg = hmm_filtrado(M[CRED].rolling(5).sum())
jf = pd.read_parquet(S / "juros_features.parquet").reindex(dias)

# ------------------------------------------------------------------ features por livro (painel livro x dia) e alvo: retorno do livro de t+2 a t+22
H = 21
lin = []
for k in L.columns:
    x = pd.DataFrame(index=dias)
    for j in (21, 63, 126):
        x[f"mom{j}"] = M[k].rolling(j).sum()
        x[f"mom_livro{j}"] = L[k].rolling(j).sum()
    x["vol63"] = M[k].rolling(63).std()
    if k in spr:
        s = spr[k]
        x["spread"] = s
        x["spread_z"] = (s - s.expanding(126).mean()) / s.expanding(126).std()
        x["dspread21"] = s - s.shift(21)
    for c in ("f_BAMLH0A0HYM2_nivel", "f_BAMLH0A0HYM2_21d", "g_EMB_21d", "g_vix_nivel", "vol21_DI1_2a", "d21_DI1_2a"):
        x[c] = jf[c] if c in jf else np.nan
    x = x.join(reg)
    x["alvo"] = sum(L[k].shift(-j) for j in range(2, H + 2)) if k == "juros DI 2a" else sum(M[k].shift(-j) for j in range(2, H + 2))
    x["livro"] = k
    lin.append(x)
P_ = pd.concat(lin).rename_axis("date").reset_index()
P_ = pd.concat([P_, pd.get_dummies(P_.livro, prefix="l", dtype=float)], axis=1)
FE = [c for c in P_ if c not in ("date", "livro", "alvo")]
# interações livro x regime/estado: cada livro pode reagir diferente
for k in L.columns:
    for c in ("rc0", "rc2", "spread_z", "mom63", "f_BAMLH0A0HYM2_21d"):
        P_[f"{c}_x_{k}"] = P_[c].fillna(0) * P_[f"l_{k}"]
FE = [c for c in P_ if c not in ("date", "livro", "alvo")]

print("walk-forward do alocador...", flush=True)
pred = pd.Series(np.nan, index=P_.index)
datas = np.array(dias)
for i0 in range(dias.searchsorted(pd.Timestamp("2020-07-01")), len(dias), 21):
    hoje = datas[i0]
    tr = P_[(P_.date < datas[max(i0 - H - 2, 0)]) & P_.alvo.notna()]      # embargo: alvo do treino não pode tocar o bloco
    alvo_bl = P_.date.between(hoje, datas[min(i0 + 20, len(dias) - 1)])
    X = tr[FE].fillna(0)
    mu, sd = X.mean(), X.std().replace(0, 1)
    m = Ridge(alpha=1000).fit((X - mu) / sd, tr.alvo)
    pred[alvo_bl] = m.predict((P_.loc[alvo_bl, FE].fillna(0) - mu) / sd)
mu_hat = P_.assign(p=pred).pivot_table(index="date", columns="livro", values="p").reindex(dias)[L.columns] * 252 / H   # % a.a. esperado

# ------------------------------------------------------------------ carteira com caixa
def carteira(alvo, lmax, fin, banda=.05, lag=2):
    """alvo: pesos desejados (fração do PL) decididos no fechamento de t. Executa em t+lag-1, rende a partir de t+lag.
    Caixa = 1 - soma dos livros de crédito; caixa negativo = alavancagem paga a CDI + fin. Juros DI é futuro: não usa caixa."""
    A = alvo.reindex(dias).fillna(0).shift(lag - 1).to_numpy()
    R = L[alvo.columns].to_numpy()
    c = cdi.to_numpy()
    cred = np.array([k in CRED for k in alvo.columns])
    cu = np.array([CUSTO[k] for k in alvo.columns])
    w = np.zeros(len(alvo.columns))                                       # pesos atuais (fração do PL), derivam com o mercado
    out, giro_, caixa = np.zeros(len(dias)), 0.0, np.zeros(len(dias))
    for t in range(1, len(dias)):
        # 1) rende o dia com a carteira de ontem
        cx = 1 - w[cred].sum()
        r_cart = (w * (c[t] + R[t])).sum() * 0 + (w[cred] * (c[t] + R[t, cred])).sum() + (w[~cred] * R[t, ~cred]).sum()
        r_cx = cx * (c[t] + (fin / 252 if cx < 0 else 0))
        r = r_cart + r_cx
        w[cred] = w[cred] * (1 + c[t] + R[t, cred]) / (1 + r)
        out[t] = r - c[t]
        # 2) negocia (decisão de ontem): vende primeiro, compra só com caixa/limite
        a = A[t]
        d = a - w
        mexe = np.abs(d) > banda
        if mexe.any():
            novo = np.where(mexe, a, w)
            vende = np.minimum(novo - w, 0)
            w = w + vende
            compra = np.maximum(novo - w, 0)
            livre = max(lmax - w[cred].sum(), 0)
            if compra[cred].sum() > livre:
                compra[cred] *= livre / compra[cred].sum()
            w = w + compra
            custo = (np.abs(vende) + compra) @ cu
            out[t] -= custo
            giro_ += np.abs(vende).sum() + compra.sum()
        caixa[t] = 1 - w[cred].sum()
    return pd.Series(out, index=dias), giro_ / ((dias[-1] - INI).days / 365.25), pd.Series(caixa, index=dias)


vol = L.rolling(63).std().shift(1) * np.sqrt(252)


def pesos_modelo(lam, lmax, wj_max, cap=1.0):
    """Média-variância por livro: w = mu / (lam * vol^2), sem venda a descoberto; crédito somado <= lmax."""
    w = (mu_hat.rolling(21, min_periods=1).mean() / (lam * vol ** 2)).clip(lower=0)      # previsão suavizada: menos giro
    w[CRED] = w[CRED].clip(upper=cap * lmax)
    s = w[CRED].sum(axis=1)
    w[CRED] = w[CRED].mul(np.minimum(1, lmax / s.replace(0, np.nan)).fillna(1), axis=0)
    w["juros DI 2a"] = w["juros DI 2a"].clip(upper=wj_max)
    return w


def pesos_regime(lmax, wj_max, janela=63):
    """Alocador de regime simples (poucos parâmetros): cada mercado de crédito entra se sua tendência (índice sem modelo, `janela` dias)
    for positiva, com peso inverso à volatilidade, cortado pela probabilidade de estresse do HMM; juros DI entram se o livro estiver em alta."""
    liga = (M[CRED].rolling(janela).sum() > 0).astype(float)
    iv = 1 / vol[CRED]
    w = liga * iv
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0) * lmax
    w = w.mul(1 - reg["rc2"].fillna(0), axis=0)
    w["juros DI 2a"] = wj_max * (L["juros DI 2a"].rolling(janela).sum() > 0) * (1 - 0 * reg["rc2"].fillna(0))
    return w.where(pd.Series(dias >= INI, index=dias), 0, axis=0)[L.columns]


def pesos_spread(base, lmax):
    """(a) mesmo mix fixo, mas o tamanho do crédito segue o percentil do spread de cada mercado (spread alto = mais exposição)."""
    pct = spr.expanding(252).rank(pct=True).reindex(columns=CRED).fillna(.5)
    w = pd.DataFrame({k: base.get(k, 0) * (.25 + .75 * pct[k]) if k in CRED else base.get(k, 0) for k in L.columns}, index=dias)
    s = w[CRED].sum(axis=1)
    w[CRED] = w[CRED].mul(np.minimum(1, lmax / s), axis=0)
    return w


fixo = {"CDI+1": {"conservador": .8, "eurobonds": .2, "juros DI 2a": .25},
        "CDI+5": {"moderado": 1.05, "eurobonds": .45, "juros DI 2a": .5},
        "CDI+10": {"high yield": 1.4, "eurobonds": .6, "juros DI 2a": 1.0}}
alav_c = {"CDI+10": {"moderado": 1.4, "high yield": .3, "eurobonds": .3, "juros DI 2a": 1.0}}   # (c) alavanca o moderado, high yield 1x-ish
PERFIL = {"CDI+1": (1.0, 0.0, .5), "CDI+5": (1.5, .01, 1.0), "CDI+10": (2.0, .015, 2.0)}  # alavancagem máx., spread do financiamento, juros máx.
META = {"CDI+1": 1, "CDI+5": 5, "CDI+10": 10}
const = lambda d: pd.DataFrame({k: d.get(k, 0.0) for k in L.columns}, index=dias)

print("carteiras...", flush=True)
todas, pesos, escolhido, resumo, n_tent = {}, {}, {}, [], 0
for p, (lmax, fin, wj) in PERFIL.items():
    cand = {"atual": (None, .05), "(a) tamanho pelo spread": (pesos_spread(fixo[p], lmax), .05)}
    if p in alav_c:
        cand["(c) alavanca o moderado"] = (const(alav_c[p]), .05)
    for lam, banda in itertools.product((8, 16, 32, 64), (.1, .2)):
        cand[f"alocador ML lam={lam} banda={banda}"] = (pesos_modelo(lam, lmax, wj), banda)
    for jan, banda in itertools.product((21, 63, 126), (.1, .2)):
        cand[f"alocador regime jan={jan} banda={banda}"] = (pesos_regime(lmax, wj / 2, jan), banda)
    res = {}
    for nome, (a, banda) in cand.items():
        if a is None:                                                      # finalista de antes: livros originais, pesos fixos
            r, g, cx = carteira(const(fixo[p]), lmax, fin, banda)
            a = const(fixo[p])
        else:
            r, g, cx = carteira(a, lmax, fin, banda)
        res[nome], pesos[(p, nome)] = (r, g, cx), a
        n_tent += 1
    # escolha SÓ na validação, entre todos os alocadores: bate a meta e maior Sharpe
    aloc = {k: v for k, v in res.items() if k.startswith("alocador")}
    ok = {k: v for k, v in aloc.items() if anual(v[0].reindex(val)) >= META[p]} or aloc
    escolhido[p] = max(ok, key=lambda k: sh(ok[k][0].reindex(val)))
    fam = [max([k for k in aloc if k.startswith(f)], key=lambda k: sh(aloc[k][0].reindex(val))) for f in ("alocador ML", "alocador regime")]
    for nome, (r, g, cx) in res.items():
        if nome.startswith("alocador") and nome not in fam and nome != escolhido[p]:
            continue
        eq = (1 + r.loc[INI:]).cumprod()
        x = r.reindex(teste)
        bs = np.array([anual(pd.Series(b[0][0])) for b in StationaryBootstrap(21, x.to_numpy(), seed=0).bootstrap(1000)])
        todas[(p, nome)] = r
        resumo.append({"perfil": p, "estratégia": nome + (" <- escolhido" if nome == escolhido[p] else ""),
                       "validação CDI+": anual(r.reindex(val)), "validação Sharpe": sh(r.reindex(val)),
                       "teste CDI+": anual(x), "teste Sharpe": sh(x), "IC 5%": np.percentile(bs, 5), "IC 95%": np.percentile(bs, 95),
                       "P(<CDI) %": (bs < 0).mean() * 100, "pior queda vs CDI %": (eq / eq.cummax() - 1).min() * 100,
                       "giro do PL/ano": g, "caixa médio %": cx.loc[INI:].mean() * 100})
tab = pd.DataFrame(resumo).set_index(["perfil", "estratégia"])
pd.set_option("display.width", 250)
print(f"\nconfigurações testadas: {n_tent}")
print(tab.round(2).to_string())
tab.to_csv(S / "alocador.csv")

print("\npesos médios (% do PL) por regime de crédito no teste (rc0 calmo ... rc2 estresse), e hoje:")
rg = reg.reindex(teste).idxmax(axis=1)
for p in PERFIL:
    w = pesos[(p, escolhido[p])].reindex(teste)
    print(p, escolhido[p])
    print((w.groupby(rg).mean() * 100).round(0).to_string())
    print("  hoje:", (pesos[(p, escolhido[p])].iloc[-1] * 100).round(0).to_dict())

# ------------------------------------------------------------------ gráficos
cor = {"atual": "#8C8C8C", "(a) tamanho pelo spread": "#6B8DD6", "(c) alavanca o moderado": "#7A5195", "alocador ML": "#2E8B57",
       "alocador regime": "#EC7000"}
o = dias[dias >= INI]
c_ = cdi.reindex(o)
fig, ax = plt.subplots(3, 1, figsize=(13, 15), sharex=True)
for a, p in zip(ax, PERFIL):
    a.axvspan(teste[0], teste[-1], color="#FFF4EA", zorder=0)
    a.plot(o, (1 + c_).cumprod() * 100, "k--", lw=1.5, label="CDI")
    a.plot(o, ((1 + c_) * (1 + META[p] / 100) ** (1 / 252)).cumprod() * 100, color="black", ls=":", lw=.8, label=f"meta CDI+{META[p]}")
    for (pp, nome), r in todas.items():
        if pp != p:
            continue
        t = tab.loc[(p, nome + (" <- escolhido" if nome == escolhido[p] else ""))]
        f = next(k for k in cor if nome.startswith(k))
        a.plot(o, (1 + c_ + r.reindex(o)).cumprod() * 100, color=cor[f], lw=2.6 if nome == escolhido[p] else 1.4, ls="-" if nome == escolhido[p] or not nome.startswith("alocador ML") else "--",
               label=f"{f}{' (escolhido)' if nome == escolhido[p] else ''}: val CDI{t['validação CDI+']:+.1f} | teste CDI{t['teste CDI+']:+.1f} "
                     f"(IC {t['IC 5%']:+.1f} a {t['IC 95%']:+.1f})")
    a.set_title(p, loc="center", fontweight="bold")
    a.legend(frameon=False, fontsize=8.5, loc="upper left")
    a.grid(alpha=.25)
    a.spines[["top", "right"]].set_visible(False)
fig.suptitle("Carteiras com caixa: atual x ideias (a), (c) x alocadores — fundo laranja = teste intocado 2024-26", fontweight="bold")
fig.tight_layout()
fig.savefig(S / "alocador.png", dpi=130)

fig, ax = plt.subplots(3, 1, figsize=(13, 11), sharex=True)
cores = {"conservador": "#003399", "moderado": "#6B8DD6", "high yield": "#C0392B", "eurobonds": "#2E8B57", "caixa (CDI)": "#D9D9D9"}
for a, p in zip(ax, PERFIL):
    w = pesos[(p, escolhido[p])].reindex(o).fillna(0)
    w["caixa (CDI)"] = (1 - w[CRED].sum(axis=1)).clip(lower=0)
    a.stackplot(o, *[w[k] * 100 for k in cores], labels=list(cores), colors=list(cores.values()), lw=0)
    a.plot(o, w["juros DI 2a"] * 100, color="black", lw=1, label="juros DI 2a (futuro, fora do caixa)")
    a.axvspan(teste[0], teste[-1], color="#EC7000", alpha=.06)
    a.set_title(f"{p}: alocação do modelo escolhido (% do PL)", loc="center", fontweight="bold")
    a.legend(frameon=False, fontsize=8, loc="upper left", ncol=3)
    a.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(S / "alocador_pesos.png", dpi=130)
print("pronto")
