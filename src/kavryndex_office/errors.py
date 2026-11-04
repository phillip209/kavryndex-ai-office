"""Errores de dominio, independientes de HTTP."""


class OfficeError(Exception):
    """Base de los errores de dominio."""


class NotFoundError(OfficeError):
    pass


class ConflictError(OfficeError):
    pass


class PermissionDeniedError(OfficeError):
    pass


class InvalidStateError(OfficeError):
    pass


class BudgetExceededError(OfficeError):
    pass


class ProviderError(OfficeError):
    """Fallo transitorio de un proveedor de IA (reintentable)."""
