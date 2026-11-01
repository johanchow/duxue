"""Preprovisioned, capture-only gateway credentials; never log raw configuration."""

import hashlib
import hmac
import json
import re
from uuid import UUID

from app.application.commands.gateway_ingestion import GatewayPrincipal
from app.bootstrap.settings import ConfigurationError, settings


def credential_config():
    return settings.gateway_credentials


def credentials():
    try:
        rows = json.loads(credential_config())
        if not isinstance(rows, list):
            raise TypeError()
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) - {
                "gateway_id",
                "token_hash",
                "allowed_ward_ids",
                "enabled",
            }:
                raise ValueError()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", row["gateway_id"]):
                raise ValueError()
            if not re.fullmatch(r"[a-f0-9]{64}", row["token_hash"]):
                raise ValueError()
            if row["token_hash"] in seen:
                raise ValueError()
            seen.add(row["token_hash"])
            if not isinstance(row.get("enabled", True), bool) or not isinstance(
                row["allowed_ward_ids"], list
            ):
                raise TypeError()
            for ward in row["allowed_ward_ids"]:
                UUID(ward)
        return rows
    except (ValueError, TypeError, KeyError):
        raise ConfigurationError(
            "Invalid GATEWAY_CREDENTIALS_JSON capture credential configuration"
        ) from None


def authenticate(token):
    supplied = hashlib.sha256(token.encode()).hexdigest()
    for row in credentials():
        if hmac.compare_digest(supplied, row["token_hash"]) and row.get(
            "enabled", True
        ):
            return GatewayPrincipal(
                row["gateway_id"],
                frozenset(str(UUID(w)) for w in row["allowed_ward_ids"]),
            )
    return None
