# Operación: respaldo y restauración

## Respaldo

```powershell
.\scripts\Backup-Stack.ps1
```

Crea `backups\<AAAAMMDD-HHMMSS>\` con:

- `database.sql`: volcado completo de MariaDB (`mariadb-dump --single-transaction --routines --triggers`). El volcado se genera dentro del contenedor, así la contraseña de root nunca aparece en la línea de comandos del host.
- `documents.tgz`: archivos subidos del volumen `compra-clara_documents`.

El respaldo **no incluye `.env`**. Guardar `.env` por separado, en un lugar seguro: sin él no se pueden reconstruir las credenciales. La carpeta `backups\` está excluida de git.

Programar el respaldo (por ejemplo, con el Programador de tareas de Windows) ejecutando el script desde la raíz del repositorio. Copiar `backups\` fuera de la máquina.

## Restauración

**Prueba segura (base separada, no toca la activa):**

```powershell
.\scripts\Restore-Stack.ps1 -BackupDir backups\<fecha> -TargetDatabase cc_restore_check
```

Luego verificar conteos y eliminar la base de prueba cuando termine.

**Restauración sobre la base activa** (borra los datos actuales; requiere confirmación explícita):

```powershell
.\scripts\Restore-Stack.ps1 -BackupDir backups\<fecha> -Confirm
.\scripts\Restore-Stack.ps1 -BackupDir backups\<fecha> -RestoreDocuments -Confirm
```

Tras restaurar, reiniciar servicios y ejecutar `.\scripts\Test-Stack.ps1`.

## Persistencia

Los datos viven en volúmenes con nombre (`compra-clara_db-data`, `compra-clara_documents`, `compra-clara_models`). Sobreviven a `docker compose restart` y a `up -d --build`. **Nunca ejecutar `docker compose down -v`**: elimina esos volúmenes.

## Evidencia de la prueba realizada

- Respaldo creado con éxito (`database.sql` de unos 157 KB).
- Restauración en `cc_restore_check`: 66 tablas; 12 usuarios, 5 expedientes, 51 eventos de auditoría y 8 proveedores, iguales a la base activa.
- Reinicio de `db`, `backend`, `worker` y `web`: datos íntegros y `Test-Stack` en OK.
- Base de prueba eliminada después de verificar.

Limitaciones: la restauración de documentos (`-RestoreDocuments`) no se probó porque el volumen de documentos no tenía archivos en el momento de la prueba. Antes de producción, probar también esa rama con documentos reales de prueba.
