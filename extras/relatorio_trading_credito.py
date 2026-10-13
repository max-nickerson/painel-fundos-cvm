"""
Resumo de trading de crédito privado (negócios de balcão da B3) -> PDF + HTML (pronto para e-mail).
  Fontes grátis: B3 (negócio a negócio e cadastro), ANBIMA (taxa indicativa e duration das debêntures),
  Tesouro Direto (curvas pré e IPCA+ para o spread), Banco Central (CDI).
  Dia: hoje se já passou das 20h e houver negócios; senão o último dia útil com negócios (D-1).
  Grupos: debêntures não isentas, debêntures isentas (Lei 12.431), bancários (LF, LFSN, LFSC, LIG) e
          estruturados (CRI, CRA, cotas de FIDC, CDCA, CPR e notas comerciais). Cotas de FII/Fiagro ficam fora.
Layout: HTML feito de tabelas com estilos inline (o que o Outlook respeita); o PDF é o mesmo HTML impresso pelo Edge/Chrome.
      O HTML (para e-mail) traz os 25 maiores negócios de cada grupo; o PDF traz todos os de R$ 1 mi ou mais.
Uso:  python relatorio_trading_credito.py [AAAA-MM-DD] [--outlook]
      --outlook: cria um RASCUNHO no Outlook (Windows) com o HTML no corpo, gráficos embutidos e o PDF anexo (não envia).
"""
import base64
import io
import os
import sys
import time
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import requests

matplotlib.use("Agg")
matplotlib.rcParams["text.parse_math"] = False                           # "R$" não é fórmula
import matplotlib.pyplot as plt

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
    """CDI anualizado do último dia (Banco Central); se a API falhar, usa o último valor salvo."""
    f = CACHE / "cdi.txt"
    hoje = pd.Timestamp.today()
    for u in ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados/ultimos/5?formato=json",
              f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial={hoje - pd.Timedelta(days=15):%d/%m/%Y}"):
        try:
            v = ((1 + float(get(u).json()[-1]["valor"]) / 100) ** 252 - 1) * 100
            f.write_text(str(v))
            return v
        except (requests.RequestException, ValueError, KeyError, IndexError):
            time.sleep(2)
    return float(f.read_text()) if f.exists() else 14.9


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


# ----------------------------------------------------------------- números e texto
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


def nome(e, n=34):
    e = str(e).title().replace(" S.A.", " S.A.").replace(" S/A", " S/A")
    return e if len(e) <= n else e[:n - 1].rstrip() + "…"


def por_ativo(g):
    w = g.assign(tv=g.taxa * g.volume, sv=g.spread * g.volume, vt=g.volume.where(g.taxa.notna()), vs=g.volume.where(g.spread.notna()))
    a = w.groupby("codigo").agg(emissor=("emissor", "first"), indexador=("indexador", "first"), volume=("volume", "sum"),
                                negocios=("id", "count"), duration=("duration", "first"), taxa_anbima=("taxa_anbima", "first"),
                                tv=("tv", "sum"), sv=("sv", "sum"), vt=("vt", "sum"), vs=("vs", "sum"))
    a["taxa"] = (a.tv / a.vt).where(a.vt > 0)
    a["spread"] = (a.sv / a.vs).where(a.vs > 0)
    a["dif_bps"] = (a.taxa - a.taxa_anbima) * 100
    return a


def destaques(g):
    """Números de cada grupo, já prontos para o layout."""
    d = {"vol": g.volume.sum(), "n": len(g)}
    if not len(g):
        return d
    a = por_ativo(g)
    d["ticket"] = d["vol"] / d["n"]
    d["top_ativo"] = (a.volume.idxmax(), a.volume.max())
    em = g.groupby("emissor").volume.sum().sort_values(ascending=False)
    d["emissores"] = list(em.head(3).items())
    dd = g.dropna(subset=["duration"])
    d["dur"] = np.average(dd.duration, weights=dd.volume) if len(dd) and dd.volume.sum() > 0 else np.nan
    grandes = a[(a.volume >= MIN_VOL) & a.duration.notna()]
    d["dur_dest"] = (grandes.duration.idxmax(), grandes.duration.max(), grandes.volume[grandes.duration.idxmax()]) if len(grandes) else None
    d["ind"] = list((g.groupby("indexador").volume.sum() / d["vol"] * 100).sort_values(ascending=False).items())
    s = a[(a.volume >= MIN_VOL) & a.spread.notna()]
    item = lambda k: (k, taxa_txt(s.indexador[k], s.taxa[k]), s.spread[k], s.volume[k])
    d["maiores"] = [item(k) for k in s.spread.nlargest(2).index]
    d["menores"] = [item(k) for k in s.spread.nsmallest(2).index]
    b = s[s.dif_bps.notna()]
    itb = lambda k: (k, taxa_txt(b.indexador[k], b.taxa[k]), taxa_txt(b.indexador[k], b.taxa_anbima[k]), b.dif_bps[k], b.volume[k])
    d["acima"] = [itb(k) for k in b.dif_bps.nlargest(2).index if b.dif_bps[k] > 0]
    d["abaixo"] = [itb(k) for k in b.dif_bps.nsmallest(2).index if b.dif_bps[k] < 0]
    d["sem_taxa"] = g.taxa.isna().all()
    return d


# ----------------------------------------------------------------- gráficos (mesma paleta do HTML)
COR = {"Debêntures não isentas": "#1F2A4D", "Debêntures isentas": "#EC7000", "Bancários": "#3E7CB1", "Estruturados": "#5E8C6A"}
TXT, SUB, LINHA, ZEBRA, FUNDO = "#1E2533", "#6B7280", "#E3E7EE", "#F6F8FB", "#EEF1F5"
plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "axes.edgecolor": "#C9CFD9", "axes.labelcolor": SUB,
                     "xtick.color": SUB, "ytick.color": SUB, "axes.titleweight": "bold"})


def g_dispersao(ax, g, cor):
    t = g.dropna(subset=["taxa", "duration"])
    if not len(t):
        ax.axis("off")
        ax.text(.5, .5, "Negócios registrados sem taxa: sem gráfico de taxa x duration", ha="center", va="center", color=SUB, fontsize=10)
        return
    ind = t.groupby("indexador").volume.sum().idxmax()
    t = t[t.indexador == ind].nlargest(40, "volume")
    ax.scatter(t.duration, t.taxa, s=30 + 900 * t.volume / t.volume.max(), color=cor, alpha=.35, edgecolor=cor, linewidth=1)
    for _, r in t.drop_duplicates("codigo").nlargest(7, "volume").iterrows():
        ax.annotate(r.codigo, (r.duration, r.taxa), fontsize=7.5, xytext=(6, 5), textcoords="offset points", color=TXT, fontweight="bold")
    ax.set_xlabel("Duration (anos)", fontsize=8.5)
    ax.set_ylabel({"CDI+": "Spread sobre o CDI (%)", "% CDI": "% do CDI", "IPCA+": "Taxa IPCA+ (%)", "PRE": "Taxa pré (%)"}.get(ind, "Taxa"), fontsize=8.5)
    ax.grid(color=LINHA, lw=.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=8)
    ax.set_title(f"40 maiores negócios {ind}: taxa x duration (bolha = volume)", loc="left", fontsize=9.5, color=TXT, pad=10)


def g_evolucao(ax, h, cor):
    x = np.arange(len(h))
    ax2 = ax.twinx()
    cores = [cor] * (len(h) - 1) + [LARANJA if cor != LARANJA else NAVY]
    ax2.bar(x, h.volume / 1e6, color=cores, alpha=.85, width=.7, zorder=1)
    ax.plot(x, h.negocios, color=TXT, marker="o", ms=3.2, lw=1.4, zorder=3)
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)
    ax.set_ylabel("Negócios (linha)", fontsize=8.5)
    ax2.set_ylabel("Volume, R$ mi (barras)", fontsize=8.5)
    ax.set_xticks(x[::2], [d.strftime("%d/%m") for d in h.index][::2], rotation=0, fontsize=7.5)
    ax.tick_params(axis="y", labelsize=8)
    ax2.tick_params(axis="y", labelsize=8)
    ax2.grid(axis="y", color=LINHA, lw=.8)
    ax2.set_axisbelow(True)
    for a_ in (ax, ax2):
        a_.spines[["top"]].set_visible(False)
    ax.set_title(f"Últimos {len(h)} dias úteis (o dia do relatório em destaque)", loc="left", fontsize=9.5, color=TXT, pad=10)


def png(func, *args, tam=(7.4, 3.0)):
    fig, ax = plt.subplots(figsize=tam)
    func(ax, *args)
    fig.tight_layout()
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=170, facecolor="white")
    plt.close(fig)
    return b.getvalue()


# ----------------------------------------------------------------- HTML (tabelas e estilos inline: funciona no Outlook)
F = "font-family:'Segoe UI',Arial,Helvetica,sans-serif;"
L = 720                                                                    # largura do corpo (px)


def celula(txt, estilo="", **attr):
    a = "".join(f' {k}="{v}"' for k, v in attr.items())
    return f'<td{a} style="{F}{estilo}">{txt}</td>'


def tabela_html(cab, linhas, alinhar, larguras=None, cores_linha=None, fonte=11):
    """Tabela zebrada; alinhar: 'l', 'c' ou 'r' por coluna; cores_linha: {(i, j): cor do texto}."""
    al = {"l": "left", "c": "center", "r": "right"}
    h = [f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;width:100%">'
         '<thead><tr>']
    for j, c in enumerate(cab):
        w = f' width="{larguras[j]}"' if larguras else ""
        h.append(f'<th{w} bgcolor="{NAVY}" style="{F}background:{NAVY};color:#FFFFFF;font-size:9.5px;font-weight:600;letter-spacing:.4px;'
                 f'text-transform:uppercase;padding:7px 8px;text-align:{al[alinhar[j]]};white-space:nowrap">{c}</th>')
    h.append("</tr></thead><tbody>")
    for i, lin in enumerate(linhas):
        fundo = ZEBRA if i % 2 else "#FFFFFF"
        h.append(f'<tr bgcolor="{fundo}">')
        for j, v in enumerate(lin):
            cor = (cores_linha or {}).get((i, j), TXT)
            peso = "600" if j == 0 or cor != TXT else "400"
            h.append(f'<td style="{F}font-size:{fonte}px;color:{cor};font-weight:{peso};padding:6px 8px;border-bottom:1px solid {LINHA};'
                     f'text-align:{al[alinhar[j]]};white-space:nowrap;font-variant-numeric:tabular-nums">{v}</td>')
        h.append("</tr>")
    h.append("</tbody></table>")
    return "".join(h)


def barra_empilhada(partes, altura=12):
    """partes: [(rótulo, %, cor)] -> barra horizontal + legenda."""
    cel = "".join(f'<td width="{max(p, .5):.1f}%" height="{altura}" bgcolor="{c}" style="background:{c};font-size:1px;line-height:1px">&nbsp;</td>'
                  for _, p, c in partes if p > 0)
    leg = "".join(f'<td style="{F}font-size:11px;color:{TXT};padding:6px 14px 0 0;white-space:nowrap">'
                  f'<span style="display:inline-block;width:9px;height:9px;background:{c};margin-right:5px"></span>{r} '
                  f'<b>{br(p, 0)}%</b></td>' for r, p, c in partes if p >= .5)
    return (f'<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{cel}</tr></table>'
            f'<table cellpadding="0" cellspacing="0" border="0"><tr>{leg}</tr></table>')


def kpis(itens, cor):
    w = int(100 / len(itens))
    cel = "".join(f'<td width="{w}%" valign="top" style="padding:0 6px 0 0"><table width="100%" cellpadding="0" cellspacing="0" border="0">'
                  f'<tr><td bgcolor="{ZEBRA}" style="{F}background:{ZEBRA};border-top:3px solid {cor};padding:10px 12px">'
                  f'<div style="{F}font-size:9.5px;color:{SUB};text-transform:uppercase;letter-spacing:.6px">{r}</div>'
                  f'<div style="{F}font-size:{17 if len(v) < 16 else 13}px;color:{NAVY};font-weight:700;padding-top:3px">{v}</div>'
                  + (f'<div style="{F}font-size:10.5px;color:{SUB};padding-top:2px">{x}</div>' if x else "")
                  + '</td></tr></table></td>' for r, v, x in itens)
    return f'<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{cel}</tr></table>'


def titulo_bloco(t):
    return (f'<div style="{F}font-size:10.5px;font-weight:700;color:{SUB};text-transform:uppercase;letter-spacing:.8px;'
            f'padding:18px 0 8px 0;border-bottom:1px solid {LINHA};margin-bottom:10px">{t}</div>')


def linha_def(rot, val):
    return (f'<tr><td width="150" valign="top" style="{F}font-size:11.5px;color:{SUB};padding:8px 10px 8px 0;border-bottom:1px solid {LINHA}">{rot}</td>'
            f'<td valign="top" style="{F}font-size:12.5px;color:{TXT};padding:8px 0;border-bottom:1px solid {LINHA};line-height:1.45">{val}</td></tr>')


def selo(txt, cor, fundo):
    return (f'<span style="{F}display:inline-block;font-size:10.5px;font-weight:700;color:{cor};background:{fundo};'
            f'padding:2px 7px;border-radius:9px;white-space:nowrap">{txt}</span>')


def cartao(titulo, itens, cor):
    corpo = "".join(f'<div style="{F}font-size:12px;color:{TXT};padding:5px 0;border-top:1px solid {LINHA}">{x}</div>' for x in itens) \
        or f'<div style="{F}font-size:12px;color:{SUB};padding:5px 0">sem ativos com {mm(MIN_VOL)}+</div>'
    return (f'<td width="50%" valign="top" style="padding:0 6px 10px 0"><table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="{F}border:1px solid {LINHA};border-left:4px solid {cor};padding:9px 12px">'
            f'<div style="{F}font-size:10px;font-weight:700;color:{cor};text-transform:uppercase;letter-spacing:.6px;padding-bottom:4px">{titulo}</div>'
            f'{corpo}</td></tr></table></td>')


def secao(nome_g, s, imagens, max_linhas, idx):
    d, cor = s["d"], COR[nome_g]
    h = [f'<tr><td style="padding:26px 28px 0 28px;page-break-before:always;break-before:page">'
         f'<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
         f'<td width="6" bgcolor="{cor}" style="background:{cor}">&nbsp;</td>'
         f'<td style="{F}padding:2px 0 2px 12px"><div style="{F}font-size:21px;font-weight:700;color:{NAVY}">{nome_g}</div>'
         f'<div style="{F}font-size:12px;color:{SUB}">{mm(d["vol"])} em {br(d["n"], 0)} negócios'
         + (f' &middot; ticket médio {mm(d["ticket"])}' if d["n"] else "") + '</div></td></tr></table>']
    if not d["n"]:
        h.append(f'<p style="{F}color:{SUB}">Sem negócios no dia.</p></td></tr>')
        return "".join(h)
    ta, va = d["top_ativo"]
    em0 = d["emissores"][0]
    h.append('<div style="height:14px"></div>' + kpis([("Volume", mm(d["vol"]), None), ("Operações", br(d["n"], 0), f'ticket {mm(d["ticket"])}'),
                                                       ("Maior ativo", ta, mm(va)), ("Maior emissor", nome(em0[0], 22), mm(em0[1]))], cor))
    # destaques
    h.append(titulo_bloco("Destaques"))
    mx = d["emissores"][0][1]
    emiss = "".join(f'<tr><td style="{F}font-size:12px;color:{TXT};padding:2px 10px 2px 0;white-space:nowrap">{nome(e, 38)}</td>'
                    f'<td width="160" style="padding:2px 8px 2px 0"><table width="{max(int(150 * v / mx), 3)}" cellpadding="0" cellspacing="0" border="0">'
                    f'<tr><td height="9" bgcolor="{cor}" style="background:{cor};font-size:1px;line-height:1px">&nbsp;</td></tr></table></td>'
                    f'<td style="{F}font-size:12px;color:{NAVY};font-weight:700;white-space:nowrap">{mm(v)}</td></tr>' for e, v in d["emissores"])
    dur = f'<b style="color:{NAVY}">{br(d["dur"])} anos</b>' + (
        f' &nbsp;<span style="color:{SUB}">maior duration negociada: <b style="color:{TXT}">{d["dur_dest"][0]}</b> '
        f'({br(d["dur_dest"][1])} anos, {mm(d["dur_dest"][2])})</span>' if d["dur_dest"] else "")
    paleta = [NAVY, LARANJA, "#3E7CB1", "#5E8C6A", "#9AA3B2", "#C9CFD9", "#B5835A"]
    ind = barra_empilhada([(k, p, paleta[i % len(paleta)]) for i, (k, p) in enumerate(d["ind"])])
    h.append(f'<table width="100%" cellpadding="0" cellspacing="0" border="0">'
             + linha_def("Emissores líderes", f'<table cellpadding="0" cellspacing="0" border="0">{emiss}</table>')
             + linha_def("Duration média ponderada", dur) + linha_def("Indexadores (volume)", ind) + "</table>")
    # atípicos
    h.append(titulo_bloco(f"Atípicos (ativos com {mm(MIN_VOL)} ou mais no dia)"))
    if d["sem_taxa"]:
        h.append(f'<p style="{F}font-size:12px;color:{SUB};margin:0">Os negócios deste grupo são registrados na B3 só com PU, sem taxa: '
                 f'não há spread nem comparação com a ANBIMA.</p>')
    else:
        sp = lambda r: f'<b>{r[0]}</b> &nbsp;{r[1]} &nbsp;{selo("spread " + br(r[2], 2, True), NAVY, "#E6EBF3")} <span style="color:{SUB}">{mm(r[3])}</span>'
        an = lambda r, c, f_: (f'<b>{r[0]}</b> &nbsp;{r[1]} <span style="color:{SUB}">vs ANBIMA {r[2]}</span> '
                               f'{selo(("+" if r[3] > 0 else "") + br(r[3], 0) + " bps", c, f_)}')
        h.append('<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
                 + cartao("Maiores spreads", [sp(r) for r in d["maiores"]], "#B23A3A")
                 + cartao("Menores spreads", [sp(r) for r in d["menores"]], "#2E7D4F") + "</tr><tr>"
                 + cartao("Acima da ANBIMA (vendedor pagou mais taxa)", [an(r, "#B23A3A", "#FBE9E9") for r in d["acima"]], "#B23A3A")
                 + cartao("Abaixo da ANBIMA (comprador pagou mais preço)", [an(r, "#2E7D4F", "#E7F4EC") for r in d["abaixo"]], "#2E7D4F")
                 + "</tr></table>")
    # gráficos
    h.append(titulo_bloco("Gráficos"))
    for k in ("img1", "img2"):
        src = f"cid:g{idx}_{k}" if imagens == "cid" else f"data:image/png;base64,{base64.b64encode(s[k]).decode()}"
        h.append(f'<img src="{src}" width="{L - 56}" alt="gráfico" style="display:block;width:{L - 56}px;max-width:100%;height:auto;'
                 f'border:1px solid {LINHA};margin-bottom:10px">')
    # tabela
    t = s["t"] if max_linhas is None else s["t"].head(max_linhas)
    sub = f"{len(s['t'])} negócios" + ("" if max_linhas is None or len(s["t"]) <= max_linhas else f", os {len(t)} maiores aqui; todos no PDF")
    h.append('<div style="page-break-before:always;break-before:page"></div>' + titulo_bloco(f"Negócios de {mm(MIN_VOL)} ou mais ({sub})"))
    cores = {}
    for i, v in enumerate(t["Dif. ANBIMA"]):
        if v not in ("-", "", "0 bps"):
            cores[(i, 10)] = "#B23A3A" if not v.startswith("-") else "#2E7D4F"
    h.append(tabela_html(list(t.columns), t.values.tolist(), "clllrrlcrrr", cores_linha=cores, fonte=10.5))
    h.append("</td></tr>")
    return "".join(h)


def tabela(g):
    t = g[g.volume >= MIN_VOL].sort_values("volume", ascending=False)
    dif = (t.taxa - t.taxa_anbima) * 100
    return pd.DataFrame({"Hora": t.hora.str.slice(0, 5), "Ativo": t.codigo, "Emissor": t.emissor.map(lambda e: nome(e, 22)),
                         "Vencimento": t.venc.dt.strftime("%d/%m/%Y").fillna("-"), "Indexador": t.indexador,
                         "Duration": t.duration.map(br), "Volume (mi)": (t.volume / 1e6).map(lambda v: br(v, 1)),
                         "Taxa": [taxa_txt(i, v) for i, v in zip(t.indexador, t.taxa)],
                         "Spread": t.spread.map(lambda v: br(v, 2, True)),
                         "ANBIMA": [taxa_txt(i, v) for i, v in zip(t.indexador, t.taxa_anbima)],
                         "Dif. ANBIMA": dif.round().map(lambda v: "-" if v != v else "0 bps" if v == 0 else ("+" if v > 0 else "") + br(v, 0) + " bps")})


def leitura(d):
    """Uma frase por grupo para a capa."""
    if not d["n"]:
        return "sem negócios no dia"
    e = d["emissores"][0]
    t = f'{mm(d["vol"])} em {br(d["n"], 0)} negócios; <b>{nome(e[0], 30)}</b> liderou ({mm(e[1])})'
    desv = (d.get("acima") or []) + (d.get("abaixo") or [])
    if desv:
        r = max(desv, key=lambda r: abs(r[3]))
        t += f'; maior desvio da ANBIMA: <b>{r[0]}</b> {r[1]} vs {r[2]} ({("+" if r[3] > 0 else "") + br(r[3], 0)} bps)'
    elif d.get("maiores"):
        r = d["maiores"][0]
        t += f'; maior spread: <b>{r[0]}</b> {r[1]}'
    elif d.get("sem_taxa"):
        t += "; negócios registrados sem taxa"
    return t + "."


def html(dia, res, top10, secoes, rodape, total, imagens="base64", max_linhas=25):
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    vol, ops, n_emis = total
    capa = [
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>Resumo de trading de crédito</title>"
        "<style>@page{size:A4;margin:8mm}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}"
        "thead{display:table-header-group}tr{page-break-inside:avoid;break-inside:avoid}img{break-inside:avoid}"
        f"@media print{{body,table[bgcolor='{FUNDO}']{{background:#FFFFFF!important}}td[style*='padding:18px 6px']{{padding:0!important}}}}</style></head>",
        f'<body style="margin:0;padding:0;background:{FUNDO}"><table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{FUNDO}">'
        f'<tr><td align="center" style="padding:18px 6px">'
        f'<table width="{L}" cellpadding="0" cellspacing="0" border="0" bgcolor="#FFFFFF" style="width:{L}px;background:#FFFFFF">',
        # cabeçalho
        f'<tr><td bgcolor="{NAVY}" style="background:{NAVY};padding:24px 28px 20px 28px">'
        f'<div style="{F}font-size:10.5px;font-weight:700;color:{LARANJA};letter-spacing:1.6px;text-transform:uppercase">Crédito privado &middot; balcão B3</div>'
        f'<div style="{F}font-size:26px;font-weight:700;color:#FFFFFF;padding-top:6px">Resumo de trading de crédito</div>'
        f'<div style="{F}font-size:13px;color:#B9C3D6;padding-top:4px">Negócios de {dias[dia.dayofweek]}, {dia:%d/%m/%Y}</div></td></tr>'
        f'<tr><td height="4" bgcolor="{LARANJA}" style="background:{LARANJA};font-size:1px;line-height:1px">&nbsp;</td></tr>',
        f'<tr><td style="padding:22px 28px 0 28px">'
        + kpis([("Volume negociado", mm(vol), None), ("Operações", br(ops, 0), None), ("Ticket médio", mm(vol / ops), None),
                ("Emissores", br(n_emis, 0), None)], LARANJA),
    ]
    # participação por grupo
    capa.append(titulo_bloco("Volume por grupo"))
    capa.append(barra_empilhada([(g, float(r.part), COR[g]) for g, r in res.iterrows()], altura=16))
    linhas = [[g, mm(r.vol), br(r.ops, 0), mm(r.ticket), br(r.part, 1, True)] for g, r in res.iterrows()]
    capa.append('<div style="height:12px"></div>' + tabela_html(["Grupo", "Volume", "Operações", "Ticket médio", "Participação"], linhas, "lrrrr",
                                                                fonte=12))
    capa.append(titulo_bloco("Leitura rápida"))
    capa.append('<table width="100%" cellpadding="0" cellspacing="0" border="0">' + "".join(
        linha_def(f'<span style="display:inline-block;width:9px;height:9px;background:{COR[g]};margin-right:6px"></span>'
                  f'<b style="color:{TXT}">{g}</b>', leitura(s["d"])) for g, s in secoes.items()) + "</table>")
    capa.append(titulo_bloco("Maiores negócios do dia"))
    capa.append(tabela_html(list(top10.columns), top10.values.tolist(), "llllrlr", fonte=11))
    capa.append("</td></tr>")
    corpo = [secao(g, s, imagens, max_linhas, i) for i, (g, s) in enumerate(secoes.items())]
    fim = (f'<tr><td style="padding:24px 28px 26px 28px"><div style="{F}font-size:10px;color:{SUB};line-height:1.5;border-top:1px solid {LINHA};'
           f'padding-top:12px">{rodape}</div></td></tr></table></td></tr></table></body></html>')
    return "".join(capa + corpo) + fim


def imprime_pdf(arq_html, arq_pdf):
    """PDF a partir do próprio HTML, pelo Edge ou Chrome em modo headless (já instalados no Windows)."""
    import shutil
    import subprocess
    cands = [shutil.which("msedge"), shutil.which("chrome"), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe"]
    exe = next((c for c in cands if c and Path(c).exists()), None)
    if not exe:
        print("Edge/Chrome não encontrado: PDF não gerado (o HTML está pronto)")
        return False
    import tempfile
    Path(arq_pdf).unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:                             # pasta e perfil próprios: não conflita com o navegador aberto
        src, out = Path(tmp) / "r.html", Path(tmp) / "r.pdf"
        shutil.copy(arq_html, src)
        subprocess.run([exe, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={Path(tmp) / 'perfil'}",
                        f"--print-to-pdf={out}", src.as_uri()], check=False, timeout=240, capture_output=True)
        for _ in range(20):                                                # o navegador pode terminar de gravar logo depois
            if out.exists() and out.stat().st_size > 0:
                break
            time.sleep(1)
        if out.exists():
            shutil.copy(out, arq_pdf)
    return Path(arq_pdf).exists()


def rascunho_outlook(arq_pdf, assunto, corpo_html, secoes):
    """Rascunho no Outlook com as imagens como anexos embutidos (cid), que aparecem no corpo em qualquer cliente de e-mail."""
    import win32com.client
    m = win32com.client.Dispatch("Outlook.Application").CreateItem(0)
    m.Subject = assunto
    for i, s in enumerate(secoes.values()):
        for k in ("img1", "img2"):
            f = PASTA / f"g{i}_{k}.png"
            f.write_bytes(s[k])
            a = m.Attachments.Add(str(f))
            a.PropertyAccessor.SetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001F", f"g{i}_{k}")
    if Path(arq_pdf).exists():
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
    hist = []
    for d in list(pd.bdate_range(dia - pd.Timedelta(days=60), dia))[-DIAS_HIST - 8:]:
        n = negocios(d)
        if len(n):
            n = n.join(cad.drop_duplicates("codigo").set_index("codigo")[["incent"]], on="codigo")
            n["grupo"] = [grupo(t, i == "True", e) for t, i, e in zip(n.tipo, n.incent, n.emissor)]
            hist.append(n[n.grupo.notna()].groupby("grupo").agg(negocios=("id", "count"), volume=("volume", "sum")).assign(data=d))
    hist = pd.concat(hist).reset_index()
    vol, ops = x.volume.sum(), len(x)
    res = x.groupby("grupo").agg(vol=("volume", "sum"), ops=("id", "count")).reindex(GRUPOS).fillna(0)
    res["ticket"] = res.vol / res.ops.replace(0, np.nan)
    res["part"] = res.vol / vol * 100
    t10 = x.nlargest(10, "volume")
    top10 = pd.DataFrame({"Ativo": t10.codigo, "Grupo": t10.grupo, "Emissor": t10.emissor.map(lambda e: nome(e, 28)),
                          "Indexador": t10.indexador, "Volume": t10.volume.map(mm),
                          "Taxa": [taxa_txt(i, v) for i, v in zip(t10.indexador, t10.taxa)], "Hora": t10.hora.str.slice(0, 5)})
    secoes = {}
    for g_ in GRUPOS:
        g = x[x.grupo == g_]
        h = hist[hist.grupo == g_].set_index("data")[["negocios", "volume"]].tail(DIAS_HIST)
        secoes[g_] = {"d": destaques(g), "t": tabela(g), "img1": png(g_dispersao, g, COR[g_]), "img2": png(g_evolucao, h, COR[g_])}
    rodape = (f"<b>Fontes:</b> B3 (negócios de balcão e cadastro de instrumentos), ANBIMA (taxa indicativa e duration de debêntures"
              f"{f', arquivo de {d_anb:%d/%m/%Y}' if d_anb is not None else ''}), Tesouro Direto (curvas pré e IPCA+), Banco Central "
              f"(CDI {br(cdi, 2)}% a.a.). <b>Spread:</b> CDI+ = taxa; % CDI = (taxa/100 &minus; 1) &times; CDI; IPCA+ e pré = taxa menos a curva "
              f"do Tesouro na mesma duration. <b>Duration:</b> ANBIMA quando há; senão aproximada pelo prazo. <b>Grupos:</b> bancários = LF, "
              f"LF subordinada, LF sênior e LIG; estruturados = CRI, CRA, cotas de FIDC, CDCA, CPR e notas comerciais; cotas de FII e "
              f"Fiagro fora. Negócios registrados sem taxa aparecem com &ldquo;-&rdquo;. Devedor de CRI/CRA só pela API da ANBIMA.")
    total = (vol, ops, x.emissor.nunique())
    PASTA.mkdir(exist_ok=True)
    base = PASTA / f"trading_credito_{dia:%Y%m%d}"
    Path(f"{base}.html").write_text(html(dia, res, top10, secoes, rodape, total), encoding="utf-8")         # e-mail: 25 por grupo
    completo = PASTA / "_completo.html"
    completo.write_text(html(dia, res, top10, secoes, rodape, total, max_linhas=None), encoding="utf-8")   # PDF: todos
    ok = imprime_pdf(completo, f"{base}.pdf")
    completo.unlink(missing_ok=True)
    if "--outlook" in sys.argv:
        rascunho_outlook(f"{base}.pdf", f"Resumo de trading de crédito - {dia:%d/%m/%Y}",
                         html(dia, res, top10, secoes, rodape, total, imagens="cid"), secoes)
        print("rascunho criado no Outlook (Rascunhos)")
    print(f"Volume {mm(vol)} em {br(ops, 0)} operações | " + " | ".join(f"{g}: {mm(r.vol)}" for g, r in res.iterrows()))
    print(f"Gerado: {base}.html" + (f" e {base}.pdf" if ok else ""))


if __name__ == "__main__":
    main()
