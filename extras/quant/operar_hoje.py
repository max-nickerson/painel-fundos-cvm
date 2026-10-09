"""
O que operar HOJE em cada conta (estratégia pessoal, custos de varejo; ver pessoal.py).
  Rico  (manual, não tem API): ranking das debêntures de varejo pela nota do modelo; o que comprar e o que vender da sua carteira.
         Opcional: quant/minhas_debentures.csv (codigo,data_compra) e quant/rico_prateleira.csv (codigo,taxa) colados da área logada.
  Clear (automático via MetaTrader 5 -> mt5_operar.py): sinal 0/1 do ETF de juros (DI 2 anos ao vivo vs 21 dias úteis atrás).
  IBKR  (automático via TWS/Gateway -> ibkr_operar.py): carteira-alvo de eurobonds (ISIN e peso) e hedge de câmbio.
Uso:  python operar_hoje.py              (usa a base já baixada)
      python operar_hoje.py --atualizar  (antes baixa os dados do dia: dados.py + base_diaria.py; rodar depois das 20h)
Saídas em quant/resultado/hoje/: rico.csv, mt5_sinal.csv, ibkr_alvo.csv, resumo.txt
"""
import contextlib
import io
import pickle
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

Q = Path(__file__).resolve().parent
if "--atualizar" in sys.argv:
    for f in ("dados.py", "base_diaria.py"):
        print(f"rodando {f}...", flush=True)
        subprocess.run([sys.executable, "-W", "ignore", str(Q / f)], cwd=Q, check=True)

import pesquisa_credito as pc  # noqa: E402
from sklearn.linear_model import Ridge  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

import pessoal as ps  # noqa: E402

S, B, dias = pc.S, pc.B, pc.dias
OUT = S / "hoje"
OUT.mkdir(exist_ok=True)
esc = pd.read_pickle(S / "pessoal_escolhas.pkl")
_, FAIXA, SAI, SEGURA = esc["rico"][:4]
ETF = esc["etf"][1]
txt = []
p = lambda *a: (print(*a, flush=True), txt.append(" ".join(str(x) for x in a)))
hoje = dias[-1]
p(f"base até {hoje:%d/%m/%Y} | Rico: faixa {FAIXA}, vende se nota < {SAI} e segurou {SEGURA} dias úteis | Clear: {ETF}")

# ------------------------------------------------------------------ Rico: nota do modelo para os papéis de hoje
print("painel e nota do modelo...", flush=True)
df = pc.painel()
df["D"] = df.groupby("codigo").D.ffill()                                    # duration é mensal: no mês corrente usa a última
jf = pd.read_parquet(S / "juros_features.parquet").reindex(dias).ffill()  # fatores de mercado: último disponível
for c in [c for c in df if c in jf.columns]:
    df[c] = df.date.map(jf[c])
feats = [c for c in df if c not in pc.NAO_FEAT and df[c].dtype != object]
arq = S / "modelo_ridge_varejo.pkl"
if not arq.exists() or time.time() - arq.stat().st_mtime > 21 * 86400 or pickle.load(open(arq, "rb"))[1] != feats:
    print("retreinando o ridge (1x por mês)...", flush=True)
    corte = dias[max(len(dias) - pc.HZ - 3, 0)]
    tr = df[(df.date <= corte) & df.alvo_rel.notna()].iloc[::3]
    m = make_pipeline(StandardScaler(), Ridge(alpha=100)).fit(tr[feats].fillna(0), tr.alvo_rel.clip(*tr.alvo_rel.quantile([.01, .99])))
    pickle.dump((m, feats), open(arq, "wb"))
m, feats = pickle.load(open(arq, "rb"))
h = df[df.date.eq(df.date.max())].copy()
h["ridge"] = m.predict(h[feats].fillna(0))
varejo = ps.universo_varejo().iloc[-1]
h = h[pc.FAIXAS[FAIXA][0](h) & h.codigo.map(varejo).eq(True)]
h["nota"] = h.ridge.rank(pct=True)
h = h.sort_values("nota", ascending=False)
cad = B["cad"]
h["vencimento"] = h.codigo.map(cad.venc).dt.strftime("%d/%m/%Y")
rico = h[["codigo", "empresa", "indice", "spread", "D", "nota", "vencimento"]].rename(columns={"D": "duration", "indice": "indexador"})
rico["acao"] = np.where(rico.nota >= .8, "comprar (topo)", np.where(rico.nota < SAI, "evitar / vender", "manter se tiver"))
dia_decisao = hoje.to_period("M") != dias[-2].to_period("M")               # 1o dia útil do mês (como no backtest)
mp = Q / "minhas_debentures.csv"
if mp.exists():
    meus = pd.read_csv(mp, parse_dates=["data_compra"], dayfirst=True)
    meus = meus.merge(rico[["codigo", "nota"]], on="codigo", how="left")
    meus["dias_uteis"] = [np.busday_count(d.date(), pd.Timestamp.today().date()) for d in meus.data_compra]
    meus["ordem"] = np.where(meus.nota.isna(), "sem nota hoje (fora do universo): revisar",
                             np.where((meus.nota < SAI) & (meus.dias_uteis >= SEGURA), "VENDER", "manter"))
    p("\nSUA CARTEIRA NA RICO:\n" + meus.to_string(index=False))
pp = Q / "rico_prateleira.csv"
if pp.exists():                                                            # cruza com a prateleira que você colou
    pr_ = pd.read_csv(pp).merge(rico, on="codigo", how="left")
    p("\nPRATELEIRA DA RICO x MODELO (taxa da prateleira vs nota):\n" + pr_.sort_values("nota", ascending=False).to_string(index=False))
rico.to_csv(OUT / "rico.csv", index=False)
p(f"\nRICO ({'DIA DE DECISÃO: rebalanceie' if dia_decisao else 'não é dia de decisão: só olhe vendas forçadas'}) — topo do ranking "
  f"(compre até {ps.N_RICO} papéis, 1 por emissor, R$ igual em cada):")
top = rico[rico.nota >= .8].drop_duplicates("empresa").head(ps.N_RICO)
p(top.round(2).to_string(index=False))

# ------------------------------------------------------------------ Clear / MT5: sinal do ETF de juros com o DI ao vivo
def di_ao_vivo(anos=2):
    try:
        sc = requests.get("https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/DI1", timeout=20).json().get("Scty", [])
    except (requests.RequestException, ValueError):
        return np.nan
    xs = sorted(((pd.Timestamp(x["asset"]["AsstSummry"]["mtrtyCode"]) - pd.Timestamp.today()).days / 365.25,
                 x["SctyQtn"].get("curPrc") or x["SctyQtn"].get("prvsDayAdjstmntPric"))
                for x in sc if x.get("asset", {}).get("AsstSummry", {}).get("mtrtyCode"))
    xs = [(t, v) for t, v in xs if t > .08 and v]
    return float(np.interp(anos, [t for t, _ in xs], [v for _, v in xs])) if len(xs) >= 3 else np.nan


di2 = B["curvas"]["DI1_2a"].dropna()
agora = di_ao_vivo()
agora = di2.iloc[-1] if np.isnan(agora) else agora
ref = di2.iloc[-21]                                                        # 21 dias úteis atrás (com o dia de hoje como o 21o)
sinal = int(agora < ref)
pd.DataFrame([{"data": pd.Timestamp.today().strftime("%Y-%m-%d"), "ativo": ETF, "alvo": sinal, "di2_agora": agora, "di2_21d": ref}]) \
    .to_csv(OUT / "mt5_sinal.csv", index=False)
p(f"\nCLEAR / MT5: DI 2 anos agora {agora:.2f}% x {ref:.2f}% há 21 dias úteis -> {ETF}: "
  f"{'COMPRADO (100% do valor da estratégia)' if sinal else 'ZERADO (dinheiro no Tesouro Selic)'}  [executa amanhã: mt5_operar.py]")

# ------------------------------------------------------------------ IBKR: eurobonds por sinal
with contextlib.redirect_stdout(io.StringIO()):
    import estrategias_sinal as es
es.livro(es.forca_eb(), es.ed.exc_eb, es.ed.PE, 15, .0025, -9, es.emis_eb)
alvo = pd.Series(es.livro.final, name="peso").rename_axis("isin").reset_index()
alvo["peso"] = alvo.peso / alvo.peso.sum() if alvo.peso.sum() > 0 else alvo.peso
alvo["emissor"] = alvo["isin"].map(es.emis_eb)
alvo["preco"] = alvo["isin"].map(es.ed.PE.ffill().iloc[-1])
alvo.to_csv(OUT / "ibkr_alvo.csv", index=False)
p(f"\nIBKR: carteira-alvo de eurobonds ({len(alvo)} papéis, pesos iguais no livro) [ibkr_operar.py faz as ordens e o hedge 6L]:")
p(alvo.round(3).to_string(index=False))
open(OUT / "resumo.txt", "w", encoding="utf-8").write("\n".join(txt))
print(f"\narquivos em {OUT}")
