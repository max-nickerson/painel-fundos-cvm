"""
Rodada final: roda TODOS os fundos (rodada 1 + ideias_*.py) na mesma base, já com os bugs corrigidos, sem taxa de gestão/performance,
e com o regime de mercado como dimensão extra da grade (escolhido só no IS).
Uso: python rodada_final.py <modulo>     (rodar | ideias_eventos_br | ideias_credito | ...)   -> resultado/final/<modulo>.pkl
"""
import pickle
import sys
import time
import traceback
from pathlib import Path

import importlib

from base import CDI
from motor import roda
from regimes import com_regime
from rodar import BENCH

OUT = Path(__file__).resolve().parent / "resultado" / "final"
OUT.mkdir(parents=True, exist_ok=True)

# fundos que a auditoria mostrou serem artefato de medição (não entram no ranking)
EXCLUI = {"02 Financiador a termo": "taxa travada vem de preços não simultâneos (termo x à vista); some com preço médio e t+1",
          "20 Multiestratégia (pods)": "73% do resultado vinha do termo (artefato)",
          "A4 Termo conservador": "mesmo artefato do termo (IR 29 = posição não marcada a mercado)"}

if __name__ == "__main__":
    mod = sys.argv[1]
    m = importlib.import_module(mod)
    log = open(OUT / f"{mod}.log", "w", encoding="utf-8")
    res = []
    for f in (getattr(m, "FUNDOS", None) or m._fundos()):
        if f.nome in EXCLUI:
            continue
        t = time.time()
        try:
            r = roda(com_regime(f), CDI, BENCH[f.benchmark], lambda *a: None)
        except Exception:
            log.write(f"{f.nome}: ERRO\n{traceback.format_exc()}\n")
            continue
        if not r:
            log.write(f"{f.nome}: sem resultado\n")
            continue
        r["modulo"] = mod
        r["fundo"].func = None
        res.append(r)
        o, rb = r["oos"], r["rob"]
        s = (f"{f.nome} | {r['params']} | OOS {o['retorno a.a. %']:.1f}% vs {o['benchmark a.a. %']:.1f}% (ativo {o['ativo a.a. pp']:+.1f}, IR {o['IR vs bench']:.2f})"
             f" | P {rb['P(bater bench OOS) %']:.0f}% | PBO {rb['PBO %']:.0f}% | x2 {rb['OOS custo x2 (pp)']:+.1f} | +1d {rb['OOS execução +1 dia (pp)']:+.1f} | {time.time() - t:.0f}s")
        print(s, flush=True)
        log.write(s + "\n")
        log.flush()
    pickle.dump(res, open(OUT / f"{mod}.pkl", "wb"))
    print("pronto", mod)
