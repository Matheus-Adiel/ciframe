# Proposta 1 — Catálogo em SQLite + índice de matching em memória

> **Documento de registro.** Este é o texto atualizado da Proposta 1, a
> abordagem escolhida em 2026-11-05. O conteúdo canônico e mantido é
> [`docs/features/sequencias-customizadas/02-proposal.md`](../docs/features/sequencias-customizadas/02-proposal.md);
> este arquivo preserva o texto da proposta submetida para decisão.

## Abordagem escolhida

A proposta escolhida é a **Proposta 1: catálogo de sequências em SQLite + índice de
matching em memória**. O banco guarda apenas o catálogo de sequências (as 6
originais e as cadastradas por visitantes). O catálogo de músicas e gêneros
continua vindo de `data/top/dataset_final.csv`, carregado uma vez no import de
`main.py`, como hoje.

A ideia central é separar três coisas que hoje estão misturadas:

1. **Definição** da sequência: lista ordenada de acordes, persistida no SQLite.
2. **Cálculo** de quais músicas casam com a sequência: feito uma vez por
   sequência, com a regra legada, e guardado em um bitset em memória.
3. **Consulta**: para cada busca, percorre-se a coleção já filtrada por gênero e
   testa-se o bit correspondente à música. Não há recálculo por requisição.

Resumo das decisões:

| Tema | Decisão |
|---|---|
| Banco | SQLite da stdlib, arquivo único, sem serviço externo |
| Matching | regra legada: bloco contíguo na ordem exata + conjunto fechado |
| Índice | um `bytearray` (bitset) por sequência, um bit por música |
| Seeds | 6 originais com IDs 0–5; customizadas a partir do ID 6 |
| API | `GET /sequencias`, `POST /sequencias`, `GET /similares?sequencia_id=...` |
| Compatibilidade | `?sequencia=...` continua funcionando como alias |
| Duplicata | HTTP 200 com o ID existente; cadastro novo retorna 201 |
| Validação | rejeita lista vazia; sem mínimo/máximo rígido; dica de UI “2 a 8 acordes” |
| Anti-abuso | limite por IP, teto de 500 customizadas e corpo de 16 KB |
| Deploy | volume `/data` para o SQLite e um único worker do gunicorn |

## Algoritmo de matching

O algoritmo é exatamente a regra que já gerou a coluna `SEQ_FAMOSA` no CSV
(`scripts/generate_data_set.py:7-24`). Para uma sequência `S` e uma música com
cifra `C`, ambas listas de tokens:

```
C = [t.lower() for t in musica.cifra]
S = [t.strip().lower() for t in sequencia.acordes]

match(S, C) =
    len(S) <= len(C)
    e set(C) ⊆ set(S)
    e existe i tal que C[i : i + len(S)] == S
```

Em palavras: a sequência precisa aparecer como um **bloco contíguo, na ordem
exata**, em algum ponto da cifra, e a música inteira só pode usar acordes que
pertencem ao conjunto da sequência. A comparação é **case-insensitive** apenas
por `lower()`; não há transposição, equivalência enarmônica (`C#` ≠ `Db`),
redução de baixo invertido (`C/G` ≠ `C`), simplificação de sufixo (`C7` ≠ `C`) nem
normalização por graus.

Detalhes importantes:

- A fonte da ordem e das repetições é `musica.cifra`, não `musica.acordes`.
  `musica.acordes` é `list(set(cifra))` (`musica.py:17`) e perde ordem e
  repetição; usá-lo mudaria a semântica.
- A condição de conjunto é implementada como “todo token de `C` pertence a
  `set(S)`”, o que é equivalente a `set(C) ⊆ set(S)` e evita construir um `set`
  novo por música.
- Repetições fora do bloco que casa são permitidas; uma repetição dentro do
  bloco quebra aquela ocorrência específica. A sequência não precisa começar no
  primeiro acorde da música.
- Listas vazias são rejeitadas no cadastro (`400`), então não existe o caso de
  sequência vazia casando com tudo.
- O campo `musica.seqs_famosas` continua sendo carregado do CSV, mas **não é
  mais lido na busca**. Ele fica apenas como oráculo de regressão: o teste
  compara o índice calculado com as tags gravadas e exige 0 divergências.

Validação da hipótese na base real: a regra reproduziu as 67.585 tags do CSV com
0 divergências (`artifacts/verifica_matching.py`). As contagens por sequência
original são 0 → 199, 1 → 296, 2 → 4, 3 → 5, 4 → 7 e 5 → 3. Esses números são o
critério de regressão da feature.

## Banco de dados

**SQLite**, pelo módulo `sqlite3` da stdlib. É a opção de menor custo para este
problema:

- não adiciona nenhuma dependência ao `requirements.txt` nem à imagem;
- é um arquivo único, com transações ACID e constraint `UNIQUE`, o que resolve
  deduplicação sem código extra;
- cabe no container único e local-only do
  [ADR 0001](../docs/adr/0001-local-only-docker-deploy.md), sem porta, daemon ou
  container auxiliar;
- o volume de dados é minúsculo (centenas de linhas), e o padrão de acesso é
  “muitas leituras, pouquíssimas escritas”, que é o caso de uso canônico do
  SQLite.

O caminho do banco vem da variável `DECIFRAME_DB`:

- no Docker: `/data/deciframe.db` (padrão da imagem);
- local, sem Docker: `./var/deciframe.db`, relativo à raiz do projeto.

O Dockerfile passa a criar `/data`, declará-lo como volume e expor a variável:

```dockerfile
ENV DECIFRAME_DB=/data/deciframe.db
RUN mkdir -p /data
VOLUME ["/data"]
```

O `docker run` documentado passa a usar um volume nomeado:

```bash
docker run --name deciframe -p 8080:8080 \
  -v deciframe-data:/data ciframe
```

**Nunca montar volume em `/app/data`**: isso esconderia o CSV e quebraria o
import de `main.py`. O volume é sempre em `/data` (ou outro diretório fora de
`/app`). Também é preciso adicionar `var/`, `*.db`, `*.db-wal` e `*.db-shm` ao
`.dockerignore` e ao `.gitignore`, para que o banco local não entre no build nem
no Git.

O app continua com **um único worker** do gunicorn. O `CMD` fixa
`--workers 1`, e o README documenta que `WEB_CONCURRENCY`/múltiplos workers não
fazem parte do setup suportado. O índice em memória, o cache e o rate limit são
por processo; suportar múltiplos workers exigiria compartilhar ou recalcular
esses dados, o que está fora do escopo desta feature.

A inicialização é idempotente: `CREATE TABLE IF NOT EXISTS`, `PRAGMA
user_version = 1` e `INSERT OR IGNORE` para as seeds. Um volume vazio se
inicializa sozinho; um volume existente não duplica linhas. O SQLite fica em
modo WAL, com `busy_timeout`, e as conexões são abertas por operação. O banco é
pequeno, mas backup continua sendo responsabilidade do operador: parar o
container antes de copiar ou usar `VACUUM INTO`.

## Esquema de dados (alto nível)

Uma única tabela, sem `nome`:

```sql
CREATE TABLE IF NOT EXISTS sequencias (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  acordes   TEXT NOT NULL,          -- JSON array, ordem e repetições preservadas
  chave     TEXT NOT NULL UNIQUE,   -- JSON normalizado (strip + lower), identidade
  origem    TEXT NOT NULL CHECK (origem IN ('original', 'customizada')),
  criado_em TEXT NOT NULL
);
```

- `acordes` guarda a lista como o usuário digitou (só com `strip` nas pontas),
  preservando caixa, ordem e repetições para exibição e para o matching.
- `chave` é a identidade normalizada: `json.dumps([a.strip().lower() for a in
  acordes])`. `C, G, Am, F`, `c,g,am,f` e `C, G, Am, F ` produzem a mesma chave;
  `C, G` e `G, C` produzem chaves diferentes, porque ordem importa.
- `origem` distingue as 6 seeds (`original`) das cadastradas (`customizada`).
- `criado_em` é um timestamp ISO 8601 em UTC; nas seeds, é o instante da
  primeira inicialização do banco.
- As seeds usam IDs fixos **0–5**, iguais aos índices atuais de `SEQ_FAMOSA`:
  `0 = Bm,G,D,A`, `1 = C,G,Am,F`, `2 = Em,G`, `3 = C,A7,Dm,G7`,
  `4 = Gm,F`, `5 = C,C7,F,Fm`.
- Sequências customizadas começam em **6** (`AUTOINCREMENT`).
- Não há `nome`: o rótulo exibido é a própria lista de acordes. O arquivo
  `data/mapeamento_sequencias_famosas.txt` continua sendo apenas documentação e
  não é lido em runtime.

As 6 originais são imutáveis: não existem endpoints de edição ou remoção. Se um
cadastro novo normalizar para a mesma `chave` de uma seed, a resposta é a seed
existente (HTTP 200), não uma linha nova.

## API

Todos os endpoints continuam retornando `json.dumps(...)` como string, não
`jsonify`; o `Content-Type` continua `text/html`, inclusive nas respostas de
erro.

### `GET /sequencias`

Retorna o catálogo inteiro, ordenado por `id` (seeds primeiro, depois as
customizadas na ordem de cadastro):

```json
[
  {"id": 0, "acordes": ["Bm", "G", "D", "A"], "origem": "original", "criado_em": "..."},
  {"id": 1, "acordes": ["C", "G", "Am", "F"], "origem": "original", "criado_em": "..."},
  {"id": 6, "acordes": ["C", "Am", "F", "G"], "origem": "customizada", "criado_em": "..."}
]
```

O importante é que o frontend recebe a lista real, sem hardcode. Uma customizada
com a mesma `chave` de uma seed não seria criada; a duplicata retornaria a seed.

### `POST /sequencias`

Corpo JSON:

```json
{"acordes": ["C", "G", "Am", "F"]}
```

Respostas:

| Situação | HTTP | Corpo |
|---|---|---|
| Sequência nova | `201` | Objeto da sequência criada, com `id`, `acordes`, `origem`, `criado_em` |
| Duplicata (mesma `chave`) | `200` | Objeto da sequência existente, com o `id` existente |
| Lista vazia ou só tokens em branco | `400` | `{"erro": "informe ao menos um acorde"}` |
| JSON malformado ou tipo inválido | `400` | `{"erro": "corpo inválido"}` |
| Corpo maior que 16 KB | `413` | `{"erro": "corpo da requisição muito grande"}` |
| Rate limit ou teto de 500 customizadas | `429` | `{"erro": "..."}` com `Retry-After` quando for rate limit |

Regras de validação e normalização:

- Aceita qualquer quantidade de acordes; **não há mínimo nem máximo rígido**. A
  dica “2 a 8 acordes” é só de UI. Uma sequência de 1 acorde é válida; uma de 9
  também.
- Tokens em branco são descartados; se não sobrar nenhum, a resposta é `400`.
- Tokens não-string ou corpo que não seja um objeto com a chave `acordes` são
  `400`.
- A ordem e as repetições são preservadas. `C, C, G` é diferente de `C, G`.
- A duplicata é verificada antes do teto: com o catálogo cheio, cadastrar uma
  sequência que já existe continua retornando `200`, não `429`.
- As seeds não podem ser alteradas; não há `PUT` nem `DELETE`.

### `GET /similares?sequencia_id=<id>`

É a forma canônica de busca por sequência. O restante da resposta é idêntico ao
modo atual: lista de músicas com os 9 campos (`id_unico_musica`, `id_artista`,
`id_musica`, `nome_artista`, `nome_musica`, `popularidade`, `acordes`, `genero`,
`url`), paginada em 100 itens por `get_pagina`, sem `diferenca` nem `intersecao`.
`generos` e `pagina` continuam funcionando como hoje.

- `sequencia_id` inválido, inexistente ou não numérico retorna `[]` com HTTP
  200, preservando o comportamento atual de sequência desconhecida (não vira
  erro).
- A ordem da resposta é a mesma de hoje: a coleção filtrada por gênero
  (`apply_filtro`) é percorrida na ordem atual e o bitset só decide se a música
  entra ou não. Paginação e ordenação não mudam.

### `GET /similares?sequencia=<...>` (alias legado)

O parâmetro antigo continua aceito para não quebrar links, scripts e frontend
antigo. A resolução tem duas etapas, nesta ordem:

1. **Chave legada exata**: remove as vírgulas do valor e compara com o mapa
   antigo das 6 originais (`BmGDA`, `CGAmF`, `EmG`, `CA7DmG7`, `GmF`, `CC7FFm`).
   Isso preserva casos estranhos que já funcionavam, como
   `?sequencia=CA7,Dm,G7`, que vira `CA7DmG7` e retorna a seed 3.
2. **Lista normalizada**: se não casar na etapa 1, interpreta o valor como lista
   separada por vírgulas, aplica `strip().lower()` em cada token e procura a
   `chave` no catálogo. Isso faz `?sequencia=C, G, Am, F` e
   `?sequencia=c,g,am,f` funcionarem, inclusive para sequências customizadas.

Exemplos:

| Requisição | Resultado |
|---|---|
| `?sequencia=Bm,G,D,A` | seed 0 |
| `?sequencia=BmGDA` | seed 0 |
| `?sequencia=CA7,Dm,G7` | seed 3 (via chave legada) |
| `?sequencia=C, G, Am, F` | seed 1 (via lista normalizada) |
| `?sequencia=c,g,am,f` | seed 1 (via lista normalizada) |
| `?sequencia=X,Y` | `[]` |

A precedência dos outros modos continua igual: `?acordes=` vence
`?id_unico_musica=`, que vence `?sequencia=`/`?sequencia_id=`. Se
`sequencia_id` e `sequencia` vierem juntos, `sequencia_id` vence.

### Anti-abuso

Como o catálogo é aberto e anônimo, a proposta inclui mitigações simples e
proporcionais ao app local:

- **Duplicata idempotente**: cadastrar de novo a mesma sequência não cria linha
  nova e retorna `200` com o ID existente.
- **Rate limit por IP**: no máximo 10 `POST /sequencias` por minuto por
  `request.remote_addr`, com resposta `429` e `Retry-After`. O contador fica em
  memória, por processo, e reseta no restart; isso é aceitável no deploy
  single-worker e local-only.
- **Teto de 500 customizadas**: quando o catálogo customizado estiver cheio,
  cadastros novos retornam `429`. As 6 seeds não contam. Duplicatas continuam
  retornando `200`.
- **Limite de corpo**: `MAX_CONTENT_LENGTH = 16 * 1024` para evitar payloads
  absurdos; o excesso retorna `413`.
- **Sem edição/remoção**: não há endpoint para alterar ou apagar sequências, o
  que reduz a superfície de abuso.
- **SQL parametrizado**: todos os acessos usam parâmetros, nunca interpolação de
  string. Os acordes são exibidos via interpolação Angular (`{{ }}`), que escapa
  HTML por padrão.

O rate limit é uma primeira barreira, não uma solução de segurança completa. Em
um deploy público de verdade, valeria considerar rate limit compartilhado,
moderação e limites por conta; nada disso é necessário para o escopo local-only
atual.

## Frontend

A página `#/porsequencia` deixa de ter a lista hardcoded de 4 sequências
(`static/assets/js/controllers/sequencia.js:2-37`) e passa a refletir o catálogo
real do backend.

### Catálogo

- No load do controller, `GET /sequencias` popula `vm.sequenciasFamosas`.
- A resposta é adaptada para o formato que o `df-hex` já espera: cada acorde
  vira `{acorde: "Bm", cor: "#..."}`. A cor pode ser derivada da nota raiz com
  um mapa fixo (reaproveitando as cores da paleta de `acordes.js`) e um fallback
  para acordes fora da paleta.
- As 6 seeds aparecem primeiro, seguidas das customizadas. Não há mais
  divergência entre o que o backend conhece e o que a página mostra.
- Se `GET /sequencias` falhar, a página mostra uma mensagem de erro e não inventa
  uma lista local.

### Cadastro

- Um campo de texto novo recebe a sequência, por exemplo `C, G, Am, F` ou
  `C G Am F`. O parser do frontend separa por vírgula e/ou espaço, remove tokens
  vazios e mantém a ordem digitada.
- Ao lado do campo, a dica **“Dica: 2 a 8 acordes”**. É só uma sugestão; o
  frontend não bloqueia 1 nem 9 acordes, e o backend também não.
- A paleta curada de `acordes.js` é usada como **sugestão**: os acordes aparecem
  como chips/datalist e um clique acrescenta o acorde ao fim do campo. O campo
  continua livre para qualquer acorde; a paleta não é allowlist. Para não
  duplicar a lista, ela pode ser extraída para uma constante/serviço Angular
  compartilhado (e incluída no `static/index.html`, já que não há build step).
- Ao enviar, o controller faz `POST /sequencias` com
  `{acordes: ["C", "G", "Am", "F"]}`.
  - `201`: mostra “Sequência cadastrada”, recarrega o catálogo e já seleciona a
    sequência nova.
  - `200`: mostra “Essa sequência já existe” e seleciona a existente.
  - `400`: mostra a mensagem de lista vazia/inválida.
  - `429`: mostra que o limite foi atingido e pede para tentar depois.
- Depois do cadastro (ou de uma duplicata), a busca é disparada automaticamente
  para a sequência retornada.

### Busca

- `pesquisarPorSequencia(sequencia)` passa a montar
  `GET /similares?sequencia_id=<id>` (com `&generos=...` quando houver filtro),
  em vez de concatenar acordes na URL.
- O restante do fluxo continua igual: `progressbar`, `esfigeSpeech`, lista
  `vm.musics`, ordenação por `-popularidade` no template e clique para abrir a
  cifra.
- O template corrige o `ng-hide="music.diferenca.length"` de
  `static/templates/sequencia.html:43`. Como a resposta de sequência não tem
  `diferenca`, a condição deve ser removida ou trocada por algo seguro, como
  `ng-hide="music.diferenca && music.diferenca.length"`, para não esconder
  resultados por acidente.
- O rótulo de cada sequência é a própria lista de acordes; não há campo `nome`
  na API, no banco ou na UI.
- Não há botão de editar/apagar, porque as sequências são imutáveis por decisão
  de escopo.

## Memória e desempenho

O ponto de atenção é real, mas o desenho evita o cenário de “uma variável
gigante”:

- **Não** se guarda um `set` de objetos `Musica` por sequência. Guarda-se um
  `bytearray` com **1 bit por música**. Com 67.585 músicas, cada bitset tem
  `ceil(67.585 / 8) = 8.449` bytes, ou ~8,25 KiB.
- 500 customizadas + 6 seeds = 506 bitsets ≈ 4,08 MiB. Mesmo 1.000 sequências
  ficariam em ~8,1 MiB. O teto de 500 mantém o pior caso previsível.
- Além dos bitsets, há um mapa único `id_unico_musica -> posição` com 67.585
  entradas, da ordem de 5–10 MB. É construído uma vez, é somente leitura e não
  cresce com o número de sequências.
- O total adicional fica abaixo de ~20 MB, pequeno perto do CSV e dos objetos
  `Musica` que já estão em memória. Não é o fator dominante de RAM.
- Um `set` de IDs por sequência também seria pequeno para as sequências atuais
  (as 514 músicas taggeadas se distribuem em grupos de 3 a 296), mas o tamanho
  dependeria de quantas músicas cada sequência casa. O bitset é fixo e
  previsível, o que é melhor para um catálogo aberto.

Custo de cálculo:

- Medição local: ~0,12–0,34 s por sequência sobre as 67.585 músicas. 100
  sequências custaram ~12,5 s. A medição foi feita com a cifra já em minúsculas;
  no runtime, o `lower()` por token adiciona custo, mas o laço continua na mesma
  ordem de grandeza. Se necessário, um cache dos ~6.653 tokens distintos evita
  repetir `lower()` sem duplicar a cifra inteira.
- As 6 seeds são calculadas **eagerly** no startup: ~1 s adicional, aceitável
  perto dos ~3,4 s de carga do CSV.
- As customizadas que vêm do banco são calculadas **lazily** na primeira busca e
  ficam no cache `id_seq -> bytearray`. Assim o startup não depende de quantas
  customizadas existem.
- Uma sequência recém-cadastrada é calculada **no próprio POST** (~0,12–0,34 s),
  para que a primeira busca já seja rápida.
- As buscas seguintes só percorrem a coleção filtrada por gênero e testam bits;
  é O(n) com operação barata, na mesma ordem de grandeza (ou mais rápido) do
  `str(id_seq) in musica.seqs_famosas` atual.
- Se duas requisições pedirem a mesma sequência ainda não indexada, ambas podem
  calcular; o resultado é idempotente e uma sobrescreve a outra. O cache e o
  rate limit usam lock; o cálculo pesado fica fora do lock para não bloquear
  outras requisições.
- O teto de 500 limita o custo total de CPU: computar todas as 500 de uma vez
  custaria dezenas de segundos, mas isso é distribuído entre POSTs e primeiras
  buscas, e o startup só paga as 6 seeds.

Se no futuro o catálogo crescer muito ou o custo da primeira busca incomodar, os
próximos passos naturais são pré-computar em background ou persistir os bitsets
com versionamento do dataset. Nada disso é necessário para o escopo atual.

## Alternativas consideradas e descartadas

1. **Escrever as novas sequências no CSV e estender `SEQ_FAMOSA`.**
   Descartada: exigiria reescrever um CSV de ~77 MB, reiniciar o processo para
   recarregar, perderia atualizações concorrentes e transformaria um arquivo de
   dados somente leitura em estado mutável. Além disso, o requisito é
   persistência sem novo deploy, e o CSV é lido uma vez no import.

2. **Calcular o matching a cada requisição, sem índice.**
   Descartada: cada sequência custa ~0,12–0,34 s sobre 67.585 músicas. Uma busca
   repetida pagaria esse custo de novo. O bitset paga uma vez e depois responde
   com teste de bit.

3. **Materializar os matches em uma tabela `sequencia_musica` no SQLite.**
   Descartada para este escopo: uma sequência pode casar com centenas ou
   milhares de músicas, o que geraria muitas linhas e um join por busca. O
   bitset é ~8 KiB por sequência e resolve a consulta em memória, no processo
   único. A tabela materializada faria mais sentido se houvesse múltiplos
   processos ou consultas SQL sobre os matches.

4. **Usar um `set` de IDs de música por sequência.**
   Descartada: para as sequências atuais seria pequeno, mas o tamanho depende do
   número de matches e pode crescer sem limite previsível. O bitset tem tamanho
   fixo e independente da quantidade de matches.

5. **TinyDB, JSON em arquivo, `shelve` ou `diskcache`.**
   Descartada: são soluções de arquivo/cache, sem a robustez de transação e a
   constraint `UNIQUE` do SQLite. O TinyDB reescreve o arquivo inteiro a cada
   escrita e não tem coordenação entre processos; para um catálogo escrito por
   HTTP, isso é frágil.

6. **DuckDB, libSQL, LMDB, RocksDB ou um banco externo (Postgres/Redis).**
   Descartada: DuckDB/libSQL/LMDB/RocksDB adicionam dependência e complexidade
   para um catálogo de centenas de linhas; Postgres/Redis violam o container
   único e local-only do ADR 0001. O SQLite da stdlib é suficiente.

7. **Matching só por conjunto, ignorando ordem/contiguidade.**
   Descartada: mudaria a semântica e não reproduziria as tags atuais. Por
   exemplo, 5.768 músicas têm todos os acordes da sequência 0 em alguma ordem,
   mas apenas 199 satisfazem a regra completa (bloco contíguo + conjunto
   fechado). O requisito de regressão exige a regra legada.

8. **Guardar um campo `nome` para exibir as sequências.**
   Descartada: não há fonte de nomes em runtime (o arquivo
   `data/mapeamento_sequencias_famosas.txt` é só documentação) e a curadoria de
   nomes para sequências anônimas seria trabalho extra sem necessidade. A
   própria lista de acordes é o rótulo.

9. **Persistir os bitsets no SQLite.**
   Descartada por enquanto: são ~4 MiB no pior caso, ficam obsoletos se o CSV
   mudar e exigiriam versionamento do dataset. Recalcular lazily é barato o
   suficiente e mantém o banco pequeno.

## Escopo explícito

**Dentro do escopo:**

- Criar a tabela `sequencias` no SQLite e inicializá-la com as 6 seeds (IDs 0–5).
- Cadastro anônimo de sequências via `POST /sequencias`, com deduplicação
  normalizada e retorno `201`/`200`.
- `GET /sequencias` com o catálogo real, sem `nome`.
- Busca por `sequencia_id` e alias `?sequencia=`, com a regra legada de matching
  e os mesmos resultados das 6 originais.
- Índice em memória por bitset, seeds eager, customizadas lazy e cálculo no POST.
- Frontend `#/porsequencia` lendo o catálogo do backend, permitindo cadastro,
  sugerindo acordes da paleta e usando `sequencia_id` na busca.
- Correção do `ng-hide` que hoje depende de `music.diferenca`.
- Rate limit por IP, teto de 500 customizadas, limite de corpo de 16 KB e
  respostas `429`/`413` coerentes.
- Dockerfile com `/data`, `VOLUME`, `DECIFRAME_DB` e `--workers 1`; README com
  o `docker run -v deciframe-data:/data`; `.gitignore`/`.dockerignore` para o
  banco local.
- Testes de regressão das 6 originais, de cadastro/duplicata/validação, de
  persistência após restart de processo e de busca por sequência customizada.
- Atualização da documentação de operação (README/AGENTS) para o novo caminho do
  banco e para o volume.

**Fora do escopo (e por quê):**

- Editar, renomear ou apagar sequências: o catálogo é imutável por decisão de
  escopo; não há endpoint de `PUT`/`DELETE`.
- Moderação, contas, login ou painel administrativo: o requisito é catálogo
  aberto e anônimo; anti-abuso simples basta para o deploy local.
- Múltiplos workers do gunicorn: o índice, o cache e o rate limit são por
  processo; suportar N workers exigiria compartilhar estado. O setup continua
  single-worker.
- Transposição, equivalência enarmônica, redução de baixo invertido,
  simplificação de sufixos ou normalização por graus: mudaria a semântica e
  quebraria a regressão das 6 originais.
- Migrar músicas/gêneros para o banco, reescrever o CSV ou alterar o pipeline de
  geração: o enunciado fixa o CSV em memória para músicas/gêneros.
- Alterar paginação, ordenação, filtro por gênero ou o formato dos 9 campos da
  resposta de sequência.
- Mudar o formato de resposta de `json.dumps` para `jsonify` ou o
  `Content-Type` `text/html`.
- Mínimo/máximo rígido de acordes: a dica “2 a 8” é só de UI; o servidor rejeita
  apenas lista vazia/inválida.
- Pré-computação em background de todas as customizadas, persistência de
  bitsets, backup automático, rate limit compartilhado ou persistente.
- Redesenho visual da página, upgrade do AngularJS ou qualquer modernização de
  stack.
- Alvo de nuvem ou serviço externo de banco: o deploy continua local-only.

## Critérios de aceitação

1. `GET /generos` continua retornando um array JSON de gêneros, sem regressão no
   startup.
2. `GET /sequencias` retorna as 6 seeds com IDs 0–5 e as listas de acordes
   exatas: `Bm,G,D,A`; `C,G,Am,F`; `Em,G`; `C,A7,Dm,G7`; `Gm,F`; `C,C7,F,Fm`.
3. Para cada seed `i`, `GET /similares?sequencia_id=i` (somando as páginas)
   retorna exatamente o mesmo conjunto de músicas que a tag `i` do CSV:
   199, 296, 4, 5, 7 e 3 músicas, respectivamente.
4. `GET /similares?sequencia=Bm,G,D,A`, `?sequencia=BmGDA`,
   `?sequencia=CA7,Dm,G7` e `?sequencia=C, G, Am, F` continuam funcionando e
   retornam os mesmos conjuntos das seeds correspondentes.
5. `POST /sequencias` com uma lista nova retorna `201`, grava a linha, aparece em
   `GET /sequencias` e fica buscável por `sequencia_id` e pelo alias.
6. Cadastrar a mesma sequência de novo (inclusive com caixa/espaço diferentes)
   retorna `200` com o mesmo ID e não cria linha duplicada.
7. Cadastrar uma sequência igual a uma seed retorna `200` com o ID da seed.
8. Lista vazia ou só com tokens em branco retorna `400`; uma lista com 1 acorde é
   aceita; uma lista com 9 acordes é aceita; não há mínimo/máximo rígido.
9. O teto de 500 customizadas retorna `429` para cadastro novo; duplicata
   continua `200`. O rate limit de 10 POSTs/minuto por IP retorna `429` com
   `Retry-After`.
10. Corpo acima de 16 KB retorna `413`.
11. As respostas continuam sendo `json.dumps(...)` com `Content-Type: text/html`,
    inclusive os erros `400`/`413`/`429`.
12. A sequência customizada sobrevive a `docker restart` e a `docker rm` +
    `docker run` com o mesmo volume nomeado; um volume vazio inicializa as
    seeds sem duplicar.
13. O frontend lista as 6 seeds e as customizadas, permite cadastrar, mostra a
    dica “2 a 8 acordes”, usa a paleta apenas como sugestão, seleciona a
    sequência retornada e exibe mensagens para duplicata/erro/limite.
14. O `ng-hide` de `static/templates/sequencia.html` não esconde mais resultados
    de sequência por causa de `music.diferenca` ausente.
15. Não existe campo `nome` no banco, na API ou na UI; o rótulo é a lista de
    acordes.
16. O teste de regressão `artifacts/verifica_matching.py` continua passando com
    0 divergências, e um teste novo compara a API das 6 seeds com as tags do
    CSV.
17. Com 500 customizadas, o custo adicional de memória dos bitsets fica em
    ~4,1 MiB (além do mapa de posições, alguns MB) e o startup continua
    calculando apenas as 6 seeds.
18. A primeira busca de uma customizada vinda do banco pode custar ~0,1–0,4 s
    para construir o índice; as buscas seguintes são rápidas e não recalculam.
