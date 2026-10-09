"""
Previsões de analistas (Banco Central, Focus): consenso de todos x Top 5 (os 5 mais certeiros do ranking do BC), desde 2018.
Indicadores: Selic, IPCA e câmbio do ano corrente e do seguinte. Disponível 3 dias úteis depois da data da pesquisa.
Saída: dados/analistas.parquet (diário): nível, divergência Top5 - consenso, revisões de 4 semanas.
"""
import urllib.parse
from pathlib import Path

import pandas as pd
import requests

D_ = Path(__file__).resolve().parent / "dados"
BASE = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"


def busca(servico, filtro):
    u = BASE + servico + "?" + urllib.parse.quote(f"$filter={filtro} and Data ge '2018-06-01'", safe="=$&'") + "&$format=json"
    return pd.DataFrame(requests.get(u, timeout=300).json()["value"])


partes = []
for ind in ("Selic", "IPCA", "Câmbio"):
    todos = busca("ExpectativasMercadoAnuais", f"Indicador eq '{ind}'")
    todos = todos[todos.baseCalculo.eq(0)] if "baseCalculo" in todos else todos
    top5 = busca("ExpectativasMercadoTop5Anuais", f"Indicador eq '{ind}' and tipoCalculo eq 'M'")
    for nome, d in (("consenso", todos), ("top5", top5)):
        d = d.assign(Data=pd.to_datetime(d.Data), ano=d.DataReferencia.astype(int))
        d["h"] = d.ano - d.Data.dt.year                                    # 0 = ano corrente, 1 = ano seguinte
        d = d[d.h.isin([0, 1])].groupby(["Data", "h"]).Mediana.last().unstack()
        d.columns = [f"{ind}_{nome}_{'ano' if h == 0 else 'prox'}" for h in d.columns]
        partes.append(d)
x = pd.concat(partes, axis=1).sort_index().ffill()
dias = pd.bdate_range(x.index.min(), pd.Timestamp.today())
x = x.reindex(dias).ffill().shift(3)                                       # publicação e defasagem
for ind in ("Selic", "IPCA", "Câmbio"):
    for h in ("ano", "prox"):
        c, t = f"{ind}_consenso_{h}", f"{ind}_top5_{h}"
        if c in x and t in x:
            x[f"an_gap_{ind}_{h}"] = x[t] - x[c]                              # o que os melhores veem diferente do consenso
            x[f"an_rev4s_{ind}_top5_{h}"] = x[t] - x[t].shift(20)
            x[f"an_rev4s_{ind}_cons_{h}"] = x[c] - x[c].shift(20)
x.columns = [c if c.startswith("an_") else "an_" + c for c in x.columns]
x.index.name = "date"
x.to_parquet(D_ / "analistas.parquet")
print(x.shape, x.dropna().index.min(), x.index.max())
print(x.iloc[-1].round(3).to_string())
