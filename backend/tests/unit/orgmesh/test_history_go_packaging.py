"""Optional overlay has no credentials or network and leaves API identity intact."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_optional_overlay_has_private_socket_and_no_credentials() -> None:
    overlay = json.loads(
        (
            ROOT / "deployment/docker_compose/docker-compose.orgmesh-history-go.yml"
        ).read_text()
    )
    core = overlay["services"]["orgmesh_history_go"]
    assert core["network_mode"] == "none"
    assert core["read_only"] is True
    assert core["cap_drop"] == ["ALL"]
    assert core["security_opt"] == ["no-new-privileges:true"]
    assert core["user"] == "0:0"
    assert (
        not {
            "ports",
            "expose",
            "env_file",
            "environment",
            "secrets",
            "privileged",
            "network",
        }
        & core.keys()
    )
    assert core["command"] == [
        "--socket",
        "/run/orgmesh-history/history.sock",
        "--peer-uid",
        "0",
    ]
    api = overlay["services"]["api_server"]
    assert set(api) == {"environment", "volumes"}
    assert (
        api["environment"]["ORGMESH_HISTORY_READ_BACKEND"]
        == "${ORGMESH_HISTORY_READ_BACKEND:-python}"
    )
    assert api["volumes"] == ["orgmesh_history_socket:/run/orgmesh-history:ro"]
    assert set(api["environment"]) == {
        "ORGMESH_HISTORY_READ_BACKEND",
        "ORGMESH_HISTORY_GO_SOCKET",
    }
    baseline = (
        ROOT / "deployment/docker_compose/docker-compose.orgmesh-presenton.yml"
    ).read_text()
    assert "ORGMESH_HISTORY_READ_BACKEND" not in baseline
    assert (
        "orgmesh_history_go"
        not in (ROOT / "deployment/docker_compose/docker-compose.yml").read_text()
    )


def test_go_image_contains_only_standalone_binary_and_socket_directory() -> None:
    dockerfile = (ROOT / "deployment/Dockerfile.orgmesh-history-go").read_text()
    assert "FROM golang:1.27.1-alpine" in dockerfile
    assert "FROM scratch" in dockerfile
    assert "CGO_ENABLED=0" in dockerfile
    assert "USER 0:0" in dockerfile
    assert "COPY services/orgmesh-core" in dockerfile
    assert "backend/onyx" not in dockerfile
    assert "EXPOSE" not in dockerfile
    assert "USER root" in (ROOT / "deployment/Dockerfile.orgmesh-backend").read_text()
