"""Users' own AI provider keys, encrypted (A8.7, M11.2 BYOK).

Owner, 27 Nov 2026: Ollama first, then the user's own keys. ``ciphertext`` is
the key encrypted with ``APP_ENCRYPTION_KEY`` (Fernet); the key itself is
never stored, logged or returned. ``key_last4`` is shown so the user can tell
keys apart. One key per user and provider.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

AI_KEY_PROVIDERS = ("openai_compatible", "anthropic")
PROVIDER_SQL = ", ".join(f"'{p}'" for p in AI_KEY_PROVIDERS)


class UserAiKey(SQLModel, table=True):
    __tablename__ = "user_ai_keys"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_ai_keys_user_provider"),
        CheckConstraint(f"provider IN ({PROVIDER_SQL})", name="ck_user_ai_keys_provider"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    )
    provider: str = Field(max_length=24)
    ciphertext: str = Field(sa_column=Column(Text, nullable=False))
    key_last4: str = Field(max_length=4)
    model: str = Field(max_length=100)
    base_url: str | None = Field(default=None, max_length=300)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
