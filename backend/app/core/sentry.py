"""
Error monitoring.

No error monitoring existed anywhere in this project before this -- every
bug found this session was found by a human clicking into the right page
at the right time. This wires up Sentry so the next silent failure gets
caught and reported automatically instead.

Without SENTRY_DSN set, init() is simply never called -- sentry_sdk has no
effect at all, not even import overhead beyond the package itself. Same
deferred-but-ready shape as RESEND_API_KEY (email_service.py): ship the
integration now, it activates the moment a DSN is added, no other code
changes needed. Call init() once, at process startup, before the FastAPI
app is constructed.
"""
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from app.core.config import settings


def init_sentry() -> None:
    if not settings.SENTRY_DSN:
        return
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        # Sampling, not "capture everything" -- a free-tier account with
        # this scale of traffic doesn't need 100% trace volume to be
        # useful, and staying under the free-tier cap matters more than
        # completeness here. Errors are always captured regardless of this
        # setting; this only controls performance-trace sampling.
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
