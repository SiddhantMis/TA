from alembic import context
from scanner_tracker.db import Base, make_engine
from scanner_tracker import models  # register application tables
import os

config = context.config
url = config.attributes.get("database_url") or os.environ.get("DATABASE_URL")
if not url:
    raise RuntimeError("DATABASE_URL is required for migrations.")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
