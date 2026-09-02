from __future__ import annotations

import asyncio
import os
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict


class MemoryMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class MemoryProvider(ABC):
    """Swappable persistent-memory boundary for the realtime agent."""

    @abstractmethod
    async def context(self, user_id: str) -> str:
        """Return compact context suitable for the model's system instruction."""

    @abstractmethod
    async def remember(self, user_id: str, messages: Sequence[MemoryMessage]) -> None:
        """Queue a completed conversation segment for memory processing."""

    async def flush(self, user_id: str) -> None:
        del user_id

    async def close(self) -> None:
        return


def memobase_user_id(user_id: str) -> str:
    """Memobase requires UUIDs; Gizmo permits stable owner/device labels."""
    try:
        return str(uuid.UUID(user_id))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"gizmo:user:{user_id}"))


class NullMemoryProvider(MemoryProvider):
    async def context(self, user_id: str) -> str:
        del user_id
        return ""

    async def remember(self, user_id: str, messages: Sequence[MemoryMessage]) -> None:
        del user_id, messages


@dataclass
class MemobaseMemoryProvider(MemoryProvider):
    """Memobase adapter. The session owns all scheduling and timeouts."""

    project_url: str
    api_key: str
    context_tokens: int = 1200

    def __post_init__(self) -> None:
        from memobase import AsyncMemoBaseClient

        self._client = AsyncMemoBaseClient(
            api_key=self.api_key,
            project_url=self.project_url.rstrip("/") + "/",
        )
        self._users: dict[str, object] = {}
        self._user_lock = asyncio.Lock()

    async def _user(self, user_id: str):
        cached = self._users.get(user_id)
        if cached is not None:
            return cached
        async with self._user_lock:
            cached = self._users.get(user_id)
            if cached is None:
                cached = await self._client.get_or_create_user(memobase_user_id(user_id))
                self._users[user_id] = cached
        return cached

    async def context(self, user_id: str) -> str:
        user = await self._user(user_id)
        return await user.context(
            max_token_size=self.context_tokens,
            require_event_summary=True,
            fill_window_with_events=True,
        )

    async def remember(self, user_id: str, messages: Sequence[MemoryMessage]) -> None:
        from memobase import ChatBlob

        cleaned = [dict(message) for message in messages if message.get("content", "").strip()]
        if not cleaned:
            return
        user = await self._user(user_id)
        await user.insert(ChatBlob(messages=cleaned), sync=False)

    async def flush(self, user_id: str) -> None:
        user = await self._user(user_id)
        await user.flush(sync=False)

    async def close(self) -> None:
        await self._client.close()


def memory_provider_from_env() -> MemoryProvider:
    project_url = os.environ.get("MEMOBASE_URL", "").strip()
    api_key = os.environ.get("MEMOBASE_API_KEY", "").strip()
    if not project_url or not api_key:
        return NullMemoryProvider()
    return MemobaseMemoryProvider(project_url=project_url, api_key=api_key)
