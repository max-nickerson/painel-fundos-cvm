"""
Motor dos fundos: simula um fundo de verdade e mede contra o benchmark.
  - estratégia devolve o EXCESSO diário sobre o CDI já com custos de negociação (decisão em t, execução em t+1)
  - fundo = CDI (caixa) + excesso; alavancagem acima de 100% do PL paga CDI + spread
  - despesas: administração/gestão, custódia+auditoria+CVM, performance 20% sobre o benchmark com linha d'água, cobrada semestralmente
  - escolha de parâmetros só dentro da amostra (IS); fora da amostra (OOS) intocado
  - robustez: P(bater o benchmark OOS) por bootstrap estacionário, PBO (CSCV), Sharpe deflacionado, custo x2, execução +1 dia
"""
import itertools
import warnings
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from scipy.stats import norm

warnings.filterwarnings("ignore")


@dataclass
class Fundo:
    nome: str
    categoria: str
    benchmark: str                                  # chave em BENCH
    tese: str
    estrutura: str
    func: Callable                                  # func(**params, custo_mult=1, lag=0) -> excesso diário sobre o CDI
    grade: dict = field(default_factory=dict)
    adm: float = .015                               # taxa de gestão+administração a.a.
    perf: float = .20                               # taxa de performance sobre o benchmark
    despesas: float = .0015                         # custódia, auditoria, CVM, etc. a.a.
    inicio: str = "2012-01-01"
    corte: str = "2021-01-01"                       # início do fora da amostra


def aplica_taxas(excesso, cdi, bench, f: Fundo):
    """Cota líquida: CDI + excesso - despesas - gestão; performance semestral sobre o benchmark com linha d'água."""
    bruto = (cdi + excesso).fillna(0)
    r = bruto - (f.adm + f.despesas) / 252
    cota, hwm, ult_cota, ult_bench = 1.0, 1.0, 1.0, 1.0
    b_acum = 1.0
    out = np.zeros(len(r))
    fim_sem = pd.Series(r.index.to_period("Q-JUN" if False else "M"), index=r.index)
    crist = (fim_sem.ne(fim_sem.shift(-1))) & r.index.month.isin([6, 12])
    for i, (ri, bi, c) in enumerate(zip(r.values, bench.reindex(r.index).fillna(0).values, crist.values)):
        nova = cota * (1 + ri)
        b_acum *= 1 + bi
        if c and f.perf > 0:
            exc = nova / ult_cota - b_acum / ult_bench
            if exc > 0 and nova > hwm:
                taxa = f.perf * exc * ult_cota
                nova -= taxa
                hwm = nova
            ult_cota, ult_bench = nova, b_acum
        out[i] = nova / cota - 1
        cota = nova
    return pd.Series(out, index=r.index)


def anual(x):
    return ((1 + x).prod() ** (252 / max(len(x), 1)) - 1) * 100


def metricas(r, b, cdi):
    """r: retorno diário do fundo; b: do benchmark; cdi: do CDI."""
    r, b, cdi = r.dropna(), b.reindex(r.index).fillna(0), cdi.reindex(r.index).fillna(0)
    a = r - b
    ex = r - cdi
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1
    te = a.std() * np.sqrt(252)
    beta = np.cov(r, b)[0, 1] / b.var() if b.var() > 0 else np.nan
    mens = (1 + a).groupby(a.index.to_period("M")).prod() - 1
    neg = ex[ex < 0]
    return {"retorno a.a. %": anual(r), "benchmark a.a. %": anual(b), "ativo a.a. pp": anual(r) - anual(b),
            "vol a.a. %": r.std() * np.sqrt(252) * 100, "Sharpe": ex.mean() / ex.std() * np.sqrt(252) if ex.std() > 0 else np.nan,
            "Sortino": ex.mean() / neg.std() * np.sqrt(252) if len(neg) > 2 else np.nan,
            "IR vs bench": a.mean() / a.std() * np.sqrt(252) if a.std() > 0 else np.nan, "tracking error %": te * 100,
            "beta vs bench": beta, "pior queda %": dd.min() * 100,
            "Calmar": (anual(r) - anual(cdi)) / abs(dd.min() * 100) if dd.min() < 0 else np.nan,
            "meses batendo bench %": (mens > 0).mean() * 100, "assimetria": r.skew(), "CVaR 5% diário %": r[r <= r.quantile(.05)].mean() * 100}


def bootstrap_prob(a, n=2000, bloco=21, seed=0):
    """P(retorno ativo anualizado > 0) por bootstrap estacionário (blocos com tamanho médio `bloco`)."""
    rng = np.random.default_rng(seed)
    x = np.log1p(a.dropna().to_numpy())
    T = len(x)
    if T < 60:
        return np.nan
    novo = rng.random((n, T)) < 1 / bloco
    novo[:, 0] = True
    pos = np.arange(T)
    ini_bloco = np.maximum.accumulate(np.where(novo, pos, 0), axis=1)
    sorteio = rng.integers(T, size=(n, T))
    idx = (np.take_along_axis(sorteio, ini_bloco, axis=1) + pos - ini_bloco) % T
    return (x[idx].sum(axis=1) > 0).mean() * 100


def pbo(M, S=10):
    """Probabilidade de overfitting (CSCV, Bailey et al.): M = retornos ativos diários (T x N variantes)."""
    M = M.dropna(how="all").fillna(0)
    if M.shape[1] < 4 or len(M) < S * 20:
        return np.nan
    blocos = np.array_split(np.arange(len(M)), S)
    lam = []
    for comb in itertools.combinations(range(S), S // 2):
        is_ = np.concatenate([blocos[i] for i in comb])
        oos = np.concatenate([blocos[i] for i in range(S) if i not in comb])
        sr = lambda X: X.mean() / X.std().replace(0, np.nan)
        best = sr(M.iloc[is_]).idxmax()
        rk = sr(M.iloc[oos]).rank(pct=True)[best]
        rk = min(max(rk, 1e-6), 1 - 1e-6)
        lam.append(np.log(rk / (1 - rk)))
    return (np.array(lam) <= 0).mean() * 100


def dsr(a, n_tent, sr_var):
    """Sharpe deflacionado (Bailey & López de Prado): prob. de o IR verdadeiro ser > 0 dado n tentativas."""
    a = a.dropna()
    s, T = a.mean() / a.std(), len(a)
    if not np.isfinite(s) or T < 60:
        return np.nan
    emc = .5772
    sr0 = np.sqrt(max(sr_var, 1e-12)) * ((1 - emc) * norm.ppf(1 - 1 / max(n_tent, 2)) + emc * norm.ppf(1 - 1 / (max(n_tent, 2) * np.e)))
    g3, g4 = a.skew(), a.kurt() + 3
    return norm.cdf((s - sr0) * np.sqrt(T - 1) / np.sqrt(max(1 - g3 * s + (g4 - 1) / 4 * s ** 2, 1e-9))) * 100


def roda(f: Fundo, cdi, bench, log=print):
    """Roda a grade, escolhe no IS pelo IR vs benchmark, avalia OOS e a robustez."""
    combos = [dict(zip(f.grade, v)) for v in itertools.product(*f.grade.values())] or [{}]
    ini, corte = pd.Timestamp(f.inicio), pd.Timestamp(f.corte)
    var = {}
    for p in combos:
        try:
            e = f.func(**p)
        except Exception as ex:
            log(f"   {f.nome} {p}: erro {ex}")
            continue
        e = e[e.index >= ini]
        if e.abs().sum() == 0:
            continue
        var[str(p)] = (p, e)
    if not var:
        return None
    b = bench.reindex(cdi.index).fillna(0)
    ativos = pd.DataFrame({k: (cdi + e).reindex(cdi.index) - b for k, (p, e) in var.items()})
    ativos = ativos[ativos.index >= max(ini, min(e.index[0] for _, e in var.values()))]
    is_ = ativos[ativos.index < corte]
    ir_is = is_.mean() / is_.std() * np.sqrt(252)
    melhor = ir_is.idxmax()
    p, e = var[melhor]
    liq = aplica_taxas(e, cdi.reindex(e.index), b.reindex(e.index), f)
    oos = liq[liq.index >= corte]
    m_tot, m_oos = metricas(liq, b, cdi), metricas(oos, b, cdi)
    a_oos = oos - b.reindex(oos.index)
    rob = {"variantes": len(var), "PBO %": pbo(ativos), "P(bater bench OOS) %": bootstrap_prob(a_oos),
           "Sharpe deflac. OOS %": dsr(a_oos, len(var), (ir_is / np.sqrt(252)).var()),
           "mediana OOS das variantes (pp)": np.nanmedian([anual((cdi + e2).reindex(oos.index).fillna(0)) - anual(b.reindex(oos.index))
                                                         for _, e2 in var.values()]),
           "% variantes > bench OOS": np.mean([anual((cdi + e2).reindex(oos.index).fillna(0)) > anual(b.reindex(oos.index))
                                               for _, e2 in var.values()]) * 100}
    for nome_s, kw in (("custo x2", {"custo_mult": 2}), ("execução +1 dia", {"lag": 1})):
        try:
            e2 = f.func(**p, **kw)
            l2 = aplica_taxas(e2[e2.index >= ini], cdi.reindex(e2[e2.index >= ini].index), b.reindex(e2[e2.index >= ini].index), f)
            rob[f"OOS {nome_s} (pp)"] = anual(l2[l2.index >= corte]) - anual(b.reindex(l2[l2.index >= corte].index))
        except Exception:
            rob[f"OOS {nome_s} (pp)"] = np.nan
    return {"fundo": f, "params": p, "liquido": liq, "bruto": cdi.reindex(e.index) + e, "total": m_tot, "oos": m_oos, "rob": rob,
            "is_ir": ir_is[melhor], "ativos": ativos}
