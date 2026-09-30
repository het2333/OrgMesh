from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.document_set import filter_document_set_ids_by_user_access
from onyx.db.enums import LLMModelFlowType, Permission
from onyx.db.llm import (
    can_user_access_llm_provider,
    fetch_model_configuration_by_id,
    fetch_user_group_ids,
)
from onyx.db.models import KVStore, Persona, StarterMessage, User
from onyx.db.persona import upsert_persona
from onyx.db.tools import get_tools
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.prompts.agents.templates import EVIDENCE_RULES, TEMPLATE_PROMPTS
from onyx.server.features.persona.models import (
    AgentTemplateInstallRequest,
    AgentTemplateSnapshot,
)
from onyx.tools.constants import SEARCH_TOOL_ID


def get_installed_agent_template(
    template_id: str, db_session: Session
) -> Persona | None:
    entry = db_session.get(KVStore, f"orgmesh.agent_template.{template_id}")
    if entry is None or not isinstance(entry.value, int):
        return None
    persona = db_session.get(Persona, entry.value)
    return persona if persona and not persona.deleted else None


def get_agent_template_tool_ids(
    db_session: Session, document_search_available: bool
) -> list[int]:
    from onyx.tools.built_in_tools import get_built_in_tool_by_id

    tool_names = {"FileReaderTool"}
    if document_search_available:
        tool_names.add("SearchTool")
    return [
        tool.id
        for tool in get_tools(db_session, only_enabled=True)
        if tool.in_code_tool_id in tool_names
        and get_built_in_tool_by_id(tool.in_code_tool_id).is_available(db_session)
    ]


def get_required_agent_template_search_tool_id(
    persona: Persona, db_session: Session
) -> int | None:
    """Require evidence for unchanged templates with attached search knowledge."""
    if not (
        persona.document_sets or persona.hierarchy_nodes or persona.attached_documents
    ):
        return None
    if persona.task_prompt not in (None, "", EVIDENCE_RULES):
        return None
    template_id = next(
        (
            key
            for key, prompt in TEMPLATE_PROMPTS.items()
            if persona.system_prompt == prompt
        ),
        None,
    )
    if template_id is None:
        return None
    entry = db_session.get(KVStore, f"orgmesh.agent_template.{template_id}")
    if entry is None or entry.value != persona.id:
        return None
    search_tool = next(
        (tool for tool in persona.tools if tool.in_code_tool_id == SEARCH_TOOL_ID),
        None,
    )
    if search_tool is None or not search_tool.enabled:
        raise OnyxError(
            OnyxErrorCode.BAD_REQUEST,
            "请启用知识搜索，以便根据内部资料回答并引用依据。",
        )
    return search_tool.id


def install_agent_template(
    template: AgentTemplateSnapshot,
    request: AgentTemplateInstallRequest,
    user: User,
    db_session: Session,
    document_search_available: bool,
) -> Persona:
    """Save the native agent and its template ID in one locked transaction."""
    key = f"orgmesh.agent_template.{template.id}"
    db_session.execute(
        insert(KVStore).values(key=key, value=None).on_conflict_do_nothing()
    )
    entry = db_session.scalars(
        select(KVStore).where(KVStore.key == key).with_for_update()
    ).one()
    installed = get_installed_agent_template(template.id, db_session)
    if installed:
        return installed

    if request.document_set_ids and not document_search_available:
        raise OnyxError(
            OnyxErrorCode.BAD_REQUEST,
            "Document search is unavailable in this deployment.",
        )
    accessible_sets = filter_document_set_ids_by_user_access(
        db_session, request.document_set_ids, user
    )
    if accessible_sets != set(request.document_set_ids):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "One or more document sets are not accessible.",
        )
    tool_ids = get_agent_template_tool_ids(db_session, document_search_available)
    try:
        persona = upsert_persona(
            user=user,
            name=template.name,
            description=template.description,
            starter_messages=[
                StarterMessage(name=template.name, message=template.starter_message)
            ],
            system_prompt=TEMPLATE_PROMPTS[template.id],
            replace_base_system_prompt=True,
            task_prompt=EVIDENCE_RULES,
            datetime_aware=True,
            is_public=True,
            db_session=db_session,
            document_set_ids=request.document_set_ids,
            tool_ids=tool_ids,
            commit=False,
        )
    except ValueError as error:
        raise OnyxError(OnyxErrorCode.BAD_REQUEST, str(error)) from error
    if request.default_model_configuration_id is not None:
        config = fetch_model_configuration_by_id(
            db_session, request.default_model_configuration_id
        )
        if (
            config is None
            or not config.is_visible
            or LLMModelFlowType.CHAT not in config.llm_model_flow_types
        ):
            raise OnyxError(
                OnyxErrorCode.BAD_REQUEST, "Select an available chat model."
            )
        if not can_user_access_llm_provider(
            config.llm_provider,
            fetch_user_group_ids(db_session, user),
            persona,
            can_manage_llms=has_global_permission(user, Permission.MANAGE_LLMS),
        ):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "This model is not accessible for this agent.",
            )
        persona.default_model_configuration_id = config.id
    entry.value = persona.id
    db_session.commit()
    return persona
