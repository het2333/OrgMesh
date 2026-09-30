import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values


def test_generated_private_configuration_passes_auth_startup_validation(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[4]
    deployment = tmp_path / "deployment"
    (deployment / "docker_compose").mkdir(parents=True)
    generator = deployment / "init_orgmesh_private.py"
    shutil.copyfile(repository / "deployment/init_orgmesh_private.py", generator)
    tls_directory = tmp_path / "tls"
    tls_directory.mkdir()
    for name in ("tls.crt", "tls.key"):
        (tls_directory / name).touch()

    subprocess.run(
        [
            sys.executable,
            str(generator),
            "--origin",
            "https://knowledge.example.com",
            "--email-domains",
            "example.com",
            "--tls-directory",
            str(tls_directory),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    config = dotenv_values(deployment / "docker_compose/.env.private")
    environment = {key: value for key, value in config.items() if value is not None}
    environment["PYTHONPATH"] = str(repository / "backend")
    environment["LOG_TO_FILE"] = "false"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from onyx.auth.users import verify_user_auth_secret; "
            "verify_user_auth_secret()",
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
