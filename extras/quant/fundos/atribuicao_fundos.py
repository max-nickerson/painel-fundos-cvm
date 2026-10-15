"""
Atribuição profunda dos vencedores da rodada 1 (fundos 02, 06, 11, 12, 15 e 20).
Reproduz cada série com os parâmetros escolhidos (lógica COPIADA dos módulos originais, que não são alterados), decompõe por ativo,
por ano e por negócio (episódio contínuo de posição), e roda os testes de fragilidade.
Saídas: resultado/atribuicao.pkl (contrib/trades por fundo), resultado/atribuicao_saida.txt (tabelas usadas no caderno).
Uso: PYTHONIOENCODING=utf-8 python -W ignore atribuicao_fundos.py
"""
import contextlib
import io
import pickle
import sys

import numpy as np
import pandas as pd

import fundos_global as fg
import travas as tv
from base import D, BIS, CDI, CDI_AA, DIAS, DIAS_US, ETF, IDX, TB_US, RQ, brl, limpa, mensal, semanal, vol_alvo, AQUI

OUT = AQUI / "resultado"
TXT = None                                                                  # aberto só quando roda como script
CORTE = pd.Timestamp("2021-01-01")


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    if TXT:
        TXT.write(s + "\n")


def md(df, nd=2):
    return df.round(nd).to_markdown()


# ======================================================================= utilitários comuns
def partes(W, R, custo, lag=0, custo_mult=1, alvo=None):
    """Mesma conta de fg._ex/carteira, mas por ativo. Devolve (contrib diária por ativo em USD, posição efetiva Wh, custo de alavancagem)."""
    if alvo:
        W = vol_alvo(W, R, alvo)
    alav = (W.abs().sum(axis=1) - 1).clip(lower=0).shift(2).fillna(0) * .005 / 252
    Wx = W.reindex(R.index).fillna(0).shift(1 + lag).fillna(0)
    Wh = Wx.shift(1).fillna(0)
    C = (Wh * R).fillna(0) - Wx.diff().abs().fillna(0) * custo * custo_mult
    return C, Wh, alav.reindex(R.index).fillna(0)


def episodios(Wh, C, R, extra=None):
    """Negócio = sequência contínua de dias com posição de mesmo sinal num ativo. retorno = retorno composto do ativo no sentido da posição."""
    out = []
    for a in Wh.columns:
        s = np.sign(Wh[a].fillna(0)).values
        if not (s != 0).any():
            continue
        quebra = np.r_[True, s[1:] != s[:-1]]
        g = np.cumsum(quebra)
        for k in np.unique(g[s != 0]):
            idx = np.where(g == k)[0]
            sl = Wh.index[idx]
            lado = s[idx[0]]
            r = R[a].iloc[idx].fillna(0)
            lin = {"ativo": a, "lado": "comprado" if lado > 0 else "vendido", "entrada": sl[0].date(), "saida": sl[-1].date(), "dias": len(idx),
                   "peso_medio": Wh[a].iloc[idx].abs().mean(), "retorno %": (np.prod(1 + lado * r.values) - 1) * 100,
                   "contrib pp": C[a].iloc[idx].sum() * 100, "contrib OOS pp": C[a].iloc[idx][sl >= CORTE].sum() * 100}
            if extra:
                for nome, X in extra.items():
                    lin[nome] = X[a].iloc[idx].sum() * 100
            out.append(lin)
    return pd.DataFrame(out)


def por_ano(C):
    return (C.groupby(C.index.year).sum() * 100)


def top(tr, k=10, col="contrib pp"):
    t = tr.sort_values(col, ascending=False)
    return t.head(k), t.tail(k).iloc[::-1]


def resumo_ativos(C, corte=CORTE):
    return pd.DataFrame({"total pp": C.sum() * 100, "OOS pp": C[C.index >= corte].sum() * 100,
                         "IS pp": C[C.index < corte].sum() * 100}).sort_values("OOS pp", ascending=False)


def anual_pp(x):
    """Excesso anualizado (pp a.a.) de uma série diária de excesso."""
    x = x.dropna()
    return ((1 + x).prod() ** (252 / max(len(x), 1)) - 1) * 100


RES = {}


# ======================================================================= F11 carry de moedas
def carry_partes(n=3, filtro=0, lado="ls", alvo=.08, teto=.25, excluir=(), haircut=1.0, lag=0, custo_mult=1, so=None):
    v, spot, dif = fg._fx()
    cols = [c for c in dif.columns if c not in excluir and (so is None or c in so)]
    v, spot, dif = v[cols], spot[cols], dif[cols]
    car = dif.shift(1) / 252 * haircut
    R = (spot + car).dropna(how="all")
    rk = dif.rank(axis=1, ascending=False)
    W = (rk <= n).astype(float) - ((rk > dif.notna().sum(axis=1).values[:, None] - n) & dif.notna()).astype(float) * (lado == "ls")
    if filtro:
        mom = np.log(v) - np.log(v).shift(63)
        W = W.where(~((W > 0) & (mom < 0)), 0).where(~((W < 0) & (mom > 0)), 0)
    vol = spot.rolling(63, min_periods=40).std()
    W = (W / vol).div((W / vol).abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0).clip(-teto, teto)
    C, Wh, alav = partes(mensal(W), R[W.columns], fg.C_FX, lag, custo_mult, alvo)
    Cs, Cc = (Wh * spot.reindex(R.index)).fillna(0), (Wh * car.reindex(R.index)).fillna(0)
    return C, Wh, alav, Cs, Cc, R[W.columns]


def carry_serie(**kw):
    C, Wh, alav, *_ = carry_partes(**kw)
    return brl(C.sum(axis=1) - alav)


def f11():
    p("\n\n# ===================== 11 CARRY DE MOEDAS (n=3, filtro=0, ls)")
    C, Wh, alav, Cs, Cc, R = carry_partes()
    ex = brl(C.sum(axis=1) - alav)
    orig = fg.carry_fx(3, 0, "ls")
    p(f"checagem: reproduzido {anual_pp(ex[ex.index >= CORTE]):.2f} pp a.a. OOS vs original {anual_pp(orig[orig.index >= CORTE]):.2f}; "
      f"diferença máx diária {(ex - orig).abs().max():.2e}")
    nome = {k: MO for k, (MO, s) in fg.MOEDA.items()}
    ren = lambda X: X.rename(columns=lambda c: c.replace("=X", ""))
    tab = pd.DataFrame({"spot pp": Cs.sum(), "carry pp": Cc.sum(), "total pp": C.sum(),
                        "spot OOS": Cs[Cs.index >= CORTE].sum(), "carry OOS": Cc[Cc.index >= CORTE].sum(), "total OOS": C[C.index >= CORTE].sum(),
                        "% dias comprado OOS": (Wh[Wh.index >= CORTE] > 0).mean(), "% dias vendido OOS": (Wh[Wh.index >= CORTE] < 0).mean()})
    tab.iloc[:, :6] *= 100
    tab.iloc[:, 6:] *= 100
    p("\n## Contribuição por moeda (soma de excesso diário, pp; positivo = ganhou)\n" + md(ren(tab.T).T.sort_values("total OOS", ascending=False), 1))
    p("\n## Por ano (pp) — maiores moedas\n" + md(ren(por_ano(C)[C.sum().abs().sort_values().index[-10:]]).assign(TOTAL=por_ano(C).sum(axis=1) - por_ano(alav.to_frame())[0]), 1))
    p("\n## Por ano: spot x carry (pp)\n" + md(pd.DataFrame({"spot": por_ano(Cs).sum(axis=1), "carry": por_ano(Cc).sum(axis=1),
                                                            "custos+alav": por_ano(C).sum(axis=1) - por_ano(Cs).sum(axis=1) - por_ano(Cc).sum(axis=1) - por_ano(alav.to_frame())[0],
                                                            "total": por_ano(C).sum(axis=1) - por_ano(alav.to_frame())[0]}), 1))
    tr = episodios(ren(Wh), ren(C), ren(R), {"spot pp": ren(Cs), "carry pp": ren(Cc)})
    # diferencial médio no negócio
    v, spot, dif = fg._fx()
    tr["dif juros médio %"] = [dif[a + "=X"].loc[str(e):str(s)].mean() * 100 for a, e, s in zip(tr.ativo, tr.entrada, tr.saida)]
    b, w = top(tr)
    p("\n## 10 melhores negócios\n" + md(b.set_index("ativo"), 2))
    p("\n## 10 piores negócios\n" + md(w.set_index("ativo"), 2))
    b, w = top(tr[pd.to_datetime(tr.saida) >= CORTE], col="contrib OOS pp")
    p("\n## 10 melhores negócios OOS (2021+)\n" + md(b.set_index("ativo"), 2))
    p("\n## 10 piores negócios OOS (2021+)\n" + md(w.set_index("ativo"), 2))
    # testes de fragilidade
    p("\n## Testes de fragilidade (excesso a.a. sobre o CDI, pp)")
    EMHI = ["TRY=X", "ZAR=X", "BRL=X", "COP=X", "HUF=X", "MXN=X", "INR=X", "IDR=X"]
    G10 = ["EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X", "JPY=X", "CAD=X", "CHF=X", "NOK=X", "SEK=X"]
    LATAM = ["MXN=X", "BRL=X", "CLP=X", "COP=X"]
    linhas = []
    for rot, kw in [("original", {}), ("sem TRY", {"excluir": ["TRY=X"]}), ("sem EM de alta inflação/alto carry (TRY ZAR BRL COP HUF MXN INR IDR)", {"excluir": EMHI}),
                    ("carry 50% (haircut)", {"haircut": .5}), ("carry 50% e sem TRY", {"haircut": .5, "excluir": ["TRY=X"]}),
                    ("carry 0% (só spot)", {"haircut": 0}), ("só G10", {"so": G10}), ("G10 + LatAm", {"so": G10 + LATAM}),
                    ("sem JPY", {"excluir": ["JPY=X"]}), ("sem JPY e sem TRY", {"excluir": ["JPY=X", "TRY=X"]}), ("só lado comprado", {"lado": "long"}),
                    ("n=5", {"n": 5}), ("execução +1 dia", {"lag": 1})]:
        e = carry_serie(**kw)
        linhas.append({"variante": rot, "IS 2010-20": anual_pp(e[(e.index >= "2010-01-01") & (e.index < CORTE)]), "OOS 2021+": anual_pp(e[e.index >= CORTE]),
                       "2021": anual_pp(e[e.index.year == 2021]), "2022": anual_pp(e[e.index.year == 2022]), "2023": anual_pp(e[e.index.year == 2023]),
                       "2024": anual_pp(e[e.index.year == 2024]), "2025+": anual_pp(e[e.index >= "2025-01-01"])})
    p(md(pd.DataFrame(linhas).set_index("variante"), 2))
    # quem ficou no top/bottom ao longo do tempo
    pos = ren(Wh).resample("QE").mean()
    p("\n## Posição média por trimestre (OOS, % do PL após vol-alvo; + comprado / − vendido)\n"
      + md((pos[pos.index >= CORTE].loc[:, lambda x: x.abs().sum() > .05] * 100), 0))
    RES["11 Carry de moedas global"] = {"contrib": ren(C), "trades": tr, "spot": ren(Cs), "carry": ren(Cc), "alav": alav}


# ======================================================================= F02 termo
def cand_termo(vol_min=2e5):
    """Cópia de travas.candidatos_termo + taxas alternativas: à vista pelo VWAP do dia e pelo pior preço (máx. de abertura, fechamento, VWAP)."""
    t = pd.read_parquet(D / "b3_termo.parquet")
    t = t[(t.volume >= vol_min) & t.prazo.between(60, 400) & (t.fech > 0)]
    t["ticker_vista"] = t.ticker.str[:-1]
    v = pd.read_parquet(D / "b3_vista.parquet", columns=["data", "ticker", "abertura", "fech", "quantidade", "volume"])
    v = v[v.volume > 5e6].rename(columns={"ticker": "ticker_vista", "fech": "s", "volume": "vol_vista"})
    v["vwap"] = v.vol_vista / v.quantidade
    x = t.merge(v, on=["data", "ticker_vista"])
    x["venc"] = x.data + pd.to_timedelta(x.prazo, unit="D")
    x["du"] = tv.du(x.data, x.venc)
    x = x[x.du >= 10]
    tx = lambda spot: (x.fech * (1 - .0005) / (spot * 1.0005)) ** (252 / x.du) - 1
    x["taxa_ind"], x["taxa_vw"], x["taxa_pior"] = tx(x.s), tx(x.vwap), tx(np.maximum.reduce([x.s, x.vwap, x.abertura]))
    x["faixa"] = pd.cut(x.prazo, [59, 120, 240, 400], labels=["60-120", "121-240", "241-400"])
    g = x.groupby(["data", "ticker", "faixa"], observed=True)
    y = g.agg(taxa_compra=("taxa_ind", "median"), taxa_vw=("taxa_vw", "median"), taxa_pior=("taxa_pior", "median"), venc=("venc", "median"),
              du=("du", "median"), n=("taxa_ind", "size"), volume=("volume", "sum"))
    y = y[y.n >= 2].reset_index()
    y["chave"] = y.ticker + "|" + y.faixa.astype(str)
    return y


def termo_partes(thr=.005, peso=.1, lag=0, teto=1.0, teto_spread=.08, cand=None, exec_col=None):
    """Cópia de travas.trava (lado compra) registrando cada posição. exec_col: seleciona pela taxa de fechamento mas trava a taxa desta coluna."""
    c = (tv.candidatos_termo() if cand is None else cand).copy()
    c["ref"] = c.data.map(CDI_AA)
    s = c[c.taxa_compra.notna()].copy()
    s["edge"] = s.taxa_compra - s.ref
    s = s[(s.edge > thr) & (s.edge < teto_spread)]
    s["taxa"] = s.taxa_compra
    s = s.sort_values(["data", "edge"], ascending=[True, False])
    if lag:
        nxt = pd.Series(DIAS[1:], index=DIAS[:-1])
        s["data"] = s.data.map(nxt)
        hoje = c.set_index(["data", "chave"])
        s = s.drop(columns=["volume"]).join(hoje[["taxa_compra", "volume"]].rename(columns={"taxa_compra": "tx"}), on=["data", "chave"])
        s["taxa"] = s.tx
        s = s[s.taxa.notna()]
    if exec_col:
        s["taxa"] = s[exec_col]
        s = s[s.taxa.notna()]
    por_dia = {d: g for d, g in s.groupby("data")}
    cdi = CDI.reindex(DIAS).fillna(0).values
    abertas, trades = [], []
    contrib = {}
    for k, d in enumerate(DIAS):
        abertas = [a for a in abertas if a["venc"] >= d]
        tot = sum(a["peso"] for a in abertas)
        for a in abertas:
            if a["entrada"] < d:
                x = a["peso"] * (a["diaria"] - cdi[k])
                a["contrib"] += x
                a["dias"] += 1
                a["cdi_soma"] += cdi[k]
                contrib.setdefault(a["ticker"], np.zeros(len(DIAS)))[k] += x
        g = por_dia.get(d)
        if g is None:
            continue
        chaves = {a["chave"] for a in abertas}
        for _, r in g.iterrows():
            if tot + peso > teto + 1e-9:
                break
            if r.chave in chaves:
                continue
            a = {"ticker": r.ticker, "chave": r.chave, "entrada": d, "venc": r.venc, "peso": peso, "taxa %": r.taxa * 100, "cdi entrada %": r.ref * 100,
                 "edge pp": (r.taxa - r.ref) * 100, "volume termo R$": r.volume, "n negócios": r.n, "du": r.du,
                 "diaria": (1 + r.taxa) ** (1 / 252) - 1, "contrib": 0.0, "dias": 0, "cdi_soma": 0.0}
            abertas.append(a)
            trades.append(a)
            chaves.add(r.chave)
            tot += peso
    T = pd.DataFrame(trades)
    T["cdi médio realizado %"] = ((1 + T.cdi_soma / T.dias.clip(lower=1)) ** 252 - 1) * 100
    T["edge realizado pp"] = T["taxa %"] - T["cdi médio realizado %"]
    T["contrib pp"] = T.contrib * 100
    C = pd.DataFrame(contrib, index=DIAS)
    return C, T, s


def f02():
    p("\n\n# ===================== 02 FINANCIADOR A TERMO (thr=0,5%, peso=10%)")
    C, T, s = termo_partes()
    ex = C.sum(axis=1)
    import fundos_br as fb
    orig = fb.termo(.005, .1)
    p(f"checagem: reproduzido {anual_pp(ex[ex.index >= CORTE]):.3f} pp a.a. OOS vs original {anual_pp(orig[orig.index >= CORTE]):.3f}; dif máx {(ex - orig).abs().max():.2e}")
    p(f"\nnegócios: {len(T)}")
    occ = pd.Series(0.0, index=DIAS)
    for _, a in T.iterrows():
        occ[(DIAS > a.entrada) & (DIAS <= a.venc)] += a.peso
    p(f"ocupação média do PL em termos: total {occ.mean() * 100:.0f}%, OOS {occ[occ.index >= CORTE].mean() * 100:.0f}%; dias com 100%: {(occ >= .999).mean() * 100:.0f}%")
    T["ano"] = pd.to_datetime(T.entrada).dt.year
    p("\n## Por ano de entrada\n" + md(T.groupby("ano").agg(negocios=("ticker", "size"), tickers=("ticker", "nunique"), taxa_media=("taxa %", "mean"),
                                                            cdi_entrada=("cdi entrada %", "mean"), edge_entrada=("edge pp", "mean"),
                                                            edge_realizado=("edge realizado pp", "mean"), prazo_du=("du", "median"),
                                                            vol_termo_mediano_RS=("volume termo R$", "median"), contrib_pp=("contrib pp", "sum")), 2))
    p("\n## Contribuição por ano (pp do PL, competência diária)\n" + md(por_ano(ex.to_frame("total")), 2))
    rk = resumo_ativos(C)
    rk["% do total"] = rk["total pp"] / rk["total pp"].sum() * 100
    p(f"\n## Por ação (top 15 de {len(rk)})\n" + md(rk.head(15), 2))
    p(f"concentração: top 5 ações = {rk['total pp'].nlargest(5).sum() / rk['total pp'].sum() * 100:.0f}% do ganho; top 10 = {rk['total pp'].nlargest(10).sum() / rk['total pp'].sum() * 100:.0f}%")
    cols = ["ticker", "entrada", "venc", "du", "taxa %", "cdi entrada %", "edge pp", "cdi médio realizado %", "edge realizado pp", "volume termo R$", "n negócios", "contrib pp"]
    T2 = T.assign(entrada=pd.to_datetime(T.entrada).dt.date, venc=pd.to_datetime(T.venc).dt.date)
    b, w = top(T2[cols])
    p("\n## 10 melhores negócios\n" + md(b.set_index("ticker"), 2))
    p("\n## 10 piores negócios\n" + md(w.set_index("ticker"), 2))
    # concentração em datas
    dd = T.groupby(pd.to_datetime(T.entrada).dt.to_period("M"))["contrib pp"].sum().sort_values(ascending=False)
    p(f"\nmeses de ENTRADA com maior contribuição: {dd.head(8).round(2).to_dict()}; top 8 meses = {dd.head(8).sum() / dd.sum() * 100:.0f}% do total")
    # capacidade: posição de 10% do PL limitada a 20% do volume a termo do dia naquele papel/faixa
    T["PL max (20% do vol) R$ mi"] = T["volume termo R$"] * .2 / T.peso / 1e6
    q = T[pd.to_datetime(T.entrada) >= CORTE]["PL max (20% do vol) R$ mi"]
    p(f"\ncapacidade (OOS): PL máximo para a posição de 10% caber em 20% do volume a termo do dia — mediana R$ {q.median():.1f} mi, p25 {q.quantile(.25):.1f}, p75 {q.quantile(.75):.1f}")
    vt = s[s.data >= CORTE].groupby("data").volume.sum()
    p(f"volume a termo diário (somente papel/faixa com taxa > CDI+0,5%): mediana R$ {vt.median() / 1e6:.1f} mi, média R$ {vt.mean() / 1e6:.1f} mi")
    # sensibilidade: sem os 5 maiores tickers; só taxas até CDI+3%
    for rot, filt in [("sem as 5 ações que mais renderam", ~T.ticker.isin(rk.index[:5])), ("só edge de entrada <= 3 pp", T["edge pp"] <= 3),
                      ("só edge de entrada > 3 pp", T["edge pp"] > 3)]:
        sub = T[filt]
        p(f"  {rot}: {len(sub)} negócios, contrib total {sub['contrib pp'].sum():.2f} pp (de {T['contrib pp'].sum():.2f})")
    # teste de sincronismo: a taxa vem do último negócio a termo x fechamento à vista (horários diferentes). Ruído selecionado = maldição do vencedor.
    cd = cand_termo()
    cd["edge"] = (cd.taxa_compra - cd.data.map(CDI_AA)) * 100
    p(f"\nTODOS os candidatos (papel/faixa/dia, n>=2): edge mediano {cd.edge.median():.2f} pp, p25 {cd.edge.quantile(.25):.2f}, p75 {cd.edge.quantile(.75):.2f} "
      f"(dispersão enorme = ruído de horário); por ano: {cd.groupby(cd.data.dt.year).edge.median().round(2).to_dict()}")
    linhas = []
    for rot, kw in [("original (seleciona e trava no fechamento)", {}), ("seleciona no fech., trava pelo VWAP à vista", {"exec_col": "taxa_vw"}),
                    ("seleciona no fech., trava pelo pior preço à vista", {"exec_col": "taxa_pior"}), ("executa no dia seguinte (lag 1)", {"lag": 1}),
                    ("thr 2% (só taxas muito altas)", {"thr": .02})]:
        Cx, Tx, _ = termo_partes(cand=cd, **kw)
        e = Cx.sum(axis=1)
        linhas.append({"teste": rot, "negócios": len(Tx), "edge médio travado pp": Tx["edge pp"].mean(), "excesso OOS pp a.a.": anual_pp(e[e.index >= CORTE]),
                       "excesso 2014-20 pp a.a.": anual_pp(e[(e.index >= "2014-01-01") & (e.index < CORTE)])})
    p("\n## Teste de sincronismo de preços\n" + md(pd.DataFrame(linhas).set_index("teste"), 2))
    # distribuição da taxa travada
    q = T[pd.to_datetime(T.entrada) >= CORTE]
    p(f"\ntaxa travada OOS: média {q['taxa %'].mean():.2f}% a.a., CDI na entrada {q['cdi entrada %'].mean():.2f}%; spread mediano {q['edge pp'].median():.2f} pp "
      f"(p10 {q['edge pp'].quantile(.1):.2f}, p90 {q['edge pp'].quantile(.9):.2f}); negócios OOS com edge realizado < 0: {(q['edge realizado pp'] < 0).mean() * 100:.0f}%")
    RES["02 Financiador a termo"] = {"contrib": C, "trades": T.drop(columns=["diaria"])}
    return T


# ======================================================================= F06 eurobonds
def eb_insumos():
    f = OUT / "cache_atribuicao_eb.pkl"
    if f.exists():
        return pd.read_pickle(f)
    sys.path.insert(0, str(RQ.parent))
    with contextlib.redirect_stdout(io.StringIO()):
        import estrategias_sinal as es
    ed = es.ed
    cad = ed.cad_eb
    d = {"F": es.forca_eb(), "exc": ed.exc_eb, "PE": ed.PE, "custo": es.e.CUSTO_EXT * 2.5, "emis": es.emis_eb, "dias": es.dias,
         "cup": ed.cup, "Dm": ed.Dm, "yD": ed.yD, "sprd": ed.sprd_eb, "nome": cad.emissor.to_dict() if "emissor" in cad else {}, "venc": cad.venc.to_dict(),
         "cdi": ed.cdi}
    pd.to_pickle(d, f)
    return d


def livro_partes(F, ret, preco, n_max, custo, stop, emissor, dias):
    """Cópia de estrategias_sinal.livro registrando valor por papel, contribuição diária e negócios."""
    ENTRA, SAI = .90, .50
    F = F.reindex(columns=[c for c in F.columns if c in ret.columns])
    R = ret[F.columns].to_numpy()
    queda = (preco[F.columns] / preco[F.columns].shift(5) - 1).to_numpy()
    Fv = F.to_numpy()
    cols = np.array(F.columns)
    em = np.array([emissor.get(c, c) for c in cols])
    val, proib, out, nav = {}, {}, np.zeros(len(dias)), 1.0
    Cm = np.zeros((len(dias), len(cols)))
    Wm = np.zeros((len(dias), len(cols)))
    abertos, trades = {}, []
    for t in range(1, len(dias)):
        f, q, i = Fv[t - 1], queda[t - 1], t - 1
        custo_dia = 0.0
        for k in list(val):
            fraco = not (f[k] >= SAI)
            sumiu = np.isnan(R[max(i - 2, 0):i + 1, k]).all()
            if fraco or sumiu:
                c_ = val.pop(k) * custo
                custo_dia += c_
                Cm[t, k] -= c_ / nav
                a = abertos.pop(k)
                a.update(saida=dias[t], motivo="sumiu" if sumiu else "sinal < 50%")
                trades.append(a)
        if len(val) < n_max:
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
                Cm[t, k] -= val[k] * custo / nav
                abertos[k] = {"isin": cols[k], "emissor": em[k], "entrada": dias[t], "px_entrada": preco[cols[k]].iloc[t - 1], "forca": f[k]}
        ganho = 0.0
        for k in val:
            r = R[t, k] if not np.isnan(R[t, k]) else 0.0
            Wm[t, k] = val[k] / nav
            ganho += val[k] * r
            Cm[t, k] += val[k] * r / nav
            val[k] *= 1 + r
        out[t] = (ganho - custo_dia) / nav
        nav *= 1 + out[t]
    for k, a in abertos.items():
        a.update(saida=dias[-1], motivo="em carteira")
        trades.append(a)
    C = pd.DataFrame(Cm, index=dias, columns=cols)
    Wh = pd.DataFrame(Wm, index=dias, columns=cols)
    return pd.Series(out, index=dias), C, Wh, pd.DataFrame(trades)


def f06():
    p("\n\n# ===================== 06 EUROBONDS BR COM HEDGE (n=15, alav=1)")
    I = eb_insumos()
    dias = I["dias"]
    r, C, Wh, T = livro_partes(I["F"], I["exc"], I["PE"], 15, I["custo"], -9, I["emis"], dias)
    corte = pd.Timestamp("2024-01-01")
    ex = r.reindex(DIAS).fillna(0)
    p(f"checagem: OOS 2024+ {anual_pp(ex[ex.index >= corte]):.2f} pp a.a.; IS 2021-23 {anual_pp(ex[(ex.index >= '2021-01-01') & (ex.index < corte)]):.2f}")
    PE, cup = I["PE"], I["cup"]
    dt = pd.Series(np.r_[1, np.diff(dias).astype("timedelta64[D]").astype(float)], index=dias)
    pr = PE / PE.shift(1) - 1
    cp = np.outer(dt / 365, cup.values) / PE.shift(1)
    ok = I["exc"].notna()
    preco_spread = (pr + I["Dm"].shift(1) * (I["yD"] - I["yD"].shift(1))).where(ok)   # variação de preço que NÃO é Treasury (spread + puxada ao par)
    carrego = (I["exc"] - preco_spread).where(ok)                                        # cupom - juro do hedge - custo do hedge cambial
    Wsh = Wh.shift(0)
    Cp = (Wsh * preco_spread.reindex(columns=Wh.columns)).fillna(0)
    Cc = (Wsh * carrego.reindex(columns=Wh.columns)).fillna(0)
    nomes = I["emis"]
    em = lambda X: X.T.groupby(lambda c: nomes.get(c, c)).sum().T
    tab = pd.DataFrame({"preço(spread) pp": em(Cp).sum(), "carrego pp": em(Cc).sum(), "total pp": em(C).sum(),
                        "OOS 2024+ pp": em(C)[C.index >= corte].sum(), "IS 2021-23 pp": em(C)[(C.index >= "2021-01-01") & (C.index < corte)].sum()}) * 100
    tab = tab[tab["total pp"].abs() > .05].sort_values("total pp", ascending=False)
    p("\n## Por emissor (pp do PL; desde 2021)\n" + md(tab, 2))
    p(f"\nTOTAL desde 2021: preço/spread {Cp[Cp.index >= '2021'].sum().sum() * 100:.1f} pp; carrego {Cc[Cc.index >= '2021'].sum().sum() * 100:.1f} pp; "
      f"custos {(C - Cp - Cc)[C.index >= '2021'].sum().sum() * 100:.1f} pp")
    p("\n## Por ano: preço x carrego (pp)\n" + md(pd.DataFrame({"preço/spread": por_ano(Cp).sum(axis=1), "carrego": por_ano(Cc).sum(axis=1),
                                                              "custos/resíduo": por_ano(C - Cp - Cc).sum(axis=1), "total": por_ano(C).sum(axis=1)}), 2))
    # negócios
    T["dias"] = [((dias > a) & (dias <= b)).sum() for a, b in zip(T.entrada, T.saida)]
    T["contrib pp"] = [C.loc[(C.index >= a) & (C.index <= b), k].sum() * 100 for k, a, b in zip(T["isin"], T.entrada, T.saida)]
    T["preço pp"] = [Cp.loc[(Cp.index > a) & (Cp.index <= b), k].sum() * 100 for k, a, b in zip(T["isin"], T.entrada, T.saida)]
    T["carrego pp"] = [Cc.loc[(Cc.index > a) & (Cc.index <= b), k].sum() * 100 for k, a, b in zip(T["isin"], T.entrada, T.saida)]
    T["px_saida"] = [PE[k].loc[:b].dropna().iloc[-1] if PE[k].loc[:b].notna().any() else np.nan for k, b in zip(T["isin"], T.saida)]
    T["retorno %"] = [((1 + I["exc"][k].loc[(dias > a) & (dias <= b)].fillna(0)).prod() - 1) * 100 for k, a, b in zip(T["isin"], T.entrada, T.saida)]
    T["cupom"] = T["isin"].map(cup)
    T["venc"] = T["isin"].map(I["venc"])
    sp = I["sprd"]
    T["spread entrada %"] = [sp[k].get(pd.Period(a, "M") - 1, np.nan) if k in sp else np.nan for k, a in zip(T["isin"], T.entrada)]
    cols = ["emissor", "cupom", "venc", "entrada", "saida", "dias", "px_entrada", "px_saida", "spread entrada %", "retorno %", "preço pp", "carrego pp", "contrib pp", "motivo"]
    T2 = T.assign(entrada=pd.to_datetime(T.entrada).dt.date, saida=pd.to_datetime(T.saida).dt.date, venc=pd.to_datetime(T.venc).dt.date)
    T2 = T2[pd.to_datetime(T2.saida) >= "2021-01-01"]
    b, w = top(T2[cols])
    p("\n## 10 melhores negócios\n" + md(b.set_index("emissor"), 2))
    p("\n## 10 piores negócios\n" + md(w.set_index("emissor"), 2))
    p(f"\nnegócios desde 2021: {len(T2)}; preço de entrada mediano {T2.px_entrada.median():.1f}; % entradas abaixo de 90: {(T2.px_entrada < 90).mean() * 100:.0f}%; abaixo de 80: {(T2.px_entrada < 80).mean() * 100:.0f}%")
    for lim in (80, 90):
        a = T2[T2.px_entrada < lim]
        p(f"  entradas < {lim}: {len(a)} negócios, contrib {a['contrib pp'].sum():.1f} pp; demais {T2[T2.px_entrada >= lim]['contrib pp'].sum():.1f} pp")
    stress = ["B2W", "Americanas", "Andrade", "Oi", "Gol", "Azul", "Light", "Braskem", "Raizen", "Usiminas", "Natura", "Hidrovias", "Simpar", "Movida", "3R", "Acu", "MC Brazil"]
    st = tab[[any(s.lower() in i.lower() for s in stress) for i in tab.index]]
    p(f"\nnomes de stress/high yield presentes: {st['total pp'].round(2).to_dict()}")
    p(f"sem eles o livro teria {tab['total pp'].sum() - st['total pp'].sum():.1f} pp (vs {tab['total pp'].sum():.1f}) desde 2021")
    RES["06 Crédito offshore com hedge (cupom cambial)"] = {"contrib": C, "trades": T, "preco": Cp, "carrego": Cc}


# ======================================================================= F15 vol
def vol_partes(peso_svxy=.5, filtro="vix3m+vvix", lag=0, custo_mult=1, extra_filtro=None):
    vix, v3 = IDX["^VIX"].reindex(DIAS_US).ffill(), IDX["^VIX3M"].reindex(DIAS_US).ffill()
    on = (vix / v3 < 1) if filtro != "nenhum" else pd.Series(True, index=DIAS_US)
    if filtro == "vix3m+vvix":
        vv = IDX["^VVIX"].reindex(DIAS_US).ffill()
        on &= vv < vv.rolling(252, min_periods=100).quantile(.8)
    if extra_filtro is not None:
        on &= extra_filtro
    sv = limpa(ETF["SVXY"].reindex(DIAS_US).pct_change(fill_method=None), .9) - TB_US
    pw = limpa(IDX["^PUT"].reindex(DIAS_US).pct_change(fill_method=None)) - TB_US
    R = pd.DataFrame({"svxy": sv, "put": pw})
    W = pd.DataFrame({"svxy": on.astype(float) * peso_svxy, "put": 1 - peso_svxy}, index=DIAS_US)
    C, Wh, _ = partes(W, R, fg.C_ETF, lag, custo_mult)
    return C, Wh, R, on, vix / v3


def f15():
    p("\n\n# ===================== 15 PRÊMIO DE VOLATILIDADE (SVXY 50% com filtro VIX/VIX3M + VVIX, ^PUT 50%)")
    C, Wh, R, on, ratio = vol_partes()
    C2, C3 = vol_partes(filtro="vix3m")[0], vol_partes(filtro="nenhum", extra_filtro=None)[0]
    ex = brl(C.sum(axis=1))
    orig = fg.vol_premio(.5, "vix3m+vvix")
    p(f"checagem: OOS {anual_pp(ex[ex.index >= CORTE]):.2f} vs original {anual_pp(orig[orig.index >= CORTE]):.2f}")
    p("\n## Por ano (pp)\n" + md(por_ano(C).assign(total=lambda x: x.sum(axis=1), **{"% dias SVXY ligado": (Wh.svxy > 0).groupby(Wh.index.year).mean() * 100}), 1))
    tr = episodios(Wh[["svxy"]], C[["svxy"]], R[["svxy"]])
    b, w = top(tr)
    p(f"\n## Episódios com SVXY ligado: {len(tr)}; duração mediana {tr.dias.median():.0f} dias")
    p("\n## 10 melhores episódios SVXY\n" + md(b.set_index("ativo"), 2))
    p("\n## 10 piores episódios SVXY\n" + md(w.set_index("ativo"), 2))
    # put-write por mês
    pm = C.put.groupby(C.index.to_period("M")).sum() * 100
    p(f"\nput-write (50%): 5 melhores meses {pm.nlargest(5).round(2).to_dict()}; 5 piores {pm.nsmallest(5).round(2).to_dict()}")
    # estresses
    p("\n## Janelas de estresse (pp do PL acumulado na janela; SVXY ligado no início?)")
    linhas = []
    for rot, a, b in [("Volmageddon fev/2018", "2018-01-29", "2018-02-28"), ("Q4 2018", "2018-10-01", "2018-12-31"), ("Covid fev-mar/2020", "2020-02-19", "2020-03-31"),
                      ("jan/2022 (início da alta do Fed)", "2022-01-01", "2022-03-15"), ("jun/2022", "2022-06-01", "2022-06-30"), ("SVB mar/2023", "2023-03-06", "2023-03-24"),
                      ("carry trade do iene ago/2024", "2024-07-15", "2024-08-16"), ("tarifas abr/2025", "2025-03-25", "2025-04-25")]:
        sl = slice(a, b)
        if not len(C.loc[sl]):
            continue
        linhas.append({"evento": rot, "SVXY pp": C.svxy.loc[sl].sum() * 100, "PUT pp": C.put.loc[sl].sum() * 100, "total pp": C.loc[sl].sum().sum() * 100,
                       "SVXY ret ativo %": ((1 + R.svxy.loc[sl].fillna(0)).prod() - 1) * 100, "dias ligado": int((Wh.svxy.loc[sl] > 0).sum()),
                       "ligado no 1o dia": bool(Wh.svxy.loc[sl].iloc[0] > 0), "total só filtro VIX3M pp": C2.loc[sl].sum().sum() * 100,
                       "total sem filtro pp": C3.loc[sl].sum().sum() * 100})
    p(md(pd.DataFrame(linhas).set_index("evento"), 2))
    spx = IDX["^GSPC"].reindex(DIAS_US).ffill().pct_change(fill_method=None) - TB_US
    for rot, X in [("filtro VIX3M+VVIX (escolhido)", C), ("só VIX3M", C2), ("sem filtro", C3), ("só put-write 100%", vol_partes(peso_svxy=0)[0])]:
        x = X.sum(axis=1)
        o = x[x.index >= CORTE]
        b = np.polyfit(spx.reindex(o.index).fillna(0), o, 1)[0]
        p(f"  {rot}: OOS {anual_pp(brl(x)[brl(x).index >= CORTE]):.2f} pp a.a., vol {o.std() * np.sqrt(252) * 100:.1f}%, beta ao S&P {b:.2f}, "
          f"excesso do beta {anual_pp(b * spx.reindex(o.index).fillna(0)):.2f} pp a.a., pior dia {o.min() * 100:.1f}%")
    for a, b in [("2018-01-30", "2018-02-09"), ("2024-07-29", "2024-08-09"), ("2025-03-31", "2025-04-11")]:
        x = pd.DataFrame({"VIX/VIX3M": ratio.loc[a:b], "filtro ON": on.loc[a:b], "peso SVXY no dia": Wh.svxy.loc[a:b], "SVXY ret %": R.svxy.loc[a:b] * 100,
                          "contrib SVXY pp": C.svxy.loc[a:b] * 100, "PUT ret %": R.put.loc[a:b] * 100})
        p(f"\n### dia a dia {a} a {b}\n" + md(x, 2))
    # e se o SVXY estivesse ligado no pior dia (agosto/2024 com filtro atrasado)? perda hipotética
    p(f"\nhipótese: SVXY ligado (50%) em 05/08/2024 = {0.5 * R.svxy.get(pd.Timestamp('2024-08-05'), np.nan) * 100:.1f}% do PL; em 05/02/2018 (antes da troca para -0,5x) = "
      f"{0.5 * R.svxy.get(pd.Timestamp('2018-02-05'), np.nan) * 100:.1f}% + 06/02 {0.5 * R.svxy.get(pd.Timestamp('2018-02-06'), np.nan) * 100:.1f}%")
    # quanto vem de anos calmos 2022-2024
    y = por_ano(C).sum(axis=1)
    p(f"\nexcesso por ano OOS: {y[y.index >= 2021].round(1).to_dict()}")
    RES["15 Prêmio de volatilidade"] = {"contrib": C, "trades": tr}


# ======================================================================= F12 commodities
def comm_partes(tipo="xs", alvo=.08, lag=0, custo_mult=1):
    c = [x for x in fg.COMM if x in fg.P]
    R = fg.RX[c]
    m = np.log(fg.P[c]) - np.log(fg.P[c]).shift(252)
    rk = m.rank(axis=1, pct=True)
    W = (rk >= .7).astype(float) - (rk <= .3).astype(float)
    vol = R.rolling(63, min_periods=40).std()
    W = (W / vol).div((W / vol).abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    C, Wh, alav = partes(semanal(W), R, fg.C_ETF, lag, custo_mult, alvo)
    return C, Wh, alav, R


def f12():
    p("\n\n# ===================== 12 COMMODITIES (momento relativo 12m, top/bottom 30%, vol-alvo 8%)")
    C, Wh, alav, R = comm_partes()
    ex = brl(C.sum(axis=1) - alav)
    orig = fg.commodities("xs", .08)
    p(f"checagem: OOS {anual_pp(ex[ex.index >= CORTE]):.2f} vs original {anual_pp(orig[orig.index >= CORTE]):.2f}")
    rk = resumo_ativos(C)
    rk["% dias comprado OOS"] = (Wh[Wh.index >= CORTE] > 0).mean() * 100
    rk["% dias vendido OOS"] = (Wh[Wh.index >= CORTE] < 0).mean() * 100
    p("\n## Por ETF\n" + md(rk, 2))
    p("\n## Por ano (pp)\n" + md(por_ano(C).assign(total=lambda x: x.sum(axis=1) - por_ano(alav.to_frame())[0]), 1))
    tr = episodios(Wh, C, R)
    b, w = top(tr[pd.to_datetime(tr.saida) >= CORTE], col="contrib OOS pp")
    p("\n## 10 melhores negócios OOS\n" + md(b.set_index("ativo"), 2))
    p("\n## 10 piores negócios OOS\n" + md(w.set_index("ativo"), 2))
    lado = pd.DataFrame({"comprado": (C.where(Wh > 0, 0)).sum(axis=1), "vendido": (C.where(Wh < 0, 0)).sum(axis=1)})
    p("\n## Comprado x vendido por ano (pp)\n" + md(por_ano(lado), 1))
    RES["12 Commodities sistemático"] = {"contrib": C, "trades": tr}


# ======================================================================= F20 multi
def f20():
    p("\n\n# ===================== 20 MULTIESTRATÉGIA (escala 1,25; OOS 2023+)")
    res = pickle.load(open(OUT / "resultados.pkl", "rb"))
    livros, pesos = {}, {}
    for r in res:
        f = r["fundo"]
        if f.nome.startswith("20") or f.benchmark != "CDI" or r["is_ir"] <= 0:
            continue
        ex = r["bruto"] - CDI.reindex(r["bruto"].index)
        is_ = ex[ex.index < pd.Timestamp(f.corte)]
        if is_.std() == 0 or len(is_) < 120:
            continue
        livros[f.nome], pesos[f.nome] = ex, 1 / (is_.std() * np.sqrt(252))
    E = pd.DataFrame(livros).reindex(DIAS)
    w = pd.Series(pesos)
    Wd = E.notna().mul(w, axis=1)
    Wd = Wd.div(Wd.sum(axis=1).replace(0, np.nan), axis=0)
    for _ in range(5):
        Wd = Wd.clip(upper=.25)
        Wd = Wd.div(Wd.sum(axis=1).replace(0, np.nan), axis=0)
    ex = (E.fillna(0) * Wd.fillna(0)).sum(axis=1)
    v = ex.rolling(126, min_periods=60).std().shift(1) * np.sqrt(252)
    esc = (.06 / v).clip(upper=3).fillna(1) * 1.25
    C = (E.fillna(0) * Wd.fillna(0)).mul(esc, axis=0)
    C = C[C.index >= "2015-01-01"]
    orig = res[-1]["bruto"] - CDI.reindex(res[-1]["bruto"].index)
    tot = C.sum(axis=1)
    p(f"checagem: OOS 2023+ {anual_pp(tot[tot.index >= '2023-01-01']):.2f} vs original {anual_pp(orig[orig.index >= '2023-01-01']):.2f}")
    c23 = pd.Timestamp("2023-01-01")
    tab = pd.DataFrame({"peso médio OOS %": Wd[Wd.index >= c23].mean() * 100, "alavanc. média OOS": esc[esc.index >= c23].mean(),
                        "contrib IS 2015-22 pp": C[C.index < c23].sum() * 100, "contrib OOS 2023+ pp": C[C.index >= c23].sum() * 100})
    tab["% do OOS"] = tab["contrib OOS 2023+ pp"] / tab["contrib OOS 2023+ pp"].sum() * 100
    p("\n## Por livro\n" + md(tab.sort_values("contrib OOS 2023+ pp", ascending=False), 2))
    p("\n## Por ano (pp)\n" + md(por_ano(C).T.assign(), 2))
    p(f"\nalavancagem (escala vol-alvo 6% x 1,25) média OOS {esc[esc.index >= c23].mean():.2f}x; max {esc.max():.2f}x")
    RES["20 Multiestratégia (pods)"] = {"contrib": C, "trades": pd.DataFrame(), "pesos": Wd, "escala": esc}


if __name__ == "__main__":
    so = sys.argv[1:]
    TXT = open(OUT / ("atribuicao_saida" + "".join("_" + x for x in so) + ".txt"), "w", encoding="utf-8")
    for k, fn in [("11", f11), ("02", f02), ("15", f15), ("12", f12), ("20", f20), ("06", f06)]:
        if not so or k in so:
            fn()
    arq = OUT / "atribuicao.pkl"
    antigo = pd.read_pickle(arq) if arq.exists() and so else {}
    antigo.update(RES)
    pickle.dump(antigo, open(arq, "wb"))
    p("pronto")
