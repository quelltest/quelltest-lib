"""
Security model, ephemeral credential constants, and import-to-infra tag registry.

DESIGN RULE: quelltest NEVER reads, prompts for, or touches production credentials.
All containers start with EPHEMERAL_CREDS — hardcoded, throwaway, non-configurable.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ephemeral credentials — the ONLY credentials quelltest ever uses
# ---------------------------------------------------------------------------

EPHEMERAL_CREDS: dict[str, dict[str, str | None]] = {
    "postgres":   {"user": "quell", "password": "quell_eph", "db": "quell_test"},
    "redis":      {"password": None},
    "mongo":      {"user": "quell", "password": "quell_eph", "db": "quell_test"},
    "mysql":      {"user": "quell", "password": "quell_eph", "db": "quell_test"},
    "localstack": {"access_key": "test", "secret_key": "test", "region": "us-east-1"},
}

# ---------------------------------------------------------------------------
# Forbidden env vars — real credentials that quelltest deliberately ignores
# ---------------------------------------------------------------------------

FORBIDDEN_ENV_READS: list[str] = [
    "DATABASE_URL", "DB_URL", "POSTGRES_URL", "MYSQL_URL",
    "REDIS_URL", "REDIS_HOST", "REDIS_PASSWORD",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "MONGODB_URI", "MONGO_URL", "SECRET_KEY", "API_KEY",
]

_TRUST_MSG = """\
┌────────────────────────────────────────────────────────┐
│  quelltest infrastructure isolation                    │
│                                                        │
│  ✓ Starting throwaway container (ephemeral creds)      │
│  ✓ No connection to your real database                 │
│  ✓ Container destroyed after this run                  │
│                                                        │
│  quelltest never reads or stores your real             │
│  database credentials or connection strings.           │
└────────────────────────────────────────────────────────┘"""

_TRUST_FLAG = Path(".quellgraph") / "trust_shown"


def _assert_no_credential_reads() -> None:
    """Log that real env vars are deliberately ignored. Never raises."""
    for key in FORBIDDEN_ENV_READS:
        if key in os.environ:
            logger.debug("quelltest: ignoring %s (using ephemeral container instead)", key)


def show_trust_message_once() -> None:
    """Print the isolation trust message on first run per project."""
    if _TRUST_FLAG.exists():
        return
    print(_TRUST_MSG)
    try:
        _TRUST_FLAG.parent.mkdir(parents=True, exist_ok=True)
        _TRUST_FLAG.touch()
    except OSError:
        pass  # non-fatal


# ---------------------------------------------------------------------------
# Import → infra tag map  (used by QuellGraph builder)
# ---------------------------------------------------------------------------

IMPORT_SIGNALS: dict[str, str] = {
    # PostgreSQL
    "sqlalchemy": "postgres",
    "databases": "postgres",
    "asyncpg": "postgres",
    "psycopg2": "postgres",
    "psycopg": "postgres",
    "tortoise": "postgres",
    "alembic": "postgres",
    # MySQL
    "pymysql": "mysql",
    "aiomysql": "mysql",
    # MongoDB
    "motor": "mongo",
    "pymongo": "mongo",
    "beanie": "mongo",
    # Redis / cache / broker
    "redis": "redis",
    "aioredis": "redis",
    "celery": "redis",   # default broker; overridden if pika also present
    "kombu": "redis",
    # AWS / object storage
    "boto3": "localstack",
    "botocore": "localstack",
    "aiobotocore": "localstack",
    "s3fs": "localstack",
    # Search
    "elasticsearch": "elasticsearch",
    "opensearchpy": "opensearch",
    # Message queue
    "pika": "rabbitmq",
    "aio_pika": "rabbitmq",
    # Email
    "smtplib": "smtp",
    "aiosmtplib": "smtp",
}

# Infra parameter type names — catches dependency-injected infra
INFRA_TYPE_NAMES: dict[str, str] = {
    "Session": "postgres",
    "AsyncSession": "postgres",
    "Connection": "postgres",
    "AsyncConnection": "postgres",
    "Redis": "redis",
    "StrictRedis": "redis",
    "AsyncRedis": "redis",
    "MongoClient": "mongo",
    "AsyncIOMotorClient": "mongo",
    "S3Client": "localstack",
    "DynamoDBClient": "localstack",
    "Elasticsearch": "elasticsearch",
    "BlockingConnection": "rabbitmq",
    "Channel": "rabbitmq",
}

# ---------------------------------------------------------------------------
# Container specs registry
# ---------------------------------------------------------------------------


@dataclass
class ContainerSpec:
    """Configuration for one type of ephemeral infrastructure container."""

    tag: str                        # e.g. "postgres"
    image: str                      # e.g. "postgres:16"
    fixture_name: str               # e.g. "_quell_pg"
    port: int
    wait_strategy: str              # "log" | "http" | "port"
    wait_value: str                 # log line or HTTP path to probe
    connection_env_key: str         # env var injected into the test subprocess
    connection_url_template: str    # format with {host} and {port}
    extra_imports: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)


CONTAINER_SPECS: dict[str, ContainerSpec] = {
    "postgres": ContainerSpec(
        tag="postgres",
        image="postgres:16",
        fixture_name="_quell_pg",
        port=5432,
        wait_strategy="log",
        wait_value="database system is ready to accept connections",
        connection_env_key="DATABASE_URL",
        connection_url_template=(
            "postgresql://quell:quell_eph@{host}:{port}/quell_test"
        ),
        extra_imports=[
            "from sqlalchemy import create_engine",
            "from sqlalchemy.orm import sessionmaker",
        ],
    ),
    "redis": ContainerSpec(
        tag="redis",
        image="redis:7",
        fixture_name="_quell_redis",
        port=6379,
        wait_strategy="log",
        wait_value="Ready to accept connections",
        connection_env_key="REDIS_URL",
        connection_url_template="redis://{host}:{port}/0",
        extra_imports=["import redis as _redis_lib"],
    ),
    "localstack": ContainerSpec(
        tag="localstack",
        image="localstack/localstack:3",
        fixture_name="_quell_localstack",
        port=4566,
        wait_strategy="http",
        wait_value="/_localstack/health",
        connection_env_key="AWS_ENDPOINT_URL",
        connection_url_template="http://{host}:{port}",
        extra_imports=["import boto3"],
        env_vars={"SERVICES": "s3,sqs,dynamodb"},
    ),
    "mongo": ContainerSpec(
        tag="mongo",
        image="mongo:7",
        fixture_name="_quell_mongo",
        port=27017,
        wait_strategy="log",
        wait_value="Waiting for connections",
        connection_env_key="MONGODB_URL",
        connection_url_template="mongodb://quell:quell_eph@{host}:{port}",
        extra_imports=["from pymongo import MongoClient"],
    ),
    "smtp": ContainerSpec(
        tag="smtp",
        image="axllent/mailpit:latest",
        fixture_name="_quell_smtp",
        port=1025,
        wait_strategy="port",
        wait_value="",
        connection_env_key="SMTP_HOST",
        connection_url_template="{host}:{port}",
        extra_imports=[],
    ),
    "rabbitmq": ContainerSpec(
        tag="rabbitmq",
        image="rabbitmq:3-management",
        fixture_name="_quell_rabbitmq",
        port=5672,
        wait_strategy="log",
        wait_value="Server startup complete",
        connection_env_key="BROKER_URL",
        connection_url_template="amqp://guest:guest@{host}:{port}//",
        extra_imports=[],
    ),
    "elasticsearch": ContainerSpec(
        tag="elasticsearch",
        image="elasticsearch:8.13.0",
        fixture_name="_quell_es",
        port=9200,
        wait_strategy="http",
        wait_value="/_cluster/health",
        connection_env_key="ELASTICSEARCH_URL",
        connection_url_template="http://{host}:{port}",
        extra_imports=["from elasticsearch import Elasticsearch"],
        env_vars={
            "discovery.type": "single-node",
            "xpack.security.enabled": "false",
        },
    ),
}
