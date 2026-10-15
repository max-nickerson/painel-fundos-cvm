"""Dados novos da frente de crédito (cache em quant/fundos/dados, nunca re-baixa o que existe):
  cvm_ipe.parquet       — IPE (fatos relevantes, comunicados, RJ) 2019+ só colunas úteis, com Data_Entrega
  cvm_cad_cia.parquet   — cadastro CVM de companhias (CNPJ -> setor, situação)
  cvm_fii_mensal.parquet — informe mensal de FII 2017+ (VP/cota, DY, segmento, ISIN, data de entrega)
"""
import io
import zipfile

import pandas as pd
import requests

from base import D

URL = "https://dados.cvm.gov.br/dados"


def _zip(u):
    r = requests.get(u, timeout=180)
    r.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(r.content))


def ipe():
    f = D / "cvm_ipe.parquet"
    if f.exists():                                       # pode ter sido baixado por outra frente (mesmo layout CVM)
        d = pd.read_parquet(f)
        d["cnpj"] = d.CNPJ_Companhia.astype(str).str.replace(r"\D", "", regex=True).str.zfill(14)
        d["Data_Entrega"] = pd.to_datetime(d.Data_Entrega, errors="coerce")
        return d
    out = []
    for a in range(2019, pd.Timestamp.today().year + 1):
        z = _zip(f"{URL}/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{a}.zip")
        d = pd.read_csv(z.open(z.namelist()[0]), sep=";", encoding="latin1", dtype=str)
        out.append(d[["CNPJ_Companhia", "Nome_Companhia", "Categoria", "Tipo", "Assunto", "Data_Referencia", "Data_Entrega"]])
    d = pd.concat(out, ignore_index=True)
    d["cnpj"] = d.CNPJ_Companhia.str.replace(r"\D", "", regex=True).str.zfill(14)
    d["Data_Entrega"] = pd.to_datetime(d.Data_Entrega, errors="coerce")
    d.to_parquet(f)
    return d


def cad_cia():
    f = D / "cvm_cad_cia.parquet"
    if f.exists():
        return pd.read_parquet(f)
    d = pd.read_csv(io.BytesIO(requests.get(f"{URL}/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv", timeout=180).content), sep=";", encoding="latin1", dtype=str)
    d["cnpj"] = d.CNPJ_CIA.str.replace(r"\D", "", regex=True).str.zfill(14)
    d = d[["cnpj", "DENOM_SOCIAL", "SETOR_ATIV", "SIT", "CATEG_REG", "TP_MERC"]]
    d.to_parquet(f)
    return d


def fii():
    f = D / "cvm_fii_mensal.parquet"
    if f.exists():
        return pd.read_parquet(f)
    out = []
    for a in range(2017, pd.Timestamp.today().year + 1):
        try:
            z = _zip(f"{URL}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{a}.zip")
        except requests.RequestException:
            continue
        nm = {k: [n for n in z.namelist() if k in n][0] for k in ("geral", "complemento")}
        g = pd.read_csv(z.open(nm["geral"]), sep=";", encoding="latin1", dtype=str)
        c = pd.read_csv(z.open(nm["complemento"]), sep=";", encoding="latin1", dtype=str)
        cf = "CNPJ_Fundo_Classe" if "CNPJ_Fundo_Classe" in g else "CNPJ_Fundo"
        g = g.rename(columns={cf: "cnpj_f"})
        c = c.rename(columns={("CNPJ_Fundo_Classe" if "CNPJ_Fundo_Classe" in c else "CNPJ_Fundo"): "cnpj_f"})
        g = g[["cnpj_f", "Data_Referencia", "Versao", "Data_Entrega", "Codigo_ISIN", "Mandato", "Segmento_Atuacao"] +
              [x for x in ("Nome_Fundo_Classe", "Nome_Fundo") if x in g]].rename(columns={"Nome_Fundo_Classe": "nome", "Nome_Fundo": "nome"})
        c = c[["cnpj_f", "Data_Referencia", "Versao", "Patrimonio_Liquido", "Cotas_Emitidas", "Valor_Patrimonial_Cotas",
               "Percentual_Dividend_Yield_Mes", "Percentual_Rentabilidade_Patrimonial_Mes", "Percentual_Amortizacao_Cotas_Mes"]]
        out.append(g.merge(c, on=["cnpj_f", "Data_Referencia", "Versao"], how="inner"))
    d = pd.concat(out, ignore_index=True)
    for x in ("Patrimonio_Liquido", "Cotas_Emitidas", "Valor_Patrimonial_Cotas", "Percentual_Dividend_Yield_Mes",
              "Percentual_Rentabilidade_Patrimonial_Mes", "Percentual_Amortizacao_Cotas_Mes", "Versao"):
        d[x] = pd.to_numeric(d[x].str.replace(",", "."), errors="coerce")
    d["Data_Referencia"] = pd.to_datetime(d.Data_Referencia, errors="coerce")
    d["Data_Entrega"] = pd.to_datetime(d.Data_Entrega, errors="coerce")
    d = d.sort_values("Versao").drop_duplicates(["cnpj_f", "Data_Referencia"], keep="last")
    d.to_parquet(f)
    return d


if __name__ == "__main__":
    for fn in (ipe, cad_cia, fii):
        x = fn()
        print(fn.__name__, x.shape)
