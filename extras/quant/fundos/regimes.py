"""
Regimes de mercado ponto-a-ponto (só usam informação até t) para ligar/desligar ou escalar qualquer estratégia.
Cada regime é uma Series em DIAS com valores em [0, 1] = fração da exposição permitida (1 = regime bom para a estratégia).

Uso típico dentro de uma estratégia:
    from regimes import aplica_regime
    def minha(..., regime="nenhum", custo_mult=1, lag=0):
        e = ...                              # excesso diário já pronto
        return aplica_regime(e, regime)      # escala o excesso pelo regime de t-1 (sem olhar o futuro)
Para estratégias com pesos W, prefira escalar W antes de `carteira`: W = W.mul(regime_serie(regime).reindex(W.index).ffill(), axis=0).

Regimes disponíveis (REGIMES): nenhum, vix_baixo, vix_contango, sp_tendencia, ibov_tendencia, risco_global (combo),
credito_ok (HYG vs IEF), selic_corte / selic_alta (ciclo do Copom), brl_calmo, hmm_sp, hmm_ibov, hmm_propria (HMM no próprio excesso),
dd_stop (corta após queda da própria estratégia), e o inverso de cada um com prefixo "inv_".
"""
import logging

import numpy as np
import pandas as pd

from base import BOVA, CDI, DIAS, ETF, IDX, PTAX, sgs

logging.getLogger("hmmlearn").setLevel(logging.ERROR)
_CACHE = {}


def _us(s):
    return s.reindex(DIAS, method="ffill")


def _cache(f):
    def g(*a):
        k = (f.__name__,) + a
        if k not in _CACHE:
            _CACHE[k] = f(*a).reindex(DIAS).ffill().fillna(1.0).clip(0, 1)
        return _CACHE[k]
    return g


@_cache
def vix_baixo():
    v = IDX["^VIX"].dropna()
    return _us((v < v.rolling(252, min_periods=120).quantile(.8)).astype(float))


@_cache
def vix_contango():
    v, v3 = IDX["^VIX"].dropna(), IDX.get("^VIX3M", pd.Series(dtype=float)).dropna()
    if v3.empty:
        return vix_baixo()
    return _us((v / v3.reindex(v.index).ffill() < 1).astype(float))


@_cache
def sp_tendencia():
    p = IDX["^GSPC"].dropna()
    return _us((p > p.rolling(200, min_periods=150).mean()).astype(float))


@_cache
def ibov_tendencia():
    p = BOVA.dropna()
    return (p > p.rolling(200, min_periods=150).mean()).astype(float)


@_cache
def credito_ok():
    h, i = ETF["HYG"].dropna(), ETF["IEF"].dropna()
    q = np.log(h / i.reindex(h.index).ffill())
    return _us((q > q.rolling(100, min_periods=60).mean()).astype(float))


@_cache
def risco_global():
    return (vix_baixo() + sp_tendencia() + credito_ok()) / 3


@_cache
def selic_corte():
    s = sgs(432).reindex(DIAS).ffill()                       # meta Selic
    return (s.diff(126) < 0).astype(float)


@_cache
def selic_alta():
    s = sgs(432).reindex(DIAS).ffill()
    return (s.diff(126) > 0).astype(float)


@_cache
def brl_calmo():
    r = np.log(PTAX).diff()
    v = r.rolling(21, min_periods=15).std()
    return (v < v.rolling(504, min_periods=250).quantile(.75)).astype(float)


def _hmm(r, refit=126, ini=750):
    """HMM gaussiano de 2 estados walk-forward: re-estima a cada `refit` dias só com dados até t e devolve a probabilidade
    FILTRADA (recursão forward, sem suavização para trás) do estado calmo em cada t."""
    from hmmlearn.hmm import GaussianHMM
    from scipy.stats import multivariate_normal as mvn
    r = r.dropna()
    X = pd.DataFrame({"r": r, "v": r.rolling(10, min_periods=5).std()}).dropna()
    out = pd.Series(np.nan, index=X.index)
    for k in range(ini, len(X), refit):
        m = GaussianHMM(2, covariance_type="full", n_iter=100, random_state=0).fit(X.iloc[:k].values)
        calmo = int(np.argmin(m.means_[:, 1]))
        a = m.predict_proba(X.iloc[k - 250:k].values)[-1]          # estado em t-1 (filtrado = último ponto da janela passada)
        for t in range(k, min(k + refit, len(X))):
            x = X.iloc[t].values
            lik = np.array([mvn.pdf(x, m.means_[s], m.covars_[s], allow_singular=True) for s in range(2)])
            a = (a @ m.transmat_) * lik
            a = a / a.sum() if a.sum() > 0 else np.array([.5, .5])
            out.iloc[t] = a[calmo]
    return out


@_cache
def hmm_sp():
    p = IDX["^GSPC"].dropna()
    return _us((_hmm(np.log(p).diff()) > .5).astype(float))


@_cache
def hmm_ibov():
    return (_hmm(np.log(BOVA.dropna()).diff()) > .5).astype(float)


REGIMES = {"nenhum": None, "vix_baixo": vix_baixo, "vix_contango": vix_contango, "sp_tendencia": sp_tendencia,
           "ibov_tendencia": ibov_tendencia, "risco_global": risco_global, "credito_ok": credito_ok, "selic_corte": selic_corte,
           "selic_alta": selic_alta, "brl_calmo": brl_calmo, "hmm_sp": hmm_sp, "hmm_ibov": hmm_ibov}


def regime_serie(nome):
    """Série em [0,1] do regime (valor de t usa info até t). Prefixo inv_ inverte."""
    if nome in (None, "nenhum"):
        return pd.Series(1.0, index=DIAS)
    inv = nome.startswith("inv_")
    s = REGIMES[nome[4:] if inv else nome]()
    return 1 - s if inv else s


def _dd_stop(e, lim=.05, pausa=21):
    """Desliga a estratégia por `pausa` dias após queda de `lim` do pico da própria curva (usa só o passado)."""
    eq = (1 + e.fillna(0)).cumprod()
    on = np.ones(len(e))
    pico, desl = 1.0, 0
    v = eq.values
    for i in range(1, len(v)):
        if desl > 0:
            desl -= 1
            on[i] = 0
            if desl == 0:
                pico = v[i - 1]
            continue
        pico = max(pico, v[i - 1])
        if v[i - 1] / pico - 1 < -lim:
            desl = pausa
            on[i] = 0
    return pd.Series(on, index=e.index)


def _hmm_propria(e):
    return (_hmm(e.fillna(0)) > .5).astype(float).reindex(e.index).shift(1).fillna(1.0)


def aplica_regime(e, nome="nenhum"):
    """Escala o excesso diário e(t) pelo regime conhecido em t-1 (já que a decisão de t-1 executa em t, use isso como aproximação conservadora:
    regime de t-2 -> posição de t-1 -> retorno de t). Inclui custo de liga/desliga implícito? Não: some o custo na própria estratégia se o regime girar muito."""
    if nome in (None, "nenhum"):
        return e
    if nome.startswith("dd_stop") or nome == "hmm_propria":
        return e * serie_exposicao(e, nome)
    s = regime_serie(nome).reindex(e.index).ffill().fillna(1.0).shift(2).fillna(1.0)
    return e * s


def serie_exposicao(e, nome):
    """Fração de exposição aplicada ao retorno de t (conhecida em t-2 para regimes de mercado; t-1 da própria curva)."""
    if nome in (None, "nenhum"):
        return pd.Series(1.0, index=e.index)
    if nome == "dd_stop":                       # cota de t-1 decide em t-1, executa no fechamento de t, vale para o retorno de t+1
        return _dd_stop(e).shift(1).fillna(1.0)
    if nome == "hmm_propria":
        return _hmm_propria(e).shift(1).fillna(1.0)
    return regime_serie(nome).reindex(e.index).ffill().fillna(1.0).shift(2).fillna(1.0)


REG_PADRAO = ["nenhum", "risco_global", "vix_contango", "sp_tendencia", "ibov_tendencia", "credito_ok", "hmm_sp", "hmm_ibov",
              "selic_corte", "brl_calmo", "dd_stop", "inv_risco_global"]


def com_regime(f, regimes=None, custo_troca=.001):
    """Devolve uma cópia do Fundo com 'regime' como dimensão extra da grade. O regime escala o excesso diário;
    cada liga/desliga paga custo_troca (10 bps por 100% de troca). A escolha do regime é feita no IS pelo motor, como qualquer parâmetro."""
    import copy
    regimes = regimes or REG_PADRAO
    memo = {}
    base = f.func

    def func(regime="nenhum", custo_mult=1, lag=0, **p):
        k = (tuple(sorted(p.items())), custo_mult, lag)
        if k not in memo:
            memo[k] = base(**p, custo_mult=custo_mult, lag=lag)
        e = memo[k]
        s = serie_exposicao(e, regime)
        return e * s - s.diff().abs().fillna(0) * custo_troca * custo_mult

    g = copy.copy(f)
    g.func = func
    g.grade = {**f.grade, "regime": regimes}
    return g
