# Pesquisa — Sequências de Acordes Customizadas

Preencha esta fase antes de propor qualquer solução. O objetivo é investigar as perguntas abaixo com evidência real (código, dados, testes rápidos que você mesmo rodou), não chutar. Apague este bloco de instruções antes de entrega

## Perguntas que você precisa responder

1. **Algoritmo de matching**: hoje, as 6 sequências hardcoded em `main.py` (linhas 40-45) são comparadas contra músicas via uma tag pré-computada
   (`SEQ_FAMOSA`/`seqs_famosas`, vinda do CSV). Sequências cadastradas pelo usuário
   não têm essa tag — o matching precisa ser calculado em tempo real a partir da
   lista de acordes de cada música (`musica.acordes`/`musica.cifra`). O que vai
   definir "a sequência X aparece na música Y"? A ordem dos acordes importa?
   Repetições de acorde dentro da música importam? É preciso normalizar (ex.:
   maiúsculas/minúsculas, variações de escrita do mesmo acorde)?
2. **Validação da hipótese**: rode o algoritmo que você está considerando contra os
   dados reais em `data/top/dataset_final.csv`, para as 6 sequências hoje
   hardcoded, e confirme (ou refute) que ele reproduz os mesmos matches que o
   código atual produz via `seqs_famosas`. Esse é o bar mínimo de correção que
   você vai usar na fase de testes.
3. **Banco de dados**: quais bancos embarcados (sem serviço externo adicional) são
   viáveis dentro do container Docker único e local-only já documentado em
   `docs/adr/0001-local-only-docker-deploy.md`? O que cada opção implica para o
   `Dockerfile` atual e para a persistência dos dados entre reinícios do
   container?
4. **Frontend existente**: o que a página `#/porsequencia`
   (`static/templates/sequencia.html` +
   `static/assets/js/controllers/sequencia.js`) já faz? Repare que ela tem hoje uma
   lista *hardcoded no JavaScript* de 4 sequências (`sequencia1`..`sequencia4`),
   diferente das 6 que existem no backend — um detalhe real e pré-existente do
   código, não um erro seu, que vale entender antes de decidir o que precisa
   mudar.

## Registro das descobertas

[Para cada pergunta acima: o que você encontrou, com referência de onde (arquivo, linha, documentação, teste que você rodou).]

Irei utilizar a notação que o próprio comando "/research-codebase" utiliza para referencias arquivos (path/to/file.py:lines), achei muito interessante uma forma muito efetiva para referenciar o que encontrei.

1. No momento, de acordo com o que foi relatado no resersh-codebase, não existe nenhum cálculo que é realizado em tempo real para encontrar as músicas com as sequências famosas. (artifacts/reppit/research/entendimento-do-repositorio.md:195-196). Assim é realizado apenas um filtro nas músicas cuja o campo "SEQ_FAMOSA" contenha o índice como string.
Essa parte de gerar a tag é feito no pipeline em "scripts/generate_data_set.py", que compara com a cifra em minúsculas e verifica se os acordes da música pertencem ao conjunto de acordes da sequência. (artifacts/reppit/research/entendimento-do-repositorio.md:200-207)
Esse pré-processamento usa a regra de que o bloco de acordes da sequência aparece de forma contínua e na ordem exata durante a música e a música inteira só usa acordes que pertencem ao conjunto da sequência. (artifacts/reppit/research/algoritmo-de-matching.md:17-22)
Além disso, há uma normalização parcial. O casamento de acordes ignora maiúsculas/minúsculas (.lower()), entretanto não há uma normalização na grafia dos acordes (C# != Db, C/G != C). Por fim, não existe um critério definido sobre a repetição dos acordes. (artifacts/reppit/research/algoritmo-de-matching.md:23-25)

2. O agente em "artifacts/reppit/research/algoritmo-de-matching.md" reproduziu involuntariamente a regra de match com a base de dados real. Ele reproduziu o "get_famosas" sobre as músicas e comparou com o valor que foi salvo no campo "SEQ_FAMOSA". Ele encontrou 0 divergências nessa verificação. Mas, por garantia, pedi para ele gerar um algoritmo em que confirmasse isso. (artifacts/verifica_matching.py). Ao rodar o código, de fato fica confirmado que a hipótese do algoritmo de match está correto. A saída foi:
```bash
arquivo: data/top/dataset_final.csv
sequências: 6

== [A] cifra crua do CSV x tag crua do CSV ==
  músicas comparadas : 67585
  concordâncias      : 67585
  divergências       : 0
  músicas por sequência (calculado): {0: 199, 1: 296, 2: 4, 3: 5, 4: 7, 5: 3}

carregando main.py (lê o CSV inteiro)...
== [B] musica.cifra x musica.seqs_famosas (runtime) ==
  músicas comparadas : 67585
  concordâncias      : 67585
  divergências       : 0
  músicas por sequência (calculado): {0: 199, 1: 296, 2: 4, 3: 5, 4: 7, 5: 3}

  tags com mais de um índice em seqs_famosas: 0
  (o runtime testa "str(i) in seqs_famosas", então uma tag composta não casa com nada)

RESULTADO: regra reproduz as tags em todas as comparações
```

3. São vários os bancos que são viáveis dentro do container Docker único e local-only, entretanto cada um possui sua particularidade. Entre eles temos o SQLite, libSQL, DuckDB, LMDB e etc. (artifacts/reppit/research/bancos-embarcados-docker.md:129-143). Apesar do texto verborrágico, o modelo se propôs a explicar de fato cada uma das opção da melhor forma possível, de fato com uma visão de pesquisa/research.
Independentemente dessas escolhas, as principais mudanças para o Dockerfile são às mesmas. Sendo elas (artifacts/reppit/research/bancos-embarcados-docker.md:269-291):
    - Utilizar o caminho para o banco de dados fora do "/app";
    - Declarar um "VOLUME" no Dockerfile ou exigir "-v" no "docker run";
    - Dono do arquivo;
    - Variável de caminho ("ENV DECIFRAME_DB=/data/deciframe.db")
    - ".dockerignore"/".gitignore";
    - Criar tabela no start ("CREATE TABLE IF NOT EXISTS").
Com essas modificações e selecionado o banco de dados, precisamos definir o nível de "reiniciar" de um conteiner. Podemos definir que há três níveis diferentes:
    1. "docker restart" / "docker stop" + "docker start": **mesmo container**, a camada gravável é preservada.
    2. "docker rm" + "docker run" (ou "docker compose up" recriando): **novo container**; a camada gravável é descartada.
    3. "docker build" + "docker run" de imagem nova: além do item 2, o conteúdo gravado na imagem é o do build.
O requisito ser apenas "não volta a ser perdido ao reiniciar o container" é atendido pelo primeiro cenário mesmo sem volume, mas qualquer um dos outros dois perde os dados salvos. Persistência de verdade exige a volume ou bind mount.

4. Atualmente na página #/porsequencia possui 4 sequências hardcodeds. Sequências essas que são um sub-conjunto das 6 sequências fixas no backend (as duas ausentes são Em-G e C-A7-Dm-G7), porém que não são sincronizadas de nenhuma forma.
Atualmente a página realiza a chamada da função/requisição para resgatar às músicas com essa sequência de acordes pré-processadas no backend, opcionalmente pode filtrar por gênero musical. Ela também consegue limpar as sequências selecionadas e os resultados. (artifacts/reppit/research/entendimento-do-repositorio.md:294-304)


## Trade-offs identificados

[Opções reais que você considerou para cada decisão (algoritmo, banco, frontend) e os prós/contras de cada uma. Isso alimenta a fase de proposta — não decida ainda aqui.]

Bem, neste momento inicial a decisão de realizar o pré-processamento das músicas por sequência é muito boa. Uma vez que as sequências de acordes estão hardcoded, então são fixos. Evitanto processamento desnecessários em runtime.
Entretanto, temos um ponto muito complicado que é a falta de sincronia entre as sequências hardcoded no frontend e no backend. O que gera incopatibilidade entre as sequências salvas.
Claro, ao adicionar a possibilidade dos usuários adicionarem novas sequências essa forma fixa de pré-processamento deve mudar. E então deve ser feito a análise dos trade-offs.
- Quando rodar o algoritmo de match com a nova sequência? 
    - Se for em tempo de runtime, então toda vez que o usuário for pesquisar uma nova sequência ele vai ter a sensação de delay, pois está sendo feito o algoritmo de match em todas as músicas. Por outro lado, vai ser uma implementação mais fácil, não será necessário reescrever várias vezes o .csv das músicas
    - Se for logo após a adição da sequência e registrar no csv. Apenas no momento em que o usuário adicionou a nova sequência irá sentir um delay. Nas próximas vezes será muito rápido o retorno. Entretanto, o tempo de delay será um pouco mais alto, uma vez que será necessário reescrever o .csv com os novos indices da nova sequência.

