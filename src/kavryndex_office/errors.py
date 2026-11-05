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


class ValidationFailedError(OfficeError):
    """Datos coherentes en forma pero inválidos para el dominio."""


class BudgetExceededError(OfficeError):
    pass


class ProviderError(OfficeError):
    """Fallo transitorio de un proveedor de IA (reintentable)."""


class TaskTimeoutError(OfficeError):
    """La ejecución superó su tiempo máximo (reintentable)."""
