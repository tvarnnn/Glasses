from datetime import datetime, timezone


class ConnectionTracker:
    """Tracks whether a tower client (the iPhone) is currently connected.

    Counts connections rather than holding a single flag, for the same
    reason `CaptureRecorder` grew an owner: on a WiFi hiccup iOS reconnects
    in ~0.5 s while uvicorn takes 20-40 s to notice the old socket died,
    so a superseded connection's teardown runs LATE -- after the new one is
    already live. A boolean flag cleared by that teardown reports "no
    client" while a client is streaming.
    """

    def __init__(self) -> None:
        self._connected_since: datetime | None = None
        self._live = 0
        self.total_connections = 0
        self.total_disconnects = 0

    def client_connected(self) -> None:
        self._live += 1
        if self._connected_since is None:
            self._connected_since = datetime.now(timezone.utc)
        self.total_connections += 1

    def client_disconnected(self) -> None:
        # Never below zero: a teardown that runs twice must not make the
        # tracker owe a connection it never had.
        self._live = max(0, self._live - 1)
        if self._live == 0:
            self._connected_since = None
        self.total_disconnects += 1

    @property
    def live_connections(self) -> int:
        return self._live

    def is_client_connected(self) -> bool:
        return self._connected_since is not None

    @property
    def connected_since(self) -> datetime | None:
        return self._connected_since
