from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import anomaly, applications, auth, document_types, forecast, health, risk
from app.core.config import settings

app = FastAPI(title=settings.app_name, version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(document_types.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(forecast.router, prefix="/api")
app.include_router(risk.router, prefix="/api")
app.include_router(anomaly.router, prefix="/api")
