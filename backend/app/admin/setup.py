"""SQLAdmin setup and mounting helper."""

from fastapi import FastAPI
from sqladmin import Admin
from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin.auth import TaskFlowAdminAuth
from app.admin.views import ALL_ADMIN_VIEWS
from app.core.database import AsyncSessionLocal


def setup_admin(app: FastAPI, engine: AsyncEngine) -> Admin:
    """Initialize SQLAdmin with session authentication and register all model views.

    Mounts at /admin with secure session-based authentication backend.
    """
    admin_auth = TaskFlowAdminAuth()
    admin = Admin(
        app=app,
        engine=engine,
        session_maker=AsyncSessionLocal,
        base_url="/admin",
        title="TaskFlow Admin",
        authentication_backend=admin_auth,
    )

    for view in ALL_ADMIN_VIEWS:
        admin.add_view(view)

    return admin
