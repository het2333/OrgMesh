import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.server.documents.models import ConnectorBase, ConnectorUpdateRequest


def schedule(refresh: int | None = None, prune: int | None = None) -> ConnectorBase:
    return ConnectorBase(
        name="Feishu",
        source=DocumentSource.FEISHU,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=refresh,
        prune_freq=prune,
    )


def test_feishu_schedule_defaults_to_five_minutes() -> None:
    connector = schedule()
    assert connector.refresh_freq == 300
    assert connector.prune_freq == 300


@pytest.mark.parametrize("refresh", [60, 120, 300])
@pytest.mark.parametrize("prune", [1, 60, 300])
def test_feishu_schedule_accepts_bounded_values(refresh: int, prune: int) -> None:
    connector = schedule(refresh, prune)
    assert connector.refresh_freq == refresh
    assert connector.prune_freq == prune


@pytest.mark.parametrize("refresh", [-1, 0, 59, 301, 86400])
def test_feishu_schedule_rejects_disabled_or_stale_refresh(refresh: int) -> None:
    with pytest.raises(ValidationError, match="refresh frequency"):
        schedule(refresh, 300)


@pytest.mark.parametrize("prune", [-1, 0, 301, 86400])
def test_feishu_schedule_rejects_disabled_or_stale_pruning(prune: int) -> None:
    with pytest.raises(ValidationError, match="prune frequency"):
        schedule(300, prune)


def test_feishu_update_uses_the_same_schedule_guard() -> None:
    update = ConnectorUpdateRequest(
        name="Feishu",
        source=DocumentSource.FEISHU,
        input_type=InputType.POLL,
        connector_specific_config={},
        access_type=AccessType.PUBLIC,
    )
    connector = update.to_connector_base()
    assert connector.refresh_freq == 300
    assert connector.prune_freq == 300
    with pytest.raises(ValidationError, match="prune frequency"):
        ConnectorUpdateRequest.model_validate(
            {**update.model_dump(), "prune_freq": 3600}
        )


def test_other_sources_keep_their_existing_schedule_contract() -> None:
    connector = ConnectorBase(
        name="Google Drive",
        source=DocumentSource.GOOGLE_DRIVE,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=86400,
        prune_freq=None,
    )
    assert connector.refresh_freq == 86400
    assert connector.prune_freq is None
