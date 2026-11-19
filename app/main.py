from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings
from app.database import engine, Base, AsyncSessionLocal
from app.models import SystemSetting, utc_now
from app.routes import client, admin
from app.storage import storage_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure database schema exists
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Initialize default system setting if not already present
    async with AsyncSessionLocal() as session:
        stmt = select(SystemSetting).where(SystemSetting.key == "global_mode")
        res = await session.execute(stmt)
        if not res.scalar_one_or_none():
            default_setting = SystemSetting(
                key="global_mode",
                value=settings.DEFAULT_GLOBAL_MODE,
                updated_at=utc_now()
            )
            session.add(default_setting)
            await session.commit()

    # Pre-seed sample images if folders are empty
    storage_manager._create_sample_image_if_empty("train")
    storage_manager._create_sample_image_if_empty("test")

    print(f"[{settings.APP_NAME}] Startup complete. Server listening.")
    yield
    print(f"[{settings.APP_NAME}] Shutting down.")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="High-reliability benchmark and evaluation server for team competitions",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Image-ID", "X-Image-Name", "X-Mode", "Content-Disposition"]
)

# Include API routers
app.include_router(client.router)
app.include_router(admin.router)


@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness probe for AWS Application Load Balancer (ALB)."""
    return {"status": "healthy", "mode": settings.ENV}


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": settings.APP_NAME,
        "status": "online",
        "docs": "/docs" if settings.ENV != "production" else "disabled"
    }
