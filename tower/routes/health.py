from fastapi import APIRouter

SERVICE_NAME = "glasses-tower"
API_VERSION = "0.1.0"

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": API_VERSION,
    }
