"""Generic capability registry for mapping stable keys to contract implementations."""

from typing import Callable, Generic, Mapping, Optional, Sequence, TypeVar

T = TypeVar("T")


class RegistryError(Exception):
    """Base exception for all registry operations."""
    pass


class DuplicateRegistrationError(RegistryError):
    """Raised when attempting to register an implementation under an already registered key."""
    pass


class RegistrationNotFoundError(RegistryError, KeyError):
    """Raised when attempting to retrieve an implementation for an unregistered key."""
    pass


class CapabilityRegistry(Generic[T]):
    """Type-safe registry managing implementations for a specific contract.

    Supports:
    - Direct instance registration
    - Lazy factory registration (instantiated only on first retrieval)
    - Key presence checking
    - Enumeration of registered keys
    - Bulk retrieval of all registered implementations
    """

    def __init__(
        self,
        capability_name: str,
        contract_type: Optional[type[T]] = None,
    ) -> None:
        self.capability_name = capability_name
        self.contract_type = contract_type
        self._instances: dict[str, T] = {}
        self._factories: dict[str, Callable[[], T]] = {}

    def register(self, key: str, instance: T, *, allow_override: bool = False) -> None:
        """Register an implementation instance under a unique key.

        Args:
            key: Unique key for the implementation.
            instance: Implementation instance satisfying contract_type.
            allow_override: If True, allow replacing an existing instance or factory under key.

        Raises:
            DuplicateRegistrationError: If the key is already registered and allow_override is False.
            TypeError: If contract_type is set and instance does not satisfy it.
        """
        if not allow_override and self.has(key):
            raise DuplicateRegistrationError(
                f"Duplicate registration for key '{key}' in '{self.capability_name}' registry."
            )
        if self.contract_type is not None and not isinstance(instance, self.contract_type):
            raise TypeError(
                f"Instance registered under '{key}' must implement {self.contract_type.__name__}, "
                f"got {type(instance).__name__}."
            )
        if allow_override:
            self._factories.pop(key, None)
        self._instances[key] = instance

    def register_factory(
        self, key: str, factory: Callable[[], T], *, allow_override: bool = False
    ) -> None:
        """Register a lazy factory under a unique key.

        The factory is NOT invoked during registration; it is executed only when
        the key is first requested via get().

        Args:
            key: Unique key for the implementation.
            factory: Callable returning an instance satisfying contract_type.
            allow_override: If True, allow replacing an existing instance or factory under key.

        Raises:
            DuplicateRegistrationError: If the key is already registered and allow_override is False.
            TypeError: If factory is not callable.
        """
        if not allow_override and self.has(key):
            raise DuplicateRegistrationError(
                f"Duplicate registration for key '{key}' in '{self.capability_name}' registry."
            )
        if not callable(factory):
            raise TypeError(f"Factory for key '{key}' must be callable.")
        if allow_override:
            self._instances.pop(key, None)
        self._factories[key] = factory

    def override(self, key: str, instance: T) -> None:
        """Explicitly override or replace an existing registration or factory with an instance."""
        self.register(key, instance, allow_override=True)

    def override_factory(self, key: str, factory: Callable[[], T]) -> None:
        """Explicitly override or replace an existing registration or factory with a new factory."""
        self.register_factory(key, factory, allow_override=True)

    def unregister(self, key: str) -> None:
        """Remove a registered instance or factory if present."""
        self._instances.pop(key, None)
        self._factories.pop(key, None)

    def has(self, key: str) -> bool:
        """Return True if the key is registered (as an instance or factory)."""
        return key in self._instances or key in self._factories

    def get(self, key: str) -> T:
        """Retrieve the implementation for the specified key.

        If registered via a factory and not yet instantiated, the factory will be
        invoked and cached.

        Raises:
            RegistrationNotFoundError: If the key is not registered.
            TypeError: If the factory returns an object not satisfying contract_type.
        """
        if key in self._instances:
            return self._instances[key]

        if key in self._factories:
            instance = self._factories[key]()
            if self.contract_type is not None and not isinstance(instance, self.contract_type):
                raise TypeError(
                    f"Factory for '{key}' produced {type(instance).__name__}, "
                    f"expected {self.contract_type.__name__}."
                )
            self._instances[key] = instance
            return instance

        raise RegistrationNotFoundError(
            f"No implementation registered for key '{key}' in '{self.capability_name}' registry."
        )

    def list_keys(self) -> Sequence[str]:
        """Return a sorted sequence of all registered keys."""
        all_keys = set(self._instances.keys()) | set(self._factories.keys())
        return sorted(all_keys)

    def all(self) -> Mapping[str, T]:
        """Retrieve all registered implementations, instantiating any lazy factories."""
        return {key: self.get(key) for key in self.list_keys()}

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    def __getitem__(self, key: str) -> T:
        return self.get(key)

    def __len__(self) -> int:
        return len(self.list_keys())

    def __repr__(self) -> str:
        keys_str = ", ".join(f"'{k}'" for k in self.list_keys())
        return f"<CapabilityRegistry[{self.capability_name}]: [{keys_str}]>"
