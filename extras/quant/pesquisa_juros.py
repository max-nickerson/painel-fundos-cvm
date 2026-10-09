"""
Pesquisa diária de juros (DAP 5 anos e DI1 2 anos): features estatísticas/álgebra linear, regimes (HMM) e vários modelos,
tudo walk-forward e com execução realista.
  Execução: decisão no fechamento de t (ajuste de t só sai à noite) -> opera em t+1 -> ganha o retorno de t+1 a t+2 (posição defasada 2 dias).
  Custo: 1 bp de taxa no DAP e 0,5 bp no DI1 por unidade girada (x duration do contrato).
  Tamanho: volatilidade-alvo de 5% a.a. por livro, com a vol estimada só com o passado (63 dias).
  Treino: janela crescente, retreino a cada 21 dias úteis, embargo igual ao horizonte do alvo (10 dias) + 2.
  Validação 2021-2023 (escolha do modelo) e teste intocado 2024-2026.
Saída: resultado/juros_modelos.parquet (retorno diário de cada modelo x livro) e resultado/juros_resumo.csv
"""
import warnings

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from arch import arch_model
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

warnings.filterwarnings("ignore")
from pathlib import Path
S = Path(__file__).resolve().parent / "resultado"
D_ = Path(__file__).resolve().parent / "dados"
B = pd.read_pickle(S / "base_diaria.pkl")
dias, cdi, cv = B["dias"], B["cdi"], B["curvas"].ffill(limit=3)
H, RETREINO, INI_OOS = 10, 21, pd.Timestamp("2021-01-04")
VAL_FIM = pd.Timestamp("2023-12-31")
ALVO_VOL = .05
LIVROS = {"DAP5": (B["r_dap5"], cv["DAP_5a"], 1.0, 4.2), "DI2": (B["r_di2"], cv["DI1_2a"], .5, 1.8)}   # retorno, taxa, custo (bp), duration


# ------------------------------------------------------------------ features
def pca_expandida(X, k=3, refaz=63, min_obs=250):
    """Fatores (nível, inclinação, curvatura) das variações diárias da curva; autovetores reestimados só com o passado."""
    dX = X.diff()
    out = pd.DataFrame(np.nan, index=X.index, columns=[f"pc{i + 1}" for i in range(k)])
    W = None
    for i in range(len(X)):
        if i >= min_obs and (W is None or i % refaz == 0):
            Z = dX.iloc[1:i].dropna()
            mu, sd = Z.mean(), Z.std()
            val, vec = np.linalg.eigh(((Z - mu) / sd).cov().to_numpy())
            W = (vec[:, ::-1][:, :k], mu, sd)
            sinal = np.sign(W[0][np.abs(W[0]).argmax(0), range(k)])     # orientação estável dos autovetores
            W = (W[0] * sinal, mu, sd)
        if W is not None and dX.iloc[i].notna().all():
            out.iloc[i] = ((dX.iloc[i] - W[1]) / W[2]).to_numpy() @ W[0]
    return out


def garch_vol(x, refaz=63, min_obs=500):
    """Volatilidade prevista para amanhã por GARCH(1,1) (em bps/dia), parâmetros reestimados só com o passado."""
    x = x.dropna() * 100
    out = pd.Series(np.nan, index=x.index)
    par = None
    for i in range(min_obs, len(x)):
        if par is None or i % refaz == 0:
            par = arch_model(x.iloc[:i], mean="Zero", vol="GARCH", p=1, q=1, rescale=False).fit(disp="off").params
        w, a, b = par["omega"], par["alpha[1]"], par["beta[1]"]
        s2 = np.var(x.iloc[max(0, i - 63):i])
        for v in x.iloc[max(0, i - 63):i]:
            s2 = w + a * v ** 2 + b * s2
        out.iloc[i - 1] = np.sqrt(s2)
    return out.reindex(dias)


def hmm_filtrado(Xf, n=3, refaz=63, min_obs=500):
    """Probabilidade FILTRADA de cada regime (usa só o passado: algoritmo forward), estados ordenados pela volatilidade."""
    X = Xf.dropna()
    out = pd.DataFrame(np.nan, index=X.index, columns=[f"reg{i}" for i in range(n)])
    m, alpha = None, None
    for i in range(min_obs, len(X)):
        if m is None or i % refaz == 0:
            Z = X.iloc[:i]
            m = GaussianHMM(n_components=n, covariance_type="diag", n_iter=200, random_state=0).fit(((Z - Z.mean()) / Z.std()).to_numpy())
            mu, sd = Z.mean(), Z.std()
            ordem = np.argsort([np.trace(np.diag(c)) if np.ndim(c) == 1 else np.trace(c) for c in m.covars_])
            alpha = m.startprob_.copy()
        ll = m._compute_log_likelihood(((X.iloc[[i]] - mu) / sd).to_numpy())[0]
        a = (alpha @ m.transmat_) * np.exp(ll - ll.max())
        alpha = a / a.sum()
        out.iloc[i] = alpha[ordem]
    return out.reindex(dias)


def monta_features():
    f = pd.DataFrame(index=dias)
    di = cv[[c for c in cv if c.startswith("DI1")]]
    for c in ["DI1_1a", "DI1_2a", "DI1_5a", "DAP_5a", "DAP_10a"]:
        for k in (5, 21, 63):
            f[f"d{k}_{c}"] = cv[c] - cv[c].shift(k)
        f[f"z63_{c}"] = (cv[c] - cv[c].rolling(63).mean()) / cv[c].rolling(63).std()
        f[f"vol21_{c}"] = cv[c].diff().rolling(21).std() * 100
    f["incl_5_1"], f["incl_10_2"] = cv.DI1_5a - cv.DI1_1a, cv.DI1_10a - cv.DI1_2a
    f["curvatura"] = 2 * cv.DI1_3a - cv.DI1_1a - cv.DI1_8a
    f["implicita_5"] = cv.DI1_5a - cv.DAP_5a
    cdi_aa = ((1 + cdi) ** 252 - 1) * 100
    f["carrego_1a"], f["carrego_2a"] = cv.DI1_1a - cdi_aa, cv.DI1_2a - cdi_aa
    for c in ["incl_5_1", "implicita_5", "carrego_1a"]:
        f[f"d21_{c}"] = f[c] - f[c].shift(21)
        f[f"z252_{c}"] = (f[c] - f[c].rolling(252).mean()) / f[c].rolling(252).std()
    print("  PCA...", flush=True)
    pc = pca_expandida(di)
    for c in pc:
        f[f"{c}_5d"], f[f"{c}_21d"] = pc[c].rolling(5).sum(), pc[c].rolling(21).sum()
    print("  GARCH...", flush=True)
    f["garch_dap5"] = garch_vol(cv.DAP_5a.diff())
    f["garch_di2"] = garch_vol(cv.DI1_2a.diff())
    usd = B["ptax"].reindex(dias).ffill()
    f["usd_5d"], f["usd_21d"], f["usd_vol21"] = usd.pct_change(5), usd.pct_change(21), usd.pct_change().rolling(21).std()
    glob = []
    if (D_ / "mercado_global.parquet").exists():                         # fatores globais (agente de dados)
        g = pd.read_parquet(D_ / "mercado_global.parquet").reindex(dias).ffill(limit=5)
        for t in [c for c in ["^VIX", "^MOVE", "^BVSP", "EWZ", "DX-Y.NYB", "BZ=F", "HYG", "EMB", "^TNX"] if c in g]:
            n = t.strip("^").replace("-", "").replace("=", "").replace(".", "")
            f[f"g_{n}_5d"], f[f"g_{n}_21d"] = g[t].pct_change(5), g[t].pct_change(21)
            glob.append(n)
        if "^VIX" in g:
            f["g_vix_nivel"] = g["^VIX"]
    if (D_ / "fred.parquet").exists():
        fr = pd.read_parquet(D_ / "fred.parquet").reindex(dias).ffill(limit=5)
        for c in [c for c in ["DGS2", "DGS10", "BAMLH0A0HYM2", "BAMLEMCBPIOAS", "T10Y2Y"] if c in fr]:
            f[f"f_{c}_21d"] = fr[c] - fr[c].shift(21)
            f[f"f_{c}_nivel"] = fr[c]
    if (D_ / "noticias_gdelt.parquet").exists():                         # tom das notícias macro (agente de notícias)
        nw = pd.read_parquet(D_ / "noticias_gdelt.parquet")
        macro = nw[~nw.chave.str.startswith("emissor", na=False)] if "chave" in nw else nw.iloc[:0]
        if len(macro):
            t = macro.groupby(pd.to_datetime(macro.date)).tom.mean().reindex(dias)
            f["news_tom_5d"], f["news_tom_21d"] = t.rolling(5, min_periods=1).mean(), t.rolling(21, min_periods=3).mean()
    if (D_ / "analistas.parquet").exists():                               # Focus: consenso x Top 5 (analistas mais certeiros)
        an = pd.read_parquet(D_ / "analistas.parquet").reindex(dias).ffill(limit=10)
        f = f.join(an[[c for c in an if c.startswith(("an_gap", "an_rev4s"))]])
        for h, v in (("ano", "DI1_1a"), ("prox", "DI1_2a")):
            for q in ("top5", "consenso"):
                c = f"an_Selic_{q}_{h}"
                if c in an:
                    f[f"an_{q}_selic_{h}_menos_curva"] = an[c] - cv[v]          # o que o analista espera x o que a curva precifica
        if "an_IPCA_top5_prox" in an:
            f["an_top5_ipca_menos_implicita"] = an["an_IPCA_top5_prox"] - (cv.DI1_2a - cv.DAP_2a)
    print("  HMM...", flush=True)
    xr = pd.DataFrame({"ddi2": cv.DI1_2a.diff(5), "dap": cv.DAP_5a.diff(5), "vol": cv.DI1_2a.diff().rolling(21).std(), "usd": usd.pct_change(5)})
    if "g_VIX_5d" in f:
        xr["vix"] = f["g_VIX_5d"]
    reg = hmm_filtrado(xr)
    f = f.join(reg)
    return f, reg


def walk_forward(X, y, ret_fut, modelos):
    """Probabilidade de 'receber' ganhar nos próximos H dias, para cada modelo, só com o passado."""
    datas = X.index[X.index >= INI_OOS]
    pred = {k: pd.Series(np.nan, index=X.index) for k in modelos}
    for i0 in range(0, len(datas), RETREINO):
        bloco = datas[i0:i0 + RETREINO]
        fim_treino = X.index[X.index.get_loc(bloco[0]) - H - 2]
        tr = X.index[(X.index <= fim_treino)]
        tr = tr[y.loc[tr].notna()]
        Xt, yt = X.loc[tr], y.loc[tr]
        if len(tr) < 400 or yt.nunique() < 2:
            continue
        for nome, fab in modelos.items():
            if nome == "hmm":                                              # retorno médio por regime no treino
                regs = Xt[[c for c in Xt if c.startswith("reg")]]
                m = (regs.mul(ret_fut.loc[tr], axis=0).sum() / regs.sum())
                p = (X.loc[bloco, regs.columns] * m.values).sum(axis=1)
                pred[nome].loc[bloco] = .5 + np.tanh(p / ret_fut.loc[tr].std()) / 2
                continue
            mod = fab().fit(Xt, yt)
            pred[nome].loc[bloco] = mod.predict_proba(X.loc[bloco])[:, 1]
    return pred


def posicao(p, banda=.04, escala=.15):
    s = (p - .5)
    return (np.sign(s) * ((s.abs() - banda).clip(lower=0) / escala).clip(upper=1)).where(p.notna())


def pnl(pos, ret, custo_bp, dur):
    vol = ret.rolling(63, min_periods=40).std().shift(1) * np.sqrt(252)
    alav = (ALVO_VOL / vol).clip(upper=4)
    q = (pos * alav).fillna(0)
    return q.shift(2) * ret.fillna(0) - q.diff().abs().shift(1).fillna(0) * custo_bp / 1e4 * dur, q


def resumo(r):
    r = r[r.index >= INI_OOS]
    out = {}
    for nome, x in (("validação 21-23", r[r.index <= VAL_FIM]), ("teste 24-26", r[r.index > VAL_FIM]), ("total", r)):
        eq = (1 + x).cumprod()
        out[f"{nome} ret a.a. %"] = x.mean() * 252 * 100
        out[f"{nome} Sharpe"] = x.mean() / x.std() * np.sqrt(252) if x.std() else np.nan
        out[f"{nome} pior queda %"] = (eq / eq.cummax() - 1).min() * 100
    return out


if __name__ == "__main__":
    print("features...", flush=True)
    X, reg = monta_features()
    X.to_parquet(S / "juros_features.parquet")
    modelos = {
        "logística": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=.05, max_iter=2000)),
        "lightgbm": lambda: LGBMClassifier(n_estimators=200, learning_rate=.03, num_leaves=8, min_child_samples=60, subsample=.8,
                                           subsample_freq=1, colsample_bytree=.6, reg_lambda=5, verbose=-1, random_state=0),
        "xgboost": lambda: XGBClassifier(n_estimators=200, learning_rate=.03, max_depth=3, min_child_weight=20, subsample=.8,
                                         colsample_bytree=.6, reg_lambda=5, random_state=0, verbosity=0),
        "rede neural": lambda: make_pipeline(StandardScaler(), MLPClassifier((32, 16), alpha=1e-2, early_stopping=True, max_iter=500, random_state=0)),
        "hmm": None}
    res, series = {}, {}
    for livro, (ret, taxa, custo, dur) in LIVROS.items():
        fwd = sum(ret.shift(-k) for k in range(2, H + 2))                # o que a posição de hoje ganha (executando com 2 dias)
        y = (fwd > 0).astype(float).where(fwd.notna())
        Xl = X.dropna(thresh=int(X.shape[1] * .8)).ffill().fillna(0)
        print(f"walk-forward {livro} ({Xl.shape[1]} features)...", flush=True)
        pred = walk_forward(Xl, y.reindex(Xl.index), fwd.reindex(Xl.index), modelos)
        pred["ensemble"] = pd.concat([pred[k] for k in ("logística", "lightgbm", "xgboost", "rede neural")], axis=1).mean(axis=1)
        sig = pd.read_csv(S / "sinal_juros.csv", index_col=0)
        for nome, p in pred.items():
            r, q = pnl(posicao(p.reindex(dias)), ret, custo, dur)
            series[(livro, nome)] = r
            res[(livro, nome)] = resumo(r) | {"giro/ano": q.diff().abs().mean() * 252}
        for nome, base_ in (("sempre recebido", pd.Series(1.0, index=dias)), ("tendência 21d", -np.sign(taxa - taxa.shift(21)))):
            r, q = pnl(base_, ret, custo, dur)
            series[(livro, nome)] = r
            res[(livro, nome)] = resumo(r) | {"giro/ano": q.diff().abs().mean() * 252}
    tab = pd.DataFrame(res).T
    pd.set_option("display.width", 250)
    print(tab.round(2).to_string())
    tab.to_csv(S / "juros_resumo.csv")
    pd.DataFrame(series).to_parquet(S / "juros_modelos.parquet")
