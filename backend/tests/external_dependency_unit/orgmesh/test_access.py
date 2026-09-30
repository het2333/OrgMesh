"""Source access checks against PostgreSQL. Every test rolls back its own rows."""

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.access.access import filter_authorized_document_ids, get_acl_for_user
from onyx.access.models import ExternalAccess
from onyx.access.utils import prefix_user_email
from onyx.db.engine.sql_engine import SqlEngine, get_sqlalchemy_engine
from onyx.db.models import Document, OrgMeshDirectoryUser, User
from onyx.db.orgmesh import refresh_source_document_access, replace_directory_snapshot
from onyx.kg.models import KGStage


class SourceAccessChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SqlEngine.init_engine(pool_size=1, max_overflow=0)

    def setUp(self) -> None:
        self.connection = get_sqlalchemy_engine().connect()
        self.transaction = self.connection.begin()
        self.session = Session(
            bind=self.connection, join_transaction_mode="create_savepoint"
        )
        self.now = datetime.now(timezone.utc)
        self.alice = User(
            id=uuid4(),
            email=f"alice-{uuid4().hex}@example.com",
            hashed_password="unused-test-value",
            is_active=True,
            is_verified=True,
            prior_emails=[],
        )
        self.bob = User(
            id=uuid4(),
            email=f"bob-{uuid4().hex}@example.com",
            hashed_password="unused-test-value",
            is_active=True,
            is_verified=True,
            prior_emails=[],
        )
        self.session.add_all([self.alice, self.bob])
        self.session.flush()
        self.membership = OrgMeshDirectoryUser(
            email=self.alice.email,
            employee_id=uuid4().hex,
            department_ids=["engineering"],
            active=True,
            expires_at=self.now + timedelta(minutes=15),
            updated_at=self.now,
        )
        self.document = Document(
            id=f"feishu:docx:{uuid4().hex}",
            semantic_id="Synthetic private policy",
            kg_stage=KGStage.NOT_STARTED,
            is_public=True,
            external_user_emails=[self.alice.email],
            external_user_group_ids=[],
            doc_metadata={"orgmesh_acl_checked_at": self.now.timestamp()},
        )
        self.session.add_all([self.membership, self.document])
        self.session.flush()

    def tearDown(self) -> None:
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def allowed(self, user: User) -> set[str]:
        return filter_authorized_document_ids([self.document.id], user, self.session)

    def test_source_email_overrides_public_connector_sharing(self) -> None:
        self.assertEqual(self.allowed(self.alice), {self.document.id})
        self.assertEqual(self.allowed(self.bob), set())

    def test_fresh_department_membership_is_scoped(self) -> None:
        self.document.external_user_emails = []
        self.document.external_user_group_ids = ["feishu:department:engineering"]
        self.session.flush()
        self.assertEqual(self.allowed(self.alice), {self.document.id})
        self.assertEqual(self.allowed(self.bob), set())

    def test_missing_directory_membership_denies_direct_email_grant(self) -> None:
        self.session.delete(self.membership)
        self.session.flush()
        self.assertEqual(self.allowed(self.alice), set())

    def test_expired_directory_preserves_native_upload_identity(self) -> None:
        self.membership.expires_at = self.now - timedelta(seconds=1)
        self.session.flush()
        self.assertIn(
            prefix_user_email(self.alice.email),
            get_acl_for_user(self.alice, self.session),
        )
        self.assertEqual(self.allowed(self.alice), set())

    def test_stale_source_permissions_deny_even_direct_grant(self) -> None:
        self.document.doc_metadata = {
            "orgmesh_acl_checked_at": (self.now - timedelta(minutes=16)).timestamp()
        }
        self.session.flush()
        self.assertEqual(self.allowed(self.alice), set())

    def test_revocation_is_visible_before_index_sync(self) -> None:
        self.assertEqual(self.allowed(self.alice), {self.document.id})
        refresh_source_document_access(
            self.session,
            {
                self.document.id: (ExternalAccess.empty(), self.now.timestamp() + 1),
            },
        )
        self.assertEqual(self.allowed(self.alice), set())

    def test_queued_permissions_do_not_extend_source_lifetime(self) -> None:
        old_time = (self.now - timedelta(minutes=16)).timestamp()
        self.document.doc_metadata = {}
        self.session.flush()
        refresh_source_document_access(
            self.session,
            {
                self.document.id: (
                    ExternalAccess({self.alice.email}, set(), False),
                    old_time,
                ),
            },
        )
        self.assertEqual(self.document.doc_metadata["orgmesh_acl_checked_at"], old_time)
        self.assertEqual(self.allowed(self.alice), set())

    def test_older_batch_cannot_replace_newer_revocation(self) -> None:
        self.document.external_user_emails = []
        self.session.flush()
        resolved = refresh_source_document_access(
            self.session,
            {
                self.document.id: (
                    ExternalAccess({self.alice.email}, set(), False),
                    self.now.timestamp() - 1,
                ),
            },
        )
        self.assertEqual(resolved[self.document.id][0], ExternalAccess.empty())
        self.assertEqual(self.allowed(self.alice), set())

    def test_directory_snapshot_removes_departments_and_deactivates_departures(
        self,
    ) -> None:
        replace_directory_snapshot(
            self.session,
            [(self.alice.email, self.membership.employee_id, ["sales"], False)],
        )
        self.session.refresh(self.alice)
        self.assertFalse(self.alice.is_active)
        self.assertEqual(self.allowed(self.alice), set())

    def test_native_user_file_ids_remain_in_native_policy(self) -> None:
        document_id = f"user-file-{uuid4()}"
        self.assertEqual(
            filter_authorized_document_ids([document_id], self.alice, self.session),
            {document_id},
        )


if __name__ == "__main__":
    unittest.main()
