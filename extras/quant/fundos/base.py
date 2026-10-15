"""Dados e utilitários comuns dos 20 fundos (calendário B3, CDI, câmbio, conversão de estratégias em dólar para reais com hedge)."""
import io
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

AQUI = Path(__file__).resolve().parent
D = AQUI / "dados"
DQ = AQUI.parent / "dados"
RQ = AQUI.parent / "resultado"


def sgs(cod, ini="2005-01-01"):
    f = D / f"sgs_{cod}.parquet"
    if f.exists() and (time.time() - f.stat().st_mtime) < 86400:
        return pd.read_parquet(f).v
    out = []
    try:
        for a in range(pd.Timestamp(ini).year, pd.Timestamp.today().year + 1, 10):
            u = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados?formato=json&dataInicial=01/01/{a}&dataFinal=31/12/{a + 9}"
            for t in range(6):
                try:
                    out.append(pd.DataFrame(requests.get(u, timeout=60).json()))
                    break
                except (requests.RequestException, ValueError):
                    if t == 5:
                        raise
                    time.sleep(5 * (t + 1))
        d = pd.concat(out)
        s = pd.Series(d.valor.astype(float).values, index=pd.to_datetime(d.data, dayfirst=True)).sort_index()
        s = s[~s.index.duplicated()]
        s.to_frame("v").to_parquet(f)
        return s
    except (requests.RequestException, ValueError):
        return pd.read_parquet(f).v


CDI = sgs(12) / 100
DIAS = CDI.index[CDI.index >= "2008-01-01"]
CDI = CDI.reindex(DIAS)
CDI_AA = (1 + CDI) ** 252 - 1
PTAX = sgs(1).reindex(DIAS).ffill(limit=5)


def y(nome):
    return pd.read_parquet(D / f"y_{nome}.parquet")


IDX = y("idx")
ETF = y("etf")
FXY = y("fx")
ADR = y("adr")
BRL_LOC = y("br_local")
DIAS_US = IDX["^GSPC"].dropna().index
TB_US = (IDX["^IRX"].reindex(DIAS_US).ffill() / 100 / 252)
BOVA = pd.read_parquet(DQ / "eq_idx.parquet")["BOVA11.SA"].reindex(DIAS).ffill(limit=5)
R_IBOV = BOVA.pct_change(fill_method=None).fillna(0)
SPX_USD = IDX["^GSPC"].reindex(DIAS_US).ffill().pct_change(fill_method=None).fillna(0)
BIS = pd.read_parquet(D / "bis_juros_politica.parquet").sort_index().ffill()


def limpa(r, lim=.25):
    """Retornos diários: zera saltos absurdos (erros de base / desdobramentos não ajustados)."""
    return r.where(r.abs() < lim, 0.0)


def limpa_fx(r, lim=.04):
    """Moedas: remove só erros de cotação (salto > lim que se desfaz no dia seguinte); mantém crises de verdade (ex.: lira turca)."""
    vira = (r.abs() > lim) & ((r + r.shift(-1)).abs() < .3 * r.abs())
    return r.where(~(vira | vira.shift(1, fill_value=False)), 0.0).where(r.abs() < .5, 0.0)


def brl(ex_us):
    """Excesso diário em dólar (sobre o T-bill) -> excesso em reais com hedge cambial (a mesma coisa, no calendário da B3)."""
    e = ex_us.fillna(0).copy()
    e.index = pd.DatetimeIndex(e.index).normalize()
    acum = np.log1p(e).cumsum()
    acum = acum[~acum.index.duplicated(keep="last")].reindex(DIAS.union(acum.index)).ffill().reindex(DIAS).fillna(0)
    return np.expm1(acum.diff().fillna(0))


def carteira(W, R, custo, lag=0, aluguel=0.0):
    """W decidido no fechamento de t (+lag dias); executado no fechamento seguinte; rende a partir daí.
    R: retornos em excesso (sobre o caixa) por ativo. Custo por unidade de giro; aluguel a.a. sobre posições vendidas."""
    W = W.reindex(R.index).fillna(0).shift(1 + lag).fillna(0)
    r = (W.shift(1) * R).sum(axis=1) - W.diff().abs().sum(axis=1) * custo - W.clip(upper=0).abs().sum(axis=1) * aluguel / 252
    return r.fillna(0)


def vol_alvo(W, R, alvo=.10, janela=63, teto=3.0):
    """Escala a carteira para a volatilidade-alvo (estimada só com o passado)."""
    rp = (W.shift(1) * R).sum(axis=1)
    v = rp.rolling(janela, min_periods=40).std().shift(1) * np.sqrt(252)
    return W.mul((alvo / v).clip(upper=teto).fillna(0), axis=0)


def fim_mes(idx):
    p = pd.Series(pd.DatetimeIndex(idx).to_period("M"), index=idx)
    return p.ne(p.shift(-1))


def fim_semana(idx):
    p = pd.Series(pd.DatetimeIndex(idx).to_period("W-FRI"), index=idx)
    return p.ne(p.shift(-1))


def _so(W, marca):
    W = W.copy()
    W.loc[~marca.values] = np.nan
    return W.ffill().fillna(0)


def mensal(W):
    return _so(W, fim_mes(W.index))


def semanal(W):
    return _so(W, fim_semana(W.index))
