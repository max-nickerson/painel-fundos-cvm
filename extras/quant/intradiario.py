"""
Dados intradiários para o estudo "a ação mexe antes da debênture?":
  1) negócios de balcão da B3 COM HORÁRIO (debêntures), desde 2024-10 (cache em ../dados_monitor/b3, o mesmo do monitor)
  2) barras de 1 hora das ações dos emissores (Yahoo, grátis, últimos ~730 dias) -> dados/acoes_1h.parquet
Uso: python intradiario.py
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

Q = Path(__file__).resolve().parent
sys.path.insert(0, str(Q.parent))
import monitor_fundo as mf  # noqa: E402

dias = pd.bdate_range("2024-10-01", pd.Timestamp.today().normalize() - pd.Timedelta(days=1))
if "barras" not in sys.argv:
    print(f"negócios com horário: {len(dias)} dias...", flush=True)
    with ThreadPoolExecutor(6) as ex:
        n = sum(len(x) for x in ex.map(mf.negocios_dia, dias) if x is not None)
    print(f"  {n} negócios", flush=True)

mapa = pd.read_csv(Q / "dados" / "acoes_mapa.csv", dtype=str)


def barras(tk):
    for tent in range(3):
        try:
            j = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{tk if tk.endswith(".SA") else tk + '.SA'}", params={"range": "730d", "interval": "60m"},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=15).json()["chart"]["result"][0]
            q = j["indicators"]["quote"][0]
            ts = pd.to_datetime(j["timestamp"], unit="s", utc=True).tz_convert("America/Sao_Paulo").tz_localize(None)
            return pd.DataFrame({"ticker": tk, "hora": ts, "close": q["close"], "volume": q["volume"]}).dropna(subset=["close"])
        except (requests.RequestException, KeyError, TypeError, IndexError, ValueError):
            time.sleep(2 * (tent + 1))
    return None


print(f"barras de 1h de {mapa.ticker.nunique()} ações...", flush=True)
with ThreadPoolExecutor(8) as ex:
    b = [x for x in ex.map(barras, mapa.ticker.dropna().unique()) if x is not None]
out = pd.concat(b, ignore_index=True)
out.to_parquet(Q / "dados" / "acoes_1h.parquet")
print(f"  {out.ticker.nunique()} ações, {len(out)} barras, de {out.hora.min()} a {out.hora.max()}")
