"""
DIAGNOSTICO DO PAINEL - arquivo separado, so confere (nao muda nada no painel).

Uso: salve na MESMA pasta do painel.py, rode o painel.py pelo menos uma vez no dia e depois:
    python diagnostico.py
Le o painel ja processado (dados_painel/painel/<data>/) e gera diagnostico.xlsx + resumo no terminal.

Confere, por fundo:
  1. carteira: soma do % PL ~ 100% em todo mes; parte confidencial
  2. spread/duration: cobertura (buracos), fontes (% do PL), parte estimada, valores fora do plausivel
  3. categorias: o que ficou fora das categorias da casa
  4. retorno: categorias somam o retorno real da cota; residuo e hedge por mes
  5. modelo de spread pelo preco (SND) contra a ANBIMA no ultimo dia disponivel
  6. cota diaria com saltos (> 2% num dia): amortizacao/distribuicao/marcacao irregular -> % do CDI pouco comparavel
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import painel as p                                   # usa as mesmas funcoes do painel (nao roda o painel)

CASA = {"Caixa", "LF", "LFSN", "LFSC", "DEB", "DEBIN", "Bonds", "CRA", "CRI", "NC", "FIDC"}
SEM_SPREAD = set(p.SEM_SPREAD)
LIM = {"soma_pl": 1.0, "estimado": 10.0, "resid_mes": 1.0, "resid_12m": 2.0, "fecho": 0.01}


def pasta():
    ps = sorted(d for d in (p.CACHE / "painel").glob("*") if (d / "visao.json").exists())
    if not ps:
        sys.exit(f"Nenhum painel processado em {p.CACHE / 'painel'}. Rode o painel.py primeiro.")
    return ps[-1]


def fundo(f, d, alertas, datas):
    a = lambda nivel, texto: alertas.append({"fundo": f["nome"], "nivel": nivel, "alerta": texto})
    r = {"fundo": f["nome"], "nosso": f["nosso"]}
    q = pd.Series(f["cota"], index=datas, dtype=float).dropna() if f["cota"] else pd.Series(dtype=float)
    if q.empty:
        a("info", "sem cota diária na CVM para este CNPJ (sem retorno)")
    saltos = q.pct_change()[lambda x: (x.abs() > 0.02) & (x.index >= q.index.max() - pd.DateOffset(months=24))] if len(q) else q
    r["saltos_cota"] = len(saltos)
    if len(saltos):
        ex = ", ".join(f"{t:%d/%m/%y} {v:+.1%}" for t, v in saltos.tail(3).items())
        a("aviso", f"cota com {len(saltos)} salto(s) > 2% num dia nos últimos 24 meses (ex.: {ex}): amortização/distribuição ou marcação irregular — % do CDI pouco comparável")
    if not f["tem_carteira"]:
        a("info", "sem carteira na CVM para este CNPJ (só cota/retorno)")
        return r, []
    D = json.loads((d / f"{f['id']}.json").read_text(encoding="utf-8"))
    C = D["carteira"]
    abertos = [x for x in C if x["conf"] < 5] or C
    U = abertos[-1]
    # 1) carteira
    for x in C:
        soma = sum(c["perc"] for c in x["cats"])
        if abs(soma - 100) > LIM["soma_pl"]:
            a("erro", f"{x['mes']}: % PL soma {soma:.2f}%")
    r.update(meses=len(C), ultimo=C[-1]["mes"], ultimo_aberto=U["mes"], conf_ultimo=round(C[-1]["conf"], 1),
             pl_mm=round(U["pl_mm"] or 0, 1), spread=U["total"]["spread"], duration=U["total"]["duration"])
    # 2) spread / duration
    buracos = [(x["mes"], c["categoria"]) for x in C for c in x["cats"]
               if c["perc"] > 0.05 and c["categoria"] not in SEM_SPREAD and (c["spread"] is None or c["duration"] is None)]
    for m, c in buracos:                            # no 1o mes do fundo nao ha mes anterior para estimar
        a("aviso" if m == C[0]["mes"] else "erro", f"{m}: categoria {c} sem spread/duration")
    fo = U["fontes"]
    est = sum(v for k, v in fo.items() if k.startswith("estimado"))
    mercado = sum(v for k, v in fo.items() if k in ("ANBIMA", "SND + preço do fundo"))
    if est > LIM["estimado"]:
        a("aviso", f"{U['mes']}: {est:.1f}% do PL com spread estimado (média)")
    r.update(buracos=len(buracos), estimado=round(est, 1), mercado=round(mercado, 1))
    at = pd.read_parquet(d / f"{f['id']}_ativos.parquet")
    au = at[at.mes == U["mes"]]
    fidc_ruim = au.fonte.fillna("").str.startswith("FIDC") & (au.spread < -5)          # retorno oficial abaixo do CDI: real
    for x in au[fidc_ruim].itertuples():
        a("info", f"{U['mes']}: FIDC {x.rotulo} rendendo abaixo do CDI (spread {x.spread:.1f}% pela rentabilidade oficial da série)")
    fora = au[~fidc_ruim & ((au.spread < -5) | (au.spread > 30) | (au.duration < 0) | (au.duration > 30))]
    for x in fora.itertuples():
        a("aviso", f"{U['mes']}: {x.rotulo} spread {x.spread:.2f} / duration {x.duration:.2f} ({x.fonte})")
    if r["spread"] is not None and not -1 <= r["spread"] <= 10:
        a("aviso", f"{U['mes']}: spread total {r['spread']:.2f} fora de -1..10")
    if r["duration"] is not None and not 0 <= r["duration"] <= 10:
        a("aviso", f"{U['mes']}: duration total {r['duration']:.2f} fora de 0..10")
    # 3) categorias fora das da casa
    cats = [{"fundo": f["nome"], "categoria": c["categoria"], "perc": round(c["perc"], 2)} for c in U["cats"]
            if c["categoria"] not in CASA and c["perc"] > 0.05]
    # 4) retorno: categorias somam o retorno real? residuo e hedge
    R = D["retorno"]
    meses = R["meses"]
    if meses:
        n = len(meses)
        soma = np.zeros(n)
        for v in R["categorias"].values():
            soma += np.array([c or 0 for c in v["contrib"]])
        real = np.array([m["real"] for m in meses])
        fecho = np.abs(soma - real).max()
        if fecho > LIM["fecho"]:
            a("erro", f"categorias não fecham com o retorno da cota (diferença máx {fecho:.3f} pp)")
        ult = meses[-12:]
        res12 = sum(m["resid"] for m in ult)
        for m in ult:
            if abs(m["resid"]) > LIM["resid_mes"]:
                a("aviso", f"{m['mes']}: resíduo {m['resid']:+.2f} pp (real {m['real']:.2f}%, hedge {m['hedge']:+.2f} pp)")
        if abs(res12) > LIM["resid_12m"]:
            a("aviso", f"resíduo de 12 meses {res12:+.2f} pp (inclui taxas de administração/performance, swaps e perdas não marcadas a mercado)")
        ret12 = np.prod([1 + m["real"] / 100 for m in ult]) - 1
        cdi12 = np.prod([1 + m["cdi"] / 100 for m in ult]) - 1
        r.update(ret_12m=round(ret12 * 100, 2), pct_cdi=round(ret12 / cdi12 * 100, 1) if cdi12 else None,
                 hedge_12m=round(sum(m["hedge"] for m in ult), 2), resid_12m=round(res12, 2), fecho=round(fecho, 4))
    return r, cats


def valida_modelo():
    """Taxa pelo preco (SND + PU par) x taxa indicativa ANBIMA, no ultimo dia ANBIMA guardado."""
    fs = sorted(p.CACHE.glob("anbima_db*.txt"))
    if not fs:
        return pd.DataFrame()
    an = p._le_anbima(fs[-1]).drop_duplicates("codigo").set_index("codigo")
    dia = an.data.iloc[0]
    car = p.snd_caracteristicas()
    pu = p.snd_pu([dia], log=lambda *_: None)
    if not len(car) or not len(pu):
        return pd.DataFrame()
    x = an.drop(columns=["venc", "indice"], errors="ignore").join(car, how="inner").join(pu.set_index("codigo").pu_par, how="inner")
    x = x[x.tipo.isin(["DI +", "IPCA +"]) & (x.pu > 0)]
    di = x.tipo.eq("DI +").values
    ix = p.ipca_indice()
    infl = float((ix.iloc[-1] / ix.iloc[-13]) ** (1 / 12) - 1)
    cdi = float(((1 + p.sgs(12, dia.strftime("%Y-%m")).iloc[-1] / 100) ** 252 - 1) * 100)
    T = ((x.venc - dia).dt.days / 365.25).values
    car_ = ((x.carencia - dia).dt.days / 365.25).values
    s, d = p.taxa_e_duration(T, x.cada_juros.values / 12, np.nan_to_num(x.cada_amort.values) / 12, car_, np.where(di, cdi, 0),
                             x.juros.values, x.pu.values / (x.pu_par.values * np.where(di, 1, 1 + infl)))
    x = x.assign(erro_taxa=s - x.taxa_ind, erro_dur=d - x.duration_anos)
    return (x.groupby("tipo").agg(n=("erro_taxa", "size"), erro_taxa_mediano=("erro_taxa", lambda v: v.abs().median()),
                                  erro_taxa_p90=("erro_taxa", lambda v: v.abs().quantile(.9)),
                                  erro_dur_mediano=("erro_dur", lambda v: v.abs().median())).round(3)
            .reset_index().assign(dia=dia.date()))


def main():
    d = pasta()
    V = json.loads((d / "visao.json").read_text(encoding="utf-8"))
    print(f"Painel: {d}  ({len(V['fundos'])} fundos, gerado {V['gerado']}, carteiras até {V['ult_carteira']}, ANBIMA {V['anbima']})\n")
    alertas, linhas, cats = [], [], []
    for f in V["fundos"]:
        try:
            r, c = fundo(f, d, alertas, pd.to_datetime(V["datas"]))
        except Exception as e:                   # o diagnostico nunca para no meio
            r, c = {"fundo": f["nome"]}, []
            alertas.append({"fundo": f["nome"], "nivel": "erro", "alerta": f"falha ao ler: {type(e).__name__}: {e}"})
        linhas.append(r)
        cats += c
    res = pd.DataFrame(linhas)
    al = pd.DataFrame(alertas, columns=["fundo", "nivel", "alerta"])
    print("Validando o modelo de spread pelo preço contra a ANBIMA...")
    try:
        mod = valida_modelo()
    except Exception as e:
        mod = pd.DataFrame([{"erro": f"{type(e).__name__}: {e}"}])
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    cols = [c for c in ["fundo", "ultimo_aberto", "meses", "spread", "duration", "mercado", "estimado", "buracos", "ret_12m",
                        "pct_cdi", "hedge_12m", "resid_12m", "saltos_cota"] if c in res.columns]
    print("\n== Resumo (último mês aberto; retorno/resíduo em 12 meses) ==")
    print(res[cols].round(2).to_string(index=False))
    print("\n== Modelo de spread pelo preço x ANBIMA ==")
    print(mod.to_string(index=False) if len(mod) else "sem arquivo ANBIMA guardado")
    n = al.nivel.value_counts()
    print(f"\n== Alertas: {n.get('erro', 0)} erros, {n.get('aviso', 0)} avisos, {n.get('info', 0)} info ==")
    for x in al[al.nivel == "erro"].itertuples():
        print(f"  ERRO  {x.fundo}: {x.alerta}")
    if (al.nivel == "aviso").any():
        print("  (avisos na aba 'alertas' do Excel)")
    out = Path(__file__).resolve().parent / "diagnostico.xlsx"
    with pd.ExcelWriter(out) as w:
        res.to_excel(w, sheet_name="resumo", index=False)
        al.to_excel(w, sheet_name="alertas", index=False)
        pd.DataFrame(cats).to_excel(w, sheet_name="categorias_fora_da_casa", index=False)
        mod.to_excel(w, sheet_name="modelo_x_anbima", index=False)
    print(f"\nExcel: {out}")


if __name__ == "__main__":
    main()
