"""
Frente EVENTOS BRASIL (event-driven com informação diária pública da CVM).
Dados: coleta_eventos_br.py (IPE, VLMO, ITR/DFP, FCA, cadastro CVM, proventos Yahoo) + b3_vista.parquet (COTAHIST 2014+).
Regra de ouro: a data do sinal é a DATA DE ENTREGA do documento na CVM; a decisão é no fechamento desse dia e a execução
no fechamento do pregão seguinte (carteira desloca 1+lag) -> se o fato saiu às 20h, ainda assim só operamos no fechamento seguinte.
Retornos: COTAHIST não ajustado -> corrigido por desdobramentos/grupamentos (Yahoo + marcação EB/EG do COTAHIST) e somado o
dividendo/JCP do Yahoo no dia ex (tickers deslistados ficam sem dividendo = conservador para comprado).
Uso: python ideias_eventos_br.py [números dos fundos]
"""
import pickle
import re
import sys
import time
import unicodedata
import warnings

import numpy as np
import pandas as pd

from base import CDI, D, DIAS, R_IBOV
from motor import Fundo, roda

warnings.filterwarnings("ignore")
OUT = D.parent / "resultado"
DATA_INI = pd.Timestamp("2014-01-02")
_C = {}                                    # cache em memória
ULT = {}                                   # detalhes (contrib, trades) da última chamada de cada estratégia


def _sem_acento(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _cnpj(s):
    return s.astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)


# ================================================================ painel de preços (ajustado)
def painel():
    """P (fech), R (retorno total ajustado), V (volume R$), ADV (média 60d com zeros), VWAP, O (abertura), NEG; só ações/units."""
    if "P" in _C:
        return _C
    f = D / "painel_eventos_br.pkl"
    if f.exists() and f.stat().st_mtime > (D / "b3_acoes_cotahist.parquet").stat().st_mtime:
        _C.update(pd.read_pickle(f))
        return _C
    v = pd.read_parquet(D / "b3_acoes_cotahist.parquet")                 # COTAHIST com CODBDI 05-09 (RJ etc.) e máx/mín
    v = v[v.ticker.str.match(r"^[A-Z]{4}(3|4|5|6|7|8|11)$") & v.especi.str[:3].str.strip().isin(["ON", "PN", "PNA", "PNB", "PNC", "UNT"])
          & ~v.especi.str.startswith("CI") & (v.fech > 0)]
    v["p"] = v.fech / v.fatcot
    v["o"] = v.abertura / v.fatcot
    v["vwap"] = (v.volume / v.quantidade.replace(0, np.nan))
    v["marca"] = v.especi.str[3:].str.strip().str.split().str[0].fillna("")
    v = v.sort_values(["ticker", "data"]).drop_duplicates(["ticker", "data"], keep="last")
    P = v.pivot(index="data", columns="ticker", values="p")
    P = P.reindex(DIAS[DIAS >= DATA_INI].union(P.index[P.index >= DATA_INI]))
    P = P[P.index.isin(DIAS)]
    O = v.pivot(index="data", columns="ticker", values="o").reindex(P.index)
    H = (v.pivot(index="data", columns="ticker", values="max") / v.pivot(index="data", columns="ticker", values="fatcot")).reindex(P.index)
    L = (v.pivot(index="data", columns="ticker", values="min") / v.pivot(index="data", columns="ticker", values="fatcot")).reindex(P.index)
    VW = v.pivot(index="data", columns="ticker", values="vwap").reindex(P.index)
    V = v.pivot(index="data", columns="ticker", values="volume").reindex(P.index)
    NEG = v.pivot(index="data", columns="ticker", values="negocios").reindex(P.index)
    MK = v.pivot(index="data", columns="ticker", values="marca").reindex(P.index)
    ult = P.ffill()
    q = P / ult.shift(1)                                                  # retorno desde o último negócio (gaps vão para o dia do negócio)
    lq = np.log(q)
    # --- desdobramentos/grupamentos: Yahoo (razão exata) ...
    pv = pd.read_parquet(D / "y_proventos.parquet").dropna(subset=["data"])
    pv = pv[pv.ticker.isin(P.columns)]
    fator = pd.DataFrame(1.0, index=P.index, columns=P.columns)
    feito = pd.DataFrame(False, index=P.index, columns=P.columns)
    for _, s in pv[pv.split > 0].iterrows():
        jan = lq.loc[s.data - pd.Timedelta(days=5): s.data + pd.Timedelta(days=5), s.ticker].dropna()
        if jan.empty:
            continue
        err = (jan + np.log(s.split)).abs()
        if err.min() < .2:
            dt = err.idxmin()
            fator.loc[dt, s.ticker] = s.split
            feito.loc[dt, s.ticker] = True
    # ... e marcação EB/EG do COTAHIST no primeiro dia (razão "redonda" mais próxima)
    mk = MK.fillna("")
    tem_bg = mk.apply(lambda c: c.str.startswith("E") & c.str.contains("B|G", regex=True))
    prim = tem_bg & ~tem_bg.shift(1, fill_value=False)
    cand = np.array(sorted({k for b in (2, 3, 4, 5, 8, 10, 20, 25, 50, 100, 1.1, 1.2, 1.25, 1.5) for k in (b, 1 / b)}))
    for dt, tk in zip(*np.where((prim & ~feito & (lq.abs() > .08)).values)):
        x = -lq.iat[dt, tk]
        k = cand[np.argmin(np.abs(np.log(cand) - x))]
        if abs(np.log(k) - x) < .06:
            fator.iat[dt, tk] = k
            feito.iat[dt, tk] = True
    r = q * fator - 1
    # --- saltos > 25% sem notícia na CVM (5 dias) e erros de cotação que se desfazem no dia seguinte
    noticia = _noticia_ticker(P)
    erro = (r.abs() > .4) & ((1 + r) * (1 + r.shift(-1)) - 1).abs().lt(.1)
    erro = erro | erro.shift(1, fill_value=False)
    r = r.where(~erro, 0.0)
    r = r.where((r.abs() < .25) | noticia | feito, 0.0)
    r = r.where(~((r > 3) & ~feito), 0.0)                                  # sobra de desdobramento não identificado
    # --- dividendos/JCP (Yahoo): rendimento no dia ex
    dv = pv[pv["div"] > 0][["data", "ticker", "div"]]
    yc = pv.pivot_table(index="data", columns="ticker", values="close").sort_index()
    dy = []
    for _, s in dv.iterrows():
        if s.ticker not in yc or s.data not in yc.index:
            continue
        c0 = yc[s.ticker].loc[:s.data].iloc[:-1].dropna()
        if len(c0) and c0.iloc[-1] > 0 and s["div"] / c0.iloc[-1] < .3:
            dy.append((s.data, s.ticker, s["div"] / c0.iloc[-1]))
    dy = pd.DataFrame(dy, columns=["data", "ticker", "y"]).groupby(["data", "ticker"]).y.sum().unstack()
    dy = dy.reindex(index=P.index, columns=P.columns).fillna(0)
    dy = dy.where(P.notna(), 0)                                           # só conta se houve negócio no dia ex
    R = (r.fillna(0) + dy).where(P.notna() | (r.notna()))
    R = R.where(ult.shift(1).notna())                                     # sem retorno antes do 1º negócio
    ADV = V.fillna(0).rolling(60, min_periods=20).mean()
    vivo = P.notna()[::-1].cummax()[::-1]                                 # ainda negocia em alguma data futura (fim = deslistagem)
    d = dict(P=P, R=R, V=V, ADV=ADV, VW=VW, O=O, H=H, L=L, NEG=NEG, vivo=vivo, inicio=P.notna().idxmax(), fim=P.notna()[::-1].idxmax(), dy=dy)
    pd.to_pickle(d, f)
    _C.update(d)
    return _C


def mapa():
    """CNPJ (14 dígitos) -> raízes de ticker (4 letras), pelo FCA (códigos de negociação) + mapas antigos do projeto."""
    if "mapa" in _C:
        return _C["mapa"]
    f = pd.read_parquet(D / "cvm_fca_vm.parquet")
    f = f[f.Codigo_Negociacao.notna()]
    m = pd.DataFrame({"cnpj": _cnpj(f.CNPJ_Companhia), "raiz": f.Codigo_Negociacao.str.strip().str[:4].str.upper()})
    try:
        a = pd.read_csv(D.parent.parent / "dados" / "acoes_mapa.csv", dtype=str)
        m = pd.concat([m, pd.DataFrame({"cnpj": a.cnpj.str.zfill(14), "raiz": a.ticker.str[:4]})])
    except FileNotFoundError:
        pass
    m = m[m.raiz.str.match(r"^[A-Z]{4}$")].drop_duplicates()
    # uma raiz pertence a um CNPJ só (o que mais aparece)
    m = m.groupby("raiz").cnpj.agg(lambda s: s.value_counts().index[0]).reset_index()
    _C["mapa"] = m
    return m


def _noticia_ticker(P):
    """True se a companhia do ticker entregou qualquer documento eventual (FR, comunicado, aviso) na CVM nos últimos 5 dias."""
    ipe = pd.read_parquet(D / "cvm_ipe.parquet", columns=["CNPJ_Companhia", "Categoria", "Data_Entrega"])
    ipe = ipe[ipe.Categoria.isin(["Fato Relevante", "Comunicado ao Mercado", "Aviso aos Acionistas"])]
    ipe["cnpj"] = _cnpj(ipe.CNPJ_Companhia)
    ipe["data"] = pd.to_datetime(ipe.Data_Entrega, errors="coerce")
    m = mapa()
    tk = pd.DataFrame({"ticker": P.columns, "raiz": P.columns.str[:4]}).merge(m, on="raiz")
    ev = ipe.merge(tk, on="cnpj")[["data", "ticker"]].dropna().drop_duplicates()
    N = pd.DataFrame(0, index=P.index, columns=P.columns)
    idx = P.index.searchsorted(ev.data)
    ok = idx < len(P.index)
    for i, t in zip(idx[ok], ev.ticker[ok]):
        N.iat[i, N.columns.get_loc(t)] = 1
    return N.rolling(6, min_periods=1).max().astype(bool)


if __name__ == "__main__" and sys.argv[1:2] == ["painel"]:
    t = time.time()
    p = painel()
    print(p["R"].shape, time.time() - t)


# ================================================================ eventos (IPE)
CLASSES = {
    "opa": r"\bopa\b|oferta publica (voluntaria |unificada |concorrente )?(de |para )?(aquisicao|permuta)|cancelamento de registro"
           r"|fechamento de capital|saida do (novo mercado|nivel)|deslistagem|conversao de registro|tag along|retirada de circulacao",
    "controle": r"mudanca (de|do) controle|alienacao (de|do) controle|transferencia do controle|aquisicao (de|do) controle|venda do controle"
                r"|alienacao da participacao (do|dos) controlador",
    "incorporacao": r"incorporacao de acoes|incorporacao da companhia|fusao|combinacao de negocios|reorganizacao societaria",
    "recompra": r"recompra|aquisicao de acoes de (sua )?(propria )?emissao|acoes de (sua )?propria emissao|aquisicao de acoes de emissao da propria",
    "oferta": r"oferta (publica )?(primaria|secundaria|subsequente|restrita|de distribuicao|de acoes|publica de acoes|publica de distribuicao)"
              r"|follow.on|esforcos restritos|distribuicao (publica )?(primaria|secundaria)|potencial oferta|eventual oferta|oferta global",
    "preco_oferta": r"precificacao|fixacao do preco|definicao do preco|preco por acao|aprovacao do preco|resultado do procedimento de alocacao",
    "rj": r"recuperacao judicial|recuperacao extrajudicial|falencia",
    "rj_pedido": r"(pedido|ajuizamento|requerimento|protocolo|ingresso|apresentacao) (de |do |da )?(pedido de )?recuperacao (judicial|extrajudicial)"
                 r"|deferimento do processamento|recuperacao judicial - pedido",
    "fraude": r"inconsistencia|fraude|irregularidade|investigacao|operacao (policial|lava)|busca e apreensao|reapresentacao das demonstracoes",
}
NAO_ACAO = r"debentur|notas? (comerciais|promissoria)|\bnotes\b|\bcri\b|\bcra\b|cpr|bonds?\b|senior|fii|cotas|\bfidc\b|recebiveis"


def eventos():
    """Fatos relevantes classificados por expressão regular no Assunto + ticker mais líquido da companhia na data."""
    if "ev" in _C:
        return _C["ev"]
    d = pd.read_parquet(D / "cvm_ipe.parquet", columns=["CNPJ_Companhia", "Nome_Companhia", "Categoria", "Tipo", "Assunto", "Data_Entrega", "Protocolo_Entrega", "Link_Download"])
    d = d[d.Categoria.isin(["Fato Relevante", "Comunicado ao Mercado", "Reunião da Administração", "Aviso aos Acionistas"])]
    d["a"] = d.Assunto.fillna("").map(_sem_acento)
    d["data"] = pd.to_datetime(d.Data_Entrega, errors="coerce")
    d["cnpj"] = _cnpj(d.CNPJ_Companhia)
    d = d[d.data >= DATA_INI].dropna(subset=["data"])
    for k, rx in CLASSES.items():
        d[k] = d.a.str.contains(rx, regex=True)
    d["nao_acao"] = d.a.str.contains(NAO_ACAO, regex=True)
    d = d[d[list(CLASSES)].any(axis=1)]
    # ticker: o mais líquido entre as raízes da companhia (ADV de 60d na data)
    p = painel()
    m = mapa()
    raizes = m.groupby("cnpj").raiz.apply(list)
    d = d[d.cnpj.isin(raizes.index)]
    adv = p["ADV"]
    col_por_raiz = pd.Series(adv.columns, index=adv.columns.str[:4]).groupby(level=0).apply(list)
    i = np.clip(adv.index.searchsorted(d.data), 0, len(adv) - 1)
    tk = []
    for ii, c in zip(i, d.cnpj):
        cols = [t for r in raizes[c] for t in col_por_raiz.get(r, [])]
        if not cols:
            tk.append(None)
            continue
        a = adv.iloc[max(ii - 1, 0)][cols]
        tk.append(a.idxmax() if a.notna().any() and a.max() > 0 else None)
    d["ticker"] = tk
    d["adv"] = [adv.iat[max(ii - 1, 0), adv.columns.get_loc(t)] if t else np.nan for ii, t in zip(i, tk)]
    d = d.dropna(subset=["ticker"]).sort_values("data")
    _C["ev"] = d
    return d


def estudo(ev, dias=(-5, 0, 1, 2, 5, 10, 20, 40, 60, 120), col="ticker"):
    """Retorno anormal médio (vs Ibovespa) acumulado de t0 = data de entrega; também a partir da execução (t+1)."""
    p = painel()
    R = p["R"]
    A = R.sub(R_IBOV.reindex(R.index), axis=0)
    la = np.log1p(A.fillna(0)).cumsum()
    i0 = R.index.searchsorted(ev.data)
    out = []
    for ii, t in zip(i0, ev[col]):
        if ii >= len(R) or t not in la:
            continue
        base = la.iat[max(ii - 1, 0), la.columns.get_loc(t)]
        out.append([la.iat[min(max(ii + k, 0), len(R) - 1), la.columns.get_loc(t)] - base for k in dias])
    x = np.expm1(pd.DataFrame(out, columns=dias)) * 100
    return x


# ================================================================ motor de livros de eventos
def custo_acao(adv):
    """Custo por perna (corretagem+emolumentos+meio spread+impacto) pela liquidez (ADV 60d em R$)."""
    return pd.DataFrame(np.select([adv >= 50e6, adv >= 10e6, adv >= 2e6], [.0010, .0020, .0040], .0080), index=adv.index, columns=adv.columns)


def aluguel_acao(adv):
    """Aluguel a.a. na ponta vendida: blue chips 1%, médias 3%, small caps 8%."""
    return pd.DataFrame(np.select([adv >= 50e6, adv >= 10e6], [.01, .03], .08), index=adv.index, columns=adv.columns)


def posicoes(ev, hold, n_max=10, sinal="s", data="data"):
    """Eventos -> pesos-alvo decididos no fechamento da data do evento. Cada posição vale 1/n_max do PL por `hold` pregões
    (novo evento no mesmo ticker renova o prazo); se houver mais de n_max posições, todas são reduzidas (bruto máx. 100%)."""
    idx = DIAS[DIAS >= DATA_INI]
    tks = sorted(ev.ticker.unique())
    A = np.zeros((len(idx), len(tks)))
    col = {t: j for j, t in enumerate(tks)}
    i0 = idx.searchsorted(ev[data].values)
    hs = ev["hold"].values if "hold" in ev else np.full(len(ev), hold)
    for i, t, s, h in zip(i0, ev.ticker, ev[sinal] if sinal in ev else np.ones(len(ev)), hs):
        if i < len(idx):
            A[i:i + int(h), col[t]] = s
    W = pd.DataFrame(A, index=idx, columns=tks) / n_max
    g = W.abs().sum(axis=1)
    return W.div(np.maximum(g, 1), axis=0)


def livro(W, hedge=1.0, custo_mult=1, lag=0, alug=None, nome=None, rotulos=None, r_ajuste=None):
    """Simula o livro: W (pesos decididos em t) executado no fechamento de t+1+lag; ações em excesso sobre o CDI;
    hedge: vende h x exposição líquida em Ibovespa (futuro/BOVA11, 3 bps). Posição em ação deslistada é encerrada no
    último negócio (OPA/incorporação liquidam a esse preço) sem custo. Guarda contribuição diária e negócios em ULT[nome]."""
    p = painel()
    W = W.reindex(DIAS).fillna(0)
    W = W.loc[:, (W != 0).any()]
    tk = list(W.columns)
    R = p["R"].reindex(index=DIAS, columns=tk)
    for (d, t), v in (r_ajuste or {}).items():
        if t in R:
            R.at[d, t] = v
    vivo = p["vivo"].reindex(index=DIAS, columns=tk).fillna(False).astype(bool)
    adv = p["ADV"].reindex(index=DIAS, columns=tk).ffill()
    c = custo_acao(adv) * custo_mult
    al = aluguel_acao(adv) if alug is None else pd.DataFrame(alug, index=DIAS, columns=tk)
    Wx = W.shift(1 + lag).fillna(0).where(vivo, 0.0)
    Rx = R.fillna(0).sub(CDI.reindex(DIAS), axis=0)
    con = Wx.shift(1).fillna(0) * Rx - Wx.diff().abs().fillna(Wx.abs()) * c.where(vivo, 0.0) \
        - Wx.clip(upper=0).abs() * al / 252
    if hedge:
        h = -hedge * Wx.sum(axis=1)
        con["IBOV (hedge)"] = h.shift(1).fillna(0) * (R_IBOV.reindex(DIAS).fillna(0) - CDI.reindex(DIAS)) - h.diff().abs().fillna(0) * .0003 * custo_mult
    ex = con.sum(axis=1)
    if nome:
        ULT[nome] = {"contrib": con.loc[:, con.abs().sum() > 0].astype("float32"), "trades": negocios(Wx, R, con, rotulos)}
    return ex


def negocios(Wx, R, con, rotulos=None):
    """Lista de negócios: cada sequência contínua de posição num ticker (entrada/saída = 1º/último dia carregado)."""
    out = []
    rib = R_IBOV.reindex(DIAS).fillna(0)
    for t in Wx.columns:
        w = Wx[t].values
        on = w != 0
        if not on.any():
            continue
        mud = np.flatnonzero(np.diff(np.r_[0, np.sign(w), 0]) != 0)
        for a, b in zip(mud[:-1], mud[1:]):
            if w[a] == 0:
                continue
            ent, sai = Wx.index[a], Wx.index[min(b, len(w) - 1)]
            seg = slice(a + 1, min(b + 1, len(w)))
            r = R[t].iloc[seg].fillna(0)
            out.append({"ativo": t, "entrada": ent, "saida": sai, "dias": b - a, "lado": "C" if w[a] > 0 else "V",
                        "peso_medio": float(np.abs(w[a:b]).mean()), "retorno": float((1 + r).prod() - 1),
                        "ret_vs_ibov": float((1 + r).prod() / (1 + rib.iloc[seg]).prod() - 1),
                        "contrib": float(con[t].iloc[a:min(b + 1, len(w))].sum())})
    tr = pd.DataFrame(out)
    if len(tr) and rotulos is not None:
        rot = rotulos.sort_values("data")[["data", "ticker", "rotulo"]].rename(columns={"ticker": "ativo"})
        tr = pd.merge_asof(tr.sort_values("entrada"), rot, left_on="entrada", right_on="data", by="ativo", direction="backward",
                           tolerance=pd.Timedelta(days=30)).drop(columns="data")
    return tr.sort_values("contrib") if len(tr) else tr


# ================================================================ conjuntos de eventos por tese
def _primeiro(x, dias=90, por="ticker"):
    """Mantém só o primeiro evento de cada ticker numa janela (evita contar o mesmo negócio várias vezes)."""
    x = x.sort_values("data")
    ult, keep = {}, []
    for d, t in zip(x.data, x[por]):
        keep.append(t not in ult or (d - ult[t]).days > dias)
        if keep[-1]:
            ult[t] = d
    return x[np.array(keep)]


def ev_recompra(adv_min=2e6):
    ev = eventos()
    x = ev[ev.recompra & ~ev.a.str.contains("encerramento|cancelamento|termino|conclusao|alteracao", regex=True) & (ev.adv >= adv_min)
           & ev.Categoria.isin(["Fato Relevante", "Reunião da Administração", "Comunicado ao Mercado"])]
    x = _primeiro(x, 120)
    return x.assign(rotulo="recompra: " + x.a.str[:80], s=1.0)


def ev_oferta(adv_min=2e6):
    """Follow-on: 1º fato relevante de oferta de ações (lançamento/pedido/potencial) ou de precificação, por empresa em 90 dias."""
    ev = eventos()
    x = ev[(ev.oferta | ev.preco_oferta) & ~ev.nao_acao & ~ev.opa & ~ev.a.str.contains("desistencia|cancelamento|suspensao|adss?\b|permuta|aquisicao", regex=True)
           & (ev.Categoria == "Fato Relevante") & (ev.adv >= adv_min)]
    x = _primeiro(x, 90)
    return x.assign(rotulo="oferta: " + x.a.str[:80], s=-1.0)


def ev_rj(adv_min=5e5):
    ev = eventos()
    x = ev[(ev.rj_pedido | ev.fraude) & (ev.Categoria == "Fato Relevante") & (ev.adv >= adv_min)]
    x = _primeiro(x, 250)
    return x.assign(rotulo=np.where(x.rj_pedido, "RJ: ", "fraude: ") + x.a.str[:80], s=-1.0)


def ev_ipo():
    """IPOs: primeiro pregão de uma raiz nova cuja companhia obteve registro na CVM há menos de 2 anos (exclui trocas de ticker)."""
    p = painel()
    ini = p["inicio"]
    raiz_ini = ini.groupby(ini.index.str[:4]).min()
    cad = pd.read_parquet(D / "cvm_cad.parquet", columns=["CNPJ_CIA", "DT_REG", "DENOM_SOCIAL"])
    cad["cnpj"] = _cnpj(cad.CNPJ_CIA)
    cad["dt_reg"] = pd.to_datetime(cad.DT_REG, errors="coerce")
    m = mapa().merge(cad[["cnpj", "dt_reg", "DENOM_SOCIAL"]].drop_duplicates("cnpj"), on="cnpj")
    x = pd.DataFrame({"raiz": raiz_ini.index, "ipo": raiz_ini.values}).merge(m, on="raiz")
    x = x[(x.ipo > DATA_INI + pd.Timedelta(days=60)) & ((x.ipo - x.dt_reg).dt.days.between(-30, 730))]
    adv = p["ADV"]
    tk = []
    for r, d in zip(x.raiz, x.ipo):
        cols = [c for c in adv.columns if c[:4] == r]
        a = adv.loc[d:].iloc[20:21][cols] if len(adv.loc[d:]) > 20 else None
        tk.append(a.iloc[0].idxmax() if a is not None and a.notna().any(axis=None) else None)
    x["ticker"] = tk
    return x.dropna(subset=["ticker"])


def ev_lockup(antes=10, adv_min=5e6):
    """Fim do lock-up de 180 dias corridos: decisão `antes` pregões antes da data (venda a descoberto)."""
    x = ev_ipo()
    x["lock"] = x.ipo - pd.Timedelta(days=1) + pd.Timedelta(days=180)
    i = DIAS.searchsorted(x.lock) - antes
    x["data"] = DIAS[np.clip(i, 0, len(DIAS) - 1)]
    adv = painel()["ADV"]
    x["adv"] = [adv.loc[:d, t].iloc[-1] if t in adv else np.nan for d, t in zip(x.data, x.ticker)]
    x = x[x.adv >= adv_min]
    return x.assign(rotulo="lock-up IPO " + x.ipo.dt.strftime("%Y-%m-%d"), s=-1.0)


def ev_insider(limiar=.02, adv_min=2e6):
    """Compras líquidas de controladores/conselho/diretoria no mês (VLMO) acima de `limiar` do giro mensal; data = entrega do formulário."""
    v = pd.read_parquet(D / "cvm_vlmo.parquet", columns=["CNPJ_Companhia", "Data_Referencia", "Versao", "Data_Entrega", "Tipo_Empresa", "Tipo_Cargo",
                                                         "Tipo_Movimentacao", "Tipo_Ativo", "Volume", "Quantidade", "Preco_Unitario"])
    v["Versao"] = pd.to_numeric(v.Versao, errors="coerce")
    v = v[v.Versao == v.groupby(["CNPJ_Companhia", "Data_Referencia"]).Versao.transform("max")]
    v = v[(v.Tipo_Empresa == "Companhia") & v.Tipo_Ativo.isin(["Ações", "Units"])
          & v.Tipo_Movimentacao.isin(["Compra à vista", "Venda à vista", "Compra", "Venda"])]
    vol = pd.to_numeric(v.Volume, errors="coerce")
    vol = vol.fillna(pd.to_numeric(v.Quantidade, errors="coerce") * pd.to_numeric(v.Preco_Unitario, errors="coerce"))
    v["liq"] = np.where(v.Tipo_Movimentacao.str.startswith("Compra"), 1, -1) * vol
    v["liq_ctrl"] = v.liq * v.Tipo_Cargo.fillna("").str.startswith("Controlador")
    g = v.groupby(["CNPJ_Companhia", "Data_Referencia"]).agg(liq=("liq", "sum"), data=("Data_Entrega", "max"), liq_ctrl=("liq_ctrl", "sum")).reset_index()
    g["data"] = pd.to_datetime(g.data)
    g["ref"] = pd.to_datetime(g.Data_Referencia)
    g = g[(g.data - g.ref).dt.days.between(0, 75)]                       # descarta reapresentações muito tardias (dado velho)
    g["cnpj"] = _cnpj(g.CNPJ_Companhia)
    p = painel()
    m = mapa()
    raizes = m.groupby("cnpj").raiz.apply(list)
    adv = p["ADV"]
    col_por_raiz = pd.Series(adv.columns, index=adv.columns.str[:4]).groupby(level=0).apply(list)
    g = g[g.cnpj.isin(raizes.index)]
    tk, a_ = [], []
    for d, c in zip(g.data, g.cnpj):
        cols = [t for r in raizes[c] for t in col_por_raiz.get(r, [])]
        a = adv.loc[:d, cols].iloc[-1] if cols and len(adv.loc[:d]) else None
        ok = a is not None and a.notna().any() and a.max() > 0
        tk.append(a.idxmax() if ok else None)
        a_.append(a.max() if ok else np.nan)
    g["ticker"], g["adv"] = tk, a_
    g = g.dropna(subset=["ticker"])
    g["intens"] = g.liq / (g.adv * 21)
    g = g[(g.adv >= adv_min) & (g.intens.abs() >= limiar)]
    g["s"] = np.sign(g.intens)
    return g.assign(rotulo="insider " + np.where(g.s > 0, "compra ", "venda ") + (g.intens * 100).round(1).astype(str) + "% do giro mensal")


def ev_resultado(adv_min=5e6):
    """Divulgação de ITR/DFP (1ª entrega) e reação anormal de 2 dias (fech t-1 -> fech t+1) vs Ibovespa. Data de decisão = t+1."""
    x = pd.read_parquet(D / "cvm_itr_dfp.parquet", columns=["CNPJ_CIA", "DT_REFER", "DT_RECEB", "VERSAO"])
    x["data0"] = pd.to_datetime(x.DT_RECEB)
    x = x.sort_values("data0").drop_duplicates(["CNPJ_CIA", "DT_REFER"])
    x["cnpj"] = _cnpj(x.CNPJ_CIA)
    p = painel()
    m = mapa()
    raizes = m.groupby("cnpj").raiz.apply(list)
    adv = p["ADV"]
    col_por_raiz = pd.Series(adv.columns, index=adv.columns.str[:4]).groupby(level=0).apply(list)
    x = x[x.cnpj.isin(raizes.index) & (x.data0 >= DATA_INI)]
    A = np.log1p(p["R"].fillna(0).sub(R_IBOV.reindex(p["R"].index).fillna(0), axis=0)).cumsum()
    idx = A.index
    out = []
    for d, c in zip(x.data0, x.cnpj):
        i = idx.searchsorted(d)
        if i + 1 >= len(idx) or i < 2:
            continue
        cols = [t for r in raizes[c] for t in col_por_raiz.get(r, [])]
        if not cols:
            continue
        a = adv.iloc[i - 1][cols]
        if not (a.max() >= adv_min):
            continue
        t = a.idxmax()
        j = A.columns.get_loc(t)
        out.append((idx[i + 1], t, np.expm1(A.iat[i + 1, j] - A.iat[i - 1, j]), a.max(), d))
    r = pd.DataFrame(out, columns=["data", "ticker", "reacao", "adv", "entrega"])
    return r.assign(rotulo="resultado " + r.entrega.dt.strftime("%Y-%m-%d") + " reação " + (r.reacao * 100).round(1).astype(str) + "%")


def ev_bloco(mult=4, pos=.8, adv_min=5e6, noticia=False):
    """Volume anormal (>= mult x média 60d) com fechamento perto da máxima (comprador agressivo) ou da mínima (vendedor).
    s=+1 fechou no topo do intervalo do dia e subiu; s=-1 fechou no fundo e caiu. noticia=False: só dias SEM documento na CVM."""
    p = painel()
    V, ADV, H, L, P, R = p["V"], p["ADV"], p["H"], p["L"], p["P"], p["R"]
    k = V / ADV.shift(1)
    lo = (P - L) / (H - L).replace(0, np.nan)
    sem = ~_noticia_ticker(P) if not noticia else pd.DataFrame(True, index=P.index, columns=P.columns)
    base = (k >= mult) & (ADV.shift(1) >= adv_min) & sem
    cima = base & (lo >= pos) & (R > .01)
    baixo = base & (lo <= 1 - pos) & (R < -.01)
    out = []
    for m, s in ((cima, 1.0), (baixo, -1.0)):
        st = m.stack()
        st = st[st]
        out.append(pd.DataFrame({"data": st.index.get_level_values(0), "ticker": st.index.get_level_values(1), "s": s}))
    x = pd.concat(out)
    x["adv"] = [ADV.at[d, t] for d, t in zip(x.data, x.ticker)]
    return x.assign(rotulo=np.where(x.s > 0, "bloco comprador", "bloco vendedor"))


def ev_queda(queda=-.20, adv_min=5e6, com_fato=True):
    """Queda anormal (vs Ibov) <= `queda` em 3 pregões; com_fato: houve documento na CVM na janela. Exclui RJ/fraude (vão para o livro vendido)."""
    p = painel()
    R = p["R"]
    A = np.log1p(R.fillna(0).sub(R_IBOV.reindex(R.index).fillna(0), axis=0))
    c3 = np.expm1(A.rolling(3).sum())
    noti = _noticia_ticker(p["P"])
    m = (c3 <= queda) & (p["ADV"].shift(3) >= adv_min) & p["P"].notna()
    m = m & (noti if com_fato else ~noti)
    st = m.stack()
    st = st[st]
    x = pd.DataFrame({"data": st.index.get_level_values(0), "ticker": st.index.get_level_values(1)})
    x["queda"] = [c3.at[d, t] for d, t in zip(x.data, x.ticker)]
    x = _primeiro(x, 30)
    ruim = ev_rj(0)
    ruim = ruim[["data", "ticker"]].rename(columns={"data": "d_rj"})
    x = x.merge(ruim, on="ticker", how="left")
    x = x[~((x.d_rj <= x.data + pd.Timedelta(days=5)) & (x.d_rj >= x.data - pd.Timedelta(days=365)))].drop(columns="d_rj").drop_duplicates(["data", "ticker"])
    return x.assign(s=1.0, rotulo="queda " + (x.queda * 100).round(0).astype(str) + "% em 3 dias")


def ibov_proxy(data, janela=252):
    """Proxy da carteira teórica do Ibovespa na data: índice de negociabilidade IN = (n/N)^(1/3) (v/V)^(2/3) em 12 meses,
    presença >= 95% dos pregões, preço >= R$1, acumulado de IN até 85%."""
    p = painel()
    NEG, V, P = p["NEG"], p["V"], p["P"]
    sl = slice(NEG.index[max(NEG.index.searchsorted(data) - janela, 0)], data)
    n, v = NEG.loc[sl].fillna(0).sum(), V.loc[sl].fillna(0).sum()
    pres = P.loc[sl].notna().mean()
    IN = (n / n.sum()) ** (1 / 3) * (v / v.sum()) ** (2 / 3)
    ult = P.loc[sl].ffill().iloc[-1]
    IN = IN[(pres >= .95) & (ult >= 1)].sort_values(ascending=False)
    acum = IN.cumsum() / IN.sum()
    return set(acum[acum.shift(1, fill_value=0) < .85].index)


def ev_ibov(antes=21):
    """Rebalanceamento quadrimestral (carteiras de jan/mai/set): entrantes prováveis (s=+1) e saintes (s=-1) pelo proxy;
    decisão `antes` pregões antes do último pregão da carteira velha; saída no último pregão antes da vigência."""
    out = []
    for ano in range(2015, DIAS[-1].year + 1):
        for mes in (1, 5, 9):
            vig = pd.Timestamp(ano, mes, 1)
            i_fim = DIAS.searchsorted(vig) - 1                              # último pregão da carteira velha
            if i_fim + 1 >= len(DIAS) or i_fim - antes < 300:
                continue
            d = DIAS[i_fim - antes]
            ant_ref = DIAS[DIAS.searchsorted(vig - pd.DateOffset(months=4)) - 1 - antes]
            novo, velho = ibov_proxy(d), ibov_proxy(ant_ref)
            for t in novo - velho:
                out.append((d, t, 1.0, DIAS[i_fim], antes))
            for t in velho - novo:
                out.append((d, t, -1.0, DIAS[i_fim], antes))
    x = pd.DataFrame(out, columns=["data", "ticker", "s", "fim", "hold"])
    return x.assign(rotulo=np.where(x.s > 0, "entra Ibov (proxy) ", "sai Ibov (proxy) ") + x.fim.dt.strftime("%Y-%m"))


# ================================================================ estratégias (excesso diário sobre o CDI, líquido de custos)
def _ev(chave, fn, *a, **k):
    """Cache de conjuntos de eventos (a grade chama a mesma função muitas vezes)."""
    ch = (chave, a, tuple(sorted(k.items())))
    if ch not in _C:
        _C[ch] = fn(*a, **k)
    return _C[ch]


def recompra(hold=126, n_max=15, custo_mult=1, lag=0):
    """Comprado nas ações que anunciam programa de recompra, vendido Ibovespa (beta 1)."""
    ev = _ev("recompra", ev_recompra)
    return livro(posicoes(ev, hold, n_max), 1.0, custo_mult, lag, nome="recompra", rotulos=ev)


def follow_on(hold=40, n_max=10, custo_mult=1, lag=0):
    """Vendido a descoberto na ação que anuncia (ou precifica) oferta subsequente; comprado Ibovespa contra (neutro)."""
    ev = _ev("oferta", ev_oferta)
    return livro(posicoes(ev, hold, n_max), 1.0, custo_mult, lag, nome="follow_on", rotulos=ev)


def lockup(antes=10, depois=10, custo_mult=1, lag=0):
    """Vendido `antes` pregões antes do fim do lock-up de 180 dias até `depois` pregões depois; aluguel caro (mín. 6% a.a.)."""
    ev = _ev("lockup", ev_lockup, antes)
    W = posicoes(ev, antes + depois, 8)
    adv = painel()["ADV"].reindex(index=DIAS, columns=W.columns).ffill()
    al = np.maximum(aluguel_acao(adv), .06)
    return livro(W, 1.0, custo_mult, lag, alug=al, nome="lockup", rotulos=ev)


def insiders(lado="ambos", limiar=.02, hold=63, custo_mult=1, lag=0):
    """Segue a negociação líquida de controladores/administradores (VLMO), a partir da DATA DE ENTREGA do formulário."""
    ev = _ev("insider", ev_insider, limiar)
    ev = ev[ev.s > 0] if lado == "compra" else ev[ev.s < 0] if lado == "venda" else ev
    return livro(posicoes(ev, hold, 15), 1.0, custo_mult, lag, nome="insiders", rotulos=ev)


def pead(limiar=.05, hold=60, custo_mult=1, lag=0):
    """Deriva pós-resultado: reação anormal de 2 dias ao ITR/DFP > limiar -> comprado; < -limiar -> vendido; hedge do líquido em Ibov."""
    r = _ev("resultado", ev_resultado)
    ev = r[r.reacao.abs() >= limiar].assign(s=lambda x: np.sign(x.reacao))
    return livro(posicoes(ev, hold, 20), 1.0, custo_mult, lag, nome="pead", rotulos=ev)


def ibov_rebal(antes=21, lado="ambos", custo_mult=1, lag=0):
    """Compra os prováveis entrantes e vende os prováveis saintes do Ibovespa (proxy da regra) e entrega aos fundos de índice
    no último pregão antes da vigência da carteira nova."""
    ev = _ev("ibov", ev_ibov, antes)
    ev = ev[ev.s > 0] if lado == "compra" else ev
    ev = ev.assign(hold=antes - 1)
    return livro(posicoes(ev, antes, 15), 1.0, custo_mult, lag, nome="ibov_rebal", rotulos=ev)


def blocos(mult=4, hold=20, lado="ambos", custo_mult=1, lag=0):
    """Negócio de bloco: volume >= mult x média com fechamento na ponta do dia -> segue a direção do 'informado'."""
    ev = _ev("bloco", ev_bloco, mult)
    ev = ev[ev.s < 0] if lado == "venda" else ev
    return livro(posicoes(ev, hold, 15), 1.0, custo_mult, lag, nome="blocos", rotulos=ev)


def crise(modo="contrarian", hold=40, rj=True, custo_mult=1, lag=0):
    """Queda > 20% em 3 dias com fato relevante: 'contrarian' compra o exagero, 'continuacao' vende; RJ/fraude sempre vendido."""
    q = _ev("queda", ev_queda).copy()
    q["s"] = 1.0 if modo == "contrarian" else -1.0
    ev = pd.concat([q, _ev("rj", ev_rj)]) if rj else q
    W = posicoes(ev, hold, 10)
    adv = painel()["ADV"].reindex(index=DIAS, columns=W.columns).ffill()
    al = np.maximum(aluguel_acao(adv), .10)                               # papel em crise: aluguel caríssimo
    return livro(W, 1.0, custo_mult, lag, alug=al, nome="crise", rotulos=ev)


# ================================================================ arbitragem de OPA / controle (preço da oferta lido do PDF do fato relevante)
_RX_RS = re.compile(r"r\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{1,4})?)")
_RX_CTX = re.compile(r"por (cada )?(acao|unit|certificado)|preco (por|unitario|de aquisicao|da oferta|da opa|ofertado|base|maximo)|/acao")


def precos_no_texto(s):
    """Valores 'R$ x' no texto que aparecem perto de 'por ação' / 'preço por' (candidatos a preço da oferta por ação)."""
    s = re.sub(r"\s+", " ", _sem_acento(s or ""))
    out = []
    for m in _RX_RS.finditer(s):
        if _RX_CTX.search(s[max(m.start() - 120, 0):m.end() + 120]):
            v = float(m.group(1).replace(".", "").replace(",", "."))
            if 0 < v < 5000:
                out.append(v)
    return out


def ev_opa(faixa=(.9, 1.5)):
    """Eventos de OPA/controle/incorporação com preço por ação no texto compatível com o preço da ação da própria companhia
    (o que garante que a companhia é o ALVO). spread = preço da oferta / fechamento do dia da entrega - 1."""
    tx = pd.read_parquet(D / "cvm_ipe_textos.parquet")
    ev = eventos()
    x = ev[(ev.opa | ev.controle | ev.incorporacao) & ev.Categoria.isin(["Fato Relevante", "Comunicado ao Mercado"])]
    x = x.merge(tx, on="Protocolo_Entrega")
    x = x[~x.a.str.contains("latibex|\badrs?\b|\bads\b|nyse|subsidiaria|controlada|debentur|resultado do leilao|resultado da opa|"
                            "conclusao|consumacao|encerramento|desistencia|cancelamento da oferta", regex=True) & ~x.nao_acao]
    P = painel()["P"].ffill(limit=5)
    out = []
    for _, r in x.iterrows():
        i = P.index.searchsorted(r.data)
        if i >= len(P) or r.ticker not in P:
            continue
        p0 = P[r.ticker].iloc[i]
        if not p0 > 0:
            continue
        c = [v for v in precos_no_texto(r.texto) if faixa[0] * p0 <= v <= faixa[1] * p0]
        if not c:
            continue
        o = min(c, key=lambda v: abs(v - p0))
        out.append({"data": P.index[i], "ticker": r.ticker, "oferta": o, "p0": p0, "spread": o / p0 - 1, "adv": r.adv,
                    "dinheiro": bool((r.opa or r.controle) and not re.search("incorporacao|combinacao|reorganizacao|fusao|permuta", r.a)),
                    "rotulo": f"{r.Nome_Companhia[:30]} | {r.a[:70]} | oferta R$ {o:.2f}"})
    return pd.DataFrame(out)


def opa_arb(smin=.03, hold=250, hedge=0.0, tipo="opa", custo_mult=1, lag=0):
    """Merger arb: compra o alvo quando o preço está pelo menos `smin` abaixo do preço da oferta (e no máx. 30%);
    sai quando o spread fecha (preço >= oferta), no LEILÃO da OPA (fato 'resultado do leilão': o arbitrador entrega as ações
    ao preço da oferta), na deslistagem (incorporação liquida ao último preço) ou após `hold` pregões.
    tipo='opa': só ofertas em dinheiro (OPA/alienação de controle); 'todos': inclui incorporações/combinações (troca de ações)."""
    ev = _ev("opa", ev_opa)
    ev = ev[(ev.spread >= smin) & (ev.spread <= .30) & (ev.adv >= 5e5)]
    if tipo == "opa":
        ev = ev[ev.dinheiro]
    e_all = eventos()
    leilao = e_all[e_all.a.str.contains("leilao", regex=False) & e_all.Categoria.isin(["Fato Relevante", "Comunicado ao Mercado"])]
    p = painel()
    P = p["P"].reindex(DIAS).ffill(limit=5)
    idx = DIAS[DIAS >= DATA_INI]
    tks = sorted(ev.ticker.unique())
    A = pd.DataFrame(0.0, index=idx, columns=tks)
    aj = {}                                                               # retorno do dia do leilão = oferta / fechamento anterior
    for _, r in ev.iterrows():
        i = idx.searchsorted(r.data)
        fim = min(i + hold, len(idx))
        pp = P[r.ticker].reindex(idx).values
        fecha = np.flatnonzero(pp[i + 1:fim] >= r.oferta * .995)
        if len(fecha):
            fim = i + 1 + fecha[0]
        lz = leilao[(leilao.ticker == r.ticker) & (leilao.data > r.data)].data
        if len(lz):
            j = idx.searchsorted(lz.iloc[0])                              # dia do leilão (data marcada no edital, conhecida antes)
            if i < j <= fim and pp[j - 1] > 0:
                fim = j - 1
                aj[(idx[j], r.ticker)] = max(r.oferta / pp[j - 1] - 1, -.5)
        A.iloc[i:fim, A.columns.get_loc(r.ticker)] = 1.0
    W = A / 8
    W = W.div(np.maximum(W.sum(axis=1), 1), axis=0)
    return livro(W, hedge, custo_mult, lag, nome="opa_arb", rotulos=ev, r_ajuste=aj)


# ================================================================ fundos
EV = "Eventos BR"
FUNDOS = [
    Fundo("E1 Arbitragem de OPA e troca de controle", EV, "CDI",
          "Compro o alvo de OPA/venda de controle quando ainda negocia abaixo do preço da oferta: o mercado cobra um prêmio de "
          "prazo/risco de a operação não sair que, no Brasil (OPA obrigatória, tag along, laudo), costuma ser maior que o risco real",
          "Preço da oferta lido do PDF do fato relevante (R$ por ação perto de 'por ação'/'preço da oferta', entre 0,9x e 1,5x o "
          "preço da ação — garante que a filer é o alvo); até 8 negócios de 12,5% do PL; sai no fechamento do spread, na "
          "deslistagem ou no prazo; hedge parcial opcional em Ibovespa", opa_arb,
          {"smin": [.02, .05], "hedge": [0.0, .5], "tipo": ["opa", "todos"]}, inicio="2014-06-01"),
    Fundo("E2 Recompra anunciada", EV, "CDI",
          "Compro quem anuncia recompra: a administração sinaliza que a ação está barata e vira compradora marginal",
          "Fato relevante/ata de RCA com 'recompra'/'aquisição de ações de própria emissão', ADV >= R$2 mi; posições de 1/n_max do PL, "
          "hedge beta 1 em Ibovespa", recompra, {"hold": [63, 126], "n_max": [10, 20]}, inicio="2014-06-01"),
    Fundo("E3 Follow-on vendido", EV, "CDI",
          "Vendo a ação que anuncia/precifica oferta subsequente: emissor e vendedor (controlador, PE) sabem mais que o mercado e "
          "vendem caro; o desconto da oferta e a oferta adicional de papel pressionam por semanas",
          "1º fato relevante de oferta de ações (lançamento, pedido de registro, potencial oferta, precificação) por empresa em 90 dias; "
          "vendido a descoberto 1/n_max do PL, aluguel por liquidez (1-8% a.a.), comprado Ibovespa contra", follow_on,
          {"hold": [20, 40, 60], "n_max": [5, 10]}, inicio="2014-06-01"),
    Fundo("E4 Fim de lock-up de IPO", EV, "CDI",
          "Vendo antes do fim do lock-up de 180 dias: fundos de PE e sócios pré-IPO vendem assim que podem",
          "IPO = 1º pregão de raiz nova com registro CVM < 2 anos; vendido `antes` pregões antes de 180 dias corridos, zera `depois`; "
          "aluguel mínimo 6% a.a.", lockup, {"antes": [5, 10, 20], "depois": [5, 15]}, inicio="2014-06-01"),
    Fundo("E5 Insiders (VLMO)", EV, "CDI",
          "Sigo controlador/conselho/diretoria: quem compra (ou vende) muito da própria empresa sabe algo; o formulário é público "
          "só ~40 dias depois e quase ninguém lê",
          "Compra/venda à vista líquida do mês >= limiar x giro mensal; entrada no pregão após a ENTREGA do formulário VLMO; "
          "63 pregões, 1/15 do PL por papel, hedge Ibov", insiders,
          {"lado": ["compra", "venda", "ambos"], "limiar": [.02, .05]}, inicio="2019-03-01", corte="2023-01-01"),
    Fundo("E6 Deriva pós-resultado (PEAD)", EV, "CDI",
          "O mercado brasileiro reage pouco a resultados fora do consenso: a reação dos 2 primeiros dias continua por 2-3 meses",
          "Reação anormal (vs Ibov) do fech. t-1 ao t+1 da 1ª entrega do ITR/DFP; |reação| >= limiar -> comprado/vendido no sinal, "
          "1/20 do PL por papel, hedge do líquido em Ibov", pead, {"limiar": [.03, .05, .08], "hold": [40, 60]}, inicio="2014-06-01"),
    Fundo("E7 Rebalanceamento do Ibovespa", EV, "CDI",
          "Antecipo a carteira teórica: fundos de índice e ETFs compram os entrantes no último pregão antes da vigência",
          "Proxy da regra B3 (índice de negociabilidade 12m, presença >= 95%, 85% acumulado); comprado entrantes / vendido saintes "
          "`antes` pregões antes da vigência (jan/mai/set), zera no último pregão da carteira velha; hedge Ibov", ibov_rebal,
          {"antes": [10, 21, 42], "lado": ["ambos", "compra"]}, inicio="2014-06-01"),
    Fundo("E8 Blocos informados", EV, "CDI",
          "Volume de 4-6x a média com o preço fechando na ponta do dia, sem fato público, é gestora grande se posicionando: o fluxo continua",
          "Volume >= mult x ADV60 e fechamento no 20% superior (subiu > 1%) -> comprado, no 20% inferior (caiu > 1%) -> vendido; "
          "só dias sem documento na CVM; 1/15 do PL por papel; hedge Ibov", blocos,
          {"mult": [3, 5], "hold": [10, 20, 40], "lado": ["ambos", "venda"]}, inicio="2014-06-01"),
    Fundo("E9 Crise corporativa (queda >20% / RJ)", EV, "CDI",
          "Contrarian: queda > 20% em 3 dias com fato relevante é exagero -> compro; RJ/fraude em fato relevante -> vendo",
          "Queda anormal <= -20% em 3 pregões com documento na CVM (excluídas empresas com RJ/fraude no último ano), ADV >= R$5 mi; "
          "modo contrarian (compra) ou continuação (venda); RJ/fraude sempre vendidos; aluguel mínimo 10% a.a.", crise,
          {"modo": ["contrarian", "continuacao"], "hold": [20, 60], "rj": [True, False]}, inicio="2014-06-01"),
]
FUNC_NOME = {opa_arb: "opa_arb", recompra: "recompra", follow_on: "follow_on", lockup: "lockup", insiders: "insiders", pead: "pead",
             ibov_rebal: "ibov_rebal", blocos: "blocos", crise: "crise"}


if __name__ == "__main__" and sys.argv[1:2] != ["painel"]:
    from rodar import BENCH
    so = sys.argv[1:]
    LOG = open(OUT / "log_eventos_br.txt", "a", encoding="utf-8")

    def log(*a):
        s = " ".join(str(x) for x in a)
        print(s, flush=True)
        LOG.write(s + "\n")
        LOG.flush()

    res = []
    for f in FUNDOS:
        if so and f.nome[1] not in so:
            continue
        t = time.time()
        log(f"\n== {f.nome}")
        r = roda(f, CDI, BENCH[f.benchmark], log)
        if r is None:
            log("   sem resultado")
            continue
        f.func(**r["params"])                                              # re-roda a escolhida para guardar contribuições e negócios
        det = ULT[FUNC_NOME[f.func]]
        r["contrib"], r["trades"] = det["contrib"], det["trades"]
        o, rb = r["oos"], r["rob"]
        log(f"   escolhido {r['params']} | IR IS {r['is_ir']:.2f} | OOS: {o['retorno a.a. %']:.1f}% vs bench {o['benchmark a.a. %']:.1f}% "
            f"(IR {o['IR vs bench']:.2f}) | P(bater) {rb['P(bater bench OOS) %']:.0f}% | PBO {rb['PBO %']:.0f}% | "
            f"custo x2 {rb['OOS custo x2 (pp)']:.1f}pp | +1 dia {rb['OOS execução +1 dia (pp)']:.1f}pp | negócios {len(r['trades'])} | {time.time() - t:.0f}s")
        res.append(r)
    for r in res:
        r["fundo"].func = None
    nome = OUT / ("ideias_eventos_br.pkl" if not so else f"ideias_eventos_br_{''.join(so)}.pkl")
    pickle.dump(res, open(nome, "wb"))
    log("pronto", nome)
