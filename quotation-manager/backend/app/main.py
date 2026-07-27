from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.booking import router as booking_router
from app.api.quotation import router as quotation_router
from app.config import CORS_ORIGINS

app = FastAPI(title="Quotation Manager API", redirect_slashes=False)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(booking_router, prefix="/api")
app.include_router(quotation_router, prefix="/api")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
