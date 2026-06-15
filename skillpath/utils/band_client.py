"""
Band WebSocket client — handles connection, sending messages,
and receiving messages from a Band chatroom.
"""

import asyncio
import json
import os
import websockets
from dotenv import load_dotenv

load_dotenv()

BAND_WS_URL  = os.getenv("BAND_WS_URL",  "wss://app.band.ai/api/v1/socket/websocket")
BAND_REST_URL = os.getenv("BAND_REST_URL", "https://app.band.ai")


class BandClient:
    """
    Lightweight Band WebSocket client.
    Each agent creates one BandClient instance with its own agent_id + api_key.
    """

    def __init__(self, agent_id: str, api_key: str, agent_name: str):
        self.agent_id   = agent_id
        self.api_key    = api_key
        self.agent_name = agent_name
        self.ws         = None
        self.room_id    = None
        self._listeners = []   # list of async callbacks

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    async def connect(self):
        """Open WebSocket connection to Band."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Agent-ID": self.agent_id,
        }

        # websockets 15+ uses additional_headers instead of extra_headers.
        # Use the modern parameter to keep the client compatible with current versions.
        self.ws = await websockets.connect(BAND_WS_URL, additional_headers=headers)
        print(f"[{self.agent_name}] Connected to Band ✔")

        # Send join/auth handshake expected by Band
        await self._send_raw({
            "type": "agent_auth",
            "agent_id": self.agent_id,
            "api_key": self.api_key,
        })

    async def disconnect(self):
        if self.ws:
            await self.ws.close()
            print(f"[{self.agent_name}] Disconnected from Band")

    # ------------------------------------------------------------------
    # Room management
    # ------------------------------------------------------------------
    async def join_room(self, room_id: str):
        """Join a Band chatroom by its ID."""
        self.room_id = room_id
        await self._send_raw({
            "type":    "join_room",
            "room_id": room_id,
        })
        print(f"[{self.agent_name}] Joined room: {room_id}")

    async def create_room(self, room_name: str) -> str:
        """
        Create a new Band room and return its ID.
        In real Band SDK this returns the room_id from the server.
        Here we derive a deterministic ID for the demo.
        """
        room_id = f"room-{room_name.lower().replace(' ', '-')}-{self.agent_id[:6]}"
        await self._send_raw({
            "type":      "create_room",
            "room_name": room_name,
            "room_id":   room_id,
        })
        self.room_id = room_id
        print(f"[{self.agent_name}] Created room: {room_name} (id={room_id})")
        return room_id

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------
    async def send_message(self, text: str, room_id: str = None):
        """Send a chat message to a Band room."""
        target_room = room_id or self.room_id
        if not target_room:
            raise ValueError("No room_id set — call join_room() first.")
        payload = {
            "type":       "send_message",
            "room_id":    target_room,
            "agent_id":   self.agent_id,
            "agent_name": self.agent_name,
            "content":    text,
        }
        await self._send_raw(payload)
        print(f"[{self.agent_name}] → {text[:120]}")

    async def send_structured(self, data: dict, room_id: str = None):
        """Send a JSON-serialised structured payload (for agent-to-agent handoffs)."""
        await self.send_message(f"__STRUCTURED__:{json.dumps(data)}", room_id)

    # ------------------------------------------------------------------
    # Listening
    # ------------------------------------------------------------------
    def on_message(self, callback):
        """Register an async callback: async def handler(agent_name, text, data)."""
        self._listeners.append(callback)

    async def listen(self):
        """
        Blocking loop — reads messages from Band WebSocket and
        dispatches them to registered callbacks.
        """
        async for raw in self.ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") != "message":
                continue

            sender = msg.get("agent_name", "unknown")
            content = msg.get("content", "")

            # Parse structured payloads
            if content.startswith("__STRUCTURED__:"):
                try:
                    data = json.loads(content[len("__STRUCTURED__:"):])
                except Exception:
                    data = {}
            else:
                data = {}

            for cb in self._listeners:
                await cb(sender=sender, text=content, data=data, raw=msg)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _send_raw(self, payload: dict):
        if self.ws:
            await self.ws.send(json.dumps(payload))
