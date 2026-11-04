# ADR 0002 — Esquema gestionado con migraciones Alembic

- **Estado:** propuesto
- **Fecha:** 2026-11-04

## Contexto

El MVP creaba las tablas con `create_all`, que no sabe modificar un esquema existente. Antes de guardar datos reales en PostgreSQL (cloud) hace falta evolucionar el esquema sin perder datos.

## Decisión

1. Alembic es la **única** vía para crear o cambiar tablas. Las migraciones viven en `src/kavryndex_office/migrations/` y se distribuyen con el paquete.
2. Convención de nombres de restricciones en `Base.metadata` para que las migraciones sean deterministas en SQLite y PostgreSQL.
3. `OFFICE_AUTO_MIGRATE=true` (por defecto) aplica migraciones al arrancar; con `false` la app se niega a arrancar si la base no está al día y se usa `kavryndex-office migrate`.
4. Una prueba automatizada garantiza que **modelos y migraciones no divergen** y que el `downgrade` completo funciona, en SQLite y en PostgreSQL (CI).

## Consecuencias

- (+) Cambios de esquema revisables en cada PR y reproducibles en cualquier entorno.
- (+) El plan gratuito (un único servicio) funciona sin pasos manuales.
- (−) Cada cambio de modelo exige generar y revisar una revisión (`alembic revision --autogenerate`).
