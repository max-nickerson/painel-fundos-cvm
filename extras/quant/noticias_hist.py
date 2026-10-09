"""Historical daily news/filing sentiment for Brazilian debenture issuers + macro (2019-01-01 .. today).

Free, keyless sources only:
  cvm   -> CVM IPE filings (fatos relevantes, comunicados...)  -> dados/noticias_cvm.parquet
  gdelt -> GDELT DOC 2.0 timelinetone / timelinevolraw        -> dados/noticias_gdelt.parquet
Everything downloaded is cached under dados/noticias_cache/, so reruns are resumable.

Usage:  python noticias_hist.py [cvm|gdelt|all]
"""
import sys, os, io, re, json, time, zipfile, unicodedata, datetime as dt
import pandas as pd, numpy as np, requests

BASE = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(BASE, 'dados')
CACHE = os.path.join(DADOS, 'noticias_cache')
INI, HOJE = dt.date(2019, 1, 1), dt.date.today()
N_EMISSORES, N_GDELT = 150, 60
EXTRAS = ['00776574000660', '60444437000146', '76535764000143', '07575651000159']  # Americanas, Light, Oi, Gol (stress cases)


def norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9 ]+', ' ', s)


# ---------------------------------------------------------------- issuers
def emissores():
    cad = pd.read_parquet(os.path.join(DADOS, 'snd_cadastro.parquet'))
    neg = pd.read_parquet(os.path.join(DADOS, 'snd_negocios.parquet'))
    neg = neg[neg.date >= '2021-01-01'].merge(cad[['codigo', 'cnpj']], on='codigo')
    vol = (neg.qtd * neg.pu_med).groupby(neg.cnpj).sum().sort_values(ascending=False)
    top = list(vol.index[:N_EMISSORES]) + [c for c in EXTRAS if c in set(cad.cnpj) and c not in vol.index[:N_EMISSORES]]
    nomes = cad.drop_duplicates('cnpj').set_index('cnpj').empresa
    return pd.DataFrame({'cnpj': top, 'empresa': nomes.reindex(top).values, 'vol': vol.reindex(top).values})


# ---------------------------------------------------------------- CVM IPE
NEG = ['recuperacao judicial', 'recuperacao extrajudicial', 'inadimpl', 'vencimento antecipado', 'rebaixamento',
       'default', 'waiver', 'assembleia de debenturistas', 'agdeb', 'reestrutura', 'renuncia', 'investigac',
       'prejuizo', 'liquidacao extrajudicial', 'falencia', 'suspensao', 'fraude', 'inconsistencia', 'impairment',
       'covenant', 'nao pagamento', 'descumprimento', 'protesto', 'acao judicial', 'processo administrativo',
       'operacao policial', 'busca e apreensao', 'mediacao', 'standstill', 'renegociacao', 'calamidade',
       'downgrade', 'perspectiva negativa', 'observacao negativa', 'multa', 'condenacao', 'arbitragem',
       'afastamento', 'deficiencia', 'perda', 'baixa contabil', 'distrato', 'rescisao', 'caducidade',
       'intervencao', 'auto de infracao', 'acordo de leniencia', 'dificuldade', 'sinistro', 'acidente',
       'rompimento', 'paralisacao', 'interrupcao', 'ressalva', 'tutela de urgencia', 'tutela cautelar',
       'medida cautelar', 'decisao judicial', 'situacao financeira', 'estrutura de capital', 'assessor',
       'stand by', 'linha de credito', 'comite independente', 'ajuizamento', 'exclusao dos indices',
       'esclarecimentos', 'noticia divulgada', 'noticias veiculadas', 'alteracao de rating', 'alteracoes de rating',
       'nota de credito', 'revisao do rating', 'pedido de', 'credores', 'plano de recuperacao',
       'ajuste de exercicios', 'reapresentacao', 'auditoria forense', 'cvm sep', 'irregularidade']
POS = ['aprovacao', 'aquisicao concluida', 'conclusao da aquisicao', 'captacao', 'emissao', 'elevacao',
       'upgrade', 'lucro', 'dividendo', 'juros sobre capital', 'jcp', 'recompra', 'resgate antecipado',
       'pre pagamento', 'prepagamento', 'perspectiva positiva', 'vencedor', 'vencedora', 'arremat', 'leilao',
       'parceria', 'expansao', 'investimento', 'recorde', 'reajuste tarifario', 'revisao tarifaria',
       'homologacao', 'liberacao', 'financiamento', 'desalavanc', 'venda de ativo', 'desinvestimento',
       'encerramento da recuperacao', 'saida da recuperacao', 'bonificacao', 'aumento da capacidade',
       'antidumping', 'grau de investimento', 'melhora', 'aumento de capital']


def _hits(txt, words):
    return sum(w in txt for w in words)


def ipe_raw():
    os.makedirs(os.path.join(CACHE, 'cvm'), exist_ok=True)
    out = []
    for y in range(INI.year, HOJE.year + 1):
        f = os.path.join(CACHE, 'cvm', f'ipe_{y}.zip')
        if not os.path.exists(f) or (y == HOJE.year and time.time() - os.path.getmtime(f) > 86400):
            r = requests.get(f'https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{y}.zip', timeout=300)
            r.raise_for_status(); open(f, 'wb').write(r.content)
        z = zipfile.ZipFile(f)
        out.append(pd.read_csv(z.open(z.namelist()[0]), sep=';', encoding='latin1', dtype=str))
    d = pd.concat(out, ignore_index=True)
    d['cnpj_cvm'] = d.CNPJ_Companhia.str.replace(r'\D', '', regex=True).str.zfill(14)
    d['date'] = pd.to_datetime(d.Data_Entrega, errors='coerce')
    d = d[(d.date >= str(INI)) & (d.date <= str(HOJE))]
    return d.drop_duplicates('Protocolo_Entrega', keep='last')  # re-submissions (Versao>1) counted once


STOP = set('cia companhia concessionaria de do da dos das e s a sa s/a ltda holding participacoes participacao '
           'energia energetica eletrica eletricidade distribuicao distribuidora transmissao transmissora geracao '
           'saneamento rodovias rodovia sistema brasil brasileira nacional servicos industria comercio sociedade '
           'banco central centrais estadual paulista uhe ute spe the em recuperacao judicial grupo nova aguas '
           'metropol rede investimentos investimento empreendimentos securitizadora logistica transportadora associada'.split())


def chave_nome(nome):
    t = [w for w in norm(nome).split() if w not in STOP and len(w) >= 3]
    return t[0] if t else None


MANUAL = {'08336783000190': '83878892000155'}  # Celesc Distribuicao -> Celesc (holding)


def mapa_cvm(em, d):
    """CNPJ match first; for unmatched issuers fall back to the parent/listed company whose *first significant
    word* is identical and unique among CVM filers (e.g. LOCALIZA FLEET -> LOCALIZA RENT A CAR)."""
    cvm = d.groupby('cnpj_cvm').agg(nome=('Nome_Companhia', 'last'), n=('date', 'size')).reset_index()
    cvm['k'] = cvm.nome.map(chave_nome)
    ok = set(cvm.cnpj_cvm)
    rows = []
    for c, e in zip(em.cnpj, em.empresa):
        if c in ok:
            rows.append((c, e, c, 'cnpj')); continue
        raiz = cvm[cvm.cnpj_cvm.str[:8] == c[:8]]  # same company, other branch CNPJ
        if len(raiz):
            rows.append((c, e, raiz.sort_values('n').cnpj_cvm.iat[-1], 'raiz')); continue
        if c in MANUAL:
            rows.append((c, e, MANUAL[c], 'manual')); continue
        k = chave_nome(e)
        cand = cvm[cvm.k == k] if k else cvm.iloc[:0]
        if len(cand) == 1:
            rows.append((c, e, cand.cnpj_cvm.iat[0], 'nome:' + cand.nome.iat[0]))
        elif len(cand) > 1:
            rows.append((c, e, None, 'ambiguo:' + k))
        else:
            rows.append((c, e, None, 'sem_match'))
    return pd.DataFrame(rows, columns=['cnpj', 'empresa', 'cnpj_cvm', 'match'])


def roda_cvm():
    em, d = emissores(), ipe_raw()
    mp = mapa_cvm(em, d)
    mp.astype(str).to_csv(os.path.join(DADOS, 'noticias_cvm_mapa.csv'), index=False, encoding='utf-8-sig')
    d = d.merge(mp.dropna(subset=['cnpj_cvm'])[['cnpj', 'cnpj_cvm']], on='cnpj_cvm')
    cat = d.Categoria.map(norm)
    txt = (cat + ' ' + d.Tipo.fillna('').map(norm) + ' ' + d.Especie.fillna('').map(norm) + ' ' + d.Assunto.fillna('').map(norm))
    d['n_fato'] = cat.str.contains('fato relevante').astype(int)
    d['n_comunicado'] = cat.str.contains('comunicado ao mercado').astype(int)
    d['sent_neg'] = txt.map(lambda t: _hits(t, NEG))
    d['sent_pos'] = txt.map(lambda t: _hits(t, POS) - ('agdeb' in t and 'emissao' in t))  # AGDEB titles say 'Emissao'
    out = d.groupby(['date', 'cnpj'])[['n_fato', 'n_comunicado', 'sent_neg', 'sent_pos']].sum().reset_index()
    out['n_docs'] = d.groupby(['date', 'cnpj']).size().values
    out.to_parquet(os.path.join(DADOS, 'noticias_cvm.parquet'), index=False)
    print(f'CVM: {len(out)} linhas, {out.cnpj.nunique()}/{len(em)} emissores, {out.date.min():%Y-%m-%d}..{out.date.max():%Y-%m-%d}')
    print(mp.match.str.split(':').str[0].value_counts().to_string())
    return out


# ---------------------------------------------------------------- GDELT
GURL = 'https://api.gdeltproject.org/api/v2/doc/doc'
PAUSA = 7.0
_ult = [0.0]


def gdelt(query, mode, ini, fim, tentativas=8):
    """One cached GDELT call. Returns parsed json (or {} when GDELT has no data)."""
    os.makedirs(os.path.join(CACHE, 'gdelt'), exist_ok=True)
    key = re.sub(r'[^A-Za-z0-9]+', '_', f'{query}_{mode}_{ini:%Y%m%d}_{fim:%Y%m%d}')[:180]
    f = os.path.join(CACHE, 'gdelt', key + '.json')
    if os.path.exists(f):
        return json.load(open(f, encoding='utf-8'))
    p = dict(query=query, mode=mode, format='json', startdatetime=f'{ini:%Y%m%d}000000', enddatetime=f'{fim:%Y%m%d}235959')
    for k in range(tentativas):
        time.sleep(max(0, PAUSA - (time.time() - _ult[0])))
        try:
            r = requests.get(GURL, params=p, timeout=120); _ult[0] = time.time()
        except requests.RequestException as e:
            print('  erro rede', e, flush=True); _ult[0] = time.time(); time.sleep(30); continue
        if r.status_code == 429 or 'limit requests' in r.text[:200]:
            w = min(60 * 2 ** k, 600); print(f'  429 -> espera {w}s', flush=True); time.sleep(w); continue
        txt = r.text.strip()
        if r.status_code != 200 or not txt.startswith('{'):
            print('  resposta invalida', r.status_code, txt[:150], flush=True)
            if 'too short' in txt or 'not found' in txt.lower() or 'invalid' in txt.lower():
                js = {'erro': txt[:300]}; json.dump(js, open(f, 'w', encoding='utf-8')); return js
            time.sleep(30); continue
        js = json.loads(txt) if txt != '{}' else {}
        json.dump(js, open(f, 'w', encoding='utf-8'))
        return js
    raise RuntimeError(f'GDELT falhou: {query} {ini}')


def serie(js):
    tl = js.get('timeline') or []
    if not tl:
        return pd.Series(dtype=float)
    d = tl[0]['data']
    return pd.Series([x['value'] for x in d], index=pd.to_datetime([x['date'][:8] for x in d]))


MACRO = {
    'macro_bcb_selic': '("Banco Central" OR Copom) Selic sourcecountry:BR',
    'macro_inflacao': '(inflação OR IPCA) sourcecountry:BR sourcelang:portuguese',
    'macro_fiscal': '("arcabouço fiscal" OR "meta fiscal" OR "dívida pública" OR "déficit") sourcecountry:BR',
    'macro_cambio': '(dólar câmbio) sourcecountry:BR sourcelang:portuguese',
    'macro_credito': '("recuperação judicial" OR calote OR inadimplência) sourcecountry:BR',
    'macro_economia': '(economia OR PIB OR juros) sourcecountry:BR sourcelang:portuguese',
}
# short distinctive names (quoted in query) for the top issuers; generic/ambiguous ones are left out
APELIDO = {
    'LOCALIZA': 'Localiza', 'REDE DOR': 'Rede D\'Or', 'VALE S': 'Vale|mineradora', 'ISA ENERGIA': 'ISA Energia',
    'AXIA': 'Axia Energia', 'ENERGISA SA': 'Energisa', 'TRANSPORTADORA DO SUDESTE': 'NTS|gasoduto',
    'SABESP': 'Sabesp', 'ENEVA': 'Eneva', 'HAPVIDA': 'Hapvida', 'COSAN': 'Cosan', 'CEMIG': 'Cemig',
    'EQUATORIAL': 'Equatorial|energia', 'AEGEA': 'Aegea', 'DIAGNOSTICOS DA AMERICA': 'Dasa', 'MOVIDA': 'Movida',
    'ENGIE': 'Engie Brasil', 'PRIO': 'Prio|petróleo', 'COELBA': 'Coelba', 'TRANSMISSORA ALIANCA': 'Taesa', 'COPEL': 'Copel',
    'ECORODOVIAS': 'Ecorodovias', 'CLARO': 'Claro|operadora', 'SENDAS': 'Assaí', 'HYPERA': 'Hypera', 'MRS': 'MRS Logística',
    'VAMOS': 'Vamos|locação', 'AUREN': 'Auren|energia', 'BRAVA': 'Brava Energia', 'CHESF': 'Chesf', 'SUZANO': 'Suzano',
    'CEEE': 'CEEE', 'MOTIVA': 'Motiva|concessões', 'TIM BRASIL': 'TIM Brasil', 'VIBRA': 'Vibra Energia', 'IGUA': 'Iguá|saneamento',
    'BRK': 'BRK Ambiental', 'TAG': 'TAG|gás', 'COMPASS': 'Compass Gás', 'PETROBRAS': 'Petrobras',
    'SERENA': 'Serena Energia', 'ALGAR': 'Algar', 'COMGAS': 'Comgás', 'ELETROPAULO': 'Enel São Paulo',
    'EUROFARMA': 'Eurofarma', 'EDP|energia': 'EDP|energia', 'VLI|ferrovia': 'VLI|ferrovia', 'RUMO': 'Rumo|ferrovia', 'SIDERURGICA NACIONAL': 'CSN',
    'JSL|logística': 'JSL|logística', 'METROVIARIA DO RIO': 'MetrôRio', 'ITAUSA': 'Itaúsa', 'CIELO': 'Cielo', 'CELPE': 'Celpe',
    'PAULISTA DE FORCA': 'CPFL', 'ARTERIS': 'Arteris', 'COPASA': 'Copasa', 'ELETRONORTE': 'Eletronorte',
    'COELCE': 'Coelce', 'ELEKTRO': 'Elektro', 'ARMAC': 'Armac', 'SIMPAR': 'Simpar', 'SMARTFIT': 'Smart Fit',
    'B3 S': 'B3|bolsa', 'CORSAN': 'Corsan', 'QUALICORP': 'Qualicorp', 'BRASKEM': 'Braskem',
    'TELEFONICA': 'Telefônica', 'BRASILEIRA DE DISTRIBUICAO': 'Pão de Açúcar', 'KLABIN': 'Klabin',
    'MAGAZINE': 'Magazine Luiza', 'RAIZEN': 'Raízen', 'USIMINAS': 'Usiminas', 'AMERICANAS': 'Americanas',
    'LIGHT SERVICOS': 'Light|energia', 'OI S': 'Oi|operadora', 'GOL LINHAS': 'Gol|aérea',
}


def apelido(nome):
    for k, v in APELIDO.items():
        if k in nome:
            return v
    return None


def janelas(passo_meses):
    a = pd.Timestamp(INI)
    while a.date() <= HOJE:
        b = min(a + pd.DateOffset(months=passo_meses) - pd.Timedelta(days=1), pd.Timestamp(HOJE))
        yield a.date(), b.date(); a = b + pd.Timedelta(days=1)


def roda_gdelt(passo_meses=3):
    """Daily resolution needs short windows; one tone + one volume call per window per key."""
    em = emissores()
    chaves, usados, mapa = dict(MACRO), {}, []  # one query per nickname (subsidiaries share the parent's key)
    for c, e in zip(em.cnpj, em.empresa):
        a = apelido(str(e))
        prio = c in EXTRAS or 'BRASKEM' in str(e)  # stress-test names always in
        if a and a not in usados and (len(usados) < N_GDELT or prio):
            usados[a] = f'emissor_{c}'
            nome, _, ctx = a.partition('|')  # 'Vale|mineradora' -> "Vale" mineradora
            chaves[usados[a]] = f'"{nome}" {ctx} sourcecountry:BR'.replace('  ', ' ')
        if a in usados:
            mapa.append((c, e, usados[a]))
    pd.DataFrame(mapa, columns=['cnpj', 'empresa', 'chave']).to_csv(
        os.path.join(DADOS, 'noticias_gdelt_mapa.csv'), index=False, encoding='utf-8-sig')
    json.dump(chaves, open(os.path.join(CACHE, 'gdelt_chaves.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    try:  # preflight: is this IP being served at all, and does history (2019) work?
        teste = gdelt('Petrobras sourcecountry:BR', 'timelinetone', dt.date(2019, 1, 1), dt.date(2019, 3, 31), tentativas=3)
    except RuntimeError:
        print('GDELT: API devolve 429 persistente para este IP (mesmo apos backoff) -> coleta pulada. Rode de novo mais tarde.')
        return None
    if not len(serie(teste)):
        print('GDELT: sem dados historicos para 2019 -> coleta pulada', teste); return None
    ws = list(janelas(passo_meses))
    tot = len(chaves) * len(ws) * 2
    print(f'GDELT: {len(chaves)} chaves x {len(ws)} janelas x 2 modos = {tot} chamadas (cache conta)', flush=True)
    rows, i = [], 0
    for ch, q in chaves.items():
        for a, b in ws:
            tom, vol = (serie(gdelt(q, m, a, b)) for m in ('timelinetone', 'timelinevolraw'))
            i += 2
            if len(tom) or len(vol):
                rows.append(pd.DataFrame({'tom': tom, 'volume': vol}).assign(chave=ch))
        print(f'  {ch}: ok ({i}/{tot})', flush=True)
        if rows:
            salva_gdelt(rows)
    return salva_gdelt(rows) if rows else print('GDELT: nenhum dado coletado')


def salva_gdelt(rows):
    g = pd.concat(rows).rename_axis('date').reset_index()
    g = g.groupby(['date', 'chave'], as_index=False).last()[['date', 'chave', 'tom', 'volume']]
    g.to_parquet(os.path.join(DADOS, 'noticias_gdelt.parquet'), index=False)
    return g


if __name__ == '__main__':
    alvo = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if alvo in ('cvm', 'all'):
        roda_cvm()
    if alvo in ('gdelt', 'all'):
        roda_gdelt()
