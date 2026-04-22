class PentAGIError(Exception):
    """Base exception for all PentAGI client errors."""


class ConfigError(PentAGIError):
    """Invalid or missing configuration values."""


class AuthError(PentAGIError):
    """Authentication or authorisation failure (HTTP 401/403)."""


class APIError(PentAGIError):
    """Non-auth HTTP error returned by the PentAGI API."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


class StreamError(PentAGIError):
    """WebSocket stream failed after all reconnect attempts."""


class ConnectionError(PentAGIError):
    """Network-level failure (DNS, TCP timeout, TLS error)."""
