# coding: utf-8
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from urllib.parse import quote

# O main.py lê o catálogo no import; o banco de teste precisa existir antes.
_DIRETORIO_DB = tempfile.mkdtemp(prefix='deciframe-api-')
os.environ['DECIFRAME_DB'] = os.path.join(_DIRETORIO_DB, 'deciframe.db')

import main  # noqa: E402
from sequencias_store import (  # noqa: E402
    MAX_CUSTOMIZADAS,
    CatalogoSequencias,
    chave_de,
)


def json_da_resposta(resposta):
    return json.loads(resposta.get_data(as_text=True))


class TestApiSequencias(unittest.TestCase):

    def setUp(self):
        self.client = main.app.test_client()
        main.rate_limiter_post.limpar()

        for id_seq in list(main.indice_sequencias._bitsets):
            if id_seq >= 6:
                main.indice_sequencias.esquecer(id_seq)

        with closing(
            sqlite3.connect(main.catalogo_sequencias.caminho)
        ) as conexao:
            with conexao:
                conexao.execute(
                    "DELETE FROM sequencias WHERE origem = 'customizada'"
                )
                conexao.execute(
                    "UPDATE sqlite_sequence SET seq = 5 "
                    "WHERE name = 'sequencias'"
                )

    def coletar(self, url_base):
        ids = set()
        pagina = 1
        separador = '&' if '?' in url_base else '?'

        while True:
            resposta = self.client.get(
                '%s%spagina=%d' % (url_base, separador, pagina)
            )
            self.assertEqual(resposta.status_code, 200)
            dados = json_da_resposta(resposta)
            if not dados:
                break
            ids.update(item['id_unico_musica'] for item in dados)
            if len(dados) < main.TAM_PAGINA:
                break
            pagina += 1

        return ids

    def coletar_sequencia(self, id_seq, generos=None):
        url = '/similares?sequencia_id=%s' % id_seq
        if generos:
            url += '&generos=' + quote(generos, safe='')
        return self.coletar(url)

    def ids_da_tag_csv(self, id_seq):
        return {
            musica.id_unico_musica
            for musica in main.musicas.values()
            if str(id_seq) in musica.seqs_famosas
        }

    def test_startup_calcula_apenas_as_seis_seeds(self):
        self.assertEqual(
            set(main.indice_sequencias._bitsets), set(range(6))
        )
        self.assertTrue(all(
            main.indice_sequencias.aquecido(id_seq)
            for id_seq in range(6)
        ))

    def test_post_calcula_bitset_e_busca_recalcula_lazy(self):
        criada = json_da_resposta(self.client.post(
            '/sequencias', json={'acordes': ['C', 'Am', 'F', 'G']}
        ))

        self.assertTrue(main.indice_sequencias.aquecido(criada['id']))

        main.indice_sequencias.esquecer(criada['id'])
        self.assertFalse(main.indice_sequencias.aquecido(criada['id']))

        self.assertTrue(self.coletar_sequencia(criada['id']))
        self.assertTrue(main.indice_sequencias.aquecido(criada['id']))

    def test_falha_de_bitset_na_busca_retorna_500_json(self):
        original = main.indice_sequencias.obter
        self.addCleanup(setattr, main.indice_sequencias, 'obter', original)

        def falhar(*_args, **_kwargs):
            raise RuntimeError('falha simulada')

        main.indice_sequencias.obter = falhar

        resposta = self.client.get('/similares?sequencia_id=0')

        self.assertEqual(resposta.status_code, 500)
        self.assertTrue(resposta.content_type.startswith('text/html'))
        self.assertIn('erro', json_da_resposta(resposta))

    def test_rate_limit_e_por_ip(self):
        primeiro = '198.51.100.10'
        segundo = '198.51.100.11'

        for _ in range(10):
            resposta = self.client.post(
                '/sequencias', json={},
                environ_base={'REMOTE_ADDR': primeiro},
            )
            self.assertEqual(resposta.status_code, 400)

        resposta = self.client.post(
            '/sequencias', json={},
            environ_base={'REMOTE_ADDR': primeiro},
        )
        self.assertEqual(resposta.status_code, 429)
        self.assertIsNotNone(resposta.headers.get('Retry-After'))

        resposta = self.client.post(
            '/sequencias', json={},
            environ_base={'REMOTE_ADDR': segundo},
        )
        self.assertEqual(resposta.status_code, 400)

    def test_generos_e_catalogo_de_seeds(self):
        resposta = self.client.get('/generos')
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.content_type.startswith('text/html'))
        self.assertIsInstance(json_da_resposta(resposta), list)

        resposta = self.client.get('/sequencias')
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.content_type.startswith('text/html'))

        sequencias = json_da_resposta(resposta)
        self.assertEqual([s['id'] for s in sequencias], list(range(6)))
        self.assertEqual(
            [s['acordes'] for s in sequencias],
            [
                ['Bm', 'G', 'D', 'A'],
                ['C', 'G', 'Am', 'F'],
                ['Em', 'G'],
                ['C', 'A7', 'Dm', 'G7'],
                ['Gm', 'F'],
                ['C', 'C7', 'F', 'Fm'],
            ],
        )
        self.assertTrue(all(s['origem'] == 'original' for s in sequencias))
        self.assertTrue(all('nome' not in s for s in sequencias))

    def test_regressao_das_seis_seeds_contra_tags_do_csv(self):
        contagens_esperadas = {0: 199, 1: 296, 2: 4, 3: 5, 4: 7, 5: 3}

        for id_seq, contagem in contagens_esperadas.items():
            with self.subTest(seed=id_seq):
                esperado = self.ids_da_tag_csv(id_seq)
                obtido = self.coletar_sequencia(id_seq)
                self.assertEqual(len(esperado), contagem)
                self.assertEqual(obtido, esperado)

    def test_alias_legado(self):
        casos = {
            'Bm,G,D,A': 0,
            'BmGDA': 0,
            'CA7,Dm,G7': 3,
            'CA7DmG7': 3,
            'C, G, Am, F': 1,
            'c,g,am,f': 1,
        }

        for alias, id_seq in casos.items():
            with self.subTest(alias=alias):
                obtido = self.coletar(
                    '/similares?sequencia=' + quote(alias, safe=',')
                )
                self.assertEqual(obtido, self.ids_da_tag_csv(id_seq))

        desconhecido = self.coletar('/similares?sequencia=X,Y')
        self.assertEqual(desconhecido, set())

    def test_sequencia_id_invalido_ou_inexistente_devolve_vazio(self):
        for valor in ['abc', '9999', '', '0.5']:
            with self.subTest(valor=valor):
                resposta = self.client.get(
                    '/similares?sequencia_id=' + quote(valor, safe='')
                )
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(json_da_resposta(resposta), [])

    def test_cadastro_novo_busca_por_id_e_alias(self):
        resposta = self.client.post(
            '/sequencias', json={'acordes': ['C', 'Am', 'F', 'G']}
        )
        self.assertEqual(resposta.status_code, 201)
        self.assertTrue(resposta.content_type.startswith('text/html'))

        criada = json_da_resposta(resposta)
        self.assertEqual(criada['id'], 6)
        self.assertEqual(criada['acordes'], ['C', 'Am', 'F', 'G'])
        self.assertEqual(criada['origem'], 'customizada')
        self.assertNotIn('nome', criada)

        catalogo = json_da_resposta(self.client.get('/sequencias'))
        self.assertEqual(len(catalogo), 7)
        self.assertEqual(catalogo[-1], criada)

        por_id = self.coletar_sequencia(criada['id'])
        por_alias = self.coletar(
            '/similares?sequencia=' + quote('C,Am,F,G', safe=',')
        )
        self.assertTrue(por_id)
        self.assertEqual(por_id, por_alias)

    def test_duplicata_normalizada_e_duplicata_de_seed(self):
        primeira = json_da_resposta(self.client.post(
            '/sequencias', json={'acordes': ['C', 'Am', 'F', 'G']}
        ))
        self.assertEqual(primeira['id'], 6)

        resposta = self.client.post(
            '/sequencias', json={'acordes': [' c ', ' AM ', 'f', 'g']}
        )
        self.assertEqual(resposta.status_code, 200)
        duplicada = json_da_resposta(resposta)
        self.assertEqual(duplicada['id'], primeira['id'])
        self.assertEqual(
            main.catalogo_sequencias.contar_customizadas(), 1
        )

        resposta = self.client.post(
            '/sequencias', json={'acordes': ['Bm', 'G', 'D', 'A']}
        )
        self.assertEqual(resposta.status_code, 200)
        seed = json_da_resposta(resposta)
        self.assertEqual(seed['id'], 0)
        self.assertEqual(seed['origem'], 'original')
        self.assertEqual(
            main.catalogo_sequencias.contar_customizadas(), 1
        )

    def test_validacao_400(self):
        casos = [
            {'acordes': []},
            {'acordes': ['  ', '']},
            {'acordes': 'C,G'},
            {'acordes': [1, 2]},
            {'acordes': ['C', None]},
            {'foo': ['C']},
        ]

        for payload in casos:
            with self.subTest(payload=payload):
                resposta = self.client.post('/sequencias', json=payload)
                self.assertEqual(resposta.status_code, 400)
                self.assertTrue(
                    resposta.content_type.startswith('text/html')
                )
                self.assertIn('erro', json_da_resposta(resposta))

        resposta = self.client.post(
            '/sequencias', data='{', content_type='application/json'
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('erro', json_da_resposta(resposta))

    def test_um_e_nove_acordes_sao_aceitos(self):
        resposta = self.client.post(
            '/sequencias', json={'acordes': ['C']}
        )
        self.assertEqual(resposta.status_code, 201)

        resposta = self.client.post(
            '/sequencias',
            json={'acordes': ['C', 'D', 'E', 'F', 'G', 'A', 'B', 'Bb', 'Eb']},
        )
        self.assertEqual(resposta.status_code, 201)

    def test_acordes_sem_formato_valido_retornam_400(self):
        casos = [
            ['aaaaaaaa'],
            ['C', 'H'],
            ['C', 'Cfoo'],
            ['C', 'C#x'],
            ['C', '123'],
        ]

        for acordes in casos:
            with self.subTest(acordes=acordes):
                resposta = self.client.post(
                    '/sequencias', json={'acordes': acordes}
                )
                self.assertEqual(resposta.status_code, 400)
                self.assertIn('erro', json_da_resposta(resposta))

        self.assertEqual(
            main.catalogo_sequencias.contar_customizadas(), 0
        )

    def test_acordes_com_sufixos_usuais_sao_aceitos(self):
        resposta = self.client.post(
            '/sequencias',
            json={'acordes': ['C#m7b5', 'G/B', 'F#', 'Bb7M', 'Am', 'Dsus4']},
        )

        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(
            json_da_resposta(resposta)['acordes'],
            ['C#m7b5', 'G/B', 'F#', 'Bb7M', 'Am', 'Dsus4'],
        )

    def test_corpo_acima_de_16kb_retorna_413(self):
        resposta = self.client.post(
            '/sequencias', json={'acordes': ['X' * 20000]}
        )
        self.assertEqual(resposta.status_code, 413)
        self.assertTrue(resposta.content_type.startswith('text/html'))
        self.assertIn('erro', json_da_resposta(resposta))

    def test_rate_limit_retorna_429_com_retry_after(self):
        for _ in range(10):
            resposta = self.client.post('/sequencias', json={})
            self.assertEqual(resposta.status_code, 400)

        resposta = self.client.post('/sequencias', json={})
        self.assertEqual(resposta.status_code, 429)
        self.assertIsNotNone(resposta.headers.get('Retry-After'))
        self.assertGreater(int(resposta.headers['Retry-After']), 0)
        self.assertTrue(resposta.content_type.startswith('text/html'))
        self.assertIn('erro', json_da_resposta(resposta))

    def test_teto_de_customizadas_429_duplicata_200(self):
        agora = '2026-01-01T00:00:00+00:00'
        with closing(
            sqlite3.connect(main.catalogo_sequencias.caminho)
        ) as conexao:
            with conexao:
                conexao.executemany(
                    'INSERT INTO sequencias '
                    '(acordes, chave, origem, criado_em) VALUES (?, ?, ?, ?)',
                    [
                        (
                            json.dumps(['CUSTOM'] if i == 0 else ['X%d' % i]),
                            chave_de(['CUSTOM'] if i == 0 else ['X%d' % i]),
                            'customizada',
                            agora,
                        )
                        for i in range(MAX_CUSTOMIZADAS)
                    ],
                )

        resposta = self.client.post(
            '/sequencias', json={'acordes': ['Z']}
        )
        self.assertEqual(resposta.status_code, 429)
        self.assertIn('erro', json_da_resposta(resposta))

        resposta = self.client.post(
            '/sequencias', json={'acordes': ['Bm', 'G', 'D', 'A']}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(json_da_resposta(resposta)['id'], 0)

        resposta = self.client.post(
            '/sequencias', json={'acordes': [' custom ']}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(json_da_resposta(resposta)['acordes'], ['CUSTOM'])

        catalogo = json_da_resposta(self.client.get('/sequencias'))
        self.assertEqual(len(catalogo), 6 + MAX_CUSTOMIZADAS)
        self.assertEqual(
            [s['id'] for s in catalogo],
            list(range(6 + MAX_CUSTOMIZADAS)),
        )
        self.assertTrue(all('nome' not in s for s in catalogo))

    def test_precedencia_dos_parametros(self):
        self.assertEqual(
            self.client.get(
                '/similares?acordes=C&sequencia_id=2&pagina=1'
            ).get_data(as_text=True),
            self.client.get(
                '/similares?acordes=C&pagina=1'
            ).get_data(as_text=True),
        )

        id_musica = next(iter(main.musicas))
        id_codificado = quote(id_musica, safe='')
        self.assertEqual(
            self.client.get(
                '/similares?id_unico_musica=%s&sequencia_id=2&pagina=1'
                % id_codificado
            ).get_data(as_text=True),
            self.client.get(
                '/similares?id_unico_musica=%s&pagina=1' % id_codificado
            ).get_data(as_text=True),
        )

        self.assertEqual(
            self.coletar('/similares?sequencia_id=2&sequencia=Bm,G,D,A'),
            self.ids_da_tag_csv(2),
        )

    def test_paginacao(self):
        pagina1 = json_da_resposta(self.client.get(
            '/similares?sequencia_id=0&pagina=1'
        ))
        pagina2 = json_da_resposta(self.client.get(
            '/similares?sequencia_id=0&pagina=2'
        ))
        pagina3 = json_da_resposta(self.client.get(
            '/similares?sequencia_id=0&pagina=3'
        ))

        self.assertEqual(len(pagina1), 100)
        self.assertEqual(len(pagina2), 99)
        self.assertEqual(pagina3, [])

    def test_filtro_por_genero(self):
        genero = next(
            genero
            for genero in main.generos
            if any(
                str(0) in musica.seqs_famosas
                for musica in main.genero_musicas[genero]
            )
        )
        esperado = {
            musica.id_unico_musica
            for musica in main.genero_musicas[genero]
            if str(0) in musica.seqs_famosas
        }

        self.assertEqual(
            self.coletar_sequencia(0, genero), esperado
        )

    def test_resposta_de_sequencia_tem_os_nove_campos(self):
        dados = json_da_resposta(self.client.get(
            '/similares?sequencia_id=2'
        ))
        self.assertTrue(dados)
        self.assertEqual(
            set(dados[0]),
            {
                'id_unico_musica',
                'id_artista',
                'id_musica',
                'nome_artista',
                'nome_musica',
                'popularidade',
                'acordes',
                'genero',
                'url',
            },
        )

    def test_persistencia_apos_reabrir_o_catalogo(self):
        criada = json_da_resposta(self.client.post(
            '/sequencias', json={'acordes': ['C', 'D', 'E', 'F']}
        ))

        reaberto = CatalogoSequencias(main.catalogo_sequencias.caminho)
        encontrada = reaberto.buscar_por_chave(['c', 'd', 'e', 'f'])

        self.assertIsNotNone(encontrada)
        self.assertEqual(encontrada.id, criada['id'])
        self.assertEqual(
            self.coletar_sequencia(encontrada.id),
            self.coletar_sequencia(criada['id']),
        )

    def test_persistencia_com_cache_frio_apos_restart(self):
        criada = json_da_resposta(self.client.post(
            '/sequencias', json={'acordes': ['C', 'Am', 'F', 'G']}
        ))
        esperado = self.coletar_sequencia(criada['id'])
        self.assertTrue(esperado)

        original = main.catalogo_sequencias
        self.addCleanup(setattr, main, 'catalogo_sequencias', original)
        main.catalogo_sequencias = CatalogoSequencias(original.caminho)
        main.indice_sequencias.esquecer(criada['id'])

        self.assertFalse(main.indice_sequencias.aquecido(criada['id']))
        self.assertEqual(self.coletar_sequencia(criada['id']), esperado)
        self.assertTrue(main.indice_sequencias.aquecido(criada['id']))

    def test_sequencia_id_fora_do_intervalo_do_sqlite_devolve_vazio(self):
        # Valores fora de 64 bits fazem o sqlite3 levantar OverflowError;
        # para o contrato da API continuam sendo "id inexistente" -> [].
        valores = [
            str(2 ** 63 - 1),
            str(2 ** 63),
            str(2 ** 63 + 1),
            str(-(2 ** 63)),
            str(-(2 ** 63) - 1),
            '9' * 30,
        ]

        for valor in valores:
            with self.subTest(valor=valor):
                resposta = self.client.get(
                    '/similares?sequencia_id=' + valor
                )
                self.assertEqual(resposta.status_code, 200)
                self.assertTrue(
                    resposta.content_type.startswith('text/html')
                )
                self.assertEqual(json_da_resposta(resposta), [])

    def test_payload_json_que_nao_e_objeto_retorna_400(self):
        for payload in ([], None, 1, True, 'abc'):
            with self.subTest(payload=payload):
                resposta = self.client.post('/sequencias', json=payload)
                self.assertEqual(resposta.status_code, 400)
                self.assertIn('erro', json_da_resposta(resposta))

        self.assertEqual(
            main.catalogo_sequencias.contar_customizadas(), 0
        )

    def test_content_type_nao_json_retorna_400(self):
        resposta = self.client.post(
            '/sequencias',
            data='{"acordes": ["C"]}',
            content_type='text/plain',
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertTrue(resposta.content_type.startswith('text/html'))
        self.assertIn('erro', json_da_resposta(resposta))

    def test_cadastro_normaliza_espacos_e_preserva_repeticoes(self):
        resposta = self.client.post(
            '/sequencias',
            json={'acordes': [' C ', '', '   ', ' G ', 'C']},
        )
        self.assertEqual(resposta.status_code, 201)
        criada = json_da_resposta(resposta)
        self.assertEqual(criada['acordes'], ['C', 'G', 'C'])

        sem_repeticao = json_da_resposta(self.client.post(
            '/sequencias', json={'acordes': ['C', 'G']}
        ))
        self.assertNotEqual(sem_repeticao['id'], criada['id'])

        por_id = self.coletar_sequencia(criada['id'])
        por_alias = self.coletar('/similares?sequencia=c,g,c')
        self.assertTrue(por_id)
        self.assertEqual(por_id, por_alias)

    def test_catalogo_em_ordem_de_cadastro_e_criado_em_iso8601(self):
        criadas = []
        for acordes in (['C'], ['D'], ['E']):
            criadas.append(json_da_resposta(self.client.post(
                '/sequencias', json={'acordes': acordes}
            )))

        catalogo = json_da_resposta(self.client.get('/sequencias'))

        self.assertEqual(
            [s['id'] for s in catalogo],
            list(range(9)),
        )
        self.assertEqual(
            [s['acordes'] for s in catalogo[6:]],
            [['C'], ['D'], ['E']],
        )
        self.assertEqual(
            [s['id'] for s in catalogo[6:]],
            [s['id'] for s in criadas],
        )
        for sequencia in catalogo:
            self.assertNotIn('nome', sequencia)
            criado_em = datetime.fromisoformat(sequencia['criado_em'])
            self.assertEqual(
                criado_em.utcoffset(), timedelta(0)
            )

    def test_duplicata_de_seed_nao_altera_as_seeds(self):
        antes = json_da_resposta(self.client.get('/sequencias'))

        resposta = self.client.post(
            '/sequencias',
            json={'acordes': [' c ', 'a7', 'DM', 'g7']},
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(json_da_resposta(resposta)['id'], 3)
        depois = json_da_resposta(self.client.get('/sequencias'))
        self.assertEqual(depois, antes)

    def test_metodos_de_escrita_nao_suportados_retornam_405(self):
        antes = json_da_resposta(self.client.get('/sequencias'))

        for metodo in (self.client.put, self.client.delete, self.client.patch):
            with self.subTest(metodo=metodo.__name__):
                resposta = metodo('/sequencias')
                self.assertEqual(resposta.status_code, 405)

        self.assertEqual(
            self.client.delete('/sequencias/0').status_code, 405
        )
        self.assertEqual(
            json_da_resposta(self.client.get('/sequencias')), antes
        )

    def test_alias_vazio_ou_so_espacos_devolve_vazio(self):
        for alias in ('', '   ', ',', ' , '):
            with self.subTest(alias=alias):
                resposta = self.client.get(
                    '/similares?sequencia=' + quote(alias, safe='')
                )
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(json_da_resposta(resposta), [])

    def test_alias_normaliza_caixa_espaco_e_repeticoes(self):
        self.assertEqual(
            self.coletar(
                '/similares?sequencia=' + quote(' c , G , aM , f ', safe=',')
            ),
            self.ids_da_tag_csv(1),
        )

        criada = json_da_resposta(self.client.post(
            '/sequencias', json={'acordes': ['C', 'C', 'G']}
        ))
        self.assertEqual(
            self.coletar('/similares?sequencia=c,c,g'),
            self.coletar_sequencia(criada['id']),
        )

    def test_genero_inexistente_devolve_vazio(self):
        resposta = self.client.get(
            '/similares?sequencia_id=0&generos=GeneroQueNaoExiste'
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(json_da_resposta(resposta), [])

    def test_pagina_alem_do_fim_devolve_vazio(self):
        resposta = self.client.get(
            '/similares?sequencia_id=0&pagina=999'
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(json_da_resposta(resposta), [])

    def test_acorde_com_sql_nao_altera_o_catalogo(self):
        resposta = self.client.post(
            '/sequencias',
            json={'acordes': ["C'); DROP TABLE sequencias; --"]},
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('erro', json_da_resposta(resposta))
        catalogo = json_da_resposta(self.client.get('/sequencias'))
        self.assertEqual(len(catalogo), 6)
        self.assertEqual(
            [s['id'] for s in catalogo], list(range(6))
        )


def tearDownModule():
    shutil.rmtree(_DIRETORIO_DB, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
