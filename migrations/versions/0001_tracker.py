"""Initial additive private tracker schema; legacy daily_flags is untouched."""
from alembic import op
from sqlalchemy import text
from scanner_tracker.db import Base
from scanner_tracker import models

revision = "0001_tracker"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql":
        for table in Base.metadata.sorted_tables:
            op.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
            for role in ("anon", "authenticated"):
                exists = bind.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar()
                if exists:
                    op.execute(text(f'REVOKE ALL ON TABLE "{table.name}" FROM "{role}"'))


def downgrade():
    raise RuntimeError("Automatic destructive downgrade is disabled. Export records before a reviewed recovery.")
