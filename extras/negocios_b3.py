"""
Todos os negócios de crédito privado da B3 (balcão) de um dia, com o cadastro de cada papel -> Excel.
  Negócios: Boletim Diário da B3 (negócio a negócio, com horário; o dia corrente atualiza a cada ~15 min).
  Cadastro: B3 (tipo, emissor, incentivada, indexador, % do indexador, taxa de emissão, vencimento).
  ANBIMA: taxa indicativa e duration das debêntures (arquivo diário gratuito).
          CRI/CRA (devedor e taxa indicativa): só pela API oficial da ANBIMA, se ANBIMA_CLIENT_ID e
          ANBIMA_CLIENT_SECRET estiverem no ambiente (cadastro gratuito em developers.anbima.com.br).
  Spread: DI+ = a própria taxa; % do CDI = (taxa/100 - 1) x CDI; IPCA+ = taxa - NTN-B (Tesouro) na duration;
          prefixado = taxa - curva pré (Tesouro) na duration.
Uso:  python negocios_b3.py              (D-1 útil)
      python negocios_b3.py 2026-10-09   |   python negocios_b3.py hoje
Saída: negocios_b3/negocios_AAAAMMDD.xlsx (abas: negocios, por_papel)
"""
import io
import os
import sys

import numpy as np
import pandas as pd
import requests

import carteira as ct

PASTA = "negocios_b3"
COLS = ["tipo", "emissor", "codigo", "quantidade", "pu", "volume", "taxa_negocio", "origem", "hora", "data", "id", "isin",
        "liquidacao", "situacao"]


def negocios(dia):
    r = ct.get("https://arquivos.b3.com.br/bdi/table/export/csv?lang=pt-BR", "POST", timeout=300,
               json={"Name": "Trade", "Date": f"{dia:%Y-%m-%d}", "FinalDate": f"{dia:%Y-%m-%d}", "ClientId": "", "Filters": {}})
    t = r.content.decode("utf-8-sig").splitlines()
    i = next((k for k, l in enumerate(t) if l.count(";") > 5), None)
    if i is None:
        return pd.DataFrame(columns=COLS)
    x = pd.read_csv(io.StringIO("\n".join(t[i:])), sep=";", dtype=str).iloc[:, :len(COLS)]
    x.columns = COLS
    x = x[x.situacao.ne("Cancelado") & x.tipo.ne("COE") & x.codigo.notna() & x.data.notna()].copy()       # tira rodapé do boletim
    for c in ("quantidade", "pu", "volume", "taxa_negocio"):
        x[c] = ct.num(x[c])
    x["taxa_negocio"] = x.taxa_negocio.where(x.taxa_negocio != 0)          # 0 = registro sem taxa informada
    return x


def classe(tipo, incent, emissor):
    e = str(emissor).upper()
    if tipo == "DEB":
        return "DEB isenta (12.431)" if incent else "DEB não isenta"
    if tipo == "CFF":
        return "FIDC" if "CREDITORIO" in e else "FII" if "IMOBILI" in e else "Fiagro" if "AGRO" in e else "Cota de fundo"
    return {"LFSN": "LF subordinada", "LFSC": "LF sênior (LFSC)", "LIG": "LIG", "NC": "Nota comercial", "CDCA": "CDCA",
            "CPR": "CPR"}.get(tipo, tipo)


def anbima_deb(dia):
    """Arquivo da ANBIMA de debêntures do dia (ou o último disponível antes): taxa indicativa, duration, % PU par, NTN-B."""
    ct.anbima()                                                            # baixa os arquivos recentes para o cache
    arqs = sorted(ct.CACHE.glob("anbima_db*.txt"))
    arqs = [f for f in arqs if f.stem[-6:] <= f"{dia:%y%m%d}"]
    if not arqs:
        return pd.DataFrame(columns=["codigo"])
    l = arqs[-1].read_bytes().decode("latin1").splitlines()
    i = next(j for j, s in enumerate(l) if s.startswith("Código@"))
    a = pd.read_csv(io.StringIO("\n".join(l[i:])), sep="@", dtype=str).iloc[:, [0, 1, 3, 6, 10, 11, 12, 14]]
    a.columns = ["codigo", "nome_anbima", "remuneracao_anbima", "taxa_anbima", "pu_anbima", "pct_pu_par", "duration_anbima", "ref_ntnb"]
    for c in ("taxa_anbima", "pu_anbima", "pct_pu_par", "duration_anbima"):
        a[c] = ct.num(a[c])
    a["duration_anbima"] /= 252
    a["data_anbima"] = pd.Timestamp(f"20{arqs[-1].stem[-6:-4]}-{arqs[-1].stem[-4:-2]}-{arqs[-1].stem[-2:]}")
    return a


def anbima_cri_cra(dia):
    """API oficial da ANBIMA (opcional): devedor e taxa indicativa de CRI/CRA. Credenciais só pelo ambiente."""
    cid, sec = os.environ.get("ANBIMA_CLIENT_ID"), os.environ.get("ANBIMA_CLIENT_SECRET")
    if not (cid and sec):
        return pd.DataFrame(columns=["codigo"])
    try:
        tok = requests.post("https://api.anbima.com.br/oauth/access-token", auth=(cid, sec),
                            json={"grant_type": "client_credentials"}, timeout=60).json()["access_token"]
        j = requests.get("https://api.anbima.com.br/feed/precos-indices/v1/cri-cra/mercado-secundario",
                         params={"data": f"{dia:%Y-%m-%d}"}, headers={"client_id": cid, "access_token": tok}, timeout=120).json()
        d = pd.json_normalize(j if isinstance(j, list) else j.get("content", j))
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"  API ANBIMA CRI/CRA indisponível: {e}")
        return pd.DataFrame(columns=["codigo"])
    pega = lambda *ns: next((d[n] for n in ns if n in d), pd.Series(np.nan, index=d.index))
    return pd.DataFrame({"codigo": pega("codigo_ativo", "codigo"), "devedor": pega("devedor", "originador", "emissor"),
                         "taxa_anbima": pd.to_numeric(pega("taxa_indicativa"), errors="coerce"),
                         "duration_anbima": pd.to_numeric(pega("duration"), errors="coerce") / 252})


def monta(dia):
    x = negocios(dia)
    print(f"{len(x)} negócios em {dia:%d/%m/%Y}", flush=True)
    cad = ct.cadastro().drop_duplicates("cod").set_index("cod")
    x = x.join(cad[["incent", "idx", "pct", "taxa", "venc", "temis"]].rename(
        columns={"incent": "incentivada", "idx": "indexador", "pct": "pct_indexador", "taxa": "taxa_emissao", "venc": "vencimento",
                 "temis": "tipo_emissao"}), on="codigo")
    x["incentivada"] = x.incentivada.eq("True")
    x["classe"] = [classe(t, i, e) for t, i, e in zip(x.tipo, x.incentivada, x.emissor)]
    x["pct_indexador"] = ct.num(x.pct_indexador)
    x["taxa_emissao"] = ct.num(x.taxa_emissao)
    x["vencimento"] = pd.to_datetime(x.vencimento, dayfirst=True, errors="coerce")
    x["anos_venc"] = (x.vencimento - pd.Timestamp(dia)).dt.days / 365.25
    # remuneração na forma usual: "DI + 1,50%", "105% do DI", "IPCA + 6,20%", "PRE 12,5%"
    pct_cdi = x.indexador.eq("DI") & x.pct_indexador.notna() & x.pct_indexador.ne(100)
    x["forma"] = np.select([pct_cdi, x.indexador.eq("DI"), x.indexador.eq("IPCA"), x.indexador.eq("PREFIXADO")],
                           ["% do DI", "DI +", "IPCA +", "PRE"], default=x.indexador.fillna("-"))
    # ANBIMA
    a = pd.concat([anbima_deb(dia), anbima_cri_cra(dia)], ignore_index=True).drop_duplicates("codigo")
    x = x.merge(a, on="codigo", how="left")
    x["empresa"] = np.where(x.tipo.isin(["CRI", "CRA"]) & x.get("devedor", pd.Series(index=x.index)).notna(),
                            x.get("devedor", pd.Series(index=x.index)), x.emissor)
    # duration: ANBIMA; senão aproximada pelo prazo
    taxa_dec = (x.taxa_negocio.where(~x.forma.isin(["% do DI", "DI +"])) / 100).fillna(.12)
    x["duration"] = x.duration_anbima.fillna(pd.Series([ct.duracao(t, a_, r) if a_ == a_ and t != "CFF" else np.nan
                                                        for t, a_, r in zip(x.tipo, x.anos_venc, taxa_dec)], index=x.index))
    # spread
    cdi_aa = ((1 + ct.sgs(12, pd.Timestamp(dia) - pd.Timedelta(days=15)).iloc[-1] / 100) ** 252 - 1) * 100
    curvas = ct.Curvas(ct.tesouro(), {}, {})
    ref = [curvas("IPCA" if f == "IPCA +" else "PRE", pd.Timestamp(dia), d) if f in ("IPCA +", "PRE") and d == d else np.nan
           for f, d in zip(x.forma, x.duration)]
    x["curva_ref"] = ref
    x["spread"] = np.select([x.forma.eq("DI +"), x.forma.eq("% do DI"), x.forma.isin(["IPCA +", "PRE"])],
                            [x.taxa_negocio, (x.taxa_negocio / 100 - 1) * cdi_aa, x.taxa_negocio - x.curva_ref], np.nan)
    x["dif_anbima_bps"] = (x.taxa_negocio - x.taxa_anbima) * 100
    cols = ["data", "hora", "classe", "tipo", "codigo", "isin", "emissor", "empresa", "nome_anbima", "forma", "indexador",
            "pct_indexador", "taxa_emissao", "taxa_negocio", "taxa_anbima", "dif_anbima_bps", "spread", "curva_ref", "duration",
            "vencimento", "incentivada", "quantidade", "pu", "pu_anbima", "pct_pu_par", "volume", "origem", "liquidacao", "id",
            "ref_ntnb", "data_anbima"]
    x = x[[c for c in cols if c in x]].sort_values(["classe", "codigo", "hora"])
    # resumo por papel: taxa média ponderada pelo volume
    w = x.assign(tv=x.taxa_negocio * x.volume, sv=x.spread * x.volume, vt=x.volume.where(x.taxa_negocio.notna()),
                 vs=x.volume.where(x.spread.notna()))
    g = w.groupby("codigo")
    papel = g.agg(classe=("classe", "first"), empresa=("empresa", "first"), forma=("forma", "first"), negocios=("id", "count"),
                  volume=("volume", "sum"), taxa_min=("taxa_negocio", "min"), taxa_max=("taxa_negocio", "max"),
                  taxa_anbima=("taxa_anbima", "first"), duration=("duration", "first"), vencimento=("vencimento", "first"),
                  primeiro=("hora", "min"), ultimo=("hora", "max"))
    papel["taxa_media_pond"] = g.tv.sum(min_count=1) / g.vt.sum().where(g.vt.sum() > 0)   # só negócios com taxa
    papel["spread_medio_pond"] = g.sv.sum(min_count=1) / g.vs.sum().where(g.vs.sum() > 0)
    papel["dif_anbima_bps"] = (papel.taxa_media_pond - papel.taxa_anbima) * 100
    return x, papel.sort_values("volume", ascending=False).reset_index()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    hoje = pd.Timestamp.today().normalize()
    dia = hoje if arg == "hoje" else pd.Timestamp(arg) if arg else hoje - pd.offsets.BDay(1)
    x, papel = monta(dia)
    os.makedirs(PASTA, exist_ok=True)
    arq = os.path.join(PASTA, f"negocios_{dia:%Y%m%d}.xlsx")
    with pd.ExcelWriter(arq, engine="xlsxwriter") as xw:
        for nome, df in (("por_papel", papel), ("negocios", x)):
            df.to_excel(xw, sheet_name=nome, index=False)
            ws = xw.sheets[nome]
            ws.autofilter(0, 0, len(df), len(df.columns) - 1)
            ws.freeze_panes(1, 2)
            ws.set_column(0, len(df.columns) - 1, 14)
    print(x.classe.value_counts().to_string())
    print(f"com taxa ANBIMA: {x.taxa_anbima.notna().mean():.0%} | com spread: {x.spread.notna().mean():.0%}")
    print("Gerado:", arq)
