# coding: utf-8
"""Catálogo persistido de sequências de acordes em SQLite (stdlib).

As seis sequências originais usam IDs fixos 0–5 e são imutáveis. Sequências
cadastradas por visitantes recebem IDs a partir de 6. Não há campo ``nome``: o
rótulo é a própria lista de acordes.
"""

import json
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

SCHEMA_VERSAO = 1
MAX_CUSTOMIZADAS = 500
CAMINHO_PADRAO = os.path.join('.', 'var', 'deciframe.db')

SEQUENCIAS_ORIGINAIS = [
    (0, ['Bm', 'G', 'D', 'A']),
    (1, ['C', 'G', 'Am', 'F']),
    (2, ['Em', 'G']),
    (3, ['C', 'A7', 'Dm', 'G7']),
    (4, ['Gm', 'F']),
    (5, ['C', 'C7', 'F', 'Fm']),
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sequencias (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  acordes   TEXT NOT NULL,
  chave     TEXT NOT NULL UNIQUE,
  origem    TEXT NOT NULL CHECK (origem IN ('original', 'customizada')),
  criado_em TEXT NOT NULL
)
"""


class LimiteDeSequenciasError(Exception):
    """O catálogo já atingiu o teto de sequências customizadas."""


@dataclass(frozen=True)
class Sequencia:
    id: int
    acordes: List[str]
    origem: str
    criado_em: str

    def para_dict(self) -> dict:
        return {
            'id': self.id,
            'acordes': list(self.acordes),
            'origem': self.origem,
            'criado_em': self.criado_em,
        }


def caminho_do_banco() -> str:
    """Resolve ``DECIFRAME_DB``; sem a variável, usa ``./var/deciframe.db``."""
    return os.environ.get('DECIFRAME_DB') or CAMINHO_PADRAO


def normalizar_acordes(acordes: Sequence[str]) -> List[str]:
    """Remove espaços e tokens vazios, preservando caixa, ordem e repetições."""
    if isinstance(acordes, (str, bytes)) or not isinstance(acordes, (list, tuple)):
        raise ValueError('a sequência deve ser uma lista de acordes')

    normalizados = []
    for acorde in acordes:
        if not isinstance(acorde, str):
            raise ValueError('cada acorde deve ser texto')
        acorde = acorde.strip()
        if acorde:
            normalizados.append(acorde)

    if not normalizados:
        raise ValueError('a sequência não pode ser vazia')

    return normalizados


def chave_de(acordes: Sequence[str]) -> str:
    """Chave normalizada usada para deduplicação (strip + lower)."""
    return json.dumps([acorde.strip().lower() for acorde in acordes])


# Nota raiz + acidente + sufixos usuais de cifra brasileira (m, 7M, sus, add,
# alterações, baixo invertido etc.). A lista é fechada para rejeitar texto que
# não seja um acorde, como "aaaaaaaa".
_NOTA = r'[A-Ga-g](?:#|b|♯|♭)?'
_EXTENSAO = r'(?:[2-9]|1[13])'
_QUALIDADE = (
    r'(?:maj|min|dim|aug|sus|add|omit|alt|no|'
    r'm|M|o|°|º|\+|-|[#b♯♭]|' + _EXTENSAO + r')'
)
_GRUPO = r'\((?:' + _QUALIDADE + r'|/)*\)'
_ACORDE_RE = re.compile(
    r'^' + _NOTA + r'(?:' + _QUALIDADE + r'|' + _GRUPO + r')*'
    r'(?:/' + _NOTA + r'|/' + _EXTENSAO + r')?$'
)


def validar_acordes(acordes: Sequence[str]) -> None:
    """Rejeita tokens que não sejam nomes de acordes reconhecíveis."""
    for acorde in acordes:
        if not _ACORDE_RE.match(acorde.strip()):
            raise ValueError('acorde inválido: %s' % acorde.strip())


def _agora_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class CatalogoSequencias:
    """Acesso ao catálogo SQLite; abre uma conexão por operação."""

    def __init__(self, caminho: Optional[str] = None) -> None:
        self.caminho = caminho or caminho_do_banco()
        self._preparar()

    def _conectar(self) -> sqlite3.Connection:
        conexao = sqlite3.connect(self.caminho, timeout=5.0)
        conexao.row_factory = sqlite3.Row
        conexao.execute('PRAGMA journal_mode=WAL')
        conexao.execute('PRAGMA busy_timeout=5000')
        return conexao

    def _preparar(self) -> None:
        if self.caminho != ':memory:':
            diretorio = os.path.dirname(os.path.abspath(self.caminho))
            try:
                os.makedirs(diretorio, exist_ok=True)
            except OSError as exc:
                raise RuntimeError(
                    'não foi possível criar o diretório do banco de sequências '
                    'em %s: %s' % (diretorio, exc)
                ) from exc

        try:
            with closing(self._conectar()) as conexao:
                versao = conexao.execute('PRAGMA user_version').fetchone()[0]
                if versao > SCHEMA_VERSAO:
                    raise RuntimeError(
                        'o banco de sequências em %s tem versão %s, mas esta '
                        'aplicação suporta apenas a versão %s'
                        % (self.caminho, versao, SCHEMA_VERSAO)
                    )

                with conexao:
                    conexao.execute(_SCHEMA)
                    self._inserir_seeds(conexao)
                    if versao == 0:
                        conexao.execute(
                            'PRAGMA user_version = %d' % SCHEMA_VERSAO
                        )
        except sqlite3.Error as exc:
            raise RuntimeError(
                'não foi possível abrir ou inicializar o banco de sequências '
                'em %s: %s' % (self.caminho, exc)
            ) from exc

    def _inserir_seeds(self, conexao: sqlite3.Connection) -> None:
        criado_em = _agora_iso()
        for id_seq, acordes in SEQUENCIAS_ORIGINAIS:
            conexao.execute(
                'INSERT OR IGNORE INTO sequencias '
                '(id, acordes, chave, origem, criado_em) '
                'VALUES (?, ?, ?, ?, ?)',
                (id_seq, json.dumps(acordes), chave_de(acordes),
                 'original', criado_em),
            )

        # As seeds são imutáveis: se o volume tiver uma linha divergente,
        # falha cedo em vez de servir um catálogo inconsistente.
        for id_seq, acordes in SEQUENCIAS_ORIGINAIS:
            linha = conexao.execute(
                'SELECT acordes, origem FROM sequencias WHERE id = ?',
                (id_seq,),
            ).fetchone()
            if linha is None:
                raise RuntimeError(
                    'a seed %s não pôde ser criada no banco de sequências' % id_seq
                )
            try:
                atuais = json.loads(linha['acordes'])
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    'a seed %s está com acordes inválidos no banco' % id_seq
                ) from exc
            if atuais != acordes or linha['origem'] != 'original':
                raise RuntimeError(
                    'a seed %s está divergente no banco: esperado %s, '
                    'encontrado %s' % (id_seq, acordes, atuais)
                )

    @staticmethod
    def _linha_para_sequencia(linha: sqlite3.Row) -> Sequencia:
        try:
            acordes = json.loads(linha['acordes'])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                'a sequência %s tem acordes inválidos no banco' % linha['id']
            ) from exc
        return Sequencia(
            id=linha['id'],
            acordes=acordes,
            origem=linha['origem'],
            criado_em=linha['criado_em'],
        )

    def listar(self) -> List[Sequencia]:
        with closing(self._conectar()) as conexao:
            linhas = conexao.execute(
                'SELECT id, acordes, origem, criado_em FROM sequencias '
                'ORDER BY id'
            ).fetchall()
        return [self._linha_para_sequencia(linha) for linha in linhas]

    def obter(self, id_seq: int) -> Optional[Sequencia]:
        with closing(self._conectar()) as conexao:
            linha = conexao.execute(
                'SELECT id, acordes, origem, criado_em FROM sequencias '
                'WHERE id = ?',
                (id_seq,),
            ).fetchone()
        if linha is None:
            return None
        return self._linha_para_sequencia(linha)

    def buscar_por_chave(self, acordes: Sequence[str]) -> Optional[Sequencia]:
        try:
            tokens = normalizar_acordes(acordes)
        except ValueError:
            return None

        with closing(self._conectar()) as conexao:
            linha = conexao.execute(
                'SELECT id, acordes, origem, criado_em FROM sequencias '
                'WHERE chave = ?',
                (chave_de(tokens),),
            ).fetchone()
        if linha is None:
            return None
        return self._linha_para_sequencia(linha)

    def contar_customizadas(self) -> int:
        with closing(self._conectar()) as conexao:
            return conexao.execute(
                "SELECT COUNT(*) FROM sequencias WHERE origem = 'customizada'"
            ).fetchone()[0]

    def criar(self, acordes: Sequence[str]) -> Tuple[Sequencia, bool]:
        """Cria a sequência ou devolve a existente.

        Retorna ``(sequencia, criada)``; ``criada`` é ``False`` para duplicata.
        Duplicata é verificada antes do teto.
        """
        tokens = normalizar_acordes(acordes)
        chave = chave_de(tokens)
        acordes_json = json.dumps(tokens)

        with closing(self._conectar()) as conexao:
            linha = conexao.execute(
                'SELECT id, acordes, origem, criado_em FROM sequencias '
                'WHERE chave = ?',
                (chave,),
            ).fetchone()
            if linha is not None:
                return self._linha_para_sequencia(linha), False

            total = conexao.execute(
                "SELECT COUNT(*) FROM sequencias WHERE origem = 'customizada'"
            ).fetchone()[0]
            if total >= MAX_CUSTOMIZADAS:
                raise LimiteDeSequenciasError(
                    'o catálogo já atingiu o limite de %d sequências '
                    'customizadas' % MAX_CUSTOMIZADAS
                )

            validar_acordes(tokens)

            try:
                with conexao:
                    cursor = conexao.execute(
                        'INSERT INTO sequencias '
                        '(acordes, chave, origem, criado_em) '
                        'VALUES (?, ?, ?, ?)',
                        (acordes_json, chave, 'customizada', _agora_iso()),
                    )
            except sqlite3.IntegrityError:
                # Corrida no UNIQUE: outra requisição inseriu a mesma chave.
                linha = conexao.execute(
                    'SELECT id, acordes, origem, criado_em FROM sequencias '
                    'WHERE chave = ?',
                    (chave,),
                ).fetchone()
                if linha is None:
                    raise
                return self._linha_para_sequencia(linha), False

            linha = conexao.execute(
                'SELECT id, acordes, origem, criado_em FROM sequencias '
                'WHERE id = ?',
                (cursor.lastrowid,),
            ).fetchone()

        return self._linha_para_sequencia(linha), True
