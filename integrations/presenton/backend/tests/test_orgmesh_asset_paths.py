"""Verify proxy-prefixed asset paths in the pinned Presenton runtime."""

import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from api.v1.auth.context import (
    reset_current_owner_id,
    reset_current_owner_is_admin,
    set_current_owner_id,
    set_current_owner_is_admin,
)
from utils.asset_directory_utils import resolve_app_path_to_filesystem


class AssetPathTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.app_data = Path(directory.name) / "app_data"
        self.static_root = Path(directory.name) / "static"
        self.owner_id = uuid.uuid4()
        self.other_id = uuid.uuid4()
        self.own_file = (
            self.app_data / "images" / "users" / str(self.owner_id) / "own.png"
        )
        self.other_file = (
            self.app_data / "images" / "users" / str(self.other_id) / "secret.png"
        )
        self.static_file = self.static_root / "icons" / "shared.svg"
        for asset in (self.own_file, self.other_file, self.static_file):
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_bytes(b"asset")
        environment = patch.dict(
            os.environ,
            {"APP_DATA_DIRECTORY": str(self.app_data), "DISABLE_AUTH": "false"},
        )
        environment.start()
        self.addCleanup(environment.stop)
        static_path = patch(
            "utils.asset_directory_utils.get_resource_path",
            return_value=str(self.static_root),
        )
        static_path.start()
        self.addCleanup(static_path.stop)
        owner_token = set_current_owner_id(self.owner_id)
        self.addCleanup(reset_current_owner_id, owner_token)
        admin_token = set_current_owner_is_admin(False)
        self.addCleanup(reset_current_owner_is_admin, admin_token)

    def test_prefixed_owner_asset_resolves_from_path_and_absolute_url(self) -> None:
        asset_path = f"/app_data/images/users/{self.owner_id}/own.png"
        for value in (
            asset_path,
            f"/presenton{asset_path}",
            f"https://orgmesh.example/presenton{asset_path}?size=1",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    resolve_app_path_to_filesystem(value), str(self.own_file.resolve())
                )

    def test_prefixed_other_owner_and_traversal_are_denied(self) -> None:
        for value in (
            f"/presenton/app_data/images/users/{self.other_id}/secret.png",
            "/presenton/app_data/images/users/"
            f"{self.owner_id}/../../{self.other_id}/secret.png",
            "/presenton/app_data/images/users/"
            f"{self.owner_id}/%252e%252e/%252e%252e/{self.other_id}/secret.png",
        ):
            with self.subTest(value=value):
                self.assertIsNone(resolve_app_path_to_filesystem(value))

    def test_prefixed_static_asset_resolves_and_cannot_escape_root(self) -> None:
        self.assertEqual(
            resolve_app_path_to_filesystem("/presenton/static/icons/shared.svg"),
            str(self.static_file.resolve()),
        )
        self.assertIsNone(
            resolve_app_path_to_filesystem(
                f"/presenton/static/../app_data/images/users/{self.other_id}/secret.png"
            )
        )

    def test_prefixed_packaged_font_resolves(self) -> None:
        font_path = "/vendor/fonts/sans_serif/poppins/Poppins-Regular.ttf"
        original = resolve_app_path_to_filesystem(font_path)
        self.assertIsNotNone(original)
        self.assertEqual(
            resolve_app_path_to_filesystem(f"/presenton{font_path}"), original
        )


if __name__ == "__main__":
    unittest.main()
