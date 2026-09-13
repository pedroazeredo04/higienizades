"""Application factory and wiring."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_config
from app.jobs import backfill_instances, build_scheduler
from app.routers import auth, chores, dashboard, history, leaderboard, settings
from app.security import CsrfFailure, NotAuthenticated, NotAuthorised
from app.templating import TEMPLATE_DIR, templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STATIC_DIR = TEMPLATE_DIR.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    scheduler = None
    if config.enable_jobs:
        backfill_instances()
        scheduler = build_scheduler()
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(title="higienizades", docs_url=None, redoc_url=None, lifespan=lifespan)

    app.add_middleware(
        SessionMiddleware,
        secret_key=config.secret_key,
        max_age=config.session_max_age_days * 24 * 3600,
        same_site="lax",
        https_only=False,  # plain HTTP on the LAN; see the README's security note
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def no_store_dynamic_pages(request: Request, call_next):
        """Every rendered page embeds a CSRF token tied to the session cookie,
        so none of them may be cached.

        Without this, Safari on iOS will happily replay a cached login page
        carrying a token from an older session: the POST then fails CSRF and
        bounces straight back to the same cached page, which looks exactly like
        a dead "Sign in" button. Chrome revalidates, which is why this only
        ever showed up on iPhones. Static assets keep their normal
        ETag-based caching.
        """
        response = await call_next(request)
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    for module in (auth, dashboard, chores, leaderboard, history, settings):
        app.include_router(module.router)

    @app.exception_handler(NotAuthenticated)
    async def _not_authenticated(request: Request, exc: NotAuthenticated):
        # HTMX would swap a redirect's HTML into the page; tell it to navigate.
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                request,
                "partials/redirect.html",
                {"request": request},
                status_code=401,
                headers={"HX-Redirect": "/login"},
            )
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(CsrfFailure)
    async def _csrf_failure(request: Request, exc: CsrfFailure):
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                request,
                "partials/redirect.html",
                {"request": request},
                status_code=400,
                headers={"HX-Redirect": request.url.path},
            )
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "title": "That form had gone stale",
                "message": (
                    "Your browser sent a sign-in form from an older session, so it "
                    "was not accepted. Reload the page and try again."
                ),
                "detail": (
                    "If it keeps happening on an iPhone, check Settings \u2192 Apps "
                    "\u2192 Safari and make sure \u201cBlock All Cookies\u201d is off, "
                    "then close the tab and reopen the address."
                ),
                "back_url": request.url.path,
                "back_label": "Back to sign in",
            },
            status_code=400,
        )

    @app.exception_handler(NotAuthorised)
    async def _not_authorised(request: Request, exc: NotAuthorised):
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "title": "Admins only",
                "message": "Ask a household admin to make that change.",
            },
            status_code=403,
        )

    return app


app = create_app()
