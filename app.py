"""
Painel de fundos com dados abertos da CVM.   Rodar:  streamlit run app.py
Escolha qualquer fundo (nome ou CNPJ) na barra lateral. Fonte: dados.cvm.gov.br (CDA, INF_DIARIO, cadastro)
e Banco Central (CDI). Tudo publico e gratuito; a 1a carga de um fundo novo baixa/recorta os arquivos da CVM.
"""
import io
import os
import zipfile

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

import lookthrough_cvm as lt

st.set_page_config(page_title="Painel de fundos CVM", page_icon="📊", layout="wide")
CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
CINZA, CDI_COR = "#898781", "#52514e"
DIVERG = [[0, "#eb6834"], [0.5, "#f0efec"], [1, "#2a78d6"]]           # %CDI: abaixo de 100 laranja, acima azul
CONTABIL = r"(?i)pagar|receber|obriga|termo|disponibilidade|exigibilidade|swap|confidencial|ajuste"
pct = lambda x, d=2: "" if pd.isna(x) else f"{x:.{d}f}%"


@st.cache_data(ttl=86400, show_spinner="Carregando cadastro de fundos da CVM...")
def cadastro():
    """Todos os fundos/classes (antigos e pos-RCVM 175) para a busca por nome ou CNPJ."""
    r = requests.get("https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip", timeout=300)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    c = pd.read_csv(z.open("registro_classe.csv"), sep=";", encoding="latin1", dtype=str, quoting=3,
                    usecols=["CNPJ_Classe", "Denominacao_Social", "Situacao"])
    c.columns = ["cnpj", "nome", "situacao"]
    a = pd.read_csv("https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv", sep=";", encoding="latin1", dtype=str,
                    quoting=3, usecols=["CNPJ_FUNDO", "DENOM_SOCIAL", "SIT"])
    a.columns = ["cnpj", "nome", "situacao"]
    c = pd.concat([c, a]).dropna(subset=["cnpj", "nome"])
    c["cnpj"] = c.cnpj.map(lt.fmt)
    c["ativo"] = ~c.situacao.fillna("").str.upper().str.contains("CANCEL")
    return c.sort_values("ativo", ascending=False).drop_duplicates("cnpj")


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def carrega(fundos, desde):
    """fundos: tupla (nome curto, cnpj). Baixa/recorta CVM so o que falta e monta tudo que o painel usa."""
    log = []
    workers = 1 if (os.cpu_count() or 1) <= 2 else min(4, os.cpu_count())
    meses, dia = lt.prepara(sorted(c for _, c in fundos), desde, workers=workers, log=log.append)
    nomes = dict(fundos)
    df = lt.lookthrough(nomes, meses) if meses else pd.DataFrame()
    d = lt.diario(nomes, dia)
    cdi = lt.cdi_mensal(desde, diario=True)
    return df, d, cdi, log


def curto(nome):
    n = nome.upper()
    for a, b in [("FUNDO DE INVESTIMENTO FINANCEIRO", "FIF"), ("FUNDO DE INVESTIMENTO EM COTAS DE FUNDOS DE INVESTIMENTO", "FIC FI"),
                 ("FUNDO DE INVESTIMENTO", "FI"), ("MULTIMERCADO", "MM"), ("CRÉDITO PRIVADO", "CP"), ("RENDA FIXA", "RF"),
                 ("RESPONSABILIDADE LIMITADA", "RL"), ("LONGO PRAZO", "LP")]:
        n = n.replace(a, b)
    return n[:34].strip()


def fig_style(fig, h=380):
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=40, b=10), legend_title_text="", hovermode="x unified",
                      font=dict(family="Arial", size=12))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(137,135,129,0.25)", zeroline=False)
    return fig


def mostra(fig, h=380):
    st.plotly_chart(fig_style(fig, h), use_container_width=True, theme="streamlit")


# ------------------------------------------------------------------ barra lateral
cad = cadastro()
rotulo = (cad.nome.str.slice(0, 70) + "  ·  " + cad.cnpj + np.where(cad.ativo, "", "  (cancelado)")).tolist()
por_rotulo = dict(zip(rotulo, cad.cnpj))
padrao = [r for r in rotulo if por_rotulo[r] in {lt.cnpj_of(x) for x in lt.PEERS.values()}]
st.sidebar.title("📊 Fundos (CVM)")
with st.sidebar.form("escolha"):
    escolhidos = st.multiselect("Fundos (digite nome ou CNPJ)", rotulo, default=padrao, max_selections=8)
    hoje = pd.Timestamp.today()
    opcoes = [f"{a}-01" for a in range(hoje.year, 2004, -1)]
    desde = st.selectbox("Carteiras desde", opcoes, index=min(2, len(opcoes) - 1),
                         help="Quanto mais antigo, mais arquivos da CVM na 1a carga (depois fica em cache).")
    st.form_submit_button("Carregar", type="primary", use_container_width=True)
st.sidebar.caption("Fonte: dados abertos da CVM (CDA mensal, informe diário, cadastro) e Banco Central (CDI). "
                   "Carteiras: look-through (cotas de fundos abertas até o ativo final).")
if not escolhidos:
    st.info("Escolha ao menos um fundo na barra lateral.")
    st.stop()

peer_nome = {lt.cnpj_of(x): n for n, x in lt.PEERS.items()}
fundos = tuple((peer_nome.get(por_rotulo[r]) or curto(r.split("  ·  ")[0]), por_rotulo[r]) for r in escolhidos)
ordem = [n for n, _ in fundos]
COR_F = {n: CORES[i % len(CORES)] for i, n in enumerate(ordem)}
with st.status("Buscando dados na CVM (1ª carga de um fundo/período pode levar alguns minutos)...", expanded=False) as s:
    df, d, cdi, log = carrega(fundos, desde)
    for l in log[-8:]:
        st.write(l)
    s.update(label=f"Dados carregados: {len(df):,} linhas de carteira, {len(d):,} dias de cota", state="complete")
if d.empty and df.empty:
    st.error("A CVM não tem dados desses fundos no período escolhido.")
    st.stop()

# ------------------------------------------------------------------ bases derivadas
cart = df[~df.derivativo] if not df.empty else df
ult_mes = cart.groupby("fundo").mes.max() if not cart.empty else pd.Series(dtype=str)
ult = cart[cart.mes == cart.fundo.map(ult_mes)] if not cart.empty else cart
cat_media = (cart[~cart.categoria.str.contains(CONTABIL)].groupby(["fundo", "mes", "categoria"]).perc_pl.sum()
             .groupby("categoria").mean().sort_values(ascending=False)) if not cart.empty else pd.Series(dtype=float)
TOP_CAT = cat_media.index[:7].tolist()
COR_C = {c: CORES[i] for i, c in enumerate(TOP_CAT)} | {"Outros": CINZA}
cat7 = lambda s: s.where(s.isin(TOP_CAT), "Outros")


def kpis():
    linhas = []
    for f in ordem:
        q = d[d.fundo == f].set_index("data").VL_QUOTA.dropna()
        if q.empty:
            continue
        fim = q.index[-1]
        ini = q[q.index <= fim - pd.Timedelta(days=365)]
        base = ini.index[-1] if len(ini) else q.index[0]
        r12 = q.iloc[-1] / q[base] - 1
        c12 = (1 + cdi[(cdi.index > base) & (cdi.index <= fim)]).prod() - 1
        ano = q[q.index < pd.Timestamp(fim.year, 1, 1)]
        rano = q.iloc[-1] / ano.iloc[-1] - 1 if len(ano) else np.nan
        dd = (q / q.cummax() - 1).min()
        x = d[(d.fundo == f) & (d.data > base)]
        u = ult[ult.fundo == f]
        emis = u.groupby("emissor").perc_pl.sum().nlargest(10).sum() if len(u) else np.nan
        linhas.append({"Fundo": f, "PL (R$ mi)": d[d.fundo == f].VL_PATRIM_LIQ.iloc[-1] / 1e6, "Retorno 12m": r12 * 100,
                       "%CDI 12m": r12 / c12 * 100 if c12 else np.nan, "Retorno no ano": rano * 100,
                       "Vol. anual": q[q.index > base].pct_change().std() * np.sqrt(252) * 100,
                       "Pior drawdown": dd * 100, "Captação líq. 12m (R$ mi)": (x.CAPTC_DIA.sum() - x.RESG_DIA.sum()) / 1e6,
                       "Cotistas": x.NR_COTST.iloc[-1] if len(x) else np.nan,
                       "Ativos na carteira": u.chave.nunique() if len(u) else np.nan, "Top 10 emissores (%PL)": emis,
                       "Última carteira": ult_mes.get(f, ""), "Última cota": fim.date()})
    return pd.DataFrame(linhas)


abas = st.tabs(["Visão geral", "Rentabilidade", "PL & captação", "Alocação", "Crédito", "Movimentações",
                "Derivativos & moeda", "Marcação (estimada)", "Comparação", "Dados"])

# ------------------------------------------------------------------ 1. visao geral
with abas[0]:
    st.subheader("Resumo")
    k = kpis()
    st.dataframe(k.style.format({c: "{:,.2f}" for c in k.columns if k[c].dtype.kind == "f"} | {"Cotistas": "{:,.0f}"}),
                 hide_index=True, use_container_width=True)
    if not d.empty:
        fig = go.Figure()
        for f in ordem:
            q = d[d.fundo == f].set_index("data").VL_QUOTA.dropna()
            if len(q):
                fig.add_scatter(x=q.index, y=(q / q.iloc[0] - 1) * 100, name=f, line=dict(color=COR_F[f], width=2))
        c = cdi[cdi.index >= d.data.min()]
        fig.add_scatter(x=c.index, y=((1 + c).cumprod() - 1) * 100, name="CDI", line=dict(color=CDI_COR, width=2, dash="dash"))
        fig.update_layout(title="Retorno acumulado no período (%)")
        mostra(fig, 420)

# ------------------------------------------------------------------ 2. rentabilidade
with abas[1]:
    rent = lt.rentabilidade(d, (1 + cdi).groupby(cdi.index.strftime("%Y-%m")).prod() - 1) if not d.empty else pd.DataFrame()
    if not rent.empty:
        hm = rent.pivot(index="fundo", columns="mes", values="pct_cdi").reindex(ordem) * 100
        fig = px.imshow(hm, color_continuous_scale=DIVERG, color_continuous_midpoint=100, zmin=0, zmax=200, aspect="auto",
                        labels=dict(color="%CDI"), title="%CDI mês a mês (azul: acima do CDI; laranja: abaixo)")
        fig.update_traces(hovertemplate="%{y}<br>%{x}: %{z:.0f}% do CDI<extra></extra>")
        mostra(fig, 120 + 40 * len(ordem))
        fig = px.bar(rent.dropna(subset=["retorno"]), x="mes", y=rent.dropna(subset=["retorno"]).retorno * 100,
                     color="fundo", barmode="group", color_discrete_map=COR_F, category_orders={"fundo": ordem},
                     labels={"y": "retorno no mês (%)", "mes": ""}, title="Retorno mensal (%)")
        mostra(fig)
        fig = go.Figure()
        for f in ordem:
            q = d[d.fundo == f].set_index("data").VL_QUOTA.dropna()
            fig.add_scatter(x=q.index, y=(q / q.cummax() - 1) * 100, name=f, line=dict(color=COR_F[f], width=2))
        fig.update_layout(title="Drawdown (% abaixo do pico anterior)")
        mostra(fig)

# ------------------------------------------------------------------ 3. PL & captacao
with abas[2]:
    if not d.empty:
        fig = px.line(d, x="data", y=d.VL_PATRIM_LIQ / 1e6, color="fundo", color_discrete_map=COR_F,
                      category_orders={"fundo": ordem}, labels={"y": "R$ milhões", "data": ""}, title="Patrimônio líquido (R$ mi)")
        mostra(fig)
        cap = d.groupby(["fundo", "mes"]).apply(lambda x: (x.CAPTC_DIA.sum() - x.RESG_DIA.sum()) / 1e6, include_groups=False)
        cap = cap.rename("liq").reset_index()
        fig = px.bar(cap, x="mes", y="liq", color="fundo", barmode="group", color_discrete_map=COR_F,
                     category_orders={"fundo": ordem}, labels={"liq": "R$ milhões", "mes": ""},
                     title="Captação líquida mensal (aplicações - resgates, R$ mi)")
        mostra(fig)
        fig = px.line(d, x="data", y="NR_COTST", color="fundo", color_discrete_map=COR_F, category_orders={"fundo": ordem},
                      labels={"NR_COTST": "cotistas", "data": ""}, title="Número de cotistas")
        mostra(fig)

# ------------------------------------------------------------------ helpers por fundo (abas 4-8)
def escolhe(chave):
    disp = [f for f in ordem if f in set(cart.fundo)] if not cart.empty else []
    return st.radio("Fundo", disp, horizontal=True, key=chave) if disp else None


def prazo_anos(x):
    v = pd.to_datetime(x.vencimento, errors="coerce")
    return (v - (pd.to_datetime(x.mes) + pd.offsets.MonthEnd(0))).dt.days / 365.25

# ------------------------------------------------------------------ 4. alocacao
with abas[3]:
    f = escolhe("aloc")
    if f:
        g = cart[cart.fundo == f]
        ev = g.assign(c=cat7(g.categoria)).groupby(["mes", "c"]).perc_pl.sum().reset_index()
        fig = px.area(ev, x="mes", y="perc_pl", color="c", color_discrete_map=COR_C, category_orders={"c": TOP_CAT + ["Outros"]},
                      labels={"perc_pl": "% do PL", "mes": "", "c": ""}, title=f"{f}: % do PL por categoria (look-through)")
        mostra(fig, 420)
        c1, c2 = st.columns(2)
        with c1:
            u = ult[ult.fundo == f]
            em = u.groupby("emissor").perc_pl.sum().nlargest(15).sort_values()
            fig = px.bar(x=em.values, y=em.index, orientation="h", labels={"x": "% do PL", "y": ""},
                         title=f"Maiores emissores ({ult_mes[f]})", color_discrete_sequence=[CORES[0]])
            mostra(fig, 460)
        with c2:
            cm = ult.assign(c=cat7(ult.categoria)).groupby(["fundo", "c"]).perc_pl.sum().reset_index()
            fig = px.bar(cm, x="perc_pl", y="fundo", color="c", orientation="h", color_discrete_map=COR_C,
                         category_orders={"c": TOP_CAT + ["Outros"], "fundo": ordem},
                         labels={"perc_pl": "% do PL", "fundo": "", "c": ""}, title="Alocação atual: todos os fundos")
            mostra(fig, 460)
        st.markdown(f"**Carteira de {ult_mes[f]}** (look-through)")
        tab = (u.groupby(["categoria", "ativo", "codigo", "emissor"], dropna=False)
               .agg(perc_pl=("perc_pl", "sum"), veiculo=("veiculo", "first")).reset_index().sort_values("perc_pl", ascending=False))
        st.dataframe(tab.style.format({"perc_pl": "{:.3f}%"}), hide_index=True, use_container_width=True, height=420)

# ------------------------------------------------------------------ 5. credito
@st.cache_data(ttl=6 * 3600, show_spinner="Buscando marcação ANBIMA de debêntures...")
def anbima():
    return lt.anbima_debentures()


def wavg(x, col, w="perc_pl"):
    ok = x[col].notna() & x[w].gt(0)
    return np.average(x.loc[ok, col], weights=x.loc[ok, w]) if ok.any() else np.nan


def marca_deb(f, an):
    """Debentures da ultima carteira aberta do fundo + marcacao ANBIMA (taxa indicativa, duration)."""
    ma = lt.mes_aberto(cart).get(f)
    u = cart[(cart.fundo == f) & (cart.mes == ma) & cart.categoria.eq("Debêntures")]
    cols = ["codigo", "indice", "tipo", "taxa_ind", "duration_anos", "pu", "pct_par", "venc"]
    return ma, u.merge(an[cols], on="codigo", how="left") if len(an) else u.assign(**{c: np.nan for c in cols[1:]})


with abas[4]:
    f = escolhe("cred")
    if f:
        an_u, an_h = anbima()
        ma, deb = marca_deb(f, an_u)
        st.caption(f"Usando a carteira de **{ma}**: o mês mais recente em que a parte confidencial é menor que 5% do PL "
                   "(meses recentes podem ter ativos omitidos por até 6 meses).")
        if len(an_u):
            dt = an_u.data.iloc[0].date()
            com = deb[deb.taxa_ind.notna()]
            st.markdown(f"#### Debêntures com marcação ANBIMA de {dt:%d/%m/%Y}")
            k = st.columns(5)
            k[0].metric("Debêntures", pct(deb.perc_pl.sum(), 1) + " do PL")
            k[1].metric("Com taxa ANBIMA", pct(com.perc_pl.sum() / deb.perc_pl.sum() * 100 if deb.perc_pl.sum() else np.nan, 0)
                        + " das debêntures")
            for col, tipo, rot in [(k[2], "DI +", "Spread médio (DI +)"), (k[3], "IPCA +", "Taxa média (IPCA +)")]:
                x = com[com.tipo == tipo]
                col.metric(rot, pct(wavg(x, "taxa_ind")) + " a.a.", f"{x.perc_pl.sum():.1f}% do PL", delta_color="off")
            k[4].metric("Duration média", f"{wavg(com, 'duration_anos'):.2f} anos")
            c1, c2 = st.columns([1, 2])
            tp = deb.assign(t=deb.tipo.fillna("sem taxa ANBIMA")).groupby("t").perc_pl.sum().sort_values()
            c1.plotly_chart(fig_style(px.bar(x=tp.values, y=tp.index, orientation="h", labels={"x": "% do PL", "y": ""},
                                             title="Debêntures por indexador", color_discrete_sequence=[CORES[0]]), 360),
                            use_container_width=True)
            sc = com[com.tipo.isin(["DI +", "IPCA +"])]
            fig = px.scatter(sc, x="duration_anos", y="taxa_ind", size="perc_pl", color="tipo", hover_name="ativo",
                             color_discrete_map={"DI +": CORES[0], "IPCA +": CORES[1]}, size_max=30,
                             labels={"duration_anos": "duration (anos)", "taxa_ind": "taxa indicativa (% a.a.)", "tipo": ""},
                             title="Taxa x duration por debênture (tamanho = % do PL)")
            c2.plotly_chart(fig_style(fig, 360), use_container_width=True)
            if an_h.data.nunique() > 1:
                ev = deb[["codigo", "perc_pl"]].merge(an_h[["data", "codigo", "tipo", "taxa_ind", "duration_anos"]], on="codigo")
                s1 = ev[ev.tipo == "DI +"].groupby("data").apply(lambda x: wavg(x, "taxa_ind"), include_groups=False)
                s2 = ev.groupby("data").apply(lambda x: wavg(x, "duration_anos"), include_groups=False)
                c1, c2 = st.columns(2)
                c1.plotly_chart(fig_style(px.line(x=s1.index, y=s1.values, labels={"x": "", "y": "% a.a."}, markers=True,
                                                  title="Spread médio DI + (mesma carteira, marcação de cada dia)",
                                                  color_discrete_sequence=[CORES[0]]), 300), use_container_width=True)
                c2.plotly_chart(fig_style(px.line(x=s2.index, y=s2.values, labels={"x": "", "y": "anos"}, markers=True,
                                                  title="Duration média das debêntures", color_discrete_sequence=[CORES[2]]), 300),
                                use_container_width=True)
                st.caption(f"Histórico ANBIMA guardado localmente: {an_h.data.nunique()} dias (o site gratuito mantém ~15 dias úteis; "
                           "cada uso do painel salva os novos, então o histórico cresce com o tempo).")
            st.dataframe(deb.sort_values("perc_pl", ascending=False)[["ativo", "codigo", "perc_pl", "indice", "taxa_ind",
                                                                       "duration_anos", "pct_par", "venc", "veiculo"]]
                         .style.format({"perc_pl": "{:.3f}%", "taxa_ind": "{:.2f}", "duration_anos": "{:.2f}", "pct_par": "{:.2f}"},
                                       na_rep="-"), hide_index=True, use_container_width=True, height=360)
        st.markdown("#### Demais títulos (informado pela própria CVM)")
        st.caption("Indexador, % do índice, cupom, taxa e rating vêm na CDA para depósitos bancários e títulos de crédito "
                   "privado (blocos 5 e 6); prazo vem do vencimento quando informado.")
        u = cart[(cart.fundo == f) & (cart.mes == ma) & ~cart.categoria.str.contains(CONTABIL)].copy()
        u["prazo"] = prazo_anos(u)
        u["idx"] = u.indexador.fillna("não informado na CDA")
        c1, c2, c3 = st.columns(3)
        ix = u.groupby("idx").perc_pl.sum().sort_values()
        c1.plotly_chart(fig_style(px.bar(x=ix.values, y=ix.index, orientation="h", labels={"x": "% do PL", "y": ""},
                                         title="Indexador (CDA)", color_discrete_sequence=[CORES[0]]), 340), use_container_width=True)
        faixa = pd.cut(u.prazo, [-1, 1, 2, 3, 5, 100], labels=["até 1a", "1-2a", "2-3a", "3-5a", "5a+"]).astype(str).replace("nan", "s/ venc.")
        pz = u.groupby(faixa).perc_pl.sum().reindex(["até 1a", "1-2a", "2-3a", "3-5a", "5a+", "s/ venc."]).fillna(0)
        c2.plotly_chart(fig_style(px.bar(x=pz.index, y=pz.values, labels={"x": "", "y": "% do PL"}, title="Prazo até o vencimento",
                                         color_discrete_sequence=[CORES[2]]), 340), use_container_width=True)
        rt = u.groupby(u.rating.fillna("sem rating")).perc_pl.sum().sort_values()
        c3.plotly_chart(fig_style(px.bar(x=rt.values, y=rt.index, orientation="h", labels={"x": "% do PL", "y": ""},
                                         title="Rating", color_discrete_sequence=[CORES[6]]), 340), use_container_width=True)
        resumo = u.groupby("categoria").apply(lambda x: pd.Series({
            "% PL": x.perc_pl.sum(), "% PL c/ taxa informada": x[x.pct_indexador.notna() | x.cupom.notna() | x.taxa_pre.notna()].perc_pl.sum(),
            "% do índice (média)": wavg(x, "pct_indexador"), "cupom/spread (média)": wavg(x, "cupom"),
            "taxa pré (média)": wavg(x, "taxa_pre"), "prazo médio (anos)": wavg(x, "prazo")}), include_groups=False)
        st.dataframe(resumo.sort_values("% PL", ascending=False).style.format("{:.2f}", na_rep="-"), use_container_width=True)

# ------------------------------------------------------------------ 6. movimentacoes
with abas[5]:
    f = escolhe("mov")
    if f:
        g = cart[cart.fundo == f]
        ms = sorted(g.mes.unique())
        aberto = lt.mes_aberto(cart).get(f)
        m = st.select_slider("Mês", ms, value=aberto if aberto in ms else ms[-1], key="mes_mov",
                             help="Começa no mês mais recente com carteira aberta (meses recentes podem ter ativos confidenciais)")
        x = g[g.mes == m].groupby(["ativo", "categoria"]).agg(compra=("compra_pct", "sum"), venda=("venda_pct", "sum")).reset_index()
        c1, c2 = st.columns(2)
        for col, lado, cor, tit in [(c1, "compra", CORES[0], "Maiores compras"), (c2, "venda", CORES[1], "Maiores vendas")]:
            t = x.nlargest(15, lado).sort_values(lado)
            col.plotly_chart(fig_style(px.bar(t, x=lado, y="ativo", orientation="h", hover_data=["categoria"],
                                              labels={lado: "% do PL do fundo", "ativo": ""}, title=f"{tit} em {m}",
                                              color_discrete_sequence=[cor]), 480), use_container_width=True)
        i = ms.index(m)
        if i:
            a, b = set(g[g.mes == ms[i - 1]].chave), set(g[g.mes == m].chave)
            novos, saidas = g[(g.mes == m) & g.chave.isin(b - a)], g[(g.mes == ms[i - 1]) & g.chave.isin(a - b)]
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Posições novas", len(b - a))
            k2.metric("% PL em posições novas", pct(novos.perc_pl.sum()))
            k3.metric("Posições zeradas", len(a - b))
            k4.metric("% PL que saiu", pct(saidas.perc_pl.sum()))
        giro = g.groupby("mes").agg(c=("compra_pct", "sum"), v=("venda_pct", "sum"))
        fig = go.Figure([go.Bar(x=giro.index, y=giro.c, name="compras", marker_color=CORES[0]),
                         go.Bar(x=giro.index, y=-giro.v, name="vendas", marker_color=CORES[1])])
        fig.update_layout(barmode="relative", title="Compras e vendas do mês (% do PL, look-through)")
        mostra(fig)

# ------------------------------------------------------------------ 7. derivativos & moeda
with abas[6]:
    f = escolhe("der")
    if f:
        dv = df[(df.fundo == f) & df.derivativo]
        st.caption("Derivativos aparecem pelo valor que o fundo informa à CVM (em geral o nocional), em % do PL; "
                   "por isso ficam fora da soma de 100% e dos gráficos de alocação.")
        if dv.empty:
            st.info("Sem derivativos na carteira no período.")
        else:
            t = dv.groupby(["mes", "tipo_ativo"]).perc_pl.sum().reset_index()
            mostra(px.bar(t, x="mes", y="perc_pl", color="tipo_ativo", color_discrete_sequence=CORES,
                          labels={"perc_pl": "% do PL", "mes": "", "tipo_ativo": ""},
                          title="Derivativos por tipo de contrato (% do PL)"), 420)
            st.dataframe(dv[dv.mes == dv.mes.max()].groupby(["categoria", "tipo_ativo", "ativo", "veiculo"]).perc_pl.sum()
                         .reset_index().sort_values("perc_pl").style.format({"perc_pl": "{:.3f}%"}),
                         hide_index=True, use_container_width=True)
        g = df[df.fundo == f]
        fx = pd.DataFrame({"Investimento no exterior": g[g.categoria.eq("Investimento no Exterior")].groupby("mes").perc_pl.sum(),
                           "Futuros de dólar (nocional)": g[g.derivativo & g.tipo_ativo.fillna("").str.contains("(?i)dol|dólar")]
                           .groupby("mes").perc_pl.sum()}).fillna(0)
        mostra(px.line(fx, labels={"value": "% do PL", "mes": "", "variable": ""}, color_discrete_sequence=[CORES[3], CORES[6]],
                       title="Exposição a moeda estrangeira (% do PL)"), 320)

# ------------------------------------------------------------------ 8. resultado estimado
with abas[7]:
    st.caption("Efeito de marcação estimado com a CDA mensal: quantidade do mês anterior × variação do preço unitário "
               "(valor ÷ quantidade), só para ativos mantidos de um mês para o outro, em % do PL do fundo. Não inclui carrego "
               "de caixa/compromissadas, ganho de negociação nem ativos confidenciais. **Pagamentos de juros/amortização "
               "aparecem como queda de preço** (ex.: meses de cupom semestral): use para ver marcações e eventos de crédito, "
               "não como P&L contábil. A linha mostra o retorno real da cota no mês.")
    f = escolhe("res")
    if f:
        k = lt.contribuicao(cart[cart.fundo == f])
        if k.empty:
            st.info("Precisa de pelo menos dois meses de carteira.")
        else:
            cc = k.assign(c=cat7(k.categoria)).groupby(["mes", "c"]).resultado_pct.sum().reset_index()
            fig = px.bar(cc, x="mes", y="resultado_pct", color="c", color_discrete_map=COR_C,
                         category_orders={"c": TOP_CAT + ["Outros"]}, labels={"resultado_pct": "% do PL", "mes": "", "c": ""},
                         title="Efeito de marcação por categoria (% do PL) e retorno real da cota")
            if not rent.empty:
                rr = rent[(rent.fundo == f) & rent.mes.isin(cc.mes)]
                fig.add_scatter(x=rr.mes, y=rr.retorno * 100, name="retorno real da cota", mode="lines+markers",
                                line=dict(color=CDI_COR, width=2))
            mostra(fig, 420)
            ms = sorted(k.mes.unique())
            aberto = lt.mes_aberto(cart).get(f)
            m = st.select_slider("Mês", ms, value=aberto if aberto in ms else ms[-1], key="mes_res")
            km = k[k.mes == m].groupby(["ativo", "categoria"]).resultado_pct.sum().reset_index()
            c1, c2 = st.columns(2)
            for col, t, cor, tit in [(c1, km.nlargest(12, "resultado_pct"), CORES[0], "Maiores altas de preço"),
                                     (c2, km.nsmallest(12, "resultado_pct"), CORES[1], "Maiores quedas de preço")]:
                col.plotly_chart(fig_style(px.bar(t.sort_values("resultado_pct"), x="resultado_pct", y="ativo", orientation="h",
                                                  hover_data=["categoria"], labels={"resultado_pct": "% do PL", "ativo": ""},
                                                  title=f"{tit} em {m}", color_discrete_sequence=[cor]), 440),
                                 use_container_width=True)
            tot = k.groupby(["ativo", "categoria"]).resultado_pct.sum().reset_index()
            st.markdown("**No período inteiro**")
            c1, c2 = st.columns(2)
            c1.dataframe(tot.nlargest(15, "resultado_pct").style.format({"resultado_pct": "{:.3f}%"}), hide_index=True)
            c2.dataframe(tot.nsmallest(15, "resultado_pct").style.format({"resultado_pct": "{:.3f}%"}), hide_index=True)

# ------------------------------------------------------------------ 9. comparacao
with abas[8]:
    if not ult.empty:
        st.markdown("**Alocação por categoria na última carteira (% do PL)**")
        st.dataframe(ult.pivot_table(index="categoria", columns="fundo", values="perc_pl", aggfunc="sum", fill_value=0)
                     .reindex(columns=[f for f in ordem if f in set(ult.fundo)]).sort_values(ordem[0] if ordem[0] in set(ult.fundo) else ult.fundo.iloc[0], ascending=False)
                     .style.format("{:.2f}"), use_container_width=True)
        e = ult.groupby(["fundo", "emissor"]).perc_pl.sum()
        comum = e.groupby(level=1).filter(lambda s: len(s) > 1).unstack(0).fillna(0)
        if len(comum):
            st.markdown("**Emissores em comum entre os fundos (% do PL)**")
            st.dataframe(comum.assign(soma=comum.sum(axis=1)).sort_values("soma", ascending=False).drop(columns="soma")
                         .head(30).style.format("{:.2f}"), use_container_width=True)
    an_u, _ = anbima()
    linhas = []
    for f in [f for f in ordem if f in set(cart.fundo)] if not cart.empty else []:
        ma, deb = marca_deb(f, an_u)
        com = deb[deb.taxa_ind.notna()] if len(deb) else deb
        linhas.append({"Fundo": f, "Carteira aberta": ma, "Debêntures (%PL)": deb.perc_pl.sum(),
                       "Cobertura ANBIMA (%)": com.perc_pl.sum() / deb.perc_pl.sum() * 100 if deb.perc_pl.sum() else np.nan,
                       "Spread DI + (% a.a.)": wavg(com[com.tipo == "DI +"], "taxa_ind") if len(com) else np.nan,
                       "Taxa IPCA + (% a.a.)": wavg(com[com.tipo == "IPCA +"], "taxa_ind") if len(com) else np.nan,
                       "Duration (anos)": wavg(com, "duration_anos") if len(com) else np.nan})
    if linhas:
        st.markdown("**Crédito: debêntures com marcação ANBIMA (última carteira aberta de cada fundo)**")
        st.dataframe(pd.DataFrame(linhas).style.format({c: "{:.2f}" for c in linhas[0] if c not in ("Fundo", "Carteira aberta")},
                                                      na_rep="-"), hide_index=True, use_container_width=True)
    k = kpis()
    if len(k):
        fig = px.scatter(k, x="Vol. anual", y="%CDI 12m", size="PL (R$ mi)", color="Fundo", color_discrete_map=COR_F,
                         title="Risco x retorno (12 meses): volatilidade anual x %CDI", size_max=50)
        mostra(fig, 420)

# ------------------------------------------------------------------ 10. dados
with abas[9]:
    st.download_button("Baixar carteira look-through (CSV)", df.drop(columns=["chave", "fator"], errors="ignore")
                       .to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"), "carteira_lookthrough.csv")
    st.download_button("Baixar cotas diárias (CSV)", d.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"), "cotas.csv")
    st.dataframe(df.head(2000), use_container_width=True, height=400)
