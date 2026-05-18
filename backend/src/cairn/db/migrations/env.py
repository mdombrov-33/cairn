import asyncio
from logging.config import fileConfig
from typing import Literal

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.sql.schema import SchemaItem

import cairn.db.models  # noqa: F401  registers ORM models with Base.metadata
from cairn.config import get_settings
from cairn.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata

_IGNORED_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
}


def include_object(
    obj: SchemaItem,
    name: str | None,
    type_: Literal["schema", "table", "column", "index", "unique_constraint", "foreign_key_constraint"],
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    return not (type_ == "table" and name in _IGNORED_TABLES)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
