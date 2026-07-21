"""CPG Pulse FastAPI service.

Serves sales, inventory-risk, promotion, retailer/product performance, and
data-quality/pipeline-ops endpoints directly off the dbt-built warehouse
marts (see dbt/models/marts/_exposures.yml for the formal dbt exposure
declaration). No business logic lives here -- every metric is already
computed in dbt; this layer is query + pagination + validation + error
handling only (docs/architecture.md section 5).

Run locally: `make api` (uvicorn api.main:app --reload --port 8000)
Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .routes import data_quality, health, inventory, products, promotions, retailers, sales, shipments

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("cpg_pulse_api")

app = FastAPI(
    title="CPG Pulse API",
    description=(
        "Omnichannel sales, inventory, and promotion intelligence for a "
        "fictional CPG manufacturer. Reads exclusively from the dbt-built "
        "warehouse marts -- see /docs for interactive request/response examples."
    ),
    version="1.0.0",
)

# Local dev: dashboard (Streamlit, port 8501) calls this API from the browser.
# A real deployment would restrict this to the actual dashboard origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("Database error handling %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": "Warehouse database is temporarily unavailable"})


app.include_router(health.router)
app.include_router(products.router)
app.include_router(sales.router)
app.include_router(inventory.router)
app.include_router(promotions.router)
app.include_router(retailers.router)
app.include_router(shipments.router)
app.include_router(data_quality.router)
