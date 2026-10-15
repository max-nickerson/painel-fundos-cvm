"""Ajustes diários dos futuros agrícolas/commodities da B3 (boletim BVBG.086 'PR', 2018+), todos os vencimentos.
Cache por dia em dados/b3_agro/ ; consolidado em dados/b3_futuros_agro.parquet. Mesma fonte de quant/dados.py."""
import io, re, sys, time, zipfile
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd, requests
from base import D, DIAS

PASTA = D / "b3_agro"
PASTA.mkdir(exist_ok=True)
FUT = re.compile(rb"<TckrSymb>((?:BGI|CCM|ICF|SJC|ETH|ETN|SOY|CNL|GLD)[FGHJKMNQUVXZ]\d\d)</TckrSymb>")
CAMPOS = ["AdjstdQt", "PrvsAdjstdQt", "OpnIntrst", "FinInstrmQty", "NtlFinVol"]
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"


def dia(d):
    f = PASTA / f"{d:%Y%m%d}.parquet"
    if f.exists():
        return
    for t in range(4):
        try:
            c = S.get(f"https://www.b3.com.br/pesquisapregao/download?filelist=PR{d:%y%m%d}.zip,", timeout=180).content
            break
        except requests.RequestException:
            time.sleep(5 * (t + 1))
    else:
        return
    try:
        z = zipfile.ZipFile(io.BytesIO(c))
        z2 = zipfile.ZipFile(io.BytesIO(z.read(z.namelist()[0])))
    except (zipfile.BadZipFile, IndexError):            # resposta inválida (limite de requisições): tenta de novo na próxima rodada
        return
    lin = []
    for n in z2.namelist():
        t = z2.read(n)
        for m in FUT.finditer(t):
            b = t[m.end(): t.find(b"</PricRpt>", m.end())]
            r = {"date": d, "ticker": m.group(1).decode()}
            for k in CAMPOS:
                v = re.search(rb"<" + k.encode() + rb"[^>]*>([-\d.]+)<", b)
                r[k] = float(v.group(1)) if v else np.nan
            lin.append(r)
    pd.DataFrame(lin).to_parquet(f)


def baixa():
    ds = [d for d in DIAS if d >= pd.Timestamp("2018-01-01")]
    for f in PASTA.glob("*.parquet"):
        if f.stat().st_size < 1500:
            f.unlink()
    ds = [d for d in ds if not (PASTA / f"{d:%Y%m%d}.parquet").exists()]
    with ProcessPoolExecutor(3) as ex:
        list(ex.map(dia, ds, chunksize=4))
    fs = [f for f in sorted(PASTA.glob("*.parquet")) if f.stat().st_size > 1500]
    x = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
    x.to_parquet(D / "b3_futuros_agro.parquet")
    print(x.shape, x.date.min(), x.date.max())


if __name__ == "__main__":
    baixa()
