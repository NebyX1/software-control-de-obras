"""auditoría append-only: triggers que impiden UPDATE/DELETE sobre audit_event

Revision ID: a1b2c3d4e5f6
Revises: 6f552f0c3a2f
"""
from alembic import op

revision = 'a1b2c3d4e5f6'
down_revision = '6f552f0c3a2f'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TRIGGER audit_event_no_update BEFORE UPDATE ON audit_event FOR EACH ROW
                  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_event es append-only: UPDATE prohibido'""")
    op.execute("""CREATE TRIGGER audit_event_no_delete BEFORE DELETE ON audit_event FOR EACH ROW
                  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_event es append-only: DELETE prohibido'""")


def downgrade():
    op.execute('DROP TRIGGER IF EXISTS audit_event_no_update')
    op.execute('DROP TRIGGER IF EXISTS audit_event_no_delete')
