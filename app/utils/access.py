"""Access-control decorators.

`require_jobs` gates the Jobs feature (job cards + the labour/employee routes jobs depend on).
Unlike `require_full_mode` (the full-suite gate that checks `User.platform_mode in ('full','both')`),
Jobs is deliberately available to EVERY accounting mode — sync, full, and both — because the job
record and its invoice/labour links do not depend on whether the user syncs to QuickBooks/Xero.
It is instead governed by the `ENABLE_JOBS` config flag (default ON; kill-switch via Railway env),
mirroring the ENABLE_VOICE_TO_QUOTE / ENABLE_QUOTE_BUILDER pattern.

Note: routes still carry `@login_required` separately; this decorator only checks the feature flag.
"""
from functools import wraps

from flask import abort, current_app


def require_jobs(f):
    """Allow the Jobs feature for any authenticated user when ENABLE_JOBS is on; else 404 (hidden)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_app.config.get('ENABLE_JOBS', True):
            abort(404)
        return f(*args, **kwargs)
    return decorated
