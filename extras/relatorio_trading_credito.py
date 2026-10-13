"""
Resumo de trading de crédito privado (negócios de balcão da B3) -> PDF + HTML (pronto para e-mail).
  Fontes grátis: B3 (negócio a negócio e cadastro), ANBIMA (taxa indicativa e duration das debêntures),
  Tesouro Direto (curvas pré e IPCA+ para o spread), Banco Central (CDI).
  Dia: hoje se já passou das 20h e houver negócios; senão o último dia útil com negócios (D-1).
  Grupos: debêntures não isentas, debêntures isentas (Lei 12.431), bancários (LF, LFSN, LFSC, LIG) e
          estruturados (CRI, CRA, cotas de FIDC, CDCA, CPR e notas comerciais). Cotas de FII/Fiagro ficam fora.
Uso:  python relatorio_trading_credito.py [AAAA-MM-DD] [--outlook]
      --outlook: cria um RASCUNHO no Outlook (Windows) com o HTML no corpo, gráficos embutidos e o PDF anexo (não envia).
"""
import base64
import io
import os
import sys
import textwrap
import time
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import requests

matplotlib.use("Agg")
matplotlib.rcParams["text.parse_math"] = False                           # "R$" não é fórmula
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

PASTA = Path(__file__).resolve().parent / "relatorio_trading"
CACHE = PASTA / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
NAVY, LARANJA, CINZA, CLARO = "#1F2A4D", "#EC7000", "#8C8C8C", "#F4F4F4"
MIN_VOL = 1e6                       # destaques: ativos com R$ 1 mi+ no dia; tabelas do PDF/HTML: negócios de R$ 1 mi+
DIAS_HIST = 30
GRUPOS = ["Debêntures não isentas", "Debêntures isentas", "Bancários", "Estruturados"]
COLS = ["tipo", "emissor", "codigo", "quantidade", "pu", "volume", "taxa", "origem", "hora", "data", "id", "isin", "liquidacao",
        "situacao"]


# ----------------------------------------------------------------- dados
def get(url, metodo="GET", **kw):
    for t in range(3):
        try:
            r = requests.request(metodo, url, timeout=300, headers={"User-Agent": "Mozilla/5.0"}, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if t == 2:
                raise
            time.sleep(3 * (t + 1))


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")


def b3(tabela, dia):
    r = get("https://arquivos.b3.com.br/bdi/table/export/csv?lang=pt-BR", "POST",
            json={"Name": tabela, "Date": f"{dia:%Y-%m-%d}", "FinalDate": f"{dia:%Y-%m-%d}", "ClientId": "", "Filters": {}})
    t = r.content.decode("utf-8-sig").splitlines()
    i = next((k for k, l in enumerate(t) if l.count(";") > 5), None)
    return pd.DataFrame() if i is None else pd.read_csv(io.StringIO("\n".join(t[i:])), sep=";", dtype=str)


def negocios(dia):
    """Negócios de um dia (cache em disco para dias encerrados)."""
    f = CACHE / f"neg_{dia:%Y%m%d}.parquet"
    if f.exists() and dia < pd.Timestamp.today().normalize():
        return pd.read_parquet(f)
    x = b3("Trade", dia)
    if len(x):
        x = x.iloc[:, :len(COLS)].set_axis(COLS, axis=1)
        x = x[x.situacao.ne("Cancelado") & x.codigo.notna() & x.data.notna()].copy()
        for c in ("quantidade", "pu", "volume", "taxa"):
            x[c] = num(x[c])
        x["taxa"] = x.taxa.where(x.taxa != 0)                              # 0 = registro sem taxa informada
        x["data"] = pd.Timestamp(dia)
    else:
        x = pd.DataFrame(columns=COLS)
    x.to_parquet(f)
    return x


def cadastro():
    f = CACHE / "cadastro.parquet"
    if f.exists() and time.time() - f.stat().st_mtime < 20 * 3600:
        return pd.read_parquet(f)
    for k in range(8):                                                     # o arquivo do dia às vezes vem incompleto
        d = b3("InstrumentRegistration", pd.Timestamp.today() - pd.Timedelta(days=k))
        if len(d) > 1000 and (d.iloc[:, 3] == "DEB").sum() > 1000 and (d.iloc[:, 3] == "LF").sum() > 1000:
            break
    else:
        return pd.read_parquet(f)
    d = d.iloc[:, :17].set_axis(["codigo", "isin", "emissor", "tipo", "incent", "serie", "emissao_n", "idx", "pct", "taxa_emis",
                                 "base", "venc", "qtd", "pu_emis", "restrito", "temis", "oferta"], axis=1)
    d.to_parquet(f)
    return d


def anbima(dia):
    """Arquivo diário de debêntures da ANBIMA do dia (ou o último antes dele)."""
    for d in pd.bdate_range(dia - pd.Timedelta(days=10), dia)[::-1]:
        f = CACHE / f"anbima_db{d:%y%m%d}.txt"
        if not f.exists():
            try:
                r = requests.get(f"https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/db{d:%y%m%d}.txt", timeout=60)
                if r.status_code == 200 and "Código@".encode("latin1") in r.content:
                    f.write_bytes(r.content)
            except requests.RequestException:
                pass
        if f.exists():
            l = f.read_bytes().decode("latin1").splitlines()
            i = next(j for j, s in enumerate(l) if s.startswith("Código@"))
            a = pd.read_csv(io.StringIO("\n".join(l[i:])), sep="@", dtype=str).iloc[:, [0, 1, 6, 12]]
            a.columns = ["codigo", "nome_anbima", "taxa_anbima", "dur_anbima"]
            a["taxa_anbima"], a["dur_anbima"] = num(a.taxa_anbima), num(a.dur_anbima) / 252
            a["nome_anbima"] = a.nome_anbima.str.replace(r"\s*\(\*+\)", "", regex=True).str.strip()
            return a, d
    return pd.DataFrame(columns=["codigo", "nome_anbima", "taxa_anbima", "dur_anbima"]), None


def curvas(dia):
    """Curvas pré e IPCA+ do Tesouro Direto no último dia até `dia`: {tipo: (prazos, taxas)}."""
    f = CACHE / "tesouro.csv"
    if not f.exists() or time.time() - f.stat().st_mtime > 20 * 3600:
        f.write_bytes(get("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/"
                          "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv").content)
    d = pd.read_csv(f, sep=";", decimal=",")
    d = d[d["Tipo Titulo"].isin(["Tesouro Prefixado", "Tesouro IPCA+"])].copy()
    d["data"] = pd.to_datetime(d["Data Base"], dayfirst=True)
    d = d[d.data <= dia]
    d = d[d.data == d.data.max()]
    d["anos"] = (pd.to_datetime(d["Data Vencimento"], dayfirst=True) - d.data).dt.days / 365.25
    d["taxa"] = d[["Taxa Compra Manha", "Taxa Venda Manha"]].replace(0, np.nan).mean(axis=1)
    d = d.dropna(subset=["taxa"]).sort_values("anos")
    return {("PRE" if t == "Tesouro Prefixado" else "IPCA"): (g.anos.values, g.taxa.values) for t, g in d.groupby("Tipo Titulo")}


def cdi_aa():
    j = get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados/ultimos/5?formato=json").json()
    return ((1 + float(j[-1]["valor"]) / 100) ** 252 - 1) * 100


def grupo(tipo, incent, emissor):
    if tipo == "DEB":
        return "Debêntures isentas" if incent else "Debêntures não isentas"
    if tipo in ("LF", "LFSN", "LFSC", "LIG"):
        return "Bancários"
    if tipo in ("CRI", "CRA", "CDCA", "CPR", "NC") or (tipo == "CFF" and "CREDITORIO" in str(emissor).upper()):
        return "Estruturados"
    return None


def encurta(nomes):
    """Nomes de emissor mais curtos para o texto e as tabelas."""
    t = nomes.astype(str).str.upper()
    for de, para in ((r"FUNDO DE INVESTIMENTO EM DIREITOS CREDIT[OÓ]RIOS?", "FIDC"), (r"RESPONSABILIDADE LIMITADA|RESP\.? LIMITADA", ""),
                     (r"SOCIEDADE DE CR[EÉ]DITO,? FINANCIAMENTO E INVESTIMENTO", "SCFI"), (r"SECURITIZADORA DE DIREITOS CREDIT[OÓ]RIOS DO AGRONEG[OÓ]CIO", "SECURITIZADORA"),
                     (r"PARTICIPA[CÇ][OÕ]ES", "PART."), (r"\s+-?\s*$", ""), (r"\s{2,}", " ")):
        t = t.str.replace(de, para, regex=True)
    return t.str.strip(" -")


def enriquece(x, cad, anb, cur, cdi):
    c = cad.drop_duplicates("codigo").set_index("codigo")[["incent", "idx", "pct", "venc"]]
    x = x.join(c, on="codigo")
    x["grupo"] = [grupo(t, i == "True", e) for t, i, e in zip(x.tipo, x.incent, x.emissor)]
    x = x[x.grupo.notna()].copy()
    x["pct"] = num(x.pct)
    x["venc"] = pd.to_datetime(x.venc, dayfirst=True, errors="coerce")
    pct_cdi = x.idx.eq("DI") & x.pct.notna() & x.pct.ne(100)
    pct_cdi |= x.idx.eq("DI") & (x.taxa > 40)                              # cadastrado como CDI+, negociado em % do CDI
    x["indexador"] = np.select([x.tipo.eq("CFF"), pct_cdi, x.idx.eq("DI"), x.idx.eq("IPCA"), x.idx.eq("PREFIXADO")],
                               ["Cota FIDC", "% CDI", "CDI+", "IPCA+", "PRE"],
                               default=x.idx.replace({"Sem Indice": "sem índice"}).fillna("sem cadastro"))
    x["emissor"] = encurta(x.emissor)
    x = x.merge(anb, on="codigo", how="left")
    anos = ((x.venc - x.data).dt.days / 365.25).clip(0, 30)
    r = (x.taxa.where(x.indexador.isin(["IPCA+", "PRE"])) / 100).fillna(.12)
    bullet = x.tipo.isin(["LF", "LFSN", "LFSC", "LIG", "NC", "CFF"])
    aprox = pd.Series(np.where(bullet, anos / (1 + r), (1 - (1 + r) ** -anos.clip(upper=10)) / r), index=x.index)
    x["duration"] = x.dur_anbima.fillna(aprox.where(x.tipo.ne("CFF")))     # cota de fundo: sem duration
    ref = [np.interp(d, *cur[k]) if k in cur and d == d else np.nan
           for k, d in zip(np.where(x.indexador.eq("IPCA+"), "IPCA", "PRE"), x.duration)]
    x["spread"] = np.select([x.indexador.eq("CDI+"), x.indexador.eq("% CDI"), x.indexador.isin(["IPCA+", "PRE"])],
                            [x.taxa, (x.taxa / 100 - 1) * cdi, x.taxa - np.array(ref)], np.nan)
    x["empresa"] = np.where(x.tipo.isin(["CRI", "CRA", "CFF"]), "n/d (lastro)", x.nome_anbima.fillna(x.emissor))
    return x


# ----------------------------------------------------------------- texto
def br(v, casas=1, pct=False):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    s = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s + ("%" if pct else "")


mm = lambda v: f"R$ {br(v / 1e6)} mi"


def taxa_txt(ind, t):
    if t != t:
        return "-"
    return {"CDI+": f"CDI + {br(t, 2)}%", "% CDI": f"{br(t, 1)}% CDI", "IPCA+": f"IPCA + {br(t, 2)}%", "PRE": f"PRE {br(t, 2)}%"}.get(ind, br(t, 2))


def por_ativo(g):
    w = g.assign(tv=g.taxa * g.volume, sv=g.spread * g.volume, vt=g.volume.where(g.taxa.notna()), vs=g.volume.where(g.spread.notna()))
    a = w.groupby("codigo").agg(emissor=("emissor", "first"), indexador=("indexador", "first"), volume=("volume", "sum"),
                                negocios=("id", "count"), duration=("duration", "first"), taxa_anbima=("taxa_anbima", "first"),
                                tv=("tv", "sum"), sv=("sv", "sum"), vt=("vt", "sum"), vs=("vs", "sum"))
    a["taxa"] = (a.tv / a.vt).where(a.vt > 0)
    a["spread"] = (a.sv / a.vs).where(a.vs > 0)
    a["dif_bps"] = (a.taxa - a.taxa_anbima) * 100
    return a


def destaques(g, nome):
    """Parágrafos do grupo e os números do cabeçalho."""
    vol, n = g.volume.sum(), len(g)
    if n == 0:
        return {"kpi": [], "texto": [f"Sem negócios de {nome.lower()} no dia."]}
    a = por_ativo(g)
    em = g.groupby("emissor").volume.sum().sort_values(ascending=False)
    top = a.volume.idxmax()
    kpi = [("Volume", mm(vol)), ("Operações", br(n, 0)), ("Maior ativo", f"{top} ({mm(a.volume[top])})"),
           ("Maior emissor", f"{em.index[0].title()} ({mm(em.iloc[0])})")]
    t = [f"{nome} movimentaram {mm(vol)} em {br(n, 0)} negócios, com ticket médio de {mm(vol / n)}. "
         f"{em.index[0].title()} liderou o volume por emissor ({mm(em.iloc[0])})"
         + (f", seguido por {em.index[1].title()} ({mm(em.iloc[1])})" if len(em) > 1 else "")
         + (f" e {em.index[2].title()} ({mm(em.iloc[2])})." if len(em) > 2 else ".")]
    d = g.dropna(subset=["duration"])
    if len(d):
        dur = np.average(d.duration, weights=d.volume)
        grandes = a[(a.volume >= MIN_VOL) & a.duration.notna()]
        lg = grandes.duration.idxmax() if len(grandes) else None
        t.append(f"Duration média ponderada de {br(dur)} anos" +
                 (f", com destaque para {lg} ({br(grandes.duration[lg])} anos, {mm(grandes.volume[lg])})." if lg else "."))
    ind = (g.groupby("indexador").volume.sum() / vol * 100).sort_values(ascending=False)
    t.append("Distribuição por indexador: " + ", ".join(f"{k} ({br(v, 0)}%)" for k, v in ind.items() if v >= .5) + ".")
    s = a[(a.volume >= MIN_VOL) & a.spread.notna()]
    linha = lambda k: f"{k} a {taxa_txt(s.indexador[k], s.taxa[k])} (spread {br(s.spread[k], 2)}%, {mm(s.volume[k])})"
    if len(s) >= 2:
        hi, lo = s.spread.nlargest(2).index, s.spread.nsmallest(2).index
        t.append(f"Atípicos (ativos com {mm(MIN_VOL)}+): maiores spreads: {linha(hi[0])} e {linha(hi[1])}. "
                 f"Menores spreads: {linha(lo[0])} e {linha(lo[1])}.")
    b = s[s.dif_bps.notna()]
    la = lambda k: f"{k} a {taxa_txt(b.indexador[k], b.taxa[k])} vs ANBIMA {taxa_txt(b.indexador[k], b.taxa_anbima[k])} ({br(b.dif_bps[k], 0)} bps)"
    if len(b) >= 2:
        ac, ab = b.dif_bps.nlargest(2).index, b.dif_bps.nsmallest(2).index
        t.append(f"Acima da ANBIMA: {la(ac[0])} e {la(ac[1])}. Abaixo da ANBIMA: {la(ab[0])} e {la(ab[1])}.")
    elif g.taxa.isna().all():
        t.append("Os negócios deste grupo são registrados na B3 sem taxa (só PU), então não há spread nem comparação com a ANBIMA.")
    return {"kpi": kpi, "texto": t}


# ----------------------------------------------------------------- gráficos
def estilo(ax, titulo):
    ax.set_title(titulo, loc="left", fontsize=10, fontweight="bold", color=NAVY)
    ax.tick_params(labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=.25)


def g_dispersao(ax, g):
    t = g.dropna(subset=["taxa", "duration"])
    if not len(t):
        ax.axis("off")
        ax.text(.5, .5, "sem negócios com taxa informada", ha="center", color=CINZA)
        return
    ind = t.groupby("indexador").volume.sum().idxmax()
    t = t[t.indexador == ind].nlargest(40, "volume")
    ax.scatter(t.duration, t.taxa, s=20 + 600 * t.volume / t.volume.max(), color=NAVY, alpha=.55, edgecolor="white")
    for _, r in t.nlargest(8, "volume").iterrows():
        ax.annotate(r.codigo, (r.duration, r.taxa), fontsize=7, xytext=(4, 4), textcoords="offset points", color=LARANJA)
    ax.set_xlabel("duration (anos)", fontsize=8)
    ax.set_ylabel({"CDI+": "spread CDI+ (%)", "% CDI": "% do CDI", "IPCA+": "taxa IPCA+ (%)", "PRE": "taxa pré (%)"}.get(ind, "taxa"), fontsize=8)
    estilo(ax, f"Maiores negócios {ind} (bolha = volume)")


def g_evolucao(ax, h):
    x = [d.strftime("%d/%m") for d in h.index]
    ax2 = ax.twinx()
    ax2.bar(x, h.volume / 1e6, color=NAVY, alpha=.35, label="volume (R$ mi)")
    ax.plot(x, h.negocios, color=LARANJA, marker="o", ms=3, lw=1.6, label="negócios")
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)
    ax.set_ylabel("negócios", fontsize=8, color=LARANJA)
    ax2.set_ylabel("volume (R$ mi)", fontsize=8, color=NAVY)
    ax.tick_params(axis="x", labelrotation=60, labelsize=7)
    ax2.tick_params(labelsize=8)
    ax2.spines[["top"]].set_visible(False)
    estilo(ax, f"Evolução {len(h)} dias úteis: negócios (linha) e volume (barras)")


def png(func, *args, tam=(7.5, 3.2)):
    fig, ax = plt.subplots(figsize=tam)
    func(ax, *args)
    fig.tight_layout()
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=130)
    plt.close(fig)
    return b.getvalue()


# ----------------------------------------------------------------- tabela
def tabela(g):
    t = g[g.volume >= MIN_VOL].sort_values("volume", ascending=False)
    return pd.DataFrame({"Hora": t.hora, "Ativo": t.codigo, "Emissor": t.emissor.str.title().str.slice(0, 24),
                         "Vencimento": t.venc.dt.strftime("%d/%m/%Y"), "Duration": t.duration.map(br),
                         "Volume (mi)": (t.volume / 1e6).map(lambda v: br(v, 2)), "Taxa negócio": [taxa_txt(i, v) for i, v in zip(t.indexador, t.taxa)],
                         "Indexador": t.indexador, "Spread over": t.spread.map(lambda v: br(v, 2, True)),
                         "Taxa ANBIMA": [taxa_txt(i, v) for i, v in zip(t.indexador, t.taxa_anbima)],
                         "Empresa": t.empresa.astype(str).str.title().str.slice(0, 22)})


# ----------------------------------------------------------------- PDF
def pdf(arq, dia, resumo_txt, res, secoes, rodape, top10):
    A4 = (8.27, 11.69)
    with PdfPages(arq) as p:
        fig = plt.figure(figsize=A4)
        fig.text(.06, .95, "Resumo de trading de crédito", fontsize=20, fontweight="bold", color=NAVY)
        fig.text(.06, .925, f"Negócios de balcão da B3 em {dia:%d/%m/%Y}", fontsize=10, color=CINZA)
        fig.add_artist(plt.Line2D([.06, .94], [.915, .915], color=LARANJA, lw=1.5))
        fig.text(.06, .89, "\n".join(textwrap.wrap(resumo_txt, 92)), fontsize=10, va="top", color=NAVY)
        ax = fig.add_axes([.06, .62, .88, .2])
        ax.axis("off")
        tb = ax.table(cellText=res.values, colLabels=res.columns, cellLoc="center", bbox=[0, 0, 1, 1])
        tb.auto_set_font_size(False)
        tb.set_fontsize(9)
        for (i, j), c in tb.get_celld().items():
            c.set_edgecolor("white")
            c.set_facecolor(NAVY if i == 0 else CLARO if i % 2 == 0 else "white")
            if i == 0:
                c.get_text().set_color("white")
                c.get_text().set_fontweight("bold")
        fig.text(.06, .57, "Maiores negócios do dia", fontsize=12, fontweight="bold", color=NAVY)
        ax = fig.add_axes([.06, .2, .88, .35])
        ax.axis("off")
        tb = ax.table(cellText=top10.values, colLabels=top10.columns, cellLoc="center", bbox=[0, 0, 1, 1])
        tb.auto_set_font_size(False)
        tb.set_fontsize(7.5)
        for (i, j), c in tb.get_celld().items():
            c.set_edgecolor("white")
            c.set_facecolor(NAVY if i == 0 else CLARO if i % 2 == 0 else "white")
            if i == 0:
                c.get_text().set_color("white")
                c.get_text().set_fontweight("bold")
        fig.text(.06, .05, "\n".join(textwrap.wrap(rodape, 120)), fontsize=7, color=CINZA)
        p.savefig(fig)
        plt.close(fig)
        for nome, s in secoes.items():
            fig = plt.figure(figsize=A4)
            fig.text(.06, .955, nome, fontsize=16, fontweight="bold", color=NAVY)
            fig.add_artist(plt.Line2D([.06, .94], [.945, .945], color=LARANJA, lw=1.5))
            for k, (rot, v) in enumerate(s["d"]["kpi"]):
                fig.text(.06 + .22 * k, .925, rot, fontsize=7.5, color=CINZA)
                fig.text(.06 + .22 * k, .908, v, fontsize=8.5, fontweight="bold", color=NAVY)
            txt = "\n\n".join("\n".join(textwrap.wrap(t, 112)) for t in s["d"]["texto"])
            fig.text(.06, .885, txt, fontsize=8.5, va="top", color="#222222")
            g_dispersao(fig.add_axes([.09, .33, .84, .24]), s["g"])
            g_evolucao(fig.add_axes([.09, .05, .80, .22]), s["h"])
            p.savefig(fig)
            plt.close(fig)
            t = s["t"]
            for i0 in range(0, len(t), 42):
                fig = plt.figure(figsize=A4)
                fig.text(.04, .965, f"{nome} - negócios de R$ 1 mi ou mais ({len(t)})" + (" (cont.)" if i0 else ""), fontsize=11,
                         fontweight="bold", color=NAVY)
                pedaco = t.iloc[i0:i0 + 42]
                ax = fig.add_axes([.02, .95 - .0215 * (len(pedaco) + 1), .96, .0215 * (len(pedaco) + 1)])
                ax.axis("off")
                tb = ax.table(cellText=pedaco.values, colLabels=pedaco.columns, cellLoc="center", bbox=[0, 0, 1, 1],
                              colWidths=[.055, .085, .14, .075, .055, .065, .1, .06, .065, .1, .14])
                tb.auto_set_font_size(False)
                tb.set_fontsize(5.6)
                for (i, j), c in tb.get_celld().items():
                    c.set_edgecolor("white")
                    c.set_facecolor(NAVY if i == 0 else CLARO if i % 2 == 0 else "white")
                    if i == 0:
                        c.get_text().set_color("white")
                        c.get_text().set_fontweight("bold")
                p.savefig(fig)
                plt.close(fig)
                if not len(t):
                    break


# ----------------------------------------------------------------- HTML
CSS = """
:root{--bg:#ffffff;--fg:#1d1d1f;--sub:#6b6b6b;--navy:#1F2A4D;--acc:#EC7000;--row:#f4f4f4;--line:#e3e3e3}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15171c;--fg:#ececec;--sub:#a0a0a0;--navy:#8fa6e6;--acc:#ff9a3d;--row:#1f222a;--line:#2c3039}}
:root[data-theme="dark"]{--bg:#15171c;--fg:#ececec;--sub:#a0a0a0;--navy:#8fa6e6;--acc:#ff9a3d;--row:#1f222a;--line:#2c3039}
body{background:var(--bg);color:var(--fg);font-family:Segoe UI,Arial,sans-serif;margin:0;padding:0 16px 40px;max-width:1100px;margin:auto}
h1{color:var(--navy);margin:20px 0 2px;font-size:26px} h2{color:var(--navy);border-bottom:2px solid var(--acc);padding-bottom:4px;margin-top:36px}
.sub{color:var(--sub);font-size:13px} p{line-height:1.5;font-size:14px}
.kpi{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0} .kpi div{background:var(--row);padding:8px 12px;border-radius:6px;min-width:150px}
.kpi b{display:block;color:var(--navy);font-size:15px} .kpi span{color:var(--sub);font-size:11px}
img{max-width:100%;height:auto;background:#fff;border-radius:6px;margin:6px 0}
.tw{overflow-x:auto} table{border-collapse:collapse;font-size:12px;width:100%} th{background:#1F2A4D;color:#fff;padding:5px 7px;text-align:center;white-space:nowrap}
td{padding:4px 7px;border-bottom:1px solid var(--line);text-align:center;white-space:nowrap} tr:nth-child(even) td{background:var(--row)}
"""


def html(dia, resumo_txt, res, secoes, rodape, top10, imagens="base64", max_linhas=None):
    h = [f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>Trading de crédito</title><style>{CSS}</style></head><body>",
         f"<h1>Resumo de trading de crédito</h1><div class='sub'>Negócios de balcão da B3 em {dia:%d/%m/%Y}</div>",
         f"<p>{resumo_txt}</p><div class='tw'>{res.to_html(index=False, border=0)}</div>",
         f"<h3>Maiores negócios do dia</h3><div class='tw'>{top10.to_html(index=False, border=0)}</div>"]
    for nome, s in secoes.items():
        h.append(f"<h2>{nome}</h2><div class='kpi'>" + "".join(f"<div><span>{r}</span><b>{v}</b></div>" for r, v in s["d"]["kpi"]) + "</div>")
        h += [f"<p>{t}</p>" for t in s["d"]["texto"]]
        for k in ("img1", "img2"):
            src = f"cid:{GRUPOS.index(nome)}_{k}" if imagens == "cid" else f"data:image/png;base64,{base64.b64encode(s[k]).decode()}"
            h.append(f"<img alt='gráfico' width='700' src='{src}'>")
        t = s["t"] if max_linhas is None else s["t"].head(max_linhas)
        h.append(f"<h3 class='sub'>Negócios de R$ 1 mi ou mais ({len(s['t'])}{'' if max_linhas is None else f', os {len(t)} maiores'})</h3>"
                 f"<div class='tw'>{t.to_html(index=False, border=0)}</div>")
    h.append(f"<p class='sub'>{rodape}</p></body></html>")
    return "".join(h)


def rascunho_outlook(arq_pdf, assunto, corpo_html, secoes):
    """Rascunho no Outlook com as imagens como anexos embutidos (cid), que aparecem no corpo em qualquer cliente de e-mail."""
    import win32com.client
    m = win32com.client.Dispatch("Outlook.Application").CreateItem(0)
    m.Subject = assunto
    for nome, s in secoes.items():
        for k in ("img1", "img2"):
            f = PASTA / f"{GRUPOS.index(nome)}_{k}.png"
            f.write_bytes(s[k])
            a = m.Attachments.Add(str(f))
            a.PropertyAccessor.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001F", f"{GRUPOS.index(nome)}_{k}")
    m.Attachments.Add(str(Path(arq_pdf).resolve()))
    m.HTMLBody = corpo_html
    m.Save()


# ----------------------------------------------------------------- main
def main():
    agora = pd.Timestamp.now()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        dia = pd.Timestamp(args[0])
    else:
        dia = agora.normalize() if agora.hour >= 20 else agora.normalize() - pd.offsets.BDay(1)
        while not len(negocios(dia)):                                     # feriado: volta até achar negócios
            dia -= pd.offsets.BDay(1)
    print(f"dia {dia:%d/%m/%Y}: baixando negócios, cadastro, ANBIMA, Tesouro e CDI...", flush=True)
    cad, (anb, d_anb), cur, cdi = cadastro(), anbima(dia), curvas(dia), cdi_aa()
    x = enriquece(negocios(dia), cad, anb, cur, cdi)
    hist_dias = [d for d in pd.bdate_range(dia - pd.Timedelta(days=60), dia)][-DIAS_HIST - 8:]
    hist = []
    for d in hist_dias:
        n = negocios(d)
        if len(n):
            n = n.join(cad.drop_duplicates("codigo").set_index("codigo")[["incent"]], on="codigo")
            n["grupo"] = [grupo(t, i == "True", e) for t, i, e in zip(n.tipo, n.incent, n.emissor)]
            hist.append(n[n.grupo.notna()].groupby("grupo").agg(negocios=("id", "count"), volume=("volume", "sum")).assign(data=d))
    hist = pd.concat(hist).reset_index()
    vol, ops = x.volume.sum(), len(x)
    v = x.groupby("grupo").volume.sum()
    sv = lambda k: mm(v.get(k, 0))
    resumo_txt = (f"Volume negociado no dia de {mm(vol)} em {br(ops, 0)} operações: debêntures {mm(v.get(GRUPOS[0], 0) + v.get(GRUPOS[1], 0))} "
                  f"(não isentas {sv(GRUPOS[0])} e isentas {sv(GRUPOS[1])}), bancários {sv('Bancários')} e estruturados {sv('Estruturados')}.")
    res = x.groupby("grupo").agg(Volume=("volume", "sum"), Operações=("id", "count")).reindex(GRUPOS).fillna(0)
    res["Ticket médio"] = res.Volume / res.Operações.replace(0, np.nan)
    res["Participação"] = res.Volume / vol * 100
    res = pd.DataFrame({"Grupo": res.index, "Volume": res.Volume.map(mm), "Operações": res.Operações.map(lambda o: br(o, 0)),
                        "Ticket médio": res["Ticket médio"].map(mm), "Participação": res.Participação.map(lambda p: br(p, 1, True))})
    t10 = x.nlargest(10, "volume")
    top10 = pd.DataFrame({"Ativo": t10.codigo, "Grupo": t10.grupo, "Emissor": t10.emissor.str.title().str.slice(0, 30),
                          "Volume": t10.volume.map(mm), "Taxa": [taxa_txt(i, v) for i, v in zip(t10.indexador, t10.taxa)],
                          "Hora": t10.hora})
    secoes = {}
    for nome in GRUPOS:
        g = x[x.grupo == nome]
        h = hist[hist.grupo == nome].set_index("data")[["negocios", "volume"]].tail(DIAS_HIST)
        secoes[nome] = {"g": g, "h": h, "d": destaques(g, nome), "t": tabela(g)}
        secoes[nome]["img1"] = png(g_dispersao, g)
        secoes[nome]["img2"] = png(g_evolucao, h)
    rodape = (f"Fontes: B3 (negócios de balcão e cadastro), ANBIMA (taxa indicativa e duration de debêntures"
              f"{f', arquivo de {d_anb:%d/%m/%Y}' if d_anb is not None else ''}), Tesouro Direto (curvas para o spread de IPCA+ e pré), "
              f"Banco Central (CDI {br(cdi, 2)}% a.a.). Spread: CDI+ = taxa; % CDI = (taxa/100 - 1) x CDI; IPCA+ e pré = taxa menos a curva "
              f"do Tesouro na duration. Duration: ANBIMA quando há; senão aproximada pelo prazo. Destaques consideram ativos com "
              f"{mm(MIN_VOL)} ou mais no dia. Cotas de FII e Fiagro fora. Devedor de CRI/CRA só pela API da ANBIMA.")
    PASTA.mkdir(exist_ok=True)
    base = PASTA / f"trading_credito_{dia:%Y%m%d}"
    pdf(f"{base}.pdf", dia, resumo_txt, res, secoes, rodape, top10)
    Path(f"{base}.html").write_text(html(dia, resumo_txt, res, secoes, rodape, top10), encoding="utf-8")
    if "--outlook" in sys.argv:
        rascunho_outlook(f"{base}.pdf", f"Resumo de trading de crédito - {dia:%d/%m/%Y}",
                         html(dia, resumo_txt, res, secoes, rodape, top10, imagens="cid"), secoes)
        print("rascunho criado no Outlook (Rascunhos)")
    print(resumo_txt)
    for nome, s in secoes.items():
        print(f"\n== {nome}\n" + "\n".join(s["d"]["texto"]))
    print(f"\nGerado: {base}.pdf e {base}.html")


if __name__ == "__main__":
    main()
