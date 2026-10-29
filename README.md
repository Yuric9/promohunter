# PromoHunter API

Caçador de promoções: pesquisa **produtos, passagens aéreas, hotéis, pousadas e promoções
anunciadas** na internet, compara os preços, escolhe as melhores ofertas e posta num
**canal do Telegram**. Roda sozinho no GitHub todo dia — ou no seu Windows, com painel.

## Rodando no GitHub (sem computador) ⭐

O robô de monitoramento roda **sozinho no GitHub Actions, a cada 30 minutos**, de graça e sem precisar
de computador ligado. Ele pesquisa tudo que está no arquivo **`monitoramento.yml`** e nos formulários:

| Tipo | Onde pesquisa | O que compara |
|---|---|---|
| `lojas` ⭐ | Direto no site da loja (VTEX ou Shopify, grátis) | Produtos com **20% ou mais** de desconto |
| `produtos` | Google Shopping | Preço e desconto em várias lojas |
| `voos` | Google Voos | Companhias aéreas + se o preço está abaixo do normal |
| `hospedagens` | Google Hotéis | Hotéis e pousadas: diária, nota e promoções |
| `anuncios` | Blogs de promoção (feed RSS, grátis) | Posts novos de promoções, filtrados por palavras |

As melhores ofertas são postadas no canal do Telegram, sem repetir a mesma oferta por 7 dias.

> 💸 **Grátis primeiro:** a execução automática (a cada 30 minutos) só confere **lojas e blogs**, que não
> gastam nada. Produtos do Google, passagens e hotéis usam a SerpApi e só rodam quando você pede
> (botão *Run workflow* ou o robô de conversa no Telegram).

Cada oferta de loja chega no canal assim:

```
📦 Tênis Mizuno Wave Rider 28
💰 Preço antigo: R$ 899,99
🔥 Preço novo: R$ 559,99
📉 Desconto: 38%
✅ Promoção verificada: 15% abaixo do preço normal (R$ 389,00 nos últimos 7 dias)
🔗 Link direto
```

> ✈️ **Passagens saindo de Goiânia:** os blogs indicam o destino em promoção e o robô confere no
> Google Voos o preço Goiânia → destino. Só posta se a rota estiver 10%+ abaixo do que custava há
> 30 dias ou abaixo da faixa normal (até `VERIFICACOES_DIA`=4 consultas por dia na SerpApi).
>
> 🏨 **Pousadas no estado de Goiás:** 1 consulta por dia no Google Hotéis; só posta as que o
> Google marca como "abaixo do normal".

> ⭐ **Lista de desejos pelo Telegram:** no privado com o robô, mande
> `/quero tênis asics novablast até 400` (ou `... sem infantil`), `/lista` e `/remover 15`.
> Cada desejo vira um formulário ⭐ na aba Issues; a cada 30 minutos o robô procura o produto em
> todas as lojas da lista e, quando chegar no preço, avisa você no privado e posta no canal.
> Os comandos precisam do robô de conversa na Vercel com `GITHUB_TOKEN` e `GITHUB_REPOSITORY`.

> 🛡️ **Contra preço falso:** muita loja mostra um preço "de" inflado o ano inteiro. Por isso o robô
> anota o preço de cada produto todo dia e só posta quando o preço de hoje está pelo menos **10%
> abaixo do preço normal** (mediana dos dias anteriores, com no mínimo 3 dias de histórico).
> Ajuste com as variáveis `QUEDA_MIN` e `HISTORICO_MIN_DIAS` (0 desliga a verificação).

### 1. Cadastrar as chaves (uma vez só)
No repositório: **Settings → Secrets and variables → Actions → New repository secret**.
Crie estes 3 secrets (nome exatamente igual, valor = a chave):

| Name | Secret |
|---|---|
| `SERPAPI_KEY` | sua chave da SerpApi |
| `TELEGRAM_BOT_TOKEN` | token do robô (BotFather) |
| `TELEGRAM_CHAT_ID` | `@link_do_canal` |

> Os secrets ficam criptografados: nem quem visita o repositório consegue ver.

### 2. Escolher o que monitorar (formulários)
Aba **Issues → New issue** e escolha um formulário:

| Formulário | O que preencher |
|---|---|
| 🏬 Monitorar loja (grátis) | Site da loja, palavras (opcional), desconto mínimo, preço máximo |
| ⭐ Lista de desejos (grátis) | Produto e preço máximo: avisa no privado e posta no canal quando chegar no preço |
| ✈️ Monitorar passagem aérea | Origem, destino, datas, adultos, preço máximo |
| 🏨 Monitorar hotel ou pousada | Local, datas, noites, diária máxima, nota mínima |
| 🛒 Monitorar produto | Nome do produto, preço máximo, desconto mínimo |
| 📢 Promoções de blogs (grátis) | Nome, palavras-chave, blogs |

Ao salvar, o robô **confere e responde no próprio issue** (✅ ativo ou ❌ o que corrigir).
Quando achar uma oferta, ele posta no canal **e comenta no issue**. Para parar, **feche o issue**.

> Só valem formulários criados por você (ou colaboradores): issues de outras pessoas são ignorados.
> Quem prefere escrever à mão pode usar o arquivo `monitoramento.yml` (tem exemplos comentados).

> Lojas e blogs (feeds RSS) são grátis. Produtos do Google, passagens e hotéis gastam 1 busca
> da SerpApi cada vez que você roda (o plano grátis tem 250 buscas/mês).

### 3. Testar agora (sem esperar o horário)
Aba **Actions → Monitorar promoções → Run workflow**. Marque **"Só simular"** para ver as
mensagens no log sem postar, ou deixe desmarcado para postar de verdade.
O horário automático é a cada 30 minutos (só lojas e blogs).

> O GitHub pausa agendamentos de repositórios sem nenhuma atividade por 60 dias. Se isso
> acontecer, ele avisa por e-mail e basta clicar em "Enable workflow" na aba Actions.

## Como usar no Windows (sem instalar nada)

1. Baixe o **`PromoHunter.exe`** na página **Releases** do repositório.
2. Coloque o arquivo numa pasta só dele (ex.: `Documentos\PromoHunter`). É ali que ele
   guarda as configurações (`.env`), os dados e o log.
3. **Dê dois cliques no `PromoHunter.exe`.** Abre uma janelinha de controle e o
   **painel no navegador**.

> Na primeira vez o Windows pode mostrar **"O Windows protegeu o computador"**, porque o
> programa não tem assinatura digital paga. Clique em **Mais informações → Executar assim mesmo**.

### Alternativa: com Python instalado

Instale o Python (https://www.python.org/downloads/, marcando **"Add python.exe to PATH"**)
e dê dois cliques em `PromoHunter.pyw`. Na primeira vez ele instala as dependências sozinho.

### Usando

No painel você busca ofertas, posta a melhor no Telegram, edita os produtos monitorados e
liga/desliga a automação.

Janelinha de controle:

| Botão | O que faz |
|---|---|
| Abrir painel | Abre o painel no navegador de novo |
| Configurações | Abre o `.env` no Bloco de Notas (chaves do Google Shopping, Shopee, ML e Telegram) |
| Ver log | Mostra o que aconteceu (útil quando algo dá errado) |
| Desligar | Para o PromoHunter (fechar a janelinha também desliga) |
| Iniciar junto com o Windows | Liga o PromoHunter automaticamente quando o PC inicia |

> A chave de acesso (`API_KEY`) é criada automaticamente na primeira execução e o painel
> já abre com ela. A API só aceita conexões do próprio computador (127.0.0.1).

> Se o `.pyw` abrir no Bloco de Notas em vez de rodar: clique com o botão direito →
> **Abrir com** → **Python**.

### Para quem prefere o terminal

`./run.sh` (Linux/macOS) ou `run.bat` (Windows) e acesse http://localhost:8000.
A documentação técnica das rotas fica em http://localhost:8000/docs.

## Ativando a busca geral (Google Shopping)

O Google Shopping junta ofertas de praticamente todas as lojas (Magalu, Amazon, Americanas,
Casas Bahia, Mercado Livre...). O PromoHunter usa a SerpApi para consultar.

1. Crie uma conta grátis em https://serpapi.com/users/sign_up (só e-mail).
2. Copie sua **API Key** em https://serpapi.com/manage-api-key.
3. Na janelinha do PromoHunter clique em **Configurações** e preencha `SERPAPI_KEY=sua_chave`.
4. Salve, clique em **Desligar** e abra o PromoHunter de novo.

> O plano grátis dá **250 buscas por mês**. Cada produto monitorado gasta 1 busca por rodada
> da automação — o painel mostra a estimativa de consumo. O intervalo padrão é de 12 horas (3 produtos ≈ 180 buscas/mês).

## Ativando o canal do Telegram

1. No Telegram, abra o **@BotFather**, envie `/newbot` e siga as instruções. Ele te dá um
   **token** (algo como `123456:ABC...`).
2. Crie um **canal** (pode ser público, ex.: `@minhas_promocoes`).
3. Nas configurações do canal, adicione o seu robô como **administrador** (com permissão
   de publicar mensagens).
4. Em **Configurações** do PromoHunter preencha:
   ```
   TELEGRAM_BOT_TOKEN=seu_token
   TELEGRAM_CHAT_ID=@minhas_promocoes
   ```
5. Salve, reinicie o PromoHunter e clique em **Testar Telegram** no painel.

## Ativando a Shopee Afiliados

Com a API de Afiliados a busca na Shopee para de ser bloqueada **e os links enviados
viram links de afiliado** (você ganha comissão nas vendas).

1. Cadastre-se em https://affiliate.shopee.com.br/ e aguarde a aprovação.
2. No painel de afiliado, abra **Open API** e solicite acesso. Você recebe um **AppID** e
   uma **Secret**.
3. Na janelinha do PromoHunter clique em **Configurações** e preencha:
   ```
   SHOPEE_APP_ID=seu_app_id
   SHOPEE_SECRET=sua_secret
   ```
4. Salve o arquivo, clique em **Desligar** e abra o PromoHunter de novo.
5. No painel, a seção **Integrações** deve mostrar ✅ Shopee Afiliados.

> Nunca compartilhe a Secret com ninguém nem coloque no GitHub — ela fica só no `.env`.

## Configuração (.env)

| Variável | Para que serve |
|---|---|
| `API_KEY` | Chave exigida no header `X-API-Key`. Gerada sozinha pelo `PromoHunter.pyw`. |
| `CORS_ORIGINS` | Sites que podem chamar a API (separados por vírgula). |
| `SERPAPI_KEY` | Chave da SerpApi para buscar no Google Shopping (todas as lojas). |
| `SHOPEE_APP_ID` / `SHOPEE_SECRET` | Chaves da API de Afiliados da Shopee (links de afiliado). |
| `ML_ACCESS_TOKEN` | Token OAuth do Mercado Livre (a busca pública pode recusar sem ele). |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Robô e canal do Telegram onde as promoções são postadas. |
| `REENVIO_HORAS` | Tempo antes de a mesma oferta poder ser postada de novo (padrão 24h). |

Só as fontes com chave preenchida são usadas na busca.

## Rotas

| Método | Rota | O que faz |
|---|---|---|
| GET | `/api/promocoes/buscar?q=ps5` | Lista ofertas ranqueadas |
| GET | `/api/comparar?q=ps5` | Retorna a melhor oferta e a economia |
| POST | `/api/telegram/postar?q=ps5` | Busca e posta a melhor oferta no Telegram |
| POST | `/api/telegram/teste` | Posta uma mensagem de teste no canal |
| GET | `/api/integracoes` | Quais fontes/destinos estão configurados |
| GET/POST | `/api/configuracoes` | Lê/salva termos, filtros e intervalo |
| POST | `/api/automacao/iniciar` | Liga a busca automática |
| POST | `/api/automacao/parar` | Desliga a busca automática |
| GET | `/api/automacao/status` | Mostra se está rodando e a próxima execução |

Todas as respostas de busca trazem `avisos` — se uma plataforma falhar (bloqueio, token
ausente, sem internet), o motivo aparece ali.

## Como o .exe é gerado

O GitHub Actions (`.github/workflows/build-exe.yml`) roda os testes, monta o `.exe` num
Windows com o PyInstaller (`PromoHunter.spec`), abre o programa para conferir se o servidor
responde e guarda o arquivo.

Para publicar uma versão na página Releases: aba **Actions** → **Gerar PromoHunter.exe** →
**Run workflow** → preencha a versão (ex.: `v1.0.1`). Também funciona enviando uma tag `v*`.

Para gerar manualmente num Windows: `pip install -r requirements.txt pyinstaller` e
`pyinstaller PromoHunter.spec` — o arquivo sai em `dist\PromoHunter.exe`.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes usam dados falsos, então não precisam de internet nem de Telegram.

## Limitações conhecidas

- Sem as chaves de afiliado, a **Shopee** bloqueia a busca (403). Veja "Ativando a Shopee Afiliados".
- O **Mercado Livre** pode exigir token OAuth: crie um app em
  https://developers.mercadolivre.com.br/ e coloque o token em `ML_ACCESS_TOKEN`.
- A automação só roda enquanto o PromoHunter estiver aberto e o computador ligado.
  Se ele reiniciar, clique em **Iniciar** no painel de novo.
