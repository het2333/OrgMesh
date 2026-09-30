#!/usr/bin/env python3
"""Apply the backend adapter to the pinned Presenton checkout."""

import argparse
import shutil
import subprocess
from pathlib import Path

PINNED_REVISION = "2dcbde772ce46687c5c220f4e1e4886bdfe91cc9"
INTEGRATION_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_DIRECTORY = INTEGRATION_DIRECTORY.parent.parent


def replace_once(path: Path, original: str, replacement: str) -> None:
    content = path.read_text(encoding="utf-8")
    if replacement in content:
        return
    if content.count(original) != 1:
        raise ValueError(f"Pinned upstream patch does not match {path}")
    path.write_text(content.replace(original, replacement, 1), encoding="utf-8")


def prepare_backend(checkout: Path) -> None:
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != PINNED_REVISION:
        raise ValueError(f"Expected Presenton {PINNED_REVISION}; found {revision}")
    backend = checkout / "servers" / "fastapi"
    shutil.copyfile(
        INTEGRATION_DIRECTORY / "backend" / "orgmesh.py",
        backend / "api" / "v1" / "orgmesh.py",
    )
    shutil.copyfile(
        INTEGRATION_DIRECTORY / "backend" / "orgmesh_tokens.py",
        backend / "utils" / "orgmesh_tokens.py",
    )
    replace_once(
        backend / "api" / "main.py",
        "from api.v1.auth.router import API_V1_AUTH_ROUTER\n",
        "from api.v1.auth.router import API_V1_AUTH_ROUTER\n"
        "from api.v1.orgmesh import ORGMESH_ROUTER\n",
    )
    replace_once(
        backend / "api" / "main.py",
        "app.include_router(API_V1_AUTH_ROUTER)\n",
        "app.include_router(API_V1_AUTH_ROUTER)\napp.include_router(ORGMESH_ROUTER)\n",
    )
    replace_once(
        backend / "api" / "middlewares.py",
        '        "/api/v1/auth/status",\n',
        '        "/api/v1/auth/status",\n        "/api/v1/orgmesh/session",\n',
    )
    replace_once(
        backend / "api" / "v1" / "auth" / "bootstrap.py",
        "logger = logging.getLogger(__name__)\n",
        "from utils.orgmesh_tokens import is_orgmesh_bridge_configured\n\n"
        "logger = logging.getLogger(__name__)\n",
    )
    replace_once(
        backend / "api" / "v1" / "auth" / "bootstrap.py",
        '    """Migrate the old single-admin account or initialize it from environment."""\n',
        '    """Migrate the old single-admin account or initialize it from environment."""\n'
        "    # OrgMesh manages accounts. Native users retain their original ownership.\n"
        "    if is_orgmesh_bridge_configured():\n"
        "        return\n",
    )
    replace_once(
        backend / "utils" / "asset_directory_utils.py",
        '    if path.startswith("/app_data/"):\n',
        "    if path.startswith(\n"
        '        ("/presenton/app_data/", "/presenton/static/", "/presenton/vendor/fonts/")\n'
        "    ):\n"
        '        path = path[len("/presenton"):]\n\n'
        '    if path.startswith("/app_data/"):\n',
    )
    replace_once(
        backend / "services" / "chat" / "slide_ui_helpers.py",
        "from utils.latex_text import replace_text_runs, text_runs_to_tagged_text\n",
        "from utils.latex_text import replace_text_runs, text_runs_to_tagged_text\n"
        "from utils.orgmesh_tokens import is_orgmesh_bridge_configured\n",
    )
    replace_once(
        backend / "services" / "chat" / "slide_ui_helpers.py",
        "    min_value = _int_or_none(min_length)\n"
        "    max_value = _int_or_none(max_length)\n",
        "    min_value = _int_or_none(min_length)\n"
        "    if min_value is not None and is_orgmesh_bridge_configured():\n"
        "        # Template density must not prevent concise user text edits.\n"
        "        min_value = min(min_value, 1)\n"
        "    max_value = _int_or_none(max_length)\n",
    )
    replace_once(
        backend / "utils" / "llm_config.py",
        "from utils.llm_provider import get_llm_provider\n",
        "from utils.llm_provider import get_llm_provider\n"
        "from api.v1.auth.context import get_current_owner_id\n"
        "from utils.orgmesh_tokens import (\n"
        "    is_orgmesh_bridge_configured,\n"
        "    issue_llm_relay_token,\n"
        ")\n",
    )
    replace_once(
        backend / "utils" / "llm_config.py",
        "            return OpenAIClientConfig(\n"
        "                base_url=base_url,\n"
        '                api_key=get_custom_llm_api_key_env() or "null",\n'
        "            )\n",
        '            api_key = get_custom_llm_api_key_env() or "null"\n'
        "            if is_orgmesh_bridge_configured():\n"
        "                owner_id = get_current_owner_id()\n"
        "                if owner_id is None:\n"
        "                    raise HTTPException(\n"
        '                        status_code=401, detail="Native owner is required"\n'
        "                    )\n"
        "                api_key = issue_llm_relay_token(owner_id)\n"
        "            return OpenAIClientConfig(\n"
        "                base_url=base_url,\n"
        "                api_key=api_key,\n"
        "            )\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "checkout",
        nargs="?",
        type=Path,
        default=REPOSITORY_DIRECTORY / ".orgmesh-local" / "presenton-src",
    )
    arguments = parser.parse_args()
    prepare_backend(arguments.checkout.resolve())
    print(f"Prepared Presenton backend at {arguments.checkout.resolve()}")


if __name__ == "__main__":
    main()
