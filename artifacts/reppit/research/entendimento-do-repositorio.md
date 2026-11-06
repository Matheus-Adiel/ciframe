# Entendimento do repositório — deciframe

> Snapshot do código em 2026-10-31, HEAD `fb97001`, árvore de trabalho limpa.
> Este documento descreve apenas o que existe hoje. Não contém proposta,
> avaliação ou trabalho futuro.

## Resumo

O deciframe é uma aplicação Flask + AngularJS 1.4.9 que sugere músicas a partir
de três buscas: título/artista, acordes conhecidos e sequências de acordes
famosas. Todo o catálogo vem de um único CSV (`data/top/dataset_final.csv`)
carregado para a memória no import de `main.py`; não há banco de dados, ORM nem
migrações. O backend expõe uma API JSON em `main.py` e `musica.py`, enquanto o
frontend está em `static/`, sem build step, consumindo a API por URLs relativas.
As sequências famosas existem em duas listas hardcoded independentes: 6 no
backend (`main.py:40-45`) e 4 no JavaScript (`sequencia.js:2-37`). A feature de
sequências customizadas descrita em `docs/features/` ainda não está implementada
no código; existem apenas os documentos/templates da tarefa.

## Leitura rápida para agentes

- O CSV é lido **uma vez no import**; editar `data/top/*.csv` exige reiniciar o
  processo (`main.py:49-98`, `AGENTS.md:45`).
- A primeira linha do CSV é **descartada** por `f.readline()` (`main.py:49-50`),
  embora o arquivo não tenha cabeçalho. A primeira música não entra na base.
- Os endpoints retornam `json.dumps(...)`, não `jsonify`; o `Content-Type` é
  `text/html; charset=utf-8` (`main.py:142`, `main.py:156`, `main.py:160`,
  `main.py:164`, `main.py:168`, `main.py:197`, `main.py:201`).
- `/musicas` devolve **todas** as músicas, sem paginação, apesar do comentário
  acima da rota falar em páginas de 100 (`main.py:149-156`). Nesta base a
  resposta tem ~48,6 MB.
- Não há autenticação, banco, cache, fila ou serviço externo.
- O frontend usa URLs relativas (`apiUrl = ""`) em todos os controllers; a
  constante `RESTAPI` em `app.js:3-5` não é usada.
- Não há suíte de testes automatizados, configuração de CI, `package.json` nem
  `pytest`/`tox` no repositório rastreado.
- `static/assets/vendor` é ignorado pelo Git (`.gitignore:1`) e não existe no
  checkout; `static/bower.json` declara apenas `ng-material-floating-button`.
- A página `#/porsequencia` chama `/similares?sequencia=...`; o backend só
  reconhece as 6 chaves hardcoded e devolve `[]` para qualquer outra
  (`main.py:190-197`).
- O endpoint `/similares?id_unico_musica=<id>` levanta `KeyError`/HTTP 500 para
  id inexistente; foi observado com `14-bis_a-qualquer-tempo`, que é justamente
  a primeira linha descartada do CSV (`main.py:187-189`).
- `/search` exige o parâmetro `key`; sem ele, `request.args.get('key').lower()`
  falha (`main.py:118`).

## Mapa do repositório

| Caminho | Papel |
|---|---|
| `main.py` | Aplicação Flask, carga do CSV, índices em memória e todos os endpoints. |
| `musica.py` | Classe `Musica`, usada como registro em memória. |
| `data/top/dataset_final.csv` | Base principal: 67.586 linhas, 9 colunas, sem cabeçalho. |
| `static/index.html` | Shell AngularJS, CDNs, navbar, menu “sobre” e inclusão dos scripts. |
| `static/assets/js/` | Módulo Angular, rotas, controllers, diretivas e barra de progresso. |
| `static/templates/` | Templates das páginas e das diretivas (`df-hex`, `df-esfinge`). |
| `scripts/` | Pipeline legado de coleta/parsing/geração do CSV (Python 2, R, Java, shell). |
| `data/` | CSVs auxiliares, HTMLs de estilos, matriz de transposição e listas de URLs. |
| `docs/adr/` | ADRs 0001 (Docker local), 0002 (template não preenchido) e 0003 (frontend liberado). |
| `docs/features/sequencias-customizadas/` | Enunciado e templates das 5 fases; feature não implementada. |
| `Dockerfile`, `requirements.txt` | Empacotamento Python 3.9 + gunicorn. |
| `AGENTS.md`, `README.md`, `CONTRIB.md` | Convenções, descrição e boilerplate de contribuição. |
| `.playground` | Metadados do skeleton antigo de App Engine, sem uso pelo app. |

## Backend

### Inicialização e carga do CSV

`main.py:49-98` executa no import do módulo:

1. Abre `data/top/dataset_final.csv` e descarta a primeira linha (`main.py:49-50`).
2. Para cada linha, remove aspas, remove todas as ocorrências literais de `NA`
   e remove o último caractere (`main.py:53`).
3. Faz `split(',')` simples, sem módulo `csv` (`main.py:55`).
4. Converte `POPULARIDADE` para inteiro removendo pontos (`main.py:56`).
5. Converte `CIFRA` em lista de acordes via `limpa_cifra` (`main.py:58-61`,
   `main.py:11-23`).
6. Divide `SEQ_FAMOSA` por `;` (`main.py:63`).
7. Cria um objeto `Musica` e o insere em `musicas_dict`
   (`main.py:69-74`).
8. Alimenta os conjuntos `generos` e `acordes` e o índice
   `genero_musicas` (`main.py:65-85`).
9. Ordena todas as músicas por popularidade decrescente em um `OrderedDict`
   (`main.py:87-89`) e ordena cada lista de `genero_musicas`
   (`main.py:94-96`).

Constantes de coluna e paginação: `main.py:25-35`. Estruturas globais:
`main.py:37-47`. O mapa de sequências hardcoded é `main.py:40-45`:

| Chave | Índice |
|---|---|
| `BmGDA` | 0 |
| `CGAmF` | 1 |
| `EmG` | 2 |
| `CA7DmG7` | 3 |
| `GmF` | 4 |
| `CC7FFm` | 5 |

`limpa_cifra` (`main.py:11-23`) ignora tokens vazios; se a linha tem `|`, pega o
primeiro token antes do `|`; caso contrário, separa a linha por espaços.

### Modelo `Musica`

`musica.py:1-25` define os campos:

- `id_artista`, `nome_artista`, `id_musica`, `nome_musica`, `genero`,
  `popularidade`, `tom`, `cifra`, `acordes`, `seqs_famosas`.
- `id_unico_musica = "<id_artista>_<id_musica>"` (`musica.py:20`).
- `url = "http://www.cifraclub.com.br/<id_artista>/<id_musica>"` (`musica.py:22`).
- `acordes = list(set(cifra))`, ou seja, acordes únicos sem ordem garantida
  (`musica.py:17`).

### Índices em memória

| Estrutura | Conteúdo | Referência |
|---|---|---|
| `musicas_dict` | `id_unico_musica -> Musica` | `main.py:47`, `main.py:74` |
| `musicas` | `OrderedDict` das músicas por popularidade desc | `main.py:87-89` |
| `genero_musicas` | `genero -> lista de Musica`, ordenada por popularidade | `main.py:37`, `main.py:80-85`, `main.py:94-96` |
| `generos` | `set` de gêneros; convertido em `list` no fim da carga | `main.py:38`, `main.py:66`, `main.py:92` |
| `acordes` | `set` de todos os acordes presentes nas cifras | `main.py:39`, `main.py:76-78` |
| `sequencias` | 6 sequências hardcoded e seus índices | `main.py:40-45` |

Contagens observadas nesta base, executando o import atual: **67.585 músicas**,
**52 gêneros**, **6.653 acordes distintos**; import em ~3,4 s em ambiente local.
O CSV tem 67.586 linhas, mas uma é descartada.

### Endpoints

| Rota | Parâmetros | Resposta | Código |
|---|---|---|---|
| `GET /` | — | `static/index.html` | `main.py:101-103` |
| `GET /<path:path>` | caminho | arquivo estático de `static/` | `main.py:109-112` |
| `GET /search` | `key` (obrigatório), `generos` (CSV), `pagina` (default `1`) | lista paginada de músicas com `id_unico_musica`, `id_artista`, `id_musica`, `nome_artista`, `nome_musica`, `genero`, `url` | `main.py:114-142` |
| `GET /musicas` | — | todas as músicas, com todos os campos do objeto | `main.py:154-156` |
| `GET /generos` | — | lista de gêneros | `main.py:158-160` |
| `GET /acordes` | — | lista de acordes | `main.py:162-164` |
| `GET /musica/<m_id>/` | `m_id` | um objeto `Musica` completo | `main.py:166-168` |
| `GET /similares` | `acordes`, `id_unico_musica`, `sequencia`, `generos`, `pagina` | lista de músicas similares | `main.py:170-201` |

A rota `/<path:path>` também serve `assets/...` e `templates/...` porque o
`index.html` referencia esses caminhos relativos (`static/index.html:18-19`,
`static/index.html:136-147`) e o Flask os resolve em `static/`.

### Busca por título/artista (`/search`)

`main.py:114-142`:

1. Lê `generos`, `pagina` e `key`; `key` é obrigatório e é lowercased
   (`main.py:116-119`).
2. Remove diacríticos com `remover_combinantes` e separa a busca por espaços
   (`main.py:119`, `main.py:145-147`).
3. Se `generos` não vier, usa todos os gêneros (`main.py:121-123`).
4. Filtra a coleção global (`musicas.values()`, ordenada por popularidade) por
   gênero (`main.py:125`, `main.py:266-272`).
5. Monta `nome_artista + " " + nome_musica`, remove diacríticos e verifica se
   **todos** os tokens da busca estão presentes na lista de tokens do texto
   (`main.py:128-131`). É comparação de token exato, não substring.
6. Pagina com `get_pagina`, que usa `TAM_PAGINA = 100` e página 1-based
   (`main.py:142`, `main.py:226-228`, `main.py:35`).

### Busca por acordes (`/similares?acordes=...`)

`main.py:184-201` e `main.py:230-263`:

- `acordes_tag` é dividido por vírgula (`main.py:185-186`).
- A coleção é filtrada por gênero (`main.py:233`, `main.py:266-272`).
- Para cada música, calcula `inter = acordes_pedidos ∩ acordes_da_musica` e
  `diff = acordes_da_musica - acordes_pedidos` (`main.py:240-241`).
- Só entram músicas com interseção não vazia (`main.py:245`).
- Cada resultado inclui `diferenca` e `intersecao` (`main.py:256-257`).
- A ordenação efetiva é `(len(diferenca), -len(intersecao))`
  (`main.py:263`). O comentário menciona popularidade, mas a chave de ordenação
  não inclui popularidade; o frontend reordena por `-popularidade` no template.

### Busca por música (`/similares?id_unico_musica=...`)

`main.py:187-189`: busca a música em `musicas`, usa `musica.acordes` como
conjunto de acordes e passa o próprio id para `get_similares`, que exclui a
música de origem (`main.py:238`). Id inexistente produz `KeyError` (HTTP 500).

### Busca por sequência (`/similares?sequencia=...`)

`main.py:190-197` e `main.py:203-223`:

- O frontend envia os acordes separados por vírgula; o backend remove as
  vírgulas e monta uma chave, por exemplo `Bm,G,D,A` vira `BmGDA`
  (`main.py:191`).
- A chave é procurada no dicionário `sequencias` (`main.py:194`).
- Se existir, `get_similares_por_sequencia` percorre a coleção filtrada por
  gênero e seleciona músicas cujo campo `seqs_famosas` contenha o índice como
  string (`main.py:203-223`, especialmente `main.py:209`).
- Se a chave não existir, a resposta é `[]` (`main.py:192-197`).
- Não há cálculo de sequência em tempo real sobre `musica.cifra` ou
  `musica.acordes` neste endpoint.
- O resultado não inclui `diferenca`/`intersecao`; inclui `popularidade`,
  `acordes`, `genero` e `url` (`main.py:210-220`).

### Semântica de `SEQ_FAMOSA`

A coluna 7 do CSV (`SEQ_FAMOSA`) contém `NA` ou índices de sequência. Na base
atual: 67.071 linhas com `NA`, 296 com `1`, 199 com `0`, 7 com `4`, 5 com `3`,
4 com `2` e 3 com `5`. A tag foi gerada pelo pipeline em
`scripts/generate_data_set.py:8-24`, que compara a sequência com a cifra em
minúsculas e verifica se os acordes da música pertencem ao conjunto de acordes
da sequência. O runtime apenas lê a tag; não recalcula.

### Filtro por gênero

`apply_filtro` (`main.py:266-272`) concatena as listas de `genero_musicas` para
cada gênero pedido que exista em `generos`. Consequências observadas:

- Com `generos` explícito, a ordem é a ordem das listas por gênero (cada uma
  ordenada por popularidade), não uma ordenação global.
- Com `/search` sem `generos`, a coleção é `musicas.values()`, globalmente
  ordenada por popularidade.
- Com `/similares` sem `generos`, `generos_key` é a lista global de gêneros e a
  coleção resultante fica agrupada por gênero.

### Respostas, erro e CORS

- Todas as respostas JSON são strings de `json.dumps`, com `Content-Type`
  `text/html; charset=utf-8`.
- `@app.after_request` adiciona `Access-Control-Allow-Origin: *` a todas as
  respostas (`main.py:274-277`).
- `python main.py` sobe o servidor de desenvolvimento em `:5000` com
  `debug=True` (`main.py:279-280`).

## Frontend

### Bootstrap e rotas

`static/index.html:1-149` é o shell:

- `ng-app="deciframeApp"` e `ng-controller="MainController"` (`index.html:2`,
  `index.html:22`).
- Bootstrap 3.3.6, jQuery 1.11.3, AngularJS 1.4.9, `angular-route`,
  `angular-animate` e `angular-ui-bootstrap` vêm de CDN
  (`index.html:13-16`, `index.html:125-134`).
- Scripts locais: `ngprogress.js`, `app.js`, `routes.js`, controllers e
  diretivas (`index.html:136-147`). `controllers/search.js` existe, mas não é
  incluído no `index.html`.
- O menu “sobre” é controlado por `MainController` (`index.html:34-38`,
  `index.html:90-121`, `main.js:1-12`).
- O conteúdo das rotas é renderizado em `<div class="page" ng-view>` (`index.html:123`).

`static/assets/js/app.js:1-58` cria o módulo `deciframeApp`, registra as
dependências `ngRoute`, `ngAnimate`, `ngProgress` e `ui.bootstrap`, define a
constante `RESTAPI` com `http://localhost:5003` (não usada) e a constante
`GENEROS` com 51 gêneros hardcoded. O backend tem 52 gêneros; o item ausente no
frontend é `R&B;`.

`static/assets/js/routes.js:1-29` define:

| Rota | Template | Controller | `controllerAs` |
|---|---|---|---|
| `/` | `templates/home.html` | `HomeController` | — |
| `/poracordes` | `templates/acordes.html` | `AcordesController` | `Chords` |
| `/pormusica` | `templates/musica.html` | `MusicaController` | `Musica` |
| `/porsequencia` | `templates/sequencia.html` | `SequenciaController` | `Sequencia` |
| `/sobre` | `templates/about.html` | `AboutController` | — |
| qualquer outra | redireciona para `/` | — | — |

### Páginas e controllers

**Home** (`home.html:1-90`, `home.js:1-4`): painel com a esfinge SVG, logo e três
links para `#/poracordes`, `#/pormusica` e `#/porsequencia`
(`home.html:61-86`).

**Por acordes** (`acordes.html:1-96`, `acordes.js:1-125`):

- Lista local de acordes em 7 grupos (C, D, E, F, G, A, B), com cores
  (`acordes.js:2-53`).
- `meusAcordes` guarda os acordes selecionados; clicar adiciona/remove
  (`acordes.js:54`, `acordes.js:63-71`).
- A cada mudança, chama `GET similares?acordes=<lista separada por vírgula>`
  e opcionalmente `&generos=<gênero>` (`acordes.js:84-108`).
- O template separa resultados em “você já sabe tocar” quando
  `diferenca.length == 0` e “aprenda mais acordes” quando há diferença
  (`acordes.html:40-91`).
- O dropdown de gênero usa `GENEROS` hardcoded (`acordes.js:59`,
  `acordes.html:24-30`).

**Por música** (`musica.html:1-119`, `musica.js:1-80`):

- Typeahead com mínimo de 3 caracteres, espera de 1000 ms, chamando
  `GET search?key=<valor>` (`musica.html:8-18`, `musica.js:14-20`).
- Ao selecionar, chama `GET similares?id_unico_musica=<id>` e opcionalmente
  `&generos=<gênero>` (`musica.js:43-68`).
- Resultados também são divididos por `diferenca.length`
  (`musica.html:46-113`).

**Por sequência** (`sequencia.html:1-63`, `sequencia.js:1-105`):

- Lista local de 4 sequências: `Bm-G-D-A`, `C-G-Am-F`, `Gm-F`,
  `C-C7-F-Fm` (`sequencia.js:2-37`).
- Ao clicar, chama `GET similares?sequencia=<acordes separados por vírgula>` e
  opcionalmente `&generos=<gênero>` (`sequencia.js:63-90`).
- `limparPesquisa` zera a sequência e os resultados (`sequencia.js:92-95`).
- O template usa `ng-hide="music.diferenca.length"` e
  `ng-show="music.diferenca.length"` (`sequencia.html:40-59`); como a resposta
  de sequência não tem `diferenca`, todos os resultados aparecem no primeiro
  bloco.

**Sobre** (`about.html:1-9`, `about.js:1-4`): mostra apenas `pageTitle`.

### Controllers não usados ou parciais

- `static/assets/js/controllers/search.js:1-26` define `SearchController`, mas
  o arquivo não é carregado por `index.html`; o corpo contém um mock de
  “Californication” e um `$http.get("")` sem uso prático.
- `MusicaController` define `addAcorde`, `temAcorde` e `createChordsString`
  (`musica.js:22-41`) sem uso no template de música.
- `RESTAPI` (`app.js:3-5`) não é injetado em nenhum controller.

### Diretivas e templates

- `dfHex` (`df-hex.js:1-12`) renderiza `templates/directives/df-hex.html:1-9`:
  um hexágono SVG com preenchimento controlado por `acordeColor` e
  `acordeChecked`.
- `dfEsfinge` (`df-esfinge.js:1-9`) renderiza
  `templates/directives/df-esfinge.html:1-326`, um SVG grande com classes de
  animação (`flyUpDown`, `flyShadow`, `rotateInUpLeft`, `rotateInUpRight`).
- `ngprogress.js` é vendorizado localmente e fornece `ngProgressFactory`.

### Estilos e assets

- `static/assets/css/app.css` contém o layout (painéis, cards, menu, esfinge,
  responsividade).
- `static/assets/css/icons.css` e `fonts/icomoon.*` fornecem os ícones.
- `static/assets/img/deciframe.png` e `team.png` são imagens do app/time.
- `static/bower.json:1-26` declara `ng-material-floating-button` em
  `assets/vendor`, mas esse diretório é ignorado e não está presente.
- `static/favicon.ico` é o favicon.

## Dados e pipeline

### `data/top/dataset_final.csv`

- 67.586 linhas, 9 colunas, sem cabeçalho.
- Colunas, na ordem usada por `main.py:26-34`:
  1. `ARTISTA_ID` (slug)
  2. `MUSICA_ID` (slug)
  3. `ARTISTA` (nome exibido)
  4. `MUSICA` (nome exibido)
  5. `GENERO`
  6. `POPULARIDADE` (inteiro; no CSV pode ter pontos de milhar)
  7. `TOM`
  8. `SEQ_FAMOSA` (`NA` ou índices separados por `;`)
  9. `CIFRA` (acordes separados por `;`)
- A primeira linha é um registro real (`14-bis,a-qualquer-tempo,...`), não um
  cabeçalho; `main.py:50` a descarta.
- `data/top/merge_datasets.R:1-17` documenta a junção que gera o arquivo a
  partir de `dataset.csv` + `visualizacoes_pontos.csv`.
- `data/top/popularidade.R:1-10` agrupa visualizações por artista.

### Dados auxiliares

| Caminho | Conteúdo |
|---|---|
| `data/mapeamento_sequencias_famosas.txt` | Nome legível das 6 sequências (0–5). |
| `data/teoria` | Campos harmônicos de F, C, G, D e escalas maiores. |
| `data/transposition_matrix2.csv` | Matriz de graus por tonalidade (I–VII). |
| `data/dataset_seq_notas.csv` | Cifras e sequências normalizadas por graus. |
| `data/data-cavaco.csv` | Base de exemplo de outro instrumento (cavaco). |
| `data/artistas_por_letra.txt`, `data/url-artistas*.txt` | Listas de URLs de artistas do cifraclub. |
| `data/top/artista_musica_estilo.txt` | Mapeamento artista/música/estilo. |
| `data/top/top_artistas.txt`, `*.songs` | Listas de artistas e URLs de músicas coletadas. |
| `data/top/visualizacoes.csv`, `visualizacoes_pontos.csv` | Dados de popularidade. |
| `data/top/html_estilos/` | HTMLs das páginas de estilo do cifraclub. |
| `data/top/chords-transitions-empty.csv` | Arquivo de uma linha usado pelo pipeline R. |

### Scripts

O diretório `scripts/` é o pipeline legado de coleta e geração da base, fora do
runtime da aplicação:

- **Coleta:** `DownloadAll.java:1-73` (jsoup) baixa listas de músicas;
  `collect_song_list.sh:1-6` o executa; `download_band_names.sh:1-11` e
  `download_cifras.sh:1-9` baixam listas e HTMLs via `curl`.
- **Parsing:** `generate_data_set.py:1-92` gera as colunas do CSV a partir dos
  HTMLs, incluindo `SEQ_FAMOSA`; `cifra_parser.py:1-27`,
  `parse_artistas_estilos.py:1-29` e `parse_estilos.py:1-22` extraem dados
  específicos. Esses arquivos usam sintaxe/print de Python 2.
- **Transformação:** `normalize_chords.R:1-41` e `simplify_chords.R:1-36`
  convertem acordes em graus; `build-chords-transitions.R:1-76` monta
  transições; `add_estilos.R:1-9` e `add_estilos.py:1-45` cruzam estilos com
  músicas.

Nenhum desses scripts é chamado pelo `main.py` em runtime.

## Deploy e operação

### Docker

`Dockerfile:1-12`:

- Base `python:3.9-slim`.
- `WORKDIR /app`.
- Instala `requirements.txt` com `pip --no-cache-dir`.
- Copia o repositório.
- Expõe `8080`.
- Executa `gunicorn --bind 0.0.0.0:8080 main:app`.

`requirements.txt:1-5` fixa `Flask==3.1.3` e `gunicorn==23.0.0`.

### Execução local

- Docker: `docker build -t ciframe .` e `docker run -p 8080:8080 ciframe`
  (`README.md:13-20`, `AGENTS.md:22-25`).
- Virtualenv: `python main.py`, servindo em `:5000` com debug
  (`README.md:22-31`, `main.py:279-280`).
- Verificação descrita: `curl http://localhost:8080/generos` deve retornar um
  array JSON de gêneros (`AGENTS.md:35-41`).

### Arquivos de deploy e documentação

- `docs/adr/0001-local-only-docker-deploy.md:1-16` registra a remoção de
  App Engine/Heroku e a adoção do Dockerfile local-only.
- `docs/adr/0003-lift-frontend-freeze.md:1-21` remove a restrição de mexer no
  frontend legado; não moderniza a stack.
- `docs/adr/0002-persist-custom-sequences.md:1-8` ainda é um template com
  instruções, sem decisão registrada.
- `docs/features/sequencias-customizadas/00-enunciado.md:1-130` descreve a
  tarefa de sequências customizadas; `01-research.md` a `04-test-report.md`
  permanecem como templates com blocos de instrução.
- `CONTRIB.md:1-38` é boilerplate do Google Cloud Platform (CLA, App Engine),
  não descreve o fluxo atual do projeto.
- `LICENSE` é Apache License 2.0.

## Fluxos ponta a ponta

### 1. Inicialização

```
main.py import
  -> lê data/top/dataset_final.csv (main.py:49-98)
  -> cria Musica por linha (musica.py:1-25)
  -> popula musicas_dict, musicas, generos, acordes, genero_musicas
  -> Flask registra rotas (main.py:101-201)
```

### 2. Busca por título/artista

```
static/templates/musica.html (typeahead)
  -> MusicaController.getMusicas (musica.js:14-20)
  -> GET /search?key=<texto> (main.py:114-142)
  -> normaliza acentos, tokeniza, filtra por gênero, pagina 100
  -> retorna metadados básicos
  -> seleção chama GET /similares?id_unico_musica=<id>
     (musica.js:43-68, main.py:187-201)
  -> resultados com diferenca/intersecao
  -> template abre music.url no cifraclub (musica.js:72-74)
```

### 3. Busca por acordes

```
acordes.html + AcordesController
  -> meusAcordes (acordes.js:63-71)
  -> GET /similares?acordes=C,G,...[&generos=...] (acordes.js:84-108)
  -> apply_filtro por gênero (main.py:266-272)
  -> interseção/diferença de acordes (main.py:230-263)
  -> frontend separa por diferenca.length (acordes.html:40-91)
```

### 4. Busca por sequência

```
sequencia.html + SequenciaController
  -> 4 sequências hardcoded (sequencia.js:2-37)
  -> GET /similares?sequencia=Bm,G,D,A (sequencia.js:63-90)
  -> backend remove vírgulas e busca em sequencias (main.py:190-197)
  -> get_similares_por_sequencia usa musica.seqs_famosas (main.py:203-223)
  -> resposta sem diferenca; template mostra no primeiro bloco
```

### 5. Arquivos estáticos

```
GET / ou /assets/... ou /templates/...
  -> Flask static_folder=static
  -> rota / (main.py:101-103) ou static_proxy (main.py:109-112)
  -> static/index.html, assets, templates
```

## Observações factuais que afetam manutenção

- O backend e o frontend têm catálogos de sequência diferentes: 6 no backend,
  4 no frontend (`main.py:40-45`, `sequencia.js:2-37`).
- O frontend tem 51 gêneros hardcoded; o backend tem 52, incluindo `R&B;`
  (`app.js:6-58`, `main.py:66`).
- A rota `/musicas` não usa `TAM_PAGINA` nem `get_pagina`; devolve o
  `OrderedDict` inteiro (`main.py:154-156` vs. `main.py:226-228`).
- O comentário de ordenação de similares menciona popularidade, mas a chave
  usada é apenas `(len(diferenca), -len(intersecao))` (`main.py:262-263`).
- A resposta de `/similares?sequencia=...` não inclui `diferenca` nem
  `intersecao`; a de `/similares?acordes=...` e a de
  `/similares?id_unico_musica=...` incluem (`main.py:210-220`,
  `main.py:246-258`).
- O CSV é tratado como texto simples: `replace('NA', '')` remove `NA` de
  qualquer posição da linha e `[:-1]` remove o último caractere antes do split
  (`main.py:53`).
- A primeira linha do CSV não é carregada (`main.py:50`); por isso
  `14-bis/a-qualquer-tempo` não existe em `musicas`.
- Não há tratamento de exceções nas rotas; parâmetros ausentes ou ids
  inexistentes resultam em erro HTTP 500 (`main.py:118`, `main.py:188`).
- Não há teste automatizado, linter, CI ou script de build no repositório.

## Referências principais

| Assunto | Arquivo:linhas |
|---|---|
| Carga do CSV e índices | `main.py:49-98` |
| Constantes de colunas | `main.py:25-35` |
| Modelo de música | `musica.py:1-25` |
| Busca por título/artista | `main.py:114-147` |
| Busca por acordes | `main.py:230-263` |
| Busca por sequência | `main.py:190-223` |
| Filtro por gênero | `main.py:266-272` |
| Rotas estáticas | `main.py:101-112` |
| Bootstrap Angular | `static/assets/js/app.js:1-58`, `static/assets/js/routes.js:1-29` |
| Controller de acordes | `static/assets/js/controllers/acordes.js:1-125` |
| Controller de música | `static/assets/js/controllers/musica.js:1-80` |
| Controller de sequência | `static/assets/js/controllers/sequencia.js:1-105` |
| Templates de página | `static/templates/*.html` |
| Diretivas | `static/assets/js/directives/*.js`, `static/templates/directives/*.html` |
| Docker | `Dockerfile:1-12`, `requirements.txt:1-5` |
| Decisões de deploy/frontend | `docs/adr/0001-local-only-docker-deploy.md`, `docs/adr/0003-lift-frontend-freeze.md` |
| Feature de sequências | `docs/features/sequencias-customizadas/00-enunciado.md:1-130` |
| Pipeline de dados | `scripts/generate_data_set.py:1-92`, `data/top/merge_datasets.R:1-17` |
