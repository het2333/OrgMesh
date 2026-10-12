# SPDX-License-Identifier: MIT
"""One bounded usage revision per scheduled invocation. No automatic retries."""

from celery import shared_task

from onyx.configs.constants import OnyxCeleryQueues, OnyxCeleryTask
from onyx.orgmesh_enterprise.config import EnterpriseConfig
from onyx.orgmesh_enterprise.snapshot import publish_usage_snapshot
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.PRODUCE_ORGMESH_USAGE_SNAPSHOT,
    queue=OnyxCeleryQueues.PRIMARY,
    ignore_result=True,
)
def produce_usage_snapshot(*, tenant_id: str) -> None:
    try:
        publish_usage_snapshot(tenant_id=tenant_id, config=EnterpriseConfig.from_env())
    except Exception:
        # Never include source rows, identities, costs, or transport content.
        logger.error(
            "OrgMesh usage snapshot failed; the next scheduled revision will reread the source"
        )
