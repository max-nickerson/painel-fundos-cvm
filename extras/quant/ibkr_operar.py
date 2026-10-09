"""
Leva a conta da IBKR à carteira-alvo de eurobonds (resultado/hoje/ibkr_alvo.csv) e faz o hedge de câmbio com o futuro de real (6L, CME).
O TWS ou o IB Gateway precisa estar ABERTO e LOGADO por você, com a API ligada (Configure > API > Enable ActiveX and Socket Clients).
Uso:  python ibkr_operar.py --valor 20000 --checar            -> lote mínimo de cada bond na IBKR (nada é enviado)
      python ibkr_operar.py --valor 20000 [--alav 1.5]        -> mostra as ordens (padrão)
      python ibkr_operar.py --valor 20000 --enviar            -> envia ordens LIMITADAS (porta 7497 = conta PAPER; 7496 = real)
--valor = seu capital em US$ para a estratégia (o hedge 6L é sobre ele; a parte alavancada já é dívida em dólar).
Teste primeiro no paper trading: confira se a quantidade dos bonds está em unidades de US$ 1.000 de face.
Requer: pip install ib_async
"""
import argparse
from pathlib import Path

import pandas as pd
from ib_async import IB, Contract, Future, LimitOrder

ap = argparse.ArgumentParser()
ap.add_argument("--valor", type=float, required=True)
ap.add_argument("--alav", type=float, default=1.0)
ap.add_argument("--porta", type=int, default=7497)
ap.add_argument("--checar", action="store_true")
ap.add_argument("--enviar", action="store_true")
ap.add_argument("--folga", type=float, default=.005, help="folga do preço limite (bonds têm spread largo)")
a = ap.parse_args()
FACE = 1000                                                                 # US$ de face por unidade de quantidade (confira no paper)

alvo = pd.read_csv(Path(__file__).resolve().parent / "resultado" / "hoje" / "ibkr_alvo.csv")
ib = IB()
ib.connect("127.0.0.1", a.porta, clientId=17)
pos = {p.contract.conId: p.position for p in ib.positions() if p.contract.secType in ("BOND", "FUT")}
ordens = []
for _, x in alvo.iterrows():
    cd = ib.reqContractDetails(Contract(secType="BOND", secIdType="ISIN", secId=x.isin, exchange="SMART", currency="USD"))
    if not cd:
        print(f"{x.isin} ({x.emissor}): não encontrado na IBKR")
        continue
    c, d = cd[0].contract, cd[0]
    minimo, passo = getattr(d, "minSize", 1) or 1, getattr(d, "sizeIncrement", 1) or 1
    q_alvo = x.peso * a.valor * a.alav / (x.preco / 100) / FACE
    q_alvo = 0 if q_alvo < minimo else round(q_alvo / passo) * passo
    tem = pos.pop(c.conId, 0)
    print(f"{x.isin} {x.emissor[:28]:28s} lote mín. {minimo:g} (US$ {minimo * FACE:,.0f}) | tem {tem:g} | alvo {q_alvo:g}"
          + ("   <- capital pequeno demais para este bond" if q_alvo == 0 and x.peso > 0 else ""))
    if not a.checar and abs(q_alvo - tem) >= passo:
        lado = "BUY" if q_alvo > tem else "SELL"
        lim = round(x.preco * (1 + a.folga if lado == "BUY" else 1 - a.folga), 3)
        ordens.append((c, LimitOrder(lado, abs(q_alvo - tem), lim, tif="DAY")))
for conid, q in pos.items():                                               # bonds que saíram da carteira-alvo
    c = ib.reqContractDetails(Contract(conId=conid))[0].contract
    if c.secType == "BOND" and q:
        print(f"{c.localSymbol}: fora da carteira-alvo -> vender {q:g}")
        ordens.append((c, LimitOrder("SELL", q, None, tif="DAY")))

# hedge de câmbio do capital próprio: comprado em BRL (6L = US$ por BRL, contrato de BRL 100.000)
fut = sorted(ib.reqContractDetails(Future("6L", exchange="CME")), key=lambda d: d.contract.lastTradeDateOrContractMonth)[0].contract
t = ib.reqMktData(fut, "", True, False)
ib.sleep(2)
px = t.last if t.last == t.last else t.close
n_hedge = round(a.valor / (100_000 * px)) if px and px == px else 0
tem6l = next((p.position for p in ib.positions() if p.contract.conId == fut.conId), 0)
print(f"\nhedge: 6L {fut.lastTradeDateOrContractMonth} a {px} | alvo {n_hedge} contrato(s) comprado(s) | tem {tem6l:g}")
if not a.checar and n_hedge != tem6l and px == px:
    ordens.append((fut, LimitOrder("BUY" if n_hedge > tem6l else "SELL", abs(n_hedge - tem6l), round(px, 6), tif="DAY")))

if a.checar:
    print("\n(--checar: nada enviado)")
for c, o in ordens:
    if o.lmtPrice is None:                                                 # venda de bond sem preço nosso: usa a cotação
        t = ib.reqMktData(c, "", True, False)
        ib.sleep(2)
        o.lmtPrice = round((t.bid if t.bid == t.bid else t.close) * (1 - a.folga), 3)
    print(("ENVIANDO" if a.enviar else "SIMULAÇÃO (use --enviar)"), o.action, o.totalQuantity, c.localSymbol or c.secId, "limite", o.lmtPrice)
    if a.enviar:
        ib.placeOrder(c, o)
ib.sleep(2)
ib.disconnect()
