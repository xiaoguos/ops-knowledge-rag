"""Initial immutable PostgreSQL schema. Generated 2026-09-16."""
from alembic import op
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None
STATEMENTS = [
  "CREATE EXTENSION IF NOT EXISTS vector",
  "CREATE TABLE audit_events (\n\tid VARCHAR(32) NOT NULL, \n\ttenant VARCHAR(80) NOT NULL, \n\tuser_id VARCHAR(32) NOT NULL, \n\taction VARCHAR(80) NOT NULL, \n\tresource_id VARCHAR(100) NOT NULL, \n\tdetail JSON NOT NULL, \n\tat TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)",
  "CREATE INDEX ix_audit_events_at ON audit_events (at)",
  "CREATE INDEX ix_audit_events_tenant ON audit_events (tenant)",
  "CREATE TABLE conversations (\n\tid VARCHAR(32) NOT NULL, \n\ttenant VARCHAR(80) NOT NULL, \n\towner_id VARCHAR(32) NOT NULL, \n\ttitle VARCHAR(120) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)",
  "CREATE INDEX ix_conversations_owner_id ON conversations (owner_id)",
  "CREATE INDEX ix_conversations_tenant ON conversations (tenant)",
  "CREATE TABLE documents (\n\tid VARCHAR(32) NOT NULL, \n\ttenant VARCHAR(80) NOT NULL, \n\towner_id VARCHAR(32) NOT NULL, \n\tactive_version VARCHAR(32), \n\trevision INTEGER NOT NULL, \n\tdeleted BOOLEAN NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)",
  "CREATE INDEX ix_documents_tenant ON documents (tenant)",
  "CREATE TABLE jobs (\n\tid VARCHAR(32) NOT NULL, \n\ttenant VARCHAR(80) NOT NULL, \n\towner_id VARCHAR(32) NOT NULL, \n\tkind VARCHAR(40) NOT NULL, \n\tpayload JSON NOT NULL, \n\tstate VARCHAR(20) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tlease_token VARCHAR(32), \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\terror TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)",
  "CREATE INDEX ix_jobs_owner_id ON jobs (owner_id)",
  "CREATE INDEX ix_jobs_state ON jobs (state)",
  "CREATE INDEX ix_jobs_tenant ON jobs (tenant)",
  "CREATE TABLE login_attempts (\n\tid VARCHAR(32) NOT NULL, \n\tidentity VARCHAR(64) NOT NULL, \n\tat TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)",
  "CREATE INDEX ix_login_attempts_at ON login_attempts (at)",
  "CREATE INDEX ix_login_attempts_identity ON login_attempts (identity)",
  "CREATE TABLE login_sessions (\n\ttoken_hash VARCHAR(64) NOT NULL, \n\tuser_id VARCHAR(32) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (token_hash)\n)",
  "CREATE INDEX ix_login_sessions_expires_at ON login_sessions (expires_at)",
  "CREATE INDEX ix_login_sessions_user_id ON login_sessions (user_id)",
  "CREATE TABLE users (\n\tid VARCHAR(32) NOT NULL, \n\ttenant VARCHAR(80) NOT NULL, \n\temail VARCHAR(254) NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tpassword_hash TEXT NOT NULL, \n\trole VARCHAR(20) NOT NULL, \n\tdepartments JSON NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (email)\n)",
  "CREATE INDEX ix_users_tenant ON users (tenant)",
  "CREATE TABLE worker_heartbeats (\n\tid VARCHAR(32) NOT NULL, \n\tat TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)",
  "CREATE TABLE document_versions (\n\tid VARCHAR(32) NOT NULL, \n\tdocument_id VARCHAR(32) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tfilename VARCHAR(255) NOT NULL, \n\tdepartment VARCHAR(80) NOT NULL, \n\tversion VARCHAR(80) NOT NULL, \n\tdigest VARCHAR(64) NOT NULL, \n\tpayload BYTEA NOT NULL, \n\tstate VARCHAR(20) NOT NULL, \n\tembedding_model VARCHAR(120) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (document_id, revision), \n\tFOREIGN KEY(document_id) REFERENCES documents (id)\n)",
  "CREATE INDEX ix_document_versions_department ON document_versions (department)",
  "CREATE INDEX ix_document_versions_document_id ON document_versions (document_id)",
  "CREATE TABLE messages (\n\tid VARCHAR(32) NOT NULL, \n\tconversation_id VARCHAR(32) NOT NULL, \n\tquestion TEXT NOT NULL, \n\tresponse JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(conversation_id) REFERENCES conversations (id)\n)",
  "CREATE INDEX ix_messages_conversation_id ON messages (conversation_id)",
  "CREATE TABLE chunks (\n\tid VARCHAR(32) NOT NULL, \n\tversion_id VARCHAR(32) NOT NULL, \n\theading TEXT NOT NULL, \n\ttext TEXT NOT NULL, \n\tpage INTEGER, \n\tembedding VECTOR(512) NOT NULL, \n\tlexical TSVECTOR, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(version_id) REFERENCES document_versions (id)\n)",
  "CREATE INDEX ix_chunks_version_id ON chunks (version_id)",
  "CREATE INDEX ix_chunks_lexical ON chunks USING gin (lexical)"
]
TABLES = ["chunks","messages","document_versions","worker_heartbeats","users","login_sessions","login_attempts","jobs","documents","conversations","audit_events"]
def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)
def downgrade():
    raise RuntimeError("Destructive downgrade is disabled. Restore a verified backup into a new database.")
