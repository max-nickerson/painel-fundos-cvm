"""
10 estratégias de ações e derivativos (Brasil e EUA), diárias, de 2015 a 2026, contra CDI e Ibovespa (BOVA11).
Decide no fechamento de t, executa no fechamento de t+1 (rende a partir de t+2); custos por perna; aluguel no short.
Retornos em reais: estratégias em dólar entram com hedge cambial (excesso sobre o T-bill + CDI).
  1  Bollinger short EUA     : vende a ação do S&P 500 que fecha acima da banda superior (20d, 2 desvios), recompra na média; hedge SPY
  2  Bollinger short Brasil  : idem no Ibovespa, hedge BOVA11
  3  Bollinger long Brasil   : compra abaixo da banda inferior, vende na média; caixa no CDI
  4  Momentum Brasil         : 20% do Ibovespa com maior retorno de 12 meses (sem o último), mensal
  5  Baixa volatilidade BR   : 20% com menor volatilidade de 3 meses, mensal
  6  Tendência em futuros    : mini índice e mini dólar comprados/vendidos pela tendência (1, 3 e 12 meses), semanal, sobre o CDI
  7  Venda coberta BOVA11    : compra BOVA11 e vende a call de ~5% fora do dinheiro do mês seguinte (preços reais da B3)
  8  Venda de put BOVA11     : vende a put de ~5% fora do dinheiro, garantia em CDI (preços reais da B3)
  9  Volatilidade EUA (VIX)  : SVXY (vendido em volatilidade) só quando VIX < VIX 3 meses (curva em contango); senão T-bill
  10 Notícias (GDELT)        : comprado nas ações cujo tom das notícias mais melhorou, vendido nas que mais pioraram (semanal)
Saídas: resultado/equity.csv, equity_diario.csv, equity.png
"""
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import requests

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
Q = Path(__file__).resolve().parent
D_, S = Q / "dados", Q / "resultado"
INI, MEIO = pd.Timestamp("2015-01-02"), pd.Timestamp("2020-12-31")
C_BR, C_US, ALUGUEL_BR, ALUGUEL_US = .0008, .0003, .02, .005


def sgs(cod, ini="2014-01-01"):
    """Série do Banco Central (com tentativas e cache local: a API às vezes devolve vazio)."""
    import time
    f = D_ / f"sgs_{cod}.parquet"
    try:
        out = []
        for a in range(pd.Timestamp(ini).year, pd.Timestamp.today().year + 1, 10):
            u = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados?formato=json&dataInicial=01/01/{a}&dataFinal=31/12/{a + 9}"
            for t in range(5):
                try:
                    out.append(pd.DataFrame(requests.get(u, timeout=60).json()))
                    break
                except (requests.RequestException, ValueError):
                    if t == 4:
                        raise
                    time.sleep(5 * (t + 1))
        d = pd.concat(out)
        s = pd.Series(d.valor.astype(float).values, index=pd.to_datetime(d.data, dayfirst=True)).sort_index()
        s = s[~s.index.duplicated()]
        s.to_frame("v").to_parquet(f)
        return s
    except (requests.RequestException, ValueError):
        print(f"  BCB indisponível: usando série {cod} salva", flush=True)
        return pd.read_parquet(f).v


print("dados...", flush=True)
cdi = sgs(12) / 100
ptax = sgs(1)
dias = cdi.index[cdi.index >= "2014-01-01"]
cdi = cdi.reindex(dias)
idx = pd.read_parquet(D_ / "eq_idx.parquet")
us = pd.read_parquet(D_ / "eq_us.parquet")
br = pd.read_parquet(D_ / "eq_br.parquet").reindex(dias).ffill(limit=5)
bova = idx["BOVA11.SA"].reindex(dias).ffill(limit=5)
dias_us = idx["SPY"].dropna().index
tbill_us = (idx["^IRX"].reindex(dias_us).ffill() / 100 / 252)
anual = lambda x: ((1 + x).prod() ** (252 / max(len(x), 1)) - 1) * 100


def para_brl(r_us_excesso):
    """Excesso diário em dólar (sobre o T-bill), com hedge cambial: soma ao CDI no calendário brasileiro."""
    e = r_us_excesso.copy()
    e.index = e.index.normalize()
    acum = np.log1p(e.fillna(0)).cumsum().reindex(dias, method="ffill").fillna(0)
    return cdi + np.expm1(acum.diff().fillna(0))


def carteira(W, R, custo, aluguel=0.0, lag=2):
    """W: pesos decididos no fechamento de t (positivos = comprado). Retorno a partir de t+lag; custo no giro; aluguel nos vendidos."""
    W = W.reindex(R.index).fillna(0)
    Wx = W.shift(lag - 1).fillna(0)                                       # posição executada no fechamento de t+1
    r = (Wx.shift(1) * R).sum(axis=1) - (Wx.diff().abs().sum(axis=1) * custo) - (Wx.clip(upper=0).abs().sum(axis=1) * aluguel / 252)
    return r.fillna(0)


def bollinger(P, lado, janela=20, k=2.0, max_pos=20):
    """Estado por ação: entra quando fecha fora da banda (acima para short, abaixo para long), sai quando volta à média."""
    m, sd = P.rolling(janela).mean(), P.rolling(janela).std()
    entra = (P > m + k * sd) if lado == "short" else (P < m - k * sd)
    sai = (P < m) if lado == "short" else (P > m)
    est = pd.DataFrame(np.where(entra, 1.0, np.where(sai, 0.0, np.nan)), index=P.index, columns=P.columns).ffill().fillna(0)
    n = est.sum(axis=1)
    return est.div(np.maximum(n, max_pos), axis=0)                        # peso 1/N, no máximo 100% (1/max_pos cada se houver poucos)


def mensal(score, top=.2):
    """Top 20% do score no último dia útil do mês, pesos iguais, mantidos o mês seguinte."""
    fim = pd.Series(score.index.to_period("M"), index=score.index)
    reb = fim.ne(fim.shift(-1))
    r = score.rank(axis=1, pct=True)
    W = (r >= 1 - top).astype(float)
    W = W.div(W.sum(axis=1).replace(0, np.nan), axis=0)
    return W.where(reb).ffill().fillna(0)


est = {}
# 1 e 2. Bollinger short, hedge com o índice (neutro): excesso = -soma(w (r_i - r_índice)) - custos - aluguel
print("1-2. Bollinger short...", flush=True)
Pu = us.reindex(dias_us).ffill(limit=5)
Ru = Pu.pct_change(fill_method=None)
Wu = bollinger(Pu, "short")
r_us = carteira(-Wu, Ru.sub(idx["SPY"].reindex(dias_us).pct_change(fill_method=None), axis=0), C_US, ALUGUEL_US)
est["1 Bollinger short EUA (hedge SPY)"] = para_brl(r_us)
Rb = br.pct_change(fill_method=None)
rb_idx = bova.pct_change(fill_method=None)
Wb = bollinger(br, "short")
est["2 Bollinger short Brasil (hedge BOVA11)"] = cdi + carteira(-Wb, Rb.sub(rb_idx, axis=0), C_BR, ALUGUEL_BR)
# 3. Bollinger long (reversão) Brasil, sem hedge, caixa no CDI
print("3. Bollinger long...", flush=True)
Wl = bollinger(br, "long")
est["3 Bollinger long Brasil (reversão)"] = cdi * (1 - Wl.shift(2).sum(axis=1).fillna(0)) + carteira(Wl, Rb, C_BR)
# 4 e 5. Fatores Brasil, mensal
print("4-5. fatores...", flush=True)
mom = br.shift(21) / br.shift(252) - 1
est["4 Momentum Brasil (12-1 meses)"] = carteira(mensal(mom), Rb, C_BR)
vol = Rb.rolling(63, min_periods=50).std()
est["5 Baixa volatilidade Brasil"] = carteira(mensal(-vol.where(br.notna())), Rb, C_BR)
# 6. Tendência em mini índice (BOVA11 - CDI) e mini dólar (PTAX - carrego), sobre o CDI
print("6. futuros...", flush=True)
X = pd.DataFrame({"WIN": rb_idx - cdi, "WDO": ptax.reindex(dias).ffill(limit=5).pct_change(fill_method=None)
                  - (cdi - tbill_us.reindex(dias).ffill())})
cum = np.log1p(X.fillna(0)).cumsum()
sig = sum(np.sign(cum - cum.shift(j)) for j in (21, 63, 252)) / 3
pos = (sig * .10 / (X.rolling(63, min_periods=40).std() * np.sqrt(252))).clip(-2, 2)
sem = pd.Series(dias.to_period("W-FRI"), index=dias)
pos[~sem.ne(sem.shift(-1)).values] = np.nan
pos = pos.ffill().shift(1)
est["6 Tendência mini índice + mini dólar"] = cdi + (pos.shift(1) * X).sum(axis=1).fillna(0) - (pos.diff().abs() * .0002).sum(axis=1)


# 7 e 8. Opções de BOVA11 com preços reais da B3
def opcoes(tipo, otm=.05):
    print(f"7-8. opções {tipo}...", flush=True)
    o = pd.read_parquet(D_ / "opcoes_b3.parquet")
    v = pd.read_parquet(D_ / "vista_b3.parquet")
    o = o[(o.ativo == "BOVA11") & (o.tipo == tipo)]
    s = v[v.ticker == "BOVA11"].set_index("data").fech.reindex(dias).ffill(limit=5)
    vencs = sorted(o.venc.dropna().unique())
    vencs = [pd.Timestamp(x) for x in vencs if pd.Timestamp(x).day >= 10 and pd.Timestamp(x).day <= 22]  # mensais
    vencs = sorted(set(pd.Series(vencs).groupby(pd.Series(vencs).dt.to_period("M")).max()))
    valor = pd.Series(np.nan, index=dias)
    ret = pd.Series(0.0, index=dias)
    for v0, v1 in zip(vencs[:-1], vencs[1:]):
        d0 = dias[dias > v0]
        if not len(d0) or d0[0] >= v1:
            continue
        d0 = d0[0]                                                         # abre no 1o dia útil depois do vencimento anterior
        S0 = s.get(d0)
        c = o[(o.data == d0) & (o.venc == v1) & (o.negocios > 0)]
        if c.empty or not S0 == S0:
            continue
        alvo = S0 * (1 + otm if tipo == "C" else 1 - otm)
        serie = c.iloc[(c.strike - alvo).abs().argsort().iloc[0]]
        premio = serie.oferta_compra if serie.oferta_compra > 0 else serie.fech * .95   # vende na melhor oferta de compra
        K = serie.strike
        hist = o[o.serie == serie.serie].set_index("data").fech.reindex(dias).ffill()
        per = dias[(dias >= d0) & (dias <= v1)]
        opc = hist.reindex(per).ffill().fillna(premio)
        opc.iloc[0] = premio
        ST = s.reindex(per).ffill()
        opc.iloc[-1] = max(ST.iloc[-1] - K, 0) if tipo == "C" else max(K - ST.iloc[-1], 0)   # liquida no vencimento pelo intrínseco
        if tipo == "C":                                                    # comprado 1 BOVA11, vendido 1 call
            val = ST - opc
        else:                                                              # vendido 1 put, garantia K aplicada no CDI
            caixa = K * (1 + cdi.reindex(per).fillna(0)).cumprod() / (1 + cdi.reindex(per).fillna(0).iloc[0])
            val = caixa - opc + premio * 0                                 # o prêmio recebido fica no caixa (somado abaixo)
            val = val + premio
        r = val.pct_change().fillna(0)                                    # capital: S0 - prêmio (call) ou K (put)
        r.iloc[0] = -.0005                                                 # custo de montar (o dia da montagem não rende)
        ret.loc[per[1:]] = r.iloc[1:].values
        valor.loc[per] = val.values
    return ret.where(dias >= pd.Timestamp(vencs[0]) if vencs else True, 0)


est["7 Venda coberta BOVA11 (call 5% OTM)"] = opcoes("C")
est["8 Venda de put BOVA11 (5% OTM, garantia CDI)"] = opcoes("P")
# 9. Volatilidade EUA: SVXY quando VIX < VIX3M
print("9. VIX...", flush=True)
vix, vix3 = idx["^VIX"].reindex(dias_us).ffill(), idx["^VIX3M"].reindex(dias_us).ffill()
contango = (vix / vix3 < 1).astype(float)
r_svxy = idx["SVXY"].reindex(dias_us).pct_change(fill_method=None).fillna(0)
w9 = contango.shift(2).fillna(0)
r9 = w9 * (r_svxy - tbill_us) - w9.diff().abs() * C_US
est["9 Venda de volatilidade EUA (SVXY com filtro VIX)"] = para_brl(r9)
# 10. Notícias (GDELT): tom do emissor
print("10. notícias...", flush=True)
g = pd.read_parquet(D_ / "noticias_gdelt.parquet")
g = g[g.chave.str.startswith("emissor_")]
mapa = pd.read_csv(D_ / "acoes_mapa.csv", dtype=str)
mapa["cnpj"] = mapa.cnpj.str.zfill(14)
tk = dict(zip("emissor_" + mapa.cnpj, mapa.ticker))
g["ticker"] = g.chave.map(tk)
g = g[g.ticker.isin(br.columns)]
tom = g.pivot_table(index="date", columns="ticker", values="tom").reindex(dias).ffill(limit=5)
volu = g.pivot_table(index="date", columns="ticker", values="volume").reindex(dias).fillna(0)
z = (tom.rolling(21, min_periods=10).mean() - tom.rolling(126, min_periods=60).mean()) / tom.rolling(126, min_periods=60).std()
z = z.where(volu.rolling(21).sum() >= 5)
sem = pd.Series(dias.to_period("W-FRI"), index=dias)
reb = sem.ne(sem.shift(-1))
rk = z.rank(axis=1, pct=True)
n_ok = z.notna().sum(axis=1)
Wn = ((rk >= 2 / 3).astype(float) - (rk <= 1 / 3).astype(float)).where(n_ok >= 6)
Wn = Wn.div(Wn.abs().sum(axis=1).replace(0, np.nan), axis=0).where(reb).ffill().fillna(0) * 2   # 100% comprado, 100% vendido
est["10 Notícias GDELT (long-short por tom)"] = cdi + carteira(Wn, Rb[Wn.columns], C_BR, ALUGUEL_BR)
print(f"   ações com notícia: {g.ticker.nunique()}", flush=True)

# ----------------------------------------------------------------- resultados
o = dias[dias >= INI]
bench = {"CDI": cdi, "Ibovespa (BOVA11)": rb_idx.fillna(0)}
tab = {}
for k, r in {**est, **bench}.items():
    x = r.reindex(o).fillna(0)
    ex = x - cdi.reindex(o)
    eq = (1 + x).cumprod()
    a, b = x[x.index <= MEIO], x[x.index > MEIO]
    tab[k] = {"retorno a.a. %": anual(x), "CDI+ a.a.": anual(x) - anual(cdi.reindex(o)), "2015-20 CDI+": anual(a) - anual(cdi.reindex(a.index)),
              "2021-26 CDI+": anual(b) - anual(cdi.reindex(b.index)), "vol a.a. %": x.std() * np.sqrt(252) * 100,
              "Sharpe (vs CDI)": ex.mean() / ex.std() * np.sqrt(252) if ex.std() > 0 else np.nan,
              "t-stat": ex.mean() / ex.std() * np.sqrt(len(ex)) if ex.std() > 0 else np.nan,
              "pior queda %": (eq / eq.cummax() - 1).min() * 100}
tab = pd.DataFrame(tab).T
pd.set_option("display.width", 220)
print(tab.round(2).to_string())
tab.to_csv(S / "equity.csv")
pd.DataFrame({**est, **bench}).reindex(o).to_csv(S / "equity_diario.csv")

fig, axs = plt.subplots(5, 2, figsize=(14, 17), sharex=True)
eq_cdi, eq_ibov = (1 + cdi.reindex(o)).cumprod() * 100, (1 + rb_idx.reindex(o).fillna(0)).cumprod() * 100
for ax, (k, r) in zip(axs.flat, est.items()):
    t = tab.loc[k]
    eq = (1 + r.reindex(o).fillna(0)).cumprod() * 100
    ax.plot(o, eq_ibov, color="#BFBFBF", lw=1.1, label="Ibovespa")
    ax.plot(o, eq_cdi, "k--", lw=1.1, label="CDI")
    cor = "#2E7D4F" if t["CDI+ a.a."] > 0 else "#B23A3A"
    ax.plot(o, eq, color=cor, lw=1.8, label="estratégia")
    ax.set_title(f"{k}\nCDI{t['CDI+ a.a.']:+.1f} a.a. | Sharpe {t['Sharpe (vs CDI)']:.2f} | queda {t['pior queda %']:.0f}%", fontsize=9.5,
                 loc="left", fontweight="bold")
    ax.set_yscale("log")
    ax.grid(alpha=.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=7, frameon=False, loc="upper left")
fig.suptitle("10 estratégias de ações e derivativos, 2015-2026, em R$ (escala log) — verde = acima do CDI", fontweight="bold", fontsize=13)
fig.tight_layout(rect=[0, 0, 1, .975])
fig.savefig(S / "equity.png", dpi=120)
print("pronto")
