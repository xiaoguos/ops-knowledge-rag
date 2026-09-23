"""Persist parse reports and human review without changing original files."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("document_versions", sa.Column("processing", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("chunks", sa.Column("parent_text", sa.Text(), nullable=False, server_default=""))


def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup.")
