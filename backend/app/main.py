"""TaskFlow FastAPI application entry point."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.admin.setup import setup_admin
from app.core.config import settings
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import CorrelationIdMiddleware, setup_logging
from app.modules.audit_logs.router import router as audit_logs_router
from app.modules.auth.router import router as auth_router
from app.modules.comments.router import router as comments_router
from app.modules.kanban.router import router as kanban_router
from app.modules.notifications.router import router as notifications_router
from app.modules.organizations.router import router as organizations_router
from app.modules.projects.router import router as projects_router
from app.modules.users.router import router as users_router

# Initialize logging
setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
)

# Register exception handlers
register_exception_handlers(app)


class TrustedOriginMiddleware(BaseHTTPMiddleware):
    """Validate Origin header on mutating requests against allowed CORS origins."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")
        if origin and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            allowed = settings.ALLOWED_ORIGINS
            base_origin = str(request.base_url).rstrip("/")
            if allowed and "*" not in allowed and origin not in allowed and origin != base_origin:
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "FORBIDDEN_ORIGIN",
                            "message": f"Untrusted origin '{origin}'.",
                            "details": None,
                        }
                    },
                )
        return await call_next(request)


# Register middlewares
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(TrustedOriginMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API v1 routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(kanban_router, prefix="/api/v1")
app.include_router(comments_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(audit_logs_router, prefix="/api/v1")

# Mount SQLAdmin site administration interface
admin = setup_admin(app, engine)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
