#!/usr/bin/env python3
"""Offline provisioning for a trusted operator; never connect to a database."""

import argparse
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from uuid import UUID


def main():
    parser = argparse.ArgumentParser(
        description="Create private gateway/server environment files without printing secrets"
    )
    parser.add_argument("--gateway-id", required=True)
    parser.add_argument("--ward-id", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.gateway_id):
        parser.error("gateway-id must be 1-64 letters, digits, hyphens or underscores")
    try:
        wards = sorted({str(UUID(value)) for value in args.ward_id})
    except ValueError:
        parser.error("ward-id must be a UUID")
    try:
        args.output_dir.mkdir(mode=0o700)
    except FileExistsError:
        parser.error(
            "output directory already exists; credentials will not be overwritten"
        )
    token = secrets.token_urlsafe(32)
    credentials = [
        {
            "gateway_id": args.gateway_id,
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "allowed_ward_ids": wards,
            "enabled": True,
        }
    ]
    for name, content in {
        "gateway.env": f"DUXUE_GATEWAY_TOKEN='{token}'\n",
        "server.env": "GATEWAY_CREDENTIALS_JSON='"
        + json.dumps(credentials, separators=(",", ":"))
        + "'\n",
    }.items():
        descriptor = os.open(
            args.output_dir / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
    print(
        f"Created private environment files in {args.output_dir}; configure camera credentials separately."
    )


if __name__ == "__main__":
    main()
