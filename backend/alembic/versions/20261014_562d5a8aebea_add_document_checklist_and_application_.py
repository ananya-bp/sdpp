"""add document checklist and application details columns

Revision ID: 562d5a8aebea
Revises: 2d9f0673822c
Create Date: 2026-10-14

Additive-only migration for the document-based eligibility feature:
- applications.details_json (request-specific submission fields)
- uploaded_documents checklist category, validation/reviewer/version tracking columns
All columns are nullable or server-defaulted so existing rows upgrade without data loss.
`document_category` is persisted so a reviewer's classification survives across requests
(a non-persisted attribute would let later hint-based reassignment silently move an
already-verified document out of its checklist slot and break payment gating).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '562d5a8aebea'
down_revision: Union[str, Sequence[str], None] = '2d9f0673822c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_col(inspector, table, column):
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    # Idempotent guards: some databases received parts of this revision through an earlier
    # manual/hotfix application. Re-running `alembic upgrade head` must not fail on columns
    # that already exist (and must add any that are missing). Additive-only either way.
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if not _has_col(inspector, 'applications', 'details_json'):
        with op.batch_alter_table('applications') as batch_op:
            batch_op.add_column(sa.Column('details_json', sa.Text(), nullable=True))

    doc_cols = {c["name"] for c in inspector.get_columns('uploaded_documents')}
    new_cols = [
        ('document_category', sa.String(length=50), True, None),
        ('validation_status', sa.String(length=30), True, None),
        ('validation_reason', sa.Text(), True, None),
        ('reviewed_by', sa.Integer(), True, None),
        ('reviewed_at', sa.DateTime(timezone=True), True, None),
        ('verified_at', sa.DateTime(timezone=True), True, None),
        ('version', sa.Integer(), False, '1'),
        ('replaces_document_id', sa.Integer(), True, None),
    ]
    missing = [(n, t, nul, dflt) for (n, t, nul, dflt) in new_cols if n not in doc_cols]
    if missing:
        with op.batch_alter_table('uploaded_documents') as batch_op:
            for name, coltype, nullable, server_default in missing:
                batch_op.add_column(sa.Column(name, coltype, nullable=nullable,
                                              server_default=server_default))
    if 'reviewed_by' not in doc_cols:
        with op.batch_alter_table('uploaded_documents') as batch_op:
            batch_op.create_foreign_key(
                'fk_uploaded_documents_reviewed_by_users',
                'users', ['reviewed_by'], ['id'], ondelete='SET NULL',
            )
    if 'replaces_document_id' not in doc_cols:
        with op.batch_alter_table('uploaded_documents') as batch_op:
            batch_op.create_foreign_key(
                'fk_uploaded_documents_replaces_document_id_uploaded_documents',
                'uploaded_documents', ['replaces_document_id'], ['id'], ondelete='SET NULL',
            )
            batch_op.create_index(
                'ix_uploaded_documents_replaces_document_id', ['replaces_document_id'], unique=False,
            )
    if 'document_category' not in doc_cols:
        with op.batch_alter_table('uploaded_documents') as batch_op:
            batch_op.create_index(
                'ix_uploaded_documents_document_category', ['document_category'], unique=False,
            )


def downgrade() -> None:
    with op.batch_alter_table('uploaded_documents') as batch_op:
        batch_op.drop_index('ix_uploaded_documents_replaces_document_id')
        batch_op.drop_constraint('fk_uploaded_documents_replaces_document_id_uploaded_documents', type_='foreignkey')
        batch_op.drop_constraint('fk_uploaded_documents_reviewed_by_users', type_='foreignkey')
        batch_op.drop_column('replaces_document_id')
        batch_op.drop_column('document_category')
        batch_op.drop_column('version')
        batch_op.drop_column('verified_at')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('reviewed_by')
        batch_op.drop_column('validation_reason')
        batch_op.drop_column('validation_status')

    with op.batch_alter_table('applications') as batch_op:
        batch_op.drop_column('details_json')
