"""Secure case references and vendor tracking tokens."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
from uuid import UUID, uuid4


@dataclass(frozen=True)
class CaseCredentials:
    case_id: str
    access_token: str

    @property
    def token_hash(self) -> str:
        return hash_access_token(self.access_token)


@dataclass(frozen=True)
class RevisionContext:
    case_id: str
    access_token: str
    parent_run_id: int
    revision_number: int

    @property
    def token_hash(self) -> str:
        return hash_access_token(self.access_token)


def create_case_credentials() -> CaseCredentials:
    return CaseCredentials(
        case_id=str(uuid4()),
        access_token=secrets.token_urlsafe(32),
    )


def hash_access_token(access_token: str) -> str:
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def normalize_case_id(case_id: str) -> str | None:
    try:
        return str(UUID(case_id.strip()))
    except (AttributeError, TypeError, ValueError):
        return None


def tracking_credentials_valid(case_id: str, access_token: str) -> bool:
    return normalize_case_id(case_id) is not None and len(access_token.strip()) >= 32
