"""
Base diária para a pesquisa quant: roda o estrategias_diario uma vez e guarda em resultado/base_diaria.pkl o que os modelos usam.
  dias, cdi, F (retorno diário de cada futuro), TX (taxa de ajuste), OI (contratos em aberto), VENC,
  curva DI1 e DAP em vértices fixos (0,5 a 10 anos), retornos dos contratos de 2 e 5 anos,
  debêntures: R (retorno diário sem hedge), Hdd (hedge), Pi/P (preço interpolado/observado), Dd (duration), cad, custos intradiários,
  eurobonds: exc_eb (excesso diário com hedge de câmbio e Treasury), PE (preço), cadastro.
Uso: python base_diaria.py
"""
import contextlib
import io

import numpy as np
import pandas as pd

with contextlib.redirect_stdout(io.StringIO()):
    import estrategias_diario as ed

print("vértices adicionais...", flush=True)
vert = {}
for cls, prazos in (("DI1", [.5, 1, 2, 3, 5, 8, 10]), ("DAP", [2, 3, 5, 8, 10])):
    cols = [c for c in ed.TX.columns if c.startswith(cls)]
    T = np.column_stack([(ed.VENC[c] - ed.dias).days.values / 365.25 for c in cols])
    X = ed.TX[cols].to_numpy()
    out = np.full((len(ed.dias), len(prazos)), np.nan)
    for i in range(len(ed.dias)):
        ok = ~np.isnan(X[i]) & (T[i] > .08)
        if ok.sum() >= 3:
            o = np.argsort(T[i][ok])
            out[i] = np.interp(prazos, T[i][ok][o], X[i][ok][o])
    for j, p in enumerate(prazos):
        vert[f"{cls}_{p:g}a"] = out[:, j]
curvas = pd.DataFrame(vert, index=ed.dias)
base = {"dias": ed.dias, "cdi": ed.cdi, "F": ed.F, "TX": ed.TX, "OI": ed.OI, "VENC": ed.VENC, "curvas": curvas,
        "r_dap5": ed.r_dap, "r_di2": ed.r_di, "tk_dap5": ed.tk_dap, "tk_di2": ed.tk_di, "r_dol": ed.r_dol,
        "R": ed.R, "Hdd": ed.Hdd, "Pi": ed.Pi, "P": ed.P, "Dd": ed.Dd, "cad": ed.c, "custo": ed.CUSTO,
        "exc_eb": ed.exc_eb, "PE": ed.PE, "cad_eb": ed.cad_eb, "sprd_eb": ed.sprd_eb, "ptax": ed.ind.ptax, "fm": ed.fm,
        "credito_ml": ed.b}
pd.to_pickle(base, ed.S / "base_diaria.pkl")
print("salvo", ed.S / "base_diaria.pkl", curvas.dropna().index.min(), curvas.index.max())
