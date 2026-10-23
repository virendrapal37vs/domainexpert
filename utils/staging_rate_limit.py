"""Direct restricted-staging 429 responses; never redirect or relax a limit."""
import math
import time
from flask import jsonify, make_response, render_template_string, request


def rate_limit_response():
    from limiter import limiter
    retry = None
    try:
        current = limiter.current_limit
        if current is not None:
            reset = current.reset_at
            if isinstance(reset, (int, float)) and math.isfinite(reset):
                retry = max(1, math.ceil(reset - time.time()))
    except Exception:
        # Storage failures must not change the rejection into a redirect or 500.
        pass
    message = "Too many requests. " + (
        f"Try again in {retry} seconds." if retry else "Wait for the request limit to reset before trying again."
    )
    if request.is_json or request.path.startswith(("/api/", "/auth/")) or request.accept_mimetypes.best == "application/json":
        body = dict(status="error", message=message)
        if retry is not None:
            body['retry_after'] = retry
        response = make_response(jsonify(body), 429)
    else:
        response = make_response(render_template_string('''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Please wait · DomainXpert Trade</title></head>
<body><main><h1>Too many requests</h1><p>{{ message }}</p>
<p>Return to your account when ready. Refreshing a submitted form may send it again.</p>
<a href="/broker">Back to account</a></main></body></html>''', message=message), 429)
    response.headers['Cache-Control'] = 'no-store'
    if retry is not None:
        response.headers['Retry-After'] = str(retry)
    return response
