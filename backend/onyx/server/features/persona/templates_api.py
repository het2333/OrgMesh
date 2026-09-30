from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.db.agent_templates import (
    get_agent_template_tool_ids,
    get_installed_agent_template,
    install_agent_template,
)
from onyx.db.document_set import filter_document_set_ids_by_user_access
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.persona import user_can_access_persona
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.persona.api import update_persona
from onyx.server.features.persona.models import (
    AgentTemplateCatalog,
    AgentTemplateConfigureRequest,
    AgentTemplateInstallRequest,
    AgentTemplateSnapshot,
    MinimalPersonaSnapshot,
    PersonaSnapshot,
    PersonaUpsertRequest,
)
from onyx.server.manage.llm.api import get_valid_model_configuration_ids_for_persona

router = APIRouter(prefix="/agent-templates")

TEMPLATES = [
    AgentTemplateSnapshot(
        id="policy",
        name="制度问答",
        description="根据内部制度回答问题，并引用真实资料。",
        starter_message="请根据公司制度说明请假流程，并引用依据。",
    ),
    AgentTemplateSnapshot(
        id="onboarding",
        name="员工入职",
        description="根据岗位和入职资料整理任务清单。",
        starter_message="我刚加入公司，请先了解我的岗位，再整理入职清单。",
    ),
    AgentTemplateSnapshot(
        id="weekly-report",
        name="项目周报",
        description="根据项目资料整理进展、风险和下周计划。",
        starter_message="请先确认项目和报告周期，再根据资料起草周报。",
    ),
]


@router.get("")
def list_agent_templates(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> AgentTemplateCatalog:
    templates = []
    for template in TEMPLATES:
        persona = get_installed_agent_template(template.id, db_session)
        if persona and not user_can_access_persona(db_session, persona.id, user):
            persona = None
        templates.append(
            template.model_copy(update={"persona_id": persona.id if persona else None})
        )
    return AgentTemplateCatalog(
        templates=templates,
        document_search_available=not DISABLE_VECTOR_DB,
        search_tool_available=not DISABLE_VECTOR_DB
        and bool(get_agent_template_tool_ids(db_session, True)),
        can_install=has_global_permission(user, Permission.MANAGE_AGENTS),
    )


@router.post("/{template_id}/install")
def install_workspace_agent_template(
    template_id: str,
    request: AgentTemplateInstallRequest,
    user: User = Depends(require_permission(Permission.MANAGE_AGENTS)),
    db_session: Session = Depends(get_session),
) -> MinimalPersonaSnapshot:
    template = next((item for item in TEMPLATES if item.id == template_id), None)
    if template is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Agent template not found.")
    persona = install_agent_template(
        template, request, user, db_session, not DISABLE_VECTOR_DB
    )
    return MinimalPersonaSnapshot.from_model(persona)


@router.patch("/{template_id}/configuration")
def configure_workspace_agent_template(
    template_id: str,
    request: AgentTemplateConfigureRequest,
    user: User = Depends(require_permission(Permission.MANAGE_AGENTS)),
    db_session: Session = Depends(get_session),
) -> PersonaSnapshot:
    persona = get_installed_agent_template(template_id, db_session)
    if persona is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND, "Install the template before configuring it."
        )
    if request.document_set_ids is not None:
        accessible = filter_document_set_ids_by_user_access(
            db_session, request.document_set_ids, user
        )
        if accessible != set(request.document_set_ids):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "One or more document sets are not accessible.",
            )
    model_id = persona.default_model_configuration_id
    if "default_model_configuration_id" in request.model_fields_set:
        model_id = request.default_model_configuration_id
        if (
            model_id is not None
            and model_id
            not in get_valid_model_configuration_ids_for_persona(
                persona, user, db_session
            )
        ):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "Select an available model for this agent.",
            )
    return update_persona(
        persona.id,
        PersonaUpsertRequest(
            name=persona.name,
            description=persona.description,
            document_set_ids=request.document_set_ids
            if request.document_set_ids is not None
            else [item.id for item in persona.document_sets],
            default_model_configuration_id=model_id,
            tool_ids=sorted(
                {tool.id for tool in persona.tools}
                | set(
                    get_agent_template_tool_ids(db_session, not DISABLE_VECTOR_DB)
                    if request.document_set_ids is not None
                    else []
                )
            ),
            starter_messages=persona.starter_messages,
            system_prompt=persona.system_prompt or "",
            task_prompt=persona.task_prompt or "",
            datetime_aware=persona.datetime_aware,
            replace_base_system_prompt=persona.replace_base_system_prompt,
            icon_name=persona.icon_name,
            search_start_date=persona.search_start_date,
        ),
        user=user,
        db_session=db_session,
    )
