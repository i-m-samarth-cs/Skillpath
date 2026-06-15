"""
Band SDK client adapter for SkillPath.

This module uses the official Band SDK (`band-sdk` / `thenvoi`) and loads
agent credentials from `agent_config.yaml`.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import yaml
from band import BandLink
from band.client.rest import (
    ChatMessageRequest,
    ChatMessageRequestMentionsItem,
    ChatRoomRequest,
    DEFAULT_REQUEST_OPTIONS,
    ParticipantRequest,
)
from band.config.loader import load_agent_config
from band.platform.event import PlatformEvent
from utils.agent_constants import STRUCTURED_MARKER

MENTION_PATTERN = re.compile(r"@([a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)?)")

# Default handoff targets for structured agent-to-agent payloads (no @ in body).
STRUCTURED_EVENT_TARGETS: dict[str, str] = {
    "gap_analysis_complete": "curriculum-architect",
    "curricula_ready": "coach-agent",
    "coaching_started": "progress-tracker",
    "progress_update": "progress-tracker",
    "progress_report_ready": "hr-reporter",
}


def _load_agent_config(agent_key: str, config_path: str | Path | None = None):
    candidate = Path(config_path) if config_path else Path.cwd() / "agent_config.yaml"
    example = candidate.parent / f"{candidate.name}.example"

    if not candidate.exists():
        if example.exists():
            print(
                f"[{agent_key}] Config file not found at {candidate}. "
                f"Falling back to example config {example}. Copy it to {candidate} and configure your agents."
            )
            candidate = example
        else:
            raise FileNotFoundError(
                f"Config file not found at {candidate}. "
                "Copy agent_config.yaml.example to agent_config.yaml and configure your agents."
            )

    return load_agent_config(agent_key, config_path=str(candidate))


def parse_structured_payload(content: str) -> dict[str, Any]:
    """Extract JSON payload even when Band prepends @mention text to content."""
    marker = STRUCTURED_MARKER
    idx = content.find(marker)
    if idx == -1:
        return {}
    try:
        return json.loads(content[idx + len(marker):])
    except json.JSONDecodeError:
        return {}


class BandSDKClient:
    def __init__(
        self,
        agent_key: str,
        agent_name: str,
        config_path: str | Path | None = None,
        ws_url: str | None = None,
        rest_url: str | None = None,
    ):
        self.agent_key = agent_key
        self.agent_name = agent_name
        self._config_path = Path(config_path) if config_path else Path.cwd() / "agent_config.yaml"
        self.agent_id, self.api_key = _load_agent_config(agent_key, config_path=config_path)
        self._peer_agent_ids = set(self._load_peer_agent_ids().values())
        self.ws_url = ws_url or "wss://app.band.ai/api/v1/socket/websocket"
        self.rest_url = rest_url or "https://app.band.ai"
        self.link: BandLink | None = None
        self.room_id: str | None = None
        self._listeners: list[Any] = []
        self._subscribed_rooms: set[str] = set()
        self._connected = False

    async def connect(self):
        if self._connected:
            return

        self.link = BandLink(
            agent_id=self.agent_id,
            api_key=self.api_key,
            ws_url=self.ws_url,
            rest_url=self.rest_url,
        )

        await self.link.connect()
        await self.link.subscribe_agent_rooms(self.agent_id)
        await self._subscribe_existing_rooms()
        self._connected = True
        print(f"[{self.agent_name}] Connected to Band SDK ✔")

    async def disconnect(self):
        if self.link and self._connected:
            await self.link.disconnect()
        self._connected = False
        self._subscribed_rooms.clear()
        self.room_id = None

    async def _subscribe_existing_rooms(self):
        if not self.link:
            return

        page = 1
        while True:
            response = await self.link.rest.agent_api_chats.list_agent_chats(
                page=page,
                page_size=50,
                request_options=DEFAULT_REQUEST_OPTIONS,
            )

            for room in response.data:
                await self.subscribe_room(room.id)

            total_pages = getattr(response.metadata, "total_pages", None)
            if not total_pages or page >= total_pages:
                break
            page += 1

    async def subscribe_room(self, room_id: str):
        if not self.link:
            raise RuntimeError("Band SDK client is not connected")
        if room_id in self._subscribed_rooms:
            return

        await self.link.subscribe_room(room_id)
        self._subscribed_rooms.add(room_id)
        self.room_id = room_id
        print(f"[{self.agent_name}] Subscribed to room: {room_id}")

    async def join_room(self, room_id: str):
        """Alias for subscribing to a room and tracking it for future messages."""
        await self.subscribe_room(room_id)

    async def _on_room_added(self, payload: Any):
        if getattr(payload, "id", None):
            await self.subscribe_room(payload.id)

    async def _on_room_removed(self, payload: Any):
        if getattr(payload, "id", None):
            self._subscribed_rooms.discard(payload.id)
            if self.room_id == payload.id:
                self.room_id = None

    def on_message(self, callback):
        self._listeners.append(callback)

    async def listen(self):
        if not self.link:
            raise RuntimeError("Band SDK client is not connected")

        async for event in self.link:
            await self._dispatch_event(event)

    async def _dispatch_event(self, event: PlatformEvent):
        if event.type != "message_created" or event.payload is None:
            return

        payload = event.payload
        room_id = event.room_id or getattr(payload, "chat_room_id", None)
        content = getattr(payload, "content", "") or ""
        sender_id = getattr(payload, "sender_id", None)
        sender = getattr(payload, "sender_name", None) or sender_id or "unknown"

        if sender_id == self.agent_id:
            return

        if not room_id:
            return

        if room_id not in self._subscribed_rooms:
            await self.subscribe_room(room_id)

        data = parse_structured_payload(content)

        raw_payload = {}
        try:
            raw_payload = payload.model_dump()  # type: ignore[attr-defined]
        except Exception:
            try:
                raw_payload = payload.dict()
            except Exception:
                raw_payload = {"content": content}

        raw = {"room_id": room_id, "sender_id": sender_id, **raw_payload}

        for callback in self._listeners:
            await callback(sender=sender, text=content, data=data, raw=raw)

    def is_peer_agent(self, sender_id: str | None) -> bool:
        return bool(sender_id and sender_id in self._peer_agent_ids and sender_id != self.agent_id)

    def _load_peer_agent_ids(self) -> dict[str, str]:
        """Return {agent_key: agent_id} for all SkillPath agents in config."""
        candidate = self._config_path
        if not candidate.exists():
            example = candidate.parent / f"{candidate.name}.example"
            candidate = example if example.exists() else candidate
        if not candidate.exists():
            return {}

        with open(candidate, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        peers: dict[str, str] = {}
        for key, value in config.items():
            if isinstance(value, dict) and value.get("agent_id"):
                peers[str(key)] = str(value["agent_id"])
        return peers

    async def _get_room_participants(self, room_id: str) -> list[dict[str, Any]]:
        if not self.link:
            return []

        response = await self.link.rest.agent_api_participants.list_agent_chat_participants(
            chat_id=room_id,
            request_options=DEFAULT_REQUEST_OPTIONS,
        )
        if not response.data:
            return []

        return [
            {
                "id": p.id,
                "name": p.name,
                "type": p.type,
                "handle": getattr(p, "handle", None),
            }
            for p in response.data
        ]

    @staticmethod
    def _normalize_identifier(value: str) -> str:
        return str(value).lstrip("@").lower()

    def _identifier_matches_participant(self, identifier: str, participant: dict[str, Any]) -> bool:
        norm = self._normalize_identifier(identifier)
        for field in (participant.get("handle"), participant.get("name"), participant.get("id")):
            if not field:
                continue
            val = self._normalize_identifier(str(field))
            if val == norm or val.endswith(f"/{norm}"):
                return True
        return False

    def _parse_mentions_from_text(self, text: str) -> list[str]:
        return MENTION_PATTERN.findall(text)

    def _resolve_mention_items(
        self,
        identifiers: list[str],
        participants: list[dict[str, Any]],
    ) -> list[ChatMessageRequestMentionsItem]:
        items: list[ChatMessageRequestMentionsItem] = []
        seen_ids: set[str] = set()

        for identifier in identifiers:
            participant = next(
                (p for p in participants if self._identifier_matches_participant(identifier, p)),
                None,
            )
            if not participant or participant["id"] in seen_ids:
                continue
            seen_ids.add(participant["id"])
            items.append(
                ChatMessageRequestMentionsItem(
                    id=participant["id"],
                    handle=participant.get("handle"),
                    name=participant.get("name"),
                )
            )
        return items

    def _default_mention_items(
        self,
        participants: list[dict[str, Any]],
    ) -> list[ChatMessageRequestMentionsItem]:
        """Mention every other participant in the room (Band requires ≥1 mention)."""
        items: list[ChatMessageRequestMentionsItem] = []
        for participant in participants:
            if participant["id"] == self.agent_id:
                continue
            items.append(
                ChatMessageRequestMentionsItem(
                    id=participant["id"],
                    handle=participant.get("handle"),
                    name=participant.get("name"),
                )
            )
        return items

    async def ensure_skillpath_peers(self, room_id: str):
        """Add all configured SkillPath agents to a room so handoffs can @mention them."""
        if not self.link:
            raise RuntimeError("Band SDK client is not connected")

        existing = {p["id"] for p in await self._get_room_participants(room_id)}
        for peer_key, peer_id in self._load_peer_agent_ids().items():
            if peer_id in existing:
                continue
            try:
                await self.link.rest.agent_api_participants.add_agent_chat_participant(
                    chat_id=room_id,
                    participant=ParticipantRequest(participant_id=peer_id),
                    request_options=DEFAULT_REQUEST_OPTIONS,
                )
                existing.add(peer_id)
                print(f"[{self.agent_name}] Added peer {peer_key} to room {room_id}")
            except Exception as exc:
                print(f"[{self.agent_name}] Could not add peer {peer_key}: {exc}")

    async def _build_mention_items(
        self,
        text: str,
        room_id: str,
        mentions: list[str] | None = None,
    ) -> list[ChatMessageRequestMentionsItem]:
        participants = await self._get_room_participants(room_id)
        identifiers = mentions or self._parse_mentions_from_text(text)
        mention_items = self._resolve_mention_items(identifiers, participants)

        if not mention_items:
            mention_items = self._default_mention_items(participants)

        if not mention_items:
            await self.ensure_skillpath_peers(room_id)
            participants = await self._get_room_participants(room_id)
            mention_items = self._resolve_mention_items(identifiers, participants)
            if not mention_items:
                mention_items = self._default_mention_items(participants)

        if not mention_items:
            mention_items = [
                ChatMessageRequestMentionsItem(
                    id=self.agent_id,
                    handle=self.agent_name,
                    name=self.agent_name,
                )
            ]

        return mention_items

    async def send_message(
        self,
        text: str,
        room_id: str | None = None,
        mentions: list[str] | None = None,
    ):
        if not self.link:
            raise RuntimeError("Band SDK client is not connected")

        target_room = room_id or self.room_id
        if not target_room:
            raise ValueError("No room_id set — call subscribe_room() or create_room() first.")

        mention_items = await self._build_mention_items(text, target_room, mentions=mentions)
        request = ChatMessageRequest(content=text, mentions=mention_items)

        await self.link.rest.agent_api_messages.create_agent_chat_message(
            chat_id=target_room,
            message=request,
            request_options=DEFAULT_REQUEST_OPTIONS,
        )

        print(f"[{self.agent_name}] → {text[:120]}")

    async def send_structured(
        self,
        data: dict,
        room_id: str | None = None,
        mention: str | None = None,
    ):
        event = data.get("event")
        target = mention or STRUCTURED_EVENT_TARGETS.get(event)
        mentions = [target] if target else None
        await self.send_message(
            f"{STRUCTURED_MARKER}{json.dumps(data)}",
            room_id,
            mentions=mentions,
        )

    async def create_room(self, room_name: str, *, add_peers: bool = True) -> str:
        if not self.link:
            raise RuntimeError("Band SDK client is not connected")

        response = await self.link.rest.agent_api_chats.create_agent_chat(
            chat=ChatRoomRequest(),
            request_options=DEFAULT_REQUEST_OPTIONS,
        )
        room_id = response.data.id
        self.room_id = room_id
        await self.subscribe_room(room_id)
        if add_peers:
            await self.ensure_skillpath_peers(room_id)
        print(f"[{self.agent_name}] Created room: {room_name} (id={room_id})")
        return room_id
