# Painel de fundos (dados abertos CVM)

Dashboard em Streamlit para analisar **qualquer fundo brasileiro** com dados públicos e gratuitos:

| Fonte | O que entra no painel |
|---|---|
| CVM – CDA (carteira mensal) | Look-through da carteira (abre cotas de fundos até o ativo final), alocação, emissores, compras e vendas do mês, derivativos, exposição externa |
| CVM – Informe diário | Cota, rentabilidade, %CDI, drawdown, volatilidade, PL, captação líquida, cotistas |
| CVM – Cadastro | Busca de fundos por nome ou CNPJ |
| ANBIMA – mercado secundário de debêntures | Taxa indicativa (spread DI+ / IPCA+), PU e duration das debêntures da carteira |
| Banco Central – SGS 12 | CDI diário |

Abas: Visão geral · Rentabilidade · PL & captação · Alocação · Crédito · Movimentações · Derivativos & moeda · Marcação (estimada) · Comparação · Dados.

## Rodar no seu computador
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Publicar de graça (Streamlit Community Cloud)
1. Entre em https://share.streamlit.io com sua conta do GitHub.
2. **Create app → Deploy a public app from GitHub** → repositório deste projeto, branch `main`, arquivo `app.py`.
3. Deploy. A primeira carga de cada fundo/período baixa os arquivos da CVM (alguns minutos); depois fica em cache.

## Também gera Excel
`python lookthrough_cvm.py` → `lookthrough_cvm.xlsx` (gráficos, evolução, rentabilidade, top 10 por categoria, uma aba por fundo) + CSV.

## Limites dos dados (importante)
- Carteiras são **mensais**; meses recentes podem ter ativos **confidenciais** (até 6 meses). O painel usa o último mês "aberto" para crédito.
- Derivativos vêm pelo valor informado (em geral nocional): ficam fora da soma de 100%.
- Quando a carteira informada não fecha com o PL, a diferença aparece como "Ajuste carteira x PL".
- ANBIMA gratuita guarda só ~15 dias úteis: o histórico de spread/duration cresce a partir do uso.
- Não há preço **ao vivo** gratuito de debêntures/CRI/LF (mercado de balcão); a referência pública é a taxa indicativa ANBIMA de fim de dia.
