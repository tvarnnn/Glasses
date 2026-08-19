from datetime import datetime, timezone


class ConnectionTracker:
    """Tracks whether a single tower client (the iPhone) is currently connected."""

    def __init__(self) -> None:
        self._connected_since: datetime | None = None
        self.total_connections = 0
        self.total_disconnects = 0

    def client_connected(self) -> None:
        self._connected_since = datetime.now(timezone.utc)
        self.total_connections += 1

    def client_disconnected(self) -> None:
        self._connected_since = None
        self.total_disconnects += 1

    def is_client_connected(self) -> bool:
        return self._connected_since is not None

    @property
    def connected_since(self) -> datetime | None:
        return self._connected_since
