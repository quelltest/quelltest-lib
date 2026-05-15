"""
Dependency resolver — maps a set of infra tags to ContainerSpec instances.

Handles the Celery broker ambiguity:
  pika present → rabbitmq wins over celery's default redis broker
  celery + redis only → redis
"""
from __future__ import annotations

import logging

from quell.infra.specs import CONTAINER_SPECS, ContainerSpec

logger = logging.getLogger(__name__)


def resolve_specs(tags: set[str]) -> list[ContainerSpec]:
    """
    Given a set of infra tags, return the ordered list of ContainerSpecs to start.

    Resolution rules:
    - Unknown tags are logged and skipped (never raise).
    - If both 'rabbitmq' and 'redis' appear, keep both — they serve different roles.
    - If only 'celery' produced 'redis' (no explicit redis import), log the resolution.
    """
    resolved: list[ContainerSpec] = []
    unknown: list[str] = []

    for tag in sorted(tags):  # sorted for deterministic ordering
        spec = CONTAINER_SPECS.get(tag)
        if spec is None:
            unknown.append(tag)
            logger.warning(
                "quelltest: no container spec for infra tag '%s' — skipping. "
                "This dependency will not be available during verification.",
                tag,
            )
        else:
            resolved.append(spec)

    if unknown:
        logger.debug("Unresolved infra tags: %s", unknown)

    return resolved


def tags_from_import_signals(
    imports: list[str],
    import_signals: dict[str, str] | None = None,
) -> set[str]:
    """
    Map a list of top-level import names to infra tags.

    Handles the Celery broker ambiguity:
      if 'pika' in imports → use 'rabbitmq' for Celery broker, not 'redis'
    """
    from quell.infra.specs import IMPORT_SIGNALS

    signals = import_signals if import_signals is not None else IMPORT_SIGNALS
    tags: set[str] = set()

    has_pika = "pika" in imports or "aio_pika" in imports
    has_celery = "celery" in imports

    for imp in imports:
        tag = signals.get(imp)
        if tag:
            tags.add(tag)

    # Resolve Celery broker ambiguity
    if has_celery and has_pika and "redis" in tags:
        # pika explicitly present → RabbitMQ is the broker; remove redis from celery
        # (only remove if redis wasn't imported directly via 'redis' or 'aioredis')
        direct_redis = any(imp in ("redis", "aioredis") for imp in imports)
        if not direct_redis:
            tags.discard("redis")
            logger.debug("Celery broker resolved to rabbitmq (pika present)")

    return tags
