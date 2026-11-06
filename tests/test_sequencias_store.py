# coding: utf-8
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest import mock

from sequencias_store import (
    MAX_CUSTOMIZADAS,
    SEQUENCIAS_ORIGINAIS,
    CatalogoSequencias,
    LimiteDeSequenciasError,
    caminho_do_banco,
    chave_de,
)


class TestCatalogoSequencias(unittest.TestCase):

    def setUp(self):
        self.diretorio = tempfile.TemporaryDirectory()
        self.caminho = os.path.join(self.diretorio.name, 'deciframe.db')
        self.catalogo = CatalogoSequencias(self.caminho)

    def tearDown(self):
        self.diretorio.cleanup()

    def test_seeds_com_ids_e_acordes_exatos(self):
        sequencias = self.catalogo.listar()

        self.assertEqual([s.id for s in sequencias], list(range(6)))
        self.assertEqual(
            [s.acordes for s in sequencias],
            [acordes for _, acordes in SEQUENCIAS_ORIGINAIS],
        )
        self.assertTrue(all(s.origem == 'original' for s in sequencias))

    def test_auto_increment_comeca_em_6(self):
        sequencia, criada = self.catalogo.criar(['C', 'Am', 'F', 'G'])

        self.assertTrue(criada)
        self.assertEqual(sequencia.id, 6)
        self.assertEqual(sequencia.origem, 'customizada')

    def test_duplicata_normaliza_caixa_e_espaco(self):
        primeira, criada = self.catalogo.criar(['C', 'Am', 'F', 'G'])
        segunda, criada_de_novo = self.catalogo.criar([' c ', ' AM ', 'f', 'g'])

        self.assertTrue(criada)
        self.assertFalse(criada_de_novo)
        self.assertEqual(primeira.id, segunda.id)
        self.assertEqual(self.catalogo.contar_customizadas(), 1)

    def test_duplicata_de_seed_retorna_id_da_seed(self):
        sequencia, criada = self.catalogo.criar(['Bm', 'G', 'D', 'A'])

        self.assertFalse(criada)
        self.assertEqual(sequencia.id, 0)
        self.assertEqual(self.catalogo.contar_customizadas(), 0)

    def test_preserva_caixa_ordem_e_repeticoes(self):
        sequencia, _ = self.catalogo.criar(['C', 'C', 'G', 'Am'])

        self.assertEqual(sequencia.acordes, ['C', 'C', 'G', 'Am'])
        self.assertEqual(
            json.loads(chave_de(sequencia.acordes)),
            ['c', 'c', 'g', 'am'],
        )

    def test_busca_por_chave_e_reabertura_do_arquivo(self):
        sequencia, _ = self.catalogo.criar(['C', 'D', 'E'])
        outro_catalogo = CatalogoSequencias(self.caminho)

        encontrada = outro_catalogo.buscar_por_chave([' c ', 'd', 'E'])

        self.assertIsNotNone(encontrada)
        self.assertEqual(encontrada.id, sequencia.id)

    def test_criar_rejeita_lista_vazia_e_tipo_invalido(self):
        with self.assertRaises(ValueError):
            self.catalogo.criar([])
        with self.assertRaises(ValueError):
            self.catalogo.criar(['  ', ''])

    def test_criar_rejeita_acordes_invalidos(self):
        for acordes in (
            ['aaaaaaaa'],
            ['C', 'H'],
            ['C', 'Cfoo'],
            ['C', 'C#x'],
            ['C', '123'],
        ):
            with self.subTest(acordes=acordes):
                with self.assertRaises(ValueError):
                    self.catalogo.criar(acordes)

        self.assertEqual(self.catalogo.contar_customizadas(), 0)

    def test_criar_aceita_acordes_com_sufixos_usuais(self):
        acordes = ['C#m7b5', 'G/B', 'F#', 'Bb7M', 'Am', 'Dsus4']
        sequencia, criada = self.catalogo.criar(acordes)

        self.assertTrue(criada)
        self.assertEqual(sequencia.acordes, acordes)

    def test_teto_de_customizadas(self):
        agora = '2026-01-01T00:00:00+00:00'
        with closing(sqlite3.connect(self.caminho)) as conexao:
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

        self.assertEqual(self.catalogo.contar_customizadas(), MAX_CUSTOMIZADAS)
        with self.assertRaises(LimiteDeSequenciasError):
            self.catalogo.criar(['Z'])

        # Duplicata é verificada antes do teto.
        sequencia, criada = self.catalogo.criar([' custom '])
        self.assertFalse(criada)
        self.assertEqual(sequencia.acordes, ['CUSTOM'])

    def test_falha_ao_abrir_aborta_sem_fallback(self):
        arquivo = os.path.join(self.diretorio.name, 'nao-e-diretorio')
        with open(arquivo, 'w'):
            pass

        with self.assertRaises(RuntimeError):
            CatalogoSequencias(os.path.join(arquivo, 'deciframe.db'))

    def test_schema_versionado(self):
        with closing(sqlite3.connect(self.caminho)) as conexao:
            versao = conexao.execute('PRAGMA user_version').fetchone()[0]
        self.assertEqual(versao, 1)

    def test_banco_tem_apenas_a_tabela_de_sequencias(self):
        # Músicas e gêneros continuam no CSV; só sequências vão para o banco.
        with closing(sqlite3.connect(self.caminho)) as conexao:
            tabelas = {
                linha[0]
                for linha in conexao.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(tabelas, {'sequencias', 'sqlite_sequence'})

    def test_wal_e_busy_timeout_configurados(self):
        with closing(sqlite3.connect(self.caminho)) as conexao:
            journal_mode = conexao.execute(
                'PRAGMA journal_mode'
            ).fetchone()[0]
            busy_timeout = conexao.execute(
                'PRAGMA busy_timeout'
            ).fetchone()[0]

        self.assertEqual(journal_mode, 'wal')
        self.assertGreaterEqual(busy_timeout, 1000)

    def test_caminho_do_banco_respeita_env_e_usa_var_por_padrao(self):
        with mock.patch.dict(
            os.environ, {'DECIFRAME_DB': '/caminho/explicito.db'}
        ):
            self.assertEqual(
                caminho_do_banco(), '/caminho/explicito.db'
            )

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DECIFRAME_DB', None)
            self.assertTrue(
                caminho_do_banco().endswith(
                    os.path.join('var', 'deciframe.db')
                )
            )

    def test_diretorio_pai_do_banco_e_criado(self):
        caminho = os.path.join(
            self.diretorio.name, 'novo', 'subdiretorio', 'deciframe.db'
        )

        CatalogoSequencias(caminho)

        self.assertTrue(os.path.exists(caminho))

    def test_reabrir_nao_duplica_as_seeds(self):
        CatalogoSequencias(self.caminho)
        reaberto = CatalogoSequencias(self.caminho)

        self.assertEqual(
            [s.id for s in reaberto.listar()], list(range(6))
        )
        self.assertEqual(reaberto.contar_customizadas(), 0)

    def test_listar_em_ordem_de_cadastro(self):
        criadas = [
            self.catalogo.criar(['C'])[0],
            self.catalogo.criar(['D'])[0],
            self.catalogo.criar(['E'])[0],
        ]

        sequencias = self.catalogo.listar()

        self.assertEqual([s.id for s in sequencias], list(range(9)))
        self.assertEqual(
            [s.id for s in sequencias[6:]],
            [s.id for s in criadas],
        )
        self.assertEqual(
            [s.acordes for s in sequencias[6:]],
            [['C'], ['D'], ['E']],
        )

    def test_obter_e_buscar_desconhecidos_retornam_none(self):
        self.assertIsNone(self.catalogo.obter(-1))
        self.assertIsNone(self.catalogo.obter(6))
        self.assertIsNone(self.catalogo.buscar_por_chave(['X', 'Y']))

    def test_normaliza_espacos_e_descarta_tokens_vazios(self):
        sequencia, criada = self.catalogo.criar(
            [' C ', '', '   ', 'G ']
        )

        self.assertTrue(criada)
        self.assertEqual(sequencia.acordes, ['C', 'G'])

        # Cadastrar de novo, agora sem os tokens vazios, é duplicata.
        mesma, criada_de_novo = self.catalogo.criar(['C', 'G'])
        self.assertFalse(criada_de_novo)
        self.assertEqual(mesma.id, sequencia.id)

    def test_criar_rejeita_tipos_invalidos(self):
        for valor in ([1], ['C', 1], 'C,G', None, 42):
            with self.subTest(valor=valor):
                with self.assertRaises(ValueError):
                    self.catalogo.criar(valor)

        self.assertEqual(self.catalogo.contar_customizadas(), 0)

    def test_chave_normaliza_caixa_espaco_e_distingue_repeticoes(self):
        self.assertEqual(
            chave_de([' C ', 'g']), chave_de(['c', 'G'])
        )
        self.assertNotEqual(
            chave_de(['C', 'C', 'G']), chave_de(['C', 'G'])
        )

    def test_acorde_invalido_com_sql_nao_altera_o_schema(self):
        with self.assertRaises(ValueError):
            self.catalogo.criar(["C'); DROP TABLE sequencias; --"])

        self.assertEqual(len(self.catalogo.listar()), 6)

    def test_rejeita_versao_futura_do_schema(self):
        with closing(sqlite3.connect(self.caminho)) as conexao:
            conexao.execute('PRAGMA user_version = 2')
            conexao.commit()

        with self.assertRaises(RuntimeError):
            CatalogoSequencias(self.caminho)

    def test_rejeita_seed_divergente(self):
        with closing(sqlite3.connect(self.caminho)) as conexao:
            with conexao:
                conexao.execute(
                    "UPDATE sequencias "
                    "SET acordes = '[\"X\"]', chave = '[\"x\"]' "
                    'WHERE id = 0'
                )

        with self.assertRaises(RuntimeError):
            CatalogoSequencias(self.caminho)

    def test_origem_invalida_e_rejeitada_pelo_schema(self):
        with closing(sqlite3.connect(self.caminho)) as conexao:
            with self.assertRaises(sqlite3.IntegrityError):
                with conexao:
                    conexao.execute(
                        'INSERT INTO sequencias '
                        '(acordes, chave, origem, criado_em) '
                        "VALUES ('[\"C\"]', '[\"c\"]', 'invalida', 'x')"
                    )


if __name__ == '__main__':
    unittest.main()
