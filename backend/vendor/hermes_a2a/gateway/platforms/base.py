"""The ``gateway.platforms.base`` surface the vendored A2A adapter imports.

BrainBuddy-owned stub (spec 014 FR-017, research.md Decision G). Not upstream
code, and deliberately not a re-implementation of the Hermes gateway: it is the
smallest object graph that lets the **unmodified** ``A2AAdapter`` run its real
HTTP server, task store, watchdog and JSON-RPC dispatch, which is the part
BrainBuddy's client is being tested against.

Upstream's own plugin tests build the same double — override
``adapter.handle_message`` and set ``adapter._message_handler`` to a truthy
sentinel — so the seam this stub occupies is the seam Hermes already tests at.

Everything here is either read by ``adapter.py`` or by the base-class methods
``adapter.py`` calls. Runtime-status publishing, session routing, media,
proxying, streaming TTS and the plugin manager are all *absent* rather than
faked, because the adapter never reaches them on the A2A path.
"""

from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional

from gateway.config import Platform, PlatformConfig

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Types of incoming messages. The A2A adapter only ever emits TEXT."""

    TEXT = "text"
    LOCATION = "location"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    VOICE = "voice"
    DOCUMENT = "document"
    STICKER = "sticker"
    COMMAND = "command"


class ProcessingOutcome(Enum):
    """Result classification for the message-processing lifecycle hook."""

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


@dataclass
class SessionSource:
    """Where an inbound message came from.

    The A2A adapter sets ``chat_id`` to the A2A ``contextId`` and resolves its
    pending reply future by that value, so ``chat_id`` is the one field with
    behavioural weight here.
    """

    platform: Optional[Platform] = None
    chat_id: str = ""
    chat_name: Optional[str] = None
    chat_type: str = "dm"
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    thread_id: Optional[str] = None
    chat_topic: Optional[str] = None
    user_id_alt: Optional[str] = None
    chat_id_alt: Optional[str] = None
    is_bot: bool = False
    scope_id: Optional[str] = None
    guild_id: Optional[str] = None
    parent_chat_id: Optional[str] = None
    message_id: Optional[str] = None
    role_authorized: bool = False
    auto_thread_created: bool = False
    auto_thread_initial_name: Optional[str] = None


@dataclass
class MessageEvent:
    """One normalized inbound message.

    ``message_id`` carries the A2A task id — ``on_processing_complete`` reads it
    back to resolve the right task — and ``source.chat_id`` carries the
    ``contextId``.
    """

    text: str
    message_type: MessageType = MessageType.TEXT
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    source: Optional[SessionSource] = None
    raw_message: Any = None
    message_id: Optional[str] = None
    allow_gateway_control: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SendResult:
    """Result of sending a message back to the platform."""

    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    raw_response: Any = None
    retryable: bool = False
    retry_after: Optional[float] = None
    continuation_message_ids: tuple = ()
    error_kind: Optional[str] = None


MessageHandler = Callable[[MessageEvent], Awaitable[None]]


class BasePlatformAdapter(ABC):
    """The lifecycle contract ``A2AAdapter`` subclasses.

    Connection state is kept as plain attributes instead of being published to
    a runtime-status directory: the harness reads it directly, and writing
    status files would need the rest of the gateway.
    """

    supports_code_blocks: bool = False
    supports_status_text: bool = False
    send_path_degraded: bool = False

    def __init__(self, config: PlatformConfig, platform: Platform) -> None:
        self.config = config
        self.platform = platform
        self._message_handler: Optional[MessageHandler] = None
        self._reaction_handler: Optional[Callable[..., Awaitable[None]]] = None
        self._platform_event_handler: Optional[Callable[..., Awaitable[None]]] = None
        self._topic_recovery_fn: Optional[Callable[[Any], Optional[str]]] = None
        self._running = False
        self._fatal_error_code: Optional[str] = None
        self._fatal_error_message: Optional[str] = None
        self._fatal_error_retryable = True

    # ── identity ──────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return getattr(self.platform, "value", str(self.platform))

    @property
    def authorization_is_upstream(self) -> bool:
        return False

    # ── connection state ──────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def has_fatal_error(self) -> bool:
        return self._fatal_error_code is not None

    @property
    def fatal_error(self) -> Optional[tuple[str, Optional[str], bool]]:
        if self._fatal_error_code is None:
            return None
        return (
            self._fatal_error_code,
            self._fatal_error_message,
            self._fatal_error_retryable,
        )

    def _mark_connected(self) -> None:
        self._running = True
        self._fatal_error_code = None
        self._fatal_error_message = None
        self._fatal_error_retryable = True

    def _mark_degraded(self) -> None:
        self._running = True

    def _mark_disconnected(self) -> None:
        self._running = False

    def _set_fatal_error(self, code: str, message: str, *, retryable: bool) -> None:
        self._running = False
        self._fatal_error_code = code
        self._fatal_error_message = message
        self._fatal_error_retryable = retryable
        logger.error("adapter fatal error %s: %s", code, message)

    def _wire_plugin_handlers(self, native: Any = None) -> None:
        """No plugin manager in the harness, so there is nothing to wire."""

    # ── message plumbing ──────────────────────────────────────────────────

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._message_handler = handler

    async def handle_message(self, event: MessageEvent) -> None:
        """Hand an inbound event to the configured handler.

        ``run_stub.py`` overrides this with its scripted reply handler, exactly
        as Hermes' own ``_make_live_adapter`` test helper does.
        """

        if self._message_handler is None:
            return
        await self._message_handler(event)

    def build_source(
        self,
        chat_id: str,
        chat_name: Optional[str] = None,
        chat_type: str = "dm",
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        thread_id: Optional[str] = None,
        chat_topic: Optional[str] = None,
        user_id_alt: Optional[str] = None,
        chat_id_alt: Optional[str] = None,
        is_bot: bool = False,
        scope_id: Optional[str] = None,
        guild_id: Optional[str] = None,
        parent_chat_id: Optional[str] = None,
        message_id: Optional[str] = None,
        role_authorized: bool = False,
        auto_thread_created: bool = False,
        auto_thread_initial_name: Optional[str] = None,
    ) -> SessionSource:
        return SessionSource(
            platform=self.platform,
            chat_id=chat_id,
            chat_name=chat_name,
            chat_type=chat_type,
            user_id=user_id,
            user_name=user_name,
            thread_id=thread_id,
            chat_topic=chat_topic,
            user_id_alt=user_id_alt,
            chat_id_alt=chat_id_alt,
            is_bot=is_bot,
            scope_id=scope_id,
            guild_id=guild_id,
            parent_chat_id=parent_chat_id,
            message_id=message_id,
            role_authorized=role_authorized,
            auto_thread_created=auto_thread_created,
            auto_thread_initial_name=auto_thread_initial_name,
        )

    def set_status_text(self, chat_id: str, text: Optional[str]) -> None:
        return None


__all__ = [
    "BasePlatformAdapter",
    "MessageEvent",
    "MessageHandler",
    "MessageType",
    "ProcessingOutcome",
    "SendResult",
    "SessionSource",
]
