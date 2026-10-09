"""
Executa o sinal do ETF de juros (resultado/hoje/mt5_sinal.csv) na Clear ou na Rico pelo MetaTrader 5.
O terminal do MT5 precisa estar ABERTO e LOGADO por você (o script não guarda nem pede senha).
Uso:  python mt5_operar.py --valor 20000             -> só mostra a ordem (padrão)
      python mt5_operar.py --valor 20000 --enviar    -> envia ordem LIMITADA do dia (preço +-0,2% do último)
Automático: Agendador de Tarefas do Windows, dias úteis ~10h15, depois de rodar operar_hoje.py na noite anterior.
Requer: pip install MetaTrader5
"""
import argparse
import math
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--valor", type=float, required=True, help="R$ destinados à estratégia de juros")
ap.add_argument("--enviar", action="store_true")
ap.add_argument("--folga", type=float, default=.002, help="folga do preço limite")
a = ap.parse_args()

s = pd.read_csv(Path(__file__).resolve().parent / "resultado" / "hoje" / "mt5_sinal.csv").iloc[0]
idade = (pd.Timestamp.today().normalize() - pd.Timestamp(s.data)).days
if idade > 4:
    raise SystemExit(f"sinal de {s.data} está velho ({idade} dias): rode operar_hoje.py --atualizar antes")
if not mt5.initialize():
    raise SystemExit(f"MT5 não abriu: {mt5.last_error()} (abra o terminal e faça login)")
tk = s.ativo
if not mt5.symbol_select(tk, True):
    raise SystemExit(f"{tk} não está disponível nesta corretora/servidor")
info, tick = mt5.symbol_info(tk), mt5.symbol_info_tick(tk)
preco = tick.last or (tick.ask + tick.bid) / 2
passo = info.volume_step or 1
tem = sum(p.volume for p in (mt5.positions_get(symbol=tk) or []))
alvo = math.floor(a.valor * s.alvo / preco / passo) * passo
delta = alvo - tem
print(f"{tk}: sinal {int(s.alvo)} | preço {preco:.2f} | posição {tem:g} | alvo {alvo:g} | ordem {delta:+g}")
if abs(delta) < passo:
    raise SystemExit("nada a fazer")
compra = delta > 0
lim = round((preco * (1 + a.folga) if compra else preco * (1 - a.folga)) / info.trade_tick_size) * info.trade_tick_size
req = {"action": mt5.TRADE_ACTION_PENDING, "symbol": tk, "volume": float(abs(delta)), "price": lim,
       "type": mt5.ORDER_TYPE_BUY_LIMIT if compra else mt5.ORDER_TYPE_SELL_LIMIT,
       "type_time": mt5.ORDER_TIME_DAY, "type_filling": mt5.ORDER_FILLING_RETURN, "comment": "quant juros"}
print(("ENVIANDO" if a.enviar else "SIMULAÇÃO (use --enviar)"), "->", "compra" if compra else "venda", abs(delta), tk, "limite", lim)
if a.enviar:
    r = mt5.order_send(req)
    print("resultado:", r.retcode, r.comment)
mt5.shutdown()
