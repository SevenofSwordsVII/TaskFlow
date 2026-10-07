"""TaskFlow FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(title="TaskFlow API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
