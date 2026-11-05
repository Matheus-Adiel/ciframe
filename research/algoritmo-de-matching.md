# Pesquisa — algoritmo de matching de sequências de acordes

> Snapshot do código em 2026-10-31, HEAD `fb97001`. A árvore de trabalho tem
> edições não commitadas em `docs/features/sequencias-customizadas/01-research.md`
> e o diretório `research/` não rastreado.
>
> Este documento descreve **apenas o que existe hoje**. Não contém proposta,
> avaliação, diagnóstico ou trabalho futuro. As medições foram feitas lendo
> `data/top/dataset_final.csv` e importando `main.py` com `.venv/bin/python`
> (Flask disponível no venv local), sem alterar o repositório.

## Resumo

Hoje **não existe matching de sequência em tempo real**: `GET /similares?sequencia=...`
apenas consulta a coluna pré-computada `SEQ_FAMOSA`/`seqs_famosas`, e qualquer
sequência fora das 6 chaves hardcoded de `main.py:40-45` retorna `[]`
(`main.py:190-197`). A definição de "a sequência aparece na música" que existe
no repositório é a do gerador offline `get_famosas`
(`scripts/generate_data_set.py:7-24`), que exige **duas condições simultâneas**:
o bloco de acordes da sequência aparece **contíguo e na ordem exata** dentro da
cifra (`scripts/generate_data_set.py:13`) **e** a música inteira só usa acordes
que pertencem ao conjunto da sequência (`scripts/generate_data_set.py:16-20`).
A comparação do gerador é **case-insensitive** (`scripts/generate_data_set.py:12`),
mas não faz transposição, equivalência enarmônica nem simplificação de acordes
com baixo invertido. A música guarda duas visões diferentes: `musica.cifra`
preserva ordem e repetições, enquanto `musica.acordes` é `list(set(cifra))`, ou
seja, sem ordem e sem repetições (`musica.py:16-17`). Na base atual, 514 das
67.585 músicas carregadas têm alguma tag (0,76%); todas usam exatamente o
conjunto de acordes da sequência taggeada, sem acordes extras.

## Escopo e método

Arquivos lidos integralmente para esta pesquisa:

- `main.py`, `musica.py`, `scripts/generate_data_set.py`,
  `scripts/normalize_chords.R`, `scripts/simplify_chords.R`,
  `scripts/build-chords-transitions.R`, `docs/adr/0002-persist-custom-sequences.md`,
  `docs/features/sequencias-customizadas/00-enunciado.md` a `04-test-report.md`,
  `static/assets/js/controllers/sequencia.js`,
  `static/assets/js/controllers/acordes.js`,
  `static/assets/js/controllers/musica.js`, `static/templates/sequencia.html`,
  `static/assets/js/app.js`, `static/assets/js/routes.js`, `README.md`,
  `docs/adr/0001-local-only-docker-deploy.md` e
  `research/entendimento-do-repositorio.md`.

Medições executadas contra a base real:

- replicação de `get_famosas` sobre as 67.585 linhas carregadas por `main.py`;
- comparação entre as tags calculadas e as tags gravadas no CSV;
- chamadas reais a `main.app.test_client()` para as 6 sequências, páginas 1–4,
  variações de caixa/espaço e chave concatenada;
- contagem de tokens, grafias, repetições, acordes vazios e diferenças entre o
  parse do CSV e o parse de runtime.

A verificação "regra calculada x tags gravadas" está reproduzível em
`artifacts/verifica_matching.py` (execução: `.venv/bin/python
artifacts/verifica_matching.py`; sai com código 0 quando não há divergência).

## 1. Onde há matching hoje

`GET /similares` tem quatro modos, escolhidos por `if/elif` nesta ordem
(`main.py:170-201`):

| Modo | Parâmetro | O que é comparado | Unidade | Ordem importa? | Repetição importa? |
|---|---|---|---|---|---|
| Título/artista | `GET /search?key=` | tokens do texto normalizado | token | não | não |
| Acordes | `acordes=` | interseção de conjuntos | conjunto | não | não |
| Música | `id_unico_musica=` | interseção de conjuntos | conjunto | não | não |
| Sequência | `sequencia=` | índice na lista `seqs_famosas` | booleano por música | **só na geração da tag** | **só na geração da tag** |

Referências: `/search` em `main.py:114-147`; os dois modos de acordes em
`main.py:184-189` e `main.py:230-263`; o modo sequência em `main.py:190-197` e
`main.py:203-223`.

Consequências diretas da ordem do `if/elif`:

- `?acordes=...&sequencia=...` executa o modo acordes; a sequência é ignorada
  (verificado: retornou 100 resultados de acordes, não os da sequência).
- `?id_unico_musica=...&sequencia=...` executa o modo música.
- `?sequencia=` vazio é falsy e cai no modo acordes com lista vazia, que
  retorna `[]`.

O único ponto do runtime que lê `seqs_famosas` é `main.py:209`:

```python
if str(id_seq) in musica.seqs_famosas:
```

Não há chamada a `get_famosas`, nem cálculo sobre `musica.cifra` ou
`musica.acordes`, em nenhum lugar do runtime. A função `get_famosas` existe
apenas em `scripts/generate_data_set.py:7-24`, que é pipeline Python 2 e não é
importado pela aplicação.

## 2. A definição existente: o gerador de tag (offline)

### 2.1 A regra, linha por linha

`scripts/generate_data_set.py:7-24`:

```python
def get_famosas(acorde):
    seqs = ['bm;g;d;a','c;g;am;f', 'em;g' , 'c;a7;dm;g7', 'gm;f', 'c;c7;f;fm' ]
    out = []
    for i in range(len(seqs)):
        s = seqs[i]
        acorde = acorde.lower()
        if s in acorde:
            achou = True
            tem_seqs = []
            for l in acorde.split(';'):
                tokens = s.split(';')
                if l not in tokens:
                    achou = False
                    break
            if achou:
                tem_seqs.append(str(i))
                out.append("-".join(tem_seqs))
    return out
```

Componentes:

1. **Lista de sequências** (`scripts/generate_data_set.py:8`): seis strings com
   acordes separados por `;`, todas em minúsculas. Os índices 0–5 dessa lista
   são os mesmos valores do dicionário `sequencias` de `main.py:40-45`.
2. **Normalização de caixa** (`scripts/generate_data_set.py:12`): `acorde.lower()`
   é aplicado à cifra inteira. Isso é o que faz `Bm` casar com `bm`, `Am` com
   `am`, etc.
3. **Condição de ordem/contiguidade** (`scripts/generate_data_set.py:13`):
   `if s in acorde` é uma busca de substring na string inteira da cifra, com os
   `;` ainda presentes. Em termos práticos, exige que o bloco
   `bm;g;d;a` (ou a sequência em questão) apareça como **tokens adjacentes e na
   ordem exata**.
4. **Condição de conjunto fechado** (`scripts/generate_data_set.py:16-20`):
   percorre **todos** os tokens da música; se **qualquer** token não pertence
   aos tokens da sequência, a música não recebe a tag. Essa condição vale para
   a música inteira, não apenas para a janela onde a sequência aparece.
5. **Resultado** (`scripts/generate_data_set.py:22-23`): o índice vira string e
   é acumulado em `out`. A coluna final é escrita em
   `scripts/generate_data_set.py:84-88`; múltiplos índices seriam concatenados
   com `''` (sem separador).

Formalmente, para uma sequência `S` e uma cifra `C` (ambas listas de tokens,
`C` na ordem original):

```
match(S, C) = (∃ i tal que C[i : i+|S|] == S)  ∧  (set(C) ⊆ set(S))
```

com a comparação feita sobre `lower()` dos tokens.

### 2.2 Exemplos da regra (executados com a implementação acima)

| Cifra de entrada | Resultado | Motivo |
|---|---|---|
| `Bm;G;D;A` | `0` | bloco contíguo na ordem e conjunto fechado |
| `bm;g;d;a` | `0` | `lower()` torna a comparação case-insensitive |
| `Bm;G;D;A;E` | nenhum | `E` não pertence ao conjunto da sequência 0 |
| `Bm;G;Bm;D;A` | nenhum | a repetição de `Bm` quebra a contiguidade da ocorrência |
| `G;Bm;D;A` | nenhum | os quatro acordes existem, mas em outra ordem |
| `Bm;G;D;A;Bm;G;D;A` | `0` | existe uma ocorrência contígua exata |
| `D;A;Bm;G;D;A` | `0` | a sequência não precisa começar no primeiro acorde |
| `Bm;G;D;A;A` | `0` | repetir um acorde da sequência no fim não invalida |
| `Bm;G;D;A;` | nenhum | o token vazio final não pertence ao conjunto |
| `C;G;Am;F;G` | `1` | `G` extra pertence ao conjunto da sequência 1 |
| `Cm;G;Am;F` | nenhum | `Cm` não é `C`; não há equivalência de acorde |
| `C;A7;Dm;G7` | `3` | sequência 3 |
| `Em;G` | `2` | sequência 2 |
| `G;Em` | nenhum | ordem invertida |
| `Gm;F` | `4` | sequência 4 |
| `C;C7;F;Fm` | `5` | sequência 5 |

### 2.3 Verificação contra a base real

Reproduzindo `get_famosas` sobre as 67.585 músicas carregadas e comparando com o
valor gravado em `seqs_famosas`:

- **0 divergências** nas 67.585 linhas;
- 67.071 músicas sem tag e 514 com tag;
- distribuição das tags: índice `1` = 296, `0` = 199, `4` = 7, `3` = 5,
  `2` = 4, `5` = 3;
- nenhuma música tem mais de um índice.

Propriedades medidas nas 514 músicas taggeadas:

| Índice | Músicas | Nº de acordes únicos por música | Acordes fora da sequência | Começa com a sequência |
|---|---|---|---|---|
| 0 (Bm-G-D-A) | 199 | sempre 4 | 0 em todas | 88 de 199 |
| 1 (C-G-Am-F) | 296 | sempre 4 | 0 em todas | 99 de 296 |
| 2 (Em-G) | 4 | sempre 2 | 0 em todas | 3 de 4 |
| 3 (C-A7-Dm-G7) | 5 | sempre 4 | 0 em todas | 3 de 5 |
| 4 (Gm-F) | 7 | sempre 2 | 0 em todas | 7 de 7 |
| 5 (C-C7-F-Fm) | 3 | sempre 4 | 0 em todas | 3 de 3 |

Exemplo de música taggeada com repetições e ordem diferente da sequência:
`30-seconds-to-mars/city-of-angels` tem 57 acordes na cifra e apenas 4 acordes
únicos (`D`, `A`, `G`, `Bm`), com tag `0` (`main.musicas[...].cifra`,
`main.musicas[...].acordes`, `main.musicas[...].seqs_famosas`).

### 2.4 Formato da tag vs. formato de leitura

- O gerador escreve a coluna com `''.join(get_famosas(str_notas))`
  (`scripts/generate_data_set.py:88`). Vários índices virariam, por exemplo,
  `"01"`.
- O loader lê com `musica[SEQ_FAMOSA].split(";")` (`main.py:63`). Um valor `"01"`
  viraria `["01"]`, e nem `"0"` nem `"1"` casariam em `main.py:209`.
- Na base atual todas as tags têm no máximo um índice, então esse formato não
  produz efeito observado.
- O sentinela `NA` é removido antes do split por
  `line.replace('"', '').replace('NA', '')[:-1]` (`main.py:53`). Por isso
  `musica.seqs_famosas` **não** é `['NA']`: é `['']` nas 67.071 músicas sem tag
  (verificado importando `main.py`). A tag `NA` existe apenas no CSV bruto.

## 3. O caminho de runtime para sequência

### 3.1 Requisição e chave

`main.py:190-197`:

```python
elif sequencia_tag:
    acordes = sequencia_tag.replace(',','')
    similares = []

    if acordes in sequencias:
        id_seq = sequencias[acordes]
        similares = get_pagina(get_similares_por_sequencia(id_seq, generos_key), pagina_tag)
    return json.dumps(similares)
```

- A chave é formada **removendo todas as vírgulas** do parâmetro
  (`main.py:191`). Não há `strip()`, `lower()`, decodificação adicional nem
  validação contra a lista de acordes.
- A busca é `acordes in sequencias`, um `dict` com as 6 chaves de
  `main.py:40-45`; é **case-sensitive** e sensível a espaço.
- Se a chave não existir, a resposta é `[]` (`main.py:192-197`), sem erro.
- O mapa de chaves usado pelo backend é:

| Chave no dict | Índice | Lista de acordes (só no gerador) | No frontend? |
|---|---|---|---|
| `BmGDA` | 0 | `bm;g;d;a` | sim (`sequencia1`) |
| `CGAmF` | 1 | `c;g;am;f` | sim (`sequencia2`) |
| `EmG` | 2 | `em;g` | não |
| `CA7DmG7` | 3 | `c;a7;dm;g7` | não |
| `GmF` | 4 | `gm;f` | sim (`sequencia3`) |
| `CC7FFm` | 5 | `c;c7;f;fm` | sim (`sequencia4`) |

As listas de acordes dos índices existem em
`scripts/generate_data_set.py:8` (minúsculas), os nomes legíveis em
`data/mapeamento_sequencias_famosas.txt:1-6`, e apenas 4 das 6 aparecem em
`static/assets/js/controllers/sequencia.js:2-37`. O dicionário de `main.py`
guarda somente chave concatenada → índice; não guarda a lista de acordes.

### 3.2 Chamadas reais ao endpoint

Executadas com `main.app.test_client()` sobre a base carregada:

| Requisição | Resultado |
|---|---|
| `/similares?sequencia=Bm,G,D,A` | HTTP 200, `Content-Type: text/html`, 100 itens (página 1 de 199) |
| `/similares?sequencia=BmGDA` | mesmo resultado da linha anterior |
| `/similares?sequencia=Bm,%20G,%20D,%20A` | `[]` (espaços entram na chave) |
| `/similares?sequencia=bm,g,d,a` | `[]` (chave case-sensitive) |
| `/similares?sequencia=CA7,Dm,G7` | 5 itens, os mesmos de `C,A7,Dm,G7` (a chave coincide) |
| `/similares?sequencia=Em,G` | 4 itens: `planet-hemp_mao-na-cabeca`, `marcelo-d2_mao-na-cabeca`, `ultraje-a-rigor_inutil`, `eric-clapton_fall-like-rain` (a ordem variou entre processos) |
| `/similares?sequencia=X,Y` | `[]` |
| `/similares?sequencia=Bm,G,D,A&pagina=2` | 99 itens (fecha as 199) |
| `/similares?sequencia=Bm,G,D,A&generos=MPB` | 1 item |
| `/similares?acordes=C&sequencia=Bm,G,D,A` | 100 itens do modo acordes; sequência ignorada |

Para cada um dos 6 índices, a união das páginas 1–4 retornou exatamente o
conjunto de músicas cuja tag é aquele índice (199, 296, 4, 5, 7 e 3,
respectivamente), sem duplicatas.

### 3.3 Forma da resposta e ordenação

`get_similares_por_sequencia` (`main.py:203-223`) monta os campos:

`id_unico_musica`, `id_artista`, `id_musica`, `nome_artista`, `nome_musica`,
`popularidade`, `acordes`, `genero`, `url`.

Não há `diferenca` nem `intersecao` nessa resposta (comparar com
`main.py:246-258`, que os inclui nos modos de acordes). `acordes` é a lista
`list(set(cifra))`, sem ordem musical.

A ordenação e a paginação vêm de:

- `apply_filtro` (`main.py:266-272`), que concatena `genero_musicas[g]` para cada
  `g` da lista de gêneros;
- `genero_musicas[g]` ordenado por popularidade (`main.py:94-96`);
- `generos` convertido de `set` para `list` (`main.py:92`), com ordem dependente
  do hash de cada processo;
- `get_pagina` (`main.py:226-228`), com `TAM_PAGINA = 100` (`main.py:35`).

Sem `generos`, a coleção percorre os gêneros na ordem arbitrária da lista e cada
gênero em ordem de popularidade. Com `generos`, a coleção é a lista daquele
gênero, em popularidade. O endpoint não reordena o resultado.

Efeito observado: como as sequências 0 e 1 têm 199 e 296 músicas, a página 1
(100 itens) é um recorte dessa ordem. Em dois processos distintos, a página 1
de `BmGDA` começou com músicas diferentes:

- processo A: `avioes-do-forro_balada-boa`, `avioes-do-forro_da-agua-pro-vinho`, …
- processo B: `antonio-cirilo_cetro-de-justica`, `arena-louvor_o-maior-milagre`, …

O frontend não envia `pagina` (usa o default 1) e ordena apenas os itens
recebidos por `-popularidade` (`static/templates/sequencia.html:42`).

### 3.4 Frontend

`#/porsequencia` (`static/assets/js/routes.js:17-19`) usa
`SequenciaController` (`static/assets/js/controllers/sequencia.js:1-105`):

- 4 sequências hardcoded: `Bm-G-D-A`, `C-G-Am-F`, `Gm-F`, `C-C7-F-Fm`
  (`sequencia.js:2-37`);
- cada objeto tem um campo `index: 1` (`sequencia.js:3, 11, 19, 25`), que não é
  lido nem enviado em nenhum ponto (o `grep` por `.index` no JS só encontra
  `indexOf`);
- `createChordsString` monta `"Bm,G,D,A"` (`sequencia.js:55-61`);
- a requisição é `similares?sequencia=<acordes>` com gênero opcional
  (`sequencia.js:63-90`, URL em `sequencia.js:73`);
- o template clica na sequência (`sequencia.html:6`), lista os hexágonos
  (`sequencia.html:34`) e renderiza os resultados com
  `ng-hide="music.diferenca.length"` (`sequencia.html:40-43`); como a resposta
  de sequência não tem `diferenca`, todos aparecem no primeiro bloco;
- não há formulário de cadastro de sequência em `sequencia.html` (o arquivo tem
  63 linhas e só contém seleção das 4 sequências, filtro de gênero e
  resultados).

## 4. Respostas às perguntas da pesquisa

### 4.1 O que define "a sequência X aparece na música Y"?

Hoje:

- **Para as 6 sequências do backend**: a música aparece se a string
  `str(id_seq)` está na lista `musica.seqs_famosas` (`main.py:209`), preenchida
  pelo CSV. A definição que produziu esse valor é a regra de
  `scripts/generate_data_set.py:7-24` descrita na seção 2.1:
  `∃ ocorrência contígua na ordem exata` **e** `todos os acordes da música
  pertencem ao conjunto da sequência`.
- **Para uma sequência que não seja uma das 6 chaves**: a resposta é `[]`
  (`main.py:190-197`). Não há cálculo em tempo real, nem em `musica.cifra`, nem
  em `musica.acordes`, nem em qualquer outra estrutura. Não há armazenamento de
  sequências cadastradas (não há tabela, arquivo ou variável de catálogo
  customizado).

### 4.2 A ordem dos acordes importa?

- **No gerador de tag, sim**: a condição `s in acorde`
  (`scripts/generate_data_set.py:13`) exige um bloco contíguo na ordem exata.
  `G;Bm;D;A` não recebe a tag da sequência `Bm;G;D;A`.
- **No runtime, não há avaliação de ordem**: o endpoint compara apenas o índice
  na lista de tags. A ordem só existe na tag já calculada.
- **Em `musica.acordes`, a ordem não existe**: é `list(set(cifra))`
  (`musica.py:17`), sem ordem musical. A ordem (e a posição) só está disponível
  em `musica.cifra` (`musica.py:16`), que é a lista na ordem do CSV.
- A ordem de iteração de `musica.acordes` não é estável entre processos, por
  causa da randomização de hash de `str` no `set`. Exemplo: em três execuções,
  `list(set(['C','G','Am','F','D','Em']))` produziu três ordens diferentes.

Para dimensionar a condição de ordem na base atual, foram medidas quatro
propriedades sobre `musica.cifra` (todas com `lower()`), sem alterar o código:

| Índice | Bloco contíguo na ordem | Subsequência ordenada (não contígua) | Todos os acordes da sequência presentes (qualquer ordem) | Só acordes da sequência (cifra não vazia) | Regra atual (contígua + conjunto fechado) |
|---|---|---|---|---|---|
| 0 | 866 | 4.763 | 5.768 | 873 | **199** |
| 1 | 1.216 | 5.887 | 6.894 | 958 | **296** |
| 2 | 3.110 | 13.643 | 14.160 | 24 | **4** |
| 3 | 96 | 427 | 582 | 53 | **5** |
| 4 | 1.039 | 3.641 | 3.847 | 18 | **7** |
| 5 | 132 | 280 | 365 | 57 | **3** |

Nenhuma das colunas intermediárias está implementada no código; elas só
descrevem quantas músicas satisfazem cada condição isoladamente. Exemplos
concretos de músicas que satisfazem uma condição e não a regra atual:

- `skank/sutilmente`: `bm` e `g` na posição 40–41, `d` na 47 e `a` na 61
  (`musica.cifra`), ou seja, subsequência ordenada sem bloco contíguo; não tem
  tag 0.
- `pitty/equalize`: janela contígua `d;bm;a;g` na posição 28; tem os quatro
  acordes, mas em outra ordem; não tem tag 0.
- `victor-leo/fotos`: contém `C;G;Am;F` contíguo, mas contém também `Dm`; não
  tem tag 1 porque `Dm` não pertence ao conjunto `{c,g,am,f}`.

### 4.3 Repetições de acorde dentro da música importam?

- A tag é **booleana por música**: existe ou não, uma vez só. Não há contagem de
  ocorrências, posição, frequência ou score em `musica.seqs_famosas`
  (`main.py:209`, `main.py:216-220`).
- Repetições **fora** da ocorrência que casa são permitidas: uma música pode
  repetir acordes da sequência à vontade desde que exista pelo menos um bloco
  contíguo igual à sequência e nenhum acorde fora do conjunto. Exemplo:
  `30-seconds-to-mars/city-of-angels` tem 57 acordes e é tag 0.
- Uma repetição **dentro** do bloco quebra aquela ocorrência específica:
  `Bm;G;Bm;D;A` não casa com `Bm;G;D;A`; se houver outra ocorrência contígua
  limpa em outro ponto da música, a tag existe mesmo assim.
- 58.906 das 67.585 músicas (87,2%) têm pelo menos um acorde repetido na cifra;
  a média é 8,34 tokens por acorde único, e a maior cifra tem 2.065 tokens
  (medido após `limpa_cifra`).
- `musica.acordes` não permite observar repetição: o `set` remove duplicatas
  (`musica.py:17`). A contagem só existe em `musica.cifra`.
- Entre as 514 músicas taggeadas, 511 têm repetição de algum acorde; 311 não
  começam com a sequência no primeiro acorde.

### 4.4 É preciso normalizar?

O que existe hoje:

- **Caixa**: o gerador aplica `acorde.lower()` na cifra inteira
  (`scripts/generate_data_set.py:12`). Isso é **necessário** para as tags
  atuais: a base usa `Bm`, `Am`, `Gm`, etc., e as sequências do gerador estão em
  minúsculas. Reproduzindo a regra sem `lower()`, **nenhuma** das 514 tags
  casa (514 divergências); com `lower()`, 0 divergências.
- **Chave de busca do endpoint**: só remove vírgulas (`main.py:191`). Não
  aplica `lower()`, não remove espaço, não remove acento. `bm,g,d,a` e
  `Bm, G, D, A` retornam `[]`; `BmGDA` e `Bm,G,D,A` retornam o mesmo resultado.
- **Transposição**: não existe no matching. `musica.tom` é carregado
  (`main.py:71`, `musica.py:15`) e devolvido em `/musicas`, mas não é lido por
  `get_similares_por_sequencia` nem pelo gerador de tag. As músicas taggeadas da
  sequência 0 têm tom `D` em 197 casos, `C` em 1 e `A` em 1; as da sequência 4
  têm `F` em 6 e `A#` em 1.
- **Equivalência enarmônica**: não existe. `C#` e `Db` são tokens distintos na
  base; não há tabela de aliases no runtime. Contagens de tokens exatos na base:
  `C#` 23.902 / `Db` 4.084; `D#` 12.146 / `Eb` 23.626; `F#` 49.288 / `Gb` 1.401;
  `G#` 21.349 / `Ab` 12.259; `A#` 10.134 / `Bb` 59.730.
- **Acordes com baixo invertido**: são tokens próprios, não são reduzidos ao
  acorde base. Na base há 3.536 grafias distintas com uma `/` e 266.096
  ocorrências; as mais frequentes são `D/F#` (24.177), `G/B` (20.125),
  `E/G#` (11.154), `A/C#` (10.710), `C/E` (8.203). `E/B`, por exemplo, não é
  tratado como `E`.
- **Variações de sufixo**: são tokens distintos. `C`, `C7`, `Cm`, `C7M` são
  acordes diferentes para o matching; não há redução a tríade.
- **Caixa como colisão**: 150 grafias distintas colidem quando passadas por
  `lower()`, incluindo pares como `AM7`/`Am7`, `CM7`/`Cm7`, `GM7`/`Gm7`,
  `DM7`/`Dm7`, `EM7`/`Em7`, `BM7`/`Bm7`, `F#M7`/`F#m7`, `C#M7`/`C#m7`,
  `EB`/`Eb`, `Ebsus7`/`ebsus7`. O `lower()` do gerador torna essas grafias
  indistintas.
- **Tokens minúsculos na base**: 139 ocorrências, 22 grafias distintas, sendo a
  maioria fragmentos (`#11`, `9/11`, `add9`, `b13`, `4`, `7`, `)`, `m`, `2x`,
  `e|-`) e algumas grafias de acorde (`ebsus7`, `eb7b9b5`, `c7m(5+)/e`). Quatro
  dessas 22 têm outra grafia do mesmo `lower()` na base.
- **Espaço e tabulação dentro de célula**: 57 células da coluna `CIFRA` têm
  espaço interno; `limpa_cifra` (`main.py:11-23`) quebra essas células em
  tokens separados. Em 44 linhas o resultado de `limpa_cifra` difere de um
  `split(';')` simples. Nenhuma dessas 44 linhas tem tag.
- **Tab/pipe**: 6 linhas têm `|` na cifra; `limpa_cifra` pega apenas o primeiro
  token antes do `|` (`main.py:16-18`), gerando tokens como `e`, `Bb`, `Gb`,
  `Db`, `D/E`, `Abdim7` a partir de linhas de tablatura.
- **Normalização por graus**: existe no repositório em
  `scripts/normalize_chords.R:1-41` e `scripts/simplify_chords.R:1-36`, que
  usam `data/transposition_matrix2.csv` para converter acorde+tom em grau
  (`I`, `IV`, `V`…), e em `data/dataset_seq_notas.csv`, que guarda `CIFRA` e
  `NCIFRA` por música. Nenhum desses artefatos é lido pelo `main.py` em
  runtime; `grep` por `normalize_chords`, `NCIFRA` e
  `transposition_matrix` no backend não retorna chamadas.

## 5. Estruturas de dados relevantes

### 5.1 `Musica`

`musica.py:1-25`:

| Campo | Origem | Ordem? | Repetição? | Usado no matching de sequência? |
|---|---|---|---|---|
| `cifra` | `limpa_cifra` sobre o índice 8 / 9ª coluna (`main.py:58-61`) | sim | sim | não no runtime; é a fonte da tag no gerador |
| `acordes` | `list(set(cifra))` (`musica.py:17`) | não | não | não |
| `seqs_famosas` | índice 7 / 8ª coluna, dividido por `;` (`main.py:63`) | lista de 1 item | não | sim (`main.py:209`) |
| `tom` | coluna 6 (`main.py:71`) | — | — | não |
| `id_unico_musica` | `"<id_artista>_<id_musica>"` (`musica.py:20`) | — | — | identifica a música na resposta |
| `url` | cifraclub (`musica.py:22`) | — | — | devolvido na resposta |

### 5.2 Carga e transformações do CSV

`main.py:49-98`:

1. `f.readline()` descarta a primeira linha (`main.py:50`), que é um registro
   real (`14-bis,a-qualquer-tempo,...`), não cabeçalho. Essa música não existe
   em `main.musicas` (verificado).
2. `line.replace('"','').replace('NA','')[:-1]` (`main.py:53`): remove aspas,
   remove **todas** as ocorrências de `NA` e remove o último caractere (o
   `\n`). No CSV bruto, `NA` só aparece como valor de campo inteiro: 8.141 em
   `CIFRA` e 67.072 em `SEQ_FAMOSA` (67.071 nas linhas carregadas, pois a
   primeira é descartada); nenhum token de acorde contém `NA`.
3. `line.split(',')` (`main.py:55`): split simples, sem módulo `csv`.
4. `limpa_cifra` (`main.py:11-23`): ignora tokens vazios, trata `|` e divide
   por espaço.
5. Popularidade vira `int` sem pontos (`main.py:56`).
6. `seqs_famosas` vira `split(';')` (`main.py:63`).
7. `Musica` é criada (`main.py:69-72`) e inserida em `musicas_dict`
   (`main.py:74`).

Resultado observado: 67.585 músicas, 52 gêneros, 6.653 acordes distintos,
8.141 músicas com `cifra == []` e `acordes == []`. O CSV tem 67.586 linhas e
9 colunas; não há músicas duplicadas por `id_unico_musica` nesta base
(67.585 linhas carregadas = 67.585 chaves no `OrderedDict`).

## 6. Fluxos ponta a ponta

### 6.1 Geração offline da tag

```
HTML do cifraclub
  -> soup.find(id="cifra_tom").parent.find_all('b')        (generate_data_set.py:70)
  -> str_notas = acordes separados por ';'                  (generate_data_set.py:71-76)
  -> get_famosas(str_notas)                                (generate_data_set.py:86)
     -> lower()                                             (generate_data_set.py:12)
     -> substring contígua na ordem                         (generate_data_set.py:13)
     -> todos os acordes da música dentro da sequência      (generate_data_set.py:16-20)
  -> famosas = ''.join(...) ou 'NA'                         (generate_data_set.py:85-88)
  -> linha do CSV (índice 7 = SEQ_FAMOSA)                   (generate_data_set.py:89)
```

### 6.2 Carga no processo Flask

```
main.py import
  -> f.readline() descarta a 1ª linha                       (main.py:50)
  -> replace('NA','') / [:-1] / split(',')                  (main.py:53-55)
  -> limpa_cifra -> cifra ordenada com repetições           (main.py:58-61)
  -> seqs_famosas = split(';')                              (main.py:63)
  -> Musica(cifra=..., acordes=list(set(cifra)), seqs_famosas=...)
                                                             (main.py:69-72, musica.py:16-18)
  -> musicas_dict / musicas / genero_musicas / generos / acordes
                                                             (main.py:74-96)
```

### 6.3 Busca por sequência

```
sequencia.html (clique em uma das 4 sequências)
  -> SequenciaController.pesquisarPorSequencia                (sequencia.js:63)
  -> createChordsString -> "Bm,G,D,A"                         (sequencia.js:55-61)
  -> GET /similares?sequencia=Bm,G,D,A[&generos=...]          (sequencia.js:73-77)
  -> sequencia_tag.replace(',','') -> "BmGDA"                 (main.py:191)
  -> sequencias["BmGDA"] -> 0                                 (main.py:40-45, 194-195)
  -> get_similares_por_sequencia(0, generos_key)              (main.py:196, 203-223)
     -> apply_filtro(musicas.values(), generos_key)           (main.py:205, 266-272)
     -> if str(0) in musica.seqs_famosas                      (main.py:209)
     -> dict com 9 campos                                     (main.py:210-220)
  -> get_pagina(..., pagina_tag)                              (main.py:196, 226-228)
  -> json.dumps(...)                                          (main.py:197)
  -> frontend ordena a página por -popularidade               (sequencia.html:42)
```

### 6.4 Contraste com o modo acordes

O modo `?acordes=` usa `musica.acordes` e trata a música como conjunto:

```
acordes_tag.split(',')                                        (main.py:185-186)
set(acordes) ∩ set(musica.acordes)                            (main.py:240)
set(musica.acordes) - set(acordes)                            (main.py:241)
if len(inter) > 0                                             (main.py:245)
sort por (len(diferenca), -len(intersecao))                   (main.py:263)
```

Esse é o único caminho do runtime que compara acordes da música com acordes
pedidos; ele não usa ordem, repetição, posição nem `musica.cifra`.

## 7. Fatos observados que afetam a reprodução dos resultados atuais

- 514 de 67.585 músicas têm tag: 0 → 199, 1 → 296, 2 → 4, 3 → 5, 4 → 7, 5 → 3.
- Todas as músicas taggeadas usam exatamente o conjunto de acordes da sequência
  (0 acordes fora do conjunto em todas as 514).
- 8.141 músicas têm cifra vazia e não podem casar com nenhuma das 6 sequências.
- A primeira linha do CSV não é carregada; `14-bis_a-qualquer-tempo` não existe
  em `main.musicas`.
- `musica.seqs_famosas` é `['']` para músicas sem tag, não `['NA']`.
- A resposta de sequência é paginada em 100 itens
  (`main.py:196`, `main.py:35`); as sequências 0 e 1 têm mais de 100 músicas.
- Sem `generos`, a ordem da página 1 depende da ordem de `generos`
  (`main.py:92`) e muda entre processos; com `generos`, a ordem é a da lista
  daquele gênero, por popularidade.
- A resposta de sequência não inclui `diferenca` nem `intersecao`
  (`main.py:210-220`); as respostas dos modos de acordes incluem
  (`main.py:246-258`).
- A chave de sequência não tem separador: `Bm,G,D,A`, `BmGDA` e
  `CA7,Dm,G7`/`C,A7,Dm,G7` produzem as mesmas chaves; `bm,g,d,a` e
  `Bm,%20G,%20D,%20A` produzem `[]`.
- O backend tem 6 sequências; o frontend tem 4, e as duas do backend que não
  aparecem na UI são `Em-G` (índice 2) e `C-A7-Dm-G7` (índice 3).
- O campo `index` dos objetos JS é sempre `1` e não é usado.
- Os 4 objetos JS não têm formulário de cadastro; a página só lista sequências
  fixas.
- Não há persistência de sequência customizada em nenhum lugar do runtime.
- O gerador de tag está em Python 2 (`print`, `reload(sys)`,
  `setdefaultencoding`) e não é executado pela aplicação.

## 8. Contexto histórico registrado no Git

- `536114e` (2015-12-13) adiciona `scripts/generate_data_set.py`, incluindo
  `get_famosas` com a regra descrita acima.
- `3b4d191` (2016-05-17) introduz o dicionário `sequencias` e
  `get_similares_por_sequencia` baseado em `musica.seqs_famosas`; antes disso, a
  busca por sequência em `back-end/api.py` era tratada pelo mesmo
  `get_similares` do modo acordes, com um parâmetro `is_sequencia` que não era
  usado no corpo da função (interseção de conjuntos).
- O commit atual `fb97001` altera apenas `docs/features/sequencias-customizadas/00-enunciado.md`.

Esses commits são citados apenas como registro do que existe no histórico; o
comportamento documentado nas seções anteriores é o do código em `fb97001`.

## Referências principais

| Assunto | Arquivo:linhas |
|---|---|
| Lista das 6 sequências no backend | `main.py:40-45` |
| Parse da requisição `/similares` | `main.py:170-201` |
| Ramo de sequência e chave sem vírgulas | `main.py:190-197` |
| Filtro por tag `seqs_famosas` | `main.py:203-223` |
| Paginação | `main.py:35`, `main.py:226-228` |
| Modo acordes (conjunto) | `main.py:230-263` |
| Filtro por gênero | `main.py:266-272` |
| Carga do CSV e transformações | `main.py:49-98` |
| `limpa_cifra` | `main.py:11-23` |
| Colunas do CSV | `main.py:25-34` |
| `Musica.cifra` / `Musica.acordes` / `Musica.seqs_famosas` | `musica.py:16-18` |
| Regra offline `get_famosas` | `scripts/generate_data_set.py:7-24` |
| Lista de acordes das 6 sequências no gerador | `scripts/generate_data_set.py:8` |
| Escrita da coluna `SEQ_FAMOSA` | `scripts/generate_data_set.py:84-89` |
| Nomes legíveis das sequências | `data/mapeamento_sequencias_famosas.txt:1-6` |
| Normalização por graus (não usada no runtime) | `scripts/normalize_chords.R:1-41`, `scripts/simplify_chords.R:1-36`, `data/transposition_matrix2.csv:1-8` |
| Sequências no frontend | `static/assets/js/controllers/sequencia.js:2-37` |
| Montagem da URL no frontend | `static/assets/js/controllers/sequencia.js:55-77` |
| Template e ordenação da página | `static/templates/sequencia.html:6-59` |
| Rota `#/porsequencia` | `static/assets/js/routes.js:17-19` |
| Enunciado da feature não implementada | `docs/features/sequencias-customizadas/00-enunciado.md:26-77` |
