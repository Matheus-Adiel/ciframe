# coding: utf-8
import json
import math
import threading
import time
from flask import Flask, request
import sys
from musica import *
from collections import OrderedDict
import unicodedata

from matching import IndiceSequencias, bit_ligado
from sequencias_store import (
    CatalogoSequencias,
    LimiteDeSequenciasError,
    normalizar_acordes,
)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024

def limpa_cifra(raw_cifra):
    cifra = []
    for m in raw_cifra:
        if m.strip() != '':
            # filtra tablaturas
            if '|' in m:
                acorde = m.split('|')[0].split()[0]
                cifra.append(acorde)
            # lida com acordes separados por espaço
            else:
                tokens = [token for token in m.split()]
                cifra += tokens
    return cifra

# colunas do csv
ARTISTA_ID = 0
MUSICA_ID = 1
ARTISTA = 2
MUSICA = 3
GENERO = 4
POPULARIDADE = 5
TOM = 6
SEQ_FAMOSA = 7
CIFRA = 8
TAM_PAGINA = 100

genero_musicas = {}
generos = set()
acordes = set()
# Chaves legadas do alias ?sequencia= (sem vírgulas), preservando os índices.
sequencias = {'BmGDA' : 0,
        'CGAmF' : 1,
        'EmG' : 2,
        'CA7DmG7' : 3,
        'GmF' : 4,
        'CC7FFm' : 5}

musicas_dict = {}

f = open('data/top/dataset_final.csv')
f.readline()

for line in f:
    line = line.replace('"', '').replace('NA', '')[:-1]

    musica = line.split(',')
    musica[POPULARIDADE] = int(musica[POPULARIDADE].replace('.', ''))

    if musica[CIFRA] != '':
        musica[CIFRA] = limpa_cifra(musica[CIFRA].split(';'))
    else:
        musica[CIFRA] = []

    musica[SEQ_FAMOSA] = musica[SEQ_FAMOSA].split(";")

    # conjunto único de gêneros
    generos.add(musica[GENERO])

    # inclui música no dict de músicas
    musica_obj = Musica(musica[ARTISTA_ID], musica[ARTISTA],
            musica[MUSICA_ID], musica[MUSICA], musica[GENERO],
            int(musica[POPULARIDADE]), musica[SEQ_FAMOSA],
            musica[TOM], musica[CIFRA])

    musicas_dict[musica_obj.id_unico_musica] = musica_obj

    # conjunto único de acordes
    for acorde in musica_obj.acordes:
        acordes.add(acorde)

    # constrói dict mapeando gênero para músicas
    # deve ser usado para melhorar o desempenho das buscas
    if musica_obj.genero in genero_musicas:
        genero_musicas[musica_obj.genero].append(musica_obj)
    else:
        genero_musicas[musica_obj.genero] = [musica_obj]

# dicionário de músicas cujos valores são ordenados por popularidade
musicas = OrderedDict(sorted(musicas_dict.items(),
    key=lambda x: x[1].popularidade, reverse = True))

# para trabalhar melhor com json
generos = list(generos)

# ordena genero_musicas por popularidade
for k,v in genero_musicas.items():
    genero_musicas[k].sort(key = lambda x : x.popularidade, reverse = True)

f.close()

# Catálogo persistido de sequências (SQLite) e índice de matching em memória.
catalogo_sequencias = CatalogoSequencias()
indice_sequencias = IndiceSequencias(list(musicas.values()))

# As 6 seeds são calculadas eagerly; customizadas são calculadas lazy na
# primeira busca e cacheadas.
for _sequencia_original in catalogo_sequencias.listar():
    if _sequencia_original.origem == 'original':
        indice_sequencias.obter(_sequencia_original.id,
                                _sequencia_original.acordes)


class _RateLimiter:
    """Rate limit em memória, por processo e por chave (IP)."""

    def __init__(self, limite=10, janela=60.0):
        self.limite = limite
        self.janela = janela
        self._eventos = {}
        self._lock = threading.Lock()

    def permitir(self, chave):
        agora = time.monotonic()
        with self._lock:
            eventos = self._eventos.setdefault(chave, [])
            limite_inferior = agora - self.janela
            while eventos and eventos[0] <= limite_inferior:
                eventos.pop(0)

            if len(eventos) >= self.limite:
                retry_after = max(
                    1, int(math.ceil(self.janela - (agora - eventos[0])))
                )
                return False, retry_after

            eventos.append(agora)
            return True, 0

    def limpar(self, chave=None):
        with self._lock:
            if chave is None:
                self._eventos.clear()
            else:
                self._eventos.pop(chave, None)


rate_limiter_post = _RateLimiter()


def erro_json(mensagem, status, cabecalhos=None):
    return json.dumps({'erro': mensagem}), status, cabecalhos or {}


@app.errorhandler(413)
def _erro_corpo_grande(_erro):
    return erro_json('corpo da requisição muito grande', 413)


@app.errorhandler(500)
def _erro_interno(_erro):
    return erro_json('erro interno ao processar a requisição', 500)


@app.route('/')
def index():
    return app.send_static_file('index.html')
''' Busca por músicas que possuem no título ou no nome do artista o argumento passado por key.
params: key e generos (opcional). Caso generos não sejam definidos, a busca não irá filtrar por gênero.
exemplo 1: /search?key=no dia em que eu saí de casa
exemplo 2: /search?key=no dia em que eu saí de casa&generos=Rock,Samba '''

@app.route('/<path:path>')
def static_proxy(path):
  # send_static_file will guess the correct MIME type
  return app.send_static_file(path)

@app.route('/search')
def busca():
    generos_tag = request.args.get('generos', [])
    pagina_tag = request.args.get('pagina','1')
    keys = request.args.get('key').lower()
    keys = remover_combinantes(keys).split(' ')

    generos_key = generos
    if generos_tag:
        generos_key = generos_tag.split(',')

    collection = apply_filtro(musicas.values(), generos_key)
    out = []

    for musica in collection:
        text = '%s %s' % (musica.nome_artista.lower(), musica.nome_musica.lower())
        text_list = remover_combinantes(text).split(' ')
        if all(key in text_list for key in keys):
            matches = {
                'id_unico_musica' : musica.id_unico_musica,
                'id_artista' : musica.id_artista,
                'id_musica' : musica.id_musica,
                'nome_artista' : musica.nome_artista,
                'nome_musica' : musica.nome_musica,
                'genero' : musica.genero,
                'url' : musica.url,
            }
            out.append(matches)
    return json.dumps(get_pagina(out, pagina_tag))

# cópia
def remover_combinantes(string):
    string = unicodedata.normalize('NFD', string)
    return u''.join(ch for ch in string if unicodedata.category(ch) != 'Mn')

''' Retorna as músicas armazenadas no sistema (ordenados por popularidade).
    O serviço é paginado. Cada página tem tamanho 100, por default.
    params: pagina. Caso não seja definida a página, o valor default é 1.
    exemplo 1: /musica?pagina=2
    exemplo 2: /musica'''
@app.route('/musicas')
def get_musicas():
    return json.dumps([v.__dict__ for v in musicas.values()])

@app.route('/generos')
def get_generos():
    return json.dumps(generos)

@app.route('/acordes')
def get_acordes():
    return json.dumps(list(acordes))

@app.route('/sequencias')
def get_sequencias():
    try:
        return json.dumps([
            sequencia.para_dict()
            for sequencia in catalogo_sequencias.listar()
        ])
    except Exception:
        app.logger.exception('falha ao listar o catálogo de sequências')
        return erro_json('não foi possível listar as sequências', 500)

@app.route('/sequencias', methods=['POST'])
def post_sequencias():
    # A checagem de rate limit vem antes da validação do corpo (O-18).
    chave_rate = request.remote_addr or 'desconhecido'
    permitido, retry_after = rate_limiter_post.permitir(chave_rate)
    if not permitido:
        return erro_json(
            'limite de cadastros atingido; tente novamente mais tarde',
            429,
            {'Retry-After': str(retry_after)},
        )

    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return erro_json('corpo da requisição deve ser um objeto JSON', 400)

    acordes_brutos = dados.get('acordes')
    if not isinstance(acordes_brutos, list):
        return erro_json('o campo "acordes" deve ser uma lista', 400)

    try:
        acordes = normalizar_acordes(acordes_brutos)
    except ValueError as exc:
        return erro_json(str(exc), 400)

    try:
        sequencia, criada = catalogo_sequencias.criar(acordes)
    except ValueError as exc:
        return erro_json(str(exc), 400)
    except LimiteDeSequenciasError as exc:
        return erro_json(str(exc), 429)
    except Exception:
        app.logger.exception('falha ao cadastrar sequência')
        return erro_json('não foi possível cadastrar a sequência', 500)

    if criada:
        try:
            indice_sequencias.obter(sequencia.id, sequencia.acordes)
        except Exception:
            # O-06: a linha já está persistida; a busca recalcula lazy.
            app.logger.exception(
                'falha ao calcular o bitset da sequência %s', sequencia.id
            )

    return json.dumps(sequencia.para_dict()), 201 if criada else 200

@app.route('/musica/<m_id>/')
def get_musica(m_id):
    return json.dumps(musicas[m_id].__dict__)

@app.route('/similares')
def get_similares():
    # tratando request
    acordes_tag = request.args.get('acordes')
    id_musica_tag = request.args.get('id_unico_musica')
    sequencia_id_tag = request.args.get('sequencia_id')
    sequencia_tag = request.args.get('sequencia')
    pagina_tag = request.args.get('pagina','1')

    # se não existir, filtra por todos.
    generos_tag = request.args.get('generos')
    generos_key = generos
    if generos_tag:
        generos_key = generos_tag.split(',')

    acordes = []
    if acordes_tag:
        acordes = acordes_tag.split(',')
    elif id_musica_tag:
        musica = musicas[id_musica_tag]
        acordes = musica.acordes
    elif sequencia_id_tag is not None:
        return resposta_sequencia(
            sequencia_por_id(sequencia_id_tag), generos_key, pagina_tag
        )
    elif sequencia_tag is not None:
        return resposta_sequencia(
            sequencia_por_alias(sequencia_tag), generos_key, pagina_tag
        )

    similares = get_similares(acordes, generos_key, id_musica_tag)

    return json.dumps(get_pagina(similares, pagina_tag))


def sequencia_por_id(id_tag):
    try:
        id_seq = int(id_tag)
    except (TypeError, ValueError):
        return None
    # Fora do intervalo de INTEGER do SQLite o id não pode existir; sem esta
    # guarda o sqlite3 levanta OverflowError e a busca vira 500 em vez de [].
    if id_seq < -(2 ** 63) or id_seq > 2 ** 63 - 1:
        return None
    return catalogo_sequencias.obter(id_seq)


def sequencia_por_alias(alias):
    # Primeiro a chave legada sem vírgulas (BmGDA, CA7DmG7, ...).
    chave_legada = alias.replace(',', '').strip()
    if chave_legada in sequencias:
        return catalogo_sequencias.obter(sequencias[chave_legada])

    # Depois a lista normalizada por strip().lower().
    tokens = [token.strip() for token in alias.split(',') if token.strip()]
    if not tokens:
        return None
    return catalogo_sequencias.buscar_por_chave(tokens)


def resposta_sequencia(sequencia, generos_key, pagina_tag):
    if sequencia is None:
        return json.dumps([])

    try:
        bitset = indice_sequencias.obter(sequencia.id, sequencia.acordes)
    except Exception:
        # O-07: falha de cálculo não pode virar [] (que significa "sem
        # resultados"); responde 500 JSON.
        app.logger.exception(
            'falha ao calcular o bitset da sequência %s', sequencia.id
        )
        return erro_json('não foi possível calcular a sequência', 500)

    similares = get_similares_por_sequencia(bitset, generos_key)
    return json.dumps(get_pagina(similares, pagina_tag))


def get_similares_por_sequencia(bitset, generos_key):
    # filtra para melhor desempenho
    collection = apply_filtro(musicas.values(), generos_key)
    posicoes = indice_sequencias.posicoes

    similares = []
    for musica in collection:
        indice = posicoes.get(musica.id_unico_musica)
        if indice is not None and bit_ligado(bitset, indice):
            similar = {
                'id_unico_musica' : musica.id_unico_musica,
                'id_artista' : musica.id_artista,
                'id_musica' : musica.id_musica,
                'nome_artista' : musica.nome_artista,
                'nome_musica' : musica.nome_musica,
                'popularidade' : musica.popularidade,
                'acordes' : musica.acordes,
                'genero' : musica.genero,
                'url' : musica.url,
            }
            similares.append(similar)

    return similares


def get_pagina(colecao, pagina_tag):
    sl = (int(pagina_tag) - 1)*TAM_PAGINA
    return colecao[sl:sl+TAM_PAGINA]

def get_similares(acordes, generos_key, id_musica = None):

    # filtra para melhor desempenho
    collection = apply_filtro(musicas.values(), generos_key)

    similares = []
    for musica in collection:

        if musica.id_unico_musica != id_musica:

            inter = set(acordes).intersection(set(musica.acordes))
            diff = set(musica.acordes) - set(acordes)

            # somente as que tiverem interseção e as que forem
            # dos generos solicitados.
            if len(inter) > 0:
                similar = {
                        'id_unico_musica' : musica.id_unico_musica,
                        'id_artista' : musica.id_artista,
                        'id_musica' : musica.id_musica,
                        'nome_artista' : musica.nome_artista,
                        'nome_musica' : musica.nome_musica,
                        'popularidade' : musica.popularidade,
                        'acordes' : musica.acordes,
                        'genero' : musica.genero,
                        'url' : musica.url,
                        'diferenca' : list(diff),
                        'intersecao' : list(inter)
                }

                similares.append(similar)

    # ordenados por menor diferença, maior interseção e maior popularidade.
    return sorted(similares, key=lambda x: (len(x['diferenca']), -len(x['intersecao'])))

## Filtra a coleção de músicas por gênero.
def apply_filtro(musicas, generos_key):
    # filtra para melhor desempenho
    collection = []
    for genero in generos_key:
        if genero in generos:
            collection += genero_musicas[genero]
    return collection

@app.after_request
def add_header(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

if __name__ == '__main__':
    app.run(debug=True)
