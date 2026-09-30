"""Read-only checks for the local OrgMesh workspace."""

import json
import unittest
import urllib.error
import urllib.request


class WorkspaceChecks(unittest.TestCase):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = "http://localhost:3090"

    def test_workspace_opens_without_login(self) -> None:
        with self.opener.open(f"{self.base_url}/api/me", timeout=20) as response:
            user = json.load(response)
        self.assertTrue(user["is_active"])
        self.assertTrue(user["admin_capabilities"])

    def test_settings_remain_accessible(self) -> None:
        with self.opener.open(
            f"{self.base_url}/api/admin/llm/provider", timeout=20
        ) as response:
            self.assertEqual(response.status, 200)

    def test_login_routes_return_to_workspace(self) -> None:
        for path in ("/auth/login", "/auth/signup"):
            with self.subTest(path=path):
                with self.opener.open(f"{self.base_url}{path}", timeout=30) as response:
                    self.assertTrue(response.url.startswith(self.base_url + "/"))
                    self.assertIn("/app", response.url)
                    self.assertNotIn("/auth/", response.url)

    def test_search_route_is_available(self) -> None:
        with self.opener.open(f"{self.base_url}/app/search", timeout=30) as response:
            self.assertEqual(response.status, 200)
            self.assertNotIn("/auth/", response.url)

    def test_management_pages_open_without_cookies(self) -> None:
        for path in ("/admin/language-models", "/admin/indexing/status"):
            with self.subTest(path=path):
                with self.opener.open(f"{self.base_url}{path}", timeout=45) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(path, response.url)

    def test_foreign_origins_and_hosts_are_rejected(self) -> None:
        for headers in ({"Origin": "https://example.org"}, {"Host": "rebind.example"}):
            with self.subTest(headers=headers):
                request = urllib.request.Request(f"{self.base_url}/api/me", headers=headers)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.opener.open(request, timeout=15)
                self.assertEqual(error.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
