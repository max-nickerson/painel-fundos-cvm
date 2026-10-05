"""
PAINEL DE FUNDOS - um arquivo so (dados abertos CVM + ANBIMA + Banco Central).

Como usar em qualquer computador:
  1) Instale o Python 3.11+ (python.org; no Windows marque "Add python.exe to PATH").
  2) No terminal:   pip install fastapi uvicorn pandas numpy requests pyarrow openpyxl
  3) Salve este arquivo como painel.py e rode:   python painel.py
     -> abre o painel no navegador em http://localhost:7860
  Excel em vez do painel:   python painel.py excel   (fundos em PEERS, abaixo)

Fontes: CVM (CDA mensal, informe diario, cadastro), ANBIMA (debentures), Banco Central (CDI). Tudo publico e gratuito.
A 1a carga de um fundo/periodo baixa arquivos da CVM (alguns minutos); depois fica em cache na pasta do usuario.
"""
import sys
import io
import json
import os
import re
import tempfile
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import requests

PEERS = {                       # nome: CNPJ (qualquer formato) ou link do Mais Retorno
    "DUAL": "34.803.938/0001-61",
    "AZ_ALTRO": "22.100.009/0001-07",
    "SPARTA_TOP": "14.188.162/0001-00",
    "XP_CE120": "22.003.930/0001-31",
    "CAPITANIA_P45": "20.146.294/0001-71",
}
DESDE = "2019-01"               # primeiro mes (CDA existe desde 2005; quanto mais antigo, mais download na 1a vez)
OUT = "lookthrough_cvm.xlsx"
WORKERS = 4

URL = "https://dados.cvm.gov.br/dados/FI/DOC"
CACHE = Path(os.environ.get("CVM_CACHE") or Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "cvm_cache")
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


def prepara(cnpjs, desde, workers=WORKERS, log=print):
    """Baixa/recorta da CVM so o que falta. Devolve (meses de carteira, {arquivo diario: meses})."""
    cda, dia = arquivos("CDA", desde), arquivos("INF_DIARIO", desde)
    for u in [u for u in cda if "HIST" not in u][-3:] + [u for u in dia if "HIST" not in u][-2:]:
        loc = CACHE / u.rsplit("/", 1)[1]           # meses recentes: a CVM republica conforme os fundos entregam
        try:
            if loc.exists() and pd.Timestamp(requests.head(u, timeout=60).headers["Last-Modified"]).timestamp() > loc.stat().st_mtime:
                loc.unlink()
                for m in (cda.get(u) or dia.get(u)):
                    for j in CACHE.glob(f"rec/*_{m}.json"):
                        j.unlink()
        except (requests.RequestException, KeyError, OSError):
            pass
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


def lookthrough(nomes, meses):
    """nomes: {nome: cnpj}. Uma linha por ativo final x caminho, com % do PL do peer e movimentacao do mes."""
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


def cdi_mensal(desde, diario=False):
    cdi, hoje = [], pd.Timestamp.today()
    for a in range(int(desde[:4]), hoje.year + 1, 9):         # API do BC: no maximo 10 anos por consulta
        fim = min(pd.Timestamp(a + 8, 12, 31), hoje).strftime("%d/%m/%Y")
        for tent in range(5):
            try:
                cdi += requests.get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados", timeout=60,
                                    params={"formato": "json", "dataInicial": f"01/01/{a}", "dataFinal": fim}).json()
                break
            except (requests.RequestException, ValueError):
                time.sleep(5 * (tent + 1))
    cdi = pd.DataFrame(cdi)
    s = pd.Series(cdi.valor.astype(float).values / 100, index=pd.to_datetime(cdi.data, dayfirst=True))
    return s if diario else (1 + s).groupby(s.index.strftime("%Y-%m")).prod() - 1


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


# ====================================================================== servidor + pagina

import hashlib
import io
import math
import os
import threading
import unicodedata
import uuid
import zipfile
from collections import OrderedDict

import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response


CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
CINZA = "#898781"
CONTABIL = r"(?i)pagar|receber|obriga|termo|disponibilidade|exigibilidade|swap|confidencial|ajuste"
app = FastAPI(title="Painel de fundos CVM")

JOBS, RESULTADOS, LOCK = {}, OrderedDict(), threading.Lock()
CAD = {"df": None, "erro": None}


# ------------------------------------------------------------------ cadastro (busca por nome/CNPJ)
def _sem_acento(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()


def carrega_cadastro():
    try:
        r = requests.get("https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip", timeout=300)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        c = pd.read_csv(z.open("registro_classe.csv"), sep=";", encoding="latin1", dtype=str, quoting=3,
                        usecols=["CNPJ_Classe", "Denominacao_Social", "Situacao"])
        c.columns = ["cnpj", "nome", "situacao"]
        a = pd.read_csv("https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv", sep=";", encoding="latin1", dtype=str,
                        quoting=3, usecols=["CNPJ_FUNDO", "DENOM_SOCIAL", "SIT"])
        a.columns = ["cnpj", "nome", "situacao"]
        c = pd.concat([c, a]).dropna(subset=["cnpj", "nome"])
        c["cnpj"] = c.cnpj.map(lt.fmt)
        c["ativo"] = ~c.situacao.fillna("").str.upper().str.contains("CANCEL")
        c = c.sort_values("ativo", ascending=False).drop_duplicates("cnpj")
        c["chave"] = c.nome.map(_sem_acento) + " " + c.cnpj.str.replace(r"\D", "", regex=True)
        CAD["df"] = c.reset_index(drop=True)
    except Exception as e:                                  # sem cadastro a busca por CNPJ continua funcionando
        CAD["erro"] = f"{type(e).__name__}: {e}"




@app.get("/api/busca")
def busca(q: str = ""):
    q = q.strip()
    dig = "".join(ch for ch in q if ch.isdigit())
    c = CAD["df"]
    if c is None:
        return [{"cnpj": lt.fmt(dig), "nome": "(cadastro carregando) " + lt.fmt(dig), "ativo": True}] if len(dig) == 14 else []
    if len(q) < 2:
        return []
    toks = _sem_acento(q).split()
    m = pd.Series(True, index=c.index)
    for t in toks:
        m &= c.chave.str.contains(t, regex=False)
    r = c[m].head(25)
    return [{"cnpj": x.cnpj, "nome": x.nome, "ativo": bool(x.ativo)} for x in r.itertuples()]


@app.get("/api/padrao")
def padrao():
    nomes = dict(zip(CAD["df"].cnpj, CAD["df"].nome)) if CAD["df"] is not None else {}
    return [{"cnpj": lt.cnpj_of(x), "nome": nomes.get(lt.cnpj_of(x), n), "curto": n} for n, x in lt.PEERS.items()]


# ------------------------------------------------------------------ helpers de serializacao
def limpo(o):
    if isinstance(o, dict):
        return {str(k): limpo(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [limpo(v) for v in o]
    if isinstance(o, (np.integer,)):
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


def registros(df, cols=None):
    df = df if cols is None else df[cols]
    return [dict(zip(df.columns, r)) for r in df.itertuples(index=False)]


def wavg(x, col, w="perc_pl"):
    ok = x[col].notna() & x[w].gt(0)
    return float(np.average(x.loc[ok, col], weights=x.loc[ok, w])) if ok.any() else None


def curto(nome):
    n = nome.upper()
    for a, b in [("FUNDO DE INVESTIMENTO FINANCEIRO", "FIF"), ("FUNDO DE INVESTIMENTO EM COTAS DE FUNDOS DE INVESTIMENTO", "FIC FI"),
                 ("FUNDO DE INVESTIMENTO", "FI"), ("MULTIMERCADO", "MM"), ("CRÉDITO PRIVADO", "CP"), ("RENDA FIXA", "RF"),
                 ("RESPONSABILIDADE LIMITADA", "RL"), ("RESP LIMITADA", "RL"), ("LONGO PRAZO", "LP")]:
        n = n.replace(a, b)
    return n[:30].strip()


# ------------------------------------------------------------------ montagem de tudo que o painel mostra
def monta(fundos, desde, log):
    """fundos: lista de (nome curto, cnpj). Devolve um dicionario JSON com todas as abas."""
    workers = max(1, min(4, (os.cpu_count() or 2)))
    meses, dia = lt.prepara(sorted(c for _, c in fundos), desde, workers=workers, log=log)
    nomes = dict(fundos)
    ordem = [n for n, _ in fundos]
    log("Montando look-through e indicadores...")
    df = lt.lookthrough(nomes, meses) if meses else pd.DataFrame()
    d = lt.diario(nomes, dia)
    cdi = lt.cdi_mensal(desde, diario=True)
    cdi_m = (1 + cdi).groupby(cdi.index.strftime("%Y-%m")).prod() - 1
    an_u, an_h = lt.anbima_debentures()
    out = {"meta": {"desde": desde, "fundos": [{"nome": n, "cnpj": c, "cor": CORES[i % 8]} for i, (n, c) in enumerate(fundos)],
                    "anbima_data": an_u.data.iloc[0].strftime("%Y-%m-%d") if len(an_u) else None,
                    "anbima_dias": int(an_h.data.nunique()) if len(an_h) else 0}}

    cart = df[~df.derivativo] if len(df) else df
    ult_mes = cart.groupby("fundo").mes.max() if len(cart) else pd.Series(dtype=str)
    ult = cart[cart.mes == cart.fundo.map(ult_mes)] if len(cart) else cart
    aberto = lt.mes_aberto(df) if len(df) else pd.Series(dtype=str)
    media = (cart[~cart.categoria.str.contains(CONTABIL)].groupby(["fundo", "mes", "categoria"]).perc_pl.sum()
             .groupby("categoria").mean().sort_values(ascending=False)) if len(cart) else pd.Series(dtype=float)
    top_cat = media.index[:7].tolist()
    out["categorias"] = {c: CORES[i] for i, c in enumerate(top_cat)} | {"Outros": CINZA}
    cat7 = lambda s: s.where(s.isin(top_cat), "Outros")
    rent = lt.rentabilidade(d, cdi_m) if len(d) else pd.DataFrame(columns=["fundo", "mes", "retorno", "cdi", "pct_cdi"])

    # ---- cotas, KPIs
    kp, cotas = [], {}
    for f in ordem:
        x = d[d.fundo == f]
        q = x.set_index("data").VL_QUOTA.dropna()
        if q.empty:
            continue
        fim = q.index[-1]
        ini = q[q.index <= fim - pd.Timedelta(days=365)]
        base = ini.index[-1] if len(ini) else q.index[0]
        r12, c12 = q.iloc[-1] / q[base] - 1, (1 + cdi[(cdi.index > base) & (cdi.index <= fim)]).prod() - 1
        ano = q[q.index < pd.Timestamp(fim.year, 1, 1)]
        u = ult[ult.fundo == f]
        x12 = x[x.data > base]
        kp.append({"fundo": f, "pl_mi": x.VL_PATRIM_LIQ.iloc[-1] / 1e6, "ret12": r12 * 100, "pct_cdi12": r12 / c12 * 100 if c12 else None,
                   "ret_ano": (q.iloc[-1] / ano.iloc[-1] - 1) * 100 if len(ano) else None,
                   "vol": q[q.index > base].pct_change().std() * np.sqrt(252) * 100, "dd": (q / q.cummax() - 1).min() * 100,
                   "capt12_mi": (x12.CAPTC_DIA.sum() - x12.RESG_DIA.sum()) / 1e6, "cotistas": x.NR_COTST.iloc[-1],
                   "ativos": u.chave.nunique() if len(u) else None,
                   "top10_emissores": u.groupby("emissor").perc_pl.sum().nlargest(10).sum() if len(u) else None,
                   "ult_carteira": ult_mes.get(f), "carteira_aberta": aberto.get(f), "ult_cota": fim.strftime("%Y-%m-%d")})
        cotas[f] = {"datas": [t.strftime("%Y-%m-%d") for t in q.index], "acum": ((q / q.iloc[0] - 1) * 100).tolist(),
                    "dd": ((q / q.cummax() - 1) * 100).tolist(), "pl": (x.set_index("data").VL_PATRIM_LIQ / 1e6).reindex(q.index).tolist(),
                    "cotistas": x.set_index("data").NR_COTST.reindex(q.index).tolist()}
    out["kpis"], out["cotas"] = kp, cotas
    c0 = cdi[cdi.index >= d.data.min()] if len(d) else cdi.iloc[:0]
    out["cdi"] = {"datas": [t.strftime("%Y-%m-%d") for t in c0.index], "acum": (((1 + c0).cumprod() - 1) * 100).tolist()}
    cap = d.groupby(["fundo", "mes"]).apply(lambda x: (x.CAPTC_DIA.sum() - x.RESG_DIA.sum()) / 1e6, include_groups=False).rename("capt_mi")
    out["mensal"] = registros(rent.join(cap, on=["fundo", "mes"])[["fundo", "mes", "retorno", "cdi", "pct_cdi", "capt_mi"]]) if len(rent) else []

    # ---- por fundo: alocacao, carteira, credito, movimentos, derivativos, marcacao
    por = {}
    for f in [f for f in ordem if f in set(cart.fundo)] if len(cart) else []:
        g, gd = cart[cart.fundo == f], df[df.fundo == f]
        u = ult[ult.fundo == f]
        ev = g.assign(c=cat7(g.categoria)).pivot_table(index="mes", columns="c", values="perc_pl", aggfunc="sum", fill_value=0)
        p = {"ult_mes": ult_mes.get(f), "mes_aberto": aberto.get(f),
             "alocacao": {"meses": ev.index.tolist(), "series": {c: ev[c].tolist() for c in top_cat + ["Outros"] if c in ev}},
             "emissores": registros(u.groupby("emissor").perc_pl.sum().nlargest(15).reset_index())}
        cp = (u.groupby(["categoria", "ativo", "codigo", "emissor"], dropna=False)
              .agg(perc_pl=("perc_pl", "sum"), veiculo=("veiculo", "first")).reset_index().sort_values("perc_pl", ascending=False))
        p["carteira"] = registros(cp)

        # credito (ultima carteira aberta) + ANBIMA
        ma = aberto.get(f, ult_mes.get(f))
        ua = g[g.mes == ma]
        deb = ua[ua.categoria.eq("Debêntures")]
        cols = ["codigo", "indice", "tipo", "taxa_ind", "duration_anos", "pct_par", "venc"]
        deb = deb.merge(an_u[cols], on="codigo", how="left") if len(an_u) else deb.assign(**{c: np.nan for c in cols[1:]})
        com = deb[deb.taxa_ind.notna()]
        hist = {}
        if len(an_h) and an_h.data.nunique() > 1 and len(com):
            evh = deb[["codigo", "perc_pl"]].merge(an_h[["data", "codigo", "tipo", "taxa_ind", "duration_anos"]], on="codigo")
            s1 = evh[evh.tipo == "DI +"].groupby("data").apply(lambda x: wavg(x, "taxa_ind"), include_groups=False)
            s2 = evh.groupby("data").apply(lambda x: wavg(x, "duration_anos"), include_groups=False)
            hist = {"datas": [t.strftime("%Y-%m-%d") for t in s2.index], "spread_di": s1.reindex(s2.index).tolist(), "duration": s2.tolist()}
        o = ua[~ua.categoria.str.contains(CONTABIL)].copy()
        venc = pd.to_datetime(o.vencimento, errors="coerce")
        o["prazo"] = (venc - (pd.to_datetime(o.mes) + pd.offsets.MonthEnd(0))).dt.days / 365.25
        faixa = pd.cut(o.prazo, [-1, 1, 2, 3, 5, 100], labels=["até 1a", "1-2a", "2-3a", "3-5a", "5a+"]).astype(str).replace("nan", "s/ venc.")
        resumo = o.groupby("categoria").apply(lambda x: pd.Series({
            "perc_pl": x.perc_pl.sum(), "perc_com_taxa": x[x.pct_indexador.notna() | x.cupom.notna() | x.taxa_pre.notna()].perc_pl.sum(),
            "pct_indexador": wavg(x, "pct_indexador"), "cupom": wavg(x, "cupom"), "taxa_pre": wavg(x, "taxa_pre"),
            "prazo": wavg(x, "prazo")}), include_groups=False).reset_index().sort_values("perc_pl", ascending=False)
        p["credito"] = {
            "mes": ma, "deb_pl": deb.perc_pl.sum(), "cobertura": com.perc_pl.sum() / deb.perc_pl.sum() * 100 if deb.perc_pl.sum() else None,
            "spread_di": wavg(com[com.tipo == "DI +"], "taxa_ind"), "pl_di": com[com.tipo == "DI +"].perc_pl.sum(),
            "taxa_ipca": wavg(com[com.tipo == "IPCA +"], "taxa_ind"), "pl_ipca": com[com.tipo == "IPCA +"].perc_pl.sum(),
            "duration": wavg(com, "duration_anos"),
            "por_tipo": registros(deb.assign(t=deb.tipo.fillna("sem taxa ANBIMA")).groupby("t").perc_pl.sum().reset_index()),
            "debs": registros(deb.sort_values("perc_pl", ascending=False),
                              ["ativo", "codigo", "perc_pl", "indice", "tipo", "taxa_ind", "duration_anos", "pct_par", "venc", "veiculo"]),
            "hist": hist,
            "indexador": registros(o.groupby(o.indexador.fillna("não informado na CDA")).perc_pl.sum().reset_index().rename(columns={"indexador": "k"})),
            "prazo": registros(o.groupby(faixa).perc_pl.sum().reindex(["até 1a", "1-2a", "2-3a", "3-5a", "5a+", "s/ venc."]).fillna(0)
                               .rename_axis("k").reset_index()),
            "rating": registros(o.groupby(o.rating.fillna("sem rating")).perc_pl.sum().rename_axis("k").reset_index()),
            "resumo": registros(resumo)}

        # movimentacoes
        giro = g.groupby("mes").agg(c=("compra_pct", "sum"), v=("venda_pct", "sum"))
        ms = sorted(g.mes.unique())
        mv = {}
        for i, m in enumerate(ms):
            x = g[g.mes == m].groupby(["ativo", "categoria"]).agg(compra=("compra_pct", "sum"), venda=("venda_pct", "sum")).reset_index()
            e = {"compras": registros(x.nlargest(15, "compra")[["ativo", "categoria", "compra"]]),
                 "vendas": registros(x.nlargest(15, "venda")[["ativo", "categoria", "venda"]])}
            if i:
                a, b = set(g[g.mes == ms[i - 1]].chave), set(g[g.mes == m].chave)
                e |= {"novos": len(b - a), "pct_novos": g[(g.mes == m) & g.chave.isin(b - a)].perc_pl.sum(),
                      "zerados": len(a - b), "pct_zerados": g[(g.mes == ms[i - 1]) & g.chave.isin(a - b)].perc_pl.sum()}
            mv[m] = e
        p["movimentos"] = {"meses": giro.index.tolist(), "compras": giro.c.tolist(), "vendas": giro.v.tolist(), "por_mes": mv}

        # derivativos e moeda
        dv = gd[gd.derivativo]
        t = dv.pivot_table(index="mes", columns="tipo_ativo", values="perc_pl", aggfunc="sum", fill_value=0) if len(dv) else pd.DataFrame()
        fx = pd.DataFrame({"exterior": gd[gd.categoria.eq("Investimento no Exterior")].groupby("mes").perc_pl.sum(),
                           "dolar": dv[dv.tipo_ativo.fillna("").str.contains("(?i)dol|dólar")].groupby("mes").perc_pl.sum()}).fillna(0)
        p["derivativos"] = {"meses": t.index.tolist(), "series": {c: t[c].tolist() for c in t.columns},
                            "atual": registros(dv[dv.mes == dv.mes.max()].groupby(["categoria", "tipo_ativo", "ativo", "veiculo"])
                                               .perc_pl.sum().reset_index().sort_values("perc_pl")) if len(dv) else [],
                            "moeda": {"meses": fx.index.tolist(), "exterior": fx.exterior.tolist(), "dolar": fx.dolar.tolist()}}

        # marcacao estimada
        k = lt.contribuicao(g)
        if len(k):
            cc = k.assign(c=cat7(k.categoria)).pivot_table(index="mes", columns="c", values="resultado_pct", aggfunc="sum", fill_value=0)
            rr = rent[rent.fundo == f].set_index("mes").retorno.reindex(cc.index) * 100
            pm = {}
            for m in cc.index:
                km = k[k.mes == m].groupby(["ativo", "categoria"]).resultado_pct.sum().reset_index()
                pm[m] = {"altas": registros(km.nlargest(12, "resultado_pct")), "quedas": registros(km.nsmallest(12, "resultado_pct"))}
            tot = k.groupby(["ativo", "categoria"]).resultado_pct.sum().reset_index()
            p["marcacao"] = {"meses": cc.index.tolist(), "series": {c: cc[c].tolist() for c in top_cat + ["Outros"] if c in cc},
                             "real": rr.tolist(), "por_mes": pm, "periodo": {"altas": registros(tot.nlargest(15, "resultado_pct")),
                                                                            "quedas": registros(tot.nsmallest(15, "resultado_pct"))}}
        por[f] = p
    out["por_fundo"] = por

    # ---- comparacao
    if len(ult):
        pv = ult.pivot_table(index="categoria", columns="fundo", values="perc_pl", aggfunc="sum", fill_value=0)
        pv = pv.reindex(columns=[f for f in ordem if f in pv.columns])
        pv = pv.loc[pv.abs().max(axis=1).sort_values(ascending=False).index]
        e = ult.groupby(["fundo", "emissor"]).perc_pl.sum()
        comum = e.groupby(level=1).filter(lambda s: len(s) > 1).unstack(0).fillna(0)
        comum = comum.loc[comum.sum(axis=1).sort_values(ascending=False).index].head(30) if len(comum) else comum
        out["comparacao"] = {"alocacao": {"fundos": pv.columns.tolist(), "linhas": [[i] + r.tolist() for i, r in pv.iterrows()]},
                             "emissores": {"fundos": comum.columns.tolist(), "linhas": [[i] + r.tolist() for i, r in comum.iterrows()]}}
    else:
        out["comparacao"] = {"alocacao": {"fundos": [], "linhas": []}, "emissores": {"fundos": [], "linhas": []}}
    RESULTADOS_DF[_chave(fundos, desde)] = (df, d)
    while len(RESULTADOS_DF) > 6:
        RESULTADOS_DF.pop(next(iter(RESULTADOS_DF)))
    log("Pronto.")
    return limpo(out)


RESULTADOS_DF = {}


def _chave(fundos, desde):
    return hashlib.md5((desde + "|" + "|".join(sorted(c for _, c in fundos))).encode()).hexdigest()


def _roda(job, fundos, desde):
    try:
        res = monta(fundos, desde, JOBS[job]["log"].append)
        with LOCK:
            RESULTADOS[_chave(fundos, desde)] = res
            while len(RESULTADOS) > 12:
                RESULTADOS.popitem(last=False)
        JOBS[job]["status"] = "ok"
    except Exception as e:
        JOBS[job] |= {"status": "erro", "erro": f"{type(e).__name__}: {e}"}


@app.post("/api/carregar")
def carregar(body: dict):
    fundos = [(curto(x.get("curto") or x["nome"]), lt.fmt(x["cnpj"])) for x in body.get("fundos", [])][:8]
    if not fundos:
        raise HTTPException(400, "escolha ao menos um fundo")
    vistos, unicos = set(), []
    for n, c in fundos:                              # nomes curtos repetidos ganham sufixo
        while n in vistos:
            n += "*"
        vistos.add(n)
        unicos.append((n, c))
    desde = body.get("desde") or "2024-01"
    k = _chave(unicos, desde)
    if k in RESULTADOS:
        return {"job": None, "chave": k, "status": "ok"}
    job = uuid.uuid4().hex[:10]
    JOBS[job] = {"status": "rodando", "log": [], "chave": k}
    threading.Thread(target=_roda, args=(job, unicos, desde), daemon=True).start()
    return {"job": job, "chave": k, "status": "rodando"}


@app.get("/api/status/{job}")
def status(job: str):
    j = JOBS.get(job) or HTTPException(404)
    if isinstance(j, HTTPException):
        raise j
    return {"status": j["status"], "log": j["log"][-6:], "erro": j.get("erro"), "chave": j["chave"]}


@app.get("/api/resultado/{chave}")
def resultado(chave: str):
    if chave not in RESULTADOS:
        raise HTTPException(404, "resultado expirou; carregue de novo")
    return JSONResponse(RESULTADOS[chave])


@app.get("/api/csv/{chave}/{tipo}")
def csv(chave: str, tipo: str):
    if chave not in RESULTADOS_DF:
        raise HTTPException(404)
    df, d = RESULTADOS_DF[chave]
    x = df.drop(columns=["chave", "fator"], errors="ignore") if tipo == "carteira" else d
    return Response(x.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{tipo}.csv"'})


@app.get("/")
def index():
    return HTMLResponse(PAGINA)


lt = sys.modules[__name__]          # o codigo do servidor chama as funcoes de dados como lt.funcao
PAGINA = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel de fundos</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect x='4' y='16' width='5' height='12' rx='1' fill='%232a78d6'/><rect x='13' y='9' width='5' height='19' rx='1' fill='%231baf7a'/><rect x='22' y='4' width='5' height='24' rx='1' fill='%23eb6834'/></svg>">
<style>
:root {
  --surface-0: #f9f9f7; --surface-1: #fcfcfb; --surface-2: #f0efec;
  --text-1: #0b0b0b; --text-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --accent: #2a78d6; --accent-ink: #ffffff;
  --good: #006300; --bad: #d03b3b; --radius: 10px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface-0: #0d0d0d; --surface-1: #1a1a19; --surface-2: #262624;
    --text-1: #ffffff; --text-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --accent: #3987e5; --good: #0ca30c; --bad: #e66767;
  }
}
:root[data-theme="dark"] {
  --surface-0: #0d0d0d; --surface-1: #1a1a19; --surface-2: #262624;
  --text-1: #ffffff; --text-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --accent: #3987e5; --good: #0ca30c; --bad: #e66767;
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--surface-0); color: var(--text-1); font: 14px/1.45 Arial, Helvetica, sans-serif; }
.topo { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-bottom: 1px solid var(--grid); background: var(--surface-1); }
h1 { margin: 0; font-size: 20px; }
h2 { font-size: 16px; margin: 22px 0 8px; }
.sub, .nota, .legenda { color: var(--text-2); margin: 2px 0 0; font-size: 12.5px; }
.layout { display: grid; grid-template-columns: 300px minmax(0, 1fr); min-height: calc(100vh - 64px); }
.layout > * { min-width: 0; }
.painel { padding: 16px; border-right: 1px solid var(--grid); background: var(--surface-1); display: flex; flex-direction: column; gap: 8px; }
main { padding: 0 20px 40px; min-width: 0; }
.rot { font-size: 12.5px; color: var(--text-2); margin-top: 6px; }
input, select { width: 100%; padding: 9px 10px; border: 1px solid var(--axis); border-radius: 8px; background: var(--surface-0); color: var(--text-1); font: inherit; }
button { font: inherit; cursor: pointer; }
.primario { margin-top: 8px; padding: 10px; border: 0; border-radius: 8px; background: var(--accent); color: var(--accent-ink); font-weight: bold; }
.primario:disabled { opacity: .6; cursor: wait; }
.icone { border: 1px solid var(--axis); background: transparent; color: var(--text-1); border-radius: 8px; width: 36px; height: 36px; font-size: 18px; }
.busca-wrap { position: relative; }
.sugestoes { position: absolute; z-index: 10; left: 0; right: 0; top: 100%; margin: 4px 0 0; padding: 4px; list-style: none; max-height: 320px; overflow: auto;
  background: var(--surface-1); border: 1px solid var(--axis); border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,.12); }
.sugestoes li { padding: 7px 8px; border-radius: 6px; cursor: pointer; font-size: 12.5px; }
.sugestoes li:hover, .sugestoes li.ativo { background: var(--surface-2); }
.sugestoes small { color: var(--muted); display: block; }
.escolhidos { list-style: none; margin: 4px 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.escolhidos li { display: grid; grid-template-columns: 12px 1fr 24px; gap: 8px; align-items: center; padding: 7px 8px; border: 1px solid var(--grid); border-radius: 8px; background: var(--surface-0); }
.escolhidos .ponto { width: 12px; height: 12px; border-radius: 3px; }
.escolhidos input { padding: 3px 5px; font-size: 12.5px; font-weight: bold; border-color: transparent; background: transparent; }
.escolhidos input:focus { border-color: var(--axis); }
.escolhidos small { display: block; color: var(--muted); font-size: 11px; padding-left: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.escolhidos button { border: 0; background: transparent; color: var(--muted); font-size: 16px; }
.progresso { font-size: 12px; color: var(--text-2); background: var(--surface-0); border: 1px solid var(--grid); border-radius: 8px; padding: 8px; white-space: pre-wrap; max-height: 160px; overflow: auto; }
.abas { display: flex; gap: 2px; overflow-x: auto; border-bottom: 1px solid var(--grid); position: sticky; top: 0; background: var(--surface-0); z-index: 5; padding-top: 10px; }
.abas button { border: 0; background: transparent; color: var(--text-2); padding: 10px 12px; white-space: nowrap; border-bottom: 2px solid transparent; }
.abas button[aria-selected="true"] { color: var(--text-1); border-bottom-color: var(--accent); font-weight: bold; }
.conteudo { padding-top: 10px; }
.vazio { padding: 60px 0; text-align: center; color: var(--text-2); }
.seletor { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 4px; align-items: center; }
.seletor button { border: 1px solid var(--axis); background: var(--surface-1); color: var(--text-1); border-radius: 999px; padding: 5px 12px; font-size: 13px; display: inline-flex; gap: 6px; align-items: center; }
.seletor button[aria-pressed="true"] { border-color: var(--text-1); font-weight: bold; }
.seletor .ponto { width: 9px; height: 9px; border-radius: 2px; }
.seletor select { width: auto; padding: 5px 8px; }
.grade { display: grid; gap: 14px; }
.g2 { grid-template-columns: repeat(2, minmax(0, 1fr)); } .g3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.cartao { background: var(--surface-1); border: 1px solid var(--grid); border-radius: var(--radius); padding: 10px 12px; min-width: 0; }
.cartao h3 { margin: 2px 0 4px; font-size: 13.5px; }
.grafico { width: 100%; min-height: 320px; }
.kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin: 10px 0; }
.kpi { background: var(--surface-1); border: 1px solid var(--grid); border-radius: var(--radius); padding: 10px 12px; }
.kpi .r { font-size: 12px; color: var(--text-2); }
.kpi .v { font-size: 22px; font-weight: bold; margin-top: 2px; }
.kpi .s { font-size: 11.5px; color: var(--muted); }
.tabela-wrap { overflow: auto; max-height: 460px; border: 1px solid var(--grid); border-radius: var(--radius); background: var(--surface-1); }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
th, td { padding: 6px 9px; border-bottom: 1px solid var(--grid); text-align: left; white-space: nowrap; }
th { position: sticky; top: 0; background: var(--surface-2); color: var(--text-2); font-weight: bold; cursor: pointer; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
td.texto { white-space: normal; min-width: 240px; }
.filtro { max-width: 340px; margin: 6px 0; }
.aviso { background: var(--surface-2); border-radius: 8px; padding: 8px 10px; color: var(--text-2); font-size: 12.5px; margin: 8px 0; }
.links a { color: var(--accent); margin-right: 16px; }
@media (max-width: 900px) {
  .layout { grid-template-columns: minmax(0, 1fr); }
  html, body { overflow-x: hidden; }
  .painel { border-right: 0; border-bottom: 1px solid var(--grid); }
  main { padding: 0 16px 40px; }
  .g2, .g3 { grid-template-columns: minmax(0, 1fr); }
  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kpi .v { font-size: 19px; }
}

</style>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
</head>
<body>
<header class="topo">
  <div>
    <h1>Painel de fundos</h1>
    <p class="sub">Dados abertos: CVM (carteira mensal e informe diário), ANBIMA (debêntures) e Banco Central (CDI)</p>
  </div>
  <button id="tema" class="icone" title="Alternar tema claro/escuro" aria-label="Alternar tema">◐</button>
</header>
<div class="layout">
  <aside class="painel">
    <label for="busca" class="rot">Adicionar fundo (nome ou CNPJ)</label>
    <div class="busca-wrap">
      <input id="busca" type="search" placeholder="ex.: Kinea, Sparta, 34.803.938/0001-61" autocomplete="off">
      <ul id="sugestoes" class="sugestoes" hidden></ul>
    </div>
    <ul id="escolhidos" class="escolhidos"></ul>
    <label for="desde" class="rot">Carteiras desde</label>
    <select id="desde"></select>
    <button id="carregar" class="primario">Carregar</button>
    <div id="progresso" class="progresso" hidden></div>
    <p class="nota">A primeira carga de um fundo ou período baixa os arquivos da CVM e pode levar alguns minutos; depois fica em cache.</p>
  </aside>
  <main>
    <nav id="abas" class="abas" role="tablist"></nav>
    <section id="conteudo" class="conteudo"><div class="vazio">Escolha os fundos e clique em <b>Carregar</b>.</div></section>
  </main>
</div>
<script>
// Painel de fundos - frontend (sem framework). Dados vem de /api (server.py).
const $ = (s, el = document) => el.querySelector(s);
const CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const ABAS = ["Visão geral", "Rentabilidade", "PL & captação", "Alocação", "Crédito", "Movimentações",
  "Derivativos & moeda", "Marcação (estimada)", "Comparação", "Dados"];
const st = { escolhidos: [], R: null, chave: null, aba: 0, fundo: {}, mes: {} };
const nf = (d) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const num = (v, d = 2) => (v == null || Number.isNaN(v) ? "-" : nf(d).format(v));
const pct = (v, d = 2) => (v == null ? "-" : num(v, d) + "%");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// ------------------------------------------------------------------ tema
const tema = localStorage.getItem("tema");
if (tema) document.documentElement.dataset.theme = tema;
$("#tema").onclick = () => {
  const escuro = document.documentElement.dataset.theme === "dark" ||
    (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = escuro ? "light" : "dark";
  try { localStorage.setItem("tema", document.documentElement.dataset.theme); } catch (e) {}
  if (st.R) desenha();
};

// ------------------------------------------------------------------ escolha de fundos
function curto(nome) {
  let n = nome.toUpperCase();
  [["FUNDO DE INVESTIMENTO FINANCEIRO", "FIF"], ["FUNDO DE INVESTIMENTO", "FI"], ["MULTIMERCADO", "MM"],
   ["CRÉDITO PRIVADO", "CP"], ["RENDA FIXA", "RF"], ["RESPONSABILIDADE LIMITADA", "RL"], ["LONGO PRAZO", "LP"]]
    .forEach(([a, b]) => (n = n.replaceAll(a, b)));
  return n.slice(0, 22).trim();
}
function desenhaEscolhidos() {
  $("#escolhidos").innerHTML = st.escolhidos.map((f, i) => `<li>
    <span class="ponto" style="background:${CORES[i % 8]}"></span>
    <div><input value="${esc(f.curto)}" data-i="${i}" aria-label="Nome curto"><small title="${esc(f.nome)}">${esc(f.cnpj)} · ${esc(f.nome)}</small></div>
    <button data-x="${i}" title="Remover" aria-label="Remover">×</button></li>`).join("");
  $("#escolhidos").querySelectorAll("input").forEach((el) => (el.onchange = () => (st.escolhidos[el.dataset.i].curto = el.value.trim() || "Fundo")));
  $("#escolhidos").querySelectorAll("button").forEach((b) => (b.onclick = () => { st.escolhidos.splice(+b.dataset.x, 1); desenhaEscolhidos(); }));
}
let tBusca, sel = -1;
$("#busca").addEventListener("input", (e) => {
  clearTimeout(tBusca);
  const q = e.target.value;
  tBusca = setTimeout(async () => {
    if (q.length < 2) return ($("#sugestoes").hidden = true);
    const r = await (await fetch("/api/busca?q=" + encodeURIComponent(q))).json();
    sel = -1;
    $("#sugestoes").innerHTML = r.map((f) => `<li data-c="${esc(f.cnpj)}" data-n="${esc(f.nome)}">${esc(f.nome)}<small>${esc(f.cnpj)}${f.ativo ? "" : " · cancelado"}</small></li>`).join("")
      || "<li>Nada encontrado</li>";
    $("#sugestoes").hidden = false;
  }, 250);
});
$("#busca").addEventListener("keydown", (e) => {
  const li = [...$("#sugestoes").querySelectorAll("li[data-c]")];
  if (!li.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + li.length) % li.length;
    li.forEach((x, i) => x.classList.toggle("ativo", i === sel));
    e.preventDefault();
  } else if (e.key === "Enter" && sel >= 0) adiciona(li[sel]);
});
$("#sugestoes").addEventListener("click", (e) => { const li = e.target.closest("li[data-c]"); if (li) adiciona(li); });
function adiciona(li) {
  if (st.escolhidos.length >= 8) return alert("Máximo de 8 fundos por vez.");
  if (!st.escolhidos.some((f) => f.cnpj === li.dataset.c))
    st.escolhidos.push({ cnpj: li.dataset.c, nome: li.dataset.n, curto: curto(li.dataset.n) });
  $("#busca").value = ""; $("#sugestoes").hidden = true; desenhaEscolhidos();
}
document.addEventListener("click", (e) => { if (!e.target.closest(".busca-wrap")) $("#sugestoes").hidden = true; });

const hoje = new Date();
for (let a = hoje.getFullYear(); a >= 2005; a--) $("#desde").insertAdjacentHTML("beforeend", `<option value="${a}-01">jan/${a}</option>`);
$("#desde").value = `${hoje.getFullYear() - 2}-01`;
fetch("/api/padrao").then((r) => r.json()).then((p) => { st.escolhidos = p; desenhaEscolhidos(); });

// ------------------------------------------------------------------ carga (job em segundo plano)
$("#carregar").onclick = async () => {
  if (!st.escolhidos.length) return alert("Escolha ao menos um fundo.");
  const b = $("#carregar"); b.disabled = true; b.textContent = "Carregando...";
  const pr = $("#progresso"); pr.hidden = false; pr.textContent = "Iniciando...";
  try {
    const r = await (await fetch("/api/carregar", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fundos: st.escolhidos, desde: $("#desde").value }) })).json();
    let chave = r.chave;
    if (r.job) {
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 2000));
        const s = await (await fetch("/api/status/" + r.job)).json();
        pr.textContent = s.log.join("\n") || "Baixando arquivos da CVM...";
        if (s.status === "erro") throw new Error(s.erro);
        if (s.status === "ok") break;
      }
    }
    st.R = await (await fetch("/api/resultado/" + chave)).json(); st.chave = chave;
    st.fundo = {}; st.mes = {};
    pr.textContent = "Pronto."; setTimeout(() => (pr.hidden = true), 1500);
    desenhaAbas(); desenha();
  } catch (e) { pr.textContent = "Erro: " + e.message; }
  b.disabled = false; b.textContent = "Carregar";
};

// ------------------------------------------------------------------ graficos
function base(titulo, extra = {}) {
  return Object.assign({
    title: { text: titulo, font: { size: 14, color: css("--text-1") }, x: 0, xanchor: "left" },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Arial", size: 12, color: css("--text-2") },
    margin: { l: 50, r: 10, t: 40, b: 40 }, hovermode: "x unified",
    legend: { orientation: "h", y: -0.18, font: { color: css("--text-2") } },
    xaxis: { gridcolor: "rgba(0,0,0,0)", linecolor: css("--axis"), automargin: true },
    yaxis: { gridcolor: css("--grid"), zerolinecolor: css("--axis"), automargin: true },
    hoverlabel: { bgcolor: css("--surface-1"), font: { color: css("--text-1") } },
  }, extra);
}
function plota(id, dados, layout, h = 340) {
  const el = document.getElementById(id); if (!el) return;
  el.style.height = h + "px";
  Plotly.newPlot(el, dados, layout, { displaylogo: false, responsive: true, displayModeBar: innerWidth > 700 ? "hover" : false,
    modeBarButtonsToRemove: ["lasso2d", "select2d"] });
}
const cor = (f) => (st.R.meta.fundos.find((x) => x.nome === f) || {}).cor || CORES[0];
const corCat = (c) => st.R.categorias[c] || "#898781";
const barH = (rows, xk, yk, c, titulo) => ({ d: [{ type: "bar", orientation: "h", x: rows.map((r) => r[xk]).reverse(), y: rows.map((r) => r[yk]).reverse(),
  marker: { color: c }, hovertemplate: "%{y}<br>%{x:.3f}% do PL<extra></extra>" }], l: base(titulo, { hovermode: "closest", margin: { l: 10, r: 10, t: 40, b: 30 },
  yaxis: { automargin: true, gridcolor: "rgba(0,0,0,0)", tickfont: { size: 11 } }, xaxis: { gridcolor: css("--grid"), ticksuffix: "%" } }) });
function tabela(cols, linhas, alt = 460) {
  return `<div class="tabela-wrap" style="max-height:${alt}px"><table><thead><tr>${cols.map((c) => `<th class="${c.n ? "n" : ""}">${c.t}</th>`).join("")}</tr></thead><tbody>${
    linhas.map((r) => `<tr>${cols.map((c) => { const v = r[c.k]; return `<td class="${c.n ? "n" : c.w ? "texto" : ""}">${c.f ? c.f(v, r) : esc(v ?? "-")}</td>`; }).join("")}</tr>`).join("")
  }</tbody></table></div>`;
}
function seletorFundo(aba) {
  const fs = st.R.meta.fundos.filter((f) => st.R.por_fundo[f.nome]);
  if (!fs.length) return "";
  st.fundo[aba] = st.fundo[aba] && st.R.por_fundo[st.fundo[aba]] ? st.fundo[aba] : fs[0].nome;
  return `<div class="seletor" data-aba="${aba}">${fs.map((f) => `<button aria-pressed="${f.nome === st.fundo[aba]}" data-f="${esc(f.nome)}"><span class="ponto" style="background:${f.cor}"></span>${esc(f.nome)}</button>`).join("")}</div>`;
}
function ligaSeletor() {
  document.querySelectorAll(".seletor[data-aba] button").forEach((b) => (b.onclick = () => { st.fundo[b.parentElement.dataset.aba] = b.dataset.f; desenha(); }));
}

// ------------------------------------------------------------------ abas
function desenhaAbas() {
  $("#abas").innerHTML = ABAS.map((a, i) => `<button role="tab" aria-selected="${i === st.aba}" data-i="${i}">${a}</button>`).join("");
  $("#abas").querySelectorAll("button").forEach((b) => (b.onclick = () => { st.aba = +b.dataset.i; desenhaAbas(); desenha(); }));
}
function desenha() {
  const R = st.R, el = $("#conteudo");
  if (!R) return;
  try { el.innerHTML = ""; [geral, rentab, plcap, alocacao, credito, movimentos, derivativos, marcacao, comparacao, dados][st.aba](el, R); }
  catch (e) { el.innerHTML = `<div class="aviso">Erro ao desenhar esta aba: ${esc(e.message)}</div>`; console.error(e); }
  ligaSeletor();
}

function geral(el, R) {
  el.innerHTML = `<h2>Resumo</h2>` + tabela([
    { t: "Fundo", k: "fundo", f: (v) => `<b style="color:${cor(v)}">■</b> ${esc(v)}` },
    { t: "PL (R$ mi)", k: "pl_mi", n: 1, f: (v) => num(v, 1) }, { t: "Retorno 12m", k: "ret12", n: 1, f: (v) => pct(v) },
    { t: "%CDI 12m", k: "pct_cdi12", n: 1, f: (v) => pct(v, 1) }, { t: "No ano", k: "ret_ano", n: 1, f: (v) => pct(v) },
    { t: "Vol. anual", k: "vol", n: 1, f: (v) => pct(v) }, { t: "Pior drawdown", k: "dd", n: 1, f: (v) => pct(v) },
    { t: "Captação líq. 12m (R$ mi)", k: "capt12_mi", n: 1, f: (v) => num(v, 1) }, { t: "Cotistas", k: "cotistas", n: 1, f: (v) => num(v, 0) },
    { t: "Ativos", k: "ativos", n: 1, f: (v) => num(v, 0) }, { t: "Top 10 emissores", k: "top10_emissores", n: 1, f: (v) => pct(v, 1) },
    { t: "Última carteira", k: "ult_carteira" }, { t: "Última aberta", k: "carteira_aberta" }, { t: "Última cota", k: "ult_cota" },
  ], R.kpis, 300) + `<div id="g_acum" class="grafico"></div>`;
  const d = Object.entries(R.cotas).map(([f, s]) => ({ x: s.datas, y: s.acum, name: f, line: { color: cor(f), width: 2 }, hovertemplate: "%{y:.2f}%" }));
  d.push({ x: R.cdi.datas, y: R.cdi.acum, name: "CDI", line: { color: css("--text-2"), width: 2, dash: "dash" }, hovertemplate: "%{y:.2f}%" });
  plota("g_acum", d, base("Retorno acumulado no período (%)", { yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 420);
}

function rentab(el, R) {
  el.innerHTML = `<div id="g_hm" class="grafico"></div><div id="g_mes" class="grafico"></div><div id="g_dd" class="grafico"></div>`;
  const fs = R.meta.fundos.map((f) => f.nome).filter((f) => R.cotas[f]);
  const meses = [...new Set(R.mensal.map((r) => r.mes))].sort();
  const z = fs.map((f) => meses.map((m) => { const r = R.mensal.find((x) => x.fundo === f && x.mes === m); return r && r.pct_cdi != null ? r.pct_cdi * 100 : null; }));
  plota("g_hm", [{ type: "heatmap", x: meses, y: fs, z, zmin: 0, zmax: 200, zmid: 100,
    colorscale: [[0, "#eb6834"], [0.5, css("--surface-2")], [1, "#2a78d6"]], colorbar: { ticksuffix: "%", title: { text: "%CDI" } },
    hovertemplate: "%{y}<br>%{x}: %{z:.0f}% do CDI<extra></extra>" }],
    base("%CDI mês a mês (azul acima do CDI, laranja abaixo)", { hovermode: "closest", yaxis: { autorange: "reversed" } }), 110 + 34 * fs.length);
  plota("g_mes", fs.map((f) => { const r = R.mensal.filter((x) => x.fundo === f && x.retorno != null);
    return { type: "bar", x: r.map((x) => x.mes), y: r.map((x) => x.retorno * 100), name: f, marker: { color: cor(f) }, hovertemplate: "%{y:.2f}%" }; }),
    base("Retorno mensal (%)", { barmode: "group", yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }));
  plota("g_dd", fs.map((f) => ({ x: R.cotas[f].datas, y: R.cotas[f].dd, name: f, line: { color: cor(f), width: 2 }, hovertemplate: "%{y:.2f}%" })),
    base("Drawdown (% abaixo do pico anterior)", { yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }));
}

function plcap(el, R) {
  el.innerHTML = `<div id="g_pl" class="grafico"></div><div id="g_cap" class="grafico"></div><div id="g_cot" class="grafico"></div>`;
  const fs = Object.keys(R.cotas);
  plota("g_pl", fs.map((f) => ({ x: R.cotas[f].datas, y: R.cotas[f].pl, name: f, line: { color: cor(f), width: 2 }, hovertemplate: "R$ %{y:,.1f} mi" })),
    base("Patrimônio líquido (R$ milhões)"));
  plota("g_cap", fs.map((f) => { const r = R.mensal.filter((x) => x.fundo === f);
    return { type: "bar", x: r.map((x) => x.mes), y: r.map((x) => x.capt_mi), name: f, marker: { color: cor(f) }, hovertemplate: "R$ %{y:,.1f} mi" }; }),
    base("Captação líquida mensal (aplicações - resgates, R$ mi)", { barmode: "group" }));
  plota("g_cot", fs.map((f) => ({ x: R.cotas[f].datas, y: R.cotas[f].cotistas, name: f, line: { color: cor(f), width: 2 } })), base("Número de cotistas"));
}

function alocacao(el, R) {
  el.innerHTML = seletorFundo("aloc");
  const f = st.fundo.aloc, p = R.por_fundo[f]; if (!p) return;
  el.insertAdjacentHTML("beforeend", `<div id="g_area" class="grafico"></div>
    <div class="grade g2"><div id="g_emi" class="grafico"></div><div id="g_atual" class="grafico"></div></div>
    <h2>Carteira de ${p.ult_mes} (look-through)</h2><input class="filtro" id="filtro" placeholder="Filtrar ativo, emissor, categoria...">
    <div id="t_cart"></div>`);
  plota("g_area", Object.entries(p.alocacao.series).map(([c, y]) => ({ x: p.alocacao.meses, y, name: c, stackgroup: "a",
    line: { width: 0.5, color: css("--surface-1") }, fillcolor: corCat(c), hovertemplate: "%{y:.1f}%" })),
    base(`${f}: % do PL por categoria (look-through)`, { yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 420);
  const e = barH(p.emissores, "perc_pl", "emissor", CORES[0], `Maiores emissores (${p.ult_mes})`); plota("g_emi", e.d, e.l, 460);
  const fs = R.comparacao.alocacao.fundos, cats = Object.keys(R.categorias);
  const agreg = (fund) => { const t = {}; R.comparacao.alocacao.linhas.forEach(([c, ...v]) => { const k = cats.includes(c) ? c : "Outros"; t[k] = (t[k] || 0) + v[fs.indexOf(fund)]; }); return t; };
  plota("g_atual", cats.map((c) => ({ type: "bar", orientation: "h", name: c, y: fs, x: fs.map((x) => agreg(x)[c] || 0), marker: { color: corCat(c) },
    hovertemplate: c + ": %{x:.1f}%<extra></extra>" })), base("Alocação atual: todos os fundos (% do PL)", { barmode: "relative", hovermode: "closest",
    yaxis: { autorange: "reversed", automargin: true }, xaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 460);
  const cols = [{ t: "Categoria", k: "categoria" }, { t: "Ativo", k: "ativo", w: 1 }, { t: "Código", k: "codigo" }, { t: "Emissor", k: "emissor", w: 1 },
    { t: "% PL", k: "perc_pl", n: 1, f: (v) => pct(v, 3) }, { t: "Veículo", k: "veiculo", w: 1 }];
  const pinta = () => { const q = $("#filtro").value.toLowerCase();
    const r = p.carteira.filter((x) => !q || [x.categoria, x.ativo, x.emissor, x.codigo].join(" ").toLowerCase().includes(q));
    $("#t_cart").innerHTML = tabela(cols, r.slice(0, 600)) + `<p class="legenda">${r.length} linhas${r.length > 600 ? " (mostrando 600; baixe o CSV na aba Dados)" : ""}</p>`; };
  $("#filtro").oninput = pinta; pinta();
}

function credito(el, R) {
  el.innerHTML = seletorFundo("cred");
  const f = st.fundo.cred, p = R.por_fundo[f]; if (!p) return; const c = p.credito;
  const an = R.meta.anbima_data ? new Date(R.meta.anbima_data + "T12:00").toLocaleDateString("pt-BR") : "-";
  el.insertAdjacentHTML("beforeend", `<div class="aviso">Carteira de <b>${c.mes}</b>: o mês mais recente com parte confidencial abaixo de 5% do PL.
    Taxas e duration das debêntures: marcação ANBIMA de <b>${an}</b>.</div>
    <div class="kpis">
      <div class="kpi"><div class="r">Debêntures</div><div class="v">${pct(c.deb_pl, 1)}</div><div class="s">do PL</div></div>
      <div class="kpi"><div class="r">Com taxa ANBIMA</div><div class="v">${pct(c.cobertura, 0)}</div><div class="s">das debêntures</div></div>
      <div class="kpi"><div class="r">Spread médio DI +</div><div class="v">${pct(c.spread_di)}</div><div class="s">a.a. · ${pct(c.pl_di, 1)} do PL</div></div>
      <div class="kpi"><div class="r">Taxa média IPCA +</div><div class="v">${pct(c.taxa_ipca)}</div><div class="s">a.a. · ${pct(c.pl_ipca, 1)} do PL</div></div>
      <div class="kpi"><div class="r">Duration média</div><div class="v">${num(c.duration)} anos</div><div class="s">debêntures com taxa</div></div>
    </div>
    <div class="grade g2"><div id="g_tipo" class="grafico"></div><div id="g_sc" class="grafico"></div></div>
    <div id="g_hist"></div><h2>Debêntures</h2><div id="t_deb"></div>
    <h2>Demais títulos (informado pela própria CVM)</h2>
    <p class="legenda">Indexador, % do índice, cupom, taxa e rating vêm na CDA para depósitos bancários e títulos de crédito privado; prazo vem do vencimento quando informado.</p>
    <div class="grade g3"><div id="g_idx" class="grafico"></div><div id="g_prz" class="grafico"></div><div id="g_rat" class="grafico"></div></div><div id="t_res"></div>`);
  const t = barH(c.por_tipo.sort((a, b) => b.perc_pl - a.perc_pl), "perc_pl", "t", CORES[0], "Debêntures por indexador (% do PL)"); plota("g_tipo", t.d, t.l, 340);
  plota("g_sc", ["DI +", "IPCA +"].map((tp, i) => { const r = c.debs.filter((x) => x.tipo === tp && x.taxa_ind != null);
    return { type: "scatter", mode: "markers", name: tp, x: r.map((x) => x.duration_anos), y: r.map((x) => x.taxa_ind), text: r.map((x) => x.ativo),
      marker: { size: r.map((x) => 6 + Math.sqrt(Math.max(x.perc_pl, 0)) * 12), color: CORES[i], line: { color: css("--surface-1"), width: 1.5 } },
      hovertemplate: "%{text}<br>duration %{x:.2f}a · taxa %{y:.2f}%<extra></extra>" }; }),
    base("Taxa indicativa x duration (tamanho = % do PL)", { hovermode: "closest", legend: { x: 0.01, y: 0.99, bgcolor: "rgba(0,0,0,0)" }, xaxis: { title: "duration (anos)", gridcolor: css("--grid") },
      yaxis: { title: "taxa (% a.a.)", gridcolor: css("--grid") } }), 340);
  if (c.hist && c.hist.datas && c.hist.datas.length > 1) {
    $("#g_hist").outerHTML = `<div class="grade g2"><div id="g_h1" class="grafico"></div><div id="g_h2" class="grafico"></div></div>
      <p class="legenda">Mesma carteira, marcação de cada dia guardado (${R.meta.anbima_dias} dias). O site gratuito da ANBIMA mantém ~15 dias úteis; o histórico cresce a cada uso.</p>`;
    plota("g_h1", [{ x: c.hist.datas, y: c.hist.spread_di, mode: "lines+markers", line: { color: CORES[0] }, name: "DI +" }], base("Spread médio DI + (% a.a.)"), 280);
    plota("g_h2", [{ x: c.hist.datas, y: c.hist.duration, mode: "lines+markers", line: { color: CORES[2] }, name: "duration" }], base("Duration média (anos)"), 280);
  }
  $("#t_deb").innerHTML = tabela([{ t: "Ativo", k: "ativo", w: 1 }, { t: "Código", k: "codigo" }, { t: "% PL", k: "perc_pl", n: 1, f: (v) => pct(v, 3) },
    { t: "Indexador", k: "indice" }, { t: "Taxa indicativa", k: "taxa_ind", n: 1, f: (v) => pct(v) }, { t: "Duration (anos)", k: "duration_anos", n: 1, f: (v) => num(v) },
    { t: "% PU par", k: "pct_par", n: 1, f: (v) => num(v) }, { t: "Vencimento", k: "venc" }, { t: "Veículo", k: "veiculo", w: 1 }], c.debs, 380);
  const b1 = barH(c.indexador.sort((a, b) => b.perc_pl - a.perc_pl), "perc_pl", "k", CORES[0], "Indexador (CDA)"); plota("g_idx", b1.d, b1.l, 320);
  plota("g_prz", [{ type: "bar", x: c.prazo.map((x) => x.k), y: c.prazo.map((x) => x.perc_pl), marker: { color: CORES[2] }, hovertemplate: "%{y:.2f}% do PL<extra></extra>" }],
    base("Prazo até o vencimento", { hovermode: "closest", yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 320);
  const b3 = barH(c.rating.sort((a, b) => b.perc_pl - a.perc_pl).slice(0, 12), "perc_pl", "k", CORES[6], "Rating"); plota("g_rat", b3.d, b3.l, 320);
  $("#t_res").innerHTML = tabela([{ t: "Categoria", k: "categoria" }, { t: "% PL", k: "perc_pl", n: 1, f: (v) => pct(v) },
    { t: "% PL c/ taxa", k: "perc_com_taxa", n: 1, f: (v) => pct(v) }, { t: "% do índice", k: "pct_indexador", n: 1, f: (v) => num(v) },
    { t: "Cupom/spread", k: "cupom", n: 1, f: (v) => num(v) }, { t: "Taxa pré", k: "taxa_pre", n: 1, f: (v) => num(v) },
    { t: "Prazo médio (anos)", k: "prazo", n: 1, f: (v) => num(v) }], c.resumo, 360);
}

function seletorMes(chave, meses, padrao) {
  st.mes[chave] = meses.includes(st.mes[chave]) ? st.mes[chave] : (meses.includes(padrao) ? padrao : meses[meses.length - 1]);
  return `<label class="seletor">Mês <select id="mes_${chave}">${meses.slice().reverse().map((m) => `<option ${m === st.mes[chave] ? "selected" : ""}>${m}</option>`).join("")}</select>
    <span class="legenda">(começa no último mês com carteira aberta)</span></label>`;
}
function ligaMes(chave) { const s = document.getElementById("mes_" + chave); if (s) s.onchange = () => { st.mes[chave] = s.value; desenha(); }; }

function movimentos(el, R) {
  el.innerHTML = seletorFundo("mov");
  const f = st.fundo.mov, p = R.por_fundo[f]; if (!p) return; const mv = p.movimentos;
  el.insertAdjacentHTML("beforeend", seletorMes("mov", mv.meses, p.mes_aberto));
  const e = mv.por_mes[st.mes.mov] || {};
  el.insertAdjacentHTML("beforeend", `<div class="kpis">
    <div class="kpi"><div class="r">Posições novas</div><div class="v">${num(e.novos, 0)}</div><div class="s">${pct(e.pct_novos)} do PL</div></div>
    <div class="kpi"><div class="r">Posições zeradas</div><div class="v">${num(e.zerados, 0)}</div><div class="s">${pct(e.pct_zerados)} do PL saiu</div></div></div>
    <div class="grade g2"><div id="g_c" class="grafico"></div><div id="g_v" class="grafico"></div></div><div id="g_giro" class="grafico"></div>`);
  ligaMes("mov");
  const c = barH(e.compras || [], "compra", "ativo", CORES[0], `Maiores compras em ${st.mes.mov} (% do PL)`); plota("g_c", c.d, c.l, 460);
  const v = barH(e.vendas || [], "venda", "ativo", CORES[1], `Maiores vendas em ${st.mes.mov} (% do PL)`); plota("g_v", v.d, v.l, 460);
  plota("g_giro", [{ type: "bar", x: mv.meses, y: mv.compras, name: "compras", marker: { color: CORES[0] }, hovertemplate: "%{y:.2f}%" },
    { type: "bar", x: mv.meses, y: mv.vendas.map((x) => -x), name: "vendas", marker: { color: CORES[1] }, hovertemplate: "%{y:.2f}%" }],
    base("Compras e vendas do mês (% do PL, look-through)", { barmode: "relative", yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }));
}

function derivativos(el, R) {
  el.innerHTML = seletorFundo("der");
  const f = st.fundo.der, p = R.por_fundo[f]; if (!p) return; const d = p.derivativos;
  el.insertAdjacentHTML("beforeend", `<p class="legenda">Derivativos aparecem pelo valor que o fundo informa à CVM (em geral o nocional), em % do PL; por isso ficam fora da soma de 100% e dos gráficos de alocação.</p>
    <div id="g_der" class="grafico"></div><div id="t_der"></div><div id="g_fx" class="grafico"></div>`);
  if (!d.meses.length) $("#g_der").outerHTML = `<div class="aviso">Sem derivativos na carteira no período.</div>`;
  else plota("g_der", Object.entries(d.series).map(([k, y], i) => ({ type: "bar", x: d.meses, y, name: k, marker: { color: CORES[i % 8] }, hovertemplate: "%{y:.2f}%" })),
    base("Derivativos por tipo de contrato (% do PL)", { barmode: "relative", yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 420);
  if (d.atual.length) $("#t_der").innerHTML = tabela([{ t: "Categoria", k: "categoria" }, { t: "Contrato", k: "tipo_ativo" }, { t: "Ativo", k: "ativo", w: 1 },
    { t: "Veículo", k: "veiculo", w: 1 }, { t: "% PL", k: "perc_pl", n: 1, f: (v) => pct(v, 3) }], d.atual, 300);
  plota("g_fx", [{ x: d.moeda.meses, y: d.moeda.exterior, name: "Investimento no exterior", line: { color: CORES[3], width: 2 } },
    { x: d.moeda.meses, y: d.moeda.dolar, name: "Futuros de dólar (nocional)", line: { color: CORES[6], width: 2 } }],
    base("Exposição a moeda estrangeira (% do PL)", { yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 300);
}

function marcacao(el, R) {
  el.innerHTML = `<p class="legenda">Efeito de marcação estimado com a CDA mensal: quantidade do mês anterior × variação do preço unitário (valor ÷ quantidade), só para ativos mantidos de um mês para o outro, em % do PL. Não inclui carrego de caixa/compromissadas, ganho de negociação nem ativos confidenciais. <b>Pagamentos de juros/amortização aparecem como queda de preço</b>: use para ver marcações e eventos de crédito, não como P&L contábil. A linha é o retorno real da cota.</p>` + seletorFundo("mar");
  const f = st.fundo.mar, p = R.por_fundo[f]; if (!p) return; const m = p.marcacao;
  if (!m) return el.insertAdjacentHTML("beforeend", `<div class="aviso">Precisa de pelo menos dois meses de carteira.</div>`);
  el.insertAdjacentHTML("beforeend", `<div id="g_mar" class="grafico"></div>${seletorMes("mar", m.meses, p.mes_aberto)}
    <div class="grade g2"><div id="g_alt" class="grafico"></div><div id="g_que" class="grafico"></div></div>
    <h2>No período inteiro</h2><div class="grade g2"><div id="t_alt"></div><div id="t_que"></div></div>`);
  ligaMes("mar");
  const d = Object.entries(m.series).map(([c, y]) => ({ type: "bar", x: m.meses, y, name: c, marker: { color: corCat(c) }, hovertemplate: "%{y:.2f}%" }));
  d.push({ x: m.meses, y: m.real, name: "retorno real da cota", mode: "lines+markers", line: { color: css("--text-1"), width: 2 }, hovertemplate: "%{y:.2f}%" });
  plota("g_mar", d, base("Efeito de marcação por categoria e retorno real da cota (% do PL)", { barmode: "relative", yaxis: { ticksuffix: "%", gridcolor: css("--grid") } }), 420);
  const e = m.por_mes[st.mes.mar] || { altas: [], quedas: [] };
  const a = barH(e.altas, "resultado_pct", "ativo", CORES[0], `Maiores altas de preço em ${st.mes.mar}`); plota("g_alt", a.d, a.l, 440);
  const q = barH(e.quedas.slice().reverse(), "resultado_pct", "ativo", CORES[1], `Maiores quedas de preço em ${st.mes.mar}`); plota("g_que", q.d, q.l, 440);
  const cols = [{ t: "Ativo", k: "ativo", w: 1 }, { t: "Categoria", k: "categoria" }, { t: "% PL", k: "resultado_pct", n: 1, f: (v) => pct(v, 3) }];
  $("#t_alt").innerHTML = tabela(cols, m.periodo.altas, 420); $("#t_que").innerHTML = tabela(cols, m.periodo.quedas, 420);
}

function comparacao(el, R) {
  const al = R.comparacao.alocacao, em = R.comparacao.emissores;
  const cr = R.meta.fundos.filter((f) => R.por_fundo[f.nome]).map((f) => ({ fundo: f.nome, ...R.por_fundo[f.nome].credito }));
  el.innerHTML = `<h2>Alocação por categoria na última carteira (% do PL)</h2>` +
    tabela([{ t: "Categoria", k: 0 }, ...al.fundos.map((f, i) => ({ t: esc(f), k: i + 1, n: 1, f: (v) => num(v) }))], al.linhas, 420) +
    `<h2>Crédito: debêntures com marcação ANBIMA (última carteira aberta)</h2>` +
    tabela([{ t: "Fundo", k: "fundo" }, { t: "Carteira", k: "mes" }, { t: "Debêntures (%PL)", k: "deb_pl", n: 1, f: (v) => num(v) },
      { t: "Cobertura ANBIMA", k: "cobertura", n: 1, f: (v) => pct(v, 0) }, { t: "Spread DI +", k: "spread_di", n: 1, f: (v) => pct(v) },
      { t: "Taxa IPCA +", k: "taxa_ipca", n: 1, f: (v) => pct(v) }, { t: "Duration (anos)", k: "duration", n: 1, f: (v) => num(v) }], cr, 300) +
    (em.linhas.length ? `<h2>Emissores em comum (% do PL)</h2>` + tabela([{ t: "Emissor", k: 0, w: 1 }, ...em.fundos.map((f, i) => ({ t: esc(f), k: i + 1, n: 1, f: (v) => num(v) }))], em.linhas, 420) : "") +
    `<div id="g_rr" class="grafico"></div>`;
  plota("g_rr", R.kpis.map((k) => ({ type: "scatter", mode: "markers+text", x: [k.vol], y: [k.pct_cdi12], text: [k.fundo], textposition: "top center", name: k.fundo,
    marker: { size: 12 + Math.sqrt(Math.max(k.pl_mi || 1, 1)) / 2, color: cor(k.fundo), line: { color: css("--surface-1"), width: 2 } },
    hovertemplate: `${esc(k.fundo)}<br>vol %{x:.2f}% · %{y:.1f}% do CDI<extra></extra>` })),
    base("Risco x retorno (12 meses): volatilidade anual x %CDI", { hovermode: "closest", showlegend: false,
      xaxis: { title: "volatilidade anual (%)", gridcolor: css("--grid") }, yaxis: { title: "%CDI 12m", gridcolor: css("--grid") } }), 420);
}

function dados(el) {
  el.innerHTML = `<h2>Downloads</h2><p class="links"><a href="/api/csv/${st.chave}/carteira">Carteira look-through (CSV)</a>
    <a href="/api/csv/${st.chave}/cotas">Cotas diárias (CSV)</a></p>
    <p class="legenda">CSV com ponto e vírgula e vírgula decimal (abre direto no Excel em português).</p>
    <h2>Fontes</h2><ul class="legenda"><li>CVM, dados abertos: CDA (carteira mensal), informe diário, cadastro de fundos (dados.cvm.gov.br)</li>
    <li>ANBIMA: mercado secundário de debêntures, taxa indicativa diária (anbima.com.br)</li><li>Banco Central: CDI, série SGS 12</li></ul>`;
}

</script>
</body>
</html>
"""


def gera_excel():
    CNPJ = {n: cnpj_of(x) for n, x in PEERS.items()}
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
    excel(df, rent, list(PEERS), OUT)
    print("salvo", OUT, "e", OUT.replace(".xlsx", "_dados.csv"), len(df), "linhas")


if __name__ == "__main__":                 # importante: os processos auxiliares do Windows reimportam este arquivo
    if len(sys.argv) > 1 and sys.argv[1].lower() == "excel":
        gera_excel()
    else:
        import webbrowser
        import uvicorn
        threading.Thread(target=carrega_cadastro, daemon=True).start()
        porta = int(os.environ.get("PORT", 7860))
        threading.Timer(2, lambda: webbrowser.open(f"http://localhost:{porta}")).start()
        print(f"Painel em http://localhost:{porta}  (Ctrl+C para parar)")
        uvicorn.run(app, host="127.0.0.1", port=porta, log_level="warning")
