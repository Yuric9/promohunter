import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.auth import exigir_api_key
from app.config import settings
from app.models import SearchConfig
from app.services import mercadolivre
from app.services.busca import buscar_todas
from app.services.comparador import comparar_termo, rankear_melhores
from app.services.telegram import enviar_telegram, formatar_mensagem
from app.storage import ja_enviado, load_config, marcar_enviado, save_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("promohunter")

scheduler = BackgroundScheduler()
JOB_ID = "promohunter"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="PromoHunter API", version="1.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["*"], allow_headers=["*"])


PAINEL = Path(__file__).parent / "static" / "painel.html"


@app.get("/", include_in_schema=False)
def painel():
    return FileResponse(PAINEL)


@app.get("/saude")
def saude():
    return {"status": "PromoHunter rodando", "docs": "/docs"}


@app.get("/api/integracoes", dependencies=[Depends(exigir_api_key)])
def integracoes():
    """Mostra no painel quais chaves foram preenchidas no .env (sem revelar os valores)."""
    return {
        "google_shopping": bool(settings.serpapi_key),
        "shopee_afiliados": bool(settings.shopee_app_id and settings.shopee_secret),
        "mercado_livre": mercadolivre.configurado(),
        "telegram": bool(settings.telegram_bot_token and settings.telegram_chat_id),
    }


@app.get("/api/configuracoes", dependencies=[Depends(exigir_api_key)])
def get_config():
    return load_config()


@app.post("/api/configuracoes", dependencies=[Depends(exigir_api_key)])
def set_config(cfg: SearchConfig):
    save_config(cfg)
    if scheduler.get_job(JOB_ID):
        scheduler.reschedule_job(JOB_ID, trigger=IntervalTrigger(minutes=cfg.intervalo_minutos))
    return {"msg": "salva", "config": cfg}


@app.get("/api/promocoes/buscar", dependencies=[Depends(exigir_api_key)])
def buscar(q: str, limite: int = Query(10, ge=1, le=50), desconto_min: int = Query(0, ge=0, le=100)):
    res = buscar_todas(q, limite)
    ofertas = rankear_melhores(res.produtos, desconto_min)
    return {"termo": q, "total": len(ofertas), "ofertas": ofertas, "avisos": res.avisos}


@app.get("/api/comparar", dependencies=[Depends(exigir_api_key)])
def comparar(q: str, limite: int = Query(10, ge=1, le=50), desconto_min: int = Query(20, ge=0, le=100)):
    res = buscar_todas(q, limite)
    return {"comparativo": comparar_termo(q, res.produtos, desconto_min), "avisos": res.avisos}


@app.post("/api/telegram/postar", dependencies=[Depends(exigir_api_key)])
def postar(q: str, desconto_min: int = 0):
    res = buscar_todas(q, 10)
    comp = comparar_termo(q, res.produtos, desconto_min)
    if not comp:
        return {"erro": "sem ofertas", "avisos": res.avisos}
    msg = formatar_mensagem(comp)
    envio = enviar_telegram(msg, comp.melhor_oferta.imagem)
    if envio["ok"]:
        marcar_enviado(comp.melhor_oferta.link)
    return {"comparativo": comp, "telegram": envio, "msg": msg, "avisos": res.avisos}


@app.post("/api/telegram/teste", dependencies=[Depends(exigir_api_key)])
def telegram_teste():
    return enviar_telegram("✅ <b>PromoHunter</b> conectado! As promoções vão aparecer aqui.")


def job():
    cfg = load_config()
    for termo in cfg.termos:
        res = buscar_todas(termo, 10)
        comp = comparar_termo(termo, res.produtos, cfg.desconto_min, cfg.preco_min, cfg.preco_max)
        if not comp:
            log.info("[%s] nenhuma oferta dentro dos filtros", termo)
            continue
        if ja_enviado(comp.melhor_oferta.link):
            log.info("[%s] melhor oferta já enviada recentemente, pulando", termo)
            continue
        envio = enviar_telegram(formatar_mensagem(comp), comp.melhor_oferta.imagem)
        if envio["ok"]:
            marcar_enviado(comp.melhor_oferta.link)
        else:
            log.error("[%s] falha ao postar no Telegram: %s", termo, envio["erro"])


@app.post("/api/automacao/iniciar", dependencies=[Depends(exigir_api_key)])
def iniciar():
    cfg = load_config()
    if not scheduler.running:
        scheduler.start()
    scheduler.add_job(job, IntervalTrigger(minutes=cfg.intervalo_minutos), id=JOB_ID, replace_existing=True)
    return {"msg": f"Automação a cada {cfg.intervalo_minutos} min"}


@app.post("/api/automacao/parar", dependencies=[Depends(exigir_api_key)])
def parar():
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)
        return {"msg": "Automação parada"}
    return {"msg": "Automação não estava rodando"}


@app.get("/api/automacao/status", dependencies=[Depends(exigir_api_key)])
def status():
    j = scheduler.get_job(JOB_ID)
    return {"rodando": j is not None, "proxima_execucao": j.next_run_time if j else None}

