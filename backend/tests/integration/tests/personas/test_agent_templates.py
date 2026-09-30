from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser


def test_templates_persist_native_agents_and_keep_edits_on_repeat_install(
    admin_user: DATestUser,
) -> None:
    catalog = client.get(
        f"{API_SERVER_URL}/agent-templates", headers=admin_user.headers
    )
    catalog.raise_for_status()
    templates = catalog.json()["templates"]
    assert {item["id"] for item in templates} == {
        "policy",
        "onboarding",
        "weekly-report",
    }
    for template in templates:
        install_url = f"{API_SERVER_URL}/agent-templates/{template['id']}/install"
        first = client.post(install_url, json={}, headers=admin_user.headers)
        first.raise_for_status()
        persona_id = first.json()["id"]
        second = client.post(install_url, json={}, headers=admin_user.headers)
        second.raise_for_status()
        assert second.json()["id"] == persona_id

        native = client.get(
            f"{API_SERVER_URL}/persona/{persona_id}", headers=admin_user.headers
        )
        native.raise_for_status()
        agent = native.json()
        assert agent["name"] == template["name"]
        assert not agent["builtin_persona"]
        assert "引用" in agent["system_prompt"]
        original_prompt = agent["system_prompt"]
        edited_prompt = original_prompt + "\n先说明引用资料的日期。"
        edited = client.patch(
            f"{API_SERVER_URL}/persona/{persona_id}",
            json={
                "name": agent["name"],
                "description": agent["description"],
                "document_set_ids": [item["id"] for item in agent["document_sets"]],
                "tool_ids": [item["id"] for item in agent["tools"]],
                "system_prompt": edited_prompt,
                "task_prompt": agent["task_prompt"],
                "datetime_aware": agent["datetime_aware"],
            },
            headers=admin_user.headers,
        )
        edited.raise_for_status()
        repeat = client.post(install_url, json={}, headers=admin_user.headers)
        repeat.raise_for_status()
        assert repeat.json()["id"] == persona_id

        configure = client.patch(
            f"{API_SERVER_URL}/agent-templates/{template['id']}/configuration",
            json={"default_model_configuration_id": None},
            headers=admin_user.headers,
        )
        configure.raise_for_status()
        reloaded = client.get(
            f"{API_SERVER_URL}/persona/{persona_id}", headers=admin_user.headers
        )
        reloaded.raise_for_status()
        assert reloaded.json()["default_model_configuration_id"] is None
        assert reloaded.json()["system_prompt"] == edited_prompt

        listed = client.get(f"{API_SERVER_URL}/persona", headers=admin_user.headers)
        listed.raise_for_status()
        assert any(item["id"] == persona_id for item in listed.json())


def test_workspace_template_install_requires_agent_management(
    basic_user: DATestUser,
) -> None:
    response = client.post(
        f"{API_SERVER_URL}/agent-templates/policy/install",
        json={},
        headers=basic_user.headers,
    )
    assert response.status_code == 403
