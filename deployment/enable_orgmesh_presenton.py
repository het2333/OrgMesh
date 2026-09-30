"""Enable the private presentation overlay without printing runtime secrets."""

import argparse
import os
import secrets
from pathlib import Path


def enable(path: Path) -> None:
    text = path.read_text()
    lines = text.splitlines()
    overlay = "docker-compose.orgmesh-presenton.yml"
    found = False
    for index, line in enumerate(lines):
        if line.startswith("COMPOSE_FILE="):
            value = line.partition("=")[2].strip("\"'")
            if overlay not in value.split(":"):
                lines[index] = "COMPOSE_FILE=" + value + ":" + overlay
            found = True
    if not found:
        if path.name != ".env.private":
            raise ValueError("Set COMPOSE_FILE before enabling Presenton")
        lines.append(
            "COMPOSE_FILE=docker-compose.yml:docker-compose.orgmesh-full.yml:docker-compose.orgmesh-private.yml:"
            + overlay
        )
    if not any(line.startswith("ORGMESH_PRESENTON_SECRET=") for line in lines):
        lines.append("ORGMESH_PRESENTON_SECRET=" + secrets.token_urlsafe(48))
    temporary = path.with_suffix(".presenton.tmp")
    temporary.write_text("\n".join(lines) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env-file", type=Path, default=Path("deployment/docker_compose/.env")
    )
    args = parser.parse_args()
    enable(args.env_file)
    print("Presenton private overlay enabled; runtime secret stored in the env file.")
