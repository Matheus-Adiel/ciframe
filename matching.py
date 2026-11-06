# coding: utf-8
"""Regra de matching e índice em memória para as sequências de acordes.

A regra é a mesma validada em ``artifacts/verifica_matching.py``:

    casa(C, S) <=> existe C[i:i+len(S)] == S   (bloco contíguo, ordem exata)
                   e set(C) <= set(S)          (acorde fora de S não casa)

A comparação é feita com ``strip().lower()``; não há transposição,
enarmonia, baixo invertido nem simplificação de sufixo.
"""

import threading
from typing import Dict, Iterable, List, Optional, Sequence


def _normaliza(acordes: Iterable[str]) -> List[str]:
    return [acorde.strip().lower() for acorde in acordes]


def casa(cifra: Sequence[str], acordes: Sequence[str]) -> bool:
    """Verifica se ``acordes`` aparece como bloco contíguo em ``cifra``."""
    c = _normaliza(cifra)
    s = _normaliza(acordes)

    if not s or len(s) > len(c):
        return False

    conjunto_c = set(c)
    conjunto_s = set(s)
    if not conjunto_c.issubset(conjunto_s):
        return False

    return any(c[i:i + len(s)] == s for i in range(len(c) - len(s) + 1))


def _ligar_bit(bitset: bytearray, indice: int) -> None:
    bitset[indice >> 3] |= 1 << (indice & 7)


def bit_ligado(bitset: bytearray, indice: int) -> bool:
    """Testa o bit de ``indice`` no bitset."""
    return bool(bitset[indice >> 3] & (1 << (indice & 7)))


def construir_bitset(musicas: Sequence, posicoes: Dict[str, int],
                     acordes: Sequence[str]) -> bytearray:
    """Constrói um bitset com um bit por música, na ordem global de ``musicas``."""
    bitset = bytearray((len(musicas) + 7) // 8)
    for musica in musicas:
        indice = posicoes.get(musica.id_unico_musica)
        if indice is not None and casa(musica.cifra, acordes):
            _ligar_bit(bitset, indice)
    return bitset


class IndiceSequencias:
    """Cache de bitsets por ``id_seq``.

    O mapa de posições é construído uma única vez a partir da ordem global de
    ``musicas``. O cálculo do bitset acontece fora do lock; se duas requisições
    calcularem a mesma sequência, o resultado é idempotente e a última gravação
    vence.
    """

    def __init__(self, musicas: Sequence) -> None:
        self.musicas = list(musicas)
        self.posicoes = {
            musica.id_unico_musica: indice
            for indice, musica in enumerate(self.musicas)
        }
        self._bitsets: Dict[int, bytearray] = {}
        self._lock = threading.Lock()

    def obter(self, id_seq: int, acordes: Sequence[str]) -> bytearray:
        """Devolve o bitset da sequência, calculando-o e cacheando se preciso."""
        with self._lock:
            bitset = self._bitsets.get(id_seq)
        if bitset is not None:
            return bitset

        # Cálculo pesado fora do lock.
        bitset = construir_bitset(self.musicas, self.posicoes, acordes)

        with self._lock:
            self._bitsets[id_seq] = bitset
        return bitset

    def contem(self, id_seq: int, id_unico_musica: str) -> bool:
        """Testa a música no bitset cacheado da sequência."""
        with self._lock:
            bitset = self._bitsets.get(id_seq)
        if bitset is None:
            raise KeyError('sequência %s não está indexada' % id_seq)

        indice = self.posicoes.get(id_unico_musica)
        return indice is not None and bit_ligado(bitset, indice)

    def aquecido(self, id_seq: int) -> bool:
        """Indica se o bitset da sequência já está no cache."""
        with self._lock:
            return id_seq in self._bitsets

    def esquecer(self, id_seq: int) -> None:
        """Remove o bitset do cache (usado em testes/operação)."""
        with self._lock:
            self._bitsets.pop(id_seq, None)
