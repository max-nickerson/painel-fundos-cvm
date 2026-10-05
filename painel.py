"""
PAINEL DE FUNDOS - um arquivo so (dados abertos CVM + ANBIMA + Banco Central).

Como usar em qualquer computador:
  1) Instale o Python 3.11+ (python.org; no Windows marque "Add python.exe to PATH").
  2) No terminal:   pip install fastapi uvicorn pandas numpy requests pyarrow openpyxl
  3) Salve este arquivo como painel.py e rode:   python painel.py
     -> baixa e processa NOSSOS_FUNDOS + PEERS (listas abaixo, desde DESDE) e so depois abre o painel
        no navegador em http://localhost:7860 com tudo pronto.
  Excel em vez do painel:   python painel.py excel

Fontes: CVM (CDA mensal, informe diario, cadastro), ANBIMA (debentures), Banco Central (CDI). Tudo publico e gratuito.
Os dados ficam na pasta dados_painel/, ao lado deste arquivo (a 1a vez baixa ~2-3 GB da CVM; evite pasta do OneDrive).
Depois so baixa o que mudou; o painel processado do dia e reaproveitado (abre em segundos).
Arquivos mensais republicados pela CVM (fundos tem ate 3 meses para abrir a carteira toda) sao rebaixados 1x por dia.
"""
import sys
import io
import json
import os
import re
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# ------------------------------------------------------------------ CONFIGURACAO (edite aqui)
NOSSOS_FUNDOS = {               # nome curto: CNPJ (qualquer formato)
    "DUAL": "34.803.938/0001-61",
}
PEERS = {
    "AZ_ALTRO": "22.100.009/0001-07",
    "SPARTA_TOP": "14.188.162/0001-00",
    "XP_CE120": "22.003.930/0001-31",
    "CAPITANIA_P45": "20.146.294/0001-71",
    "KINEA_CP_PREV": "26.491.419/0001-87",
    "IBIUNA_CREDIT": "37.310.657/0001-65",
    "DAYCOVAL_CLASSIC": "10.783.480/0001-68",
    "BRADESCO_BONUS": "20.216.829/0001-33",
    "RIZA_LOTUS_PREV": "43.423.186/0001-02",
}
DESDE = "2019-01"               # primeiro mes de carteira/cota (CDA existe desde 2005; mais antigo = mais download na 1a vez)
# grupo economico: a CVM so informa o emissor. Regra = trecho do nome do emissor (sem acento, maiusculo) -> grupo.
# Securitizadoras (Opea, Vert, True...) ficam como estao: o devedor do lastro nao vem na CDA.
GRUPOS = {
    "LOCALIZA|UNIDAS": "Localiza", "REDE D.?OR|DOR SAO LUIZ": "Rede D'Or", "AEGEA|AGUAS DO RIO|AGUAS DO PARA|EQUIPAV|CORSAN|RIOGRANDENSE DE SANEAMENTO": "Aegea",
    "BRK AMBIENTAL": "BRK", "EQUATORIAL|CEEE": "Equatorial", "ENERGISA": "Energisa", "CEMIG": "Cemig", "COPEL": "Copel",
    "SABESP|SANEAMENTO BASICO DO ESTADO DE SAO PAULO": "Sabesp", "COPASA|SANEAMENTO DE MINAS": "Copasa", "PETROBRAS|PETROLEO BRASILEIRO": "Petrobras",
    "PRIO|PETRO RIO": "Prio", "PETRORECONCAVO": "PetroReconcavo", "COSAN|RAIZEN|RUMO|COMPASS|MOOVE": "Cosan", "VALE S": "Vale",
    "SUZANO": "Suzano", "KLABIN": "Klabin", "SENDAS|ASSAI": "Assaí", "HAPVIDA|NOTRE DAME": "Hapvida", "VAMOS|SIMPAR|JSL|MOVIDA|CS INFRA": "Simpar",
    "MILLS": "Mills", "EUROFARMA": "Eurofarma", "IOCHPE": "Iochpe-Maxion", "CCR|MOTIVA": "Motiva (CCR)", "ECORODOVIAS": "EcoRodovias",
    "ELETROBRAS|CENTRAIS ELETRICAS BRASILEIRAS|FURNAS|CHESF|ELETRONORTE": "Eletrobras", "TAESA|TRANSMISSORA ALIANCA": "Taesa",
    "ISA ENERGIA|CTEEP": "ISA Energia", "AUREN|CESP|AES BRASIL": "Auren", "NOVA TRANSPORTADORA DO SUDESTE": "NTS", "VLI ": "VLI",
    "ITAU": "Itaú", "BRADESCO": "Bradesco", "SANTANDER": "Santander", "BANCO DO BRASIL": "Banco do Brasil", "CAIXA ECONOMICA": "Caixa",
    "BTG": "BTG Pactual", "VOTORANTIM|BANCO BV": "BV", "XP ": "XP", "SAFRA": "Safra", "DAYCOVAL": "Daycoval",
    "TESOURO NACIONAL|SECRETARIA DO TESOURO": "Tesouro Nacional",
}
OUT = "lookthrough_cvm.xlsx"
WORKERS = 4

URL = "https://dados.cvm.gov.br/dados/FI/DOC"
CACHE = Path(os.environ.get("PAINEL_DADOS") or Path(__file__).resolve().parent / "dados_painel")   # pasta ao lado do .py
(CACHE / "rec").mkdir(parents=True, exist_ok=True)
VERSAO = 2                      # muda quando o recorte guarda colunas novas (forca reprocessar)
REN = {"CNPJ_FUNDO": "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO_COTA": "CNPJ_FUNDO_CLASSE_COTA",
       "NM_FUNDO_COTA": "NM_FUNDO_CLASSE_SUBCLASSE_COTA"}             # nomes antigos (ate 2022) -> novos
NUM = ["QT_POS_FINAL", "VL_CUSTO_POS_FINAL", "VL_AQUIS_NEGOC", "VL_VENDA_NEGOC", "PR_INDEXADOR_POSFX",
       "PR_CUPOM_POSFX", "PR_TAXA_PREFX"]
COLS = {"CNPJ_FUNDO_CLASSE", "DT_COMPTC", "TP_APLIC", "TP_ATIVO", "VL_MERC_POS_FINAL", "CNPJ_FUNDO_CLASSE_COTA",
        "NM_FUNDO_CLASSE_SUBCLASSE_COTA", "DS_ATIVO", "CD_ATIVO", "CD_ISIN", "TP_TITPUB", "DT_VENC", "EMISSOR",
        "CNPJ_EMISSOR", "CPF_CNPJ_EMISSOR", "DS_SWAP", "CD_SWAP", "DS_ATIVO_EXTERIOR", "CD_ATIVO_BV_MERC", "PAIS",
        "DS_INDEXADOR_POSFX", "GRAU_RISCO", "AG_RISCO", *NUM} | set(REN)
PASSIVO = r"(?i)a pagar|obriga|exigibilidade"                        # entram negativos (PL = ativos - passivos)
DERIV = r"(?i)mercado futuro|opç|swap|termo"   # derivativos vem pelo nocional: fora da soma de 100% e dos graficos
AJUSTE = "Ajuste carteira x PL"


def fmt(c):
    d = re.sub(r"\D", "", c)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def cnpj_of(x):
    if "maisretorno" in x:
        m = re.search(r"id=(\d{14})", x) or re.search(
            r"CNPJ\D{0,30}(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", requests.get(x, timeout=60, headers={"User-Agent": "Mozilla/5.0"}).text)
        x = m.group(1)
    return fmt(x)


def baixa(url):
    f = CACHE / url.rsplit("/", 1)[1]
    if not f.exists():
        tmp = f.with_suffix(f".{os.getpid()}.part")
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(tmp, "wb") as o:
                for ch in r.iter_content(1 << 20):
                    o.write(ch)
        tmp.replace(f)
    return f


def lista(pasta, padrao):        # arquivos disponiveis no diretorio da CVM
    return sorted(set(re.findall(padrao, requests.get(f"{URL}/{pasta}", timeout=60).text)))


def arquivos(tipo, desde):       # {arquivo: [meses]} - mensal recente + anual (HIST) antigo
    mens = lista(f"{tipo}/DADOS/", rf"{tipo.lower()}_fi_(\d{{6}})\.zip")
    anos = lista(f"{tipo}/DADOS/HIST/", rf"{tipo.lower()}_fi_(\d{{4}})\.zip")
    out = {}
    for a in anos:
        ms = [f"{a}-{m:02d}" for m in range(1, 13) if f"{a}-{m:02d}" >= desde and f"{a}{m:02d}" not in mens]
        if ms:
            out[f"{URL}/{tipo}/DADOS/HIST/{tipo.lower()}_fi_{a}.zip"] = ms
    for m in mens:
        if f"{m[:4]}-{m[4:]}" >= desde:
            out[f"{URL}/{tipo}/DADOS/{tipo.lower()}_fi_{m}.zip"] = [f"{m[:4]}-{m[4:]}"]
    return out


def le(z, nome, cols):
    df = pd.read_csv(z.open(nome), sep=";", encoding="latin1", dtype=str, low_memory=False, quoting=3,
                     usecols=lambda c: c in cols)                      # quoting=3: CVM nao usa aspas (e tem " soltas)
    return df.rename(columns=REN)


def marca(kind, m):
    f = CACHE / "rec" / f"{kind}_{m}.json"
    try:
        j = json.loads(f.read_text())
        return set(j["fundos"]) if isinstance(j, dict) and j.get("v") == VERSAO else None
    except (OSError, ValueError):
        return None


def fecho(lk, peers, base=()):   # tudo que os peers alcancam via cotas de fundos
    alvo, novo = set(peers) | set(base), set(peers)
    while novo:
        novo = set(lk[lk.CNPJ_FUNDO_CLASSE.isin(novo)].CNPJ_FUNDO_CLASSE_COTA) - alvo
        alvo |= novo
    return alvo


def processa_cda(url, meses, peers):
    """Le um zip CDA: links fundo->cota e PL de todos; posicoes so dos fundos ligados aos peers."""
    z = zipfile.ZipFile(baixa(url))
    nomes = z.namelist()
    if not any("_PL_" in n for n in nomes) or not any("_BLC_2_" in n for n in nomes):
        return url + " (CVM ainda publicando este mes: pulado)"
    pl = le(z, next(n for n in nomes if "_PL_" in n), {"CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO", "DT_COMPTC", "VL_PATRIM_LIQ"})
    blc = pd.concat([le(z, n, COLS).assign(conf="CONFID" in n) for n in nomes if "_BLC_" in n or "CONFID" in n],
                    ignore_index=True)
    for df in (pl, blc):
        df["mes"] = df.DT_COMPTC.str[:7]
    links = blc.dropna(subset=["CNPJ_FUNDO_CLASSE_COTA"])[["mes", "CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO_CLASSE_COTA"]]
    for m in meses:
        lk = links[links.mes == m]
        alvo = fecho(lk, peers, marca("cda", m) or ())
        b = blc[(blc.mes == m) & blc.CNPJ_FUNDO_CLASSE.isin(alvo)].copy()
        b["v"] = pd.to_numeric(b.VL_MERC_POS_FINAL, errors="coerce").fillna(0)
        b.loc[b.TP_APLIC.fillna("").str.contains(PASSIVO), "v"] *= -1

        def first(*cs):                           # primeira coluna preenchida entre as candidatas
            out = pd.Series(None, index=b.index, dtype=object)
            for c in cs:
                if c in b:
                    out = out.where(out.notna(), b[c])
            return out
        b["ativo"] = first("DS_ATIVO", "NM_FUNDO_CLASSE_SUBCLASSE_COTA", "DS_SWAP", "DS_ATIVO_EXTERIOR", "TP_TITPUB", "TP_ATIVO")
        b["emissor"] = first("EMISSOR", "CNPJ_EMISSOR", "CPF_CNPJ_EMISSOR")
        b["codigo"] = first("CD_ATIVO", "CD_ISIN", "CNPJ_FUNDO_CLASSE_COTA", "CD_SWAP", "CD_ATIVO_BV_MERC")
        b.loc[b.conf, "ativo"] = "(confidencial) " + b.loc[b.conf, "TP_APLIC"].fillna("")
        b["ativo"] = b.ativo.fillna(b.TP_ATIVO).fillna(b.TP_APLIC)
        venc = b.DT_VENC.fillna("").str[:7] if "DT_VENC" in b else ""
        b["ativo"] = (b.ativo.fillna("") + " " + b.emissor.fillna("").where(b.ativo.fillna("") != b.emissor.fillna(""), "")
                      + " " + venc).str.replace(r"\s+", " ", regex=True).str.strip()
        for c in NUM:
            b[c] = pd.to_numeric(b[c], errors="coerce") if c in b else None
        keep = ["CNPJ_FUNDO_CLASSE", "TP_APLIC", "TP_ATIVO", "ativo", "codigo", "emissor", "CNPJ_FUNDO_CLASSE_COTA", "v",
                "DT_VENC", "DS_INDEXADOR_POSFX", "GRAU_RISCO", "AG_RISCO", "PAIS", *NUM]
        b.reindex(columns=keep).to_parquet(CACHE / "rec" / f"cda_{m}.parquet", index=False)
        lk.drop(columns="mes").to_parquet(CACHE / "rec" / f"links_{m}.parquet", index=False)
        pl[pl.mes == m][["CNPJ_FUNDO_CLASSE", "VL_PATRIM_LIQ"]].to_parquet(CACHE / "rec" / f"pl_{m}.parquet", index=False)
        (CACHE / "rec" / f"cda_{m}.json").write_text(json.dumps({"v": VERSAO, "fundos": sorted(alvo)}))
    return url


def processa_diario(url, meses, peers):
    z = zipfile.ZipFile(baixa(url))
    cols = {"CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO", "ID_SUBCLASSE", "DT_COMPTC", "VL_QUOTA", "VL_PATRIM_LIQ", "CAPTC_DIA",
            "RESG_DIA", "NR_COTST"}
    d = pd.concat([le(z, n, cols) for n in z.namelist()], ignore_index=True)
    alvo = set(peers).union(*[marca("diario", m) or set() for m in meses])   # mantem quem ja estava no recorte
    d = d[d.CNPJ_FUNDO_CLASSE.isin(alvo)]
    d = d[d.ID_SUBCLASSE.isna()] if "ID_SUBCLASSE" in d else d          # classe (nao subclasses)
    for m in meses:
        d[d.DT_COMPTC.str[:7] == m].to_parquet(CACHE / "rec" / f"diario_{m}.parquet", index=False)
        (CACHE / "rec" / f"diario_{m}.json").write_text(json.dumps({"v": VERSAO, "fundos": sorted(alvo)}))
    return url


def precisa(kind, m, peers):     # recorte em cache cobre os fundos pedidos?
    tem = marca(kind, m)
    if tem is None:
        return True
    if kind == "diario":
        return not set(peers) <= tem
    return not fecho(pd.read_parquet(CACHE / "rec" / f"links_{m}.parquet"), peers) <= tem


def _modificado(u):
    try:
        return u, pd.Timestamp(requests.head(u, timeout=60).headers["Last-Modified"]).timestamp()
    except (requests.RequestException, KeyError, ValueError):
        return u, None


def atualiza_publicacoes(cda, dia, log=print):
    """A CVM republica o arquivo do mes conforme os fundos entregam ou abrem a carteira (ha meses de prazo).
    Uma vez por dia confere a data de TODOS os arquivos mensais e rebaixa os que mudaram."""
    marca_dia = CACHE / f"verificado_{date.today()}.txt"
    if marca_dia.exists():
        return
    urls = [u for u in list(cda) + list(dia) if "HIST" not in u and (CACHE / u.rsplit("/", 1)[1]).exists()]
    with ThreadPoolExecutor(8) as ex:
        mudou = [u for u, t in ex.map(_modificado, urls) if t and t > (CACHE / u.rsplit("/", 1)[1]).stat().st_mtime]
    for u in mudou:
        (CACHE / u.rsplit("/", 1)[1]).unlink(missing_ok=True)
        for m in (cda.get(u) or dia.get(u)):
            for j in CACHE.glob(f"rec/*_{m}.json"):
                j.unlink(missing_ok=True)
    if mudou:
        log(f"{len(mudou)} arquivo(s) da CVM republicado(s) desde a ultima carga: baixando de novo")
    for velho in CACHE.glob("verificado_*.txt"):
        velho.unlink(missing_ok=True)
    marca_dia.write_text(f"{len(urls)} arquivos conferidos, {len(mudou)} atualizados")


def prepara(cnpjs, desde, workers=WORKERS, log=print):
    """Baixa/recorta da CVM so o que falta. Devolve (meses de carteira, {arquivo diario: meses})."""
    cda, dia = arquivos("CDA", desde), arquivos("INF_DIARIO", desde)
    atualiza_publicacoes(cda, dia, log)
    tarefas = ([(processa_cda, u, ms) for u, ms in cda.items() if any(precisa("cda", m, cnpjs) for m in ms)]
               + [(processa_diario, u, ms) for u, ms in dia.items() if any(precisa("diario", m, cnpjs) for m in ms)])

    def roda(i, fn):
        try:
            log(f"{i}/{len(tarefas)} {fn().rsplit('/', 1)[1]}")
        except Exception as e:                    # um arquivo ruim da CVM nao derruba o resto
            log(f"{i}/{len(tarefas)} ATENCAO: arquivo pulado ({type(e).__name__}: {e})")
    if workers > 1 and len(tarefas) > 1:
        with ProcessPoolExecutor(workers) as ex:
            fut = [ex.submit(f, u, ms, cnpjs) for f, u, ms in tarefas]
            for i, f in enumerate(fut, 1):
                roda(i, f.result)
    else:
        for i, (f, u, ms) in enumerate(tarefas, 1):
            roda(i, lambda: f(u, ms, cnpjs))
    meses = sorted(m for ms in cda.values() for m in ms if (CACHE / "rec" / f"cda_{m}.parquet").exists())
    return meses, dia


def fund_cat(name):
    n = (name or "").upper()
    return ("FIDC" if "FIDC" in n or "DIREITOS CREDIT" in n else "FIAGRO" if "FIAGRO" in n or "CADEIAS PRODUTIVAS" in n
            else "Cotas de Fundos")


def carrega_pos(meses):
    """Posicoes (so dos fundos recortados) + PL de todos, todos os meses, com a linha de ajuste carteira x PL."""
    pos = pd.concat([pd.read_parquet(CACHE / "rec" / f"cda_{m}.parquet").assign(mes=m) for m in meses], ignore_index=True)
    pl = pd.concat([pd.read_parquet(CACHE / "rec" / f"pl_{m}.parquet").assign(mes=m) for m in meses], ignore_index=True)
    pl = pl.drop_duplicates(["mes", "CNPJ_FUNDO_CLASSE"]).set_index(["mes", "CNPJ_FUNDO_CLASSE"]).VL_PATRIM_LIQ.astype(float)
    pos = pos.join(pl.rename("pl_fundo"), on=["mes", "CNPJ_FUNDO_CLASSE"])
    # a CDA nem sempre permite dar sinal certo a toda linha (ex.: compromissada tomada x doada): a diferenca
    # entre PL e soma da carteira vira uma linha explicita, em vez de inflar/encolher as categorias
    der = pos.TP_APLIC.fillna("").str.contains(DERIV)
    aj = (pos[~der].groupby(["mes", "CNPJ_FUNDO_CLASSE"]).agg(soma=("v", "sum"), pl_fundo=("pl_fundo", "first"))
          .assign(v=lambda a: a.pl_fundo - a.soma))
    aj = aj[(aj.v.abs() > 0.005 * aj.pl_fundo.abs())].reset_index().assign(
        TP_APLIC=AJUSTE, ativo="Diferença entre PL informado e soma da carteira (fonte CVM)")
    pos = pd.concat([pos, aj.drop(columns="soma")], ignore_index=True)
    return pos, pl


def lookthrough(nomes, meses, carga=None):
    """nomes: {nome: cnpj}. Uma linha por ativo final x caminho, com % do PL do fundo e movimentacao do mes."""
    pos, pl = carga or carrega_pos(meses)
    tem_cart = set(zip(pos.mes, pos.CNPJ_FUNDO_CLASSE))
    front = pd.DataFrame([dict(fundo=n, mes=m, veic=c, peso=1.0, caminho=n, cadeia=c)
                          for n, c in nomes.items() for m in meses if (m, c) in tem_cart])
    folhas = []
    for _ in range(12):
        if front.empty:
            break
        r = front.merge(pos, left_on=["mes", "veic"], right_on=["mes", "CNPJ_FUNDO_CLASSE"])
        f = r.peso / r.pl_fundo * 100              # R$ no veiculo -> % do PL do peer
        r["perc_pl"], r["compra_pct"], r["venda_pct"] = r.v * f, r.VL_AQUIS_NEGOC * f, r.VL_VENDA_NEGOC * f
        r["fator"] = f
        cota = r.CNPJ_FUNDO_CLASSE_COTA
        abre = cota.notna() & pd.Series([(m, c) in tem_cart and c not in cad for m, c, cad in zip(r.mes, cota, r.cadeia)],
                                        index=r.index, dtype=bool)
        nxt = r[abre]
        front = pd.DataFrame(dict(fundo=nxt.fundo, mes=nxt.mes, veic=nxt.CNPJ_FUNDO_CLASSE_COTA, peso=nxt.perc_pl / 100,
                                  caminho=nxt.caminho + " > " + nxt.ativo, cadeia=nxt.cadeia + "|" + nxt.CNPJ_FUNDO_CLASSE_COTA))
        folha = r[~abre].copy()
        eh_cota = folha.TP_APLIC.eq("Cotas de Fundos")
        folha["categoria"] = folha.TP_APLIC.where(~eh_cota, folha.ativo.map(fund_cat))
        folha["veiculo"] = folha.caminho.str.split(" > ").str[-1]
        folhas.append(folha)
    df = pd.concat(folhas, ignore_index=True)
    df = df.rename(columns={"veic": "cnpj_veiculo", "TP_ATIVO": "tipo_ativo", "DT_VENC": "vencimento",
                            "DS_INDEXADOR_POSFX": "indexador", "PR_INDEXADOR_POSFX": "pct_indexador",
                            "PR_CUPOM_POSFX": "cupom", "PR_TAXA_PREFX": "taxa_pre", "GRAU_RISCO": "rating",
                            "AG_RISCO": "agencia", "PAIS": "pais", "v": "valor_veiculo", "QT_POS_FINAL": "quantidade",
                            "VL_CUSTO_POS_FINAL": "custo", "VL_AQUIS_NEGOC": "compras_veiculo",
                            "VL_VENDA_NEGOC": "vendas_veiculo", "pl_fundo": "pl_veiculo"})
    df = df[["fundo", "mes", "categoria", "ativo", "codigo", "emissor", "perc_pl", "compra_pct", "venda_pct", "veiculo",
             "cnpj_veiculo", "caminho", "tipo_ativo", "vencimento", "indexador", "pct_indexador", "cupom", "taxa_pre",
             "rating", "agencia", "pais", "quantidade", "valor_veiculo", "custo", "compras_veiculo", "vendas_veiculo",
             "pl_veiculo", "fator"]]
    df["categoria"] = df.categoria.fillna("Outros")
    df["codigo"] = df.codigo.str.strip()                  # CVM manda codigos com espacos (ex.: "ASER12  ")
    curto = df.ativo.fillna("").str.len() <= 4             # descricao generica ("DEB"): usa codigo + emissor
    df.loc[curto, "ativo"] = (df.codigo.fillna("") + " " + df.emissor.fillna("")).str.strip()[curto]
    df["derivativo"] = df.categoria.str.contains(DERIV)
    df["confidencial"] = df.ativo.str.startswith("(confidencial)", na=False)
    df["chave"] = df.cnpj_veiculo + "|" + df.codigo.fillna(df.ativo)
    return df


def mes_aberto(df, limite=5):
    """Por fundo, o mes mais recente em que a parte confidencial da carteira fica abaixo de `limite`% do PL."""
    t = df.groupby(["fundo", "mes"]).agg(conf=("perc_pl", lambda s: s[df.loc[s.index, "confidencial"]].sum()))
    ok = t[t.conf < limite].reset_index()
    return ok.groupby("fundo").mes.max()


def contribuicao(df):
    """Estimativa mensal de resultado por ativo pela variacao de preco das posicoes mantidas: quantidade do mes anterior
    x (preco unitario do mes - preco do mes anterior), em % do PL do peer. Preco unitario = valor / quantidade (CDA).
    Fica de fora: ganho de negociacao dentro do mes, carrego de caixa/compromissadas (sem quantidade) e ativos
    confidenciais. Cupons/amortizacoes pagos aparecem como queda de preco."""
    x = df[~df.derivativo & ~df.confidencial & ~df.categoria.eq(AJUSTE) & df.quantidade.gt(0)]
    k = x.groupby(["fundo", "mes", "chave"]).agg(v=("valor_veiculo", "sum"), qt=("quantidade", "sum"),
                                                  fator=("fator", "first"), categoria=("categoria", "first"),
                                                  ativo=("ativo", "first"), emissor=("emissor", "first")).reset_index()
    meses = sorted(df.mes.unique())
    seguinte = dict(zip(meses[:-1], meses[1:]))
    prev = k[["fundo", "mes", "chave", "v", "qt"]].assign(mes=k.mes.map(seguinte)).dropna(subset=["mes"])
    k = k.merge(prev.rename(columns={"v": "v_ant", "qt": "qt_ant"}), on=["fundo", "mes", "chave"])
    k["resultado_pct"] = k.qt_ant * (k.v / k.qt - k.v_ant / k.qt_ant) * k.fator
    return k


def _le_anbima(f):
    linhas = f.read_bytes().decode("latin1").splitlines()
    i = next(j for j, l in enumerate(linhas) if l.startswith("Código@"))
    a = pd.read_csv(io.StringIO("\n".join(linhas[i:])), sep="@", dtype=str)
    a.columns = ["codigo", "nome", "venc", "indice", "taxa_compra", "taxa_venda", "taxa_ind", "desvio", "int_min",
                 "int_max", "pu", "pct_par", "duration_du", "pct_reune", "ref_ntnb"][:a.shape[1]]
    for c in ["taxa_ind", "pu", "pct_par", "duration_du"]:
        a[c] = pd.to_numeric(a[c].str.replace(",", ".", regex=False), errors="coerce")
    ind = a.indice.fillna("").str.upper()
    a["tipo"] = pd.Series("Outros", index=a.index).mask(ind.str.contains("IGP"), "IGP-M +").mask(
        ind.str.contains("IPCA"), "IPCA +").mask(ind.str.contains("%") & ind.str.contains("DI"), "% do DI").mask(
        ind.str.match(r"^DI\s*\+"), "DI +")
    a["duration_anos"] = a.duration_du / 252
    return a.assign(data=pd.Timestamp(f"20{f.stem[-6:-4]}-{f.stem[-4:-2]}-{f.stem[-2:]}"))


def anbima_debentures():
    """Marcacao ANBIMA gratuita de debentures (taxa indicativa, PU, duration). O site so guarda ~15 dias uteis:
    cada execucao salva os arquivos da janela, entao o historico local cresce a partir de agora.
    Devolve (ultimo dia, historico de todos os dias guardados)."""
    hoje = pd.Timestamp.today().normalize()
    for dia in pd.bdate_range(hoje - pd.Timedelta(days=25), hoje):
        f = CACHE / f"anbima_db{dia:%y%m%d}.txt"
        if f.exists():
            continue
        try:
            r = requests.get(f"https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/db{dia:%y%m%d}.txt",
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        except requests.RequestException:
            continue
        if r.status_code == 200 and "Código@".encode("latin1") in r.content:     # feriado/ainda nao publicado: pula
            f.write_bytes(r.content)
    fs = sorted(CACHE.glob("anbima_db*.txt"))
    if not fs:
        return pd.DataFrame(), pd.DataFrame()
    hist = pd.concat([_le_anbima(f) for f in fs], ignore_index=True)
    return hist[hist.data == hist.data.max()], hist


def sgs(codigo, desde):
    """Serie do Banco Central (SGS). Diarias: no maximo 10 anos por consulta."""
    out, hoje = [], pd.Timestamp.today()
    for a in range(int(desde[:4]), hoje.year + 1, 9):
        fim = min(pd.Timestamp(a + 8, 12, 31), hoje).strftime("%d/%m/%Y")
        for tent in range(5):
            try:
                out += requests.get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados", timeout=60,
                                    params={"formato": "json", "dataInicial": f"01/01/{a}", "dataFinal": fim}).json()
                break
            except (requests.RequestException, ValueError):
                time.sleep(5 * (tent + 1))
    d = pd.DataFrame(out)
    return pd.Series(d.valor.astype(float).values, index=pd.to_datetime(d.data, dayfirst=True)).sort_index() if len(d) else pd.Series(dtype=float)


def cdi_mensal(desde, diario=False):
    s = sgs(12, desde) / 100
    return s if diario else (1 + s).groupby(s.index.strftime("%Y-%m")).prod() - 1


def ipca_indice():
    """Numero-indice do IPCA (IBGE/SIDRA), mensal. Usado no valor do contrato futuro DAP."""
    f = CACHE / "ipca_indice.json"
    if not f.exists() or f.stat().st_mtime < time.time() - 86400:
        try:
            r = requests.get("https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2266/p/all", timeout=120).json()
            f.write_text(json.dumps({x["D3C"]: x["V"] for x in r[1:]}))
        except (requests.RequestException, ValueError, KeyError):
            if not f.exists():
                return pd.Series(dtype=float)
    d = json.loads(f.read_text())
    s = pd.Series({f"{k[:4]}-{k[4:]}": float(v) for k, v in d.items() if v not in ("...", "-", "")})
    return s.sort_index()


def tesouro():
    """Curvas do Tesouro Direto (gratuito, diario desde 2004): prefixado (LTN) e IPCA+ (NTN-B principal), taxa x prazo."""
    f = CACHE / "tesouro_direto.csv"
    if not f.exists() or f.stat().st_mtime < time.time() - 86400:
        try:
            r = requests.get("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
                             "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv", timeout=300)
            r.raise_for_status()
            f.write_bytes(r.content)
        except requests.RequestException:
            if not f.exists():
                return {}
    d = pd.read_csv(f, sep=";", decimal=",")
    d = d[d["Tipo Titulo"].isin(["Tesouro Prefixado", "Tesouro IPCA+"])].copy()
    d["data"] = pd.to_datetime(d["Data Base"], dayfirst=True)
    d["anos"] = (pd.to_datetime(d["Data Vencimento"], dayfirst=True) - d.data).dt.days / 365.25
    d["taxa"] = d[["Taxa Compra Manha", "Taxa Venda Manha"]].replace(0, np.nan).mean(axis=1)
    d["tipo"] = np.where(d["Tipo Titulo"].eq("Tesouro Prefixado"), "PRE", "IPCA")
    d = d.dropna(subset=["taxa"]).sort_values(["tipo", "data", "anos"])
    out = {}
    for t, g in d.groupby("tipo"):
        por_dia = {k: (x.anos.values, x.taxa.values) for k, x in g.groupby("data")}
        datas = sorted(por_dia)
        out[t] = (np.array(datas, dtype="datetime64[ns]"), datas, por_dia)
    return out


def curva(curvas, tipo, dia, anos):
    """Taxa (% a.a.) da curva `tipo` ("PRE" ou "IPCA") no ultimo dia util <= `dia`, interpolada no prazo `anos`."""
    if tipo not in curvas:
        return np.full(np.shape(anos), np.nan)
    arr, datas, por_dia = curvas[tipo]
    i = np.searchsorted(arr, np.datetime64(pd.Timestamp(dia)), side="right") - 1
    if i < 0:
        return np.full(np.shape(anos), np.nan)
    x, y = por_dia[datas[i]]
    return np.interp(np.clip(anos, x.min(), x.max()), x, y)


def _sem_acento(t):
    import unicodedata
    return unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().upper()


_GRUPOS_RE = [(re.compile(k), v) for k, v in GRUPOS.items()]
_SUFIXOS = re.compile(r"(?<![\w.])(S\.A\.?|S/A|SA|LTDA|SPE|PARTICIPACOES|HOLDING|COMPANHIA|CIA|EMPREENDIMENTOS|E|DE|DO|DA|DOS|DAS|EM)(?![\w/])")


def grupo(emissor, categoria=""):
    """Grupo economico pelo nome do emissor (mapa GRUPOS); sem mapa, o proprio emissor sem sufixos."""
    if categoria in ("Operações Compromissadas",):
        return "Compromissadas"
    if categoria == "Títulos Públicos":
        return "Tesouro Nacional"
    if categoria in ("Disponibilidades", "Valores a receber", "Valores a pagar", AJUSTE):
        return "Caixa e outros"
    if not isinstance(emissor, str) or not emissor.strip():
        return None
    n = _sem_acento(emissor)
    for rx, g in _GRUPOS_RE:
        if rx.search(n):
            return g
    base = " ".join(w for w in _SUFIXOS.sub(" ", n).split() if not w.isdigit())
    return base.title()[:40] or emissor


def diario(nomes, dia):
    nome = {c: n for n, c in nomes.items()}
    d = pd.concat([pd.read_parquet(CACHE / "rec" / f"diario_{m}.parquet") for ms in dia.values() for m in ms
                   if (CACHE / "rec" / f"diario_{m}.parquet").exists()], ignore_index=True)
    d = d[d.CNPJ_FUNDO_CLASSE.isin(nome)]
    for c in ["VL_QUOTA", "VL_PATRIM_LIQ", "CAPTC_DIA", "RESG_DIA", "NR_COTST"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.drop_duplicates(["CNPJ_FUNDO_CLASSE", "DT_COMPTC"], keep="last").sort_values("DT_COMPTC")
    return d.assign(data=pd.to_datetime(d.DT_COMPTC), mes=d.DT_COMPTC.str[:7], fundo=d.CNPJ_FUNDO_CLASSE.map(nome))


def rentabilidade(d, cdi):
    g = d.groupby(["fundo", "mes"])
    rent = pd.DataFrame({"cota_fim": g.VL_QUOTA.last(), "pl_fim": g.VL_PATRIM_LIQ.last(),
                         "captacao_liquida": g.CAPTC_DIA.sum() - g.RESG_DIA.sum(), "cotistas": g.NR_COTST.last()})
    rent["retorno"] = rent.groupby(level=0).cota_fim.pct_change()
    rent["cdi"] = rent.index.get_level_values(1).map(cdi)
    rent["pct_cdi"] = rent.retorno / rent.cdi
    return rent.reset_index()


def excel(df, rent, ordem, out):
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.chart import AreaChart, Reference
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils.indexed_list import IndexedList
    limpa = lambda v: ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v
    df = df.copy()
    for c in df.select_dtypes("object"):
        df[c] = df[c].map(limpa)
    B, N = Font(name="Arial", size=10, bold=True), Font(name="Arial", size=10)
    HF = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    FILL, MFILL = PatternFill("solid", fgColor="1F3864"), PatternFill("solid", fgColor="D9E1F2")
    PCT, PCT2 = '0.0000"%";(0.0000"%")', '0.00"%";(0.00"%")'

    def put(ws, vals, font=None, fill=None, fmt=None):
        ws.append(vals)
        r = ws._current_row                       # O(1); ws.max_row recontaria a planilha toda
        for j in range(1, len(vals) + 1):
            c = ws.cell(r, j)
            if font:
                c.font = font
            if fill:
                c.fill = fill
            if fmt and j in fmt:
                c.number_format = fmt[j]
        return r

    def header(ws, cols, widths):
        put(ws, cols, HF, FILL)
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w

    wb = Workbook()
    wb._fonts = IndexedList([N])                  # Arial 10 como fonte padrao
    wb.remove(wb.active)
    for nm, g in df.groupby("fundo", sort=False):
        ws = wb.create_sheet(nm[:31])
        header(ws, ["Categoria / Ativo", "Codigo", "% PL " + nm, "% da categoria", "Veiculo", "Emissor"], (70, 18, 14, 14, 50, 40))
        ws.sheet_properties.outlinePr.summaryBelow = False
        ws.freeze_panes = "A2"
        for ym, gm in sorted(g.groupby("mes"), reverse=True):
            put(ws, [ym, None, gm.perc_pl.sum()], B, MFILL, {3: PCT})
            ats = gm.groupby(["categoria", "ativo", "codigo"], dropna=False).agg(
                perc_pl=("perc_pl", "sum"), veiculo=("veiculo", "first"), emissor=("emissor", "first"))
            for cat, tot in gm.groupby("categoria").perc_pl.sum().sort_values(ascending=False).items():
                r = put(ws, ["   " + cat, None, tot], B, None, {3: PCT})
                ws.row_dimensions[r].outline_level = 1
                for (_, ativo, cod), a in ats.loc[[cat]].sort_values("perc_pl", ascending=False).iterrows():
                    last = put(ws, ["      " + ativo, None if pd.isna(cod) else cod, a.perc_pl,
                                    a.perc_pl / tot * 100 if tot else None, a.veiculo, a.emissor], fmt={3: PCT, 4: PCT})
                ws.row_dimensions.group(r + 1, last, outline_level=2, hidden=True)

    CURTO = {"Depósitos a prazo e outros títulos de IF": "Depósitos a prazo / IF",
             "Outros valores mobiliários registrados na CVM objeto de oferta pública": "Outros VM (CVM)",
             "Títulos ligados ao agronegócio": "Títulos agro", "Títulos de Crédito Privado": "Crédito privado (CCB/NC)"}
    CORES, OUTROS_COR = ["2A78D6", "EB6834", "1BAF7A", "EDA100", "E87BA4", "008300", "4A3AA7"], "898781"
    cat_ = df.categoria.map(lambda c: CURTO.get(c, c))
    CONTABIL = r"(?i)pagar|receber|obriga|termo|disponibilidade|exigibilidade|swap|confidencial|ajuste"
    TOP = (df.assign(c=cat_)[~cat_.str.contains(CONTABIL) & ~df.derivativo].groupby(["fundo", "mes", "c"]).perc_pl.sum()
           .groupby("c").mean().sort_values(ascending=False).index[:7].tolist())
    SERIES = TOP + ["Outros"]
    ev = df[~df.derivativo].assign(c=cat_.where(cat_.isin(TOP), "Outros")).pivot_table(
        index=["fundo", "mes"], columns="c", values="perc_pl", aggfunc="sum", fill_value=0).reindex(columns=SERIES, fill_value=0)
    ws, gr = wb.create_sheet("evolucao", 0), wb.create_sheet("graficos", 0)
    put(gr, ["Composicao por categoria (% do PL, look-through, dados CVM). Numeros em 'evolucao'."], B)
    for k, nm in enumerate(n for n in ordem if n in ev.index.get_level_values(0)):
        row0 = put(ws, [nm], B)
        put(ws, ["mes"] + SERIES, HF, FILL)
        for ym, r in ev.loc[nm].iterrows():
            last = put(ws, [ym] + [float(v) for v in r], fmt={j: PCT2 for j in range(2, len(SERIES) + 2)})
        ws.append([])
        ws.append([])
        ch = AreaChart()
        ch.grouping, ch.title, ch.y_axis.title = "stacked", f"{nm} — % do PL por categoria", "% do PL"
        ch.y_axis.scaling.min, ch.y_axis.scaling.max, ch.y_axis.majorGridlines = 0, 100, None
        ch.x_axis.tickLblSkip, ch.x_axis.delete, ch.y_axis.delete = 12, False, False
        ch.add_data(Reference(ws, min_col=2, max_col=1 + len(SERIES), min_row=row0 + 1, max_row=last), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=row0 + 2, max_row=last))
        for s, cor in zip(ch.series, CORES + [OUTROS_COR]):
            s.graphicalProperties.solidFill, s.graphicalProperties.line.solidFill = cor, "FCFCFB"
        ch.legend.position, ch.width, ch.height = "r", 26, 9
        gr.add_chart(ch, f"A{3 + k * 19}")
    ws.column_dimensions["A"].width = 12

    ws = wb.create_sheet("rentabilidade", 2)
    header(ws, ["fundo", "mes", "retorno", "CDI", "% CDI", "cota fim", "PL fim", "captacao liquida", "cotistas"],
           (16, 9, 11, 11, 11, 14, 18, 18, 10))
    for r in rent.itertuples(index=False):
        put(ws, [r.fundo, r.mes, r.retorno, r.cdi, r.pct_cdi, r.cota_fim, r.pl_fim, r.captacao_liquida, r.cotistas],
            fmt={3: "0.00%", 4: "0.00%", 5: "0.0%", 7: "#,##0", 8: "#,##0;(#,##0)"})

    ult = df[df.mes == df.fundo.map(df.groupby("fundo").mes.max())]
    top10 = (ult.groupby(["categoria", "fundo", "mes", "ativo", "codigo"], dropna=False).perc_pl.sum().reset_index()
             .sort_values(["categoria", "perc_pl"], ascending=[True, False]).groupby("categoria").head(10))
    top10.insert(1, "rank", top10.groupby("categoria").cumcount() + 1)
    ws = wb.create_sheet("top10", 3)
    header(ws, ["categoria", "rank", "fundo", "mes", "ativo", "codigo", "% PL do fundo"], (34, 6, 16, 9, 70, 18, 14))
    for r in top10.itertuples(index=False):
        put(ws, [None if pd.isna(x) else x for x in r], fmt={7: PCT})
    wb.save(out)
    df.drop(columns=["chave", "fator"]).to_csv(out.replace(".xlsx", "_dados.csv"), index=False, sep=";", decimal=",",
                                               encoding="utf-8-sig")


lt = sys.modules[__name__]          # o servidor chama as funcoes de dados como lt.funcao

# ====================================================================== servidor + pagina

import json
import math
import os
import re
import threading
from datetime import date

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response


app = FastAPI(title="Painel de fundos")

CAT_CORES = ["#2a78d6", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7", "#008300", "#e34948", "#7ba7d9"]
NOSSAS_CORES = ["#eb6834", "#c24f1d", "#f29a6b", "#a8401a", "#f5b38d"]
GENERICO = (r"(?i)\b(FUNDO DE INVESTIMENTO|FUNDO|EM DIREITOS CREDIT[OÓ]RIOS|DE INVESTIMENTO|FIDC|FIC|FI|COTAS|MULTIMERCADO|"
            r"RENDA FIXA|CR[EÉ]DITO PRIVADO|RESPONSABILIDADE LIMITADA|RESP LTDA|N[AÃ]O PADRONIZADO|NP|LONGO PRAZO|LP)\b")
METODO = 5                                     # suba quando mudar o calculo -> refaz o cache do dia
CAIXA = ("Caixa e provisões", "Operações Compromissadas")
CREDITO = ("Debêntures", "Títulos de Crédito Privado", "Títulos ligados ao agronegócio",
           "Outros valores mobiliários registrados na CVM objeto de oferta pública", "Investimento no Exterior", "Outras aplicações")
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


# ------------------------------------------------------------------ calculo por fundo
class Contexto:
    """Dados de mercado compartilhados por todos os fundos."""

    def __init__(self, log):
        log("Baixando curvas (Tesouro Direto), IPCA (IBGE), PTAX e CDI (Banco Central) e marcação ANBIMA...")
        self.curvas = lt.tesouro()
        self.ipca = lt.ipca_indice()
        self.ptax = lt.sgs(1, lt.DESDE)
        self.cdi_d = lt.cdi_mensal(lt.DESDE, diario=True)
        self.cdi_m = (1 + self.cdi_d).groupby(self.cdi_d.index.strftime("%Y-%m")).prod() - 1
        self.an_u, self.an_h = lt.anbima_debentures()
        self.an_dias = sorted(self.an_h.data.unique()) if len(self.an_h) else []

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


def enriquece(g, m, ctx, recentes):
    """Spread sobre o CDI (% a.a., equivalente) e duration (anos) de cada linha da carteira do mes."""
    g = g.copy()
    anos = ((pd.to_datetime(g.vencimento, errors="coerce") - fim_mes(m)).dt.days / 365.25).clip(lower=0)
    cdi = ctx.cdi_aa(m)
    sp, du = pd.Series(np.nan, index=g.index), pd.Series(np.nan, index=g.index)
    idx = g.indexador.fillna("")
    cup = g.cupom.where(g.cupom.fillna(0) != 0)
    pct_i = g.pct_indexador
    # informado na CDA (depositos bancarios, credito privado)
    di = idx.str.contains("DI de um dia|Selic")
    sp[di] = cup[di].fillna((pct_i[di] - 100) / 100 * cdi)
    du[di] = anos[di]
    ip = idx.str.contains("IPCA")
    sp[ip] = cup[ip] - lt.curva(ctx.curvas, "IPCA", fim_mes(m), anos[ip].fillna(3).values)
    du[ip] = anos[ip]
    pr = idx.str.contains("prefixada")
    sp[pr] = g.taxa_pre[pr].fillna(cup[pr]) - lt.curva(ctx.curvas, "PRE", fim_mes(m), anos[pr].fillna(1).values)
    du[pr] = anos[pr]
    # titulos publicos e caixa
    tp = g.categoria.eq("Títulos Públicos")
    lft = tp & g.ativo.str.contains("FINANCEIRAS DO TESOURO|LFT", na=False)
    sp[tp], du[tp] = 0.0, anos[tp]
    du[lft] = 0.0
    cx = g.categoria.isin(CAIXA)
    sp[cx], du[cx] = 0.0, 0.0
    # debentures: marcacao ANBIMA
    dia, an = ctx.anbima_mes(m, recentes)
    deb = g.categoria.eq("Debêntures") & g.codigo.notna()
    if an is not None and deb.any():
        a = an.reindex(g.codigo[deb])
        tx, tipo, dur = a.taxa_ind.values, a.tipo.values, a.duration_anos.values
        s = np.where(tipo == "DI +", tx, np.where(tipo == "% do DI", (tx - 100) / 100 * cdi, np.nan))
        real = np.isin(tipo, ["IPCA +", "IGP-M +"])
        s = np.where(real, tx - lt.curva(ctx.curvas, "IPCA", pd.Timestamp(dia), np.nan_to_num(dur, nan=3)), s)
        pre = tipo == "Outros"
        s = np.where(pre, tx - lt.curva(ctx.curvas, "PRE", pd.Timestamp(dia), np.nan_to_num(dur, nan=2)), s)
        sp[deb], du[deb] = s, dur
    g["spread"], g["duration"] = sp, du
    tipo_an = g.codigo.map(ctx.an_u.drop_duplicates("codigo").set_index("codigo").tipo) if len(ctx.an_u) else pd.Series(np.nan, index=g.index)
    g["ipca"] = tipo_an.isin(["IPCA +", "IGP-M +"]) | ip | g.ativo.str.contains("SERIE B|NTN-B", na=False)
    g["pre"] = (tipo_an.eq("Outros") & g.categoria.eq("Debêntures")) | pr | (tp & g.ativo.str.contains(r"LETRAS DO TESOURO NACIONAL|SERIE F|LTN|NTN-F", na=False) & ~lft)
    g["usd"] = g.categoria.eq("Investimento no Exterior") | idx.str.contains("Dólar")
    return g, dia


def derivativos_mes(gd, m, ctx, dur_ipca, dur_pre):
    """Contratos futuros do mes: tipo, lado, contratos, prazo e nocional estimado (R$)."""
    out = []
    for r in gd.itertuples():
        tipo, venc = contrato(f"{r.codigo or ''} {r.ativo or ''} {r.tipo_ativo or ''}")
        if "mercado futuro" not in str(r.categoria).lower():   # termo/opcao/swap: sem P&L de futuro
            tipo, venc = "OUTRO", None
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
    """Tudo que as abas Carteira e Retorno mostram para um fundo."""
    df = df.copy()
    if ctx.an_h is not None and len(ctx.an_h):         # debenture sem emissor na CDA: nome do emissor pela ANBIMA
        df["emissor"] = df.emissor.fillna(df.codigo.map(ctx.an_h.drop_duplicates("codigo", keep="last").set_index("codigo").nome))
    emis = df[["emissor", "categoria"]].drop_duplicates()
    gmap = {(e, c): lt.grupo(e, c) for e, c in zip(emis.emissor, emis.categoria)}
    df["grupo"] = [gmap[(e, c)] for e, c in zip(df.emissor, df.categoria)]
    curto = df.ativo.str.replace(GENERICO, " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip().str.slice(0, 40)
    df["grupo"] = df.grupo.fillna(curto)
    contabil = df.categoria.isin(["Disponibilidades", "Valores a receber", "Valores a pagar", lt.AJUSTE]) | (
        df.categoria.str.contains(lt.PASSIVO, na=False) & ~df.derivativo)
    df["categoria"] = df.categoria.mask(contabil, "Caixa e provisões")   # linhas contabeis numa so categoria
    meses = sorted(df.mes.unique())
    recentes = set(meses[-4:])
    pl_f = {m: float(pl.get((m, cnpj), np.nan)) for m in meses}
    cart_meses, ricos = [], {}
    for m in meses:
        g = df[df.mes == m]
        nd, gd = g[~g.derivativo], g[g.derivativo]
        e, dia = enriquece(nd, m, ctx, recentes)
        ricos[m] = (e, gd)
        e["fin"] = e.perc_pl / 100 * pl_f[m] / 1e6
        cats = []
        for c, x in e.groupby("categoria"):
            com = x.spread.notna() & x.perc_pl.gt(0)
            cats.append({"categoria": c, "perc": x.perc_pl.sum(), "fin": x.fin.sum(), "spread": wavg(x.spread, x.perc_pl),
                         "duration": wavg(x.duration, x.perc_pl), "cobertura": x.perc_pl[com].sum() / x.perc_pl[x.perc_pl > 0].sum() * 100
                         if x.perc_pl.gt(0).any() else None})
        cats.sort(key=lambda r: -r["perc"])
        total = {"categoria": "Total", "perc": e.perc_pl.sum(), "fin": e.fin.sum(), "spread": wavg(e.spread, e.perc_pl),
                 "duration": wavg(e.duration, e.perc_pl)}
        ip = e[e.ipca & e.perc_pl.gt(0)]
        dur_ipca = wavg(ip.duration, ip.perc_pl) or 3.0
        pr = e[e.pre & e.perc_pl.gt(0)]
        dur_pre = wavg(pr.duration, pr.perc_pl) or 1.0
        der = []
        for c in derivativos_mes(gd, m, ctx, dur_ipca, dur_pre):
            v = nocional(c, m, ctx, pl_f[m])
            der.append({"contrato": c["tipo"] if c["tipo"] != "OUTRO" else (c["ativo"] or c["categoria"])[:40],
                        "lado": "comprado" if c["lado"] > 0 else "vendido", "contratos": c["n"], "fin": v / 1e6 if pd.notna(v) else None,
                        "prazo": c["anos"]})
        dd = pd.DataFrame(der)
        if len(dd):
            dd = dd.groupby(["contrato", "lado"], dropna=False).agg(contratos=("contratos", "sum"), fin=("fin", "sum"),
                                                                     prazo=("prazo", "mean")).reset_index()
        x = e[(e.perc_pl > 0) & ~e.categoria.isin(CAIXA + ("Valores a receber", "Valores a pagar", lt.AJUSTE))]
        x = x.assign(sw=(x.spread * x.perc_pl).fillna(0), sp=x.perc_pl.where(x.spread.notna(), 0),
                     dw=(x.duration * x.perc_pl).fillna(0), dp=x.perc_pl.where(x.duration.notna(), 0))
        top = (x.groupby(["ativo", "codigo"], dropna=False)
               .agg(grupo=("grupo", "first"), categoria=("categoria", "first"), perc=("perc_pl", "sum"), sw=("sw", "sum"),
                    sp=("sp", "sum"), dw=("dw", "sum"), dp=("dp", "sum")).reset_index().nlargest(10, "perc"))
        top["spread"] = (top.sw / top.sp).where(top.sp > 0)
        top["duration"] = (top.dw / top.dp).where(top.dp > 0)
        top = top.drop(columns=["sw", "sp", "dw", "dp"])
        gr = x.groupby("grupo").perc_pl.sum().nlargest(10).reset_index()
        cart_meses.append({"mes": m, "pl_mm": pl_f[m] / 1e6, "anbima": dia, "conf": e[e.confidencial].perc_pl.sum(),
                           "cats": cats, "total": total, "deriv": dd.to_dict("records") if len(dd) else [],
                           "top": top.to_dict("records"), "grupos": gr.rename(columns={"perc_pl": "perc"}).to_dict("records")})

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
    id_ativo = lambda a, c, gr: ativos.setdefault((a, c), {"i": len(ativos), "ativo": a, "categoria": c, "grupo": gr})["i"]
    for j in range(1, len(meses)):
        p, m = meses[j - 1], meses[j]
        if m not in real.index or pd.isna(real.get(m)):
            continue
        e0, gd0 = ricos[p]
        w = e0[~e0.confidencial].copy()
        w = w[w.perc_pl.abs() > 0]
        cdi_m = float(ctx.cdi_m.get(m, 0.0))
        # 1) retorno de cada ativo: esperado = CDI + spread proprio; usa a variacao real de preco quando ela e critica
        #    (queda maior que 1,5 p.p. abaixo do esperado = pagamento de cupom/amortizacao -> fica o esperado)
        esperado = (1 + cdi_m) * (1 + w.spread.fillna(0).clip(-5, 30) / 100) ** (1 / 12) - 1
        rp = w.chave.map(preco.loc[m]) if len(preco) and m in preco.index.get_level_values(0) else pd.Series(np.nan, index=w.index)
        r = rp.where(rp.notna() & (rp >= esperado - 0.015) & (rp <= esperado + 0.03), esperado)
        cx = w.categoria.isin(CAIXA)
        r[cx] = cdi_m
        ativo_c = w.perc_pl * r
        # 3) derivativos -> ativos protegidos
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
        # 4) resto (taxas, negociacao, marcacao fora do esperado) -> todas as categorias que nao sao caixa, pelo peso
        resid = float(real[m]) * 100 - ativo_c.sum()
        cr = w.perc_pl.gt(0) & ~cx
        ativo_c[cr] += resid * w.perc_pl[cr] / w.perc_pl[cr].sum()
        atr_meses.append({"mes": m, "real": float(real[m]) * 100, "cdi": float(ctx.cdi_m.get(m, np.nan)) * 100,
                          "hedge": hedge, "resid": resid})
        jm = len(atr_meses) - 1
        por_cat = ativo_c.groupby(w.categoria).sum()
        peso = w.groupby("categoria").perc_pl.sum()
        for c in set(por_cat.index) | set(cats_atr):
            cats_atr.setdefault(c, {"contrib": [None] * jm, "peso": [None] * jm})
            cats_atr[c]["contrib"].append(float(por_cat.get(c, 0.0)))
            cats_atr[c]["peso"].append(float(peso.get(c, 0.0)))
        pa = ativo_c[~cx].groupby([w.ativo[~cx], w.categoria[~cx], w.grupo[~cx]]).sum()   # caixa/compromissada fora do ranking
        for (a, c, gr), v in pa.items():
            if abs(v) > 1e-5:
                contrib.append([id_ativo(a, c, gr), jm, float(v)])
    for c in cats_atr.values():
        for key in ("contrib", "peso"):
            c[key] += [None] * (len(atr_meses) - len(c[key]))
    return limpo({"nome": nome, "cnpj": cnpj, "carteira": cart_meses,
                  "retorno": {"meses": atr_meses, "categorias": cats_atr,
                              "ativos": sorted(ativos.values(), key=lambda x: x["i"]), "contrib": contrib}})


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
        ctx = Contexto(escreve)
        escreve("Carregando carteiras...")
        carga = lt.carrega_pos(meses)
        pl = carga[1]
        nomes = {n: c for n, c, _ in fundos}
        d = lt.diario(nomes, dia)
        rent = lt.rentabilidade(d, ctx.cdi_m) if len(d) else pd.DataFrame(columns=["fundo", "mes", "retorno"])
        for i, (n, c, _) in enumerate(fundos, 1):
            escreve(f"[{i}/{len(fundos)}] {n}: look-through, carteira e atribuição...")
            df = lt.lookthrough({n: c}, meses, carga)
            fid = re.sub(r"\D", "", c)
            if len(df):
                (dest / (fid + ".json")).write_text(json.dumps(detalhe(n, c, df, ctx, pl, rent)), encoding="utf-8")
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


@app.get("/api/csv/{fid}")
def csv(fid: str):
    df = pd.read_parquet(_arquivo(re.sub(r"\D", "", fid) + ".parquet"))
    return Response(df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="carteira_{fid}.csv"'})


@app.get("/")
def index():
    return HTMLResponse(PAGINA)


PAGINA = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel de fundos</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect x='4' y='16' width='5' height='12' rx='1' fill='%232a78d6'/><rect x='13' y='9' width='5' height='19' rx='1' fill='%231baf7a'/><rect x='22' y='4' width='5' height='24' rx='1' fill='%23eb6834'/></svg>">
<style>
:root {
  --bg: #f5f6f8; --surface: #ffffff; --surface-2: #f0f1f4; --line: #e3e5ea; --line-2: #d0d3da;
  --text-1: #14161a; --text-2: #4d525c; --muted: #8a8f99;
  --accent: #2a78d6; --accent-soft: rgba(42,120,214,.10); --nosso: #eb6834; --nosso-soft: rgba(235,104,52,.12);
  --good: #0f7b3f; --bad: #c43d3d; --radius: 12px;
  --shadow: 0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.06);
  --font: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, "Helvetica Neue", Arial, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0f1012; --surface: #17191c; --surface-2: #1f2226; --line: #2a2d32; --line-2: #3a3e45;
    --text-1: #f2f3f5; --text-2: #b7bcc6; --muted: #858b96; --accent: #3987e5; --accent-soft: rgba(57,135,229,.16);
    --good: #2fbf6b; --bad: #ef6b6b; --shadow: none; --nosso-soft: rgba(235,104,52,.18);
  }
}
:root[data-theme="dark"] {
  --bg: #0f1012; --surface: #17191c; --surface-2: #1f2226; --line: #2a2d32; --line-2: #3a3e45;
  --text-1: #f2f3f5; --text-2: #b7bcc6; --muted: #858b96; --accent: #3987e5; --accent-soft: rgba(57,135,229,.16);
  --good: #2fbf6b; --bad: #ef6b6b; --shadow: none; --nosso-soft: rgba(235,104,52,.18);
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--text-1); font: 14px/1.5 var(--font); }
h1 { font-size: 16px; margin: 0; }
h2 { font-size: 20px; margin: 0; letter-spacing: -.01em; }
h3 { font-size: 14px; margin: 0 0 2px; }
button { font: inherit; cursor: pointer; }
input, select { font: inherit; color: var(--text-1); background: var(--surface); border: 1px solid var(--line-2); border-radius: 8px; padding: 8px 10px; }

.barra { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 18px; padding: 8px 22px; background: var(--surface); border-bottom: 1px solid var(--line); }
.marca { display: flex; align-items: center; gap: 10px; min-width: 0; }
.logo { width: 26px; height: 26px; flex: none; } .logo.grande { width: 48px; height: 48px; }
.datas { margin: 0; font-size: 11.5px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.abas { display: flex; gap: 4px; margin-left: auto; }
.abas button { border: 0; background: transparent; color: var(--text-2); padding: 8px 14px; border-radius: 8px; font-weight: 600; }
.abas button:hover { background: var(--surface-2); }
.abas button[aria-selected="true"] { background: var(--accent-soft); color: var(--accent); }
.botao { border: 1px solid var(--line-2); background: var(--surface); color: var(--text-1); border-radius: 8px; padding: 7px 12px; }
.botao:hover { background: var(--surface-2); }
.botao.icone { width: 36px; padding: 7px 0; }
.botao.sel { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); font-weight: 600; }

main { max-width: 1380px; margin: 0 auto; padding: 18px 24px 60px; }
.cab { display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; justify-content: space-between; margin-bottom: 14px; }
.titulo-fundo { min-width: 0; }
.titulo-fundo h2 { display: flex; align-items: center; gap: 8px; }
.tag { font-size: 11px; font-weight: 700; color: var(--nosso); background: var(--nosso-soft); border-radius: 6px; padding: 2px 7px; letter-spacing: .02em; }
.sub { color: var(--muted); font-size: 12px; margin: 2px 0 0; }
.controles { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.controles label { font-size: 12px; color: var(--text-2); display: flex; gap: 6px; align-items: center; }

/* busca de fundo por digitacao */
.busca { position: relative; width: min(420px, 100%); }
.busca input { width: 100%; padding-left: 34px; }
.busca::before { content: "⌕"; position: absolute; left: 11px; top: 6px; font-size: 17px; color: var(--muted); }
.sugestoes { position: absolute; z-index: 30; left: 0; right: 0; top: 100%; margin: 4px 0 0; padding: 4px; list-style: none; max-height: 340px; overflow: auto;
  background: var(--surface); border: 1px solid var(--line-2); border-radius: 10px; box-shadow: 0 10px 28px rgba(0,0,0,.16); }
.sugestoes li { padding: 7px 9px; border-radius: 7px; cursor: pointer; display: flex; justify-content: space-between; gap: 10px; font-size: 13px; }
.sugestoes li small { color: var(--muted); }
.sugestoes li:hover, .sugestoes li.ativo { background: var(--surface-2); }

.grade { display: grid; gap: 16px; margin-bottom: 16px; }
.g2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.g-tabela { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); }
.cartao { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 14px 16px; min-width: 0; margin-bottom: 16px; }
.grade > .cartao { margin-bottom: 0; }
.cartao .sub { margin-bottom: 8px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 16px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); padding: 12px 14px; }
.kpi .r { font-size: 12px; color: var(--text-2); }
.kpi .v { font-size: 24px; font-weight: 700; letter-spacing: -.02em; margin-top: 2px; font-variant-numeric: tabular-nums; }
.kpi .s { font-size: 11.5px; color: var(--muted); }
.pos { color: var(--good); } .neg { color: var(--bad); }

.tabela-wrap { overflow: auto; border: 1px solid var(--line); border-radius: 10px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 7px 11px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
th { position: sticky; top: 0; background: var(--surface-2); color: var(--text-2); font-weight: 600; font-size: 12px; z-index: 1; }
th.ord { cursor: pointer; } th.ord:hover { color: var(--text-1); }
tbody tr:hover td { background: var(--accent-soft); }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
td.texto { white-space: normal; min-width: 200px; }
tr.total td { font-weight: 700; border-top: 2px solid var(--line-2); background: var(--surface-2); }
tr.secao td { font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); background: var(--surface); padding-top: 14px; }
tr.nosso td:first-child { box-shadow: inset 3px 0 0 var(--nosso); }
.ponto { display: inline-block; width: 9px; height: 9px; border-radius: 3px; margin-right: 6px; vertical-align: 0; }
.nota { color: var(--muted); font-size: 11.5px; margin: 8px 0 0; }

/* selecao multipla (consolidado) */
.multi { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 6px; border: 1px solid var(--line-2); border-radius: 10px; background: var(--surface); min-height: 44px; }
.multi .chip { display: inline-flex; align-items: center; gap: 5px; border-radius: 999px; padding: 3px 4px 3px 10px; font-size: 12.5px; background: var(--surface-2); }
.multi .chip.nosso { background: var(--nosso-soft); }
.multi .chip button { border: 0; background: none; color: var(--muted); font-size: 15px; line-height: 1; padding: 0 4px; }
.multi .busca { width: 220px; flex: 1; }
.multi .busca input { border: 0; padding: 5px 5px 5px 30px; }
.multi .busca::before { top: 2px; }

.carregando { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; background: var(--bg); }
.carregando[hidden] { display: none; }
.carregando .caixa { width: min(560px, 92vw); text-align: center; }
.carregando h2 { margin-top: 12px; }
.descricao { color: var(--text-2); font-size: 13px; }
.barra-prog { height: 4px; background: var(--line); border-radius: 4px; overflow: hidden; margin: 18px 0 10px; }
.barra-prog div { height: 100%; width: 35%; background: var(--accent); border-radius: 4px; animation: vai 1.4s ease-in-out infinite; }
@keyframes vai { 0% { transform: translateX(-100%); } 100% { transform: translateX(300%); } }
pre { text-align: left; white-space: pre-wrap; font: 12px/1.5 ui-monospace, Consolas, monospace; color: var(--text-2); background: var(--surface);
  border: 1px solid var(--line); border-radius: 8px; padding: 10px; max-height: 220px; overflow: auto; margin: 0; }
.vazio { padding: 60px 0; text-align: center; color: var(--text-2); }

@media (max-width: 980px) {
  html, body { overflow-x: hidden; }
  .barra { flex-wrap: wrap; padding: 8px 14px; gap: 8px; }
  .abas { margin-left: 0; order: 3; width: 100%; }
  main { padding: 14px 14px 50px; }
  .g2, .g-tabela { grid-template-columns: minmax(0, 1fr); }
  .kpi .v { font-size: 20px; }
}

</style>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
</head>
<body>
<header class="barra">
  <div class="marca">
    <svg class="logo" viewBox="0 0 32 32" aria-hidden="true"><rect x="4" y="16" width="5" height="12" rx="1.5" fill="#2a78d6"/><rect x="13.5" y="9" width="5" height="19" rx="1.5" fill="#1baf7a"/><rect x="23" y="4" width="5" height="24" rx="1.5" fill="#eb6834"/></svg>
    <div><h1>Painel de fundos</h1><p id="datas" class="datas"></p></div>
  </div>
  <nav class="abas" role="tablist">
    <button role="tab" data-aba="carteira" aria-selected="true">Carteira</button>
    <button role="tab" data-aba="retorno" aria-selected="false">Retorno</button>
    <button role="tab" data-aba="consolidado" aria-selected="false">Consolidado</button>
  </nav>
  <button id="tema" class="botao icone" title="Tema claro/escuro" aria-label="Alternar tema">◐</button>
</header>
<main id="conteudo"></main>

<div id="carregando" class="carregando">
  <div class="caixa">
    <svg class="logo grande" viewBox="0 0 32 32" aria-hidden="true"><rect x="4" y="16" width="5" height="12" rx="1.5" fill="#2a78d6"/><rect x="13.5" y="9" width="5" height="19" rx="1.5" fill="#1baf7a"/><rect x="23" y="4" width="5" height="24" rx="1.5" fill="#eb6834"/></svg>
    <h2>Preparando o painel</h2>
    <p class="descricao">Baixando e processando os dados de todos os fundos. Na primeira vez do dia pode levar alguns minutos.</p>
    <div class="barra-prog"><div></div></div>
    <pre id="log-carga"></pre>
  </div>
</div>
<script>
// Painel de fundos - 3 abas: Carteira, Retorno, Consolidado. Dados processados pelo servidor (/api).
const $ = (s, el = document) => el.querySelector(s);
const nf = (d) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (v, d = 2) => (v == null || !isFinite(v) ? "–" : nf(d).format(v));
const pct = (v, d = 2) => (v == null || !isFinite(v) ? "–" : nf(d).format(v) + "%");
const pp = (v, d = 2) => (v == null || !isFinite(v) ? "–" : (v > 0 ? "+" : "") + nf(d).format(v) + " pp");
const cls = (v) => (v == null ? "" : v >= 0 ? "pos" : "neg");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const mesBR = (m) => (m ? MESES[+m.slice(5, 7) - 1] + "/" + m.slice(0, 4) : "–");
const dataBR = (d) => (d ? d.slice(8, 10) + "/" + d.slice(5, 7) + "/" + d.slice(0, 4) : "–");
const semAcento = (t) => String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
const espera = (ms) => new Promise((ok) => setTimeout(ok, ms));
const st = { V: null, F: {}, aba: "carteira", fundo: null, mesCart: {}, ret: { de: null, ate: null }, cons: { sel: null, de: null, ate: null, ord: "ret", asc: false } };

// ------------------------------------------------------------------ tema e abas
try { const t = localStorage.getItem("tema"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
$("#tema").onclick = () => {
  const escuro = document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = escuro ? "light" : "dark";
  try { localStorage.setItem("tema", document.documentElement.dataset.theme); } catch (e) {}
  if (st.V) desenha();
};
document.querySelectorAll(".abas button").forEach((b) => (b.onclick = () => {
  st.aba = b.dataset.aba;
  document.querySelectorAll(".abas button").forEach((x) => x.setAttribute("aria-selected", x === b));
  desenha();
}));

// ------------------------------------------------------------------ carga
(async function inicia() {
  for (;;) {
    let s;
    try { s = await (await fetch("/api/inicial")).json(); } catch (e) { await espera(2000); continue; }
    $("#log-carga").textContent = (s.log || []).join("\n") || "Iniciando...";
    if (s.status === "erro") return ($("#log-carga").textContent += "\n\nErro: " + s.erro);
    if (s.status === "ok") break;
    await espera(2000);
  }
  st.V = await (await fetch("/api/visao")).json();
  const V = st.V;
  st.fundo = (V.fundos.find((f) => f.nosso && f.tem_carteira) || V.fundos.find((f) => f.tem_carteira) || V.fundos[0]).id;
  st.cons.sel = new Set(V.fundos.map((f) => f.id));
  $("#datas").textContent = `${V.fundos.length} fundos (${V.fundos.filter((f) => f.nosso).length} nossos) · carteiras até ${mesBR(V.ult_carteira)} · cotas até ${dataBR(V.datas[V.datas.length - 1])} · ANBIMA ${dataBR(V.anbima)}`;
  $("#carregando").hidden = true;
  desenha();
})();
async function detalhe(id) {
  if (!st.F[id]) st.F[id] = await (await fetch("/api/fundo/" + id)).json();
  return st.F[id];
}
const fundoPor = (id) => st.V.fundos.find((f) => f.id === id);

// ------------------------------------------------------------------ busca de fundo (digitando)
function campoBusca(onPick, placeholder = "Digite o nome ou CNPJ do fundo...", soComCarteira = false) {
  const wrap = document.createElement("div");
  wrap.className = "busca";
  wrap.innerHTML = `<input type="search" placeholder="${placeholder}" autocomplete="off"><ul class="sugestoes" hidden></ul>`;
  const inp = $("input", wrap), ul = $("ul", wrap);
  let sel = 0, lista = [];
  const filtra = () => {
    const q = semAcento(inp.value.trim()), dig = inp.value.replace(/\D/g, "");
    lista = st.V.fundos.filter((f) => (!soComCarteira || f.tem_carteira) && (!q || semAcento(f.nome).includes(q) || (dig.length > 2 && f.id.includes(dig))))
      .sort((a, b) => b.nosso - a.nosso || a.nome.localeCompare(b.nome)).slice(0, 30);
    sel = 0;
    ul.innerHTML = lista.map((f, i) => `<li data-i="${i}" class="${i === 0 ? "ativo" : ""}"><span>${f.nosso ? '<span class="ponto" style="background:var(--nosso)"></span>' : ""}${esc(f.nome)}</span><small>${esc(f.cnpj)}</small></li>`).join("") || "<li>Nada encontrado</li>";
    ul.hidden = false;
  };
  const escolhe = (i) => { if (lista[i]) { ul.hidden = true; inp.value = ""; onPick(lista[i]); } };
  inp.addEventListener("input", filtra);
  inp.addEventListener("focus", filtra);
  inp.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + lista.length) % Math.max(lista.length, 1);
      ul.querySelectorAll("li").forEach((x, i) => x.classList.toggle("ativo", i === sel)); e.preventDefault();
    } else if (e.key === "Enter") { e.preventDefault(); escolhe(sel); } else if (e.key === "Escape") ul.hidden = true;
  });
  ul.addEventListener("mousedown", (e) => { const li = e.target.closest("li[data-i]"); if (li) escolhe(+li.dataset.i); });
  inp.addEventListener("blur", () => setTimeout(() => (ul.hidden = true), 150));
  return wrap;
}

// ------------------------------------------------------------------ graficos e tabelas
function layout(extra = {}) {
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { family: css("--font"), size: 12, color: css("--text-2") },
    margin: { l: 50, r: 14, t: 10, b: 40 }, hovermode: "x unified", legend: { orientation: "h", y: -0.18, font: { color: css("--text-2") } },
    xaxis: { gridcolor: "rgba(0,0,0,0)", linecolor: css("--line-2"), automargin: true },
    yaxis: { gridcolor: css("--line"), zerolinecolor: css("--line-2"), automargin: true },
    hoverlabel: { bgcolor: css("--surface"), bordercolor: css("--line-2"), font: { color: css("--text-1") } },
  }, extra);
}
function plota(el, dados, lay, h = 340) {
  el.style.height = h + "px";
  Plotly.newPlot(el, dados, lay, { displaylogo: false, responsive: true, displayModeBar: innerWidth > 700 ? "hover" : false,
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] });
}
const cartao = (titulo, sub, corpo) => `<div class="cartao"><h3>${titulo}</h3>${sub ? `<p class="sub">${sub}</p>` : ""}${corpo}</div>`;
function tabela(cols, linhas, extra = {}) {
  const th = cols.map((c) => `<th class="${c.n ? "n" : ""} ${c.ord ? "ord" : ""}" ${c.ord ? `data-ord="${c.ord}"` : ""}>${c.t}</th>`).join("");
  const tr = linhas.map((r) => `<tr class="${r._cls || ""}">${cols.map((c) => `<td class="${c.n ? "n" : c.w ? "texto" : ""}">${c.f ? c.f(r[c.k], r) : esc(r[c.k] ?? "–")}</td>`).join("")}</tr>`).join("");
  return `<div class="tabela-wrap" style="max-height:${extra.alt || 620}px"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}
const kpi = (r, v, s = "", c = "") => `<div class="kpi"><div class="r">${r}</div><div class="v ${c}">${v}</div><div class="s">${s}</div></div>`;
function categoriasPrincipais(series, n = 7) {
  return Object.entries(series).map(([c, ys]) => [c, ys.reduce((s, y) => s + (y || 0), 0)]).sort((a, b) => b[1] - a[1]).slice(0, n).map((x) => x[0]);
}

function desenha() {
  const el = $("#conteudo");
  try {
    if (st.aba === "carteira") carteira(el);
    else if (st.aba === "retorno") retorno(el);
    else consolidado(el);
  } catch (e) { el.innerHTML = `<div class="vazio">Erro ao desenhar: ${esc(e.message)}</div>`; console.error(e); }
}
function cabecalhoFundo(el, f, extra = "") {
  el.innerHTML = `<div class="cab"><div class="titulo-fundo"><h2>${esc(f.nome)} ${f.nosso ? '<span class="tag">NOSSO</span>' : ""}</h2>
    <p class="sub">${esc(f.cnpj)}${f.pl ? ` · PL R$ ${num(f.pl, 0)} mm` : ""}</p></div><div class="controles" id="ctl">${extra}</div></div><div id="corpo"></div>`;
  $("#ctl").prepend(campoBusca((x) => { st.fundo = x.id; desenha(); }, "Trocar de fundo: digite nome ou CNPJ...", st.aba === "carteira"));
}

// ------------------------------------------------------------------ CARTEIRA
async function carteira(el) {
  const f = fundoPor(st.fundo);
  if (!f.tem_carteira) { cabecalhoFundo(el, f); $("#corpo").innerHTML = `<div class="vazio">A CVM não tem carteira deste fundo no período.</div>`; return; }
  cabecalhoFundo(el, f);
  $("#corpo").innerHTML = `<div class="vazio">Carregando ${esc(f.nome)}...</div>`;
  const D = await detalhe(f.id);
  if (st.fundo !== f.id || st.aba !== "carteira") return;
  const ms = D.carteira.map((x) => x.mes);
  const aberto = [...D.carteira].reverse().find((x) => x.conf < 5) || D.carteira[D.carteira.length - 1];
  const mes = ms.includes(st.mesCart[f.id]) ? st.mesCart[f.id] : aberto.mes;
  const C = D.carteira.find((x) => x.mes === mes);
  $("#ctl").insertAdjacentHTML("beforeend", `<label>Carteira <select id="mes">${ms.slice().reverse().map((m) => `<option value="${m}" ${m === mes ? "selected" : ""}>${mesBR(m)}${D.carteira.find((x) => x.mes === m).conf >= 5 ? " (confid.)" : ""}</option>`).join("")}</select></label>
    <a class="botao" href="/api/csv/${f.id}" title="Carteira look-through completa (CSV)">CSV</a>`);
  $("#mes").onchange = (e) => { st.mesCart[f.id] = e.target.value; desenha(); };

  const linhas = C.cats.map((c) => ({ ...c })).concat([{ ...C.total, _cls: "total", categoria: "Total ponderado" }]);
  if (C.deriv.length) {
    linhas.push({ categoria: "Derivativos (nocional estimado)", _cls: "secao" });
    C.deriv.forEach((d) => linhas.push({ categoria: `${d.contrato} · ${d.lado}${d.contratos ? ` · ${num(d.contratos, 0)} contratos` : ""}`, perc: null, fin: d.fin, spread: null, duration: d.prazo, _der: 1 }));
  }
  const tab = tabela([
    { t: "Categoria", k: "categoria", w: 1 },
    { t: "% PL", k: "perc", n: 1, f: (v, r) => (r._cls === "secao" ? "" : r._der ? "–" : pct(v)) },
    { t: "Financeiro (R$ mm)", k: "fin", n: 1, f: (v, r) => (r._cls === "secao" ? "" : num(v)) },
    { t: "Spread CDI+ (% a.a.)", k: "spread", n: 1, f: (v, r) => (r._cls === "secao" || r._der ? "" : num(v)) },
    { t: "Duration (anos)", k: "duration", n: 1, f: (v, r) => (r._cls === "secao" ? "" : num(v)) },
  ], linhas);
  const conf = C.conf >= 0.5 ? ` · ${pct(C.conf, 1)} do PL ainda confidencial` : "";
  $("#corpo").innerHTML = cartao(`Carteira de ${mesBR(mes)} por categoria`, `PL R$ ${num(C.pl_mm, 2)} mm · look-through (cotas de fundos abertas até o ativo)${conf}`, tab +
    `<p class="nota">Spread CDI+ = equivalente em CDI: debêntures pela taxa indicativa ANBIMA de ${dataBR(C.anbima)} (IPCA+ menos a NTN-B de mesma duration); CDBs, LFs e crédito pela taxa informada à CVM; caixa e compromissadas = 0. FIDCs e cotas de fundos não têm taxa pública. Médias ponderadas pelo % do PL, só onde há taxa.</p>`) +
    `<div class="grade g2">${cartao("% do PL por categoria", "Evolução mensal (sem derivativos)", '<div id="g_aloc"></div>')}${cartao("Spread CDI+ por categoria", "Média ponderada no mês, % a.a. (debêntures só nos meses com marcação ANBIMA guardada)", '<div id="g_spread"></div>')}</div>
    <div class="grade g-tabela">${cartao("Top 10 ativos", `% do PL em ${mesBR(mes)}`, '<div id="t_top"></div>')}${cartao("Maiores grupos econômicos", "% do PL", '<div id="g_grupos"></div>')}</div>`;

  $("#t_top").innerHTML = tabela([{ t: "Ativo", k: "ativo", w: 1 }, { t: "Grupo econômico", k: "grupo", w: 1 }, { t: "% PL", k: "perc", n: 1, f: (v) => pct(v) },
    { t: "Spread CDI+", k: "spread", n: 1, f: (v) => num(v) }, { t: "Duration", k: "duration", n: 1, f: (v) => num(v) }], C.top);
  const series = {};
  D.carteira.forEach((x, i) => x.cats.forEach((c) => { (series[c.categoria] ||= Array(D.carteira.length).fill(0))[i] = c.perc; }));
  const tops = categoriasPrincipais(series), cores = st.V.cat_cores;
  const agrup = tops.map((c, i) => ({ c, y: series[c], cor: cores[i % cores.length] }));
  agrup.push({ c: "Outros", y: ms.map((_, i) => Object.entries(series).filter(([c]) => !tops.includes(c)).reduce((s, [, y]) => s + (y[i] || 0), 0)), cor: "#9aa0a6" });
  plota($("#g_aloc"), agrup.map((a) => ({ x: ms.map((m) => m + "-15"), y: a.y, name: a.c, stackgroup: "a", line: { width: 0.5, color: css("--surface") },
    fillcolor: a.cor, hovertemplate: "%{y:.1f}%" })), layout({ yaxis: { ticksuffix: "%", gridcolor: css("--line") } }), 360);
  const sp = {};
  D.carteira.forEach((x, i) => x.cats.forEach((c) => { if (c.spread != null) (sp[c.categoria] ||= Array(D.carteira.length).fill(null))[i] = c.spread; }));
  plota($("#g_spread"), tops.filter((c) => sp[c]).map((c) => ({ x: ms.map((m) => m + "-15"), y: sp[c], name: c, mode: "lines+markers", connectgaps: false,
    line: { color: cores[tops.indexOf(c) % cores.length], width: 2 }, marker: { size: 4 }, hovertemplate: "%{y:.2f}%" })),
    layout({ yaxis: { ticksuffix: "%", gridcolor: css("--line") } }), 360);
  const g = C.grupos.slice().reverse();
  plota($("#g_grupos"), [{ type: "bar", orientation: "h", x: g.map((x) => x.perc), y: g.map((x) => x.grupo), marker: { color: cores[0] }, hovertemplate: "%{y}: %{x:.2f}% do PL<extra></extra>" }],
    layout({ hovermode: "closest", margin: { l: 8, r: 14, t: 6, b: 30 }, yaxis: { automargin: true, gridcolor: "rgba(0,0,0,0)" }, xaxis: { ticksuffix: "%", gridcolor: css("--line") } }), 400);
}

// ------------------------------------------------------------------ RETORNO
function periodoMeses(ms, chave) {
  if (!ms.includes(st[chave].de)) st[chave].de = ms[Math.max(0, ms.length - 12)];
  if (!ms.includes(st[chave].ate)) st[chave].ate = ms[ms.length - 1];
  const opt = (v) => ms.slice().reverse().map((m) => `<option value="${m}" ${m === v ? "selected" : ""}>${mesBR(m)}</option>`).join("");
  return `<label>De <select id="de">${opt(st[chave].de)}</select></label><label>até <select id="ate">${opt(st[chave].ate)}</select></label>
    ${[["6m", 6], ["12m", 12], ["24m", 24], ["No ano", "ano"], ["Tudo", 999]].map(([t, n]) => `<button class="botao" data-p="${n}">${t}</button>`).join("")}`;
}
function ligaPeriodo(ms, chave) {
  $("#de").onchange = (e) => { st[chave].de = e.target.value; desenha(); };
  $("#ate").onchange = (e) => { st[chave].ate = e.target.value; desenha(); };
  document.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => {
    const ult = ms[ms.length - 1], n = b.dataset.p;
    st[chave].ate = ult;
    st[chave].de = n === "ano" ? (ms.find((m) => m.startsWith(ult.slice(0, 4))) || ms[0]) : ms[Math.max(0, ms.length - +n)];
    desenha();
  }));
}
function estatPeriodo(f, i0, i1) {
  // retorno, vol anual e drawdown da cota entre os indices i0..i1 de V.datas (precisa existir no inicio e no fim)
  const c = f.cota; if (!c || !c.length) return null;
  let a = i0; while (a <= i1 && c[a] == null) a++;
  if (a > i0 + 6 || a > i1) return null;
  let b = i1; while (b > a && c[b] == null) b--;
  if (b < i1 - 6) return null;
  const rets = []; let pico = c[a], dd = 0, ant = c[a];
  for (let k = a + 1; k <= b; k++) { if (c[k] == null) continue; rets.push(Math.log(c[k] / ant)); ant = c[k]; pico = Math.max(pico, c[k]); dd = Math.min(dd, c[k] / pico - 1); }
  const m = rets.reduce((s, x) => s + x, 0) / Math.max(rets.length, 1);
  const vol = Math.sqrt(rets.reduce((s, x) => s + (x - m) ** 2, 0) / Math.max(rets.length - 1, 1) * 252);
  const cdi = st.V.cdi[b] / st.V.cdi[a] - 1, ret = c[b] / c[a] - 1;
  return { ret: ret * 100, cdi: cdi * 100, pcdi: cdi ? (ret / cdi) * 100 : null, vol: vol * 100, dd: dd * 100 };
}
function indicesDatas(de, ate) {
  const D = st.V.datas;
  let i0 = D.findIndex((d) => d >= de); if (i0 < 0) i0 = D.length - 1;
  let i1 = D.length - 1; while (i1 > 0 && D[i1] > ate) i1--;
  return [Math.max(0, i0 - 1), i1];   // inclui a cota do dia anterior ao inicio (retorno do 1o dia)
}
async function retorno(el) {
  const f = fundoPor(st.fundo);
  cabecalhoFundo(el, f);
  if (!f.tem_carteira) { $("#corpo").innerHTML = `<div class="vazio">A CVM não tem carteira deste fundo no período.</div>`; return; }
  $("#corpo").innerHTML = `<div class="vazio">Carregando ${esc(f.nome)}...</div>`;
  const D = await detalhe(f.id);
  if (st.fundo !== f.id || st.aba !== "retorno") return;
  const R = D.retorno, ms = R.meses.map((x) => x.mes);
  if (!ms.length) { $("#corpo").innerHTML = `<div class="vazio">Sem meses suficientes para calcular retorno.</div>`; return; }
  $("#ctl").insertAdjacentHTML("beforeend", periodoMeses(ms, "ret"));
  ligaPeriodo(ms, "ret");
  const j0 = ms.indexOf(st.ret.de), j1 = ms.indexOf(st.ret.ate);
  const [a, b] = j0 <= j1 ? [j0, j1] : [j1, j0];
  const J = Array.from({ length: b - a + 1 }, (_, k) => a + k);
  const tot = J.reduce((p, j) => p * (1 + R.meses[j].real / 100), 1) - 1, cdi = J.reduce((p, j) => p * (1 + R.meses[j].cdi / 100), 1) - 1;
  const linhas = Object.entries(R.categorias).map(([c, v]) => {
    let contrib = 0, ret = 1, nP = 0, sP = 0, nR = 0;
    J.forEach((j) => { const cc = v.contrib[j] || 0, p = v.peso[j] || 0; contrib += cc; if (p > 0.05) { ret *= 1 + cc / p; nR++; } sP += p; nP++; });
    return { categoria: c, peso: sP / Math.max(nP, 1), contrib, ret: nR ? (ret - 1) * 100 : null, pcdi: nR && cdi ? ((ret - 1) / cdi) * 100 : null };
  }).filter((r) => Math.abs(r.peso) > 0.05 || Math.abs(r.contrib) > 0.005).sort((x, y) => y.contrib - x.contrib);
  linhas.push({ _cls: "total", categoria: "Fundo (retorno da cota)", peso: 100, contrib: tot * 100, ret: tot * 100, pcdi: cdi ? (tot / cdi) * 100 : null });
  const somaAt = {};
  R.contrib.forEach(([ia, jm, v]) => { if (jm >= a && jm <= b) somaAt[ia] = (somaAt[ia] || 0) + v; });
  const ativos = Object.entries(somaAt).map(([ia, v]) => ({ ...R.ativos[ia], contrib: v }));
  const melhores = ativos.slice().sort((x, y) => y.contrib - x.contrib).slice(0, 10), piores = ativos.slice().sort((x, y) => x.contrib - y.contrib).slice(0, 5);
  const hedge = J.reduce((s, j) => s + (R.meses[j].hedge || 0), 0);

  $("#corpo").innerHTML = `<div class="kpis">${kpi("Retorno do fundo", pct(tot * 100), `${mesBR(ms[a])} a ${mesBR(ms[b])}`, cls(tot))}${kpi("CDI", pct(cdi * 100), "mesmo período")}
      ${kpi("% do CDI", pct(cdi ? (tot / cdi) * 100 : null, 1), "")}${kpi("Excesso sobre o CDI", pp((tot - cdi) * 100), "", cls(tot - cdi))}${kpi("Derivativos", pp(hedge), "já alocado nos ativos protegidos", cls(hedge))}</div>` +
    cartao("Retorno por categoria", "Contribuição em pontos percentuais do PL; retorno e % do CDI da própria categoria no período", tabela([
      { t: "Categoria", k: "categoria", w: 1 }, { t: "Peso médio", k: "peso", n: 1, f: (v) => pct(v, 1) }, { t: "Contribuição", k: "contrib", n: 1, f: (v) => `<span class="${cls(v)}">${pp(v)}</span>` },
      { t: "Retorno", k: "ret", n: 1, f: (v) => pct(v) }, { t: "% do CDI", k: "pcdi", n: 1, f: (v) => pct(v, 0) }], linhas) +
      `<p class="nota">Estimado com as carteiras mensais da CVM: variação de preço das posições + carrego do caixa + derivativos (futuro de DAP → ativos IPCA+, DI1 → prefixados, dólar → ativos no exterior, estimados pelas curvas do Tesouro, PTAX e IPCA) + a diferença para o retorno real da cota (taxas, negociação, marcação fora do esperado) distribuída nas categorias pelo peso. Cada ativo rende CDI + seu spread, ou a variação real de preço quando ela é crível. A soma das categorias fecha com o retorno real da cota.</p>`) +
    `<div class="grade g-tabela">${cartao("Ativos que mais contribuíram", `${mesBR(ms[a])} a ${mesBR(ms[b])}`, '<div id="t_mel"></div><h3 style="margin-top:14px">Piores</h3><div id="t_pio"></div>')}
      ${cartao("Risco x retorno: todos os fundos", "Mesmo período · laranja = nossos · cinza = peers", '<div id="g_rr"></div>')}</div>`;
  const cols = [{ t: "Ativo", k: "ativo", w: 1 }, { t: "Grupo econômico", k: "grupo", w: 1 }, { t: "Categoria", k: "categoria", w: 1 },
    { t: "Contribuição", k: "contrib", n: 1, f: (v) => `<span class="${cls(v)}">${pp(v, 3)}</span>` }];
  $("#t_mel").innerHTML = tabela(cols, melhores);
  $("#t_pio").innerHTML = tabela(cols, piores);
  riscoRetorno($("#g_rr"), ms[a] + "-01", ms[b] + "-31", f.id);
}
function riscoRetorno(el, de, ate, destaque) {
  const [i0, i1] = indicesDatas(de, ate);
  const pts = st.V.fundos.map((f) => ({ f, e: estatPeriodo(f, i0, i1) })).filter((x) => x.e);
  const grupo = (arr, nome, cor, tam, linha) => ({ type: "scatter", mode: "markers+text", name: nome, x: arr.map((p) => p.e.vol), y: arr.map((p) => p.e.pcdi),
    text: arr.map((p) => (p.f.nosso || p.f.id === destaque ? p.f.nome : "")), textposition: "top center", textfont: { size: 11, color: css("--text-1") },
    customdata: arr.map((p) => [p.f.nome, p.e.ret]), marker: { size: tam, color: cor, line: linha, opacity: 0.9 },
    hovertemplate: "%{customdata[0]}<br>retorno %{customdata[1]:.2f}% · %{y:.1f}% do CDI · vol %{x:.2f}%<extra></extra>" });
  const peers = pts.filter((p) => !p.f.nosso && p.f.id !== destaque), nossos = pts.filter((p) => p.f.nosso && p.f.id !== destaque), sel = pts.filter((p) => p.f.id === destaque);
  const dados = [grupo(peers, "Peers", "#9aa0a6", 10, { width: 0 }), grupo(nossos, "Nossos", "#eb6834", 10, { width: 0 })];
  if (sel.length) dados.push(grupo(sel, "Selecionado", sel[0].f.nosso ? "#eb6834" : "#9aa0a6", 13, { width: 2.5, color: css("--text-1") }));
  plota(el, dados, layout({ hovermode: "closest", legend: { orientation: "h", y: -0.2 }, xaxis: { title: "volatilidade anual (%)", gridcolor: css("--line"), zeroline: false },
    yaxis: { title: "% do CDI", gridcolor: css("--line"), zeroline: false } }), 420);
}

// ------------------------------------------------------------------ CONSOLIDADO
function consolidado(el) {
  const V = st.V, C = st.cons, ult = V.datas[V.datas.length - 1];
  if (!C.ate) C.ate = ult;
  if (!C.de) { const d = new Date(ult + "T12:00"); d.setFullYear(d.getFullYear() - 1); C.de = d.toISOString().slice(0, 10); }
  el.innerHTML = `<div class="cab"><div class="titulo-fundo"><h2>Consolidado</h2><p class="sub">Retorno de cada fundo no período · só fundos ativos do início ao fim do período</p></div>
    <div class="controles"><label>De <input type="date" id="cde" value="${C.de}" min="${V.datas[0]}" max="${ult}"></label><label>até <input type="date" id="cate" value="${C.ate}" min="${V.datas[0]}" max="${ult}"></label>
    ${[["12m", 12], ["24m", 24], ["No ano", "ano"], ["Tudo", "tudo"]].map(([t, n]) => `<button class="botao" data-q="${n}">${t}</button>`).join("")}</div></div>
    <div class="cartao"><div class="controles" style="margin-bottom:8px"><span class="sub" style="margin:0">Fundos:</span>
      <button class="botao" data-s="todos">Todos</button><button class="botao" data-s="nossos">Nossos</button><button class="botao" data-s="peers">Peers</button><button class="botao" data-s="nenhum">Limpar</button></div>
      <div class="multi" id="multi"></div></div>
    <div id="cc"></div>`;
  $("#cde").onchange = (e) => { C.de = e.target.value; desenha(); };
  $("#cate").onchange = (e) => { C.ate = e.target.value; desenha(); };
  document.querySelectorAll("[data-q]").forEach((b) => (b.onclick = () => {
    const d = new Date(ult + "T12:00"), q = b.dataset.q;
    C.ate = ult;
    C.de = q === "tudo" ? V.datas[0] : q === "ano" ? ult.slice(0, 4) + "-01-01" : (d.setMonth(d.getMonth() - +q), d.toISOString().slice(0, 10));
    desenha();
  }));
  document.querySelectorAll("[data-s]").forEach((b) => (b.onclick = () => {
    const s = b.dataset.s;
    C.sel = new Set(V.fundos.filter((f) => s === "todos" || (s === "nossos" && f.nosso) || (s === "peers" && !f.nosso)).map((f) => f.id));
    desenha();
  }));
  const multi = $("#multi");
  const chips = V.fundos.filter((f) => C.sel.has(f.id));
  multi.innerHTML = (chips.length > 24 ? `<span class="chip">${chips.filter((f) => f.nosso).length} nossos + ${chips.filter((f) => !f.nosso).length} peers selecionados</span>`
    : chips.map((f) => `<span class="chip ${f.nosso ? "nosso" : ""}">${esc(f.nome)}<button data-x="${f.id}" aria-label="Remover">×</button></span>`).join(""));
  multi.querySelectorAll("[data-x]").forEach((b) => (b.onclick = () => { C.sel.delete(b.dataset.x); desenha(); }));
  multi.appendChild(campoBusca((x) => { C.sel.add(x.id); desenha(); }, "Adicionar fundo: digite..."));

  const [i0, i1] = indicesDatas(C.de, C.ate);
  const linhas = [], fora = [];
  V.fundos.filter((f) => C.sel.has(f.id)).forEach((f) => { const e = estatPeriodo(f, i0, i1); (e ? linhas : fora).push({ f, ...(e || {}) }); });
  const cdiP = (V.cdi[i1] / V.cdi[i0] - 1) * 100;
  const ord = C.ord, sgn = C.asc ? 1 : -1;
  linhas.sort((x, y) => sgn * ((x[ord] ?? -1e9) - (y[ord] ?? -1e9)));
  $("#cc").innerHTML = cartao("Retorno acumulado", `${dataBR(V.datas[i0 + 1] || V.datas[i0])} a ${dataBR(V.datas[i1])} · CDI ${pct(cdiP)} · laranja = nossos · cinza = peers`, '<div id="g_cons"></div>') +
    cartao("Ranking no período", fora.length ? `${fora.length} fundo(s) selecionado(s) fora por não existirem no período inteiro: ${fora.map((x) => esc(x.f.nome)).join(", ")}` : "Clique no título da coluna para ordenar",
      tabela([{ t: "#", k: "_i" }, { t: "Fundo", k: "nome", w: 1, f: (v, r) => `${r.f.nosso ? '<span class="ponto" style="background:var(--nosso)"></span>' : '<span class="ponto" style="background:#9aa0a6"></span>'}${esc(r.f.nome)}` },
        { t: "Retorno", k: "ret", n: 1, ord: "ret", f: (v) => `<span class="${cls(v)}">${pct(v)}</span>` }, { t: "% do CDI", k: "pcdi", n: 1, ord: "pcdi", f: (v) => pct(v, 1) },
        { t: "Vol. anual", k: "vol", n: 1, ord: "vol", f: (v) => pct(v) }, { t: "Pior drawdown", k: "dd", n: 1, ord: "dd", f: (v) => pct(v) },
        { t: "PL (R$ mm)", k: "pl", n: 1, ord: "pl", f: (v) => num(v, 0) }],
        linhas.map((r, i) => ({ ...r, _i: i + 1, nome: r.f.nome, pl: r.f.pl, _cls: r.f.nosso ? "nosso" : "" }))));
  document.querySelectorAll("th[data-ord]").forEach((th) => (th.onclick = () => { if (C.ord === th.dataset.ord) C.asc = !C.asc; else { C.ord = th.dataset.ord; C.asc = false; } desenha(); }));
  const xs = V.datas.slice(i0, i1 + 1);
  const serie = (f) => { const c = f.cota.slice(i0, i1 + 1); let b = c.find((v) => v != null); return c.map((v) => (v == null ? null : (v / b - 1) * 100)); };
  const dados = linhas.filter((r) => !r.f.nosso).map((r) => ({ x: xs, y: serie(r.f), name: r.f.nome, mode: "lines", line: { color: "#9aa0a6", width: 1.2 }, opacity: 0.55, showlegend: false,
    hovertemplate: `${esc(r.f.nome)}: %{y:.2f}%<extra></extra>` }));
  linhas.filter((r) => r.f.nosso).forEach((r) => dados.push({ x: xs, y: serie(r.f), name: r.f.nome, mode: "lines", line: { color: r.f.cor, width: 2.8 }, hovertemplate: `${esc(r.f.nome)}: %{y:.2f}%<extra></extra>` }));
  const c0 = V.cdi[i0];
  dados.push({ x: xs, y: V.cdi.slice(i0, i1 + 1).map((v) => (v / c0 - 1) * 100), name: "CDI", mode: "lines", line: { color: css("--text-1"), width: 2, dash: "dash" }, hovertemplate: "CDI: %{y:.2f}%<extra></extra>" });
  plota($("#g_cons"), dados, layout({ hovermode: "closest", yaxis: { ticksuffix: "%", gridcolor: css("--line") } }), 460);
}

</script>
</body>
</html>
"""


def gera_excel():
    CNPJ = {n: cnpj_of(x) for n, x in {**NOSSOS_FUNDOS, **PEERS}.items()}
    meses, dia = prepara(sorted(CNPJ.values()), DESDE)
    print(f"{len(meses)} meses de carteira ({meses[0]} a {meses[-1]})")
    df = lookthrough(CNPJ, meses)
    soma = df[~df.derivativo].groupby(["fundo", "mes"]).perc_pl.sum()
    print("soma do %PL por carteira (sem derivativos): min", round(soma.min(), 3), "max", round(soma.max(), 3))
    grandes = df[df.categoria.eq(AJUSTE) & (df.perc_pl.abs() > 1)]
    if len(grandes):
        print("ajustes carteira x PL acima de 1% do peer (veiculo onde a CDA nao fecha com o PL):")
        print(grandes.groupby(["fundo", "veiculo"]).perc_pl.agg(["count", "min", "max"]).round(2).to_string())
    cruz = df[df.cnpj_veiculo.isin(CNPJ.values()) & (df.cnpj_veiculo != df.fundo.map(CNPJ))]
    print("peers investindo em outro peer:", "nenhum" if cruz.empty else sorted(set(zip(cruz.fundo, cruz.veiculo))))
    rent = rentabilidade(diario(CNPJ, dia), cdi_mensal(DESDE))
    excel(df, rent, list(CNPJ), OUT)
    print("salvo", OUT, "e", OUT.replace(".xlsx", "_dados.csv"), len(df), "linhas")


if __name__ == "__main__":                 # importante: os processos auxiliares do Windows reimportam este arquivo
    if len(sys.argv) > 1 and sys.argv[1].lower() == "excel":
        gera_excel()
    else:
        import webbrowser
        import uvicorn
        print(f"Preparando o painel: {len(NOSSOS_FUNDOS) + len(PEERS)} fundos desde {DESDE}. Na 1a vez pode levar bastante tempo...")
        precarrega(log=lambda m: print("  " + m, flush=True))
        if PRE["status"] != "ok":
            sys.exit("Nao foi possivel preparar o painel: " + str(PRE["erro"]))
        porta = int(os.environ.get("PORT", 7860))
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{porta}")).start()
        print(f"Pronto. Painel em http://localhost:{porta}  (deixe esta janela aberta; Ctrl+C para fechar)")
        uvicorn.run(app, host="127.0.0.1", port=porta, log_level="warning")
