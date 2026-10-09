"""
Carteiras-modelo de HOJE das três estratégias (CDI+1, CDI+5, CDI+10), operando por sinal e sem stop.
  Crédito e eurobonds: a simulação por sinal é rodada até ontem; o que ela carrega hoje é a carteira-modelo.
  Juros: o voto (tendência de 21 dias, inclinação, modelo) é recalculado com os futuros da B3 AO VIVO e aplicado com histerese.
Saídas em quant/resultado/: carteira_modelo_<perfil>.csv (codigo, categoria, perc_nav), ordens_hoje.csv e juros_hoje.json.
O monitor ao vivo lê esses arquivos:  python monitor_fundo.py "modelo CDI+5"
Uso: python sinais_ao_vivo.py   (rodar uma vez por dia, depois de dados.py)
"""
import io
import json
import contextlib

import numpy as np
import pandas as pd
import requests

with contextlib.redirect_stdout(io.StringIO()):
    import estrategias_sinal as s
ed, e, dias = s.ed, s.e, s.dias
S = s.S
hoje = pd.Timestamp.today().normalize()


def ao_vivo(cls, anos):
    """Taxa interpolada no prazo com a cotação atual dos futuros da B3 (15 min); sem negócio, usa o ajuste anterior."""
    try:
        sc = requests.get(f"https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/{cls}", timeout=20).json().get("Scty", [])
    except (requests.RequestException, ValueError):
        return np.nan
    xs = sorted(((pd.Timestamp(x["asset"]["AsstSummry"]["mtrtyCode"]) - hoje).days / 365.25, x["SctyQtn"].get("curPrc") or x["SctyQtn"].get("prvsDayAdjstmntPric"))
                for x in sc if x.get("asset", {}).get("AsstSummry", {}).get("mtrtyCode"))
    xs = [(t, v) for t, v in xs if t > .08 and v]
    return float(np.interp(anos, [t for t, _ in xs], [v for _, v in xs])) if len(xs) >= 3 else np.nan


# ------------------------------------------------------------------ juros: voto de hoje com os futuros ao vivo
agora = {"dap5": ao_vivo("DAP", 5), "di2": ao_vivo("DI1", 2), "di1a": ao_vivo("DI1", 1), "di5": ao_vivo("DI1", 5)}
hist = {"dap5": ed.dap5, "di2": ed.di2, "di1a": ed.di1a, "di5": ed.di5}
incl = (ed.di5 - ed.di1a).dropna()
incl_hoje = agora["di5"] - agora["di1a"]
juros = {}
for col, k, nome in (("p_dap", "dap5", "DAP 5 anos"), ("p_di1", "di2", "DI1 2 anos")):
    v = hist[k].dropna()
    tend = -np.sign(agora[k] - v.iloc[-21])
    inc = np.sign(incl_hoje - incl.iloc[-500:].median())
    ml = np.sign(ed.pj[col].dropna().iloc[-1] - .5)
    voto = (tend + inc + ml) / 3
    ant = s.pos[col].dropna().iloc[-1]
    novo = np.sign(voto) if abs(voto) >= .99 else (0.0 if ant * voto < 0 else ant)
    juros[nome] = {"taxa_agora": round(agora[k], 3), "taxa_21d_atras": round(float(v.iloc[-21]), 3), "voto": round(float(voto), 2),
                   "tendencia": int(tend), "inclinacao": int(inc), "modelo": int(ml), "posicao_ontem": int(ant), "posicao_hoje": int(novo),
                   "leitura": {1: "RECEBIDO (aposta na queda da taxa)", -1: "PAGO (aposta na alta da taxa)", 0: "ZERADO"}[int(novo)]}

# ------------------------------------------------------------------ crédito: o que a simulação por sinal carrega hoje
livros = {}
for nome, f, ret, preco, n, custo, stop, em in [
        ("cons", s.forca("score", ed.lim(-1, 3, 5)), ed.exc_hed, ed.Pi, 30, ed.CUSTO["cons"], s.STOP_DEB, s.emis),
        ("mod", s.forca("score", ed.lim(-1, 8)), s.exc_sinal, ed.Pi, 25, ed.CUSTO["mod"], s.STOP_DEB, s.emis),
        ("hy", s.forca("spread", ed.lim(2, 40)), s.exc_sinal, ed.Pi, 20, ed.CUSTO["hy"], s.STOP_DEB, s.emis),
        ("eb", s.forca_eb(), ed.exc_eb, ed.PE, 15, e.CUSTO_EXT, s.STOP_EB, s.emis_eb)]:
    s.livro(f, ret, preco, n, custo, stop, em)
    livros[nome] = (s.livro.final, s.livro.ordens)
cat = ed.b.drop_duplicates("codigo").set_index("codigo")
categoria = lambda k: "Bonds" if k.startswith(("US", "XS")) else ("DEBIN" if cat.at[k, "incentivada"] else "DEB") if k in cat.index else "DEB"
perfis = {"CDI+1": {"cons": .8, "eb": .2}, "CDI+5": {"mod": 1.4, "eb": .6}, "CDI+10": {"hy": 2.1, "eb": .9}}
alav = {"CDI+1": (0, 0), "CDI+5": (1.5, 1.0), "CDI+10": (3.0, 2.0)}
ordens = []
for p, mix in perfis.items():
    pos = {}
    for liv, w in mix.items():
        for k, peso in livros[liv][0].items():
            pos[k] = pos.get(k, 0) + w * peso
        ordens += [{"perfil": p, "data": d.strftime("%d/%m/%Y"), "codigo": k, "ordem": o} for d, k, o in livros[liv][1] if d >= dias[-6]]
    isin_snd = pd.read_parquet(e.DADOS / "snd_negocios.parquet", columns=["codigo", "isin"]).drop_duplicates("codigo").set_index("codigo")["isin"]
    df = pd.DataFrame([{"codigo": k, "isin": isin_snd.get(k, k), "categoria": categoria(k), "perc_nav": v} for k, v in pos.items()])
    df.loc[len(df)] = {"codigo": "caixa", "categoria": "Cash", "perc_nav": max(1 - df.perc_nav.sum(), 0) if len(df) else 1}
    df.to_csv(S / f"carteira_modelo_{p}.csv", index=False)
    dap, di = alav[p]
    print(f"\n{p}: {len(df) - 1} papéis, {df.perc_nav[df.codigo != 'caixa'].sum() * 100:.0f}% do PL em crédito"
          + (f"; juros: DAP {dap:g}x {juros['DAP 5 anos']['leitura']}, DI1 {di:g}x {juros['DI1 2 anos']['leitura']}" if dap else ""))
    print(df.sort_values("perc_nav", ascending=False).head(8).assign(perc_nav=lambda x: (x.perc_nav * 100).round(2)).to_string(index=False))
pd.DataFrame(ordens).drop_duplicates().to_csv(S / "ordens_hoje.csv", index=False)
json.dump({"gerado": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"), "juros": juros, "alavancagem": alav}, open(S / "juros_hoje.json", "w"), indent=1, ensure_ascii=False)
print("\nJuros agora:", json.dumps(juros, ensure_ascii=False, indent=1))
print("\nOrdens dos últimos 5 dias:", pd.DataFrame(ordens).drop_duplicates().groupby(["perfil", "ordem"]).size().to_dict())
