"""Vendored client for the Somfy Connect UAI+ gateway.

Kept inside the integration rather than published as a dependency so that
manifest.json can declare `requirements: []`. That avoids the git+https
dependency that makes a sibling project fragile, and keeps hassfest happy.

Pure asyncio and stdlib -- nothing here imports Home Assistant, so it can be
tested without a HA test harness.
"""

from __future__ import annotations

from .client import (
    DEFAULT_PORT,
    UaiAuthError,
    UaiClient,
    UaiConnectionError,
    UaiError,
    UaiTimeoutError,
)
from .models import (
    ALL_GROUP_ID,
    Capability,
    GroupInfo,
    Node,
    capability_for_group,
    classify_type,
    find_name_group_conflicts,
    group_id_for_index,
    group_index_for_id,
    parse_position,
    unique_slug_names,
)
from .protocol import Response, encode_request, parse_response

__all__ = [
    "ALL_GROUP_ID",
    "DEFAULT_PORT",
    "Capability",
    "GroupInfo",
    "Node",
    "Response",
    "UaiAuthError",
    "UaiClient",
    "UaiConnectionError",
    "UaiError",
    "UaiTimeoutError",
    "capability_for_group",
    "classify_type",
    "encode_request",
    "find_name_group_conflicts",
    "group_id_for_index",
    "group_index_for_id",
    "parse_position",
    "parse_response",
    "unique_slug_names",
]
