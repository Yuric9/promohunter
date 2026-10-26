# PromoHunter API

API em FastAPI que busca um produto no **Mercado Livre** e na **Shopee**, compara as ofertas,
escolhe a melhor e envia para o **WhatsApp** (via Evolution API). Também pode rodar sozinha
de tempos em tempos.

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

No painel você busca ofertas, envia para o WhatsApp, edita os produtos monitorados e
   liga/desliga a automação.

Janelinha de controle:

| Botão | O que faz |
|---|---|
| Abrir painel | Abre o painel no navegador de novo |
| Configurações | Abre o `.env` no Bloco de Notas (dados da Evolution API, token do ML) |
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

## Configuração (.env)

| Variável | Para que serve |
|---|---|
| `API_KEY` | Chave exigida no header `X-API-Key`. Gerada sozinha pelo `PromoHunter.pyw`. |
| `CORS_ORIGINS` | Sites que podem chamar a API (separados por vírgula). |
| `ML_ACCESS_TOKEN` | Token OAuth do Mercado Livre (a busca pública pode recusar sem ele). |
| `EVOLUTION_*` | Dados da sua instância da Evolution API. |
| `WHATSAPP_DEFAULT_NUMBER` / `WHATSAPP_DEFAULT_GROUP_ID` | Destino padrão das mensagens. |
| `REENVIO_HORAS` | Tempo antes de a mesma oferta poder ser enviada de novo (padrão 24h). |

## Rotas

| Método | Rota | O que faz |
|---|---|---|
| GET | `/api/promocoes/buscar?q=ps5` | Lista ofertas ranqueadas |
| GET | `/api/comparar?q=ps5` | Retorna a melhor oferta e a economia |
| POST | `/api/whatsapp/enviar?q=ps5` | Busca e envia a melhor oferta |
| GET/POST | `/api/configuracoes` | Lê/salva termos, filtros e intervalo |
| POST | `/api/automacao/iniciar` | Liga a busca automática |
| POST | `/api/automacao/parar` | Desliga a busca automática |
| GET | `/api/automacao/status` | Mostra se está rodando e a próxima execução |

Todas as respostas de busca trazem `avisos` — se uma plataforma falhar (bloqueio, token
ausente, sem internet), o motivo aparece ali.

## Como o .exe é gerado

O GitHub Actions (`.github/workflows/build-exe.yml`) roda os testes, monta o `.exe` num
Windows com o PyInstaller (`PromoHunter.spec`), abre o programa para conferir se o servidor
responde e guarda o arquivo. Para publicar uma versão na página Releases, crie uma tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Para gerar manualmente num Windows: `pip install -r requirements.txt pyinstaller` e
`pyinstaller PromoHunter.spec` — o arquivo sai em `dist\PromoHunter.exe`.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes usam dados falsos, então não precisam de internet nem de WhatsApp.

## Limitações conhecidas

- A **Shopee** bloqueia buscas automatizadas com frequência. Para algo estável, use a
  [API de afiliados da Shopee](https://affiliate.shopee.com.br/).
- O **Mercado Livre** pode exigir token OAuth: crie um app em
  https://developers.mercadolivre.com.br/ e coloque o token em `ML_ACCESS_TOKEN`.
- A automação só roda enquanto o PromoHunter estiver aberto e o computador ligado.
  Se ele reiniciar, clique em **Iniciar** no painel de novo.
