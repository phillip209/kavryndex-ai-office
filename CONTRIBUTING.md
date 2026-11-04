# Estándares de desarrollo

## Flujo Git

- `main` es la rama protegida: **solo** recibe cambios por Pull Request aprobado por el director.
- Nombres de rama: `feat/…`, `fix/…`, `docs/…`, `chore/…`, `refactor/…`, `test/…`.
- Commits con [Conventional Commits](https://www.conventionalcommits.org/es/): `feat(tasks): soportar dependencias`.
- Un PR = un objetivo. Cada PR incluye: archivos modificados, pruebas ejecutadas, resultados, problemas y próximos pasos (ver plantilla).
- Nunca se reescribe historia publicada (`push --force`) en ramas compartidas.

## Código

- Python ≥ 3.12, tipado en todas las funciones públicas.
- `ruff check .` y `ruff format --check .` sin errores.
- `mypy src` sin errores.
- `pytest` en verde con cobertura ≥ 85 %.
- El núcleo **no importa SDKs de proveedores IA**: solo `providers/base.py`.
- Todo cambio de modelo incluye su migración Alembic revisada; `pytest` falla si divergen.
- Las pruebas **no usan red ni gastan dinero**: proveedor `mock` o transportes HTTP simulados.

## Decisiones de arquitectura

Toda decisión relevante se registra como ADR en `docs/adr/NNNN-titulo.md` (contexto, decisión, consecuencias).

## Secretos

- Nunca subir `.env`, claves, tokens ni contraseñas. Usar `.env.example` con valores vacíos.
- Los secretos se leen solo de variables de entorno y se tipan como `SecretStr`.
