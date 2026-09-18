"""Allow user-authored lyric overrides."""
from alembic import op

revision = "0041_manual_lyrics_overrides"
down_revision = "0040_lyrics_transcription"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE lyrics DROP CONSTRAINT IF EXISTS lyrics_source_check")
    op.execute("""ALTER TABLE lyrics ADD CONSTRAINT lyrics_source_check
                  CHECK (source IN ('embedded', 'local-file', 'transcribed', 'manual', 'none'))""")


def downgrade():
    op.execute("ALTER TABLE lyrics DROP CONSTRAINT IF EXISTS lyrics_source_check")
    op.execute("""ALTER TABLE lyrics ADD CONSTRAINT lyrics_source_check
                  CHECK (source IN ('embedded', 'local-file', 'transcribed', 'none'))""")
