"""
Look-through de carteiras com dados abertos da CVM (dados.cvm.gov.br) - oficial, gratuito, sem bloqueio.
  CDA (carteira mensal de todos os fundos)  -> abre cotas de fundo recursivamente, % = produto ao longo da cadeia
  INF_DIARIO (cota diaria)                  -> rentabilidade, PL, captacao, cotistas (CDI: Banco Central, SGS 12)
Uso direto (gera Excel):  python lookthrough_cvm.py
Usado tambem pelo painel:  streamlit run app.py
Saida do Excel (lookthrough_cvm.xlsx): graficos, evolucao, rentabilidade, top10, uma aba por peer
  + lookthrough_cvm_dados.csv (tabela plana, uma linha por caminho ate o ativo)
Cache local: zips da CVM + recortes em parquet so dos fundos necessarios.
"""
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


if __name__ == "__main__":
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
