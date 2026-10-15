"""
AUDITORIA (red team) dos candidatos event-driven ao top 5 — versões corrigidas.
  python ideias_aud_eventos.py            -> roda os fundos auditados (com a dimensão de regime, como a rodada final) e salva
                                             resultado/ideias_aud_eventos.pkl (com contrib e trades)
  python ideias_aud_eventos.py medidas    -> só imprime as medições da auditoria (cobertura, viés, concentração)
Caderno: pesquisa/auditoria_eventos.md. Não altera base/motor/rodar/regimes nem os ideias_* originais (só os importa).

O que foi corrigido (detalhes no caderno):
  G3  spin-offs: (i) spin-offs que NEGOCIARAM (Forms 3/4 por > 90 dias) mas sumiram do Yahoo entram com preço sintético de -30% no
      carregamento (cenário conservador do viés de sobrevivência: os que faltam no OOS são justamente LYLT, TSVT, ZIMV, KLG...);
      (ii) hedge 50% SPY + 50% IWM (a carteira tem GEV/CEG/SNDK — large caps; IWM puro embute small - large = -7,5 pp/ano no OOS).
  E3  follow-on vendido: (i) aluguel mínimo de 10% a.a. (papel em oferta fica caro/indisponível para alugar; os maiores ganhos são
      IRBR3/VIIA3/AZUL4/CVCB3, todos de aluguel alto); (ii) hedge por tamanho: emissor com ADV >= R$50 mi contra Ibovespa, o resto contra
      SMAL11 (vender small cap contra Ibov embute o fator tamanho, SMLL - Ibov = -9 pp/ano no OOS).
  IE06 índices EUA: (i) remove eventos cujo ticker da época foi RECICLADO (empresa sumiu da SEC e o Yahoo devolve outra empresa com o mesmo
      ticker: MNST 2008 = Hansen, KG, SII, GENZ, EP, SUN...); (ii) excluídas que quebraram (Chapter 11/FDIC) e sumiram do Yahoo entram com
      -50% no carregamento (FRC e SIVB em 2023, LEH/WM/GM no IS).
  IE08 PEAD Ásia: hedge contra a cesta igualitária dos MESMOS membros atuais do índice (e não contra o índice): remove o viés comum de
      sobrevivência (quem está no índice hoje subiu mais que o índice no passado).
"""
import pickle
import re
import sys
import time
import warnings

import numpy as np
import pandas as pd

from base import CDI, D, DIAS, DIAS_US, R_IBOV, TB_US, brl
from motor import Fundo

warnings.filterwarnings("ignore")
OUT = D.parent / "resultado"
_C = {}


def _c(k, fn):
    if k not in _C:
        _C[k] = fn()
    return _C[k]


# =============================================================== G3 spin-offs [auditado]
def _g():
    import ideias_global as g
    if "SPYIWM" not in g.RX_US:
        g.RX_US["SPYIWM"] = .5 * g.RX_US["SPY"] + .5 * g.RX_US["IWM"]        # hedge 50/50 (só em memória)
    return g


def spin_sem_preco():
    """Spin-offs (10-12B) com ticker nos Forms 3/4 que negociaram (insiders arquivando por > 90 dias) mas não têm preço no Yahoo."""
    def f():
        g = _g()
        ev = g.spin_eventos()
        P = g._precos_ev("spinoffs")
        tk = g.cik_ticker()
        s = ev[~ev.ticker.isin(P.columns)].merge(tk[["cik", "tk", "d0", "d1"]], left_on=["cik", "ticker"], right_on=["cik", "tk"])
        return s[(s.d1 - s.d0).dt.days > 90]
    return _c("spin_sem", f)


def spin_cobertura():
    g = _g()
    ix = pd.read_parquet(D / "sec_indice.parquet")
    s10 = ix[ix.forma.isin(["10-12B", "10-12B/A"])].groupby("cik").data.min()
    ev = g.spin_eventos()
    P = g._precos_ev("spinoffs")
    sem = spin_sem_preco()
    return pd.DataFrame({"10-12B": s10.dt.year.value_counts(), "com ticker": ev.d10.dt.year.value_counts(),
                         "com preço": ev[ev.ticker.isin(P.columns)].d10.dt.year.value_counts(),
                         "negociou e sumiu": sem.d10.dt.year.value_counts()}).fillna(0).astype(int).sort_index()


def spin_aud(espera=40, dias=126, perda=-.30, hedge="SPYIWM", custo_mult=1, lag=0, detalhe=False):
    """G3 corrigido: mesmos eventos/regras do original + spin-offs sem preço com trajetória sintética (perda total `perda` em 166 pregões,
    começando no 1º Form 3/4) + hedge 50/50 SPY/IWM."""
    g = _g()
    P = g._precos_ev("spinoffs").copy()
    s = g.spin_eventos()
    ev = []
    for c, t, d in zip(s.cik, s.ticker, s.d10):
        if t not in P:
            continue
        x = P[t].dropna()
        x = x[x.index >= d - pd.Timedelta(days=30)]
        if len(x) > espera + 5 and x.index[0] <= d + pd.Timedelta(days=365) and (P[t].loc[:d - pd.Timedelta(days=30)].notna().sum() == 0):
            ev.append({"ticker": t, "data": x.index[espera]})
    if perda is not None:
        k = np.log1p(perda) / 166
        for t, d0 in zip(spin_sem_preco().ticker, spin_sem_preco().d0):
            i0 = DIAS_US.searchsorted(d0)
            n = min(300, len(DIAS_US) - i0)
            if n > espera + 5:
                P.loc[DIAS_US[i0:i0 + n], t + "*"] = np.exp(k * np.arange(n))
                ev.append({"ticker": t + "*", "data": DIAS_US[i0 + espera]})
    return g.carteira_eventos(pd.DataFrame(ev), P, dias, .05, hedge, .002, custo_mult, lag, detalhe=detalhe)


# =============================================================== E3 follow-on vendido [auditado]
def _small():
    def f():
        y = pd.read_parquet(D / "y_br_local.parquet")
        y.index = pd.DatetimeIndex(y.index).tz_localize(None).normalize()
        r = y["SMAL11.SA"].reindex(DIAS).ffill(limit=5).pct_change(fill_method=None)
        return r.fillna(R_IBOV.reindex(DIAS)).fillna(0)
    return _c("small", f)


def follow_on_aud(hold=20, n_max=5, piso_alug=.10, corte_adv=50e6, custo_mult=1, lag=0, detalhe=False):
    """E3 corrigido: mesmos eventos (1º FR de oferta por empresa em 90 dias, Data_Entrega), aluguel >= piso_alug, hedge por tamanho."""
    import ideias_eventos_br as eb
    p = eb.painel()
    ev = eb._ev("oferta", eb.ev_oferta)
    W = eb.posicoes(ev, hold, n_max)
    adv = p["ADV"].reindex(index=DIAS, columns=W.columns).ffill()
    al = np.maximum(eb.aluguel_acao(adv), piso_alug)
    e = eb.livro(W, 0.0, custo_mult, lag, alug=al, nome="e3_aud", rotulos=ev)
    Wx = W.reindex(DIAS).fillna(0).shift(1 + lag).fillna(0)
    grande = (adv >= corte_adv).shift(1 + lag).fillna(False).astype(bool)        # ADV conhecido na decisão
    cdi = CDI.reindex(DIAS)
    out = {}
    for nome, w, r in (("IBOV (hedge)", Wx.where(grande, 0).sum(axis=1), R_IBOV.reindex(DIAS).fillna(0)),
                       ("SMAL11 (hedge)", Wx.where(~grande, 0).sum(axis=1), _small())):
        h = -w
        out[nome] = h.shift(1).fillna(0) * (r - cdi) - h.diff().abs().fillna(0) * .0003 * custo_mult
    e = e + out["IBOV (hedge)"] + out["SMAL11 (hedge)"]
    if not detalhe:
        return e
    ct = eb.ULT["e3_aud"]["contrib"].copy()
    for k, v in out.items():
        ct[k] = v.astype("float32")
    return e, ct, eb.ULT["e3_aud"]["trades"]


# =============================================================== IE06 inclusão/exclusão S&P 500 / Nasdaq-100 [auditado]
_SUF = r"\b(INC|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|HOLDINGS?|GROUP|THE|NV|SA|LP|TRUST|INTERNATIONAL|INCORPORATED)\b"


def _nome(s):
    s = re.sub(r"[^A-Z ]", " ", str(s).upper())
    return re.sub(_SUF, " ", s).split()[:2]


def idx_eventos_aud():
    """Eventos de IE06 + diagnóstico: reciclado (ticker da época devolve OUTRA empresa no Yahoo), destino das excluídas sem preço."""
    def f():
        import ideias_i_eventos as ie
        ev = ie._cache("idx_us", ie.ev_indices_us).copy()
        w = ie.wiki_mudancas()
        nm = pd.concat([w[["indice", "efetiva", "entra", "entra_nome"]].set_axis(["indice", "efetiva", "tk_era", "nome_era"], axis=1).assign(lado="entra"),
                        w[["indice", "efetiva", "sai", "sai_nome"]].set_axis(["indice", "efetiva", "tk_era", "nome_era"], axis=1).assign(lado="sai")])
        ev = ev.merge(nm.drop_duplicates(["indice", "efetiva", "tk_era", "lado"]), on=["indice", "efetiva", "tk_era", "lado"], how="left")
        sec = ie.tickers_sec()
        vivo = set(sec.cik)
        dono = sec.drop_duplicates("tk").set_index("tk").nome
        P = ie._us()["P"]
        ev["tem_px"] = ev.ticker.isin(P.columns)
        ult = P.apply(lambda s: s.last_valid_index())
        hoje = P.index[-1] - pd.Timedelta(days=30)
        # reciclado: a empresa do evento sumiu da SEC e (a) o ticker hoje é de OUTRA empresa (nome diferente) ou (b) ninguém o tem na SEC mas
        # o Yahoo ainda tem preço até hoje (série de outra listagem). Ticker sem dono e série que acaba (deslistou há pouco) = mesma empresa.
        ev["reciclado"] = [(c not in vivo) and tp and ((t in dono.index and _nome(n) != _nome(dono[t])) or (t not in dono.index and ult[t] > hoje))
                           for c, t, n, tp in zip(ev.cik, ev.ticker, ev.nome_era, ev.tem_px)]
        ix = pd.read_parquet(D / "sec_indice.parquet")
        cap = ie._fts_ev("cap11", ["8-K"])
        cap = set(cap[cap.itens.str.contains("1.03", regex=False)].cik)
        quebra = ev.cik.isin(cap) | ev.motivo.fillna("").str.contains("FDIC|bankrupt|receivership|Chapter 11", case=False, regex=True)
        fusao = ev.cik.isin(set(ix[ix.forma.isin(["DEFM14A", "SC 14D9", "SC TO-T", "PREM14A", "DEFM14C"])].cik)) | \
            ev.motivo.fillna("").str.contains("acqui|merg|taken private", case=False, regex=True)
        ev["destino"] = np.where(quebra, "quebrou", np.where(fusao, "comprada", "outro"))
        return ev
    return _c("idx_aud", f)


def indices_us_aud(fase="pos", lado="ambos", dias=20, perda_quebra=-.50, custo_mult=1, lag=0, detalhe=False):
    """IE06 corrigido: sem tickers reciclados; excluídas que quebraram e sumiram do Yahoo entram com perda sintética no carregamento."""
    import ideias_i_eventos as ie
    ev = idx_eventos_aud()
    us = ie._us()
    P, R = us["P"], us["R"]
    cal = P.index
    ev = ev[~ev.reciclado].copy()
    sint = ev[(ev.lado == "sai") & ~ev.tem_px & (ev.destino == "quebrou")].copy()
    if perda_quebra is not None and len(sint):
        P, R = P.copy(), R.copy()
        for i, r in sint.iterrows():
            t = f"{r.tk_era}*{r.efetiva:%Y%m}"
            k0 = max(ie.pos_cal(cal, [r.efetiva])[0] - 60, 0)
            n = min(120, len(cal) - k0)
            px = np.ones(n)
            j = 60 - 2                                                          # a perda começa na execução (fechamento da véspera da efetiva)
            px[j:] = np.exp(np.log1p(perda_quebra) / dias * np.minimum(np.arange(n - j), dias))
            P.loc[cal[k0:k0 + n], t] = px
            R[t] = P[t].pct_change(fill_method=None)
            ev.loc[i, "ticker"] = t
            ev.loc[i, "tem_px"] = True
    out = []
    for fz in (["pre", "pos"] if fase == "pre+pos" else [fase]):
        e = ev.copy()
        if lado == "entra":
            e = e[e.lado == "entra"]
        kE = ie.pos_cal(cal, e.efetiva)
        if fz == "pre":
            ok = e.anuncio.notna().values
            kA = ie.pos_cal(cal, e.anuncio.fillna(pd.Timestamp("2100-01-01")))
            e = e.assign(i0=kA, i1=kE - 3)[ok & (kE - 3 >= kA)]
            e["lado"] = np.where(e.lado == "entra", 1, -1)
        else:
            e = e.assign(i0=kE - 2, i1=kE - 3 + dias)
            e["lado"] = np.where(e.lado == "entra", -1, 1)
        out.append(e)
    e = pd.concat(out)
    e = e[e.ticker.isin(P.columns)]
    hg = pd.Series(np.where(e.indice == "NDX", "QQQ", "SPY"), index=e.ticker).groupby(level=0).first()
    return ie.livro(e, P, R, hg.to_dict(), .10, 1.0, us["C"], us["A"], custo_mult, lag, detalhe, rf=TB_US)


# =============================================================== IE08 PEAD Ásia [auditado]
def _asia_ew():
    """Painel asiático + cesta igualitária dos membros ATUAIS por mercado (EW:JP/EW:KR/EW:HK), no calendário de cada mercado."""
    def f():
        import ideias_i_eventos as ie
        L = ie._local(["asia"])
        P, R = L["P"].copy(), L["R"].copy()
        mb = ie.membros_asia()
        for mk in ("JP", "KR", "HK"):
            cal = P[ie.IDX_LOCAL[mk]].dropna().index
            cols = [t for t in mb[mb.mercado == mk].ticker if t in R.columns]
            r = R.loc[cal, cols].clip(-.5, 1).mean(axis=1)
            R["EW:" + mk] = r.reindex(R.index).fillna(0)
            P["EW:" + mk] = (1 + R["EW:" + mk]).cumprod()
        return P, R
    return _c("asia_ew", f)


def vies_asia():
    """Deriva de sobrevivência: cesta igualitária dos membros atuais - índice local, por mercado, IS (2014-06..2020) e OOS (2021+), pp a.a."""
    import ideias_i_eventos as ie
    P, R = _asia_ew()
    out = {}
    for mk in ("JP", "KR", "HK"):
        cal = P[ie.IDX_LOCAL[mk]].dropna().index
        d = (R.loc[cal, "EW:" + mk] - R.loc[cal, ie.IDX_LOCAL[mk]]).fillna(0)
        out[mk] = {per: d[(d.index >= a) & (d.index < b)].mean() * 252 * 100 for per, a, b in
                   (("IS 2014-20", "2014-06-01", "2021-01-01"), ("OOS 2021+", "2021-01-01", "2100-01-01"))}
    return pd.DataFrame(out).T.round(1)


def pead_asia_aud(mercados="JP+KR+HK", limiar=.08, hold=60, filtro="reacao", hedge="ew", custo_mult=1, lag=0, detalhe=False):
    """IE08 com hedge na cesta igualitária dos mesmos sobreviventes (hedge='ew'; 'indice' reproduz o original)."""
    import ideias_i_eventos as ie
    e = ie.eventos_pead_asia()
    e = e[e.mercado.isin(mercados.split("+")) & (e.reacao.abs() >= limiar)].copy()
    e["lado"] = np.sign(e.reacao)
    if filtro == "concorda":
        e = e[e.surpresa == e.lado]
    for a, b in ie.VETO_VENDA_KR:
        e = e[~((e.mercado == "KR") & (e.lado < 0) & e.dec.between(a, b))]
    P, R = _asia_ew()
    cal = P.index
    e["i0"] = ie.pos_cal(cal, e.dec)
    e["i1"] = e.i0 + hold - 1
    c = e.drop_duplicates("ticker").set_index("ticker").mercado
    Cdf = pd.DataFrame([{t: ie.CUSTO_LOCAL[m][0] for t, m in c.items()}] * len(cal), index=cal)
    Adf = pd.DataFrame([{t: ie.CUSTO_LOCAL[m][1] for t, m in c.items()}] * len(cal), index=cal)
    hm = {t: ("EW:" + m if hedge == "ew" else ie.IDX_LOCAL[m]) for t, m in c.items()}
    return ie.livro(e, P, R, hm, .03, 1.0, Cdf, Adf, custo_mult, lag, detalhe, c_hedge=.0010 if hedge == "ew" else .0003, a_hedge=.005)


# =============================================================== FUNDOS
FUNDOS = [
    Fundo("G3 Spin-offs após a venda forçada [auditado]", "Event-driven", "CDI",
          "A separada é vendida por fundos de índice e gestores da controladora nas 1as semanas; o preço volta quando a venda acaba. "
          "Auditado: spin-offs que negociaram e sumiram do Yahoo entram com -30%; hedge 50/50 SPY/IWM",
          "Compra 10-40 pregões após o 1º preço, segura 6-12 meses, 5% por nome, hedge 50% SPY + 50% IWM; sem preço = -30% sintético",
          spin_aud, {"espera": [10, 20, 40], "dias": [126, 252]}, inicio="2008-01-01", corte="2021-01-01"),
    Fundo("E3 Follow-on vendido [auditado]", "Eventos BR", "CDI",
          "Vendo a ação que anuncia/precifica oferta subsequente. Auditado: aluguel mínimo 10% a.a. (papel em oferta) e hedge por tamanho "
          "(small/mid contra SMAL11, ADV >= R$50 mi contra Ibovespa)",
          "1º FR de oferta de ações por empresa em 90 dias (Data_Entrega), vendido 1/n_max do PL, aluguel max(1-8%, 10%) a.a., hedge Ibov/SMAL11",
          follow_on_aud, {"hold": [20, 40, 60], "n_max": [5, 10]}, inicio="2014-06-01"),
    Fundo("IE06 Inclusão/exclusão S&P 500 e Nasdaq-100 [auditado]", "Fluxo", "CDI",
          "Fundos de índice compram quem entra na véspera da efetiva; depois a pressão reverte. Auditado: sem tickers reciclados; excluídas "
          "que quebraram e sumiram do Yahoo entram com -50%",
          "pre/pos como o original (10% por nome, hedge SPY/QQQ); eventos com ticker reciclado removidos; quebradas sem preço = -50% em 20 pregões",
          indices_us_aud, {"fase": ["pre", "pos", "pre+pos"], "lado": ["entra", "ambos"]}, inicio="2008-01-01", corte="2021-01-01"),
    Fundo("IE08 PEAD Ásia (Japão, Coreia, Hong Kong) [auditado]", "Event-driven", "CDI",
          "Subreação a resultado na Ásia. Auditado: hedge contra a cesta igualitária dos mesmos membros ATUAIS (remove a deriva comum de sobrevivência)",
          "Como o original (3% por nome, reação t-1..t+1, decide t+1), mas hedge = cesta igualitária dos membros atuais do mercado, 10 bps",
          pead_asia_aud, {"mercados": ["JP+KR+HK", "JP"], "limiar": [.05, .08], "hold": [20, 60]}, inicio="2014-06-01", corte="2021-01-01"),
]


def medidas():
    print("G3 cobertura dos spin-offs:\n", spin_cobertura().to_string())
    ev = idx_eventos_aud()
    print("\nIE06 reciclados removidos:", int(ev.reciclado.sum()))
    print(ev[ev.reciclado][["indice", "lado", "tk_era", "nome_era", "efetiva", "ticker"]].to_string())
    s = ev[ev.lado == "sai"]
    print("\nIE06 excluídas: cobertura por destino (IS/OOS)")
    print(s.groupby([s.efetiva >= "2021-01-01", "destino"]).tem_px.agg(["size", "sum"]).to_string())
    print("\nIE08 deriva de sobrevivência (cesta dos membros atuais - índice, pp a.a.):\n", vies_asia().to_string())


if __name__ == "__main__" and sys.argv[1:2] == ["medidas"]:
    medidas()
    sys.exit()

if __name__ == "__main__":
    from motor import roda
    from regimes import com_regime
    from rodar import BENCH
    so = sys.argv[1:]
    res = []
    for f in FUNDOS:
        if so and f.nome.split()[0] not in so:
            continue
        t0 = time.time()
        r = roda(com_regime(f), CDI, BENCH[f.benchmark], lambda *a: None)
        if r is None:
            print(f.nome, "sem resultado")
            continue
        p = {k: v for k, v in r["params"].items() if k != "regime"}
        _, ct, tr = f.func(**p, detalhe=True)
        r["contrib"], r["trades"], r["modulo"] = ct, tr, "ideias_aud_eventos"
        o, rb = r["oos"], r["rob"]
        print(f"{f.nome[:55]:55s} {str(r['params']):70s} IR IS {r['is_ir']:5.2f} | OOS {o['retorno a.a. %']:5.1f}% vs {o['benchmark a.a. %']:5.1f}% "
              f"(ativo {o['ativo a.a. pp']:+.1f}) IR {o['IR vs bench']:5.2f} DD {o['pior queda %']:5.1f} | P {rb['P(bater bench OOS) %']:3.0f}% "
              f"PBO {rb['PBO %']:3.0f}% | c2 {rb['OOS custo x2 (pp)']:+5.1f} l1 {rb['OOS execução +1 dia (pp)']:+5.1f} | {time.time() - t0:.0f}s", flush=True)
        r["fundo"].func = None
        res.append(r)
    nome = "ideias_aud_eventos.pkl" if not so else f"ideias_aud_eventos_{'_'.join(so)}.pkl"
    pickle.dump(res, open(OUT / nome, "wb"))
    print("pronto", OUT / nome)
