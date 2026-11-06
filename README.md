# deciframe

Descubra as músicas que você já sabe tocar (e ainda não faz ideia). Busque por
título/artista, gênero, pelos acordes que você já manja, ou por sequências de
acordes famosas — o deciframe cruza isso com uma base de cifras e sugere
músicas parecidas.

Stack: backend Flask (Python) servindo uma API JSON + um frontend AngularJS
estático. As músicas e gêneros continuam vindo do CSV em memória; o catálogo de
sequências (as 6 originais e as cadastradas por visitantes) fica em um arquivo
SQLite.

## Rodando localmente

### Com Docker

```
docker build -t ciframe .
docker run --name deciframe -p 8080:8080 -v deciframe-data:/data ciframe
```

Acesse [http://localhost:8080](http://localhost:8080).

O volume nomeado `deciframe-data` guarda o catálogo de sequências em
`/data/deciframe.db`. Use sempre um volume em `/data`; montar um volume em
`/app/data` esconderia o CSV e impediria o startup.

A aplicação roda com **um único worker** do gunicorn (`--workers 1`). O índice
de matching e o rate limit ficam em memória, por processo; não use
`WEB_CONCURRENCY` nem aumente o número de workers sem revisar essa decisão.

Para preservar o catálogo entre `docker rm` e um novo `docker run`, use o mesmo
volume nomeado:

```
docker run --name deciframe -p 8080:8080 -v deciframe-data:/data ciframe
```

### Com virtualenv

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Acesse [http://localhost:5000](http://localhost:5000).

Sem `DECIFRAME_DB`, o banco local fica em `./var/deciframe.db` (o diretório é
criado automaticamente). Para usar outro caminho:

```
DECIFRAME_DB=/caminho/deciframe.db python main.py
```

## Banco de sequências e backup

- Seeds: as 6 sequências originais têm IDs fixos 0–5 e são imutáveis.
- Customizadas: recebem IDs a partir de 6; o cadastro é anônimo, com teto de
  500 sequências e limite de 10 cadastros por minuto por IP.
- Duplicata normalizada (caixa/espaço) devolve `200` com o ID existente; uma
  sequência nova devolve `201`.
- O schema é criado de forma idempotente no startup. Um volume vazio cria as
  seeds; um volume existente não as duplica.

O backup é responsabilidade do operador. Pare o container antes de copiar o
arquivo ou use `VACUUM INTO` com o container em execução:

```
docker stop deciframe
docker cp deciframe:/data/deciframe.db ./deciframe-backup.db
docker start deciframe
```

---

Para convenções de contribuição, veja [CONTRIB.md](CONTRIB.md). Licença: [LICENSE](LICENSE).
