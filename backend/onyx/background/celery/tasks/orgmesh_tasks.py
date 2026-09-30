from celery import shared_task

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.redis.redis_pool import get_redis_client
from onyx.server.orgmesh import load_directory_config, synchronize_directory
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(name="orgmesh-sync-directory", ignore_result=True)
def sync_employee_directory(*, tenant_id: str) -> None:
    if not load_directory_config().enabled:
        return
    lock = get_redis_client(tenant_id=tenant_id).lock(
        "orgmesh:directory-sync", timeout=600
    )
    if not lock.acquire(blocking=False):
        return
    try:
        with get_session_with_current_tenant() as session:
            count = synchronize_directory(session)
            logger.info("OrgMesh directory synchronized %s employees", count)
    except Exception:
        # No raw upstream response or credentials enter worker logs.
        logger.error(
            "OrgMesh directory sync failed; memberships expire after 15 minutes"
        )
    finally:
        if lock.owned():
            lock.release()
