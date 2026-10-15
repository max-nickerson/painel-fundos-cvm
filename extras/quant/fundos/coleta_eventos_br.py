"""
Coletor de eventos corporativos BR (CVM dados abertos + Yahoo proventos). Tudo com cache em quant/fundos/dados/.
  cvm_ipe.parquet      — IPE 2013+ (fatos relevantes, comunicados, atas, ofertas...) com Data_Entrega (= data de publicação)
  cvm_vlmo.parquet     — VLMO 2018+ (negociação de administradores/controladores) com data de entrega do formulário
  cvm_itr_dfp.parquet  — data de entrega (DT_RECEB) de ITR/DFP 2013+ (lido por HTTP Range: só o índice dentro do zip)
  cvm_fca_vm.parquet   — FCA valores mobiliários (CNPJ -> código de negociação) 2010+
  cvm_cad.parquet      — cadastro de companhias abertas (data de registro, situação)
  y_proventos.parquet  — dividendos e desdobramentos (Yahoo) dos tickers B3 listados com volume
Uso: python coleta_eventos_br.py
"""
import io
import time
import zipfile

import pandas as pd
import requests

from base import D

URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA"
ANO_FIM = pd.Timestamp.today().year
S = requests.Session()


def _get(u, **kw):
    for t in range(5):
        try:
            r = S.get(u, timeout=120, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if t == 4:
                raise
            time.sleep(3 * (t + 1))


def _csv(z, nome):
    return pd.read_csv(z.open(nome), sep=";", encoding="latin1", dtype=str)


def _anos(f, ini, fn):
    """Cache por ano: anos fechados não são re-baixados; o ano corrente é atualizado se o arquivo tem > 1 dia."""
    velho = pd.read_parquet(f) if f.exists() else pd.DataFrame()
    feitos = set(velho["_ano"].unique()) if len(velho) else set()
    fresco = f.exists() and time.time() - f.stat().st_mtime < 86400
    novos = []
    for a in range(ini, ANO_FIM + 1):
        if a in feitos and (a < ANO_FIM - 1 or fresco):
            continue
        try:
            x = fn(a)
        except Exception as e:
            print("  falhou", f.name, a, e)
            continue
        x["_ano"] = a
        novos.append(x)
        print("  ", f.name, a, len(x))
    if novos:
        anos = {n["_ano"].iloc[0] for n in novos if len(n)}
        velho = velho[~velho["_ano"].isin(anos)] if len(velho) else velho
        out = pd.concat([velho] + novos, ignore_index=True)
        out.to_parquet(f)
        return out
    return velho


def ipe():
    def um(a):
        z = zipfile.ZipFile(io.BytesIO(_get(f"{URL}/DOC/IPE/DADOS/ipe_cia_aberta_{a}.zip").content))
        return _csv(z, z.namelist()[0])
    return _anos(D / "cvm_ipe.parquet", 2013, um)


def vlmo():
    def um(a):
        z = zipfile.ZipFile(io.BytesIO(_get(f"{URL}/DOC/VLMO/DADOS/vlmo_cia_aberta_{a}.zip").content))
        cab = _csv(z, f"vlmo_cia_aberta_{a}.csv")[["CNPJ_Companhia", "Data_Referencia", "Versao", "Data_Entrega", "Tipo"]]
        mov = _csv(z, f"vlmo_cia_aberta_con_{a}.csv")
        return mov.merge(cab, on=["CNPJ_Companhia", "Data_Referencia", "Versao"], how="left")
    return _anos(D / "cvm_vlmo.parquet", 2018, um)


class _HttpArq(io.RawIOBase):
    """Arquivo remoto só-leitura via HTTP Range (para ler o índice de um zip de 30 MB sem baixá-lo)."""

    def __init__(self, u):
        self.u, self.p = u, 0
        self.n = int(S.head(u, timeout=60).headers["Content-Length"])

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.p

    def seek(self, o, w=0):
        self.p = o if w == 0 else self.p + o if w == 1 else self.n + o
        return self.p

    def readinto(self, b):
        if self.p >= self.n:
            return 0
        fim = min(self.p + len(b), self.n) - 1
        d = _get(self.u, headers={"Range": f"bytes={self.p}-{fim}"}).content
        b[:len(d)] = d
        self.p += len(d)
        return len(d)


def itr_dfp():
    def um(a):
        out = []
        for doc in ("ITR", "DFP"):
            z = zipfile.ZipFile(io.BufferedReader(_HttpArq(f"{URL}/DOC/{doc}/DADOS/{doc.lower()}_cia_aberta_{a}.zip"), 1 << 20))
            x = _csv(z, f"{doc.lower()}_cia_aberta_{a}.csv")
            x["doc"] = doc
            out.append(x.drop(columns=["LINK_DOC"], errors="ignore"))
        return pd.concat(out)
    return _anos(D / "cvm_itr_dfp.parquet", 2013, um)


def fca_vm():
    def um(a):
        z = zipfile.ZipFile(io.BytesIO(_get(f"{URL}/DOC/FCA/DADOS/fca_cia_aberta_{a}.zip").content))
        return _csv(z, f"fca_cia_aberta_valor_mobiliario_{a}.csv")
    return _anos(D / "cvm_fca_vm.parquet", 2010, um)


def cad():
    f = D / "cvm_cad.parquet"
    if f.exists() and time.time() - f.stat().st_mtime < 7 * 86400:
        return pd.read_parquet(f)
    x = pd.read_csv(io.BytesIO(_get(f"{URL}/CAD/DADOS/cad_cia_aberta.csv").content), sep=";", encoding="latin1", dtype=str)
    x.to_parquet(f)
    return x


def textos(docs, max_n=None):
    """Baixa o PDF de documentos IPE (Link_Download) e guarda o texto (até 40 mil caracteres) em cvm_ipe_textos.parquet."""
    import fitz
    f = D / "cvm_ipe_textos.parquet"
    velho = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["Protocolo_Entrega", "texto"])
    velho = velho[~velho.texto.str.lstrip().str.startswith("<") & ~velho.texto.str.startswith("ERRO")]   # página HTML = limite de acesso
    falta = docs[~docs.Protocolo_Entrega.isin(velho.Protocolo_Entrega)].drop_duplicates("Protocolo_Entrega")
    if max_n:
        falta = falta.head(max_n)
    novos = []
    for i, (pr, u) in enumerate(zip(falta.Protocolo_Entrega, falta.Link_Download)):
        try:
            for k in range(6):                                            # o RAD devolve HTML quando limita o acesso: espera e tenta de novo
                b = _get(u).content
                if not b.lstrip()[:1] == b"<":
                    break
                time.sleep(5 * (k + 1))
            if b.lstrip()[:1] == b"<":
                continue
            if b[:4] == b"%PDF":
                with fitz.open(stream=b, filetype="pdf") as doc:
                    t = "".join(pg.get_text() for pg in doc)[:40000]
            else:
                t = b[:40000].decode("latin1", "ignore")
        except Exception as e:
            t = f"ERRO {e}"[:200]
        novos.append((pr, t))
        if (i + 1) % 50 == 0 or i + 1 == len(falta):
            velho = pd.concat([velho, pd.DataFrame(novos, columns=["Protocolo_Entrega", "texto"])], ignore_index=True)
            velho.to_parquet(f)
            novos = []
            print("   textos", i + 1, "/", len(falta), flush=True)
    return velho


def proventos(tickers):
    """Dividendos/JCP e desdobramentos/bonificações do Yahoo (só tickers ainda listados; deslistados ficam sem dividendo)."""
    import yfinance as yf
    f = D / "y_proventos.parquet"
    velho = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["data", "ticker", "div", "split", "close"])
    falta = sorted(set(tickers) - set(velho.ticker.unique()))
    out = []
    for i in range(0, len(falta), 50):
        lote = [t + ".SA" for t in falta[i:i + 50]]
        try:
            x = yf.download(lote, start="2013-06-01", auto_adjust=False, actions=True, progress=False, threads=True, group_by="column")
        except Exception as e:
            print("  yahoo falhou", e)
            continue
        if x is None or x.empty:
            continue
        for t in lote:
            try:
                d = pd.DataFrame({"div": x["Dividends"][t], "split": x["Stock Splits"][t], "close": x["Close"][t]}).dropna(subset=["close"])
            except KeyError:
                continue
            d = d.reset_index().rename(columns={"Date": "data"})
            d["ticker"] = t[:-3]
            out.append(d[["data", "ticker", "div", "split", "close"]])
        marcados = pd.DataFrame({"ticker": [t[:-3] for t in lote]})               # marca como tentado (mesmo sem dados)
        out.append(marcados.assign(data=pd.NaT, div=0.0, split=0.0, close=float("nan")))
        print("   yahoo", i + len(lote), "/", len(falta))
    if out:
        velho = pd.concat([velho] + out, ignore_index=True)
        velho["data"] = pd.to_datetime(velho["data"]).dt.tz_localize(None)
        velho.to_parquet(f)
    return velho


def cotahist_acoes():
    """Re-lê os COTAHIST anuais (quant/dados/cotahist) para ações INCLUINDO CODBDI 05-09 (sancionadas, recuperação judicial etc.,
    que b3_vista.parquet omite — viés de sobrevivência justamente nos eventos ruins) e com máxima/mínima do dia."""
    from base import DQ
    f = D / "b3_acoes_cotahist.parquet"
    zs = sorted((DQ / "cotahist").glob("COTAHIST_A*.ZIP"))
    if f.exists() and f.stat().st_mtime > max(z.stat().st_mtime for z in zs):
        return pd.read_parquet(f)
    out = []
    for z in zs:
        with zipfile.ZipFile(z) as zz:
            linhas = zz.open(zz.namelist()[0]).read().decode("latin1").splitlines()
        reg = [l for l in linhas if l[:2] == "01" and l[24:27] == "010" and l[10:12] in ("02", "05", "06", "07", "08", "09")]
        n = lambda a, b: [int(l[a:b]) for l in reg]
        x = pd.DataFrame({"data": pd.to_datetime([l[2:10] for l in reg]), "ticker": [l[12:24].strip() for l in reg],
                          "codbdi": [l[10:12] for l in reg], "especi": [l[39:49] for l in reg],
                          "abertura": n(56, 69), "max": n(69, 82), "min": n(82, 95), "fech": n(108, 121),
                          "oferta_compra": n(121, 134), "oferta_venda": n(134, 147), "negocios": n(147, 152),
                          "quantidade": n(152, 170), "volume": n(170, 188), "fatcot": n(210, 217)})
        for c in ("abertura", "max", "min", "fech", "oferta_compra", "oferta_venda", "volume"):
            x[c] = x[c] / 100
        out.append(x)
        print("  ", z.name, len(x))
    x = pd.concat(out, ignore_index=True)
    x.to_parquet(f)
    return x


if __name__ == "__main__":
    print("cotahist", len(cotahist_acoes()))
    for fn in (cad, fca_vm, ipe, vlmo, itr_dfp):
        x = fn()
        print(fn.__name__, len(x))
    v = pd.read_parquet(D / "b3_vista.parquet", columns=["data", "ticker", "volume"])
    v = v[v.ticker.str.match(r"^[A-Z]{4}(3|4|5|6|11)$")]
    liq = v.groupby("ticker").volume.median()
    print("proventos", len(proventos(liq[liq > 5e5].index)))
