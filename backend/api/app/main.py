from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.context import REQUEST_ID_HEADER
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import get_logger
from app.core.middleware import CorrelationIdMiddleware
from app.routers import health

logger = get_logger(__name__)

app = FastAPI(title=settings.project_name)

# Order matters. Starlette applies middleware in reverse registration order,
# so CORS, registered last, is outermost and attaches its headers to error
# responses too. Otherwise a 500 reaches the browser as an opaque CORS failure
# and the real status is invisible.
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # JS cannot read a response header that is not exposed; the SPA needs the
    # id to put in a bug report.
    expose_headers=[REQUEST_ID_HEADER],
)
register_exception_handlers(app)

app.include_router(health.router)

logger.info("application_started", project=settings.project_name, aws_region=settings.aws_region)
if settings.auth_bypass_enabled:
    logger.warning("local_auth_bypass_enabled", detail="Authenticated routes serve a stand-in user. Local only.")
elif settings.local_auth_bypass:
    logger.warning("local_auth_bypass_ignored", detail="LOCAL_AUTH_BYPASS is set but this is a deployed task.")
