"""
Estratégias de renda fixa sintética com derivativos da B3 (taxa travada x CDI):
  box de 4 pontas  : compra call K1, vende call K2, compra put K2, vende put K1 -> recebe K2-K1 no vencimento
  conversão        : compra o ativo, compra put K, vende call K -> recebe K no vencimento (BOVA11 e IBOV-like, sem dividendo)
  termo (financiamento): compra à vista e vende a termo -> recebe o preço a termo
Preço de execução: melhor oferta (compra paga a oferta de venda, venda recebe a de compra); sem oferta, fechamento com folga.
Exige que todas as pernas tenham negociado no dia. Custos: B3 + corretagem sobre os prêmios; ações 0,05% por perna.
"""
import numpy as np
import pandas as pd

from base import CDI, CDI_AA, D, DIAS

LIQUIDAS = ["BOVA", "PETR", "VALE", "ITUB", "BBDC", "BBAS", "ABEV", "B3SA", "ITSA", "SMAL"]
_OPC = None


def opcoes():
    global _OPC
    if _OPC is None:
        o = pd.read_parquet(D / "b3_opcoes.parquet", columns=["data", "raiz", "tipo", "fech", "oferta_compra", "oferta_venda", "negocios",
                                                              "volume", "strike", "venc"], filters=[("raiz", "in", LIQUIDAS)])
        o = o[(o.negocios > 0) & (o.fech > 0) & (o.strike > 0)]
        o["dc"] = (o.venc - o.data).dt.days
        o = o[o.dc.between(15, 200)]
        _OPC = o.sort_values("negocios").drop_duplicates(["data", "raiz", "venc", "tipo", "strike"], keep="last")
    return _OPC


def precos(df, folga):
    compra = np.where(df.oferta_venda > 0, df.oferta_venda, df.fech * (1 + folga) + .01)
    venda = np.where(df.oferta_compra > 0, df.oferta_compra, np.maximum(df.fech * (1 - folga) - .01, 0))
    return compra, venda


def du(a, b):
    return np.busday_count(np.asarray(a, dtype="datetime64[D]"), np.asarray(b, dtype="datetime64[D]"))


def candidatos_box(folga=.02, custo_premio=.002):
    o = opcoes()
    o["pc"], o["pv"] = precos(o, folga)
    c = o[o.tipo == "C"][["data", "raiz", "venc", "strike", "pc", "pv", "fech"]]
    p = o[o.tipo == "P"][["data", "raiz", "venc", "strike", "pc", "pv", "fech"]]
    cp = c.merge(p, on=["data", "raiz", "venc", "strike"], suffixes=("_c", "_p"))   # strikes com call e put negociadas no dia
    out = []
    for (d, r, v), g in cp.groupby(["data", "raiz", "venc"], sort=False):
        if len(g) < 2:
            continue
        g = g.sort_values("strike")
        K = g.strike.values
        i, j = np.triu_indices(len(g), 1)
        larg = K[j] - K[i]
        ok = larg >= .01 * K[i]
        i, j, larg = i[ok], j[ok], larg[ok]
        if not len(i):
            continue
        custo = g.pc_c.values[i] - g.pv_c.values[j] + g.pc_p.values[j] - g.pv_p.values[i]
        premios = g.fech_c.values[i] + g.fech_c.values[j] + g.fech_p.values[i] + g.fech_p.values[j]
        custo = custo + custo_premio * premios
        # vender o box (tomar emprestado): recebe hoje
        receb = g.pv_c.values[i] - g.pc_c.values[j] + g.pv_p.values[j] - g.pc_p.values[i] - custo_premio * premios
        out.append(pd.DataFrame({"data": d, "raiz": r, "venc": v, "k1": K[i], "k2": K[j], "larg": larg, "custo": custo, "receb": receb}))
    b = pd.concat(out, ignore_index=True)
    b["du"] = du(b.data, b.venc)
    b = b[b.du >= 10]
    b["taxa_compra"] = np.where((b.custo > 0) & (b.custo < b.larg), (b.larg / b.custo) ** (252 / b.du) - 1, np.nan)
    b["taxa_venda"] = np.where((b.receb > 0) & (b.receb < b.larg), (b.larg / b.receb) ** (252 / b.du) - 1, np.nan)
    b["chave"] = b.raiz + "|" + b.venc.astype(str) + "|" + b.k1.astype(str) + "|" + b.k2.astype(str)
    return b


def candidatos_conversao(folga=.02, custo_premio=.002):
    o = opcoes()
    o = o[o.raiz.isin(["BOVA", "SMAL"])]                                  # ETFs: sem dividendos, sem exercício antecipado relevante
    v = pd.read_parquet(D / "b3_vista.parquet", columns=["data", "ticker", "fech", "oferta_venda"],
                        filters=[("ticker", "in", ["BOVA11", "SMAL11"])])
    v["raiz"] = v.ticker.str[:4]
    v["s"] = np.where(v.oferta_venda > 0, v.oferta_venda, v.fech * 1.0005)
    o["pc"], o["pv"] = precos(o, folga)
    c = o[o.tipo == "C"][["data", "raiz", "venc", "strike", "pv", "fech"]].rename(columns={"pv": "call_venda", "fech": "fc"})
    p = o[o.tipo == "P"][["data", "raiz", "venc", "strike", "pc", "fech"]].rename(columns={"pc": "put_compra", "fech": "fp"})
    x = c.merge(p, on=["data", "raiz", "venc", "strike"]).merge(v[["data", "raiz", "s"]], on=["data", "raiz"])
    x = x[(x.strike / x.s).between(.9, 1.1)]
    x["custo"] = x.s * 1.0005 + x.put_compra - x.call_venda + custo_premio * (x.fc + x.fp)
    x["du"] = du(x.data, x.venc)
    x = x[x.du >= 10]
    x["taxa_compra"] = (x.strike / x.custo) ** (252 / x.du) - 1
    x["taxa_venda"] = np.nan
    x["chave"] = x.raiz + "|" + x.venc.astype(str) + "|" + x.strike.astype(str)
    return x


def candidatos_termo(vol_min=2e5):
    t = pd.read_parquet(D / "b3_termo.parquet")
    t = t[(t.volume >= vol_min) & t.prazo.between(16, 400) & (t.fech > 0)]
    t["ticker_vista"] = t.ticker.str[:-1]
    v = pd.read_parquet(D / "b3_vista.parquet", columns=["data", "ticker", "fech", "volume"])
    v = v[v.volume > 5e6].rename(columns={"ticker": "ticker_vista", "fech": "s", "volume": "vol_vista"})
    x = t.merge(v, on=["data", "ticker_vista"])
    x["venc"] = x.data + pd.to_timedelta(x.prazo, unit="D")
    x["du"] = du(x.data, x.venc)
    x = x[x.du >= 10]
    x = x[x.prazo.between(60, 400)]
    x["custo"] = x.s * 1.0005                                             # compra à vista + corretagem/emolumentos
    x["taxa_ind"] = (x.fech * (1 - .0005) / x.custo) ** (252 / x.du) - 1
    x["faixa"] = pd.cut(x.prazo, [59, 120, 240, 400], labels=["60-120", "121-240", "241-400"])
    # taxa robusta: mediana do dia por ação e faixa de prazo (o à vista de fechamento não é simultâneo a cada negócio a termo)
    g = x.groupby(["data", "ticker", "faixa"], observed=True)
    y = g.agg(taxa_compra=("taxa_ind", "median"), venc=("venc", "median"), du=("du", "median"), n=("taxa_ind", "size"), volume=("volume", "sum"))
    y = y[y.n >= 2].reset_index()
    y["taxa_venda"] = np.nan
    y["chave"] = y.ticker + "|" + y.faixa.astype(str)
    return y


def trava(cand, thr=.01, peso=.2, teto=1.0, lag=0, lado="compra", teto_spread=.10, custo_mult=1.0):
    """Abre posições quando a taxa travada passa o CDI do dia + thr (e é crível: < CDI + teto_spread). Mantém até o vencimento.
    Excesso diário = peso x (taxa travada diária - CDI do dia). lado='ambos' também vende box quando a taxa < CDI - thr."""
    cdi_aa = CDI_AA
    c = cand.copy()
    c["ref"] = c.data.map(cdi_aa)
    sinais = []
    for col, sgn in (("taxa_compra", 1), ("taxa_venda", -1)):
        if col == "taxa_venda" and lado != "ambos":
            continue
        s = c[c[col].notna()].copy()
        s["edge"] = sgn * (s[col] - s.ref)
        s = s[(s.edge > thr) & (s.edge < teto_spread)]
        s["taxa"], s["sinal"] = s[col], sgn
        sinais.append(s)
    s = pd.concat(sinais).sort_values(["data", "edge"], ascending=[True, False])
    if lag:                                                               # executa no dia seguinte, à taxa daquele dia
        nxt = pd.Series(DIAS[1:], index=DIAS[:-1])
        s["data"] = s.data.map(nxt)
        hoje = c.set_index(["data", "chave"])
        s = s.join(hoje[["taxa_compra", "taxa_venda"]].rename(columns=lambda x: x + "_x"), on=["data", "chave"])
        s["taxa"] = np.where(s.sinal > 0, s.taxa_compra_x, s.taxa_venda_x)
        s = s[s.taxa.notna()]
    abertas, exc = [], pd.Series(0.0, index=DIAS)
    por_dia = {d: g for d, g in s.groupby("data")}
    cdi = CDI.reindex(DIAS).fillna(0).values
    tot = 0.0
    for k, d in enumerate(DIAS):
        abertas = [a for a in abertas if a[0] >= d]                       # (vencimento, peso, taxa diária, sinal, chave)
        tot = sum(a[1] for a in abertas)
        e = sum(a[1] * a[3] * (a[2] - cdi[k]) for a in abertas if a[4] < d)
        exc.iloc[k] = e
        g = por_dia.get(d)
        if g is None:
            continue
        chaves = {a[5] for a in abertas}
        for _, r in g.iterrows():
            if tot + peso > teto + 1e-9:
                break
            if r.chave in chaves:
                continue
            taxa = r.taxa - (r.taxa - r.ref) * 0 - .0 * custo_mult
            diaria = (1 + taxa) ** (1 / 252) - 1
            if custo_mult != 1:                                           # custo extra: piora a taxa em (mult-1) x custo base
                diaria -= (custo_mult - 1) * .002 / max(r.du, 1)
            abertas.append((r.venc, peso, diaria, r.sinal, d, r.chave))
            chaves.add(r.chave)
            tot += peso
    return exc


if __name__ == "__main__":
    import time
    t0 = time.time()
    b = candidatos_box()
    print(f"box: {len(b)} candidatos em {time.time() - t0:.0f}s; datas {b.data.nunique()}")
    b["edge"] = b.taxa_compra - b.data.map(CDI_AA)
    print(b.groupby(b.data.dt.year).edge.describe(percentiles=[.5, .9]).round(4).to_string())
    print(b[b.edge.between(.01, .1)].groupby([b.data.dt.year, "raiz"]).size().unstack(fill_value=0).to_string())
