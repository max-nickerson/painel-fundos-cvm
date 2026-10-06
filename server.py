"""
Painel de fundos (CVM + ANBIMA + Tesouro Direto + Banco Central + IBGE) - backend FastAPI.
Rodar local:  uvicorn server:app --port 7860      (abre http://localhost:7860)
Na partida baixa/processa TODOS os fundos (NOSSOS_FUNDOS + PEERS em lookthrough_cvm.py) e salva o resultado do dia
em dados_painel/painel/<data>/. O navegador mostra o progresso e abre quando termina.
"""
import json
import math
import os
import re
import threading
from datetime import date

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import lookthrough_cvm as lt

AQUI = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="Painel de fundos")
app.mount("/static", StaticFiles(directory=os.path.join(AQUI, "static")), name="static")

CAT_CORES = ["#2a78d6", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7", "#008300", "#e34948", "#7ba7d9"]
NOSSAS_CORES = ["#eb6834", "#c24f1d", "#f29a6b", "#a8401a", "#f5b38d"]
GENERICO = (r"(?i)\b(FUNDO DE INVESTIMENTO|FUNDO|EM DIREITOS CREDIT[OÓ]RIOS|DE INVESTIMENTO|FIDC|FIC|FI|COTAS|MULTIMERCADO|"
            r"RENDA FIXA|CR[EÉ]DITO PRIVADO|RESPONSABILIDADE LIMITADA|RESP LTDA|N[AÃ]O PADRONIZADO|NP|LONGO PRAZO|LP)\b")
METODO = 13                                     # suba quando mudar o calculo -> refaz o cache do dia
CAIXA = ("Caixa",)
CAIXA_CVM = ("Disponibilidades", "Operações Compromissadas", "Valores a receber", "Valores a pagar", lt.AJUSTE)
TIPO_CASA = {"CDB/ RDB": "CDB", "CDB Vinculado": "CDB", "DPGE": "DPGE", "FI Imobiliário": "FII", "FI Participações": "FIP",
             "Fundos de Índice": "ETF", "Fundos Offshore": "Fundos offshore", "CCB": "CCB", "CCCB": "CCB", "LCA": "LCA", "CPR": "CPR",
             "CDCA": "CDCA", "CCI": "CCI", "NCA": "NCA", "Letra de Câmbio/ Letra Hipotecária/ Letra Imobiliária": "LCI/LH"}
CURTO_CVM = {"Depósitos a prazo e outros títulos de IF": "Outros títulos de IF", "Títulos ligados ao agronegócio": "Agro (outros)",
             "Outros valores mobiliários registrados na CVM objeto de oferta pública": "Outros valores mobiliários",
             "Investimento no Exterior": "Exterior (outros)", "Títulos de Crédito Privado": "Crédito privado (outros)",
             "Cotas de Fundos": "Cotas de fundos"}
SEM_SPREAD = ("Ações", "FII", "FIP", "ETF", "FIAGRO", "Confidencial")
MERCADO = ("ANBIMA", "SND + preço do fundo")            # renda variavel: spread e duration nao se aplicam
FUNDOS = ("FIDC", "FII", "FIP", "ETF", "FIAGRO", "Cotas de fundos", "Fundos offshore")
USD = ("Bonds", "Fundos offshore", "Exterior (outros)")
TP = [("LFT", r"BRSTNCLF|FINANCEIRAS DO TESOURO|LFT"), ("NTN-B", r"BRSTNCNTB|SERIE B|NTN-B"),
      ("NTN-F", r"BRSTNCNTF|SERIE F|NTN-F"), ("LTN", r"BRSTNCLTN|LETRAS DO TESOURO NACIONAL|LTN")]
MESES_COD = "FGHJKMNQUVXZ"
PRE = {"status": "parado", "log": [], "erro": None, "pasta": None}


# ------------------------------------------------------------------ utilidades
def limpo(o):
    if isinstance(o, dict):
        return {str(k): limpo(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [limpo(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(o) or math.isinf(o)) else round(float(o), 6)
    if isinstance(o, pd.Timestamp):
        return None if pd.isna(o) else o.strftime("%Y-%m-%d")
    if o is None or isinstance(o, (str, bool)):
        return o
    try:
        return None if pd.isna(o) else o
    except (TypeError, ValueError):
        return o


def wavg(v, w):
    v, w = np.asarray(v, float), np.asarray(w, float)
    ok = ~np.isnan(v) & (w > 0)
    return float(np.average(v[ok], weights=w[ok])) if ok.any() else None


def fim_mes(m):
    return pd.Timestamp(m) + pd.offsets.MonthEnd(0)


def contrato(texto):
    """Tipo, vencimento (ano, mes) de um futuro a partir do codigo/descricao da CDA (ex.: DI1FUTF29, FUT DAP/Q30)."""
    t = lt._sem_acento(texto)
    tipo = ("DAP" if re.search(r"DAP|CUPOM DE IPCA|DI X IPCA", t) else "DI1" if re.search(r"DI1|DI DE 1 DIA", t)
            else "WDO" if "WDO" in t else "DOL" if re.search(r"DOL|DOLAR", t) else "DDI" if re.search(r"DDI|FRC|CUPOM CAMBIAL", t)
            else "IND" if re.search(r"\bIND|WIN|IBOV", t) else "OUTRO")
    m = re.search(r"(?:DI1|DAP|DOL|WDO|DDI|FRC|IND|WIN)\s*(?:FUT)?\s*/?\s*([FGHJKMNQUVXZ])(\d{2})\b", t)
    return tipo, ((2000 + int(m.group(2)), MESES_COD.index(m.group(1)) + 1) if m else None)


# ------------------------------------------------------------------ fluxo de caixa: duration e taxa implicita pelo preco
def _grade(T, p_jur, p_amo, t_car):
    """Fluxos por unidade de principal numa grade mensal contada a partir do vencimento (vetorizado).
    T: anos ate o vencimento; juros a cada p_jur anos; amortizacao constante a cada p_amo anos (0 = no vencimento)
    a partir de t_car anos. Devolve (prazos, peso_juros, principal, periodo_juros)."""
    T = np.clip(np.nan_to_num(np.atleast_1d(np.asarray(T, float)), nan=1.0), 1 / 12, 40)
    col = lambda v, pad: np.broadcast_to(np.nan_to_num(np.asarray(v, float), nan=pad), T.shape)[:, None]
    j = np.arange(int(np.ceil(T.max() * 12)) + 1)[None, :]
    tau = T[:, None] - j / 12
    ok = tau > 1e-6
    kj = np.clip(np.round(col(p_jur, 0.5) * 12), 1, 600)
    ka = np.round(col(p_amo, 0) * 12)
    am = np.where(ka > 0, (j % np.maximum(ka, 1) == 0) & (tau >= col(t_car, 0) - 1e-6), j == 0) & ok
    am |= (j == 0) & ~am.any(1, keepdims=True)
    princ = am / am.sum(1, keepdims=True)
    saldo = np.cumsum(princ, 1)                       # saldo devedor antes do pagamento em tau
    return np.where(ok, tau, 1.0), ((j % kj == 0) & ok) * saldo, princ, kj / 12


def pv(tau, wj, princ, per, y_cup, y):
    """Valor presente por unidade de principal (e soma de prazo x VP): juros a taxa do titulo y_cup, desconto a y (% a.a.)."""
    fl = wj * ((1 + np.asarray(y_cup, float)[:, None] / 100) ** per - 1) + princ
    df = (1 + np.asarray(y, float)[:, None] / 100) ** -tau
    return (fl * df).sum(1), (fl * df * tau).sum(1)


def taxa_e_duration(T, p_jur, p_amo, t_car, base, s0, pct_par):
    """Taxa de mercado s (mesma unidade de s0) que leva o preco a pct_par do PU par, e a duration (anos) nessa taxa.
    y = (1+base)(1+s)-1: base = CDI para DI+, 0 para IPCA+/pre (s ja e a taxa). pct_par NaN -> fica s0."""
    tau, wj, princ, per = _grade(T, p_jur, p_amo, t_car)
    n = len(tau)
    base, s0 = np.broadcast_to(np.asarray(base, float), (n,)), np.broadcast_to(np.asarray(s0, float), (n,)).copy()
    alvo = np.broadcast_to(np.asarray(pct_par, float), (n,))
    y = lambda s, b: ((1 + b / 100) * (1 + s / 100) - 1) * 100
    s = s0.copy()
    r = np.where(np.isfinite(alvo) & np.isfinite(s0))[0]
    if len(r):                                       # bissecao: o preco cai quando a taxa sobe
        a = (tau[r], wj[r], princ[r], per[r])
        v0, _ = pv(*a, y(s0[r], base[r]), y(s0[r], base[r]))
        lo, hi = np.full(len(r), -10.0), np.full(len(r), 80.0)
        for _ in range(30):
            mid = (lo + hi) / 2
            v, _ = pv(*a, y(s0[r], base[r]), y(mid, base[r]))
            caro = v / v0 > alvo[r]
            lo, hi = np.where(caro, mid, lo), np.where(caro, hi, mid)
        s[r] = (lo + hi) / 2
    v, vt = pv(tau, wj, princ, per, y(np.nan_to_num(s0), base), y(np.nan_to_num(s), base))
    return s, vt / v


# ------------------------------------------------------------------ calculo por fundo
class Contexto:
    """Dados de mercado compartilhados por todos os fundos."""

    def __init__(self, log, meses):
        log("Baixando curvas (Tesouro Direto), IPCA (IBGE), PTAX e CDI (Banco Central) e marcação ANBIMA...")
        self.curvas = lt.tesouro()
        self.ipca = lt.ipca_indice()
        self.ptax = lt.sgs(1, lt.DESDE)
        self.cdi_d = lt.cdi_mensal(lt.DESDE, diario=True)
        self.cdi_m = (1 + self.cdi_d).groupby(self.cdi_d.index.strftime("%Y-%m")).prod() - 1
        self.an_u, self.an_h = lt.anbima_debentures()
        self.an_dias = sorted(self.an_h.data.unique()) if len(self.an_h) else []
        log("Cadastro e PU par das debêntures (SND), prazo dos FIDCs (CVM) e Treasury (EUA)...")
        self.snd = lt.snd_caracteristicas()
        hoje = pd.Timestamp.today().normalize() - pd.offsets.BDay(1)
        alvo = {m: min(pd.Timestamp(m) + pd.offsets.BMonthEnd(0), hoje) for m in meses}
        pu = lt.snd_pu(sorted(set(alvo.values())), log=log)
        falta = {m: d - pd.offsets.BDay(1) for m, d in alvo.items() if d not in set(pu.data)}      # feriado no fim do mes
        if falta:
            pu = pd.concat([pu, lt.snd_pu(sorted(set(falta.values())), log=log)], ignore_index=True)
            alvo.update(falta)
        self.pu_dia = alvo
        self.pu = {d: x.drop_duplicates("codigo").set_index("codigo").pu_par for d, x in pu.groupby("data")}
        f, ser = lt.fidc_mensal(lt.DESDE, log)
        self.fidc = {c: (x.mes.values, x.anos.values) for c, x in f.sort_values("mes").groupby("cnpj")}
        ser = ser[(ser.cota > 0) & ser.rent.notna()].sort_values(["cnpj", "serie", "mes"])
        e = (1 + ser.rent / 100) / (1 + ser.mes.map(self.cdi_m)) - 1
        primeiro = ser.groupby(["cnpj", "serie"]).cumcount() == 0             # 1o mes da serie e parcial
        ser = ser.assign(e=e.where(~primeiro & (e > -0.03) & (e < 0.2)))       # < -3% no mes: amortizacao/evento pontual
        ser["spread"] = ((1 + ser.groupby(["cnpj", "serie"]).e.transform(lambda x: x.rolling(6, min_periods=2).median())) ** 12 - 1) * 100
        esp = ((1 + ser.esperado / 100) / (1 + ser.mes.map(self.cdi_m))) ** 12 * 100 - 100        # benchmark da serie (X_6)
        ruim = ~((ser.spread > -30) & (ser.spread < 40))                 # perda recorrente aparece; absurdo vira benchmark
        ser["spread"] = ser.spread.mask(ruim, esp.where((ser.esperado > 0) & (esp > -5) & (esp < 30)))
        ser = ser.dropna(subset=["spread"])
        sr = ser.serie.str.contains("Senior|Sênior", case=False, na=False)
        self.fidc_ser = {k: (x.cota.values, x.spread.values, float(x.spread[sr[x.index]].median()) if sr[x.index].any() else float(x.spread.median()))
                         for k, x in ser.groupby(["cnpj", "mes"])}
        self.ust = lt.treasury()
        px = self.ptax.groupby(self.ptax.index.strftime("%Y-%m")).last()
        self.fx_m = px / px.shift() - 1
        u = pd.Series({m: float(lt.curva(self.ust, "UST", fim_mes(m), np.array([1.0]))[0]) / 1200 for m in px.index}) if self.ust else pd.Series(dtype=float)
        self.ust_m = u.shift()
        self._taxas = {}
        self.emissores = {}                       # (mes, grupo) -> soma spread*peso, duration*peso, peso

    def pu_par(self, m):
        return self.pu.get(self.pu_dia.get(m), pd.Series(dtype=float))

    def proj_ipca(self, m):
        """IPCA mensal projetado (media dos 12 meses anteriores): o PU par do SND so usa o indice ja divulgado."""
        x = self.ipca[self.ipca.index < m]
        return float((x.iloc[-1] / x.iloc[-13]) ** (1 / 12) - 1) if len(x) > 13 else 0.004

    def fidc_anos(self, cnpj, m):
        x = self.fidc.get(cnpj)
        if x is None:
            return np.nan
        i = np.searchsorted(x[0], m, side="right") - 1
        return float(x[1][max(i, 0)])

    def fidc_spread(self, cnpj, m, pu):
        """Spread da serie do FIDC que o fundo tem: acha a serie pelo valor da cota (tab X_2) e usa a mediana de 6 meses
        da rentabilidade acima do CDI (tab X_3; benchmark X_6 se ela for anomala). Sem serie com a mesma cota: seniores."""
        for k in range(4):                                  # informe do mes ou de ate 3 meses antes
            x = self.fidc_ser.get((cnpj, (pd.Timestamp(m) - pd.DateOffset(months=k)).strftime("%Y-%m")))
            if x is not None:
                cota, spr, senior = x
                if np.isfinite(pu) and pu > 0:
                    dif = np.abs(cota / pu - 1)
                    if dif.min() < 0.02:
                        return float(spr[dif.argmin()])
                return senior
        return np.nan

    def taxa(self, m, cods, T, pj, pa, car, base, s0, pp_):
        """taxa_e_duration com memoria: o mesmo ativo no mesmo mes e preco aparece em varios fundos."""
        ch = [(m, c, round(float(p), 5) if np.isfinite(p) else None, round(float(b), 4)) for c, p, b in zip(cods, pp_, s0)]
        novos = {k: i for i, k in enumerate(ch) if k not in self._taxas}
        if novos:
            i = np.array(list(novos.values()))
            s, d = taxa_e_duration(T[i], pj[i], pa[i], car[i], base[i], s0[i], pp_[i])
            self._taxas.update(zip(novos, zip(s, d)))
        r = np.array([self._taxas[k] for k in ch], dtype=float).reshape(-1, 2)
        return r[:, 0], r[:, 1]

    def cdi_aa(self, m):
        x = self.cdi_d[self.cdi_d.index <= fim_mes(m)]
        return float(((1 + x.iloc[-1]) ** 252 - 1) * 100) if len(x) else np.nan

    def ptax_em(self, m):
        x = self.ptax[self.ptax.index <= fim_mes(m)]
        return float(x.iloc[-1]) if len(x) else np.nan

    def anbima_mes(self, m, recentes):
        """Marcacao ANBIMA para a carteira do mes: o dia guardado mais proximo do fim do mes (ate 10 dias);
        nos meses mais recentes, o ultimo dia disponivel."""
        if not self.an_dias:
            return None, None
        alvo = fim_mes(m)
        perto = [d for d in self.an_dias if abs((pd.Timestamp(d) - alvo).days) <= 10]
        d = min(perto, key=lambda d: abs((pd.Timestamp(d) - alvo).days)) if perto else (self.an_dias[-1] if m in recentes else None)
        return (d, self.an_h[self.an_h.data == d].drop_duplicates("codigo").set_index("codigo")) if d is not None else (None, None)


def tipo_tp(g):
    s = (g.codigo.fillna("") + " " + g.ativo.fillna("")).map(lt._sem_acento)
    out = pd.Series(None, index=g.index, dtype=object)
    for nome, rx in TP:
        out = out.mask(out.isna() & s.str.contains(rx), nome)
    return out


def vencimento(g):
    """Vencimento informado ou lido do nome do ativo (CRI: 'CRI:APCS:150629', '... / 25/09/2029 / ...', '... 2029-05')."""
    a = g.ativo.fillna("")
    v = pd.to_datetime(g.vencimento, errors="coerce")
    for rx, fmt in [(r"(\d{2}/\d{2}/\d{4})", "%d/%m/%Y"), (r"CR[AI]:[A-Z0-9]+:(\d{6})\b", "%d%m%y"), (r"\b((?:19|20)\d{2}-\d{2})$", "%Y-%m")]:
        v = v.fillna(pd.to_datetime(a.str.extract(rx)[0], format=fmt, errors="coerce"))
    return v


def casa(df, ctx):
    """Categorias da casa: Caixa, LF, LFSN, LFSC, DEB, DEBIN, Bonds, CRA, CRI, NC, FIDC. O que nao se encaixa fica com o
    nome do tipo/categoria da CVM (CDB, Títulos Públicos, FII, ...)."""
    t, c = df.tipo_ativo.fillna(""), df.categoria
    a = df.ativo.fillna("").map(lt._sem_acento)
    inc = df.codigo.map(ctx.snd.incentivada) if len(ctx.snd) else pd.Series(np.nan, index=df.index)
    out = t.map(TIPO_CASA).fillna(c.map(CURTO_CVM)).fillna(c)
    fundo = t.isin(["FIDC", "FI Imobiliário", "Fundos de Índice", "FI Participações", "Fundos Offshore"]) | c.isin(["FIDC", "Cotas de Fundos", "FIAGRO"])
    out = out.mask(c.eq("FIAGRO"), "FIAGRO").mask(t.str.startswith("Aç") | t.str.contains("subscri"), "Ações")
    out = out.mask(t.isin(["Bonds e Treasury", "Título da Dívida Externa"]), "Bonds")
    out = out.mask(t.eq("FIDC") | c.eq("FIDC"), "FIDC")
    out = out.mask(~fundo & (t.str.contains("Nota Promiss|Nota Comercial") | a.str.match(r"NOTA COMERCIAL")), "NC")
    out = out.mask(~fundo & (t.str.contains("imobili.rios") | a.str.contains(r"\bCRI\b")), "CRI")
    out = out.mask(~fundo & (t.eq("CRA") | a.str.match(r"CRA\b")), "CRA")
    deb = ~fundo & (t.str.startswith("Debênture") | a.str.match(r"DEBENTURE") | inc.notna())
    out = out.mask(deb, np.where(inc.eq(True), "DEBIN", "DEB"))
    lf = t.eq("Letra Financeira")
    venc = pd.to_datetime(df.vencimento, errors="coerce")
    chave = df.emissor.fillna("") + "|" + df.vencimento.astype(str)
    primeiro = pd.to_datetime(df.mes.where(lf)).groupby(chave).transform("min")
    longo = (venc - primeiro).dt.days / 365.25 > 6          # LF subordinada nivel II: prazo longo (> 6 anos), nao perpetua
    out = out.mask(lf, np.where(venc.dt.year >= 2049, "LFSC", np.where(longo, "LFSN", "LF")))
    out = out.mask(c.eq("Debêntures") & ~out.isin(["DEB", "DEBIN"]), "DEB")
    contabil = c.isin(CAIXA_CVM) | (c.str.contains(lt.PASSIVO, na=False) & ~df.derivativo)
    out = out.mask(contabil, "Caixa").mask(c.eq("Títulos Públicos"), "Títulos Públicos")
    return out.mask(df.confidencial & ~df.derivativo, "Confidencial")       # CVM so informa o tipo, sem o ativo


def rotulo(g, venc, tp):
    """Nome curto 'codigo - mm/aaaa': debenture/acao pelo ticker, CRI/CRA pelo codigo, titulo publico pelo tipo,
    LF/CDB pelo tipo + grupo, fundos pelo nome sem palavras genericas."""
    a = g.ativo.fillna("")
    cod = g.codigo.fillna("").str.strip()
    fundo = g.casa.isin(FUNDOS)
    ticker = cod.str.fullmatch(r"[A-Z]{4}[A-Z0-9]{1,4}") & ~fundo
    cri = a.str.extract(r"\b(CR[AI]):([A-Z0-9]+)")
    isin = a.str.extract(r"\b(BR[A-Z0-9]{10})\b")[0]
    curto = a.str.replace(GENERICO, " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip(" -").str.slice(0, 38)
    base = np.select([ticker, tp.notna(), cri[0].notna(), isin.notna(), fundo],
                     [cod, tp.fillna(""), cri[0].fillna("") + " " + cri[1].fillna(""), isin.fillna(""), curto],
                     g.casa + " " + g.grupo.fillna("").str.slice(0, 26))
    cx = g.casa.eq("Caixa")
    base = np.where(cx, np.where(g.categoria.eq("Operações Compromissadas"), "Compromissada " + tp.fillna(""), g.categoria), base)
    v = venc.dt.strftime("%m/%Y")
    return pd.Series(base, index=g.index).str.strip() + np.where(v.notna() & ~fundo & ~cx, " - " + v.fillna(""), "")


def implicito(df, ctx):
    """Spread implicito pelo preco (ativos sem taxa publica: cotas de FIDC, CRI sem taxa, bonds...): mediana dos ultimos
    6 retornos mensais do preco unitario acima do CDI, anualizada. Em dolar: tira o cambio e compara com o Treasury 1 ano."""
    k = lt.contribuicao(df)
    if not len(k):
        return pd.Series(dtype=float)
    k = k[(k.qt > 0) & (k.qt_ant > 0) & (k.v_ant > 0)].copy()
    rp = (k.v / k.qt) / (k.v_ant / k.qt_ant) - 1
    usd = k.chave.map(df.drop_duplicates("chave").set_index("chave").casa).isin(USD)
    e = (1 + rp) / (1 + k.mes.map(ctx.cdi_m)) - 1
    e = e.where(~usd, (1 + rp) / ((1 + k.mes.map(ctx.fx_m).fillna(0)) * (1 + k.mes.map(ctx.ust_m).fillna(0))) - 1)
    k["e"] = e.where(e.abs() < 0.2)
    k = k.sort_values(["chave", "mes"])
    k["med"] = k.groupby("chave").e.transform(lambda s: s.rolling(6, min_periods=1).median())
    return ((1 + k.set_index(["mes", "chave"]).med) ** 12 - 1) * 100


def mede(g, m, ctx, recentes, impl, ant=None):
    """Spread CDI (% a.a., equivalente), duration (anos), PU, indexador e fonte de TODAS as linhas da carteira do mes.
    Preferencia: ANBIMA (mercado) > SND + preco do fundo (mercado) > taxa contratada (CVM) > implicito pelo preco >
    media da categoria. Renda variavel (acoes, FII, FIP, ETF, FIAGRO): nao se aplica."""
    g = g.copy()
    fm, cdi, n = fim_mes(m), ctx.cdi_aa(m), len(g)
    sp, du = np.full(n, np.nan), np.full(n, np.nan)
    fonte, ind = np.full(n, "", dtype=object), np.full(n, "", dtype=object)
    cod = g.codigo.fillna("").values
    snd = ctx.snd.reindex(cod)
    venc = g.venc.fillna(pd.Series(snd.venc.values, index=g.index))
    anos = ((venc - fm).dt.days / 365.25).clip(lower=1 / 365).values
    tem_venc = venc.notna().values
    pu_f = (g.valor_veiculo / g.quantidade).where(g.quantidade > 0).values
    ca = g.casa.values.astype(str)
    nome = g.ativo.fillna("").map(lt._sem_acento).values.astype(str)
    curva = lambda t, a: lt.curva(ctx.curvas, t, fm, np.nan_to_num(a, nan=3))
    valido = lambda v: np.isfinite(v) & (v > -5) & (v < 30)          # spread fora disso = dado ruim: tenta a proxima fonte

    def poe(msk, s, d, f, i):                    # preenche so onde ainda nao ha spread
        msk = msk & np.isnan(sp)
        b = lambda v: np.broadcast_to(np.asarray(v, dtype=object if isinstance(v, str) or (np.ndim(v) and np.asarray(v).dtype == object) else float), (n,))
        sp[msk], du[msk], fonte[msk], ind[msk] = b(s)[msk], b(d)[msk], b(f)[msk], b(i)[msk]

    # 1) caixa e titulos publicos
    poe((ca == "Caixa") | ((ca == "ETF") & (np.char.find(nome, "SELIC") >= 0)), 0.0, 0.0, "caixa", "DI")
    tp = g.tp.values.astype(str)
    m_tp = ca == "Títulos Públicos"
    if m_tp.any():
        y = np.where(tp == "NTN-B", curva("IPCA", anos), curva("PRE", anos))
        _, d_cup = taxa_e_duration(anos, 0.5, 0, 0, 0, y, np.nan)
        poe(m_tp, 0.0, np.where(np.isin(tp, ["NTN-B", "NTN-F"]), d_cup, anos), "Tesouro (curva)",
            np.where(tp == "NTN-B", "IPCA", np.where(np.isin(tp, ["LTN", "NTN-F"]), "PRE", "DI")).astype(object))
    # 2) debentures: ANBIMA do dia mais proximo do fim do mes
    dia, an = ctx.anbima_mes(m, recentes)
    deb = np.isin(ca, ["DEB", "DEBIN"])
    if an is not None and deb.any():
        a = an.reindex(cod)
        tx, tipo, dur = a.taxa_ind.values.astype(float), a.tipo.values.astype(str), a.duration_anos.values.astype(float)
        real = np.isin(tipo, ["IPCA +", "IGP-M +"])
        s = np.where(tipo == "DI +", tx, np.where(tipo == "% do DI", (tx - 100) / 100 * cdi, np.nan))
        s = np.where(real, tx - lt.curva(ctx.curvas, "IPCA", pd.Timestamp(dia), np.nan_to_num(dur, nan=3)), s)
        s = np.where(tipo == "Outros", tx - lt.curva(ctx.curvas, "PRE", pd.Timestamp(dia), np.nan_to_num(dur, nan=2)), s)
        poe(deb & np.isfinite(s), s, dur, "ANBIMA", np.where(real, "IPCA", np.where(tipo == "Outros", "PRE", "DI")).astype(object))
    # 3) debentures fora da ANBIMA: taxa de emissao (SND) ajustada pelo preco do fundo / PU par do SND
    idx = snd.indice.fillna("").values.astype(str)
    di, real, pre = idx == "DI", np.isin(idx, ["IPCA", "IGP-M", "INPC"]), idx == "PRE"
    m3 = deb & np.isnan(sp) & (di | real | pre) & tem_venc
    if m3.any():
        pct, jur = snd.pct.values.astype(float), snd.juros.values.astype(float)
        s0 = np.where(di & (pct > 100) & (np.nan_to_num(jur) == 0), (pct - 100) / 100 * cdi, jur)
        s0 = np.where((np.nan_to_num(jur) == 0) & ~(di & (pct > 100)), np.nan, s0)     # "nao padrao" no SND: sem taxa util
        par = ctx.pu_par(m).reindex(cod).values.astype(float) * np.where(real, 1 + ctx.proj_ipca(m), 1)
        pp_ = pu_f / par
        pp_ = np.where((pp_ > 0.7) & (pp_ < 1.15), pp_, np.nan)
        car = ((snd.carencia - fm).dt.days / 365.25).values.astype(float)
        r = np.where(m3 & np.isfinite(s0))[0]
        s, d = np.full(n, np.nan), np.full(n, np.nan)
        s[r], d[r] = ctx.taxa(m, cod[r], anos[r], snd.cada_juros.values.astype(float)[r] / 12,
                              np.nan_to_num(snd.cada_amort.values.astype(float)[r]) / 12, car[r], np.where(di[r], cdi, 0), s0[r], pp_[r])
        s = np.where(np.abs(s - s0) > 15, s0, s)              # preco sem sentido (evento, erro de unidade): fica a taxa de emissao
        spr = np.where(di, s, np.where(real, s - curva("IPCA", d), s - curva("PRE", d)))
        poe(m3 & valido(spr), spr, d, np.where(np.isfinite(pp_), "SND + preço do fundo", "SND (taxa de emissão)").astype(object),
            np.where(di, "DI", np.where(real, "IPCA", "PRE")).astype(object))
    # 4) taxa contratada informada a CVM (LF, CDB, CRA, NC, debenture sem codigo...)
    ix = g.indexador.fillna("").values.astype(str)
    cup = g.cupom.values.astype(float)
    cup = np.where(np.nan_to_num(cup) != 0, cup, np.nan)
    pct_i, tpre = g.pct_indexador.values.astype(float), g.taxa_pre.values.astype(float)
    i_di = (np.char.find(ix, "DI de um dia") >= 0) | (np.char.find(ix, "Selic") >= 0)
    i_ip, i_pr = np.char.find(ix, "IPCA") >= 0, np.char.find(ix, "prefixada") >= 0
    m4 = np.isnan(sp) & (i_di | i_ip | i_pr) & ~np.isin(ca, SEM_SPREAD) & tem_venc
    if m4.any():
        cup_di = np.where(cup >= 50, (cup - 100) / 100 * cdi, cup)                  # % do CDI informado no campo de cupom
        taxa = np.where(i_di, np.where(np.isfinite(cup), cup_di, (pct_i - 100) / 100 * cdi), np.where(i_ip, cup, np.where(np.isfinite(tpre), tpre, cup)))
        zero = np.isin(ca, ["LF", "LFSN", "CDB", "DPGE", "LCA", "NC", "CCB", "LCI/LH"])   # pagam tudo no vencimento
        _, d = taxa_e_duration(anos, np.where(zero, anos + 1, 0.5), 0, 0, np.where(i_di, cdi, 0), np.nan_to_num(taxa), np.nan)
        spr = np.where(i_di, taxa, np.where(i_ip, taxa - curva("IPCA", d), taxa - curva("PRE", d)))
        poe(m4 & valido(spr), spr, d, "taxa contratada (CVM)", np.where(i_di, "DI", np.where(i_ip, "IPCA", "PRE")).astype(object))
    # 5) sem taxa publica: implicito pelo preco (cotas de FIDC, CRI sem taxa, bonds, outros)
    fid = ca == "FIDC"
    d_fidc = np.full(n, np.nan)
    d_fidc[fid] = [ctx.fidc_anos(c, m) for c in cod[fid]]
    m_f = fid & np.isnan(sp)
    if m_f.any():
        v = np.full(n, np.nan)
        v[m_f] = [ctx.fidc_spread(c, m, p) for c, p in zip(cod[m_f], pu_f[m_f])]
        poe(m_f & np.isfinite(v) & (v > -30) & (v < 40), v, d_fidc, "FIDC: rentabilidade da série (CVM)", "DI")
    m5 = np.isnan(sp) & ~np.isin(ca, SEM_SPREAD)
    if m5.any() and len(impl):
        v = impl.reindex(pd.MultiIndex.from_arrays([[m] * n, g.chave.values])).values.astype(float)
        usd = np.isin(ca, USD)
        d = d_fidc.copy()
        _, d_cri = taxa_e_duration(anos, 1 / 12, 1 / 12, 0, cdi, np.nan_to_num(v), np.nan)       # CRI: amortiza todo mes
        d = np.where((ca == "CRI") & tem_venc, d_cri, d)
        ust = lt.curva(ctx.ust, "UST", fm, np.nan_to_num(anos, nan=5)) if ctx.ust else np.full(n, 4.5)
        _, d_b = taxa_e_duration(anos, 0.5, 0, 0, ust, np.nan_to_num(v), np.nan)
        d = np.where((ca == "Bonds") & tem_venc, d_b, d)
        zero = np.isin(ca, ["LF", "LFSN", "CDB", "DPGE", "LCA", "NC", "CCB", "LCI/LH"])
        _, d_g = taxa_e_duration(anos, np.where(zero, anos + 1, 0.5), 0, 0, cdi, np.nan_to_num(v), np.nan)
        d = np.where(np.isnan(d) & tem_venc, d_g, d)
        poe(m5 & valido(v), v, d, np.where(usd, "implícito (preço em US$)", np.where(fid & np.isfinite(d), "implícito (cota) + prazo FIDC",
                                                                                        "implícito (preço)")).astype(object),
            np.where(usd, "USD", "DI").astype(object))
    # 6) renda variavel: nao se aplica
    na = np.isin(ca, SEM_SPREAD) & np.isnan(sp)
    fonte[na] = np.where(ca[na] == "Confidencial", "confidencial (CVM)", "não se aplica")
    # 7) o que faltar: mesmo emissor (neste fundo ou em outro fundo no mes); senao media da categoria; senao do fundo
    w = g.perc_pl.values.astype(float)
    gr = g.grupo.fillna("").values.astype(str)
    ok = np.isfinite(sp) & np.isfinite(du) & ~na & (w > 0) & ~np.isin(ca, ["Caixa", "Títulos Públicos"])         & ~np.char.startswith(fonte.astype(str), "estimado")
    for nome_g in np.unique(gr[ok]):                                    # alimenta o mapa de emissores do mes
        x = ok & (gr == nome_g)
        a = ctx.emissores.setdefault((m, nome_g), [0.0, 0.0, 0.0])
        a[0] += (sp[x] * w[x]).sum(); a[1] += (du[x] * w[x]).sum(); a[2] += w[x].sum()
    sem = np.isnan(sp) & ~na
    for nome_g in np.unique(gr[sem]):
        a = ctx.emissores.get((m, nome_g)) if nome_g else None
        if a and a[2] > 0:
            sel = sem & (gr == nome_g)
            sp[sel], fonte[sel], ind[sel] = a[0] / a[2], "estimado (mesmo emissor)", "DI"
            du[sel] = np.where(np.isnan(du[sel]), a[1] / a[2], du[sel])
    falta_s, falta_d = np.isnan(sp) & ~na, np.isnan(du) & ~na
    if falta_s.any() or falta_d.any():
        cred = ~np.isin(ca, ["Caixa", "Títulos Públicos"]) & ~na & (w > 0)

        def media(v, msk):
            ok = msk & np.isfinite(v) & (w > 0)
            return float(np.average(v[ok], weights=w[ok])) if ok.any() else np.nan
        for c in np.unique(ca[falta_s | falta_d]):
            mc = ca == c
            for v, falta, rotulo_ in ((sp, falta_s, None), (du, falta_d, " · duration estimada")):
                sel = mc & falta
                if not sel.any():
                    continue
                x, orig = media(v, mc & ~falta), "estimado (média da categoria)"
                if np.isnan(x):
                    x, orig = media(v, cred & ~falta), "estimado (média do fundo)"
                if np.isnan(x) and ant:                  # FIC sem a carteira do fundo investido no mes
                    x, orig = ant[0 if v is sp else 1], "estimado (carteira do mês anterior)"
                v[sel] = x
                if rotulo_ is None:
                    fonte[sel], ind[sel] = orig, "DI"
                else:
                    fonte[sel & ~falta_s] = fonte[sel & ~falta_s] + rotulo_
    g["spread"], g["duration"], g["pu"], g["fonte"] = sp, du, pu_f, fonte
    g["ipca"], g["pre"] = ind == "IPCA", ind == "PRE"
    g["usd"] = np.isin(ca, USD) | (ind == "USD")
    return g, dia


def derivativos_mes(gd, m, ctx, dur_ipca, dur_pre):
    """Contratos futuros do mes: tipo, lado, contratos, prazo e nocional estimado (R$)."""
    out = []
    for r in gd.itertuples():
        tipo, venc = contrato(f"{r.codigo or ''} {r.ativo or ''} {r.tipo_ativo or ''}")
        if "mercado futuro" not in str(r.categoria).lower():   # termo/opcao/swap: sem P&L de futuro
            tipo, venc = "OUTRO", None
        if tipo in ("DI1", "DAP") and not venc:                 # sem vencimento nao da para saber o prazo (ex.: trava de curva)
            tipo = "OUTRO"
        lado = -1 if "vendida" in str(r.categoria).lower() else 1
        n = abs(r.quantidade) if pd.notna(r.quantidade) else np.nan
        if venc:
            anos = max((pd.Timestamp(venc[0], venc[1], 15 if tipo == "DAP" else 1) - fim_mes(m)).days / 365.25, 1 / 252)
        else:
            anos = dur_ipca if tipo == "DAP" else dur_pre if tipo == "DI1" else 1.0
        out.append(dict(i=r.Index, tipo=tipo, lado=lado, n=n, anos=anos, fator=r.fator, categoria=r.categoria,
                        ativo=r.ativo, perc_cda=r.perc_pl))
    return out


def valor_ponto(tipo, m, ctx):
    if tipo == "DI1":
        return 1.0
    if tipo == "DAP":
        x = ctx.ipca[ctx.ipca.index <= m]
        return 0.00025 * float(x.iloc[-1]) if len(x) else np.nan
    return np.nan


def pu(tipo, m, anos, ctx):
    t = "PRE" if tipo == "DI1" else "IPCA"
    y = float(lt.curva(ctx.curvas, t, fim_mes(m), np.array([anos]))[0])
    return 1e5 / (1 + y / 100) ** anos


def nocional(c, m, ctx, pl_fundo):
    if c["tipo"] in ("DI1", "DAP") and pd.notna(c["n"]):
        return c["lado"] * c["n"] * pu(c["tipo"], m, c["anos"], ctx) * valor_ponto(c["tipo"], m, ctx)
    if c["tipo"] in ("DOL", "WDO") and pd.notna(c["n"]):
        return c["lado"] * c["n"] * (50000 if c["tipo"] == "DOL" else 10000) * ctx.ptax_em(m)
    return c["perc_cda"] / 100 * pl_fundo if pd.notna(c["perc_cda"]) else np.nan


def pnl_futuro(c, p, m, ctx):
    """P&L estimado (R$) do contrato entre o fim do mes p e o fim do mes m, com a posicao de p."""
    if pd.isna(c["n"]):
        return 0.0
    cdi = float(ctx.cdi_m.get(m, 0.0))
    if c["tipo"] in ("DI1", "DAP"):
        a1 = max(c["anos"] - (fim_mes(m) - fim_mes(p)).days / 365.25, 1 / 252)
        pu0, pu1 = pu(c["tipo"], p, c["anos"], ctx), pu(c["tipo"], m, a1, ctx)
        if c["tipo"] == "DI1":
            return c["lado"] * c["n"] * (pu1 - pu0 * (1 + cdi))
        i0, i1 = ctx.ipca[ctx.ipca.index <= p], ctx.ipca[ctx.ipca.index <= m]
        inf = float(i1.iloc[-1] / i0.iloc[-1] - 1) if len(i0) and len(i1) else 0.0
        return c["lado"] * c["n"] * valor_ponto("DAP", m, ctx) * (pu1 - pu0 * (1 + cdi) / (1 + inf))
    if c["tipo"] in ("DOL", "WDO"):
        return c["lado"] * c["n"] * (50000 if c["tipo"] == "DOL" else 10000) * (ctx.ptax_em(m) - ctx.ptax_em(p))
    return 0.0


def detalhe(nome, cnpj, df, ctx, pl, rent):
    """Tudo que as abas Carteira e Retorno mostram para um fundo + tabela de ativos (busca/top/grupos) de cada mes."""
    df = df.copy()
    # fecha 100% do PL em todo mes: a diferenca vira uma linha explicita (confidencial se o mes tem parte relevante assim)
    nd = df[~df.derivativo]
    falta = (100 - nd.groupby("mes").perc_pl.sum()).loc[lambda x: x.abs() > 0.05]
    if len(falta):
        conf = nd[nd.confidencial].groupby("mes").perc_pl.sum().reindex(falta.index).fillna(0) >= 5
        df = pd.concat([df, pd.DataFrame({"fundo": nome, "mes": falta.index, "categoria": lt.AJUSTE, "perc_pl": falta.values,
                                          "ativo": "Diferença entre PL e carteira informada (CVM)", "derivativo": False,
                                          "confidencial": conf.values, "chave": "ajuste|" + falta.index})], ignore_index=True)
    for c in ("emissor", "codigo", "ativo", "tipo_ativo", "indexador", "categoria"):     # coluna toda vazia vira texto
        if c in df.columns:
            df[c] = df[c].astype(object)
    if len(ctx.snd):                                    # emissor faltando: nome do emissor pelo SND / ANBIMA
        df["emissor"] = df.emissor.fillna(df.codigo.map(ctx.snd.empresa))
    if ctx.an_h is not None and len(ctx.an_h):
        df["emissor"] = df.emissor.fillna(df.codigo.map(ctx.an_h.drop_duplicates("codigo", keep="last").set_index("codigo").nome))
    lixo = r"(?i)\bBONDS?\s*\d*\s*DAYS?\s*SETTLE\b|\s[\d.,]{5,}\b"           # bonds: 'BONDS 2 DAYS SETTLE - emissor - qtd'
    df["emissor"] = df.emissor.astype(object).str.replace(lixo, " ", regex=True).str.strip(" -").replace("", "Emissor não informado")
    emis = df[["emissor", "categoria"]].drop_duplicates()
    k = lambda e: e if isinstance(e, str) else None                            # NaN nao serve de chave
    gmap = {(k(e), c): lt.grupo(e, c) for e, c in zip(emis.emissor, emis.categoria)}
    df["grupo"] = [gmap[(k(e), c)] for e, c in zip(df.emissor, df.categoria)]
    curto = df.ativo.str.replace(GENERICO, " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip(" -").str.slice(0, 40)
    df["grupo"] = df.grupo.fillna(curto)
    df["casa"] = casa(df, ctx)
    df["venc"] = vencimento(df)
    df["tp"] = tipo_tp(df)
    df["rotulo"] = rotulo(df, df.venc.fillna(df.codigo.map(ctx.snd.venc) if len(ctx.snd) else df.venc), df.tp)
    impl = implicito(df, ctx)
    meses = sorted(df.mes.unique())
    recentes = set(meses[-4:])
    pl_f = {m: float(pl.get((m, cnpj), np.nan)) for m in meses}
    cart_meses, ricos, tab_ativos, ant = [], {}, [], None
    for m in meses:
        g = df[df.mes == m]
        e, dia = mede(g[~g.derivativo], m, ctx, recentes, impl, ant)
        ricos[m] = (e, g[g.derivativo])
        e["fin"] = e.perc_pl / 100 * pl_f[m] / 1e6
        cats = [{"categoria": c, "perc": x.perc_pl.sum(), "fin": x.fin.sum(), "spread": wavg(x.spread, x.perc_pl),
                 "duration": wavg(x.duration, x.perc_pl)} for c, x in e.groupby("casa")]
        cats.sort(key=lambda r: -r["perc"])
        total = {"categoria": "Total", "perc": e.perc_pl.sum(), "fin": e.fin.sum(), "spread": wavg(e.spread, e.perc_pl),
                 "duration": wavg(e.duration, e.perc_pl)}
        pos = e[e.perc_pl > 0]
        fontes = (pos.groupby(pos.fonte.str.split(" · ").str[0]).perc_pl.sum() / max(pos.perc_pl.sum(), 1e-9) * 100).round(1)
        if total["spread"] is not None and total["duration"] is not None:
            ant = (total["spread"], total["duration"])
        cart_meses.append({"mes": m, "pl_mm": pl_f[m] / 1e6, "anbima": dia, "conf": e[e.confidencial].perc_pl.sum(),
                           "cats": cats, "total": total, "fontes": fontes.sort_values(ascending=False).to_dict()})
        # tabela de ativos do mes (rotulo curto), maior posicao primeiro
        x = e[e.perc_pl != 0].sort_values("perc_pl", ascending=False)
        x = x.assign(sw=(x.spread * x.perc_pl).fillna(0), sp_=x.perc_pl.where(x.spread.notna(), 0),
                     dw=(x.duration * x.perc_pl).fillna(0), dp=x.perc_pl.where(x.duration.notna(), 0))
        t = x.groupby("rotulo", sort=False).agg(categoria=("casa", "first"), grupo=("grupo", "first"), emissor=("emissor", "first"),
                                                codigo=("codigo", "first"), perc=("perc_pl", "sum"), sw=("sw", "sum"), sp_=("sp_", "sum"),
                                                dw=("dw", "sum"), dp=("dp", "sum"), pu=("pu", "first"), fonte=("fonte", "first")).reset_index()
        t["spread"] = (t.sw / t.sp_).where(t.sp_ != 0)
        t["duration"] = (t.dw / t.dp).where(t.dp != 0)
        tab_ativos.append(t.drop(columns=["sw", "sp_", "dw", "dp"]).assign(mes=m))

    # ---- atribuicao mensal (retorno por categoria, hedges alocados nos ativos protegidos)
    real = rent[rent.fundo == nome].set_index("mes").retorno
    k = lt.contribuicao(df)
    if len(k):                                   # variacao do preco unitario de cada posicao mantida (v/qt)
        k = k[(k.qt > 0) & (k.qt_ant > 0) & (k.v_ant > 0)]
        k = k.assign(rp=(k.v / k.qt) / (k.v_ant / k.qt_ant) - 1)
        preco = k.groupby(["mes", "chave"]).rp.first()
    else:
        preco = pd.Series(dtype=float)
    atr_meses, cats_atr, ativos, contrib = [], {}, {}, []
    id_ativo = lambda a, c, gr, cod, em: ativos.setdefault((a, c), {"i": len(ativos), "ativo": a, "categoria": c, "grupo": gr,
                                                                     "codigo": cod, "emissor": em})["i"]
    for j in range(1, len(meses)):
        p, m = meses[j - 1], meses[j]
        if m not in real.index or pd.isna(real.get(m)):
            continue
        e0, gd0 = ricos[p]
        w = e0[e0.perc_pl.abs() > 0].copy()            # confidenciais entram (rendem CDI + residuo): a soma sempre fecha
        cdi_m = float(ctx.cdi_m.get(m, 0.0))
        # 1) retorno de cada ativo: esperado = CDI + spread proprio; usa a variacao real de preco quando ela e critica
        #    (queda maior que 1,5 p.p. abaixo do esperado = pagamento de cupom/amortizacao -> fica o esperado)
        esperado = (1 + cdi_m) * (1 + w.spread.fillna(0).clip(-5, 30) / 100) ** (1 / 12) - 1
        # + marcacao a mercado: -duration x (variacao da curva IPCA/pre no prazo + variacao do spread de mercado)
        D = w.duration.fillna(0).clip(0, 30).values
        dc = np.zeros(len(w))
        for flag, t in ((w.ipca.values, "IPCA"), (w.pre.values, "PRE")):
            if flag.any():
                dc[flag] = lt.curva(ctx.curvas, t, fim_mes(m), D[flag]) - lt.curva(ctx.curvas, t, fim_mes(p), D[flag])
        e1 = ricos[m][0].drop_duplicates("chave").set_index("chave")
        ds = (w.chave.map(e1.spread) - w.spread).where(w.fonte.isin(MERCADO) & w.chave.map(e1.fonte).isin(MERCADO))
        y = ctx.cdi_aa(p) / 100 + w.spread.fillna(0).values / 100
        esperado = esperado - D / (1 + y) * (np.nan_to_num(dc) + ds.fillna(0).clip(-5, 5).values) / 100
        rp = w.chave.map(preco.loc[m]) if len(preco) and m in preco.index.get_level_values(0) else pd.Series(np.nan, index=w.index)
        r = rp.where(rp.notna() & (rp >= esperado - 0.015) & (rp <= esperado + 0.03), esperado)
        cx = w.casa.isin(CAIXA)
        r[cx] = cdi_m
        ativo_c = w.perc_pl * r
        # 2) derivativos -> ativos protegidos
        ip = w[w.ipca & w.perc_pl.gt(0)]
        dur_ipca = wavg(ip.duration, ip.perc_pl) or 3.0
        pr = w[w.pre & w.perc_pl.gt(0)]
        dur_pre = wavg(pr.duration, pr.perc_pl) or 1.0
        hedge = 0.0
        for c in derivativos_mes(gd0, p, ctx, dur_ipca, dur_pre):
            v = pnl_futuro(c, p, m, ctx) * c["fator"] / 100 * 100 if pd.notna(c["fator"]) else 0.0  # % do PL do fundo
            if not v or np.isnan(v):
                continue
            alvo = (w.ipca if c["tipo"] == "DAP" else w.pre if c["tipo"] == "DI1" and w.pre.any() else w.ipca
                    if c["tipo"] == "DI1" else w.usd if c["tipo"] in ("DOL", "WDO", "DDI") else pd.Series(False, index=w.index))
            alvo = alvo & w.perc_pl.gt(0)
            if not alvo.any():
                alvo = w.perc_pl.gt(0) & ~cx
            ativo_c[alvo] += v * w.perc_pl[alvo] / w.perc_pl[alvo].sum()
            hedge += v
        # 3) resto (taxas, negociacao, marcacao fora do esperado) -> todas as categorias que nao sao caixa, pelo peso
        resid = float(real[m]) * 100 - ativo_c.sum()
        cr = w.perc_pl.gt(0) & ~cx
        if not cr.any():
            cr = w.perc_pl.gt(0)
        ativo_c[cr] += resid * w.perc_pl[cr] / w.perc_pl[cr].sum()
        atr_meses.append({"mes": m, "real": float(real[m]) * 100, "cdi": float(ctx.cdi_m.get(m, np.nan)) * 100,
                          "hedge": hedge, "resid": resid})
        jm = len(atr_meses) - 1
        por_cat = ativo_c.groupby(w.casa).sum()
        peso = w.groupby("casa").perc_pl.sum()
        for c in set(por_cat.index) | set(cats_atr):
            cats_atr.setdefault(c, {"contrib": [None] * jm, "peso": [None] * jm})
            cats_atr[c]["contrib"].append(float(por_cat.get(c, 0.0)))
            cats_atr[c]["peso"].append(float(peso.get(c, 0.0)))
        nc = w[~cx & ~w.casa.eq("Confidencial")].assign(c_=ativo_c[~cx & ~w.casa.eq("Confidencial")])                               # caixa/compromissada fora do ranking
        pa = nc.groupby(["rotulo", "casa"]).agg(v=("c_", "sum"), p=("perc_pl", "sum"), gr=("grupo", "first"),
                                                cod=("codigo", "first"), em=("emissor", "first"))
        for (a, c), x in pa.iterrows():
            if abs(x.v) > 1e-5:
                contrib.append([id_ativo(a, c, x.gr, x.cod, x.em), jm, round(float(x.v), 6), round(float(x.p), 4)])
    for c in cats_atr.values():
        for key in ("contrib", "peso"):
            c[key] += [None] * (len(atr_meses) - len(c[key]))
    tab = pd.concat(tab_ativos, ignore_index=True) if tab_ativos else pd.DataFrame()
    return limpo({"nome": nome, "cnpj": cnpj, "carteira": cart_meses,
                  "retorno": {"meses": atr_meses, "categorias": cats_atr,
                              "ativos": sorted(ativos.values(), key=lambda x: x["i"]), "contrib": contrib}}), tab


# ------------------------------------------------------------------ pre-carga de todos os fundos
def pasta_dia():
    return lt.CACHE / "painel" / str(date.today())


def precarrega(log=None):
    escreve = log or PRE["log"].append
    PRE["status"] = "rodando"
    try:
        fundos = [(n, lt.cnpj_of(x), True) for n, x in lt.NOSSOS_FUNDOS.items()] + \
                 [(n, lt.cnpj_of(x), False) for n, x in lt.PEERS.items()]
        dest = pasta_dia()
        chave = "|".join(sorted(c for _, c, _ in fundos)) + "|" + lt.DESDE + f"|m{METODO}"
        if (dest / "visao.json").exists() and json.loads((dest / "visao.json").read_text(encoding="utf-8")).get("chave") == chave:
            escreve("Usando o painel já processado hoje.")
            PRE.update(status="ok", pasta=str(dest))
            return
        dest.mkdir(parents=True, exist_ok=True)
        for velho in (lt.CACHE / "painel").glob("*"):
            if velho != dest and velho.is_dir():
                for f in velho.glob("*"):
                    f.unlink(missing_ok=True)
                velho.rmdir()
        escreve(f"Baixando/atualizando dados da CVM de {len(fundos)} fundos desde {lt.DESDE}...")
        workers = max(1, min(4, (os.cpu_count() or 2)))
        meses, dia = lt.prepara(sorted(c for _, c, _ in fundos), lt.DESDE, workers=workers, log=escreve)
        ctx = Contexto(escreve, meses)
        escreve("Carregando carteiras...")
        carga = lt.carrega_pos(meses)
        pl = carga[1]
        nomes = {n: c for n, c, _ in fundos}
        d = lt.diario(nomes, dia)
        rent = lt.rentabilidade(d, ctx.cdi_m) if len(d) else pd.DataFrame(columns=["fundo", "mes", "retorno"])
        for i, (n, c, _) in enumerate(fundos, 1):
            escreve(f"[{i}/{len(fundos)}] {n}: look-through, carteira e atribuição...")
            fid = re.sub(r"\D", "", c)
            try:                                 # um fundo com problema nao derruba os outros
                df = lt.lookthrough({n: c}, meses, carga)
                if not len(df):
                    escreve(f"   {n}: a CVM não tem carteira deste CNPJ no período (só cota/retorno).")
                    continue
                det, tab = detalhe(n, c, df, ctx, pl, rent)
            except Exception as e:
                escreve(f"   {n}: pulado ({type(e).__name__}: {e})")
                continue
            (dest / (fid + ".json")).write_text(json.dumps(det), encoding="utf-8")
            tab.to_parquet(dest / (fid + "_ativos.parquet"), index=False)
            df.drop(columns=["chave", "fator"], errors="ignore").to_parquet(dest / (fid + ".parquet"), index=False)
        # visao geral: cotas diarias de todos (para retorno em qualquer periodo, consolidado e risco x retorno)
        datas = sorted(d.data.unique())
        idx = pd.DatetimeIndex(datas)
        q = d.pivot_table(index="data", columns="fundo", values="VL_QUOTA").reindex(idx)
        plf = d.pivot_table(index="data", columns="fundo", values="VL_PATRIM_LIQ").reindex(idx)
        cdi_idx = (1 + ctx.cdi_d.reindex(idx).fillna(0)).cumprod()
        cores, k_nosso = {}, 0
        for n, c, nosso in fundos:
            cores[n] = NOSSAS_CORES[k_nosso % len(NOSSAS_CORES)] if nosso else "#9aa0a6"
            k_nosso += nosso
        visao = {"chave": chave, "gerado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "desde": lt.DESDE,
                 "ult_carteira": max(meses) if meses else None, "anbima": ctx.an_dias[-1] if ctx.an_dias else None,
                 "datas": [t.strftime("%Y-%m-%d") for t in idx], "cdi": cdi_idx.tolist(),
                 "fundos": [{"nome": n, "cnpj": c, "id": re.sub(r"\D", "", c), "nosso": nosso, "cor": cores[n],
                             "tem_carteira": (dest / (re.sub(r"\D", "", c) + ".json")).exists(),
                             "cota": q[n].tolist() if n in q else [], "pl": float(plf[n].dropna().iloc[-1]) / 1e6 if n in plf and plf[n].notna().any() else None}
                            for n, c, nosso in fundos],
                 "cat_cores": CAT_CORES}
        (dest / "visao.json").write_text(json.dumps(limpo(visao)), encoding="utf-8")
        escreve("Pronto.")
        PRE.update(status="ok", pasta=str(dest))
    except Exception as e:
        import traceback
        PRE.update(status="erro", erro=f"{type(e).__name__}: {e}")
        escreve("ERRO: " + PRE["erro"])
        escreve(traceback.format_exc()[-1500:])


def _inicio():                              # servidor (pasta/Docker): pre-carga em segundo plano
    if PRE["status"] == "parado":
        threading.Thread(target=precarrega, daemon=True).start()


app.add_event_handler("startup", _inicio)


# ------------------------------------------------------------------ API
@app.middleware("http")
async def sem_cache(req, call_next):         # pagina/JS/CSS novos aparecem logo depois de atualizar o arquivo
    r = await call_next(req)
    if not req.url.path.startswith("/api/"):
        r.headers["Cache-Control"] = "no-cache"
    return r


@app.get("/api/inicial")
def inicial():
    return {"status": PRE["status"], "log": PRE["log"][-8:], "erro": PRE["erro"]}


def _arquivo(nome):
    if PRE["status"] != "ok":
        raise HTTPException(503, "painel ainda carregando")
    f = os.path.join(PRE["pasta"], nome)
    if not os.path.exists(f):
        raise HTTPException(404, "sem dados")
    return f


@app.get("/api/visao")
def visao():
    return FileResponse(_arquivo("visao.json"), media_type="application/json")


@app.get("/api/fundo/{fid}")
def fundo(fid: str):
    return FileResponse(_arquivo(re.sub(r"\D", "", fid) + ".json"), media_type="application/json")


_ATIVOS = {}


@app.get("/api/ativos/{fid}")
def ativos_mes(fid: str, mes: str):
    """Todos os ativos do fundo no mes (rotulo, categoria, grupo, % PL, spread, duration, PU, fonte)."""
    f = _arquivo(re.sub(r"\D", "", fid) + "_ativos.parquet")
    if f not in _ATIVOS:
        if len(_ATIVOS) > 30:
            _ATIVOS.clear()
        _ATIVOS[f] = pd.read_parquet(f)
    t = _ATIVOS[f]
    return JSONResponse(limpo(t[t.mes == mes].drop(columns="mes").to_dict("records")))


@app.get("/api/csv/{fid}")
def csv(fid: str):
    df = pd.read_parquet(_arquivo(re.sub(r"\D", "", fid) + ".parquet"))
    return Response(df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="carteira_{fid}.csv"'})


@app.get("/")
def index():
    return FileResponse(os.path.join(AQUI, "static", "index.html"))
