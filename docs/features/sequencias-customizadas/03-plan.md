# Plano — Sequências de Acordes Customizadas

> Esta fase produz apenas o plano. Nenhum arquivo de código é alterado aqui.
> Se a implementação mudar de rumo, este documento deve ser atualizado antes de
> continuar.

## Contexto Atual

- O backend é um único `main.py` Flask que carrega `data/top/dataset_final.csv`
  em memória no import; não há banco, ORM, migração, cache ou serviço externo
  (`main.py:49-98`).
- As 6 sequências famosas são um dicionário hardcoded em `main.py:40-45`; a
  busca apenas verifica se o índice está na tag pré-computada
  `musica.seqs_famosas`, vinda da coluna `SEQ_FAMOSA` do CSV
  (`main.py:190-223`).
- O frontend `#/porsequencia` tem 4 sequências hardcoded em
  `static/assets/js/controllers/sequencia.js:2-37`, um subconjunto das 6 do
  backend, sem sincronização.
- A regra que gerou `SEQ_FAMOSA` já foi validada contra a base real: bloco
  contíguo na ordem exata + conjunto de acordes da música contido no conjunto da
  sequência, comparando em minúsculas, com 0 divergências
  (`artifacts/verifica_matching.py`, `research/algoritmo-de-matching.md`).
- Todos os endpoints devolvem `json.dumps(...)` como string, com
  `Content-Type: text/html`, inclusive erros; isso é comportamento legado e não
  será alterado.
- O deploy é Docker local-only, container único, documentado no
  `docs/adr/0001-local-only-docker-deploy.md`; o `Dockerfile:12` hoje não fixa
  número de workers.
- A proposta escolhida está em `02-proposal.md` e a decisão de persistência em
  `docs/adr/0002-persist-custom-sequences.md`: SQLite para o catálogo de
  sequências, CSV em memória para músicas/gêneros, bitset em memória para o
  matching.
- Não há suíte de testes, CI, linter nem `pytest`/`tox` no repositório.

### Escopo e premissas

- Entra: catálogo persistido, cadastro anônimo, busca por sequência, frontend e
  operação Docker.
- Não entra: edição/remoção de sequências, contas/moderação, múltiplos workers,
  transposição/enarmonia, migração de músicas/gêneros para o banco, mudança do
  formato de resposta ou modernização do AngularJS.
- Sem prazo externo informado; as estimativas abaixo são de trabalho contínuo
  (1 dia ≈ 6 h) e servem para ordenar as fases, não como compromisso.
- O setup suportado continua single-worker e local-only. Estado em memória
  (índice, cache, rate limit) é por processo.

## Requisitos

### Requisitos Funcionais

- `GET /sequencias` devolve o catálogo real: 6 seeds com IDs 0–5 e as
  customizadas em ordem de cadastro, sem campo `nome`.
- `POST /sequencias` cadastra uma lista ordenada de acordes anonimamente;
  retorna `201` para sequência nova e `200` com o ID existente para duplicata
  normalizada.
- `GET /similares?sequencia_id=<id>` busca músicas pela sequência cadastrada,
  mantendo os 9 campos, a paginação de 100 e a ordem atuais.
- `GET /similares?sequencia=<...>` continua funcionando como alias legado,
  inclusive para as grafias antigas (`BmGDA`, `CA7,Dm,G7`).
- As 6 sequências originais continuam produzindo exatamente os mesmos conjuntos
  de músicas de hoje: 199, 296, 4, 5, 7 e 3 músicas para os IDs 0–5.
- A página `#/porsequencia` lê o catálogo do backend, permite cadastrar uma
  sequência nova, sugere acordes da paleta e busca por `sequencia_id`.
- A sequência cadastrada sobrevive a `docker restart` e a `docker rm` +
  `docker run` com o mesmo volume nomeado.

### Requisitos Não Funcionais

- Sem nova dependência de runtime: SQLite via `sqlite3` da stdlib.
- Startup continua carregando o CSV e calcula apenas as 6 seeds; acréscimo
  esperado de ~1 s, não dezenas de segundos.
- Memória adicional limitada: ~8,25 KiB por bitset; 506 sequências ≈ 4,1 MiB,
  além do mapa de posições (alguns MB).
- Busca por sequência continua O(n) sobre a coleção filtrada por gênero, sem
  recalcular o matching a cada requisição.
- Compatibilidade: `json.dumps`, `Content-Type: text/html`, paginação, filtro
  por gênero e precedência de parâmetros preservados.
- Catálogo aberto e anônimo, com anti-abuso proporcional ao deploy local.
- Operação em um único worker do gunicorn; `--workers 1` explícito.

## Decisões de Design

### 1. Algoritmo de matching

Será usada a regra legada, sem alterações:

```text
casa(cifra C, sequência S) =
    len(S) <= len(C)
    e set(C) ⊆ set(S)
    e existe i tal que C[i : i + len(S)] == S
```

- Fonte da ordem e das repetições: `musica.cifra`, nunca `musica.acordes`, que é
  `list(set(cifra))` e perde ordem (`musica.py:17`).
- Comparação apenas com `strip().lower()`; sem transposição, enarmonia
  (`C#` ≠ `Db`), baixo invertido (`C/G` ≠ `C`), simplificação de sufixo
  (`C7` ≠ `C`) ou normalização por graus.
- Repetições fora do bloco que casa são permitidas; a sequência pode começar em
  qualquer ponto da música.
- `musica.seqs_famosas` deixa de ser lido na busca e fica apenas como oráculo de
  regressão.
- Lista vazia é rejeitada no cadastro; `casa` também devolve `False` para
  sequência vazia.

### 2. Persistência

SQLite da stdlib, arquivo único, sem serviço externo.

- Caminho via `DECIFRAME_DB`: `/data/deciframe.db` na imagem e
  `./var/deciframe.db` localmente quando a variável não existe.
- `CREATE TABLE IF NOT EXISTS`, `PRAGMA user_version = 1` e
  `INSERT OR IGNORE` para as seeds; inicialização idempotente.
- `PRAGMA journal_mode=WAL`, `busy_timeout` e uma conexão por operação, sempre
  com SQL parametrizado.
- As 6 seeds são imutáveis e usam IDs fixos 0–5; customizadas começam em 6.
- Não há `nome`; o rótulo é a própria lista de acordes.
- Backup é responsabilidade do operador (parar o container ou usar
  `VACUUM INTO`).

### 3. Índice de matching em memória

Um `bytearray` (bitset) por sequência, com 1 bit por música.

- Mapa único `id_unico_musica -> posição` construído uma vez a partir da ordem
  global de `musicas`; usado para testar o bit em qualquer coleção filtrada.
- Seeds calculadas eagerly no startup; customizadas vindas do banco calculadas
  lazily na primeira busca e cacheadas por `id_seq`.
- Sequência recém-cadastrada é calculada no próprio `POST`, para a primeira
  busca já ser rápida.
- Cache e rate limit usam lock; o cálculo pesado fica fora do lock. Se duas
  requisições calcularem a mesma sequência, o resultado é idempotente.
- Alternativa descartada: `set` de IDs por sequência, cujo tamanho depende do
  número de matches; o bitset tem tamanho fixo e previsível.

### 4. API e compatibilidade

- Forma canônica de busca: `GET /similares?sequencia_id=<id>`.
- O alias `?sequencia=` é resolvido em duas etapas: primeiro a chave legada sem
  vírgulas (`BmGDA`, `CA7DmG7`, ...); depois a lista normalizada por
  `strip().lower()`.
- Precedência: `?acordes=` > `?id_unico_musica=` > `?sequencia_id=` >
  `?sequencia=`.
- `sequencia_id` inválido, não numérico ou inexistente retorna `[]` com HTTP
  200, preservando o comportamento atual de sequência desconhecida.
- Duplicata é verificada antes do teto de 500; com catálogo cheio, cadastrar
  sequência existente continua retornando `200`.
- Não há `PUT` nem `DELETE`; as seeds não podem ser alteradas.

### 5. Frontend

- `#/porsequencia` deixa de ter a lista hardcoded e passa a carregar
  `GET /sequencias` no controller.
- Cada acorde é adaptado para o formato do `df-hex`:
  `{acorde: "Bm", cor: "#..."}`; a cor vem de um mapa fixo por nota raiz, com
  fallback.
- Campo de texto aceita vírgula e/ou espaço, remove tokens vazios e preserva a
  ordem digitada; a dica “2 a 8 acordes” é só de UI.
- A paleta curada de `acordes.js` é usada apenas como sugestão (chips); o campo
  continua livre para qualquer acorde.
- `POST /sequencias` é disparado com `{acordes: [...]}`; a UI trata `201`,
  `200`, `400` e `429`.
- Busca passa a usar `sequencia_id`; o restante do fluxo (progressbar, esfige,
  `orderBy:'-popularidade'`, abrir cifra) continua igual.
- `ng-hide="music.diferenca.length"` em `static/templates/sequencia.html:43`
  será removido ou trocado por
  `ng-hide="music.diferenca && music.diferenca.length"`, porque a resposta de
  sequência não tem `diferenca`.

### 6. Anti-abuso

- Rate limit em memória: 10 `POST /sequencias` por minuto por
  `request.remote_addr`, com `429` e `Retry-After`.
- Teto de 500 customizadas; seeds não contam; duplicata continua `200`.
- `MAX_CONTENT_LENGTH = 16 * 1024`, com `413` para excesso.
- Sem edição/remoção; acordes exibidos por interpolação Angular (`{{ }}`), que
  escapa HTML.
- O rate limit é uma barreira proporcional ao escopo local-only, não uma solução
  completa de segurança pública.

## Desenho Técnico

### 1. Componentes Principais

```python
# matching.py
from typing import List

def casa(cifra: List[str], acordes: List[str]) -> bool:
    """Regra legada: bloco contíguo na ordem exata + conjunto fechado."""

def construir_bitset(musicas, posicoes: dict, acordes: List[str]) -> bytearray:
    """Um bit por música, na ordem global de `musicas`."""

class IndiceSequencias:
    def __init__(self, musicas) -> None: ...
    def obter(self, id_seq: int, acordes: List[str]) -> bytearray: ...
    def contem(self, id_seq: int, id_unico_musica: str) -> bool: ...
```

```python
# sequencias_store.py
from dataclasses import dataclass
from typing import List, Optional, Tuple

@dataclass(frozen=True)
class Sequencia:
    id: int
    acordes: List[str]
    origem: str
    criado_em: str

class CatalogoSequencias:
    def __init__(self, caminho: str) -> None: ...
    def listar(self) -> List[Sequencia]: ...
    def obter(self, id_seq: int) -> Optional[Sequencia]: ...
    def buscar_por_chave(self, acordes: List[str]) -> Optional[Sequencia]: ...
    def criar(self, acordes: List[str]) -> Tuple[Sequencia, bool]: ...
    def contar_customizadas(self) -> int: ...
```

- `main.py` permanece como ponto de entrada e dono das rotas; importa os dois
  módulos novos e inicializa catálogo + índice depois da carga do CSV.
- `musica.py` não precisa mudar: `cifra`, `acordes` e `seqs_famosas` continuam
  como estão.

### 2. Modelos de Dados

```sql
CREATE TABLE IF NOT EXISTS sequencias (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  acordes   TEXT NOT NULL,          -- JSON array; ordem e repetições preservadas
  chave     TEXT NOT NULL UNIQUE,   -- JSON normalizado (strip + lower)
  origem    TEXT NOT NULL CHECK (origem IN ('original', 'customizada')),
  criado_em TEXT NOT NULL           -- ISO 8601 UTC
);
```

- `acordes`: `json.dumps([a.strip() for a in tokens])`, preservando caixa, ordem
  e repetições.
- `chave`: `json.dumps([a.strip().lower() for a in tokens])`; a mesma função é
  usada no cadastro e na busca por duplicata.
- Seeds: `0 = Bm,G,D,A`; `1 = C,G,Am,F`; `2 = Em,G`; `3 = C,A7,Dm,G7`;
  `4 = Gm,F`; `5 = C,C7,F,Fm`.
- `AUTOINCREMENT` deve começar em 6 depois das seeds; isso será coberto por
  teste.

### 3. Pontos de Integração

| Rota | Entrada | Sucesso | Erros previstos |
|---|---|---|---|
| `GET /sequencias` | — | `200` com lista ordenada por `id` | — |
| `POST /sequencias` | JSON `{"acordes": [...]}` | `201` novo / `200` duplicata | `400`, `413`, `429` |
| `GET /similares?sequencia_id=` | `sequencia_id`, `generos`, `pagina` | `200` com página de músicas | `[]` para id inválido/inexistente |
| `GET /similares?sequencia=` | lista ou chave legada | `200` com página de músicas | `[]` para chave desconhecida |

- Fluxo de cadastro: rate limit → parse/validação → duplicata → teto → insert →
  cálculo do bitset → resposta.
- Fluxo de busca: resolve `id_seq` → obtém bitset (lazy se necessário) → percorre
  `apply_filtro(musicas.values(), generos_key)` na ordem atual → testa o bit →
  pagina com `get_pagina`.
- Respostas de erro também usam `json.dumps`; `413` precisa de
  `@app.errorhandler(413)` para não vazar o HTML padrão do Flask.

### 4. Arquivos Afetados

Ver a tabela em [Arquivos afetados](#arquivos-afetados). Nenhum outro arquivo
deve ser alterado nesta feature.

## Passos

### Fase 1 — Fundação de matching e persistência

- [ ] Criar `matching.py` com `casa`, `construir_bitset` e `IndiceSequencias`
  (mapa de posições, cache, lock).
- [ ] Criar `sequencias_store.py` com resolução de `DECIFRAME_DB`, schema,
  seeds, normalização de chave, listagem, busca, criação idempotente e contagem
  de customizadas.
- [ ] Criar `tests/test_matching.py` cobrindo ordem, contiguidade, conjunto
  fechado, caixa, repetições, lista vazia e ausência de transposição.
- [ ] Criar `tests/test_sequencias_store.py` cobrindo seeds, dedupe, chave,
  `AUTOINCREMENT` em 6, teto e reabertura do arquivo.
- Estimativa: 0,5–1 dia.

### Fase 2 — API no `main.py`

- [ ] Inicializar `CatalogoSequencias` e `IndiceSequencias` após a carga do CSV;
  calcular as seeds 0–5 eagerly.
- [ ] Adicionar `GET /sequencias` e `POST /sequencias` mantendo `json.dumps`.
- [ ] Substituir o branch de sequência em `/similares` por bitset; adicionar
  `sequencia_id` e manter o alias `sequencia` com a resolução em duas etapas.
- [ ] Configurar `MAX_CONTENT_LENGTH`, `@app.errorhandler(413)` e o rate limiter
  com `429` + `Retry-After`.
- [ ] Rodar `artifacts/verifica_matching.py` e um teste novo que compare a API
  das 6 seeds com as tags do CSV.
- Estimativa: 1 dia.

### Fase 3 — Frontend `#/porsequencia`

- [ ] Reescrever `sequencia.js` para carregar `GET /sequencias`, montar a paleta
  de cores, cadastrar via `POST /sequencias` e buscar por `sequencia_id`.
- [ ] Adicionar ao template o campo de cadastro, a dica “2 a 8 acordes”, as
  sugestões e as mensagens de sucesso/duplicata/erro/limite.
- [ ] Corrigir o `ng-hide` que depende de `music.diferenca`.
- [ ] Testar manualmente no browser: listar seeds, cadastrar, duplicar, buscar,
  filtrar por gênero e abrir cifra.
- Estimativa: 0,5–1 dia.

### Fase 4 — Deploy e operação

- [ ] Atualizar `Dockerfile` com `ENV DECIFRAME_DB=/data/deciframe.db`,
  `RUN mkdir -p /data`, `VOLUME ["/data"]` e `--workers 1`.
- [ ] Adicionar `var/`, `*.db`, `*.db-wal`, `*.db-shm` a `.gitignore` e
  `.dockerignore`.
- [ ] Atualizar `README.md` e `AGENTS.md` com o `docker run -v
  deciframe-data:/data`, o caminho local do banco, o worker único e o backup.
- [ ] Validar que montar volume em `/app/data` não é feito em nenhum comando
  documentado.
- Estimativa: 0,25 dia.

### Fase 5 — Testes e fechamento

- [ ] Criar testes de integração com `Flask.test_client` para `GET/POST
  /sequencias`, `sequencia_id`, alias, precedência, paginação, `400/413/429` e
  `Content-Type`.
- [ ] Criar teste de persistência: cadastrar, fechar/reabrir o banco e verificar
  que a sequência continua disponível.
- [ ] Rodar smoke test no Docker: `/generos`, `/sequencias`, cadastro, busca,
  `docker restart` e `docker rm` + `docker run` com o mesmo volume.
- [ ] Preencher `04-test-report.md` com cobertura, comando exato e resultado da
  regressão.
- Estimativa: 0,5 dia.

Tempo total estimado: **2,75–3,75 dias**.

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `main.py` | Inicializa catálogo/índice; adiciona `GET/POST /sequencias`; troca a busca por sequência para bitset; adiciona `sequencia_id`, alias legado, `MAX_CONTENT_LENGTH`, `413` e rate limit. |
| `musica.py` | Nenhuma alteração prevista; `cifra`/`acordes`/`seqs_famosas` continuam como estão. |
| `sequencias_store.py` (novo) | Acesso ao SQLite, schema, seeds, normalização de chave, dedupe, listagem, criação e contagem. |
| `matching.py` (novo) | Regra `casa`, construção de bitset e `IndiceSequencias` com posições, cache e lock. |
| `static/assets/js/controllers/sequencia.js` | Remove as 4 sequências hardcoded; carrega o catálogo, cadastra, sugere acordes e busca por `sequencia_id`. |
| `static/templates/sequencia.html` | Adiciona formulário/dica/sugestões/mensagens; corrige o `ng-hide` de `diferenca`. |
| `Dockerfile` | `/data`, `ENV DECIFRAME_DB`, `VOLUME` e `--workers 1`. |
| `.gitignore` | Ignora `var/`, `*.db`, `*.db-wal`, `*.db-shm`. |
| `.dockerignore` | Ignora `var/`, `*.db`, `*.db-wal`, `*.db-shm`. |
| `README.md` | Comando com volume nomeado, persistência, worker único e backup. |
| `AGENTS.md` | Atualiza gotchas de execução, banco local e volume. |
| `tests/test_matching.py` (novo) | Testes unitários da regra e do bitset. |
| `tests/test_sequencias_store.py` (novo) | Testes unitários do catálogo SQLite. |
| `tests/test_api_sequencias.py` (novo) | Testes de integração da API, regressão das 6 seeds e persistência. |
| `docs/features/sequencias-customizadas/04-test-report.md` | Preenchido na Fase 5 com cobertura e resultado da regressão. |
| `docs/adr/0002-persist-custom-sequences.md` | Já registra a decisão; apenas conferir, sem reescrever. |
| `artifacts/verifica_matching.py` | Sem alteração; continua sendo o oráculo de regressão. |

## Riscos e mitigação

| Risco | Como perceber | Mitigação |
|---|---|---|
| Startup mais lento pelas seeds eager | Medir tempo de import antes/depois; meta ~+1 s | Calcular só as 6 seeds; customizadas lazy; medir e registrar no teste |
| Volume montado em `/app/data` esconde o CSV | `FileNotFoundError` no import; `/generos` falha | Volume sempre em `/data`; documentar explicitamente no README/AGENTS |
| Estado por processo quebra com múltiplos workers | Cache/rate limit inconsistentes entre workers | Fixar `--workers 1`; documentar que `WEB_CONCURRENCY` não é suportado |
| Divergência na regra de matching | Teste de regressão com divergências ≠ 0 | Usar a regra validada em `artifacts/verifica_matching.py`; manter `seqs_famosas` só como oráculo |
| `413`/`429` saindo como HTML padrão do Flask | Resposta sem JSON e `Content-Type` diferente | `errorhandler(413)` e respostas de erro com `json.dumps`; testar status e corpo |
| Corrida no cache/rate limit | Cálculo duplicado ou contador inconsistente | Lock no cache/contador; cálculo pesado fora do lock; resultado idempotente |
| ID da primeira customizada não começa em 6 | Teste de `AUTOINCREMENT` falha | Teste explícito; ajustar `sqlite_sequence` apenas se necessário |
| Corpo grande ou JSON malformado | `400`/`413` inesperado | `get_json(silent=True)` + validação explícita; `MAX_CONTENT_LENGTH`; testes |
| Cache do browser servindo JS antigo | Página ainda mostra 4 sequências | Hard refresh no teste manual; sem build step, não há cache-busting automático |
| Permissão do arquivo SQLite no volume | Erro de `sqlite3` ao abrir/gravar | `mkdir -p /data` na imagem; testar `docker run` com volume nomeado |
| Primeira busca de customizada lenta | Delay de ~0,1–0,4 s após restart | Calcular no `POST`; lazy com progressbar; documentar como limitação |
| `replace('NA', '')` continua corrompendo nomes | Não é regressão desta feature | Não alterar a carga do CSV neste escopo; registrar como dívida separada |

## Estratégia de Testes

### Testes Unitários

- `casa`:
  - bloco contíguo na ordem exata;
  - ordem trocada não casa;
  - acorde fora do conjunto da sequência não casa;
  - caixa diferente casa;
  - repetição dentro do bloco quebra a ocorrência;
  - sequência vazia não casa;
  - sequência maior que a cifra não casa;
  - `C#` não equivale a `Db`, `C/G` não equivale a `C`, `C7` não equivale a
    `C`.
- `construir_bitset`/`IndiceSequencias`: posição correta, bit ligado/desligado,
  cache hit, cálculo concorrente idempotente.
- `sequencias_store`: normalização de `chave`, dedupe com caixa/espaço, seeds,
  `AUTOINCREMENT` em 6, teto de 500, reabertura do banco.
- Estratégia de mock: usar banco em diretório temporário; não mockar o CSV nos
  testes de matching (a base real é o oráculo).

### Testes de Integração

- `Flask.test_client` com `DECIFRAME_DB` apontando para arquivo temporário.
- `GET /sequencias`: 6 seeds, IDs 0–5, listas exatas, ordem.
- `POST /sequencias`: `201` novo; `200` duplicata; `200` duplicata de seed;
  `400` vazio/branco/JSON inválido; `413` acima de 16 KB; `429` no teto e no
  rate limit.
- `GET /similares?sequencia_id=i`: para cada seed, somar as páginas e comparar
  com as tags do CSV; contagens 199, 296, 4, 5, 7 e 3.
- Alias `?sequencia=`: `Bm,G,D,A`, `BmGDA`, `CA7,Dm,G7`, `C, G, Am, F`,
  `c,g,am,f` e `X,Y`.
- Precedência de `acordes`/`id_unico_musica`/`sequencia_id`/`sequencia`.
- Paginação, filtro por gênero e `Content-Type: text/html` em sucesso e erro.
- Persistência: criar sequência, fechar e reabrir o catálogo, buscar de novo.
- Rate limit: limitador injetável ou resetável para não depender de 10 POSTs
  reais por teste; usar `remote_addr` controlado.
- Cobertura esperada: todos os caminhos novos de `matching.py`,
  `sequencias_store.py` e das rotas; não há meta percentual rígida, mas os
  status `400/413/429` e a regressão das seeds são obrigatórios.

## Segurança

- Catálogo aberto e anônimo por requisito; não há login, conta ou painel
  administrativo.
- SQL sempre parametrizado; nenhuma interpolação de string com entrada do
  usuário.
- Acordes exibidos via `{{ }}` do Angular, que escapa HTML; não usar
  `ng-bind-html` para conteúdo cadastrado.
- Rate limit de 10 POSTs/min por IP, teto de 500 customizadas e corpo máximo de
  16 KB; `429`/`413` coerentes.
- Sem `PUT`/`DELETE`, reduzindo a superfície de abuso.
- Limitações: o rate limit é por processo, em memória, e usa `remote_addr`, que
  pode ser impreciso atrás de proxy; isso é aceitável no deploy local-only.
- O `Access-Control-Allow-Origin: *` existente em `main.py:274-277` permanece;
  não é ampliado nem removido neste escopo.
- O arquivo SQLite fica em volume fora de `/app`; backup e permissão são
  responsabilidade do operador.

## Rollout

1. **Desenvolvimento:** fases 1–3 em branch local; rodar testes unitários e de
   integração.
2. **Teste local:** `python main.py` com `DECIFRAME_DB=./var/deciframe.db`;
   validar `/generos`, `/sequencias`, cadastro, busca e persistência após
   reiniciar o processo.
3. **Build da imagem:** `docker build -t ciframe .`; subir com volume nomeado:
   `docker run --name deciframe -p 8080:8080 -v deciframe-data:/data ciframe`.
4. **Smoke test no container:** cadastrar uma sequência, buscar, reiniciar com
   `docker restart deciframe` e repetir; depois `docker rm -f deciframe` +
   mesmo `docker run` e confirmar que a sequência continua.
5. **Monitoramento manual:** conferir tempo de startup, memória do processo,
   ausência de erro no log do gunicorn e resposta das 6 seeds.
6. **Rollback:** parar/remover o container e subir a imagem anterior; o volume
   `/data` é inofensivo para a versão antiga, que não o lê. Não há migração de
   dados de produção a desfazer.
7. **Observação:** não há staging nem alvo de nuvem; o rollout é local-only,
   conforme o ADR 0001.

## Observabilidade

Não se aplica a este escopo: o app não tem logging estruturado, métricas,
alertas ou tracing hoje, e a feature não introduz nenhum desses elementos. A
verificação é feita por testes automatizados e smoke test manual no Docker.

## Considerações Futuras

### Melhorias Potenciais

- Suporte a múltiplos workers: compartilhar cache/rate limit e persistir bitsets
  com versionamento do dataset.
- Pré-computação em background das customizadas, para eliminar o custo da
  primeira busca.
- Campo `nome` e curadoria/moderação, se o catálogo deixar de ser local-only.
- Endpoints de edição/remoção e painel administrativo.
- Observabilidade real (logs, métricas de tempo de busca e memória).
- Migrações versionadas com `PRAGMA user_version` além da versão 1.
- Backup automatizado do volume.

### Limitações Conhecidas

- Índice, cache e rate limit são por processo; o setup é single-worker.
- SQLite é um único escritor; leituras concorrentes são baratas, escritas não.
- Matching não faz transposição, enarmonia, baixo invertido, simplificação de
  sufixo nem normalização por graus.
- Não há edição/remoção nem `nome`; as seeds são imutáveis.
- Rate limit reseta no restart e não é compartilhado.
- A primeira busca de uma customizada após restart custa ~0,1–0,4 s.
- Frontend legado AngularJS 1.4.9 sem build step, sem cache-busting automático.
- O CSV continua sendo lido uma vez no import; editar
  `data/top/dataset_final.csv` exige restart.

## Dependências

- Runtime: nenhuma nova; `sqlite3`, `json`, `datetime` e `threading` são da
  stdlib.
- Dev: nenhuma nova se os testes usarem `unittest` da stdlib; o comando previsto
  é `python -m unittest discover -s tests -v`.
- Ferramentas: Docker para o smoke test; `curl` para verificação manual.
- Documentação externa: docs do `sqlite3` (Python 3.9) e do Flask 3.1 para
  `MAX_CONTENT_LENGTH`/`errorhandler`.

## Definição de pronto

- [ ] `GET /generos` continua retornando um array JSON, sem regressão no
  startup.
- [ ] `GET /sequencias` retorna as 6 seeds com IDs 0–5 e as listas exatas
  `Bm,G,D,A`; `C,G,Am,F`; `Em,G`; `C,A7,Dm,G7`; `Gm,F`; `C,C7,F,Fm`.
- [ ] Para cada seed `i`, somando as páginas de `GET /similares?sequencia_id=i`,
  o conjunto é idêntico ao da tag `i` do CSV: 199, 296, 4, 5, 7 e 3 músicas.
- [ ] `?sequencia=Bm,G,D,A`, `?sequencia=BmGDA`, `?sequencia=CA7,Dm,G7` e
  `?sequencia=C, G, Am, F` continuam funcionando e retornam os mesmos conjuntos
  das seeds correspondentes.
- [ ] `POST /sequencias` com lista nova retorna `201`, grava a linha, aparece em
  `GET /sequencias` e fica buscável por `sequencia_id` e pelo alias.
- [ ] Cadastrar a mesma sequência de novo, inclusive com caixa/espaço
  diferentes, retorna `200` com o mesmo ID e não cria linha duplicada.
- [ ] Cadastrar uma sequência igual a uma seed retorna `200` com o ID da seed.
- [ ] Lista vazia ou só com tokens em branco retorna `400`; 1 acorde é aceito;
  9 acordes são aceitos; não há mínimo/máximo rígido.
- [ ] Teto de 500 customizadas retorna `429` para cadastro novo, mas duplicata
  continua `200`; rate limit de 10 POSTs/minuto por IP retorna `429` com
  `Retry-After`.
- [ ] Corpo acima de 16 KB retorna `413`.
- [ ] Todas as respostas, inclusive `400`/`413`/`429`, continuam sendo
  `json.dumps(...)` com `Content-Type: text/html`.
- [ ] Sequência customizada sobrevive a `docker restart` e a `docker rm` +
  `docker run` com o mesmo volume nomeado; volume vazio inicializa as seeds sem
  duplicar.
- [ ] Frontend lista seeds e customizadas, permite cadastrar, mostra a dica
  “2 a 8 acordes”, usa a paleta só como sugestão, seleciona a sequência
  retornada e exibe mensagens de duplicata/erro/limite.
- [ ] O `ng-hide` de `static/templates/sequencia.html` não esconde mais
  resultados por causa de `music.diferenca` ausente.
- [ ] Não existe campo `nome` no banco, na API ou na UI; o rótulo é a lista de
  acordes.
- [ ] `artifacts/verifica_matching.py` continua passando com 0 divergências e o
  teste novo compara a API das 6 seeds com as tags do CSV.
- [ ] Com 500 customizadas, o custo adicional dos bitsets fica em ~4,1 MiB além
  do mapa de posições, e o startup calcula apenas as 6 seeds.
- [ ] A primeira busca de uma customizada vinda do banco pode custar ~0,1–0,4 s;
  as seguintes não recalculam.
- [ ] `Dockerfile`, README e AGENTS documentam `/data`, o volume nomeado, o
  worker único e o backup; nada monta volume em `/app/data`.

## Referências

- `docs/features/sequencias-customizadas/00-enunciado.md`
- `docs/features/sequencias-customizadas/01-research.md`
- `docs/features/sequencias-customizadas/02-proposal.md`
- `research/entendimento-do-repositorio.md`
- `research/algoritmo-de-matching.md`
- `research/bancos-embarcados-docker.md`
- `artifacts/verifica_matching.py`
- `docs/adr/0001-local-only-docker-deploy.md`
- `docs/adr/0002-persist-custom-sequences.md`
- `docs/adr/0003-lift-frontend-freeze.md`
- `main.py:11-23`, `main.py:40-45`, `main.py:49-98`, `main.py:170-223`,
  `main.py:226-228`, `main.py:266-277`
- `musica.py:1-25`
- `static/assets/js/controllers/sequencia.js:1-105`
- `static/templates/sequencia.html:1-63`
- `static/assets/js/controllers/acordes.js:1-53`
- `Dockerfile:1-12`, `.gitignore:1-4`, `.dockerignore:1-4`
- `README.md:11-31`, `AGENTS.md`
