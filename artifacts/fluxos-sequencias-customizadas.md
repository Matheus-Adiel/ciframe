# Fluxos de execução — Sequências de Acordes Customizadas

> Artefato de apoio ao [`03-plan.md`](../docs/features/sequencias-customizadas/03-plan.md).
> Descreve os fluxos ponta a ponta entre visitante, frontend AngularJS, backend
> Flask, catálogo SQLite e índice de matching. Também separa o que já está
> decidido do que precisa de validação antes da implementação.
>
> Este documento existe para o agente de implementação não precisar reler
> `01-research.md`, `02-proposal.md` e os três documentos de `artifacts/reppit/research/` a cada
> tarefa.

## 1. Atores e componentes

| Ator/Componente | Papel |
|---|---|
| Visitante | Pessoa anônima que abre `#/porsequencia`, cadastra sequências e busca músicas. |
| Navegador/AngularJS | `static/assets/js/controllers/sequencia.js` + `static/templates/sequencia.html`; consome a API por URLs relativas. |
| Flask (`main.py`) | Rotas, validação de parâmetros, paginação, filtro por gênero e respostas `json.dumps`. |
| `CatalogoSequencias` (`sequencias_store.py`, novo) | Schema, seeds, leitura/escrita no SQLite, normalização de `chave`, dedupe e contagem. |
| `IndiceSequencias` (`matching.py`, novo) | Regra de matching, mapa `id_unico_musica -> posição`, cache de bitsets e lock. |
| SQLite | Arquivo em `DECIFRAME_DB` (`/data/deciframe.db` na imagem, `./var/deciframe.db` local). |
| CSV em memória | `data/top/dataset_final.csv` carregado no import; fonte de músicas, gêneros, cifras e tags. |
| Operador/Docker | Sobe o container, cria/monta o volume, reinicia e faz backup. |

Convenções:

- `S` = lista ordenada de acordes da sequência; `C` = `musica.cifra` (com ordem
  e repetições).
- `chave` = `json.dumps([a.strip().lower() for a in S])`; é a identidade usada
  para deduplicar.
- `id_seq` = chave primária da tabela `sequencias`.
- Um único worker do gunicorn. Índice, cache e rate limit são por processo.
- Toda resposta é `json.dumps(...)` com `Content-Type: text/html`, inclusive
  erros.
- A ordem da coleção é a de `apply_filtro(musicas.values(), generos_key)`; a
  busca por sequência não reordena.

```text
Visitante
  -> AngularJS (#/porsequencia)
  -> Flask main.py
       -> CatalogoSequencias -> SQLite (DECIFRAME_DB)
       -> IndiceSequencias -> cache bytearray
       -> musicas (CSV em memória)
```

## 2. Mapa dos casos de uso

| ID | Caso de uso | Ator | Gatilho | Resultado |
|---|---|---|---|---|
| UC-01 | Inicialização | Operador/Docker | gunicorn importa `main.py` | CSV carregado, SQLite pronto, seeds indexadas |
| UC-02 | Listar catálogo | Visitante | abre `#/porsequencia` | lista de sequências |
| UC-03 | Cadastrar sequência | Visitante | envia lista de acordes | `201`/`200` + sequência persistida |
| UC-04 | Buscar por `sequencia_id` | Visitante | seleciona sequência | músicas paginadas |
| UC-05 | Buscar pelo alias `sequencia` | Visitante/legado | URL antiga | músicas paginadas |
| UC-06 | Interação no frontend | Visitante | navega/cadastra/filtra | UI atualizada |
| UC-07 | Persistência | Operador | restart/recria container | catálogo preservado |
| UC-08 | Regressão das 6 seeds | Desenvolvedor | roda testes | mesmos conjuntos de hoje |
| UC-09 | Resolução de parâmetros | Sistema | `GET /similares` | modo escolhido por precedência |
| UC-10 | Erros e limites | Sistema | request inválida/grande | JSON + status coerente |

## 3. Fluxos detalhados

### UC-01 — Inicialização do processo

**Pré-condições:** imagem construída; volume `/data` montado ou diretório local
gravável; CSV presente.

1. **Operador** executa `docker run --name deciframe -p 8080:8080 -v
   deciframe-data:/data ciframe`.
2. **gunicorn** inicia **1 worker** e importa `main.py`.
3. **Flask/main.py** carrega `data/top/dataset_final.csv` para a memória
   (comportamento atual, `main.py:49-98`).
4. **CatalogoSequencias** resolve `DECIFRAME_DB`; cria o diretório pai se
   necessário; abre o SQLite; aplica `journal_mode=WAL` e `busy_timeout`.
5. **CatalogoSequencias** lê `PRAGMA user_version`. Se for `0`, executa
   `CREATE TABLE IF NOT EXISTS`, grava `user_version = 1` e segue.
6. **CatalogoSequencias** insere as seeds 0–5 com `INSERT OR IGNORE` e
   `origem='original'`; `criado_em` é o instante da primeira inicialização.
7. **Flask/main.py** lista o catálogo e cria o `IndiceSequencias` com o mapa de
   posições de todas as músicas.
8. **IndiceSequencias** calcula eagerly os bitsets das seeds 0–5 e os guarda no
   cache.
9. **Flask** fica pronto; `GET /generos` e `GET /sequencias` respondem.

**Alternativas e erros:**

| Situação | Comportamento esperado | Decisão |
|---|---|---|
| Volume vazio | Cria schema, insere seeds, indexa 0–5 | — |
| Volume com customizadas | Seeds ignoradas; customizadas calculadas lazy na primeira busca | — |
| SQLite inacessível/sem permissão | Aborta o startup com erro claro; sem fallback | O-01 (confirmado) |
| `user_version > 1` | Aborta o startup com erro de versão | O-02 |
| Seed existente com acordes diferentes | Falha de integridade ou mantém a linha? | O-03 |
| CSV ausente | Falha no import (comportamento atual) | — |

**Pós-condições:** schema v1 garantido; 6 seeds presentes; bitsets 0–5 em
cache; nenhuma customizada foi calculada ainda.

**Tempo esperado:** ~3,4 s de CSV + ~1 s de seeds.

### UC-02 — Listar o catálogo (`GET /sequencias`)

**Pré-condições:** UC-01 concluído.

1. **Visitante** abre `#/porsequencia`.
2. **AngularJS** dispara `GET /sequencias`.
3. **Flask** chama `CatalogoSequencias.listar()`.
4. **SQLite** executa `SELECT id, acordes, origem, criado_em FROM sequencias
   ORDER BY id`.
5. **Flask** converte `acordes` de JSON para lista e responde `200` com
   `json.dumps`.
6. **AngularJS** adapta cada acorde para `{acorde, cor}`, guarda o `id` da
   sequência e renderiza com `df-hex`.

**Resposta de sucesso:**

```json
[
  {"id": 0, "acordes": ["Bm", "G", "D", "A"], "origem": "original", "criado_em": "..."},
  {"id": 1, "acordes": ["C", "G", "Am", "F"], "origem": "original", "criado_em": "..."},
  {"id": 6, "acordes": ["C", "Am", "F", "G"], "origem": "customizada", "criado_em": "..."}
]
```

**Alternativas e erros:**

| Situação | Comportamento esperado | Decisão |
|---|---|---|
| Falha de rede/DB | UI mostra mensagem de erro; **não** inventa lista local | O-04 |
| Catálogo vazio | Estado vazio explícito (não deve ocorrer com seeds) | O-15 |
| Linha com JSON inválido | Fail-fast ou ignorar a linha? | O-03 |

### UC-03 — Cadastrar sequência (`POST /sequencias`)

**Pré-condições:** UC-01 concluído; visitante na página `#/porsequencia`.

**Fluxo principal:**

1. **Visitante** digita a sequência (por exemplo `C, G, Am, F`) e,
   opcionalmente, clica em chips de sugestão.
2. **AngularJS** separa por vírgula e/ou espaço, remove tokens vazios, preserva
   a ordem e mostra a dica “2 a 8 acordes”.
3. **AngularJS** envia `POST /sequencias` com `{"acordes": ["C", "G", "Am",
   "F"]}`.
4. **Flask** aplica `MAX_CONTENT_LENGTH` (16 KB); corpo maior retorna `413`.
5. **Flask** verifica o rate limit por IP (10/min); excedeu, retorna `429` com
   `Retry-After`.
6. **Flask** faz `request.get_json(silent=True)`; se não for JSON válido,
   retorna `400`.
7. **Flask** valida: corpo é objeto, `acordes` é lista, cada token é string;
   aplica `strip`, descarta vazios; se sobrar zero, retorna `400`.
8. **CatalogoSequencias** calcula a `chave` normalizada.
9. **CatalogoSequencias** procura duplicata pela `chave`; se existir, retorna
   `200` com a sequência existente.
10. **CatalogoSequencias** conta as customizadas; se já houver 500, retorna
    `429`.
11. **CatalogoSequencias** insere a nova linha e obtém o `id` (a partir de 6).
12. **IndiceSequencias** calcula o bitset da nova sequência e o guarda no
    cache.
13. **Flask** responde `201` com `{id, acordes, origem, criado_em}`.
14. **AngularJS** mostra “Sequência cadastrada”, recarrega o catálogo,
    seleciona a sequência retornada e dispara a busca (UC-04).

**Máquina de estados do POST:**

```text
[recebido]
  -> 413  (corpo > 16 KB)
  -> 429  (rate limit)
  -> 400  (JSON inválido / tipo inválido / lista vazia)
  -> 200  (duplicata: mesma chave de seed ou customizada)
  -> 429  (teto de 500 customizadas)
  -> 201  (inserida)
  -> [bitset calculado e cacheado]
```

A ordem acima (rate limit antes da validação) está confirmada em O-18.

**Matriz de validação:**

| Entrada | Status | Resultado |
|---|---|---|
| `{"acordes": ["C"]}` | `201` | aceito; não há mínimo rígido |
| `{"acordes": ["C","G","Am","F","G","D","A","E","B"]}` | `201` | aceito; não há máximo rígido |
| `{"acordes": []}` | `400` | lista vazia |
| `{"acordes": ["  ", ""]}` | `400` | só tokens em branco |
| `{"acordes": "C,G"}` | `400` | `acordes` não é lista |
| `{"acordes": [1, 2]}` | `400` | token não-string |
| `{"foo": ["C"]}` | `400` | falta `acordes` |
| corpo não-JSON | `400` | corpo inválido |
| `{"acordes": ["C","C","G"]}` | `201` | distinto de `C,G`; repetição preservada |
| `{"acordes": ["c"," g "]}` | `200` se `C,G` já existe | caixa/espaço normalizados na `chave` |
| `{"acordes": ["Bm","G","D","A"]}` | `200` | duplicata da seed 0; retorna `id=0` |
| corpo > 16 KB | `413` | limite de corpo |
| 11º POST no mesmo minuto/IP | `429` | `Retry-After` presente |
| 501ª customizada | `429` | teto; duplicata ainda retorna `200` |

**Alternativas e erros:**

| Situação | Comportamento esperado | Decisão |
|---|---|---|
| Corrida no `UNIQUE` | Capturar `IntegrityError`, reler pela `chave` e retornar `200` | — |
| Falha de escrita no SQLite | `500` com JSON, não HTML padrão | O-05 |
| Falha ao calcular o bitset no POST | Linha já persistida; retorna `201` e a busca recalcula lazy | O-06 (confirmado) |
| Duplicata de seed | `200` com o ID da seed; seeds não são alteradas | — |
| Catálogo cheio e sequência duplicada | Duplicata é checada antes do teto; retorna `200` | — |

**Pós-condições:** linha persistida; bitset em cache; catálogo passa a incluir a
sequência; a busca já pode usá-la.

### UC-04 — Buscar por `sequencia_id` (`GET /similares?sequencia_id=`)

**Pré-condições:** catálogo inicializado; visitante selecionou uma sequência ou
acabou de cadastrar.

1. **AngularJS** monta `GET /similares?sequencia_id=<id>` e, se houver filtro,
   `&generos=<gênero>`.
2. **Flask** lê `sequencia_id`, `generos` e `pagina`.
3. **Flask** tenta converter `sequencia_id` para inteiro e busca no catálogo.
   Se for inválido, inexistente ou não numérico, responde `200` com `[]`.
4. **IndiceSequencias** devolve o bitset: seeds já estão em cache; customizadas
   são calculadas na primeira busca e cacheadas.
5. **Flask** monta a coleção com `apply_filtro(musicas.values(), generos_key)`.
6. **Flask** percorre a coleção na ordem atual; para cada música, testa o bit
   correspondente no bitset.
7. **Flask** monta os 9 campos atuais (`id_unico_musica`, `id_artista`,
   `id_musica`, `nome_artista`, `nome_musica`, `popularidade`, `acordes`,
   `genero`, `url`), sem `diferenca` nem `intersecao`.
8. **Flask** pagina com `get_pagina` (100 itens) e responde `200`.
9. **AngularJS** faz `orderBy:'-popularidade'`, renderiza e abre a cifra no
   clique.

**Alternativas e erros:**

| Situação | Comportamento esperado | Decisão |
|---|---|---|
| `sequencia_id` inválido/inexistente | `200` com `[]` (não é erro) | — |
| Nenhuma música casa | `200` com `[]` | — |
| `pagina` além do fim | `200` com `[]` | — |
| Gênero inexistente | `[]` (comportamento atual de `apply_filtro`) | — |
| Falha ao calcular bitset lazy | `500` JSON, sem mascarar como `[]` | O-07 (confirmado) |
| Duas requisições pedem a mesma customizada | Ambas podem calcular; resultado idempotente; cache recebe o último | — |

**Resposta de sucesso:** lista paginada com os 9 campos atuais, na ordem da
coleção filtrada. A ordenação por popularidade continua sendo feita no
frontend. Manter a ordem da coleção no servidor está confirmado em O-13.

**Tempo esperado:** seed em cache → O(n) barato; customizada na primeira busca →
+0,1–0,4 s; buscas seguintes → O(n) barato.

### UC-05 — Buscar pelo alias legado (`GET /similares?sequencia=`)

**Pré-condições:** as mesmas do UC-04.

1. **Flask** lê o valor de `sequencia`.
2. **Flask** remove as vírgulas e procura no mapa legado das 6 originais.
   - Se casar, obtém o `id_seq` (ex.: `CA7,Dm,G7` → `CA7DmG7` → seed 3).
3. Se não casar, **Flask** separa por vírgula, aplica `strip().lower()` em cada
   token, monta a `chave` e procura no catálogo.
4. Se não encontrar, responde `200` com `[]`.
5. Se encontrar, segue o UC-04 a partir do passo 4 (bitset, filtro, paginação).

**Exemplos:**

| Requisição | Resultado |
|---|---|
| `?sequencia=Bm,G,D,A` | seed 0 |
| `?sequencia=BmGDA` | seed 0 |
| `?sequencia=CA7,Dm,G7` | seed 3 (chave legada) |
| `?sequencia=C, G, Am, F` | seed 1 (lista normalizada) |
| `?sequencia=c,g,am,f` | seed 1 (lista normalizada) |
| `?sequencia=X,Y` | `[]` |
| `?sequencia=sequência-customizada` | busca no catálogo por `chave` |

**Alternativas e erros:**

| Situação | Comportamento esperado | Decisão |
|---|---|---|
| Valor tem vírgulas e também forma chave legada | Chave legada vence (passo 2) | O-08 |
| Valor com espaços/caixa diferente | Normaliza por `strip().lower()` | — |
| Valor vazio | `[]` | — |
| `sequencia_id` e `sequencia` juntos | `sequencia_id` vence | UC-09 |

### UC-06 — Interação no frontend (`#/porsequencia`)

**Fluxo de carregamento:**

1. **Visitante** abre a rota; `SequenciaController` inicializa.
2. **AngularJS** dispara `GET /sequencias`.
3. **UI** mostra estado de carregamento.
4. **Sucesso:** renderiza seeds + customizadas; cada acorde vira `{acorde, cor}`.
5. **Erro:** mostra mensagem e mantém a lista vazia; não usa fallback local.

**Fluxo de cadastro:**

1. **Visitante** digita no campo ou clica em chips de sugestão.
2. **UI** mostra a dica “2 a 8 acordes” (apenas informativa).
3. **Visitante** clica em “Cadastrar”.
4. **AngularJS** valida localmente lista não vazia e faz `POST /sequencias`.
5. **UI** trata a resposta:
   - `201` → “Sequência cadastrada”; recarrega o catálogo; seleciona a nova.
   - `200` → “Essa sequência já existe”; seleciona a existente.
   - `400` → mostra mensagem de lista vazia/inválida.
   - `413` → mostra mensagem de conteúdo grande.
   - `429` → mostra limite atingido e pede para tentar depois.
   - falha de rede/`500` → mensagem genérica.
6. **UI** dispara a busca da sequência retornada (UC-04).

**Fluxo de busca:**

1. **Visitante** clica em uma sequência do catálogo.
2. **UI** seleciona, mostra os acordes e inicia `progressbar`.
3. **AngularJS** chama `GET /similares?sequencia_id=<id>` (+ `&generos=` se
   houver filtro).
4. **UI** mostra “Encontrei essas músicas”, lista os resultados ordenados por
   popularidade e abre a cifra no clique.
5. **Visitante** troca o gênero: a mesma busca é refeita com `&generos=`.
6. **Visitante** clica em “limpar”: zera sequência, resultados e mensagens.

**Estados da UI:**

| Estado | Gatilho | Comportamento |
|---|---|---|
| Carregando catálogo | load inicial | spinner/progressbar; sem lista local |
| Erro de catálogo | `GET /sequencias` falha | mensagem; sem fallback |
| Catálogo vazio | lista vazia | estado vazio explícito | 
| Cadastrando | submit | botão desabilitado/progressbar |
| Duplicata | `200` | mensagem + seleção da existente |
| Limite | `429` | mensagem + orientação para tentar depois |
| Buscando | clique/gênero | progressbar + limpeza dos resultados anteriores |
| Sem resultados | `[]` | mensagem de vazio |

**Decisões de UI:** paleta e sugestões em mapa local em `sequencia.js`
(O-10, confirmado). Demais decisões de UI: O-09, O-11 e O-15 (pendentes).

### UC-07 — Persistência entre reinícios

**Cenários:**

| Cenário | O que acontece | Requisito |
|---|---|---|
| `docker restart` / `stop` + `start` | Mesmo container; camada gravável preservada | Atendido mesmo sem volume; o volume é o suporte oficial |
| `docker rm` + `docker run` com o mesmo volume nomeado | Novo container; `/data` remontado; catálogo preservado | **Obrigatório** |
| `docker rm` + `docker run` sem volume | Camada gravável descartada; catálogo perdido | Documentar que não é suportado |
| Volume vazio | Schema + seeds criados; nenhuma duplicata | Obrigatório |
| Volume com schema antigo | `user_version` orienta migração/falha | O-02 |
| Backup | Operador para o container ou usa `VACUUM INTO` | Documentar |

**Fluxo de verificação:**

1. Subir com `-v deciframe-data:/data`.
2. Cadastrar uma sequência.
3. `docker restart deciframe`; buscar a sequência.
4. `docker rm -f deciframe`; subir de novo com o mesmo volume; buscar de novo.
5. Confirmar que `GET /sequencias` não duplicou as seeds.

### UC-08 — Regressão das 6 sequências originais

**Fluxo de verificação:**

1. Rodar `artifacts/verifica_matching.py`; exigir 0 divergências nas duas
   conferências ([A] cifra crua × tag crua; [B] runtime × `seqs_famosas`).
2. Rodar o teste novo que soma as páginas de `GET /similares?sequencia_id=i`
   para `i = 0..5` e compara com as tags do CSV.
3. Exigir as contagens: `0 → 199`, `1 → 296`, `2 → 4`, `3 → 5`, `4 → 7`,
   `5 → 3`.
4. Exigir que os aliases `Bm,G,D,A`, `BmGDA`, `CA7,Dm,G7` e `C, G, Am, F`
   retornem os mesmos conjuntos.

**Pós-condição:** qualquer divergência bloqueia a entrega.

### UC-09 — Resolução de parâmetros em `GET /similares`

**Precedência:** `acordes` > `id_unico_musica` > `sequencia_id` > `sequencia`.

| Combinação | Modo escolhido |
|---|---|
| `?acordes=...&sequencia_id=1` | acordes |
| `?id_unico_musica=...&sequencia=...` | id_unico_musica |
| `?sequencia_id=1&sequencia=C,G` | sequencia_id |
| `?sequencia=C,G` | alias legado |
| nenhum parâmetro | `get_similares([], generos_key)` (comportamento atual) |

Essa ordem preserva o comportamento atual e só insere `sequencia_id` antes do
alias.

### UC-10 — Erros e limites

| Rota/situação | Status | Corpo |
|---|---|---|
| `POST` JSON inválido/lista vazia/tipo inválido | `400` | `{"erro": "..."}` |
| `POST` corpo > 16 KB | `413` | `{"erro": "corpo da requisição muito grande"}` |
| `POST` rate limit | `429` + `Retry-After` | `{"erro": "..."}` |
| `POST` teto de 500 customizadas | `429` | `{"erro": "..."}` |
| `GET /similares?sequencia_id=` inválido | `200` | `[]` |
| `GET /similares?sequencia=` desconhecido | `200` | `[]` |
| Erro inesperado de DB | `500` | `{"erro": "..."}` (decisão O-05) |

Todos com `Content-Type: text/html` e corpo `json.dumps`.

## 4. Decisões

### 4.1 Já decidido (não reabrir sem custo)

- SQLite da stdlib; sem serviço externo; arquivo em `/data` (ou `./var` local).
- Matching legado: bloco contíguo na ordem exata + conjunto fechado;
  comparação só por `lower()`.
- Bitset de 1 bit por música; seeds eager, customizadas lazy, cálculo no POST.
- Seeds com IDs fixos 0–5; customizadas a partir de 6; sem `nome`.
- Sem edição/remoção; duplicata idempotente (`200`); nova = `201`.
- Rate limit 10/min por IP; teto de 500; corpo de 16 KB.
- Respostas `json.dumps` com `Content-Type: text/html`.
- Um único worker; deploy local-only com volume nomeado.

### 4.2 Decisões validadas e pendentes

| ID | Decisão | Opções | Recomendação | Status | Impacto |
|---|---|---|---|---|---|
| O-01 | Falha ao abrir/criar o SQLite no startup | (a) abortar; (b) cair para `./var` | (a) abortar com erro claro | **Confirmado** | Evita rodar com persistência silenciosamente quebrada |
| O-02 | `user_version` maior que 1 | (a) abortar; (b) ignorar; (c) migrar | (a) abortar por enquanto | Pendente | Migração real fica para o futuro; evita corromper dados |
| O-03 | Seed existente com acordes divergentes | (a) falhar; (b) sobrescrever; (c) manter | (a) falhar no startup | Pendente | Detecta volume adulterado/incompatível cedo |
| O-04 | `GET /sequencias` falha no frontend | (a) erro sem fallback; (b) seeds locais | (a) erro sem fallback | Pendente | Mantém a regra “catálogo real, sem hardcode” |
| O-05 | Erro inesperado no `POST` | (a) JSON `500`; (b) HTML padrão | (a) JSON `500` | Pendente | Consistência de contrato |
| O-06 | Falha ao calcular bitset no `POST` | (a) `201` + lazy; (b) `500` + rollback; (c) `500` sem rollback | (a) `201` + lazy | **Confirmado** | A linha já é válida; a busca tenta recalcular |
| O-07 | Falha ao calcular bitset na busca | (a) `500` JSON; (b) `[]` | (a) `500` JSON | **Confirmado** | `[]` mascara erro como “sem resultados” |
| O-08 | Prioridade do alias | (a) chave legada antes; (b) lista normalizada antes | (a) chave legada antes | Pendente | Preserva `CA7,Dm,G7` e casos estranhos que já funcionam |
| O-09 | Fallback de paleta no frontend | (a) nada; (b) `#2E1C74` para desconhecidos | (b) fallback fixo | Pendente | Acordes fora da paleta continuam visíveis |
| O-10 | Origem da paleta/sugestões | (a) mapa local em `sequencia.js`; (b) constante compartilhada em `app.js`/novo arquivo | (a) mapa local | **Confirmado** | Menos arquivos; duplica parte da paleta de `acordes.js` |
| O-11 | Após `POST` com sucesso | (a) recarregar `GET /sequencias`; (b) inserir otimista | (a) recarregar | Pendente | Catálogo sempre autoritativo; custo desprezível |
| O-12 | Rate limit: chave | (a) `remote_addr`; (b) `X-Forwarded-For` | (a) `remote_addr` | Pendente | Correto no local-only; documentar proxy |
| O-13 | Ordem da resposta de sequência | (a) manter ordem da coleção; (b) ordenar por popularidade no servidor | (a) manter | **Confirmado** | Preserva o comportamento atual; frontend já ordena |
| O-14 | Framework de teste | (a) `unittest` stdlib; (b) `pytest` | (a) `unittest` | Pendente | Zero dependência nova; suficiente para o escopo |
| O-15 | Destaque da sequência selecionada | (a) corrigir `temAcorde`; (b) manter | (b) manter | Pendente | Evita ampliar escopo com bug pré-existente |
| O-16 | Backup do SQLite | (a) documentar; (b) automatizar | (a) documentar | Pendente | Operação local; `VACUUM INTO` ou parar o container |
| O-17 | Teto de customizadas | (a) fixo em 500; (b) configurável por env | (a) fixo | Pendente | Menos superfície; proposta já fixa 500 |
| O-18 | Ordem das checagens no `POST` | (a) rate → JSON → validação → duplicata → teto; (b) validação antes do rate | (a) rate primeiro | **Confirmado** | Protege CPU/DB; requests inválidas consomem quota |

## 5. Decisões confirmadas

| ID | Decisão | Escolha |
|---|---|---|
| O-01 | Falha ao abrir/criar o SQLite no startup | Abortar o startup; sem fallback para `./var` |
| O-06 | Falha ao calcular bitset no `POST` | `201` + lazy; a linha permanece persistida |
| O-07 | Falha ao calcular bitset na busca | `500` JSON; não retornar `[]` |
| O-10 | Origem da paleta/sugestões | Mapa local em `sequencia.js` |
| O-13 | Ordem da resposta de sequência | Manter a ordem atual da coleção |
| O-18 | Ordem das checagens no `POST` | Rate limit antes da validação do corpo |

### Pendentes

As demais decisões (O-02, O-03, O-04, O-05, O-08, O-09, O-11, O-12, O-14,
O-15, O-16, O-17) permanecem abertas e seguem a recomendação da tabela 4.2 até
validação explícita. Nenhuma delas bloqueia o início da implementação.

## 6. Referências

- [`03-plan.md`](../docs/features/sequencias-customizadas/03-plan.md)
- [`02-proposal.md`](../docs/features/sequencias-customizadas/02-proposal.md)
- [`01-research.md`](../docs/features/sequencias-customizadas/01-research.md)
- `docs/adr/0001-local-only-docker-deploy.md`
- `docs/adr/0002-persist-custom-sequences.md`
- `artifacts/verifica_matching.py`
- `main.py:40-45`, `main.py:170-223`, `main.py:266-277`
- `static/assets/js/controllers/sequencia.js:1-105`
- `static/templates/sequencia.html:1-63`
