"""Local, explicit onboarding policy data for the case-study demo."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "data" / "blocked_vendors.json"


def load_blocked_vendors(path: Path = DEFAULT_POLICY_PATH) -> dict[str, str]:
    """Return exact GSTIN-to-reason mappings from the synthetic policy file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    vendors = payload.get("blocked_vendors", [])
    result: dict[str, str] = {}
    for vendor in vendors:
        gstin = str(vendor.get("gstin", "")).strip().upper()
        reason = str(vendor.get("reason", "")).strip()
        if not gstin or not reason:
            raise ValueError("Every blocked vendor requires a GSTIN and reason.")
        if gstin in result:
            raise ValueError(f"Duplicate blocked GSTIN in policy: {gstin}")
        result[gstin] = reason
    return result
