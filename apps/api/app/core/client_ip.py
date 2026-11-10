"""The caller's IP address, for rate limits and security logs.

Behind a reverse proxy (Vercel, a load balancer) the TCP peer is the proxy, so
every shop would share one rate-limit bucket. With TRUST_PROXY_HEADERS=true the
IP the proxy reports is used instead. Leave it false whenever clients can reach
the API directly: a client could otherwise forge these headers.
"""

from starlette.requests import Request

from app.core.config import get_settings

# Most specific first. Vercel sets x-vercel-forwarded-for and x-real-ip itself.
_SINGLE_IP_HEADERS = ("x-vercel-forwarded-for", "x-real-ip")


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        for header in _SINGLE_IP_HEADERS:
            value = request.headers.get(header, "").split(",")[0].strip()
            if value:
                return value
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"
