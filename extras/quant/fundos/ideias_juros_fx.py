"""
Frente JUROS E CÂMBIO (macro de mesa, Brasil + mundo) — rodada 2.
  python ideias_juros_fx.py dados   -> baixa/atualiza dados novos (cache em dados/, nunca re-baixa o que existe)
  python ideias_juros_fx.py         -> roda os fundos e salva resultado/ideias_juros_fx.pkl
Instrumentos:
  - Tesouro (LTN, NTN-F, NTN-B, NTN-B principal) 2008+: retorno pela taxa (carry + IPCA - duration x dy), contra o CDI.
    Na prática a mesa usaria DI1/DAP (mesmo risco); as taxas do Tesouro Direto dão histórico desde 2005.
  - Futuros B3 2019+ (FRC/DDI/DOL) para o cupom cambial.
  - PTAX + CFTC + fluxo cambial BCB para o real; Yahoo + BIS/FMI para carry de moedas.
"""
import io
import pickle
import re
import sys
import time

import numpy as np
import pandas as pd
import requests

from base import BIS, CDI, DIAS, DIAS_US, FXY, IDX, PTAX, TB_US, brl, limpa_fx, mensal, semanal, sgs, vol_alvo, D, DQ

OLINDA = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"


# =============================================================== DADOS (cache em dados/)
def _olinda(recurso, filtro, campos):
    out, skip = [], 0
    while True:
        u = f"{OLINDA}{recurso}?$filter={filtro}&$select={campos}&$top=20000&$skip={skip}&$format=json"
        for t in range(5):
            try:
                v = requests.get(u, timeout=180).json()["value"]
                break
            except Exception:
                time.sleep(5 * (t + 1))
        else:
            raise RuntimeError(u)
        out += v
        if len(v) < 20000:
            return pd.DataFrame(out)
        skip += 20000


def focus_anuais():
    """Focus: medianas anuais de Selic (fim de ano) e IPCA (ano-calendário), por data de coleta. dados/focus_anuais.parquet"""
    f = D / "focus_anuais.parquet"
    if not f.exists():
        x = pd.concat([_olinda("ExpectativasMercadoAnuais", f"Indicador eq '{i}' and baseCalculo eq 0", "Indicador,Data,DataReferencia,Mediana")
                       for i in ("Selic", "IPCA")])
        x["Data"] = pd.to_datetime(x.Data)
        x["ref"] = pd.to_numeric(x.DataReferencia, errors="coerce")
        x.dropna(subset=["ref"]).to_parquet(f)
    return pd.read_parquet(f)


def focus_12m():
    """Focus: IPCA esperado 12 meses à frente (suavizado). dados/focus_ipca12m.parquet"""
    f = D / "focus_ipca12m.parquet"
    if not f.exists():
        x = _olinda("ExpectativasMercadoInflacao12Meses", "Indicador eq 'IPCA' and Suavizada eq 'S' and baseCalculo eq 0", "Data,Mediana")
        x["Data"] = pd.to_datetime(x.Data)
        x.to_parquet(f)
    return pd.read_parquet(f).groupby("Data").Mediana.last()


FRONT = {"EGP=X": "EGY", "NGN=X": "NGA", "KZT=X": "KAZ", "PKR=X": "PAK", "ARS=X": "ARG", "KES=X": "KEN", "UAH=X": "UKR", "GHS=X": "GHA",
         "UYU=X": "URY", "DOP=X": "DOM", "UZS=X": "UZB", "RSD=X": "SRB"}


def fx_fronteira():
    """Moedas de fronteira (Yahoo, unidades por USD). dados/y_fx_fronteira.parquet"""
    f = D / "y_fx_fronteira.parquet"
    if not f.exists():
        import yfinance as yf
        x = yf.download(list(FRONT), start="2005-01-01", progress=False, auto_adjust=True)["Close"]
        x.to_parquet(f)
    return pd.read_parquet(f)


def juros_fronteira():
    """FMI (MFS_IR, mensal): juro de mercado monetário > T-bill > política, por país. dados/imf_juros_fronteira.parquet"""
    f = D / "imf_juros_fronteira.parquet"
    if not f.exists():
        out = {}
        for ind in ("MMRT_RT_PT_A_PT", "GSTBILY_RT_PT_A_PT", "MFS166_RT_PT_A_PT"):
            t = requests.get(f"https://api.imf.org/external/sdmx/2.1/data/IMF.STA,MFS_IR/{'+'.join(FRONT.values())}.{ind}.M", timeout=180).text
            for m in re.finditer(r"<Series ([^>]*)>(.*?)</Series>", t, re.S):
                c = re.search(r'COUNTRY="(\w+)"', m.group(1)).group(1)
                ob = re.findall(r'TIME_PERIOD="(\d{4})-M(\d{2})" OBS_VALUE="([^"]+)"', m.group(2))
                out[(ind[:5], c)] = pd.Series({pd.Timestamp(int(a), int(b), 1): float(v) for a, b, v in ob})
        x = pd.DataFrame(out).sort_index()
        x.columns = [f"{a}_{b}" for a, b in x.columns]
        x.to_parquet(f)
    x = pd.read_parquet(f)
    r = {}
    for c in FRONT.values():
        s = None
        for ind in ("MMRT_", "GSTBI", "MFS16"):
            k = f"{ind}_{c}"
            if k in x:
                s = x[k] if s is None else s.combine_first(x[k])
        if s is not None:
            r[c] = s
    return pd.DataFrame(r)


def baixa():
    for cod in (432, 433, 22704):
        print(cod, len(sgs(cod)))
    print("focus anuais", len(focus_anuais()), "focus 12m", len(focus_12m()))
    print("fx fronteira", fx_fronteira().shape, "juros fronteira", juros_fronteira().shape)


# =============================================================== BASES COMUNS
CDI1 = CDI.shift(1).fillna(0)                      # CDI que remunera o dia t (de t-1 para t)
TIPOS = {"Tesouro Prefixado": "LTN", "Tesouro Prefixado com Juros Semestrais": "NTNF", "Tesouro IPCA+": "NTNBP",
         "Tesouro IPCA+ com Juros Semestrais": "NTNB"}
CUPOM = {"LTN": 0.0, "NTNBP": 0.0, "NTNF": 1.1 ** .5 - 1, "NTNB": 1.06 ** .5 - 1}
_C = {}


def _cache(nome, f):
    if nome not in _C:
        _C[nome] = f()
    return _C[nome]


def ipca_diario():
    """IPCA mensal realizado (SGS 433) rateado pelos dias úteis do mês (é o que corrige o VNA da NTN-B/DAP)."""
    m = sgs(433) / 100
    m.index = m.index.to_period("M")
    per = pd.Series(DIAS.to_period("M"), index=DIAS)
    n = per.map(per.value_counts())
    v = per.map(m).ffill()
    return (1 + v) ** (1 / n) - 1


def _dur(y, T, c):
    """Duration modificada (anos) de título com cupom semestral c (taxa efetiva anual y, prazo T anos)."""
    if c == 0:
        return T / (1 + y)
    P = np.zeros_like(y)
    S = np.zeros_like(y)
    for k in range(0, 90):
        t = T - .5 * k
        ok = t > 0
        cf = c + (k == 0)
        df = np.where(ok, (1 + y) ** -np.where(ok, t, 0), 0)
        P += cf * df
        S += np.where(ok, t, 0) * cf * df
    return S / P / (1 + y)


def td():
    """Painel do Tesouro: Y (taxa), T (prazo em anos), Dm (duration mod.), R (excesso diário sobre o CDI), tipo por coluna."""
    def f():
        t = pd.read_csv(DQ / "tesouro_direto.csv", sep=";", decimal=",")
        t = t[t["Tipo Titulo"].isin(TIPOS)].copy()
        t["d"] = pd.to_datetime(t["Data Base"], dayfirst=True)
        t["v"] = pd.to_datetime(t["Data Vencimento"], dayfirst=True)
        t["tp"] = t["Tipo Titulo"].map(TIPOS)
        t["col"] = t.tp + "_" + t.v.dt.strftime("%Y-%m")
        Y0 = t.pivot_table(index="d", columns="col", values="Taxa Venda Manha", aggfunc="last") / 100
        Y0 = Y0.where(Y0 > 0)
        Y = Y0.reindex(DIAS).ffill(limit=3)
        venc = t.groupby("col").v.first().reindex(Y.columns)
        tipo = t.groupby("col").tp.first().reindex(Y.columns)
        T = pd.DataFrame((venc.values[None, :] - DIAS.values[:, None]) / np.timedelta64(1, "D") / 365.25, index=DIAS, columns=Y.columns)
        T = T.where(Y.notna() & (T > 0))
        Y = Y.where(T.notna())
        Dm = pd.DataFrame(index=DIAS, columns=Y.columns, dtype=float)
        for c in Y.columns:
            Dm[c] = _dur(Y[c].to_numpy(), T[c].to_numpy(), CUPOM[tipo[c]])
        pi = ipca_diario()
        carry = (1 + Y.shift(1)) ** (1 / 252) - 1
        real = tipo.isin(["NTNB", "NTNBP"]).values
        carry.loc[:, real] = (1 + carry.loc[:, real]).mul(1 + pi, axis=0) - 1
        dy = Y.diff()
        R = carry - Dm.shift(1) * dy + .5 * Dm.shift(1) ** 2 * dy ** 2
        R = R.sub(CDI1, axis=0)
        R = R.where(Y.shift(1).notna() & Y.notna())
        T0 = pd.DataFrame((venc.values[None, :] - Y0.index.values[:, None]) / np.timedelta64(1, "D") / 365.25, index=Y0.index, columns=Y0.columns)
        return {"Y": Y, "T": T, "Dm": Dm, "R": R, "tipo": tipo, "Y0": Y0.where(T0 > 0), "T0": T0.where(T0 > 0)}
    return _cache("td", f)


def curva(tipos, H, completa=False):
    """Taxa interpolada (linear no prazo) no vértice H anos usando os títulos dos tipos dados (sinal, não instrumento).
    completa=True: histórico inteiro do Tesouro Direto (2005+, datas próprias); senão, no calendário DIAS (2008+)."""
    def f():
        P = td()
        cols = P["tipo"][P["tipo"].isin(tipos)].index
        Y, T = P["Y0"][cols].to_numpy(), P["T0"][cols].to_numpy()
        out = np.full(len(Y), np.nan)
        for i in range(len(Y)):
            ok = ~np.isnan(Y[i]) & ~np.isnan(T[i]) & (T[i] > .2)
            if ok.sum() >= 2:
                o = np.argsort(T[i][ok])
                x, yv = T[i][ok][o], Y[i][ok][o]
                if x[0] <= H * 1.6 and x[-1] >= H * .6:
                    out[i] = np.interp(H, x, yv)
        return pd.Series(out, index=P["Y0"].index)
    c = _cache(f"curva{tipos}{H}", f)
    return c if completa else c.reindex(DIAS.union(c.index)).ffill(limit=3).reindex(DIAS)


def escolhe(tipos, alvo, lo, hi):
    """Título (coluna) com prazo mais próximo de `alvo` anos dentro de [lo, hi], por data."""
    P = td()
    cols = P["tipo"][P["tipo"].isin(tipos)].index
    T = P["T"][cols].where((P["T"][cols] >= lo) & (P["T"][cols] <= hi))
    ok = T.notna().any(axis=1)
    return (T - alvo).abs().fillna(1e9).idxmin(axis=1).where(ok)


def matriz(escolha, peso, cols):
    """Matriz de pesos com `peso` na coluna escolhida em cada data."""
    W = pd.DataFrame(0.0, index=DIAS, columns=cols)
    e = escolha.reindex(DIAS)
    p = peso.reindex(DIAS).fillna(0)
    ok = e.notna() & (p != 0)
    ci = pd.Index(cols).get_indexer(e[ok])
    W.values[np.flatnonzero(ok.values), ci] = p[ok].values
    return W


def estado(entra_mais, entra_menos, sai):
    """Máquina de estados: +1/-1 ao disparar, 0 na saída, senão mantém."""
    s = pd.Series(np.nan, index=entra_mais.index)
    s[sai.fillna(False).astype(bool)] = 0.0
    s[entra_mais.fillna(False).astype(bool)] = 1.0
    s[entra_menos.fillna(False).astype(bool)] = -1.0
    return s.ffill().fillna(0)


def focus_diario():
    """Focus como o mercado conhece (coleta + 1 dia útil): Selic fim de ano e IPCA ano-calendário h=0..4; IPCA 12m."""
    def f():
        x = focus_anuais().copy()
        x["h"] = x.ref - x.Data.dt.year
        x = x[(x.h >= 0) & (x.h <= 4)]
        P = x.pivot_table(index="Data", columns=["Indicador", "h"], values="Mediana", aggfunc="last")
        P[("IPCA12", 0)] = focus_12m()
        P = P.sort_index()
        P = P.reindex(DIAS.union(P.index)).ffill().reindex(DIAS).shift(1)
        for i in ("Selic", "IPCA"):                                       # horizonte ausente: usa o mais próximo disponível
            for h in range(1, 5):
                P[(i, h)] = P[(i, h)].fillna(P[(i, h - 1)])
        return P
    return _cache("focus", f)


def selic_esperada():
    """Trajetória esperada da Selic (Focus): hoje (meta) -> fim do ano -> fim do ano seguinte, linear. Média dos próximos 12m e ponto em 12m."""
    def f():
        F = focus_diario()
        s = sgs(432)
        S0 = s.reindex(DIAS.union(s.index)).ffill().reindex(DIAS)
        FY, FY1 = F[("Selic", 0)].fillna(S0), F[("Selic", 1)]
        t1 = pd.Series((pd.to_datetime((DIAS.year).astype(str) + "-12-31") - DIAS).days / 365.25, index=DIAS).clip(lower=1 / 365)
        vals = []
        for tt in np.linspace(0, 1, 25):
            a = S0 + (FY - S0) * np.minimum(tt / t1, 1)
            b = FY + (FY1 - FY) * np.clip(tt - t1, 0, 1)
            vals.append(np.where(tt <= t1, a, b))
        V = np.vstack(vals)
        return pd.DataFrame({"S0": S0, "media12": V.mean(axis=0), "em12": V[-1]}, index=DIAS)
    return _cache("selic", f)


# =============================================================== EXECUÇÃO, CUSTOS E NEGÓCIOS
def livro(W, R, cst, lag=0, custo_mult=1):
    """W decidido no fechamento de t -> executado no fechamento de t+1(+lag) -> rende a partir de t+2.
    cst: custo por unidade de notional girada (DataFrame alinhado ou escalar). Devolve (contribuição por ativo, posição executada)."""
    W = W.reindex(index=R.index, columns=R.columns).fillna(0)
    Wx = W.shift(1 + lag).fillna(0)
    pnl = Wx.shift(1).fillna(0) * R.fillna(0)
    if isinstance(cst, pd.DataFrame):
        cst = cst.reindex(index=R.index, columns=R.columns).ffill().bfill().fillna(.002)
    giro = Wx.diff().abs().fillna(Wx.abs()) * cst * custo_mult
    return pnl - giro, Wx


def negocios(est, contrib, ativos=None, extras=None):
    """Um negócio = trecho contínuo com o mesmo sinal de `est` (estado executado). Contribuição = soma do resultado (% do PL)
    do dia da execução até o dia seguinte à saída (inclui custos de entrada e saída)."""
    est = est.fillna(0)
    sg = np.sign(est).to_numpy()
    tot = contrib.sum(axis=1).to_numpy() if isinstance(contrib, pd.DataFrame) else contrib.to_numpy()
    idx = est.index
    rows, i, n = [], 0, len(sg)
    while i < n:
        if sg[i] == 0:
            i += 1
            continue
        j = i
        while j + 1 < n and sg[j + 1] == sg[i]:
            j += 1
        k = min(j + 1, n - 1)
        r = {"ativo": "", "lado": "comprado" if sg[i] > 0 else "vendido", "entrada": idx[i], "saida": idx[k], "dias": j - i + 1,
             "contrib_%PL": tot[i:k + 1].sum() * 100}
        if ativos is not None:
            r["ativo"] = " / ".join(pd.unique(ativos.iloc[i:j + 1].dropna().astype(str)))
        for nm, s in (extras or {}).items():
            r[f"{nm}_entrada"], r[f"{nm}_saida"] = s.iloc[i], s.iloc[k]
        rows.append(r)
        i = j + 1
    return pd.DataFrame(rows)


def negocios_por_ativo(Wx, contrib, extras=None):
    out = []
    for c in Wx.columns:
        if (Wx[c] != 0).any():
            n = negocios(np.sign(Wx[c]), contrib[c], None, {k: v[c] for k, v in (extras or {}).items() if c in v})
            n["ativo"] = c
            out.append(n)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def saida(contrib, trades, detalhe):
    ex = contrib.sum(axis=1).reindex(DIAS).fillna(0)
    return (ex, contrib, trades) if detalhe else ex




def _dur_de(escolha):
    Dm = td()["Dm"]
    return pd.Series([Dm.at[d, c] if isinstance(c, str) else np.nan for d, c in escolha.items()], index=escolha.index)


# =============================================================== F1 JURO REAL DE VALOR (NTN-B longa)
def juro_real(regra="p85", filtro=0, dur=5.0, custo_mult=1, lag=0, detalhe=False):
    """IPCA+7% numa NTN-B longa é demais: compra NTN-B ~15 anos quando o juro real de 10 anos está em extremo.
    regra 'pXX': acima do percentil XX dos últimos 5 anos (histórico desde 2005), zera abaixo do percentil 50;
    regra 'aX': acima de X% a.a., zera abaixo de X-1%. filtro=1: só entra se também estiver > juro real neutro do Focus + 0,5 pp
    (Selic esperada em 3 anos / IPCA esperado em 3 anos). Tamanho: `dur` anos de duration por PL."""
    P = td()
    y0 = curva(["NTNBP", "NTNB"], 10, completa=True)
    pct0 = y0.rolling(1250, min_periods=500).apply(lambda x: (x[-1] >= x).mean(), raw=True)
    re_ = lambda s: s.reindex(DIAS.union(s.index)).ffill(limit=3).reindex(DIAS)
    y10, pct = re_(y0), re_(pct0)
    F = focus_diario()
    neutro = (1 + F[("Selic", 3)] / 100) / (1 + F[("IPCA", 3)] / 100) - 1
    if regra.startswith("p"):
        ent, sai = pct > int(regra[1:]) / 100, pct < .5
    else:
        x = float(regra[1:]) / 100
        ent, sai = y10 > x, y10 < x - .01
    if filtro:
        ent &= (y10 - neutro) > .005
    st = estado(ent, pd.Series(False, index=DIAS), sai).clip(lower=0)
    bond = escolhe(["NTNBP", "NTNB"], 15, 8, 30)
    st = st.where(bond.notna(), 0)
    W = matriz(bond, st * dur / _dur_de(bond), P["R"].columns)
    contrib, Wx = livro(W, P["R"].fillna(0), .0003 * P["Dm"], lag, custo_mult)   # 3 bps de taxa por negócio
    contrib = contrib.loc[:, (Wx != 0).any()]
    tr = None
    if detalhe:
        tr = negocios(st.shift(1 + lag), contrib, bond.shift(1 + lag),
                      {"juro_real_10a_%": y10 * 100, "percentil_5a": pct, "neutro_focus_%": neutro * 100})
    return saida(contrib, tr, detalhe)


# =============================================================== F2 INFLAÇÃO IMPLÍCITA x FOCUS
def inflacao_implicita(z_in=1.5, janela=504, lado="ambos", H=3, K=5.0, custo_mult=1, lag=0, detalhe=False):
    """Breakeven de H anos (pré x NTN-B) contra a inflação esperada pelo Focus no mesmo horizonte. Prêmio de inflação muito acima
    do normal -> vende inflação (compra pré, vende NTN-B/DAP), DV01 neutro; muito abaixo -> compra inflação. Sai quando o z cruza 0."""
    P = td()
    be = (1 + curva(["LTN", "NTNF"], H)) / (1 + curva(["NTNBP", "NTNB"], H)) - 1
    F = focus_diario()
    a2 = pd.Series(np.where(DIAS.month <= 6, F[("IPCA", 1)], F[("IPCA", 2)]), index=DIAS)
    a3 = pd.Series(np.where(DIAS.month <= 6, F[("IPCA", 2)], F[("IPCA", 3)]), index=DIAS)
    esp = ((1 + F[("IPCA12", 0)] / 100) * (1 + a2 / 100) * (1 + a3 / 100)) ** (1 / 3) - 1
    gap = (be - esp).rolling(5, min_periods=3).median()                    # mediana de 5 dias: tira saltos de interpolação na troca de títulos
    z = (gap - gap.rolling(janela, min_periods=janela // 2).mean()) / gap.rolling(janela, min_periods=janela // 2).std()
    menos = (z < -z_in) & (lado == "ambos")
    s0 = estado(z > z_in, menos, pd.Series(False, index=DIAS))
    st = estado(z > z_in, menos, (z * s0) < 0)
    nom = escolhe(["LTN", "NTNF"], H, H - 1.2, H + 1.5)
    rea = escolhe(["NTNBP", "NTNB"], H, H - 1.5, H + 2.5)
    st = st.where(nom.notna() & rea.notna(), 0)
    W = matriz(nom, st * K / _dur_de(nom), P["R"].columns) + matriz(rea, -st * K / _dur_de(rea), P["R"].columns)
    contrib, Wx = livro(W, P["R"].fillna(0), .0003 * P["Dm"], lag, custo_mult)
    contrib = contrib.loc[:, (Wx != 0).any()]
    tr = None
    if detalhe:
        pares = (nom + " x " + rea).shift(1 + lag)
        tr = negocios(st.shift(1 + lag), contrib, pares, {"breakeven_%": be * 100, "focus_%": esp * 100, "gap_pp": gap * 100})
        tr["lado"] = tr.lado.map({"comprado": "vende inflação", "vendido": "compra inflação"})
    return saida(contrib, tr, detalhe)


# =============================================================== F3 PRÊMIO DO DI 1 ANO x SELIC ESPERADA (Focus)
def premio_1a(thr=1.0, lado="ambos", filtro=1, K=2.0, custo_mult=1, lag=0, detalhe=False):
    """Taxa pré de 1 ano contra a média da Selic que o Focus espera para os próximos 12 meses (- 0,10 pp = CDI).
    Prêmio > thr: o mercado paga demais por proteção -> recebe taxa (compra LTN/DI1 ~1 ano). Prêmio < -thr: paga taxa.
    Sai quando o prêmio volta para menos de thr/3. Tamanho: K anos de duration por PL.
    filtro=1 (lição de 2021): só recebe se o Focus NÃO está revisando a Selic para cima (média 12m esperada não subiu em 4 semanas),
    só paga se não está revisando para baixo; se a revisão vira contra a posição, zera."""
    P = td()
    y1 = curva(["LTN", "NTNF"], 1)
    esp = (selic_esperada()["media12"] - .10) / 100
    prem = (y1 - esp) * 100
    rev = esp.diff(20) * 100
    sobe, desce = (rev > .1) if filtro else pd.Series(False, index=DIAS), (rev < -.1) if filtro else pd.Series(False, index=DIAS)
    st = estado((prem > thr) & ~sobe, (prem < -thr) & (lado == "ambos") & ~desce,
                (prem.abs() < thr / 3) | ((prem > 0) & sobe) | ((prem < 0) & desce))   # revisão do Focus contra a posição -> zera
    bond = escolhe(["LTN", "NTNF"], 1, .6, 1.7)
    st = st.where(bond.notna(), 0)
    W = matriz(bond, st * K / _dur_de(bond), P["R"].columns)
    contrib, Wx = livro(W, P["R"].fillna(0), .0002 * P["Dm"], lag, custo_mult)
    contrib = contrib.loc[:, (Wx != 0).any()]
    tr = None
    if detalhe:
        tr = negocios(st.shift(1 + lag), contrib, bond.shift(1 + lag), {"taxa_1a_%": y1 * 100, "cdi_esperado_%": esp * 100, "premio_pp": prem})
        tr["lado"] = tr.lado.map({"comprado": "recebe taxa", "vendido": "paga taxa"})
    return saida(contrib, tr, detalhe)


# =============================================================== F4 INCLINAÇÃO CONDICIONADA AO CICLO
def inclinacao(thr=.75, cond=1, curto=1, K=3.0, custo_mult=1, lag=0, detalhe=False):
    """Focus espera cortes de > thr pp nos próximos 12m -> steepener (recebe o curto, paga o 5 anos), DV01 neutro;
    espera altas > thr -> flattener. Com cond=1 só entra se a inclinação (5a - curto) estiver do lado 'barato' da mediana de 2 anos.
    Sai quando a mudança esperada da Selic fica menor que thr/2."""
    P = td()
    S = selic_esperada()
    dS = S["em12"] - S["S0"]
    sl = curva(["LTN", "NTNF"], 5) - curva(["LTN", "NTNF"], curto)
    med = sl.rolling(504, min_periods=250).median()
    mais, menos = dS < -thr, dS > thr
    if cond:
        mais &= sl < med
        menos &= sl > med
    st = estado(mais, menos, dS.abs() < thr / 2)
    cs = escolhe(["LTN", "NTNF"], curto, curto - .5, curto + .8)
    lg = escolhe(["LTN", "NTNF"], 5, 4, 7)
    st = st.where(cs.notna() & lg.notna(), 0)
    W = matriz(cs, st * K / _dur_de(cs), P["R"].columns) + matriz(lg, -st * K / _dur_de(lg), P["R"].columns)
    contrib, Wx = livro(W, P["R"].fillna(0), .0002 * P["Dm"], lag, custo_mult)
    contrib = contrib.loc[:, (Wx != 0).any()]
    tr = None
    if detalhe:
        tr = negocios(st.shift(1 + lag), contrib, (cs + " x " + lg).shift(1 + lag),
                      {"inclinacao_pp": sl * 100, "var_selic_esperada_12m_pp": dS})
        tr["lado"] = tr.lado.map({"comprado": "steepener", "vendido": "flattener"})
    return saida(contrib, tr, detalhe)


# =============================================================== F5 CUPOM CAMBIAL CURTO x SOFR
def futuros():
    def f():
        x = pd.read_parquet(DQ / "futuros.parquet").drop_duplicates(["date", "ticker"])
        M = dict(zip("FGHJKMNQUVXZ", range(1, 13)))
        x = x[x.ticker.str.len() == 6].copy()
        x["venc"] = pd.to_datetime(dict(year=2000 + x.ticker.str[-2:].astype(int), month=x.ticker.str[3].map(M), day=1))
        return x
    return _cache("fut", f)


def juro_usd():
    f = pd.read_parquet(D / "fred_diario.parquet")
    u = f["SOFR"].combine_first(f["DFF"])
    return u.reindex(DIAS.union(u.index)).ffill().reindex(DIAS)


def cupom_curto(thr=1.0, sair=.25, peso=5.0, funding=.5, custo_mult=1, lag=0, detalhe=False):
    """Cupom cambial limpo do 1º FRC (FRA de cupom de ~1 mês, o único com preço de verdade) contra SOFR + funding (0,5% a.a.).
    Escassez de dólar onshore (cupom >> SOFR) -> empresta dólar onshore: compra DOL e vende dólar à vista com caixa offshore,
    isto é, recebe cupom e paga SOFR + funding. Entra se o spread líquido > thr, sai se < sair.
    Resultado = carry diário do spread + marcação (-0,083 x variação do cupom do mesmo contrato). Custo 3 bps + 1 bp/mês de rolagem."""
    x = futuros()
    fr = x[x.ticker.str.startswith("FRC") & x.AdjstdQtTax.notna() & (x.AdjstdQtTax != 0)].sort_values(["date", "venc"])
    prim = fr.groupby("date").first()
    c = prim.AdjstdQtTax.reindex(DIAS)
    tk = prim.ticker.reindex(DIAS)
    piv = fr.pivot_table(index="date", columns="ticker", values="AdjstdQtTax").reindex(DIAS)
    us = juro_usd()
    sp = c - us - funding
    st = estado(sp > thr, pd.Series(False, index=DIAS), sp < sair).where(c.notna(), 0)
    ontem = tk.shift(1)
    hoje_mesmo = pd.Series([piv.at[d, t] if isinstance(t, str) and t in piv.columns else np.nan for d, t in ontem.items()], index=DIAS)
    dmesmo = hoje_mesmo - c.shift(1)
    cal = pd.Series(DIAS, index=DIAS).diff().dt.days.fillna(1)
    R = (sp.shift(1) / 100 * cal / 360 - .083 * dmesmo.fillna(0) / 100).fillna(0)
    W = (st * peso).to_frame("cupom")
    contrib, Wx = livro(W, R.to_frame("cupom"), .0003, lag, custo_mult)
    contrib = contrib - (Wx.shift(1).fillna(0).abs() * .0001 / 21 * custo_mult)
    tr = negocios(st.shift(1 + lag), contrib, tk.shift(1 + lag), {"cupom_limpo_%": c, "sofr_%": us, "spread_liq_pp": sp}) if detalhe else None
    return saida(contrib, tr, detalhe)


# =============================================================== F6 REAL TÁTICO (juro real, CFTC, fluxo)
def _cot_brl():
    c = pd.read_parquet(D / "cot.parquet")
    nome = [x for x in c.columns if "Market_and_Exchange" in x][0]
    dt = [x for x in c.columns if "YYYY-MM-DD" in x][0]
    c = c[c[nome].str.contains("BRAZILIAN REAL", na=False) & (c.relatorio == "fin")].dropna(subset=[dt])
    s = ((c.Lev_Money_Positions_Long_All - c.Lev_Money_Positions_Short_All) / c.Open_Interest_All).groupby(pd.to_datetime(c[dt])).mean()
    s.index = s.index + pd.Timedelta(days=3)                            # relatório de terça, publicado na sexta
    return s.reindex(DIAS.union(s.index)).ffill().reindex(DIAS)


def r_brl():
    """Comprado em real (vendido em DOL): -variação da PTAX + carry (CDI - cupom cambial); cupom ~ T-bill + 1,0% a.a.
    (2019+: o FRC curto ficou em média 1,07 pp acima da SOFR)."""
    tb = (TB_US * 252).reindex(DIAS.union(TB_US.index)).ffill().reindex(DIAS)
    return (-PTAX.pct_change(fill_method=None) + CDI - (tb + .01) / 252).fillna(0)


def real_tatico(sinais="juro+cot+fluxo", janela=756, alvo=.10, custo_mult=1, lag=0, detalhe=False):
    """Real contra o dólar: diferencial de juro real Brasil-EUA alto (z) -> comprado em real; especuladores (CFTC, leveraged funds)
    em extremo de posição -> contra eles; fluxo cambial de 3 meses forte (BCB) -> comprado em real. Semanal, vol-alvo 10% na convicção cheia."""
    zz = lambda x, j: (x - x.rolling(j, min_periods=j // 2).mean()) / x.rolling(j, min_periods=j // 2).std()
    F = focus_diario()
    fr = pd.read_parquet(D / "fred_diario.parquet")
    us_real = (fr["DFF"] - fr["T5YIE"]).reindex(DIAS.union(fr.index)).ffill().reindex(DIAS)
    dif = (selic_esperada()["S0"] - F[("IPCA12", 0)]) - us_real
    s = {"juro": zz(dif, janela).clip(-2, 2) / 2}
    zc = zz(_cot_brl(), janela)
    s["cot"] = -np.sign(zc) * (zc.abs() > 1.5)
    fl3 = sgs(22704).rolling(3).sum()
    fl3.index = fl3.index + pd.offsets.MonthBegin(1) + pd.Timedelta(days=12)   # mês fechado sai no início do mês seguinte
    fl3 = fl3.reindex(DIAS.union(fl3.index)).ffill().reindex(DIAS)
    s["fluxo"] = zz(fl3, janela).clip(-2, 2) / 2
    score = pd.concat([s[k] for k in sinais.split("+")], axis=1).mean(axis=1).fillna(0)
    R = r_brl()
    vol = R.rolling(63, min_periods=40).std() * np.sqrt(252)
    W = semanal((score * alvo / vol).clip(-2, 2).fillna(0).to_frame("BRL"))
    contrib, Wx = livro(W, R.to_frame("BRL"), .0002, lag, custo_mult)
    tr = None
    if detalhe:
        tr = negocios(np.sign(Wx["BRL"]), contrib, None, {"ptax": PTAX, "dif_juro_real_pp": dif, "score": score})
        tr["ativo"] = "BRL (DOL)"
        tr["lado"] = tr.lado.map({"comprado": "comprado em real", "vendido": "vendido em real"})
    return saida(contrib, tr, detalhe)


# =============================================================== F7 CARRY DE MOEDAS REALISTA (CME/B3) e FRONTEIRA
REAL = {"EURUSD=X": ("XM", 1, "G10"), "GBPUSD=X": ("GB", 1, "G10"), "AUDUSD=X": ("AU", 1, "G10"), "NZDUSD=X": ("NZ", 1, "G10"),
        "JPY=X": ("JP", -1, "G10"), "CAD=X": ("CA", -1, "G10"), "CHF=X": ("CH", -1, "G10"), "NOK=X": ("NO", -1, "G10"),
        "SEK=X": ("SE", -1, "G10"), "MXN=X": ("MX", -1, "EM"), "ZAR=X": ("ZA", -1, "EM"), "PLN=X": ("PL", -1, "EM"),
        "HUF=X": ("HU", -1, "EM"), "CZK=X": ("CZ", -1, "EM"), "ILS=X": ("IL", -1, "EM"), "TRY=X": ("TR", -1, "EM"),
        "CNY=X": ("CN", -1, "EM")}


def carry_realista(n=3, protecao="vix", lado="ls", alvo=.08, teto=.2, custo_mult=1, lag=0, detalhe=False):
    """Só moedas com futuro na CME/B3 (G10 + MXN, ZAR, PLN, HUF, CZK, ILS, TRY, CNH). Carry = diferencial BIS
    (EM com haircut de 50%: o forward entregável paga menos que o juro de política). Proteção: zera quando VIX > VIX3M
    (curva invertida) ou VIX acima do percentil 80 de 1 ano. Teto por moeda, vol-alvo, rebalanceamento mensal."""
    v = pd.DataFrame({k: FXY[k] ** s for k, (c, s, g) in REAL.items() if k in FXY}).reindex(DIAS_US).ffill(limit=5)
    spot = limpa_fx(v.pct_change(fill_method=None))
    i = BIS.reindex(DIAS_US).ffill()
    dif = pd.DataFrame({k: (i[c] - i["US"]) / 100 * (1 if g == "G10" else .5) for k, (c, s, g) in REAL.items() if k in v}).reindex(DIAS_US)
    R = (spot + dif.shift(1) / 252).fillna(0)
    rk = dif.rank(axis=1, ascending=False)
    W = (rk <= n).astype(float) - ((rk > dif.notna().sum(axis=1).values[:, None] - n) & dif.notna()).astype(float) * (lado == "ls")
    vol = spot.rolling(63, min_periods=40).std()
    W = (W / vol).div((W / vol).abs().sum(axis=1).replace(0, np.nan), axis=0).fillna(0).clip(-teto, teto)
    W = mensal(W)
    if protecao == "vix":
        vx, v3 = IDX["^VIX"].reindex(DIAS_US).ffill(), IDX["^VIX3M"].reindex(DIAS_US).ffill()
        risco = (vx > v3) | (vx > vx.rolling(252, min_periods=126).quantile(.8))
        W = W.mul((~risco).astype(float), axis=0)
    W = vol_alvo(W, R, alvo)
    c1 = pd.Series({k: .0002 if REAL[k][2] == "G10" else .0012 for k in R.columns})
    cst = pd.DataFrame(np.tile(c1.values, (len(R), 1)), index=R.index, columns=R.columns)
    contrib_us, Wx = livro(W, R, cst, lag, custo_mult)
    contrib = contrib_us.apply(brl)
    tr = negocios_por_ativo(Wx.reindex(DIAS, method="ffill").fillna(0), contrib) if detalhe else None
    return saida(contrib, tr, detalhe)


def limpa_log(v, lim=.08):
    """Cotação de fronteira no Yahoo tem erros de 100x que se desfazem no dia seguinte. Em log: zera o par de dias quando o salto
    (> lim) é desfeito em até 2 dias (|soma| < 10% do salto). Desvalorizações de verdade (ARS -54% em dez/23, EGP -42% em nov/16,
    NGN -25% em fev/24) ficam. Devolve o preço reconstruído."""
    lr = np.log(v.ffill()).diff()
    for c in lr.columns:
        x = lr[c].to_numpy().copy()
        for i in range(1, len(x)):
            if np.isfinite(x[i]) and abs(x[i]) > lim:
                for k in (1, 2):
                    if i + k < len(x):
                        s = np.nansum(x[i + 1:i + k + 1])
                        if abs(x[i] + s) < .1 * abs(x[i]):
                            x[i:i + k + 1] = 0.0
                            break
        lr[c] = x
    base = v.bfill().iloc[0]
    return np.exp(lr.fillna(0).cumsum()).mul(base).where(v.notna())


def carry_fronteira(n=4, haircut=1.0, filtro=1, custo_mult=1, lag=0, detalhe=False):
    """O carry que ninguém arbitra: comprado (vs USD) nas n moedas de fronteira de maior juro local (FMI: mercado monetário >
    T-bill > política, defasado 2 meses), peso igual, mensal, custo de 75 bps por lado (150 bps ida e volta).
    filtro=1: não entra em moeda que caiu > 10% em 3 meses (desvalorização em curso)."""
    v = _cache("vfront", lambda: limpa_log(1 / fx_fronteira().reindex(DIAS_US).ffill(limit=5)))
    spot = v.pct_change(fill_method=None)
    jr = juros_fronteira()
    jr.index = jr.index + pd.offsets.MonthBegin(2)
    jr = jr.reindex(DIAS_US.union(jr.index)).ffill(limit=300).reindex(DIAS_US)
    us = (TB_US * 252).reindex(DIAS_US).ffill()
    dif = pd.DataFrame({k: (jr[c] / 100 - us) * haircut for k, c in FRONT.items() if c in jr and k in v}).reindex(DIAS_US)
    vivo = v[dif.columns].notna() & (v[dif.columns].diff().abs().rolling(21).sum() > 0)   # cotação viva (não congelada no Yahoo)
    dif = dif.where(vivo)
    R = (spot[dif.columns] + dif.shift(1).fillna(0) / 252).fillna(0)
    elegivel = dif.notna() & (dif > .02)
    if filtro:
        elegivel &= (v[dif.columns] / v[dif.columns].shift(63) - 1) > -.10
    rk = dif.where(elegivel).rank(axis=1, ascending=False)
    W = (rk <= n).astype(float)
    W = W.div(W.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    W = mensal(W)
    contrib_us, Wx = livro(W, R, .0075, lag, custo_mult)
    contrib = contrib_us.apply(brl)
    tr = negocios_por_ativo(Wx.reindex(DIAS, method="ffill").fillna(0), contrib,
                            {"carry_%": (dif * 100).reindex(DIAS, method="ffill")}) if detalhe else None
    return saida(contrib, tr, detalhe)


# =============================================================== FUNDOS
from motor import Fundo, roda                                              # noqa: E402

MM = dict(adm=0.0, perf=0.0)
FUNDOS = [
    Fundo("JF1 Juro real de valor (NTN-B longa)", "Juros Brasil", "CDI",
          "IPCA+7% é prêmio demais: comprar NTN-B longa quando o juro real de 10 anos está em extremo histórico e zerar quando normaliza",
          "NTN-B (principal ou cupom) de ~10 ou ~15 anos, 5 anos de duration por PL, financiada no CDI (na prática DAP); custo 3 bps de taxa",
          juro_real, {"regra": ["p80", "p90", "a6.5", "a7"], "dur": [5.0]}, inicio="2010-01-01", corte="2021-01-01", **MM),
    Fundo("JF2 Inflação implícita x Focus", "Juros Brasil", "CDI",
          "Breakeven de 3 anos muito acima (abaixo) do IPCA esperado pelo Focus volta à média: vender (comprar) inflação",
          "LTN/NTN-F ~3a contra NTN-B ~3a (na prática DI1 x DAP), DV01 neutro, 5 anos de DV01 por perna", inflacao_implicita,
          {"z_in": [1.0, 1.5], "janela": [504, 756], "lado": ["ambos", "vende"]}, inicio="2010-01-01", corte="2021-01-01", **MM),
    Fundo("JF3 Prêmio do DI 1 ano x Selic esperada", "Juros Brasil", "CDI",
          "O DI de 1 ano paga mais que a Selic média que o Focus espera: o mercado paga demais por proteção -> receber; e o inverso",
          "LTN ~1 ano (na prática DI1), 2 anos de duration por PL; filtro de revisão do Focus (não receber com o Focus subindo a Selic)",
          premio_1a, {"thr": [.5, 1.0, 1.5], "filtro": [0, 1]}, inicio="2010-01-01", corte="2021-01-01", **MM),
    Fundo("JF4 Inclinação pelo ciclo do Copom", "Juros Brasil", "CDI",
          "Ciclo de cortes esperado -> steepener; ciclo de altas -> flattener, só quando a inclinação ainda não andou",
          "LTN 1-2a x LTN/NTN-F 5a, DV01 neutro (3 anos de DV01 por perna)", inclinacao,
          {"thr": [.5, 1.0], "cond": [0, 1], "curto": [1, 2]}, inicio="2010-01-01", corte="2021-01-01", **MM),
    Fundo("JF5 Cupom cambial curto x SOFR", "Arbitragem FX", "CDI",
          "Quando o cupom limpo de 1 mês paga muito mais que a SOFR + funding, emprestar dólar onshore (receber cupom)",
          "1º FRC (FRA de cupom), notional 5x PL; perna offshore paga SOFR + 0,5%; custo 3 bps + rolagem 1 bp/mês", cupom_curto,
          {"thr": [.5, 1.0, 1.5], "sair": [0.0, .25]}, inicio="2019-03-01", corte="2023-01-01", **MM),
    Fundo("JF6 Real tático (juro real, CFTC, fluxo)", "Macro FX", "CDI",
          "Diferencial de juro real Brasil-EUA alto atrai o real; especulador lotado é sinal contrário; fluxo cambial confirma",
          "DOL/WDO, semanal, vol-alvo 10% na convicção cheia (máx. 2x PL); carry = CDI - (T-bill + 1%)", real_tatico,
          {"sinais": ["juro", "juro+cot", "juro+fluxo", "juro+cot+fluxo"], "janela": [756, 1260]}, inicio="2011-01-01", corte="2021-01-01", **MM),
    Fundo("JF7 Carry de moedas realista (CME/B3)", "Macro FX", "CDI",
          "Carry só em moedas com futuro líquido, carry de EM com haircut de 50%, desligado em estresse (VIX)",
          "G10 + MXN/ZAR/PLN/HUF/CZK/ILS/TRY/CNH, top/bottom n, teto 20% por moeda, vol-alvo 8%, hedge para R$", carry_realista,
          {"n": [3, 4], "protecao": ["nenhuma", "vix"], "lado": ["ls", "long"]}, inicio="2010-01-01", corte="2021-01-01", **MM),
    Fundo("JF8 Carry de fronteira (o carry que ninguém arbitra)", "Macro FX", "CDI",
          "Moedas de fronteira pagam juro local muito acima da desvalorização média; custo alto e acesso difícil afastam a concorrência",
          "Comprado nas n moedas de maior juro (FMI) entre EGP, NGN, KZT, PKR, ARS, KES, UAH, GHS, UYU, DOP, UZS, RSD; 150 bps ida e volta",
          carry_fronteira, {"n": [3, 5], "filtro": [0, 1]}, inicio="2010-01-01", corte="2021-01-01", **MM),
]


if __name__ == "__main__":
    if sys.argv[1:2] == ["dados"]:
        baixa()
        sys.exit()
    from rodar import BENCH
    so = sys.argv[1:]
    res = []
    for f in FUNDOS:
        if so and f.nome.split()[0] not in so:
            continue
        t0 = time.time()
        r = roda(f, CDI, BENCH[f.benchmark], print)
        if r is None:
            print(f.nome, "sem resultado")
            continue
        ex, contrib, trades = f.func(**r["params"], detalhe=True)
        r["contrib"], r["trades"] = contrib, trades
        o, rb = r["oos"], r["rob"]
        print(f"{f.nome:55s} {str(r['params']):55s} IR IS {r['is_ir']:5.2f} | OOS {o['retorno a.a. %']:5.1f}% vs {o['benchmark a.a. %']:5.1f}% "
              f"IR {o['IR vs bench']:5.2f} | P(bater) {rb['P(bater bench OOS) %']:3.0f}% | PBO {rb['PBO %']:3.0f}% | "
              f"x2 custo {rb['OOS custo x2 (pp)']:5.2f} | +1d {rb['OOS execução +1 dia (pp)']:5.2f} | {time.time() - t0:.0f}s", flush=True)
        res.append(r)
    for r in res:
        r["fundo"].func = None
    if not so:
        pickle.dump(res, open(D.parent / "resultado" / "ideias_juros_fx.pkl", "wb"))
    print("pronto")
