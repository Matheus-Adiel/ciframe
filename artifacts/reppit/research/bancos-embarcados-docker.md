# Bancos de dados embarcados no container — opções e implicações

> Snapshot do código em 2026-11-03, HEAD `fb97001` (árvore suja: `research/` e
> `artifacts/` não commitados). Metadados de pacotes e da imagem base
> verificados nesta data; comandos e URLs usados estão nas seções 7 e nas
> referências.

## Resumo

Todos os bancos embarcados considerados aqui são bibliotecas instaladas via
`pip`, executadas dentro do próprio processo do gunicorn: nenhum deles exige
porta, container auxiliar, daemon ou serviço externo, então o deploy continua
sendo uma única imagem e um único `docker run`. A opção de custo zero é o
SQLite, que já vem na imagem base (`sqlite3` da stdlib, libsqlite3 3.46.1 com
FTS5 e JSON1) e não adiciona um único byte ao `requirements.txt`; LMDB, libSQL,
RocksDB e DuckDB entram como wheels de 0,5 MB a 20 MB; TinyDB, `diskcache` e
ZODB são Python puro, mas o TinyDB não tem coordenação entre processos, o
`diskcache` é seguro entre processos porém é um cache chave-valor, e o ZODB não
abre o mesmo `FileStorage` em vários processos. A imagem base atual
(`python:3.9-slim`, Python 3.9.25, Debian trixie) foi congelada em 2025-10-31,
logo depois do fim de vida do Python 3.9, e as versões correntes de DuckDB
(2.0), TinyDB (4.9), ZODB (6.4), APSW (3.54) e SQLAlchemy (2.1) já exigem
Python 3.10/3.11 — escolher essas bibliotecas força pinar versões antigas ou
subir o `FROM`. O Dockerfile atual não tem `VOLUME`, `USER` nem variável de
caminho, e a aplicação não escreve nada em disco: sem um volume, um banco
criado em runtime sobrevive a `docker restart` (a camada gravável do container
continua lá), mas é perdido em `docker rm`, em `docker run --rm` e em qualquer
recriação a partir de uma imagem reconstruída. Fazer a persistência valer para
os cenários que a feature de sequências customizadas pede exige, no mínimo,
escolher um diretório fora de `/app` (montar um volume em `/app/data`
esconderia o CSV e quebraria o import do `main.py`), declarar esse caminho no
Dockerfile e documentar/declarar o volume.

## Escopo e método

Lido integralmente para esta análise:

- `Dockerfile:1-12`, `requirements.txt:1-5`, `.dockerignore:1-4`,
  `.gitignore:1-4`, `README.md:13-31`, `AGENTS.md:20-42`;
- `docs/adr/0001-local-only-docker-deploy.md`, `docs/adr/0002-persist-custom-sequences.md`
  (template não preenchido), `docs/features/sequencias-customizadas/00-enunciado.md:1-130`;
- `artifacts/reppit/research/entendimento-do-repositorio.md` (seções "Deploy e operação" e
  "Observações factuais"), `main.py:49-98`, `musica.py:1-25`.

Verificado empiricamente nesta data:

- a imagem `python:3.9-slim` foi inspecionada pelo registry do Docker Hub:
  Python 3.9.25, base Debian **trixie**, criada em 2025-10-31 (o `last_updated`
  do tag é 2025-11-01); o CPython é compilado contra `libsqlite3-dev` do
  sistema;
- o `sqlite3` do Debian trixie é 3.46.1-7+deb13u2 e é compilado com
  `--enable-fts5` e `--enable-json` (`debian/rules` do pacote);
- metadados do PyPI (versão, `requires_python`, presença de wheel `cp39`,
  tamanho) de duckdb, lmdb, rocksdict, libsql-experimental, tinydb, diskcache,
  zodb, apsw, sqlitedict e sqlalchemy;
- comportamento de concorrência do DuckDB (documentação oficial), do WAL do
  SQLite (`sqlite.org/wal.html`), ciclo de vida de volumes (documentação do
  Docker) e o default de workers do gunicorn (código do `gunicorn/config.py`).

Não foi possível buildar nem rodar a imagem: não existe binário `docker` neste
ambiente. Os trechos de Dockerfile abaixo são propostas de diff, não foram
executados; o comando para conferir cada afirmação está na seção 7.

Não houve alteração de código nesta análise.

## 1. Ponto de partida

`Dockerfile:1-12` é um estágio único, sem `USER`, sem `VOLUME`, sem `ENV` e
sem multi-stage:

```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]
```

Consequências relevantes para a pergunta:

- **Não há banco hoje.** O único acesso a disco em runtime é
  `open('data/top/dataset_final.csv')` no import (`main.py:49`); não há
  `sqlite3`, `shelve`, `pickle` nem escrita de arquivo em `main.py`/`musica.py`.
- **O processo é único.** `gunicorn` sem `--workers` usa
  `WEB_CONCURRENCY` ou 1 (`gunicorn/config.py`, classe `Workers`), com worker
  `sync`. Hoje, portanto, não há concorrência entre processos; isso só muda se
  alguém definir `WEB_CONCURRENCY`/`--workers`.
- **O contexto de build tem 78 MB** (excluindo `.git`, 47 MB, e `.venv`, 20 MB,
  ambos no `.dockerignore`); `data/` sozinho tem 77 MB. Qualquer banco novo
  acrescenta pouco em relação a isso.
- **`COPY . .` copia o repositório inteiro** para `/app`, então um arquivo de
  banco criado no diretório do projeto (por exemplo `instance/app.db`) entra no
  build seguinte, a menos que seja adicionado ao `.dockerignore`.
- **O requisito que motiva o banco** está em
  `docs/features/sequencias-customizadas/00-enunciado.md:38-43,52-53`: o
  catálogo de sequências passa a ser persistido em banco e "não volta a ser
  perdido ao reiniciar o container". O mesmo documento fixa que músicas e
  gêneros continuam vindo do CSV (`:60-62`) e que o app segue em "container
  único, sem serviços externos adicionais" (`:63-65`), com a tecnologia de
  banco sendo decisão de quem implementa, "desde que caiba no container Docker
  único e local" (`:74-75`).
- **O ADR 0001** fixa "local-only" e um único Dockerfile; nada nele proíbe um
  banco embarcado, desde que não apareça um serviço externo.

## 2. O que "embarcado" significa nesta análise

Um banco embarcado é uma **biblioteca linkada ao processo Python**, que
gerencia seus dados em arquivos locais. Não abre porta, não tem daemon, não
precisa de container auxiliar e não sobrevive sozinho ao processo — quem
garante durabilidade é o sistema de arquivos (e, no Docker, o volume).

Este é exatamente o recorte do enunciado: o app continua no "container único,
sem serviços externos adicionais" (`00-enunciado.md:63-65`) e a tecnologia de
banco pode ser escolhida "desde que caiba no container Docker único e local"
(`00-enunciado.md:74-75`).

Ficam de fora, por não atenderem "sem serviço adicional":

- PostgreSQL, MySQL/MariaDB e Redis iniciados por um `entrypoint`/supervisor
  **dentro do mesmo container**: tecnicamente é um container só, mas são
  processos de servidor, com diretório de dados próprio, usuário não-root,
  init e healthcheck — não é embarcado no sentido acima;
- PGlite e similares, que são WASM/JavaScript e não têm binding Python;
- qualquer opção com réplica/sync em nuvem (libSQL/Turso, por exemplo) quando
  usada no modo remoto.

## 3. Tipos e opções

### 3.1 Comparativo

| Opção | Tipo | Dependência no `requirements.txt` | Wheel p/ py3.9 (x86_64) | Concorrência entre processos | Encaixe para o catálogo de sequências |
|---|---|---|---|---|---|
| **SQLite** | relacional, arquivo único | nenhuma (stdlib) | — | 1 escritor, N leitores (WAL) | alto |
| **libSQL** | relacional compatível com SQLite | `libsql-experimental==0.0.55` | 5,0 MB | como SQLite | baixo: pacote 0.0.x, README diz que não é production grade, só Linux/macOS |
| **DuckDB** | colunar/analítico | `duckdb==1.4.5` (a 2.0 exige py≥3.11) | 19,5 MB | 1 processo lê e escreve; os demais só leitura | baixo: analítico, não é bom para transações pequenas |
| **LMDB** | chave-valor B-tree | `lmdb==3.0.0` | 0,5 MB | 1 escritor, N leitores | médio: rápido e simples, mas sem SQL |
| **RocksDB** | chave-valor LSM | `rocksdict==0.3.29` | 4,0 MB | 1 processo escritor | baixo: projetado para volume alto de escrita |
| **diskcache** | chave-valor sobre SQLite | `diskcache==5.6.3` | ~0,1 MB (puro Python) | seguro entre processos | médio: é cache, não catálogo consultável |
| **TinyDB** | documento JSON | `tinydb==4.8.2` (a 4.9 exige py≥3.10) | ~0,1 MB (puro Python) | nenhuma garantia | baixo: reescreve o arquivo inteiro a cada escrita |
| **ZODB** | objetos persistentes | `zodb==6.1` (a 6.4 exige py≥3.10) | ~1 MB (puro Python) | 1 processo por `FileStorage` | baixo: overkill e trava com múltiplos workers |
| **dbm/`shelve`** | chave-valor | nenhuma (stdlib) | — | fraca | baixo |

As opções com extensão nativa publicam wheels `manylinux` `cp39` para x86_64;
LMDB, DuckDB e rocksdict também publicam para aarch64. Exceção:
`libsql-experimental` 0.0.55 **não** publica wheel `cp39` aarch64 — em Apple
Silicon/ARM o `pip install` tentaria compilar Rust. TinyDB e `diskcache` são
`py3-none-any` (puro Python), sem wheel específica de plataforma.

### 3.2 SQLite (stdlib)

- **Como entra na imagem:** já está. O módulo `sqlite3` é da stdlib e a
  libsqlite3 vem do Debian trixie (3.46.1, com FTS5 e JSON1). Nada a instalar.
- **Modelo:** arquivo único (`app.db`), tabelas SQL, transações ACID; WAL
  permite leitores concorrentes com um escritor.
- **Encaixe:** o catálogo é uma tabela de poucas colunas e poucas linhas
  (`id`, `nome`, `acordes`, `criado_em`); operações são `INSERT`/`SELECT`/`DELETE`
  pequenos. É o caso de uso canônico do SQLite.
- **Alternativa de binding:** APSW faz o mesmo papel com outra API; a versão
  atual (3.54.1.0) exige Python ≥3.11, e o último wheel `cp39` é o 3.51.0.0.
- **No container:** exige um diretório gravável. Cuidado com dono do arquivo
  quando o processo não for root, e com os arquivos `-wal`/`-shm` ao copiar.

### 3.3 libSQL (`libsql-experimental`)

- **Como entra:** `pip install libsql-experimental`; wheel de 5 MB, sem
  dependência de sistema.
- **Modelo:** fork do SQLite; o modo local grava um arquivo no formato derivado
  do SQLite (WAL, transações). O modo "embedded replica" sincroniza com um
  servidor Turso, o que seria serviço externo e está fora do escopo local-only.
- **Risco:** o próprio README do pacote diz que ele é experimental e não é
  considerado production grade, e que suporta só Linux e macOS; a versão é
  0.0.55 (pré-1.0).
- **No container:** mesmas implicações do SQLite; a ausência de wheel aarch64
  cp39 quebra builds em ARM.

### 3.4 DuckDB

- **Como entra:** `pip install duckdb`. A versão atual (2.0.0) exige Python
  ≥3.11; para a imagem atual (3.9) é preciso pinar a linha 1.4.x (1.4.5 tem
  wheel cp39 de 19,5 MB) ou subir o Python.
- **Modelo:** colunar, orientado a consultas analíticas; lê CSV/Parquet
  diretamente e tem SQL completo.
- **Concorrência (documentação oficial):** ou **um** processo lê e escreve, ou
  **vários** processos só leem (`READ_ONLY`); não há escrita multi-processo. O
  processo escritor tem MVCC entre threads.
- **Encaixe:** sobra para um catálogo de sequências; faria sentido se o projeto
  fosse consultar analiticamente as 67 mil músicas. Com `--workers > 1` no
  gunicorn, o modo escrita deixa de funcionar.
- **No container:** arquivo único, mas o formato de armazenamento tem versão;
  atualizar a lib pode exigir migração/`EXPORT`/`IMPORT`.

### 3.5 LMDB (`lmdb` / py-lmdb)

- **Como entra:** `pip install lmdb`; wheel cp39 de 0,5 MB (x86_64 e aarch64).
- **Modelo:** B-tree mapeado em memória, chave-valor, transações; vários
  leitores concorrentes e um escritor. Não tem SQL: as consultas são
  varreduras/iteração sobre chaves.
- **Ponto de atenção:** `map_size` é definido na abertura e limita o tamanho do
  ambiente; crescer exige reabrir com outro valor. O ambiente é um **diretório**
  com `data.mdb` e `lock.mdb` (copiar os dois juntos, ou usar `mdb_copy`).
- **Encaixe:** bom se o modelo for "catálogo como dicionário serializado"; para
  consultas por nome/ordem, o SQL do SQLite evita código.

### 3.6 RocksDB (`rocksdict`)

- **Como entra:** `pip install rocksdict`; wheel cp39 de 4 MB. A alternativa
  `python-rocksdb` exigiria compilar a lib C++ no build.
- **Modelo:** LSM, chave-valor, alto throughput de escrita, column families.
- **Concorrência:** um processo abre o banco para escrita (lock de arquivo);
  outro processo não consegue abrir o mesmo banco para escrita, e leitura
  concorrente exigiria uma instância secundária do RocksDB.
- **Encaixe:** dimensão errada para o problema (poucas escritas, poucos dados).

### 3.7 Chave-valor sobre SQLite: `diskcache` e `sqlitedict`

- **`diskcache`** (5.6.3, puro Python, Apache 2.0): cache chave-valor com TTL
  sobre SQLite; seguro entre processos. Serve para cache de respostas, não
  como catálogo relacional.
- **`sqlitedict`** (2.1.0, puro Python): dicionário persistente sobre SQLite;
  API mínima, sem consultas.
- **No container:** herdam as regras do SQLite (arquivo único, volume).

### 3.8 TinyDB (`tinydb`)

- **Como entra:** puro Python; a versão 4.9 exige ≥3.10, então na imagem atual
  seria `tinydb==4.8.2`.
- **Modelo:** documento JSON com API de consulta em Python. Cada escrita
  reescreve o arquivo inteiro, com `flush`/`fsync`, mas sem `rename` atômico e
  sem qualquer coordenação entre processos.
- **Encaixe:** funciona para 6–100 sequências com um único worker; é frágil
  como persistência de um catálogo que cresce e é escrito por HTTP.

### 3.9 ZODB

- **Como entra:** puro Python; 6.4 exige ≥3.10, então `zodb==6.1` na imagem
  atual, com dependências (`persistent`, `transaction`, `ZConfig`).
- **Modelo:** persistência transparente de objetos Python com transações.
- **Concorrência:** `FileStorage` é aberto por **um** processo; acesso
  multi-processo exige ZEO, que é um servidor separado — exatamente o serviço
  adicional que a pergunta quer evitar.
- **Encaixe:** resolve um problema que o projeto não tem (grafo de objetos).

### 3.10 `dbm`/`shelve` (stdlib)

- **Como entra:** já está na stdlib; no Linux o backend é `dbm.gnu` (gdbm).
- **Modelo:** chave-valor com `pickle`; sem esquema, sem transações, com
  semântica de lock dependente do backend.
- **Encaixe:** aceitável para um protótipo descartável; ruim para dados que
  precisam sobreviver a escritas concorrentes e a mudanças de formato.

### 3.11 O que fica de fora

- **Postgres/MySQL/Redis no mesmo container:** não são embarcados; exigem
  segundo processo, diretório de dados, `init`, geralmente usuário não-root e
  um healthcheck próprio. Aumentam imagem e superfície operacional.
- **Bancos gerenciados/cloud:** contrariam o ADR 0001 (local-only).
- **SQLAlchemy/Alembic:** não são bancos; são camada de acesso/migração e
  podem ser usados (ou não) com SQLite. A versão 2.1 exige ≥3.11.
- **Outros embarcados menos usuais em Python:** Firebird embedded (exige a
  biblioteca cliente do sistema, não só `pip`), Berkeley DB via `bsddb3`
  (compilação e projeto pouco mantido) e UnQLite (binding pouco mantido).
  Mantêm o modelo de arquivo único, mas nenhum combina stdlib + wheel +
  maturidade como o SQLite.

## 4. Implicações para o Dockerfile

### 4.1 O que não muda

Nenhuma opção da seção 3 exige `EXPOSE` novo, rede, container auxiliar ou
`docker compose`. O `CMD` do gunicorn continua igual, e o banco roda dentro do
mesmo processo do gunicorn (por padrão, um único worker). O "single docker,
local-only" do ADR 0001 é preservado em todas elas.

### 4.2 O que muda em qualquer opção

1. **Caminho do banco fora de `/app`.** Precisa ser um diretório próprio,
   gravável, que possa ser montado como volume sem esconder o CSV.
2. **Volume.** Declarar `VOLUME` no Dockerfile ou exigir `-v` no `docker run`;
   sem isso, `docker rm` apaga o banco.
3. **Dono do arquivo.** Hoje o container roda como root (não há `USER`); se
   for adicionado um usuário, o diretório do banco precisa de `chown` na imagem
   e o bind mount precisa de UID compatível.
4. **Variável de caminho.** `ENV DECIFRAME_DB=/data/deciframe.db` evita que o
   caminho fique hardcoded no código e permite trocar por bind mount.
5. **`.dockerignore`/`.gitignore`.** Se o banco puder ser criado dentro do
   repositório, ele não pode entrar no build nem no Git.
6. **Inicialização.** Criar tabela/seed de forma idempotente no start
   (`CREATE TABLE IF NOT EXISTS`), sem depender de `before_first_request`
   (removido no Flask 3).

### 4.3 Diff mínimo com SQLite

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DECIFRAME_DB=/data/deciframe.db \
    PYTHONDONTWRITEBYTECODE=1
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]
```

Com usuário não-root (opcional, mas recomendado se o banco for gravável):

```dockerfile
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /data && chown app:app /data
USER app
```

Ordem importa: `mkdir`/`chown` antes de `USER`; o `VOLUME` pode vir depois,
porque o Docker copia conteúdo e dono do diretório da imagem ao criar o volume.

Uso:

```bash
docker build -t ciframe .
docker run --name deciframe -p 8080:8080 -v deciframe-data:/data ciframe
```

### 4.4 Diff com biblioteca nativa (LMDB, libSQL, rocksdict, DuckDB)

```dockerfile
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

e uma linha nova em `requirements.txt`. Como os wheels manylinux existem para
cp39 (x86_64 e, exceto libSQL, aarch64), **não** é preciso `gcc` no estágio
final. Os tamanhos de camada adicionados ficam entre 0,5 MB (LMDB) e 20 MB
(DuckDB 1.4.5); o SQLite adiciona 0.

### 4.5 Se não houver wheel para a plataforma

Aí entra multi-stage, para não levar `gcc`/headers para a imagem final:

```dockerfile
FROM python:3.9-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir -w /wheels -r requirements.txt

FROM python:3.9-slim
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl \
 && rm -rf /wheels
```

Isso vale para `python-rocksdb` e para qualquer pin antigo sem wheel. Para
`libsql-experimental` em aarch64 o problema é outro: não há wheel cp39 e o
pacote é escrito em Rust, então o estágio de build precisaria do toolchain Rust
(`rustup`/`cargo`), não só de `gcc` — mais um motivo para o libSQL só fazer
sentido em x86_64.

### 4.6 Tamanho da imagem

Estimativa (não buildada aqui): base `python:3.9-slim` ~120–130 MB
descompactada, dependências atuais ~20–30 MB, contexto copiado 78 MB. Um banco
embarcado muda esse total em 0 (SQLite) a ~20 MB (DuckDB). O `data/` de 77 MB
domina o tamanho de qualquer forma.

### 4.7 Armadilhas específicas deste repositório

- **Não montar volume em `/app/data`.** `main.py:49` abre
  `data/top/dataset_final.csv` por caminho relativo; um volume vazio montado em
  `/app/data` esconde o CSV e o import falha. Use `/data` (ou outro diretório
  fora de `/app`).
- **Não colocar o banco em `/app/static`.** A rota `/<path:path>`
  (`main.py:109-112`) serve arquivos de `static/`; um `.db` ali seria baixável
  pela web.
- **`COPY . .` + banco local.** Se o caminho padrão for `instance/app.db` ou
  `data/app.db`, um build feito depois de rodar localmente pode assar o banco
  no meio do repositório. Acrescente `instance/`, `*.db`, `*.sqlite*`,
  `*.mdb` ao `.dockerignore` (e ao `.gitignore`).
- **`VOLUME` declarado no Dockerfile** cria volume anônimo quando o usuário não
  passa `-v`; os dados sobrevivem ao `docker rm`, mas ficam em um volume de
  nome aleatório, difícil de localizar/backup. É uma rede de segurança, não
  substitui um volume nomeado documentado.
- **`PYTHONDONTWRITEBYTECODE=1`** evita que um usuário não-root tente escrever
  `__pycache__` em `/app` (root-owned).

## 5. Persistência entre reinícios do container

### 5.1 Três coisas diferentes chamadas de "reiniciar"

1. `docker restart` / `docker stop` + `docker start`: **mesmo container**, a
   camada gravável é preservada.
2. `docker rm` + `docker run` (ou `docker compose up` recriando): **novo
   container**; a camada gravável é descartada.
3. `docker build` + `docker run` de imagem nova: além do item 2, o conteúdo
   gravado na imagem é o do build.

O requisito da feature ("não volta a ser perdido ao reiniciar o container",
`00-enunciado.md:52-53`) é atendido pelo cenário 1 mesmo sem volume, mas
qualquer um dos outros dois perde os dados. Persistência de verdade exige
volume ou bind mount.

### 5.2 Matriz de sobrevivência

| Ação | Sem volume (camada gravável) | Volume anônimo (`VOLUME` no Dockerfile) | Volume nomeado (`-v nome:/data`) | Bind mount (`-v /host/dir:/data`) |
|---|---|---|---|---|
| `docker restart` | sobrevive | sobrevive | sobrevive | sobrevive |
| `docker stop` + `start` | sobrevive | sobrevive | sobrevive | sobrevive |
| `docker rm` + novo `run` | **perde** | sobrevive (volume órfão) | sobrevive | sobrevive |
| `docker run --rm` | **perde** | **perde** | sobrevive | sobrevive |
| rebuild + container novo | **perde** | sobrevive | sobrevive | sobrevive |
| `docker volume prune` (volume sem container em uso) | — | **perde** | **perde** | não afeta |
| `docker compose down -v` | **perde** | **perde** | **perde** | não afeta |
| reboot do host / daemon | sobrevive | sobrevive | sobrevive | sobrevive |

Base: documentação do Docker — "quando um container é destruído, a camada
gravável é destruída com ele"; volumes anônimos persistem após `docker rm`,
exceto com `--rm`; volumes nomeados não são removidos por `--rm`;
`docker volume prune` remove volumes não usados.

### 5.3 Volume nomeado, anônimo ou bind mount

- **Nomeado** (`-v deciframe-data:/data`): melhor padrão; independe do caminho
  do host, sobrevive a rebuild, funciona igual em Linux/macOS/Windows.
- **Anônimo** (só `VOLUME ["/data"]`): evita perda acidental no `docker rm`,
  mas o nome é aleatório; descobrir qual volume é o banco exige
  `docker inspect`.
- **Bind mount** (`-v "$PWD/var/db:/data"`): fácil de inspecionar e copiar no
  host, mas herda dono/permissões do host, depende do filesystem e sofre com
  locking em Docker Desktop (macOS/Windows). Em Linux com ext4/xfs é o cenário
  mais previsível; em hosts com SELinux pode ser necessário `:z`/`:Z` no mount.

Em todos os casos, o diretório do banco precisa existir e ser gravável dentro
do container; com volume nomeado novo, o Docker copia o conteúdo (e o dono) do
diretório correspondente da imagem.

### 5.4 Permissões e UID

- Container como root (situação atual): escreve em qualquer bind mount, mas os
  arquivos ficam com dono `root` no host.
- Com `USER app` (uid fixo, por exemplo 10001): o diretório `/data` na imagem
  precisa de `chown`; bind mounts precisam de UID compatível ou
  `docker run --user "$(id -u):$(id -g)"`.
- Volume nomeado: o dono vem do diretório da imagem quando o volume é criado
  pela primeira vez; se o `chown` for feito depois, o volume antigo continua
  com o dono anterior.

### 5.5 Filesystem, WAL e Docker Desktop

- O WAL do SQLite exige que todos os processos estejam **no mesmo host** e usa
  memória compartilhada (`-shm`); **não funciona em filesystem de rede**
  (NFS/SMB). Vale para bind mounts em NAS.
- Em Docker Desktop (macOS/Windows), bind mounts passam por uma camada de
  compartilhamento de arquivos; o locking do SQLite pode falhar ou ser lento.
  Volume nomeado (que fica dentro da VM Linux) evita o problema; bind mount é
  aceitável em Linux nativo.
- `-v` em cima de um diretório com arquivos existentes **obscurece** o conteúdo
  original da imagem (documentação do Docker) — daí a armadilha de `/app/data`.

### 5.6 Backup e restauração

- **SQLite:** não copiar o `.db` com o processo escrevendo (pode pegar
  transação pela metade). Usar a backup API da stdlib:
  `python -c "import sqlite3; sqlite3.connect('/data/app.db').backup(sqlite3.connect('/data/backup.db'))"`
  ou `VACUUM INTO '/data/backup.db'`. Parar o container também funciona.
- **Volume inteiro:**
  `docker run --rm -v deciframe-data:/data -v "$PWD":/backup alpine tar czf /backup/db.tgz -C /data .`
- **LMDB:** copiar `data.mdb` + `lock.mdb` com o container parado, ou usar
  `mdb_copy`.
- **DuckDB:** `CHECKPOINT` antes de copiar o arquivo.
- **RocksDB:** usar a API de checkpoint, não `cp` com o banco aberto.
- Restaurar é o inverso: subir um container com o mesmo volume e copiar o
  arquivo de volta antes de iniciar a aplicação.

### 5.7 Inicialização, seed e migração

- Criar o esquema no start com `CREATE TABLE IF NOT EXISTS`; sem ORM isso
  cabe em poucas linhas.
- Semear as 6 sequências originais de forma idempotente (`INSERT OR IGNORE`
  com `id` fixo) para que um volume vazio funcione e um volume existente não
  duplique linhas.
- Versionar o esquema com `PRAGMA user_version` e aplicar migrações simples no
  start; um banco no volume sobrevive a rebuilds de imagem, então o código novo
  pode encontrar esquema antigo.
- Se o banco for usado também para o catálogo de músicas (não é o que o
  enunciado pede), a carga inicial de 67 mil linhas precisa ser idempotente e
  rápida; hoje o import leva ~3,4 s só para o CSV.

### 5.8 Múltiplos workers do gunicorn

Hoje o default é 1 worker. Se `WEB_CONCURRENCY`/`--workers` for definido:

| Opção | Com N processos |
|---|---|
| SQLite | funciona com WAL + `busy_timeout`; escritas serializam |
| LMDB | funciona: N leitores, 1 escritor por vez |
| DuckDB | **não** funciona para escrita (só 1 processo RW) |
| ZODB `FileStorage` | **não** funciona (lock exclusivo) |
| TinyDB | **não** é seguro |
| `diskcache` | funciona (SQLite por baixo) |
| RocksDB | **não** para escrita concorrente |

### 5.9 O que o requisito pede, na prática

Para "não perder ao reiniciar o container" com o `docker run` documentado no
`README.md:16-17` (que hoje não tem `-v`), as mudanças mínimas são: caminho do
banco em `/data`, `VOLUME ["/data"]` no Dockerfile (ou `-v` obrigatório na
documentação) e inicialização idempotente. Sem isso, o banco funciona em
`docker restart`, mas some no primeiro `docker rm` ou rebuild.

## 6. Restrições que a escolha esbarra

- **Python 3.9 está em fim de vida** (a página de versões do devguide marca
  3.9 como "end-of-life") e a imagem `python:3.9-slim` foi congelada em
  2025-10-31 (Python 3.9.25). Rebuilds não trazem correções novas do Debian.
- **Bibliotecas atuais já subiram o piso:** DuckDB 2.0.0 (`>=3.11`), TinyDB
  4.9.0 (`>=3.10`), ZODB 6.4 (`>=3.10`), APSW 3.54.1.0 (`>=3.11`), SQLAlchemy
  2.1.8 (`>=3.11`). Com o `FROM` atual, é preciso pinar versões antigas
  (DuckDB 1.4.5, TinyDB 4.8.2, ZODB 6.1) ou trocar a base para 3.11/3.12 — uma
  mudança de Dockerfile que afeta a aplicação inteira, não só o banco.
- **SQLite, LMDB, libSQL, rocksdict e `diskcache` instalam hoje no 3.9** com
  wheel (exceto libSQL em aarch64).
- **`COPY . .` e volume em `/app/data`** são as duas armadilhas específicas
  deste repositório; qualquer opção precisa respeitá-las.
- **ADR 0001** deixa o alvo de nuvem em aberto e exige Docker local; um banco
  embarcado não conflita, mas um serviço de banco separado conflitaria com o
  espírito "single Dockerfile".
- **ADR 0002** (persistência de sequências) segue como template vazio; a
  escolha de banco é justamente a decisão que ele deveria registrar.

## 7. Como reproduzir as verificações

```bash
# versão de Python, Debian e SQLite dentro da imagem
docker run --rm python:3.9-slim python -c \
  "import sqlite3, sys; print(sys.version); print(sqlite3.sqlite_version)"

# FTS5 disponível?
docker run --rm python:3.9-slim python -c \
  "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE t USING fts5(x)'); print('fts5 ok')"

# build e persistência
docker build -t ciframe .
docker run -d --name deciframe -p 8080:8080 -v deciframe-data:/data ciframe
curl -s localhost:8080/generos | head -c 80
docker restart deciframe          # sobrevive
docker rm -f deciframe
docker run -d --name deciframe -p 8080:8080 -v deciframe-data:/data ciframe
docker volume inspect deciframe-data
```

## Referências

| Assunto | Fonte |
|---|---|
| Dockerfile, dependências e contexto de build | `Dockerfile:1-12`, `requirements.txt:1-5`, `.dockerignore:1-4` |
| Decisão local-only | `docs/adr/0001-local-only-docker-deploy.md` |
| Persistência de sequências (pendente) | `docs/adr/0002-persist-custom-sequences.md` |
| Requisito de banco, de sobrevivência a restart e de container único | `docs/features/sequencias-customizadas/00-enunciado.md:38-65,74-75` |
| Leitura do CSV e ausência de escrita | `main.py:49-98`, `musica.py:1-25` |
| Execução local | `README.md:13-31`, `AGENTS.md:20-42` |
| Concorrência do DuckDB | https://duckdb.org/docs/1.4/connect/concurrency |
| WAL do SQLite (mesmo host, sem NFS) | https://www.sqlite.org/wal.html |
| Ciclo de vida de volumes | https://docs.docker.com/engine/storage/volumes/ |
| Default de workers do gunicorn | https://github.com/benoitc/gunicorn/blob/master/gunicorn/config.py (`class Workers`) |
| Fim de vida do Python 3.9 | https://devguide.python.org/versions/ |
| Metadados de pacotes (versão, `requires_python`, wheels) | PyPI JSON API, consultado em 2026-11-03 |
| Imagem `python:3.9-slim` (Python 3.9.25, Debian trixie) | Docker Hub / registry, consultado em 2026-11-03 |
| SQLite 3.46.1 com FTS5/JSON1 no Debian trixie | `sources.debian.org` (pacote `sqlite3`, `debian/rules`) |
