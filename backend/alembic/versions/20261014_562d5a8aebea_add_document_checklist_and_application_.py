"""add document checklist and application details columns

Revision ID: 562d5a8aebea
Revises: 2d9f0673822c
Create Date: 2026-10-14

Additive-only migration for the document-based eligibility feature:
- applications.details_json (request-specific submission fields)
- uploaded_documents validation/reviewer/version tracking columns
All columns are nullable or server-defaulted so existing rows upgrade without data loss.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '562d5a8aebea'
down_revision: Union[str, Sequence[str], None] = '2d9f0673822c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('applications') as batch_op:
        batch_op.add_column(sa.Column('details_json', sa.Text(), nullable=True))

    with op.batch_alter_table('uploaded_documents') as batch_op:
        batch_op.add_column(sa.Column('validation_status', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('validation_reason', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('replaces_document_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_uploaded_documents_reviewed_by_users',
            'users', ['reviewed_by'], ['id'], ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            'fk_uploaded_documents_replaces_document_id_uploaded_documents',
            'uploaded_documents', ['replaces_document_id'], ['id'], ondelete='SET NULL',
        )
        batch_op.create_index(
            'ix_uploaded_documents_replaces_document_id', ['replaces_document_id'], unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('uploaded_documents') as batch_op:
        batch_op.drop_index('ix_uploaded_documents_replaces_document_id')
        batch_op.drop_constraint('fk_uploaded_documents_replaces_document_id_uploaded_documents', type_='foreignkey')
        batch_op.drop_constraint('fk_uploaded_documents_reviewed_by_users', type_='foreignkey')
        batch_op.drop_column('replaces_document_id')
        batch_op.drop_column('version')
        batch_op.drop_column('verified_at')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('reviewed_by')
        batch_op.drop_column('validation_reason')
        batch_op.drop_column('validation_status')

    with op.batch_alter_table('applications') as batch_op:
        batch_op.drop_column('details_json')
