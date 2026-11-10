from __future__ import annotations

import uvicorn

from promhis.config import settings


def main() -> None:
    # proxy_headers/forwarded_allow_ips only matter when PROMHIS_TRUST_PROXY
    # is explicitly set — this app sits directly on the internet for a bare-
    # metal self-host, so trusting X-Forwarded-For/-Proto by default would
    # let any client spoof its own source IP. Only set this true when there's
    # genuinely a trusted reverse proxy/load balancer in front of Promhis.
    uvicorn.run(
        "promhis.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        proxy_headers=settings.trust_proxy,
        forwarded_allow_ips="*" if settings.trust_proxy else None,
    )


if __name__ == "__main__":
    main()
