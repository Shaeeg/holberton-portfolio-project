"""Access policy for the operator dashboard and its JSON API."""

import hmac
import os

from flask import request


def protect_operator_routes(app, local_demo):
    password = os.getenv("OPERATOR_PASSWORD", "")
    username = os.getenv("OPERATOR_USERNAME", "operator")

    @app.before_request
    def check_operator_access():
        if request.path != "/" and not request.path.startswith("/api/"):
            return None
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
                return {"error": "Cross-origin operator request"}, 403
            if not request.is_json:
                return {"error": "Expected JSON"}, 415
        if not password:
            if local_demo:
                return None
            return {"error": "Operator access is not configured"}, 503
        auth = request.authorization
        if auth and auth.type == "basic":
            valid_user = hmac.compare_digest((auth.username or "").encode(), username.encode())
            valid_password = hmac.compare_digest((auth.password or "").encode(), password.encode())
            if valid_user and valid_password:
                return None
        return {"error": "Operator authentication required"}, 401, {
            "WWW-Authenticate": 'Basic realm="Support center", charset="UTF-8"'
        }

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        if request.path.startswith("/api/") and not response.get_etag()[0]:
            response.cache_control.no_store = True
        return response
