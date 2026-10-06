"""
Dados abertos de fundos: CVM (carteira CDA mensal, informe diario), ANBIMA (debentures), Tesouro Direto (curvas),
Banco Central (CDI, PTAX) e IBGE (IPCA). Tudo publico e gratuito.
  CDA -> look-through: abre cotas de fundo recursivamente, % = produto dos pesos ao longo da cadeia
Os dados baixados ficam na pasta "dados_painel", ao lado deste arquivo.
Uso direto (gera Excel):  python lookthrough_cvm.py
"""
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
    "GD MM": "14.416.823/0001-07",
    "GD MM Flexprev": "40.209.105/0001-70",
    "GD MM Ultra": "42.332.169/0001-99",
    "Precision": "32.292.528/0001-78",
    "Dual": "34.803.938/0001-61",
    "Prev": "49.803.664/0001-88",
    "Dual Prev": "58.156.912/0001-37",
    "Dual Global": "62.917.953/0001-76",
    "Dual Prev Dist": "65.983.811/0001-03",
    "Fuji": "67.269.289/0001-10",
    "GD RF": "32.973.123/0001-03",
    "Prev BB": "58.013.738/0001-73",
    "GD RF Flexprev": "39.566.756/0001-38",
}
PEERS = {                       # se um CNPJ tambem estiver em NOSSOS_FUNDOS, vale como nosso
    "XP Corporate Top Credito": "04.621.721/0001-70",
    "Valora Absolute": "10.326.625/0001-00",
    "XP Corporate Light": "11.046.179/0001-34",
    "Principal Claritas": "11.447.136/0001-60",
    "Sparta Top": "14.188.162/0001-00",
    "Plural Credito Corporativo": "18.316.558/0001-46",
    "Sparta Max": "26.773.148/0001-52",
    "Itau Multimercado Credito Privado": "28.840.420/0001-03",
    "AF Invest Geraes 30": "29.044.189/0001-04",
    "JGP Corporate Plus": "32.892.264/0001-93",
    "Dual Advanced": "34.803.938/0001-61",
    "Compass Yield 30": "36.318.479/0001-56",
    "Itau High Yield All": "42.263.927/0001-64",
    "Icatu Vanguarda": "42.501.967/0001-05",
    "ARX Vinson": "42.698.327/0001-29",
    "Itau Sinfonia Multimercado": "42.717.960/0001-17",
    "Occam Credito Corporativo": "47.586.648/0001-55",
    "Absolute Creta Selecao": "48.094.354/0001-79",
    "Mag High Grade Plus 30": "50.697.486/0001-37",
    "Vinland Credito Selecao": "50.980.211/0001-06",
    "Itau Sinfonia All": "54.278.393/0001-29",
    "Solis Capital Antares": "13.054.728/0001-48",
    "Capitania Premium 45": "20.146.294/0001-71",
    "AZ Quest Altro": "22.100.009/0001-07",
    "XP Corporate Plus": "23.999.611/0001-90",
    "ARX Everest": "32.102.131/0001-76",
    "Precision Advanced": "32.292.528/0001-78",
    "JGP Select": "32.892.615/0001-66",
    "AZ Quest Supra": "36.352.498/0001-07",
    "Root Capital Credito HG": "42.405.028/0001-59",
    "SPX Seahawk": "42.431.531/0001-89",
    "AF Horizonte": "44.025.131/0001-07",
    "Sparta Max 60": "44.643.192/0001-20",
    "Absolute Atenas Itau": "49.645.368/0001-04",
    "ARX RF": "41.575.611/0001-45",
    "ARX K2 IVP Inflacao Curta": "46.997.356/0001-42",
    "BTG Pactual Credito Corporativo": "42.827.247/0001-26",
    "Capitania Itau": "41.709.507/0001-04",
    "Capitania Idence Itau": "42.827.631/0001-29",
    "Icatu Vanguarda Absoluto II": "47.212.476/0001-50",
    "Icatu Vanguarda A": "34.781.249/0001-01",
    "Itau Active Fix": "41.301.133/0001-85",
    "Itau High Yield II": "42.860.483/0001-44",
    "JGP Credito Itau": "41.955.494/0001-45",
    "Kinea FI RF": "26.491.419/0001-87",
    "Porto Credito RF": "54.974.029/0001-01",
    "Schroder Idencia Itau I": "42.535.150/0001-40",
    "Sparta Inflacao IU": "43.737.649/0001-00",
    "Sparta IU": "46.997.384/0001-60",
    "SPX Seahawk Itau": "42.014.260/0001-66",
    "SulAmerica Cred ESG Itau": "45.615.787/0001-34",
    "Vinland Credito A T1 MM": "49.456.416/0001-08",
    "Absolute Delfos Itau": "49.645.692/0001-14",
    "Capitania Reit Itau": "42.934.005/0001-31",
    "Ibiuna I Credit Itau": "45.644.076/0001-98",
    "Icatu Vanguarda A Qualificado": "41.867.248/0001-31",
    "Itau BTG Pactual CorpPlus": "41.735.237/0001-06",
    "Itau Flexprev Advanced": "49.803.664/0001-88",
    "Itau Dual Prev": "58.156.912/0001-37",
    "Itau Sinfonia MM": "42.380.882/0001-08",
    "Vinland Credito IQ": "61.735.868/0001-24",
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
    "ITAU": "Itaú", "BRADESCO": "Bradesco", "SANTANDER": "Santander", "BANCO DO BRASIL": "Banco do Brasil", "CAIXA ECONOMICA": "Caixa Econômica",
    "BTG": "BTG Pactual", "VOTORANTIM|BANCO BV": "BV", "XP ": "XP", "SAFRA": "Safra", "DAYCOVAL": "Daycoval",
    "TESOURO NACIONAL|SECRETARIA DO TESOURO": "Tesouro Nacional",
}
OUT = "lookthrough_cvm.xlsx"
WORKERS = 4

URL = "https://dados.cvm.gov.br/dados/FI/DOC"
CACHE = Path(os.environ.get("PAINEL_DADOS") or Path(__file__).resolve().parent / "dados_painel")   # pasta ao lado do .py
(CACHE / "rec").mkdir(parents=True, exist_ok=True)
VERSAO_DIARIO = 4               # recorte das cotas diarias (3: fundos que so informam cota por subclasse)
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
DERIV = r"(?i)mercado futuro|opç|swap"   # derivativos (nocional): fora dos 100%; termo de acoes e posicao real e entra
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
        return set(j["fundos"]) if isinstance(j, dict) and j.get("v") == (VERSAO_DIARIO if kind == "diario" else VERSAO) else None
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
    if "ID_SUBCLASSE" in d:                       # cota da classe; se a classe so informa por subclasse, a de maior PL
        cls = d[d.ID_SUBCLASSE.isna()]
        tem = set(zip(cls.CNPJ_FUNDO_CLASSE, cls.DT_COMPTC))                 # decide dia a dia (fundo migrando no mes)
        sub = d[d.ID_SUBCLASSE.notna()]
        sub = sub[[k not in tem for k in zip(sub.CNPJ_FUNDO_CLASSE, sub.DT_COMPTC)]]
        if len(sub):
            pl = pd.to_numeric(sub.VL_PATRIM_LIQ, errors="coerce").groupby([sub.CNPJ_FUNDO_CLASSE, sub.ID_SUBCLASSE]).sum()
            maior = pl.groupby(level=0).idxmax().map(lambda t: t[1])
            sub = sub[sub.ID_SUBCLASSE == sub.CNPJ_FUNDO_CLASSE.map(maior)]
        d = pd.concat([cls, sub], ignore_index=True)
    for m in meses:
        d[d.DT_COMPTC.str[:7] == m].to_parquet(CACHE / "rec" / f"diario_{m}.parquet", index=False)
        (CACHE / "rec" / f"diario_{m}.json").write_text(json.dumps({"v": VERSAO_DIARIO, "fundos": sorted(alvo)}))
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
    if not folhas:                              # CVM sem nenhuma carteira desse CNPJ no periodo
        return pd.DataFrame()
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


# ------------------------------------------------------------------ SND (debentures.com.br), FIDC (CVM) e Treasury: cobertura total
SND = "https://www.debentures.com.br/exploreosnd/consultaadados/emissoesdedebentures/"
UA = {"User-Agent": "Mozilla/5.0"}


def _get(url, tent=4, **kw):
    for t in range(tent):
        try:
            r = requests.get(url, headers=UA, timeout=300, **kw)
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if t == tent - 1:
                raise
            time.sleep(3 * (t + 1))


def _tabela_snd(conteudo, inicio):
    t = conteudo.decode("latin1").splitlines()
    i = next((j for j, l in enumerate(t) if l.startswith(inicio)), None)
    if i is None:
        return pd.DataFrame()
    a = pd.read_csv(io.StringIO("\n".join(t[i:])), sep="\t", dtype=str, quoting=3)
    a.columns = [c.strip() for c in a.columns]
    return a.apply(lambda s: s.str.strip())


def _diario(f):                    # arquivo que muda: rebaixa 1x por dia
    return not f.exists() or date.fromtimestamp(f.stat().st_mtime) < date.today()


def snd_caracteristicas():
    """Cadastro de TODAS as debentures do SND (ativas e ja vencidas/excluidas): indice, taxa de emissao, vencimento,
    periodicidade de juros, amortizacao e se e incentivada (Lei 12.431)."""
    partes = []
    for exc in ("False", "True"):
        f = CACHE / f"snd_caracteristicas_{exc}.txt"
        if _diario(f):
            try:
                f.write_bytes(_get(SND + f"caracteristicas_e.asp?tip_deb=publicas&op_exc={exc}&ativo="))
            except requests.RequestException:
                pass
        if f.exists():
            partes.append(_tabela_snd(f.read_bytes(), "Codigo do Ativo"))
    a = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    if not len(a):
        return pd.DataFrame()
    dt = lambda c: pd.to_datetime(a[c], format="%d/%m/%Y", errors="coerce")
    meses = lambda c, u: pd.to_numeric(a[c], errors="coerce") * np.where(a[u].eq("DIA"), 1 / 30, 1)
    out = pd.DataFrame({"codigo": a["Codigo do Ativo"], "empresa": a["Empresa"], "cnpj": a["CNPJ"],
                        "venc": dt("Data de Saida / Novo Vencimento").fillna(dt("Data de Vencimento")),
                        "indice": a["indice"].map(_sem_acento),
                        "pct": pd.to_numeric(a["Percentual Multiplicador/Rentabilidade"], errors="coerce"),
                        "juros": pd.to_numeric(a["Juros Criterio Novo - Taxa"].str.replace(",", "."), errors="coerce"),
                        "cada_juros": meses("Juros Criterio Novo - Cada", "Juros Criterio Novo - Unidade"),
                        "cada_amort": meses("Amortizacao - Cada", "Amortizacao - Unidade"),
                        "carencia": dt("Amortizacao - Carencia"),
                        "incentivada": a["Deb. Incent. (Lei 12.431)"].eq("S")})
    return out.drop_duplicates("codigo").set_index("codigo")


def snd_pu(datas, workers=4, log=print):
    """PU par (curva de emissao, com juros acumulados e amortizacoes) de todas as debentures em cada data.
    Um arquivo pequeno por data, guardado: so baixa datas novas."""
    vazio = lambda d: CACHE / f"snd_pu_{d:%Y%m%d}_vazio"        # feriado: marcado para nao pedir de novo

    def um(d):
        if vazio(d).exists():
            return None
        partes = []
        for e in ("False", "True"):             # ativas + ja vencidas/excluidas
            f = CACHE / f"snd_pu_{d:%Y%m%d}_{e}.txt"
            if not f.exists():
                try:
                    b = _get(SND + f"puhistorico_e.asp?op_exc={e}&ativo=&dt_ini={d:%d/%m/%Y}&dt_fim={d:%d/%m/%Y}")
                except requests.RequestException:
                    return None
                if e == "False" and b.count(b"\n") < 20:     # feriado / sem dados
                    if d < pd.Timestamp.today().normalize() - pd.Timedelta(days=7):
                        vazio(d).touch()
                    return None
                f.write_bytes(b)
            partes.append(_tabela_snd(f.read_bytes(), "Data do PU"))
        a = pd.concat(partes, ignore_index=True)
        a = a[a.iloc[:, 0].str.match(r"\d\d/\d\d/\d{4}", na=False)]
        num = lambda s: pd.to_numeric(s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")
        return pd.DataFrame({"data": d, "codigo": a.iloc[:, 1].values, "pu_par": num(a.iloc[:, 5]).values})
    novas = [d for d in datas if not (CACHE / f"snd_pu_{d:%Y%m%d}_True.txt").exists() and not vazio(d).exists()]
    if novas:
        log(f"SND: PU par das debêntures em {len(novas)} fins de mês (só na 1a vez)...")
    with ThreadPoolExecutor(workers) as ex:
        out = [x for x in ex.map(um, datas) if x is not None]
    return pd.concat(out, ignore_index=True).drop_duplicates(["data", "codigo"]) if out else pd.DataFrame(columns=["data", "codigo", "pu_par"])


FIDC_URL = "https://dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS/"
_MEIO = [15, 45, 75, 105, 135, 165, 270, 540, 900, 1440]       # meio de cada faixa de prazo (dias) da tabela V


def _prazo_fidc(z, nome):
    t = pd.read_csv(z.open(nome), sep=";", encoding="latin1", dtype=str, quoting=3)
    c = "CNPJ_FUNDO_CLASSE" if "CNPJ_FUNDO_CLASSE" in t.columns else "CNPJ_FUNDO"
    b = t[[k for k in t.columns if re.match(r"TAB_V_A\d+_VL_PRAZO_VENC", k)]].apply(pd.to_numeric, errors="coerce").fillna(0).values
    tot = b.sum(1)
    return pd.DataFrame({"cnpj": t[c].values, "mes": t.DT_COMPTC.str[:7].values,
                         "anos": np.where(tot > 0, (b * _MEIO).sum(1) / np.where(tot > 0, tot, 1) / 365.25, np.nan)}).dropna()


def _series_fidc(z, n2, n3, n6):
    """Valor e quantidade de cotas (tab X_2), rentabilidade do mes (X_3), desempenho esperado (X_6) e amortizacoes
    pagas no mes (X_4) de cada classe/serie de cada FIDC."""
    le = lambda n: pd.read_csv(z.open(n), sep=";", encoding="latin1", dtype=str, quoting=3)
    a, b = le(n2), le(n3)
    n4 = n2.replace("_X_2_", "_X_4_")
    am = le(n4) if n4 in z.namelist() else pd.DataFrame(columns=list(a.columns[:4]) + ["TAB_X_TP_OPER", "TAB_X_CLASSE_SERIE", "TAB_X_VL_TOTAL"])
    e = le(n6) if n6 in z.namelist() else pd.DataFrame(columns=list(a.columns[:4]) + ["TAB_X_CLASSE_SERIE", "TAB_X_PR_DESEMP_ESPERADO"])
    c = "CNPJ_FUNDO_CLASSE" if "CNPJ_FUNDO_CLASSE" in a.columns else "CNPJ_FUNDO"
    e = e.rename(columns={"CNPJ_FUNDO": c}) if c not in e.columns else e
    am = am.rename(columns={"CNPJ_FUNDO": c}) if c not in am.columns else am
    am = am[am.TAB_X_TP_OPER.fillna("").str.contains("Amortiza")].copy()
    for t in (a, b, e, am):
        t["n"] = t.groupby([c, "DT_COMPTC", "TAB_X_CLASSE_SERIE"]).cumcount()
    k = [c, "DT_COMPTC", "TAB_X_CLASSE_SERIE", "n"]
    x = a.merge(b, on=k, how="outer").merge(e[k + ["TAB_X_PR_DESEMP_ESPERADO"]], on=k, how="left")         .merge(am[k + ["TAB_X_VL_TOTAL"]], on=k, how="left")
    num = lambda s: pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")
    return pd.DataFrame({"cnpj": x[c].values, "mes": x.DT_COMPTC.str[:7].values, "serie": x.TAB_X_CLASSE_SERIE.str.strip().values,
                         "cota": num(x.TAB_X_VL_COTA).values, "qt": num(x.TAB_X_QT_COTA).values, "rent": num(x.TAB_X_VL_RENTAB_MES).values,
                         "esperado": num(x.TAB_X_PR_DESEMP_ESPERADO).values, "amort": num(x.TAB_X_VL_TOTAL).fillna(0).values})


def fidc_mensal(desde, log=print):
    """Do informe mensal de FIDC da CVM: (1) prazo medio (anos) dos recebiveis a vencer de cada FIDC (tabela V) =
    duration estimada da cota; (2) valor da cota e rentabilidade de cada classe/serie (tabelas X_2/X_3) = spread da
    serie que o fundo tem. Guarda so o resultado (pequeno), nao os zips."""
    f, fs = CACHE / "fidc_prazo4.parquet", CACHE / "fidc_series4.parquet"
    tem = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["cnpj", "mes", "anos"])
    ser = [pd.read_parquet(fs)] if fs.exists() else []
    feitos = set(tem.mes)
    hoje = pd.Timestamp.today()
    novos = []
    for a in range(int(desde[:4]), hoje.year + 1):
        ms = [f"{a}-{m:02d}" for m in range(1, 13) if pd.Timestamp(a, m, 1) <= hoje and f"{a}-{m:02d}" >= desde]
        falta = [m for m in ms if m not in feitos]
        if not falta:
            continue
        urls = [FIDC_URL + f"inf_mensal_fidc_{m.replace('-', '')}.zip" for m in falta] if a >= 2025 else [FIDC_URL + f"HIST/inf_mensal_fidc_{a}.zip"]
        for u in urls:
            try:
                z = zipfile.ZipFile(io.BytesIO(_get(u, tent=2)))
            except (requests.RequestException, zipfile.BadZipFile):
                continue
            log(f"FIDC: prazo e rentabilidade das séries ({u.rsplit('/', 1)[1]})...")
            nomes = z.namelist()
            for n in nomes:
                if "_tab_V_" in n:
                    novos.append(_prazo_fidc(z, n))
                if "_tab_X_2_" in n and n.replace("_X_2_", "_X_3_") in nomes:
                    ser.append(_series_fidc(z, n, n.replace("_X_2_", "_X_3_"), n.replace("_X_2_", "_X_6_")))
    if novos:
        tem = pd.concat([tem] + novos, ignore_index=True).drop_duplicates(["cnpj", "mes"], keep="last")
        tem.to_parquet(f, index=False)
        pd.concat(ser, ignore_index=True).drop_duplicates(["cnpj", "mes", "serie", "cota"], keep="last").to_parquet(fs, index=False)
    return tem, (pd.concat(ser, ignore_index=True) if ser else pd.DataFrame(columns=["cnpj", "mes", "serie", "cota", "qt", "rent", "esperado", "amort"]))


def taxas():
    """Taxa de administracao e de performance (com o benchmark) de cada fundo: extrato anual da CVM, ultimo informado."""
    partes = []
    for a in range(max(int(DESDE[:4]), 2019), date.today().year + 1):
        f = CACHE / f"extrato_fi_{a}.csv"
        if not f.exists() or (a == date.today().year and _diario(f)):
            try:
                f.write_bytes(_get(f"{URL}/EXTRATO/DADOS/extrato_fi_{a}.csv", tent=2))
            except requests.RequestException:
                pass
        if f.exists():
            t = pd.read_csv(f, sep=";", encoding="latin1", dtype=str, quoting=3)
            t = t.rename(columns={"CNPJ_FUNDO": "CNPJ_FUNDO_CLASSE"})
            partes.append(t[[c for c in ["CNPJ_FUNDO_CLASSE", "DT_COMPTC", "TAXA_ADM", "TAXA_PERFM", "PARAM_TAXA_PERFM",
                                         "PR_INDICE_REFER_TAXA_PERFM"] if c in t.columns]])
    if not partes:
        return {}
    t = pd.concat(partes, ignore_index=True).sort_values("DT_COMPTC").drop_duplicates("CNPJ_FUNDO_CLASSE", keep="last")
    num = lambda c: pd.to_numeric(t[c].str.replace(",", ".", regex=False), errors="coerce") if c in t.columns else np.nan
    t = t.assign(adm=num("TAXA_ADM"), perf=num("TAXA_PERFM"), pct=num("PR_INDICE_REFER_TAXA_PERFM"))
    return {c: (a if a == a else 0.0, p if p == p else 0.0, str(par or ""), q if q == q and q > 0 else 100.0)   # 0 = nao informado
            for c, a, p, par, q in zip(t.CNPJ_FUNDO_CLASSE, t.adm, t.perf, t.get("PARAM_TAXA_PERFM", ""), t.pct)}


def treasury():
    """Curva de juros do Tesouro americano (treasury.gov, gratuito), no formato de tesouro() para usar em curva()."""
    tenor = {"1 Mo": 1 / 12, "3 Mo": .25, "6 Mo": .5, "1 Yr": 1, "2 Yr": 2, "3 Yr": 3, "5 Yr": 5, "7 Yr": 7, "10 Yr": 10, "20 Yr": 20, "30 Yr": 30}
    partes = []
    for a in range(int(DESDE[:4]), date.today().year + 1):
        f = CACHE / f"treasury_{a}.csv"
        if not f.exists() or (a == date.today().year and _diario(f)):
            try:
                f.write_bytes(_get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                                   f"{a}/all?type=daily_treasury_yield_curve&field_tdr_date_value={a}&page&_format=csv", tent=2))
            except requests.RequestException:
                continue
        if f.exists():
            partes.append(pd.read_csv(f))
    if not partes:
        return {}
    d = pd.concat(partes, ignore_index=True)
    d["data"] = pd.to_datetime(d.Date, format="%m/%d/%Y")
    d = d.drop_duplicates("data").sort_values("data")
    cols = [c for c in tenor if c in d.columns]
    x = np.array([tenor[c] for c in cols])
    por_dia = {r.data: (x[~np.isnan(v)], v[~np.isnan(v)]) for r, v in zip(d.itertuples(), d[cols].to_numpy(float)) if (~np.isnan(v)).sum() > 2}
    datas = sorted(por_dia)
    return {"UST": (np.array(datas, dtype="datetime64[ns]"), datas, por_dia)}


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
    """Numero-indice do IPCA, mensal (indice "AAAA-MM"). Fonte: IBGE/SIDRA; se vier vazio ou falhar, monta pela
    variacao mensal do Banco Central (SGS 433) ancorada no numero-indice oficial de dez/2019 (5320,25)."""
    f = CACHE / "ipca_indice.json"
    if not f.exists() or f.stat().st_mtime < time.time() - 86400:
        try:
            r = requests.get("https://apisidra.ibge.gov.br/values/t/1737/n1/all/v/2266/p/all", timeout=120).json()
            d = {x["D3C"]: x["V"] for x in r[1:]}
            if len(d) > 12:
                f.write_text(json.dumps(d))
        except (requests.RequestException, ValueError, KeyError, TypeError, IndexError):
            pass
    s = pd.Series(dtype=float, index=pd.Index([], dtype=object))
    if f.exists():
        d = json.loads(f.read_text())
        s = pd.Series({f"{k[:4]}-{k[4:]}": float(v) for k, v in d.items() if v not in ("...", "-", "")}, dtype=float)
    if len(s) < 12:
        v = sgs(433, "1994-01") / 100
        if len(v):
            v.index = v.index.strftime("%Y-%m")
            nivel = (1 + v).cumprod()
            s = nivel / nivel.get("2019-12", nivel.iloc[-1]) * 5320.25
    s.index = s.index.astype(object)
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
    d = d.dropna(subset=["taxa"])
    d = d[d.anos >= 0.5].sort_values(["tipo", "data", "anos"])      # titulo vencendo em meses distorce a taxa (projecao do IPCA)
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


def distribuicoes(d):
    """Fundos que distribuem rendimentos (ex.: infra "renda"): a cota cai todo mes no dia da distribuicao e nao mostra
    o retorno total. Detecta queda > 0,4% (bem abaixo do normal do fundo) no inicio do mes, em >= 60% dos meses, e
    reconstroi a cota de retorno total somando a distribuicao de volta. Devolve (d ajustado, {fundo: (n, media %)})."""
    partes, info = [], {}
    for n, g in d.groupby("fundo", sort=False):
        g = g.sort_values("data").copy()
        q = g.VL_QUOTA.values.astype(float)
        if len(q) < 60:
            partes.append(g); continue
        r = np.r_[0.0, q[1:] / q[:-1] - 1]
        base = pd.Series(r).rolling(21, min_periods=5, center=True).median().values
        cand = (r < -0.004) & (r < base - 0.004) & (g.data.dt.day.values <= 12)
        meses_cand = sorted(set(g.mes[cand].tolist()))
        if len(meses_cand) >= 6:
            ini, fim = pd.Period(meses_cand[0]), pd.Period(meses_cand[-1])
            if len(meses_cand) >= 0.6 * ((fim - ini).n + 1):
                info[n] = (int(cand.sum()), float(-np.mean(r[cand]) * 100))
                r = np.where(cand, base, r)
                g["VL_QUOTA"] = q[0] * np.cumprod(1 + np.nan_to_num(r))
        partes.append(g)
    return (pd.concat(partes, ignore_index=True) if partes else d), info


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
