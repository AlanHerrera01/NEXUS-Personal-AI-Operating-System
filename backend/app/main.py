from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.infrastructure.logging import configure_logging
from app.presentation.api.agent_run_routes import router as agent_run_router
from app.presentation.api.event_ingress_routes import router as event_ingress_router
from app.presentation.api.health_routes import router as health_router
from app.presentation.api.llm_health_routes import router as llm_health_router
from app.presentation.api.llm_routes import router as llm_router
from app.presentation.api.memory_routes import router as memory_router
from app.presentation.api.proactive_rule_routes import router as proactive_rule_router
from app.presentation.api.routes.permission_requests import router as permission_requests_router
from app.presentation.api.routes.permissions import router as permissions_router
from app.presentation.api.runtime_routes import router as runtime_router
from app.presentation.api.scheduled_job_routes import router as scheduled_job_router
from app.presentation.api.skills_routes import router as skills_router
from app.presentation.dependencies.security import get_security_audit
from app.presentation.middleware.security import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Own the Always-On background loop for the life of the process.

    Startup order is deliberate. The recovery sweep runs *before* the scheduler
    starts, so executions abandoned by a previous process are marked FAILED
    before anything can pick them up -- otherwise the first tick would see
    phantom RUNNING rows and defer real work as if the user were at their
    concurrency limit.

    Startup failures are logged and swallowed rather than crashing the app. An
    unreachable database should surface as a failing health check, not as an
    API that refuses to boot for the interactive features that do not need it.
    """
    settings = get_settings()

    if not settings.always_on_enabled:
        logger.info("Always-On is disabled; background scheduler not started")
        yield
        return

    scheduler = None
    try:
        from app.infrastructure.always_on.polling_scheduler import PollingScheduler
        from app.presentation.lifespan.always_on import build_tick_handler

        tick_handler = build_tick_handler()
        await tick_handler.recover()
        logger.info("Always-On recovery sweep complete")

        scheduler = PollingScheduler(
            interval_seconds=settings.always_on_poll_interval_seconds
        )
        scheduler.start(tick_handler.tick)
        logger.info(
            "Always-On scheduler running every %.1fs",
            settings.always_on_poll_interval_seconds,
        )
    except Exception:
        logger.exception(
            "Always-On failed to start; the rest of the API will still serve"
        )
        scheduler = None

    try:
        yield
    finally:
        if scheduler is not None:
            await scheduler.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="NEXUS backend: reasoning, memory, tools, MCP, trust and sandboxed execution.",
        lifespan=lifespan,
    )
    
    # Middleware order matters. Starlette applies these outside-in in reverse
    # registration order, so the *last* registered is the *outermost* and runs
    # first on the way in. That ordering is deliberate:
    #
    #   rate limit -> body limit -> CORS -> security headers -> routes
    #
    # A rejected request is rate limited before its body is read, so a flood never
    # gets to spend bandwidth; CORS sits inside the body limit so an oversized
    # preflight fails cheaply; headers are applied innermost so that error
    # responses produced by the layers outside them still carry them, since
    # CORSMiddleware is the layer that can add headers to its own rejections.
    application.add_middleware(SecurityHeadersMiddleware, settings=settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        # Explicit, not "*". The UI sends Content-Type and X-Request-ID; a
        # wildcard would also let any site attempt an authenticated request
        # against this API.
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-RateLimit-Remaining", "Retry-After"],
        max_age=600,
    )
    application.add_middleware(
        BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes
    )
    application.add_middleware(
        RateLimitMiddleware, settings=settings, audit=get_security_audit()
    )
    # Outermost: a request id exists before anything else can log or reject.
    application.add_middleware(RequestIdMiddleware)
    
    application.include_router(health_router)
    application.include_router(memory_router)
    application.include_router(llm_router)
    application.include_router(llm_health_router)
    application.include_router(agent_run_router)
    application.include_router(skills_router)
    application.include_router(permissions_router)
    application.include_router(permission_requests_router)
    # Registered in Phase 10: these routes were written but never mounted, so
    # the sandboxed runtime was unreachable over HTTP despite being wired in the
    # composition root.
    application.include_router(runtime_router)
    # Always-On. These are mounted unconditionally so the UI can list, pause and
    # delete existing work while the feature is switched off; the endpoints that
    # would *start* work answer 503 instead.
    application.include_router(scheduled_job_router)
    application.include_router(proactive_rule_router)
    application.include_router(event_ingress_router)
    return application


app = create_app()
