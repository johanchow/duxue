"""Private configuration validator/debug executor, without business API or worker startup."""
from fastapi import FastAPI

from app.api.v1.agent_admin import router

app = FastAPI(title="Agent configuration executor", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
