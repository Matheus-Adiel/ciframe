# Relatório de testes — Sequências de Acordes Customizadas

## Cobertura

A suíte usa `unittest` da stdlib e roda em um banco SQLite temporário; o CSV
real (`data/top/dataset_final.csv`) é carregado uma vez, como na aplicação.
São 93 testes, distribuídos em quatro arquivos:

### `tests/test_matching.py` — regra e índice (26 testes)

- `casa`: bloco contíguo na ordem exata, ordem trocada, acorde fora do conjunto
  da sequência, normalização de caixa/espaços, repetição dentro do bloco,
  repetição fora do bloco, sequência vazia, sequência maior que a cifra e
  ausência de transposição/enarmonia/baixo invertido/simplificação de sufixo.
- Casos de borda adicionais: acorde extra antes/depois do bloco (o conjunto
  fechado vale para a cifra inteira), cifra vazia, sequência minúscula contra
  cifra maiúscula, repetições próprias da sequência, sequência de um acorde e
  espaços nos tokens.
- `construir_bitset`: liga exatamente as posições das músicas que casam; testa
  os limites de byte (posições 0, 8 e 16), garante que bits além do total de
  músicas ficam zerados, cobre lista de músicas vazia e sequência vazia.
- `IndiceSequencias`: cálculo e cache hit, posições depois do primeiro byte,
  sequência vazia sem matches, `contem` sem cache aquecido (`KeyError`),
  música desconhecida retorna `False` e cálculo concorrente com quatro threads
  produzindo o mesmo bitset.

### `tests/test_sequencias_store.py` — catálogo SQLite (26 testes)

- Seeds com IDs 0–5 e listas exatas, todas com `origem = original`, e
  reabertura sem duplicar seeds.
- `AUTOINCREMENT` da primeira customizada em 6; ordenação de várias
  customizadas por ID de cadastro.
- Duplicata normalizada por `strip().lower()` retorna o mesmo ID e não cria
  linha; duplicata de seed retorna o ID da seed.
- Preservação de caixa, ordem e repetições no campo `acordes`, com `chave`
  normalizada; tokens vazios são descartados; repetição distingue sequências.
- Busca por chave e reabertura do arquivo (persistência); `obter` e
  `buscar_por_chave` desconhecidos retornam `None`.
- Rejeição de lista vazia/só brancos e de tipos inválidos (lista com não-texto,
  string solta, `None`, número).
- Rejeição de acordes fora do formato (`aaaaaaaa`, `H`, `Cfoo`, `C#x`, `123`)
  e aceitação de sufixos usuais (`C#m7b5`, `G/B`, `F#`, `Bb7M`, `Am`, `Dsus4`).
- Teto de 500 customizadas, com duplicata ainda retornando `200` antes do teto.
- Falha ao abrir o banco aborta sem fallback silencioso para `./var`; diretório
  pai é criado automaticamente.
- Resolução de `DECIFRAME_DB` e padrão `./var/deciframe.db`.
- `PRAGMA user_version = 1`, `journal_mode = wal`, `busy_timeout` configurado;
  apenas `sequencias` e `sqlite_sequence` existem no banco.
- `user_version` futuro e seed divergente abortam o startup; `origem` fora do
  `CHECK` é rejeitada pelo schema.
- Acorde contendo SQL (`C'); DROP TABLE sequencias; --`) é rejeitado sem
  alterar o schema.

### `tests/test_api_sequencias.py` — API, regressão e persistência (35 testes)

- `GET /generos` e `GET /sequencias`: 6 seeds, IDs 0–5, listas exatas, sem
  campo `nome`, `Content-Type: text/html`.
- Regressão das 6 seeds: para cada ID, todas as páginas de
  `GET /similares?sequencia_id=i` são somadas e comparadas com o conjunto de
  músicas cuja tag `seqs_famosas` contém `i`; as contagens 199, 296, 4, 5, 7 e
  3 também são verificadas.
- Alias legado `?sequencia=`: `Bm,G,D,A`, `BmGDA`, `CA7,Dm,G7`, `CA7DmG7`,
  `C, G, Am, F`, `c,g,am,f`, caixa/espaço, repetições, vazio/só espaços e uma
  chave desconhecida.
- `sequencia_id` inválido, não numérico, vazio e inexistente devolve `[]` com
  HTTP 200; valores nos limites de 64 bits e fora do intervalo de `INTEGER` do
  SQLite também devolvem `[]` (regressão do `OverflowError`).
- Cadastro novo (`201`), presença em `GET /sequencias`, busca por
  `sequencia_id` e pelo alias; normalização de espaços e preservação de
  repetições (`C,G,C` é distinto de `C,G`).
- Catálogo em ordem de cadastro, com `criado_em` em ISO 8601 UTC.
- Duplicata com caixa/espaço diferentes (`200`, mesmo ID) e duplicata de seed
  (`200`, ID da seed) sem alterar as seeds.
- Validação `400`: lista vazia, tokens em branco, `acordes` não-lista, itens
  não-string, campo ausente, JSON malformado, payload que não é objeto
  (lista, `null`, número, booleano, string) e `Content-Type` não-JSON; corpo de
  erro em JSON com `Content-Type: text/html`.
- Um e nove acordes são aceitos.
- Acordes fora do formato retornam `400` e não criam linha; sufixos usuais são
  aceitos no cadastro; um acorde com SQL não altera o catálogo.
- Corpo acima de 16 KB retorna `413` em JSON.
- Rate limit: 10 tentativas por minuto e a 11ª retorna `429` com
  `Retry-After` positivo; o contador é separado por IP.
- Teto de 500 customizadas retorna `429` para sequência nova, mas duplicata
  (inclusive de seed) continua `200`; com o teto cheio, o catálogo lista
  506 sequências na ordem dos IDs.
- Precedência `acordes` > `id_unico_musica` > `sequencia_id` > `sequencia`.
- Paginação de 100 itens (100 + 99 + vazio), página além do fim vazia e filtro
  por gênero, inclusive gênero inexistente.
- Resposta de sequência com os 9 campos atuais (sem `diferenca`/`intersecao`).
- `PUT`, `DELETE` e `PATCH` em `/sequencias` retornam `405` e não alteram o
  catálogo.
- Persistência: cadastrar, reabrir o catálogo em outra instância e buscar de
  novo; simulação de restart com catálogo novo e bitset frio devolve o mesmo
  conjunto e volta a cachear.
- Startup: apenas as seeds 0–5 ficam no cache de bitsets; customizadas ficam
  lazy.
- `POST` de sequência nova já aquece o bitset; depois de `esquecer`, a busca
  recalcula e volta a cachear.
- Falha simulada no cálculo do bitset durante a busca retorna `500` em JSON,
  não `[]`.

### `tests/test_contratos_do_projeto.py` — contratos de contexto (6 testes)

- `Dockerfile` mantém `--workers 1`, `DECIFRAME_DB=/data/deciframe.db`,
  `mkdir -p /data` e `VOLUME ["/data"]`.
- Comandos `docker run` documentados montam o volume em `/data` e não em
  `/app/data`.
- `.gitignore`/`.dockerignore` ignoram `var/`, `*.db`, `*.db-wal` e `*.db-shm`.
- Controller carrega `GET /sequencias`, cadastra com `POST /sequencias` e busca
  por `sequencia_id`.
- Template mantém a dica “2 a 8 acordes” e o `ng-hide` protegido contra
  `music.diferenca` ausente.

## Teste de regressão obrigatório

Foram feitas três verificações independentes:

1. **Oráculo do repositório** — `artifacts/verifica_matching.py`, executado com
   `.venv/bin/python` e `DECIFRAME_DB` apontando para um arquivo temporário:

   ```
   == [A] cifra crua do CSV x tag crua do CSV ==
     músicas comparadas : 67585
     concordâncias      : 67585
     divergências       : 0
     músicas por sequência: {0: 199, 1: 296, 2: 4, 3: 5, 4: 7, 5: 3}

   == [B] musica.cifra x musica.seqs_famosas (runtime) ==
     músicas comparadas : 67585
     concordâncias      : 67585
     divergências       : 0
     músicas por sequência: {0: 199, 1: 296, 2: 4, 3: 5, 4: 7, 5: 3}

   tags com mais de um índice em seqs_famosas: 0
   RESULTADO: regra reproduz as tags em todas as comparações
   ```

   As duas comparações somam 135.170 checagens, com **0 divergências**.

2. **Teste de integração pela API** —
   `test_regressao_das_seis_seeds_contra_tags_do_csv` percorre todas as páginas
   de `GET /similares?sequencia_id=i` e compara o conjunto de
   `id_unico_musica` com o conjunto extraído diretamente de
   `musica.seqs_famosas` no CSV em memória. As seis seeds passam com exatamente
   199, 296, 4, 5, 7 e 3 músicas.

3. **Smoke test com servidor real (sem Docker)** — processo Flask iniciado com
   banco temporário: `GET /generos` (52 gêneros), `GET /sequencias` (6 seeds),
   `POST /sequencias` (`201`, ID 6), busca por `sequencia_id=6` (103 músicas em
   todas as páginas), duplicata com caixa/espaço (`200`, mesmo ID), parada e
   reinício do processo. Após o reinício, a sequência continuou em
   `GET /sequencias` e a busca devolveu exatamente o mesmo conjunto de 103
   músicas. `Content-Type` foi `text/html` em todas as respostas.

Resultado: **regressão aprovada, 0 divergências e mesmas contagens para as 6
seeds**.

## Falha encontrada e corrigida na revisão dos testes

Os testes de borda revelaram que `GET /similares?sequencia_id=` com um inteiro
fora do intervalo de `INTEGER` do SQLite (por exemplo
`999999999999999999999`) levantava `OverflowError` na consulta e devolvia
`500`, contrariando o contrato de “id inválido ou inexistente → `[]` com HTTP
200”. A guarda de intervalo foi adicionada em `sequencia_por_id` (`main.py`),
e o caso ficou coberto por `test_sequencia_id_fora_do_intervalo_do_sqlite_devolve_vazio`
com os limites `±2^63`, um valor imediatamente fora e um inteiro de 30 dígitos.

## Smoke test de browser

`artifacts/smoke_frontend.py` sobe o Flask com banco temporário e usa Firefox
headless via Selenium/geckodriver para percorrer `#/porsequencia`:

- renderiza as 6 seeds do catálogo;
- clica numa seed e confirma que os cards aparecem (o `ng-hide` corrigido não
  esconde resultados sem `diferenca`);
- cadastra `E, B, C#m, A`, confirma a mensagem de sucesso, o 7º item no
  catálogo e a busca com resultados;
- tenta a duplicata ` e , b , C#M , a `, confirma a mensagem “já existe” e que o
  catálogo continua com 7 sequências;
- troca o filtro de gênero e confere que todos os cards exibidos pertencem ao
  gênero escolhido;
- clica num card e confirma que `window.open` foi chamado com uma URL.

Resultado: **SMOKE FRONTEND OK**.

## Teste manual do container (Docker)

Comece limpo (se já existir um container/volume de testes):

```
sudo docker rm -f deciframe 2>/dev/null || true
sudo docker volume rm deciframe-data 2>/dev/null || true
```

Construa e suba:

```
sudo docker build -t ciframe .
sudo docker run -d --name deciframe -p 8080:8080 \
  -v deciframe-data:/data ciframe
```

Espere o startup (o CSV e as 6 seeds são carregados no import) e verifique:

```
curl -s http://localhost:8080/generos
curl -s http://localhost:8080/sequencias
```

Cadastre uma sequência e confirme o `201` com ID 6:

```
curl -s -X POST http://localhost:8080/sequencias \
  -H 'Content-Type: application/json' \
  -d '{"acordes":["E","B","C#m","A"]}'
curl -s 'http://localhost:8080/similares?sequencia_id=6&pagina=1'
```

Teste a duplicata normalizada (deve retornar `200` com o mesmo ID):

```
curl -s -X POST http://localhost:8080/sequencias \
  -H 'Content-Type: application/json' \
  -d '{"acordes":[" e ","b","C#M","a"]}'
```

Teste a persistência com `docker restart`:

```
sudo docker restart deciframe
curl -s http://localhost:8080/sequencias
curl -s 'http://localhost:8080/similares?sequencia_id=6&pagina=1'
```

Agora remova o container e suba de novo com o mesmo volume:

```
sudo docker rm -f deciframe
sudo docker run -d --name deciframe -p 8080:8080 \
  -v deciframe-data:/data ciframe
curl -s http://localhost:8080/sequencias
```

A sequência de ID 6 deve continuar aparecendo em `GET /sequencias` e a busca
deve devolver o mesmo conjunto. Confira também que o volume está em `/data`:

```
sudo docker volume inspect deciframe-data
sudo docker exec deciframe ls -l /data
```

No fim, para limpar o ambiente de teste:

```
sudo docker rm -f deciframe
sudo docker volume rm deciframe-data
```

## Medições

Executadas nesta máquina, com o CSV real:

- **Startup** (import do `main.py`, incluindo CSV + 6 seeds): 7,0–8,6 s,
  variando entre execuções.
- **Cálculo das 6 seeds**: ~0,48–0,50 s por seed, ~2,9 s no total.
- **Primeiro cálculo de uma customizada** (bitset ainda não cacheado):
  ~0,49–0,82 s em três execuções; a busca seguinte é cache hit (~3 µs).
- **Bitset por sequência**: 8.449 bytes = 8,25 KiB. Para 500 customizadas, o
  teto teórico é 4,03 MiB, além do mapa de posições.
- **RSS ao adicionar 500 bitsets**: delta medido de ~2 MiB, menor que o teto
  teórico porque o processo reutiliza arenas livres do carregamento do CSV.
- **Startup só calcula as seeds**: teste automatizado confirma que o cache
  inicial contém exatamente os IDs 0–5.

## Como rodar

```
.venv/bin/python -m unittest discover -s tests -v
```

Resultado da última execução:

```
Ran 93 tests in 11.617s

OK
```

O oráculo de regressão deve ser rodado com o interpretador do projeto (o
`python` do sistema pode não ter Flask instalado):

```
DECIFRAME_DB=/tmp/deciframe-verifica.db \
  .venv/bin/python artifacts/verifica_matching.py
```

O smoke de browser é opcional (depende de Selenium, geckodriver, Firefox e dos
CDNs do `index.html`):

```
.venv/bin/pip install selenium
GECKODRIVER=/caminho/para/geckodriver \
  .venv/bin/python artifacts/smoke_frontend.py
```

## O que ficou de fora

- **Smoke test no Docker e no volume nomeado.** O daemon Docker não estava
  acessível sem `sudo` neste ambiente. A persistência foi validada reabrindo o
  catálogo, reiniciando o processo Flask e pelo smoke de browser, mas
  `docker restart` / `docker rm` + `docker run` com o volume nomeado não foram
  executados aqui. O passo a passo manual está em [Teste manual do container (Docker)](#teste-manual-do-container-docker).
- **Múltiplos POSTs simultâneos e contenção de escrita no SQLite.** O bitset
  tem teste concorrente e o rate limit tem teste por IP, mas não há teste de
  corrida real de escrita concorrente nem de `remote_addr` atrás de proxy.
- **Falha real do SQLite durante POST/busca.** O caminho `500` da busca foi
  exercitado com falha simulada no bitset; não se induziu erro real de disco ou
  de permissão no meio de uma requisição.
- **Migração de schema anterior à versão 1.** Não existe versão anterior; só a
  criação idempotente e a recusa de versão futura estão cobertas.
- **Aspectos visuais/responsivos.** O smoke de browser verifica o fluxo
  funcional, não layout, cores ou comportamento em diferentes tamanhos de tela.
- **Vídeo/gif e arquivo da sessão.** São entregas manuais do exercício, não
  fazem parte da suíte automatizada.
