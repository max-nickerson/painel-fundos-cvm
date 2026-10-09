"""
Pesquisa diária de crédito (debêntures): painel papel x dia, features, modelos walk-forward e carteiras com execução realista.
  Elegível no dia t: negociou nos últimos 5 dias úteis e girou >= R$ 1 mi em 21 dias (dá para comprar de verdade).
  Alvo: excesso hedgeado (sobre o CDI) de t+2 a t+22, relativo à média dos elegíveis do dia (ranking).
  Modelos: LightGBM, XGBoost, rede neural (MLP), ridge linear, ensemble; bases: carrego (prêmio) e o modelo mensal antigo.
  Treino: janela crescente, amostra a cada 3 dias, retreino a cada 21 dias, embargo de 24 dias.
  Carteira: força = percentil do score entre os elegíveis da faixa; compra no top 10%, vende abaixo de 50%, 1 por emissor,
            sem stop; decide em t, executa em t+1, rende a partir de t+2; custo medido no intradiário.
Saída: resultado/credito_scores.parquet, resultado/credito_livros.parquet, resultado/credito_resumo.csv
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")
Q = Path(__file__).resolve().parent
S, D_ = Q / "resultado", Q / "dados"
B = pd.read_pickle(S / "base_diaria.pkl")
dias, cdi, cad = B["dias"], B["cdi"], B["cad"]
INI_OOS, VAL_FIM, HZ, RETREINO = pd.Timestamp("2021-01-04"), pd.Timestamp("2023-12-31"), 21, 21
ENTRA, SAI = .90, .50


def excesso_sem_futuro():
    """Retorno diário marcado no último preço NEGOCIADO (não no interpolado até o próximo negócio, que ainda não aconteceu).
    PU par do dia: G = (1+R)*Pi(t-1)/Pi(t) a partir da base; preço: P com preenchimento para frente (até 21 dias)."""
    R, Pi, P, Dd = B["R"], B["Pi"], B["P"], B["Dd"]
    G = (1 + R) * Pi.shift(1) / Pi
    Pf = P.ffill(limit=21)
    Rf = (Pf / Pf.shift(1) * G - 1).where(G.notna())
    Rf = Rf.where(Rf.abs() < .3)
    Hd = B["Hdd"].reindex_like(R).fillna(0)
    return (Rf + Hd).sub(cdi, axis=0), Pf, P, Dd


def painel():
    exc, Pi, P, Dd = excesso_sem_futuro()
    R = B["R"]
    snd = pd.read_parquet(D_ / "snd_negocios.parquet")
    fin = (snd.qtd * snd.pu_med).groupby([snd.date, snd.codigo]).sum().unstack().reindex(index=dias, columns=R.columns).fillna(0)
    obs = P.notna()
    lexc = np.log1p(exc.fillna(0))
    fwd = sum(lexc.shift(-k) for k in range(2, HZ + 2)).where(obs.rolling(HZ + 2).sum().shift(-HZ - 1) >= 1)   # exige negócio no período
    prem = -np.log(Pi / 100) / Dd.clip(lower=.2) * 100                    # prêmio sobre a emissão (pp), com o ÚLTIMO preço negociado
    f = {"prem": prem}
    for k in (5, 21, 63):
        f[f"dprem{k}"] = prem - prem.shift(k)
        f[f"mom{k}"] = lexc.rolling(k).sum()
    f["vol21"], f["vol63"] = exc.rolling(21).std(), exc.rolling(63).std()
    f["queda63"] = exc.clip(upper=0).rolling(63).std()
    f["dias_neg21"] = obs.rolling(21).sum()
    f["fin21"] = np.log1p(fin.rolling(21).sum())
    ult = pd.DataFrame(np.where(obs, np.arange(len(dias))[:, None], np.nan), index=dias, columns=obs.columns).ffill()
    f["sem_negocio"] = np.arange(len(dias))[:, None] - ult                # dias úteis desde o último negócio
    f["D"] = Dd
    venc = pd.DataFrame({k: (cad.venc[k] - dias).days / 365.25 for k in R.columns}, index=dias)
    f["T"] = venc
    elig = obs.rolling(5).sum().ge(1) & fin.rolling(21).sum().ge(1e6) & (venc > .5)
    linhas = []
    for nome, m in f.items():
        linhas.append(m.where(elig).stack().rename(nome))
    df = pd.concat(linhas, axis=1)
    df["alvo"] = fwd.where(elig).stack()
    df.index.names = ["date", "codigo"]
    df = df.reset_index()
    # cadastro e o modelo mensal antigo (conhecido só no 1o dia útil do mês seguinte)
    df = df.join(cad[["indice", "incentivada"]], on="codigo")
    for x in ("DI", "IPCA", "PRE"):
        df[f"idx_{x}"] = df.indice.eq(x).astype(int)
    df["incentivada"] = df.incentivada.astype(int)
    b = B["credito_ml"][["mes", "codigo", "spread", "residuo", "score", "spread_vs_emissao", "emissor_ds3", "empresa"]].copy()
    b["date"] = [dias[min(dias.searchsorted(B["fm"][m], side="right") + 1, len(dias) - 1)] for m in b.mes]
    b = b.drop(columns="mes").sort_values("date")
    df = pd.merge_asof(df.sort_values("date"), b.rename(columns={"score": "score_mensal"}), on="date", by="codigo", direction="backward",
                       tolerance=pd.Timedelta(days=45))
    # ação e notícias do emissor (se os agentes já coletaram)
    cnpj = cad.cnpj.astype(str).str.replace(r"\D", "", regex=True)
    df["cnpj"] = df.codigo.map(cnpj)
    if (D_ / "acoes_diario.parquet").exists():
        a = pd.read_parquet(D_ / "acoes_diario.parquet").reindex(dias).ffill(limit=5)
        a.columns = [str(c).zfill(14) for c in a.columns]
        ra = np.log(a).diff()
        feats = {"acao5": ra.rolling(5).sum(), "acao21": ra.rolling(21).sum(), "acao63": ra.rolling(63).sum(), "acao_vol21": ra.rolling(21).std()}
        for n, m in feats.items():
            s = m.stack().rename(n)
            s.index.names = ["date", "cnpj"]
            df = df.join(s, on=["date", "cnpj"])
    if (D_ / "noticias_cvm.parquet").exists():
        nw = pd.read_parquet(D_ / "noticias_cvm.parquet")
        nw["cnpj"] = nw.cnpj.astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)
        nw = nw.groupby([pd.to_datetime(nw.date), "cnpj"])[["n_fato", "sent_neg", "sent_pos"]].sum()
        for n in ("n_fato", "sent_neg", "sent_pos"):
            m = nw[n].unstack().reindex(dias).fillna(0)
            for k in (30, 90):
                s = m.rolling(k, min_periods=1).sum().stack().rename(f"{n}_{k}")
                s.index.names = ["date", "cnpj"]
                df = df.join(s, on=["date", "cnpj"])
                df[f"{n}_{k}"] = df[f"{n}_{k}"].fillna(0)
    if (S / "juros_features.parquet").exists():                           # regime de mercado e fatores do dia
        jf = pd.read_parquet(S / "juros_features.parquet")
        cols = [c for c in jf if c.startswith(("reg", "g_", "f_", "news_", "pc"))] + ["vol21_DI1_2a", "d21_DI1_2a", "incl_5_1"]
        df = df.join(jf[cols], on="date")
    # rankings no corte do dia (deixa o modelo comparar papéis entre si)
    g = df.groupby("date")
    for c in ("prem", "dprem21", "mom21", "vol63", "fin21", "spread", "residuo"):
        if c in df:
            df[f"rk_{c}"] = g[c].rank(pct=True)
    df["alvo_rel"] = df.alvo - g.alvo.transform("mean")
    return df.sort_values(["date", "codigo"]).reset_index(drop=True)


NAO_FEAT = {"date", "codigo", "alvo", "alvo_rel", "indice", "empresa", "cnpj", "score_mensal"}


def walk_forward(df, modelos):
    feats = [c for c in df if c not in NAO_FEAT and df[c].dtype != object]
    di = df.date.values.astype("datetime64[ns]")
    datas = np.unique(di)
    oos = datas[datas >= np.datetime64(INI_OOS)]
    out = {k: np.full(len(df), np.nan) for k in modelos}
    pos_data = np.searchsorted(datas, di)                                  # índice do dia de cada linha (filtros rápidos)
    for i0 in range(0, len(oos), RETREINO):
        bloco = oos[i0:i0 + RETREINO]
        i_corte = np.searchsorted(datas, bloco[0]) - HZ - 3
        tr = df[(pos_data <= i_corte) & (pos_data % 3 == 0) & df.alvo_rel.notna().to_numpy()]
        if len(tr) < 5000:
            continue
        Xt, yt = tr[feats].fillna(0), tr.alvo_rel.clip(*tr.alvo_rel.quantile([.01, .99]))
        alvo_idx = (di >= bloco[0]) & (di <= bloco[-1])
        Xp = df.loc[alvo_idx, feats].fillna(0)
        for nome, fab in modelos.items():
            Xf = Xt if nome != "rede neural" else Xt.iloc[::4]
            m = fab().fit(Xf, yt if nome != "rede neural" else yt.iloc[::4])
            out[nome][alvo_idx] = m.predict(Xp)
        print(f"  {pd.Timestamp(bloco[0]).date()} treino {len(tr)}", flush=True)
    sc = pd.DataFrame(out, index=df.index)
    sc["ensemble"] = sc.rank(pct=True).groupby(df.date).rank(pct=True).mean(axis=1) if False else \
        pd.concat([sc[k].groupby(df.date).rank(pct=True) for k in modelos], axis=1).mean(axis=1)
    return sc, feats


def simula(forca, exc, elig_compra, custo, n_max, emissor, lag=2):
    """Livro diário por sinal: decide no fechamento de t com a força de t, executa em t+1 e rende a partir de t+2."""
    F = forca.reindex(index=dias, columns=exc.columns).shift(lag - 1)
    EC = elig_compra.reindex(index=dias, columns=exc.columns).fillna(False).to_numpy()   # negociou no dia da execução
    R = exc.to_numpy()
    Fv = F.to_numpy()
    em = np.array([emissor.get(c, c) for c in exc.columns])
    val, out, nav, ops = {}, np.zeros(len(dias)), 1.0, 0
    for t in range(1, len(dias)):
        f, custo_dia = Fv[t - 1], 0.0
        for k in list(val):                                               # só vende num dia em que o papel negociou
            if (not (f[k] >= SAI) and EC[t - 1, k]) or np.isnan(R[max(t - 25, 0):t, k]).all():
                custo_dia += val.pop(k) * custo
                ops += 1
        if len(val) < n_max:
            emis_h = {em[k] for k in val}
            cand = np.where((f >= ENTRA) & EC[t - 1])[0]
            for k in cand[np.argsort(-f[cand])]:
                livre = nav - sum(val.values())
                if len(val) >= n_max or livre <= 1e-9:
                    break
                if k in val or em[k] in emis_h:
                    continue
                val[k] = min(nav / n_max, livre)
                emis_h.add(em[k])
                custo_dia += val[k] * custo
                ops += 1
        ganho = 0.0
        for k in val:
            r = 0.0 if np.isnan(R[t, k]) else R[t, k]
            ganho += val[k] * r
            val[k] *= 1 + r
        out[t] = (ganho - custo_dia) / nav
        nav *= 1 + out[t]
    return pd.Series(out, index=dias), ops


def resumo(r):
    r = r[r.index >= INI_OOS]
    o = {}
    for nome, x in (("validação 21-23", r[r.index <= VAL_FIM]), ("teste 24-26", r[r.index > VAL_FIM]), ("total", r)):
        eq = (1 + x).cumprod()
        o[f"{nome} CDI+ % a.a."] = ((1 + x).prod() ** (252 / max(len(x), 1)) - 1) * 100
        o[f"{nome} Sharpe"] = x.mean() / x.std() * np.sqrt(252) if x.std() else np.nan
        o[f"{nome} pior queda %"] = (eq / eq.cummax() - 1).min() * 100
    return o


FAIXAS = {"conservador": (lambda d: d.spread.between(-1, 3) & (d.D <= 5), 30, "cons"),
          "moderado": (lambda d: d.spread.between(-1, 8), 25, "mod"),
          "high yield": (lambda d: d.spread.between(2, 40), 20, "hy")}

if __name__ == "__main__":
    print("painel diário...", flush=True)
    df = painel()
    print(f"  {len(df)} linhas papel x dia, {df.codigo.nunique()} debêntures, {df.shape[1]} colunas", flush=True)
    modelos = {
        "lightgbm": lambda: LGBMRegressor(objective="huber", n_estimators=300, learning_rate=.03, num_leaves=31, min_child_samples=200,
                                          subsample=.7, subsample_freq=1, colsample_bytree=.6, reg_lambda=10, verbose=-1, random_state=0),
        "xgboost": lambda: XGBRegressor(objective="reg:pseudohubererror", n_estimators=300, learning_rate=.03, max_depth=5, min_child_weight=100,
                                        subsample=.7, colsample_bytree=.6, reg_lambda=10, tree_method="hist", random_state=0, verbosity=0),
        "rede neural": lambda: make_pipeline(StandardScaler(), MLPRegressor((64, 32), alpha=1e-2, early_stopping=True, max_iter=300, random_state=0)),
        "ridge": lambda: make_pipeline(StandardScaler(), Ridge(alpha=100))}
    print("walk-forward...", flush=True)
    sc, feats = walk_forward(df, modelos)
    df = pd.concat([df, sc], axis=1)
    df["carrego"] = df.prem.fillna(-9) + 0 * df.spread.fillna(0)
    df.to_parquet(S / "credito_scores.parquet")
    exc = excesso_sem_futuro()[0]
    emissor = df.drop_duplicates("codigo").set_index("codigo").empresa.dropna().to_dict()
    elig_compra = B["P"].notna()                                          # houve negócio naquele dia
    res, livros = {}, {}
    for fx, (filtro, n, ck) in FAIXAS.items():
        d = df[filtro(df) & (df.date >= INI_OOS)]
        for nome in list(modelos) + ["ensemble", "carrego", "score_mensal"]:
            forca = d.assign(f=d.groupby("date")[nome].rank(pct=True)).pivot_table(index="date", columns="codigo", values="f")
            r, ops = simula(forca, exc, elig_compra, B["custo"][ck], n, emissor)
            livros[(fx, nome)] = r
            res[(fx, nome)] = resumo(r) | {"operações/ano": ops / ((dias[-1] - INI_OOS).days / 365.25)}
            print(fx, nome, {k: round(v, 2) for k, v in res[(fx, nome)].items() if "total" in k}, flush=True)
    tab = pd.DataFrame(res).T
    pd.set_option("display.width", 260)
    print(tab.round(2).to_string())
    tab.to_csv(S / "credito_resumo.csv")
    pd.DataFrame(livros).to_parquet(S / "credito_livros.parquet")
    imp = LGBMRegressor(objective="huber", n_estimators=300, learning_rate=.03, num_leaves=31, min_child_samples=200, verbose=-1) \
        .fit(df.loc[df.alvo_rel.notna(), feats].fillna(0), df.loc[df.alvo_rel.notna(), "alvo_rel"]).feature_importances_
    print(pd.Series(imp, feats).sort_values(ascending=False).head(20).to_string())
