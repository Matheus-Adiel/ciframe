# coding: utf-8
import unittest
from types import SimpleNamespace

from matching import (
    IndiceSequencias,
    bit_ligado,
    casa,
    construir_bitset,
)


def musica(id_unico, cifra):
    return SimpleNamespace(id_unico_musica=id_unico, cifra=cifra)


class TestCasa(unittest.TestCase):

    def test_bloco_contiguo_na_ordem_exata(self):
        self.assertTrue(casa(['C', 'G', 'Am', 'F'], ['C', 'G', 'Am', 'F']))
        self.assertTrue(casa(['F', 'C', 'G', 'Am', 'F'],
                             ['C', 'G', 'Am', 'F']))

    def test_ordem_trocada_nao_casa(self):
        self.assertFalse(casa(['C', 'F', 'Am', 'G'], ['C', 'G', 'Am', 'F']))

    def test_acorde_fora_do_conjunto_nao_casa(self):
        self.assertFalse(casa(['C', 'G', 'Am', 'F', 'D'],
                              ['C', 'G', 'Am', 'F']))

    def test_caixa_e_espacos_sao_normalizados(self):
        self.assertTrue(casa(['c', ' g ', 'AM', 'f'],
                             ['C', 'G', 'Am', 'F']))

    def test_repeticao_dentro_do_bloco_quebra_a_ocorrencia(self):
        self.assertFalse(casa(['C', 'G', 'G', 'Am', 'F'],
                              ['C', 'G', 'Am', 'F']))

    def test_sequencia_vazia_nao_casa(self):
        self.assertFalse(casa(['C', 'G'], []))

    def test_sequencia_maior_que_a_cifra_nao_casa(self):
        self.assertFalse(casa(['C', 'G'], ['C', 'G', 'Am']))

    def test_repeticao_fora_do_bloco_e_permitida(self):
        self.assertTrue(casa(['C', 'G', 'Am', 'F', 'C', 'G'],
                             ['C', 'G', 'Am', 'F']))

    def test_sem_transposicao_enarmonia_baixo_ou_sufixo(self):
        self.assertFalse(casa(['C#', 'G'], ['Db', 'G']))
        self.assertFalse(casa(['C/G', 'G'], ['C', 'G']))
        self.assertFalse(casa(['C7', 'G'], ['C', 'G']))

    def test_acorde_extra_antes_do_bloco_nao_casa(self):
        # O conjunto fechado vale para a cifra inteira, não só para o bloco.
        self.assertFalse(casa(['D', 'C', 'G'], ['C', 'G']))

    def test_acorde_extra_depois_do_bloco_nao_casa(self):
        self.assertFalse(casa(['C', 'G', 'F', 'C', 'G'], ['C', 'G']))

    def test_cifra_vazia_nao_casa(self):
        self.assertFalse(casa([], ['C']))
        self.assertFalse(casa([], []))

    def test_sequencia_minuscula_casa_cifra_maiuscula(self):
        self.assertTrue(casa(['C', 'G'], ['c', 'g']))

    def test_sequencia_com_repeticoes_proprias_casa(self):
        self.assertTrue(casa(['C', 'G', 'C', 'G'], ['C', 'G', 'C', 'G']))
        self.assertTrue(casa(['C', 'G', 'C', 'G'], ['C', 'G', 'C']))
        self.assertFalse(casa(['C', 'G', 'G', 'C'], ['C', 'G', 'C']))

    def test_sequencia_de_um_acorde_casa_no_fim_da_cifra(self):
        self.assertTrue(casa(['F', 'F'], ['F']))
        # O conjunto fechado continua valendo: D fora da sequência quebra.
        self.assertFalse(casa(['D', 'F'], ['F']))

    def test_espacos_na_sequencia_sao_ignorados(self):
        self.assertTrue(casa([' C ', ' g '], ['c', 'G']))


class TestBitset(unittest.TestCase):

    def setUp(self):
        self.musicas = [
            musica('a', ['C', 'G', 'Am', 'F']),
            musica('b', ['C', 'D', 'E']),
            musica('c', ['C', 'G', 'Am', 'F', 'C']),
            musica('d', []),
        ]
        self.posicoes = {
            m.id_unico_musica: i for i, m in enumerate(self.musicas)
        }

    def test_construir_bitset_liga_as_posicoes_certas(self):
        bitset = construir_bitset(
            self.musicas, self.posicoes, ['C', 'G', 'Am', 'F']
        )
        self.assertEqual(len(bitset), 1)
        self.assertTrue(bit_ligado(bitset, 0))
        self.assertFalse(bit_ligado(bitset, 1))
        self.assertTrue(bit_ligado(bitset, 2))
        self.assertFalse(bit_ligado(bitset, 3))

    def test_indice_calcula_e_cacheia(self):
        indice = IndiceSequencias(self.musicas)
        primeiro = indice.obter(7, ['C', 'G', 'Am', 'F'])
        segundo = indice.obter(7, ['C', 'G', 'Am', 'F'])

        self.assertIs(primeiro, segundo)
        self.assertTrue(indice.aquecido(7))
        self.assertTrue(indice.contem(7, 'a'))
        self.assertFalse(indice.contem(7, 'b'))

    def test_contem_sem_cache_falha(self):
        indice = IndiceSequencias(self.musicas)
        with self.assertRaises(KeyError):
            indice.contem(99, 'a')

    def test_calculo_concorrente_e_idempotente(self):
        indice = IndiceSequencias(self.musicas)
        resultados = []

        def calcular():
            resultados.append(indice.obter(3, ['C', 'G', 'Am', 'F']))

        import threading
        threads = [threading.Thread(target=calcular) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(resultados), 4)
        self.assertTrue(all(r == resultados[0] for r in resultados))

    def test_bitset_atravessa_limite_de_byte(self):
        # As posições 0, 8 e 16 caem em bytes diferentes do bitset.
        musicas = [
            musica(str(i), ['C'] if i in (0, 8, 16) else ['D'])
            for i in range(17)
        ]
        posicoes = {
            m.id_unico_musica: i for i, m in enumerate(musicas)
        }

        bitset = construir_bitset(musicas, posicoes, ['C'])

        self.assertEqual(len(bitset), 3)
        for indice in range(17):
            self.assertEqual(
                bit_ligado(bitset, indice),
                indice in (0, 8, 16),
                'posição %d' % indice,
            )
        # O último byte só deve usar o primeiro bit; os demais ficam zerados.
        self.assertEqual(bitset[2], 0b1)

    def test_bitset_sem_musicas(self):
        self.assertEqual(construir_bitset([], {}, ['C']), bytearray())

    def test_bitset_de_sequencia_vazia_nao_liga_nada(self):
        bitset = construir_bitset(self.musicas, self.posicoes, [])

        self.assertEqual(len(bitset), 1)
        self.assertFalse(any(
            bit_ligado(bitset, indice)
            for indice in range(len(self.musicas))
        ))

    def test_indice_contem_posicoes_alem_do_primeiro_byte(self):
        musicas = [
            musica(str(i), ['C'] if i == 8 else ['D'])
            for i in range(10)
        ]
        indice = IndiceSequencias(musicas)
        indice.obter(1, ['C'])

        self.assertTrue(indice.contem(1, '8'))
        self.assertFalse(indice.contem(1, '0'))
        self.assertFalse(indice.contem(1, '9'))

    def test_indice_com_sequencia_vazia_nao_contem_ninguem(self):
        indice = IndiceSequencias(self.musicas)
        indice.obter(2, [])

        self.assertFalse(any(
            indice.contem(2, m.id_unico_musica) for m in self.musicas
        ))

    def test_indice_nao_contem_musica_desconhecida(self):
        indice = IndiceSequencias(self.musicas)
        indice.obter(0, ['C', 'G', 'Am', 'F'])

        self.assertFalse(indice.contem(0, 'musica-que-nao-existe'))


if __name__ == '__main__':
    unittest.main()
