from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app import config
from app.db import Base, SessionLocal, engine
from app.models import User
from app.graph import models as _graph_models  # noqa: F401
from app.graph.errors import (
    LLMBadOutput,
    LLMTimeout,
    LLMUnavailable,
)
from app.routers import admin, auth, graph
from app.security import hash_password


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    if config.SYSADMIN_EMAIL and config.SYSADMIN_PASSWORD:
        with SessionLocal() as db:
            if not db.scalar(select(func.count()).select_from(User)):
                db.add(
                    User(
                        email=config.SYSADMIN_EMAIL.lower(),
                        name="System Admin",
                        password_hash=hash_password(config.SYSADMIN_PASSWORD),
                        role="sysAdmin",
                    )
                )
                db.commit()
    yield


app = FastAPI(title="Graph Knowledge System - Admin", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(graph.router)


@app.exception_handler(LLMTimeout)
def _llm_timeout(request: Request, exc):
    return JSONResponse(
        {"detail": "The language model took too long. Try again."}, 504
    )


@app.exception_handler(LLMUnavailable)
@app.exception_handler(LLMBadOutput)
def _llm_down(request: Request, exc):
    return JSONResponse(
        {"detail": "The language model is unavailable. Try again later."}, 502
    )
