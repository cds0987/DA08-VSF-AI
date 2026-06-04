import asyncio
from dataclasses import dataclass

from app.infrastructure.auth.auth_service import AuthenticatedUser


@dataclass
class SSEConnection:
    user: AuthenticatedUser
    queue: asyncio.Queue[dict]


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[SSEConnection]] = {}

    async def connect(self, user: AuthenticatedUser) -> SSEConnection:
        connection = SSEConnection(user=user, queue=asyncio.Queue())
        self._connections.setdefault(user.id, []).append(connection)
        return connection

    async def disconnect(self, connection: SSEConnection) -> None:
        connections = self._connections.get(connection.user.id, [])
        self._connections[connection.user.id] = [item for item in connections if item is not connection]
        if not self._connections[connection.user.id]:
            self._connections.pop(connection.user.id, None)

    async def push_to_user(self, user_id: str, payload: dict) -> None:
        for connection in self._connections.get(user_id, []):
            await connection.queue.put(payload)

    def online_users(self) -> list[AuthenticatedUser]:
        users: dict[str, AuthenticatedUser] = {}
        for connections in self._connections.values():
            for connection in connections:
                users[connection.user.id] = connection.user
        return list(users.values())

    def reset(self) -> None:
        self._connections.clear()
