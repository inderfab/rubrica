from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from db import connection
from web.contacts import router as contacts_router
from web.folders import router as folders_router
from web.review import router as review_router
from web.imports import router as imports_router
from web.export import router as export_router
from web.archivio import router as archivio_router
from web.settings import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    connection.init_schema()
    yield


app = FastAPI(title="Rubrica", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="web/static"), name="static")
app.include_router(contacts_router)
app.include_router(folders_router)
app.include_router(review_router)
app.include_router(imports_router)
app.include_router(export_router)
app.include_router(archivio_router)
app.include_router(settings_router)


@app.get("/")
def root():
    return RedirectResponse(url="/kontakte")
