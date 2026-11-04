# Política de seguridad

- **Secretos:** solo en variables de entorno o en el gestor de secretos del proveedor cloud. `.env` está excluido de Git.
- **Si un secreto se filtra:** revocarlo de inmediato en el proveedor, generar uno nuevo y registrar el incidente. Borrar el commit no basta.
- **Autonomía controlada:** los agentes no ejecutan comandos del sistema. Las herramientas destructivas o externas requieren aprobación humana.
- **Gasto:** los proveedores de pago están deshabilitados por defecto (`OFFICE_ALLOW_PAID_PROVIDERS=false`).
- **Datos en proveedores gratuitos de IA:** no enviar datos personales, credenciales ni información confidencial; algunos niveles gratuitos pueden usar el contenido para mejorar sus productos.
- **Reportes:** abrir un issue privado o contactar directamente al responsable del repositorio.
