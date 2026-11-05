#!/usr/bin/env python3
# coding: utf-8
"""Confere a regra de matching descrita em research/algoritmo-de-matching.md
contra as tags SEQ_FAMOSA que a aplicação carrega hoje.

Regra documentada, aplicada à lista de acordes da música (C) e da sequência (S):

    casa(C, S) <=> existe C[i:i+len(S)] == S   (ordem exata, bloco contíguo)
                   e set(C) <= set(S)          (nenhum acorde fora de S)

Comparação em minúsculas. O script só lê a base; não altera nada.

São feitas duas conferências, com a mesma regra:

  [A] cifra crua do CSV  x  tag crua do CSV
      isola a regra em si (é o que o gerador offline via, sem passar por
      limpa_cifra nem pelo replace('NA', '') de main.py);

  [B] musica.cifra  x  musica.seqs_famosas  (objetos que o runtime usa)
      isola o efeito do carregamento de main.py sobre o resultado final.

Uso:
    .venv/bin/python artifacts/verifica_matching.py
    .venv/bin/python artifacts/verifica_matching.py --limite 10
"""

import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(RAIZ, 'data', 'top', 'dataset_final.csv')

# Cópia de scripts/generate_data_set.py:8, na mesma ordem (índice = tag).
SEQUENCIAS = [
    ['bm', 'g', 'd', 'a'],
    ['c', 'g', 'am', 'f'],
    ['em', 'g'],
    ['c', 'a7', 'dm', 'g7'],
    ['gm', 'f'],
    ['c', 'c7', 'f', 'fm'],
]

COLUNA_SEQ_FAMOSA = 7
COLUNA_CIFRA = 8


def casa(cifra, seq):
    """Regra documentada: bloco contíguo na ordem exata + conjunto contido."""
    c = [acorde.lower() for acorde in cifra]
    s = [acorde.lower() for acorde in seq]
    if not s or len(s) > len(c):
        return False
    if not set(c).issubset(s):
        return False
    return any(c[i:i + len(s)] == s for i in range(len(c) - len(s) + 1))


def matches(cifra):
    """Índices das sequências que casam com a cifra dada."""
    return {i for i, seq in enumerate(SEQUENCIAS) if casa(cifra, seq)}


def parse_tag(campo):
    """Tag do CSV ('NA', '0', '0-1', ...) -> conjunto de índices."""
    campo = campo.strip()
    if campo in ('', 'NA'):
        return set()
    return {int(p) for p in re.split(r'[;,-]', campo) if p.isdigit()}


def le_csv_cru():
    """(id, cifra crua, tag crua) de cada linha, na forma que o gerador via."""
    with open(CSV, encoding='utf-8') as f:
        f.readline()  # main.py:50 descarta o cabeçalho
        for linha in f:
            campos = linha.rstrip('\n').split(',')
            if len(campos) < 9:
                continue
            yield '%s_%s' % (campos[0], campos[1]), campos[COLUNA_CIFRA], campos[COLUNA_SEQ_FAMOSA]


def formata(ids):
    return sorted(ids) if ids else '—'


def relata(nome, total, divergencias, por_sequencia, limite):
    print('== %s ==' % nome)
    print('  músicas comparadas : %d' % total)
    print('  concordâncias      : %d' % (total - len(divergencias)))
    print('  divergências       : %d' % len(divergencias))
    print('  músicas por sequência (calculado): %s' % por_sequencia)
    for item in divergencias[:limite]:
        print('    ! %s  tag=%s  calculado=%s  cifra=%s'
              % (item['id'], formata(item['tag']), formata(item['calc']), item['cifra'][:70]))
    if len(divergencias) > limite:
        print('    ... e mais %d divergência(s); use --limite para ver mais.'
              % (len(divergencias) - limite))
    print()


def main():
    limite = 5
    if '--limite' in sys.argv:
        limite = int(sys.argv[sys.argv.index('--limite') + 1])

    print('arquivo: %s' % os.path.relpath(CSV, RAIZ))
    print('sequências: %d\n' % len(SEQUENCIAS))

    # [A] regra x tag do CSV, sobre a cifra crua.
    total_a = 0
    div_a = []
    contagem_a = {i: 0 for i in range(len(SEQUENCIAS))}
    for id_unico, cifra_crua, tag_crua in le_csv_cru():
        total_a += 1
        calculado = matches([] if cifra_crua in ('', 'NA') else cifra_crua.split(';'))
        esperado = parse_tag(tag_crua)
        for i in calculado:
            contagem_a[i] += 1
        if calculado != esperado:
            div_a.append({'id': id_unico, 'tag': esperado, 'calc': calculado, 'cifra': cifra_crua})
    relata('[A] cifra crua do CSV x tag crua do CSV', total_a, div_a, contagem_a, limite)

    # [B] regra x seqs_famosas, sobre os objetos do runtime.
    print('carregando main.py (lê o CSV inteiro)...')
    os.chdir(RAIZ)
    sys.path.insert(0, RAIZ)
    try:
        import main
    except ImportError as e:
        print('erro: não foi possível importar main.py (%s).' % e)
        print('rode com o interpretador do projeto, ex.: .venv/bin/python %s'
              % os.path.relpath(__file__, RAIZ))
        return 2

    total_b = 0
    div_b = []
    contagem_b = {i: 0 for i in range(len(SEQUENCIAS))}
    tags_compostas = 0
    for musica in main.musicas.values():
        total_b += 1
        calculado = matches(musica.cifra)
        esperado = {int(t) for t in musica.seqs_famosas if t.strip().isdigit()}
        if len(esperado) > 1:
            tags_compostas += 1
        for i in calculado:
            contagem_b[i] += 1
        if calculado != esperado:
            div_b.append({'id': musica.id_unico_musica, 'tag': esperado,
                          'calc': calculado, 'cifra': ';'.join(musica.cifra)})
    relata('[B] musica.cifra x musica.seqs_famosas (runtime)', total_b, div_b, contagem_b, limite)
    print('  tags com mais de um índice em seqs_famosas: %d' % tags_compostas)
    print('  (o runtime testa "str(i) in seqs_famosas", então uma tag composta não casa com nada)')
    print()

    ok = not div_a and not div_b
    print('RESULTADO: %s' % ('regra reproduz as tags em todas as comparações'
                             if ok else 'há divergências entre a regra e as tags'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
