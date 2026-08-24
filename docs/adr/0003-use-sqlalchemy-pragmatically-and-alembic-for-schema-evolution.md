# ADR 0003: Use SQLAlchemy pragmatically and Alembic for schema evolution

## Status

Accepted

## Context

The analysis service accumulated handwritten psycopg queries in route handlers. This made ordinary entity lifecycle work repetitive and left schema upgrades dependent on PostgreSQL initialization scripts, which do not run for an existing database volume. Echora also has PostgreSQL-specific analytical work involving pgvector, `DISTINCT ON`, lateral joins, bulk reconciliation, and corpus extraction. Translating those queries into ORM relationship traversal would hide their execution shape without making them safer.

## Decision

Use SQLAlchemy 2 mapped models and transactional sessions for ordinary application entities, authentication, preferences, connections, and curation lifecycle operations.

Use SQLAlchemy Core or reviewed explicit SQL for vector operations, corpus CTEs, set-based synchronization, search, aggregates, and other queries where PostgreSQL execution details matter.

Use Alembic for schema creation and every later schema change. The analysis service runs `alembic upgrade head` before starting the API. Revision `0001_existing_schema` is the consolidated v1 baseline from SQL migrations `001` through `011`.

## Consequences

Application CRUD gains one transaction boundary and mapped relationships. Complex analytical SQL remains visible and can be checked with `EXPLAIN`.

The service now depends on SQLAlchemy and Alembic. Model mappings and migrations must be reviewed together. A new empty PostgreSQL database is initialized automatically from the v1 baseline. Existing databases already stamped past revision `0001_existing_schema` are unchanged.
