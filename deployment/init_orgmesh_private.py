"""Generate a separate private deployment configuration without printing secrets."""

import argparse
import ipaddress
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="Public HTTPS origin")
    parser.add_argument("--email-domains", required=True)
    parser.add_argument("--tls-directory", required=True, type=Path)
    parser.add_argument("--bind", default="127.0.0.1", type=ipaddress.ip_address)
    parser.add_argument("--port", default=3443, type=int)
    parser.add_argument(
        "--subnet", default="172.16.248.0/24", type=ipaddress.ip_network
    )
    args = parser.parse_args()
    url = urlsplit(args.origin)
    try:
        _ = url.port
    except ValueError:
        parser.error("HTTPS origin contains an invalid port")
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
        or not re.fullmatch(r"[a-zA-Z0-9.-]+", url.hostname)
    ):
        parser.error("Use an HTTPS origin with a DNS hostname and optional port")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    domains = [item.strip().lower() for item in args.email_domains.split(",")]
    if not domains or any(
        not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", item) for item in domains
    ):
        parser.error("Use comma-separated corporate email domains")
    tls_dir = args.tls_directory.expanduser().resolve()
    if any(char in str(tls_dir) for char in ("\n", "\r", "'")):
        parser.error("Certificate directory contains unsupported characters")
    if any(not (tls_dir / name).is_file() for name in ("tls.crt", "tls.key")):
        parser.error("Certificate directory must contain tls.crt and tls.key")
    origin = args.origin.rstrip("/")
    values = {
        "IMAGE_TAG": "v4.8.1",
        "ONYX_BACKEND_IMAGE": "orgmesh-backend:local",
        "ONYX_WEB_SERVER_IMAGE": "orgmesh-web:local",
        "ONYX_MODEL_SERVER_IMAGE": "onyxdotapp/onyx-model-server:v4.8.1",
        "AUTH_TYPE": "basic",
        "AUTH_BACKEND": "postgres",
        "CACHE_BACKEND": "redis",
        "FILE_STORE_BACKEND": "postgres",
        "ORGMESH_LOCAL_ACCESS": "false",
        "LICENSE_ENFORCEMENT_ENABLED": "false",
        "ENABLE_PAID_ENTERPRISE_EDITION_FEATURES": "false",
        "REQUIRE_EMAIL_VERIFICATION": "true",
        "VALID_EMAIL_DOMAINS": ",".join(domains),
        "WEB_DOMAIN": origin,
        "CORS_ALLOWED_ORIGIN": origin,
        "DISABLE_VECTOR_DB": "false",
        "PDF_OCR_ENABLED": "true",
        "POSTGRES_PASSWORD": "Om!" + secrets.token_urlsafe(36),
        "USER_AUTH_SECRET": secrets.token_urlsafe(48),
        "ENCRYPTION_KEY_SECRET": secrets.token_urlsafe(48),
        "OPENSEARCH_ADMIN_PASSWORD": "Om!" + secrets.token_urlsafe(36),
        "S3_AWS_ACCESS_KEY_ID": secrets.token_urlsafe(18),
        "S3_AWS_SECRET_ACCESS_KEY": secrets.token_urlsafe(36),
        "ORGMESH_PRIVATE_HOST": url.hostname,
        "ORGMESH_PRIVATE_BIND": str(args.bind),
        "ORGMESH_PRIVATE_PORT": str(args.port),
        "ORGMESH_PRIVATE_SUBNET": str(args.subnet),
        "ORGMESH_TLS_DIRECTORY": str(tls_dir),
        "DISABLE_TELEMETRY": "true",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "DISPOSABLE_EMAIL_DOMAINS_URL": "",
    }
    destination = Path(__file__).resolve().parent / "docker_compose/.env.private"
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(
            "# Configure SMTP_SERVER, SMTP_PORT, EMAIL_FROM and SMTP credentials before signup.\n"
        )
        stream.write(
            "\n".join(f"{key}='{value}'" for key, value in values.items()) + "\n"
        )
    print(
        "Private configuration created with mode 0600. Configure SMTP before the first admin signs up."
    )


if __name__ == "__main__":
    main()
