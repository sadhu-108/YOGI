"""Operational exceptions for external market data providers."""


class DataProviderError(RuntimeError):
    """Base exception for external market data provider communication and operational failures."""
    pass


class DataProviderAuthenticationError(DataProviderError, ValueError):
    """Raised when data provider credentials, API keys, or session tokens are invalid or expired."""
    pass
