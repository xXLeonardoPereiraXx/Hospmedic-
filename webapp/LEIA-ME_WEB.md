# HBI Web — guia da interface e do deploy

A versão web coloca o HBI no navegador, com login, para a equipe da HospMedic
usar sem mexer em terminal. Ela **reaproveita todo o pipeline** (`hbi/`); a
pasta `webapp/` é só a camada web (Flask).

## Rodar localmente (seu PC)

Dentro da pasta do projeto (a que contém `main.py` e a pasta `hbi/`):

```bash
pip install -r requirements.txt

# define os usuários (login:senha, separados por ';') e uma chave de sessão
# Windows (PowerShell):
$env:HBI_USERS = "leonardo:minhaSenha;maria:outraSenha"
$env:HBI_SECRET_KEY = "qualquer-texto-secreto"
python -m webapp.app

# Linux/Mac:
HBI_USERS="leonardo:minhaSenha" HBI_SECRET_KEY="segredo" python -m webapp.app
```

Abra `http://localhost:5000` no navegador e entre com um dos logins definidos.

Se você **não** definir `HBI_USERS`, é criado um usuário padrão: `admin` / `hbi123`
(troque antes de publicar!).

## Colocar na internet (Render)

O Render provisiona **HTTPS automaticamente** — nada a configurar do seu lado.

1. Suba o projeto para um repositório no GitHub.
2. No painel do Render: **New > Blueprint** e aponte para o repositório
   (o arquivo `render.yaml` já descreve o serviço).
3. Na aba **Environment** do serviço, defina:
   - `HBI_USERS` → os logins da equipe, ex.: `leonardo:senhaForte;maria:outra`
   - (o `HBI_SECRET_KEY` é gerado automaticamente pelo Render)
4. O Render instala as dependências, sobe com `gunicorn` e te dá uma URL
   `https://...onrender.com`.

### Por que os logins não se perdem

No plano gratuito do Render o disco é efêmero (zera a cada reinício). Para que
isso não derrube os acessos, os usuários são **re-semeados a partir de
`HBI_USERS` a cada inicialização** (ver `webapp/database.py`). Ou seja: mesmo
que o banco SQLite seja recriado do zero, os logins da equipe voltam sozinhos.

O histórico de análises, por ficar no mesmo SQLite efêmero, é reiniciado quando
o serviço "dorme" e acorda — no free tier isso é esperado. Se o histórico
persistente virar requisito, o próximo passo é um disco pago no Render ou um
banco externo.

## Observações do plano gratuito

- **Primeiro acesso após inatividade**: o serviço hiberna após ~15 min parado e
  leva cerca de 1 minuto para acordar na requisição seguinte.
- **Limite de uso**: 750 horas de instância por mês (suficiente para uso normal
  de uma equipe pequena).

## Segurança

- Senhas são guardadas com **hash** (`werkzeug.security`), nunca em texto puro.
- O acesso a todas as telas (exceto login) exige sessão autenticada.
- Em produção, use senhas fortes em `HBI_USERS` e nunca versione o `.env`.


## Desempenho em instâncias pequenas

O free tier do Render oferece **512 MB de RAM e 0.1 CPU**. Duas medidas
tornam a análise viável nesse orçamento:

**Memória constante.** As páginas do PDF são percorridas uma a uma e o cache
de objetos de cada página é liberado após o uso. Antes, todas as páginas eram
mantidas em memória e o consumo crescia com o tamanho do documento — um edital
de 83 páginas chegava a ~850 MB e a instância era encerrada por falta de
memória. Hoje o pico fica em torno de 110 MB, mesmo em editais de 200+ páginas.

**Processamento fora da requisição.** A análise roda numa thread; a requisição
apenas enfileira a tarefa e redireciona para uma página de progresso, que
consulta o estado a cada 2 s e avança sozinha quando termina. Isso evita o
tempo limite da conexão HTTP em análises de vários minutos — inevitável com
0.1 CPU — e dá retorno visual ao usuário.

Por isso o serviço roda com **um worker e várias threads**
(`--workers 1 --threads 8`): as tarefas ficam na memória do processo, e um
segundo worker não as enxergaria ao responder a consulta de estado.

Se a análise ainda ficar lenta demais para o uso diário, o caminho é o plano
**Starter (US$ 7/mês)**, que mantém 512 MB mas sobe para 0.5 CPU — cinco vezes
mais rápido — e elimina a hibernação. Nada no código precisa mudar.
