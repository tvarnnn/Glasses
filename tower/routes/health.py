from fastapi import APIRouter, Request

SERVICE_NAME = "glasses-tower"
API_VERSION = "0.1.0"

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict:
    container = request.app.state.module_container
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": API_VERSION,
        "module_state": container.state.value,
        "module_id": container.descriptor.id,
    }
