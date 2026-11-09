# PromoHunter API

Caçador de promoções que pesquisa produtos e lojas e publica ofertas em um canal do Telegram. Este README descreve também a configuração atual deste repositório, ajustada para monitorar lojas de calçados e moda esportiva.

## Configuração atual do monitoramento

A configuração versionada em `monitoramento.yml` contém **somente lojas**. A pesquisa automática usa o GitHub Actions, com agendamento a cada 30 minutos (`17` e `47` minutos de cada hora; o GitHub pode atrasar execuções).

Para cada loja configurada, o robô procura tênis (na Renner também tênis) e só considera ofertas que atendam aos dois filtros:

- preço atual de até **R$ 300**;
- desconto informado pela loja de pelo menos **20%**.

A comparação com o histórico de preços das lojas está desligada (`HISTORICO_MIN_DIAS=0` por padrão no código). Portanto, o robô não espera acumular histórico nem exige queda adicional em relação à média anterior; ele usa o preço e o desconto informados pela loja. Como qualquer desconto anunciado pode usar um preço original promocional, confira a oferta e as condições no site antes de comprar.

Lojas atualmente listadas em `monitoramento.yml`:

- Flávio's — https://www.flavios.com.br
- World Tennis — https://www.worldtennis.com.br
- Centauro — https://www.centauro.com.br
- adidas — https://www.adidas.com.br
- Nike — https://www.nike.com.br
- PUMA — https://br.puma.com
- Skechers — https://www.skechers.com.br
- New Balance — https://www.newbalance.com.br
- ASICS — https://www.asics.com.br
- Under Armour — https://www.underarmour.com.br
- Vans — https://www.vans.com.br
- Mizuno — https://www.mizuno.com.br
- FILA — https://www.fila.com.br
- Olympikus — https://www.olympikus.com.br
- Converse — https://www.converse.com.br
- Renner — https://www.lojasrenner.com.br

A configuração atual **não inclui** passagens, hospedagens ou feeds de blogs. O código e os formulários do projeto ainda oferecem esses tipos de monitoramento; formulários ativos no GitHub podem acrescentar itens à configuração durante a execução. Voos e hospedagens dependem da SerpApi e não fazem parte da lista fixa de lojas acima.

## Execução no GitHub Actions

O workflow `.github/workflows/monitorar.yml` é agendado a cada 30 minutos. No agendamento, ele executa o modo grátis; com a configuração atual, isso significa pesquisar as lojas listadas. Uma execução manual pode ser iniciada em **Actions → Monitorar promoções → Run workflow**. Marque **Só simular** para conferir as mensagens no log sem publicar no Telegram.

Para permitir publicação, configure em **Settings → Secrets and variables → Actions**:

| Secret | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token do bot criado no BotFather |
| `TELEGRAM_CHAT_ID` | Identificador do canal, por exemplo `@meu_canal` |
| `SERPAPI_KEY` | Necessária somente para pesquisas que usam a SerpApi, como Google Shopping, voos ou hotéis |

O workflow limita a publicação a 15 ofertas por execução e evita repetir uma oferta por 7 dias. O horário do cron é UTC e o GitHub pode atrasar ou pular execuções agendadas. Repositórios sem atividade podem ter o agendamento pausado pelo GitHub.

## Formas de monitoramento disponíveis no projeto

Além das lojas configuradas acima, o código permite configurar os seguintes tipos por formulários em **Issues → New issue** ou por `monitoramento.yml`:

| Tipo | Fonte | Observações |
|---|---|---|
| `lojas` | Sites de lojas compatíveis com VTEX ou Shopify | Pesquisa direta no site; os limites de preço e desconto são configuráveis. |
| `produtos` | Google Shopping via SerpApi | Pesquisa geral por produto; consome buscas da SerpApi. |
| `voos` | Google Voos via SerpApi | Pode aplicar limite de preço ou exigir indicação de preço abaixo do normal. |
| `hospedagens` | Google Hotéis via SerpApi | Pode filtrar por diária, nota e indicação de oferta. |
| `anuncios` | Feeds RSS ou busca via SerpApi | Pode filtrar anúncios por palavras e, opcionalmente, verificar passagens. |

O arquivo `monitoramento.yml` é somado aos formulários válidos abertos no GitHub. Apenas issues criados pelo proprietário ou colaboradores são aceitos pelo workflow. Para parar um monitoramento criado por formulário, feche o issue correspondente.

## Como usar no Windows

1. Baixe `PromoHunter.exe` na página **Releases** do repositório.
2. Coloque o executável em uma pasta própria; configurações, dados e logs ficam nessa pasta.
3. Abra o executável para iniciar o painel no navegador.

Também é possível instalar Python e executar `PromoHunter.pyw`, ou usar `./run.sh` (Linux/macOS) e `run.bat` (Windows). O painel local fica em http://localhost:8000 e a documentação da API em http://localhost:8000/docs.

## Configuração local (.env)

| Variável | Para que serve |
|---|---|
| `API_KEY` | Chave de acesso à API local. |
| `CORS_ORIGINS` | Origens permitidas no CORS, separadas por vírgula. |
| `SERPAPI_KEY` | Acesso às buscas do Google via SerpApi. |
| `SHOPEE_APP_ID` / `SHOPEE_SECRET` | Credenciais da API de Afiliados Shopee. |
| `ML_ACCESS_TOKEN` | Token OAuth do Mercado Livre. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Bot e canal de destino das promoções. |
| `REENVIO_HORAS` | Intervalo para permitir o reenvio de uma mesma oferta. |
| `HISTORICO_MIN_DIAS` | Dias mínimos de histórico para validar promoções de lojas; `0` desliga essa validação. |
| `QUEDA_MIN` | Queda mínima configurada para comparações históricas, quando aplicável. |

Não coloque tokens ou segredos no repositório. Use GitHub Actions Secrets ou um arquivo `.env` local não versionado.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes usam dados falsos e não precisam de internet nem de acesso ao Telegram.

## Limitações conhecidas

- A leitura direta de lojas funciona com plataformas VTEX ou Shopify; lojas em outras plataformas podem não ser compatíveis.
- Alguns sites podem bloquear solicitações automatizadas ou alterar suas APIs de catálogo.
- A execução no computador local só ocorre enquanto o PromoHunter estiver aberto e o computador ligado.
- O Mercado Livre pode exigir token OAuth. A Shopee pode bloquear consultas sem as credenciais de afiliado.
