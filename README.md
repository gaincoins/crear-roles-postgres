# PostgreSQL Role Creator

Script en Python para la creación automatizada de roles y permisos en PostgreSQL, diseñado para gestionar múltiples bases de datos con un esquema de seguridad jerárquico.

## Características

- **Creación automática de roles globales**: `role_dba` y `role_monitoring`
- **Roles por base de datos**: `role_owner_*`, `role_writer_*`, `role_reader_*`
- **Gestión de permisos jerárquica**: DBA > Owner > Writer > Reader
- **Filtrado por bases de datos**: Procesa todas o solo las especificadas
- **Grant temporal automático**: Asigna y revoca permisos de forma segura
- **Manejo de errores**: Continúa procesando aunque falle una base de datos

## Requisitos

```bash
pip install asyncpg python-dotenv
```

## Configuración

Crea un archivo `.env` en el directorio del proyecto:

```env
# Conexión PostgreSQL
PGHOST=localhost
PGPORT=5432
PGUSER=postgres
PGPASSWORD=tu_password
PGDATABASE=postgres

# Opcional: Filtrar bases de datos (separadas por coma)
# Si no se especifica, procesa todas las DBs
PG_TARGET_DATABASES=db_contabilidad,db_marketing,dblog
```

## Uso

### Ejecutar con todas las bases de datos

```bash
python role_creator.py
```

### Ejecutar con bases de datos específicas

```bash
export PG_TARGET_DATABASES="mi_app,db_reportes"
python role_creator.py
```

## Estructura de Roles

### Roles Globales

| Rol | Descripción | Permisos |
|-----|-------------|----------|
| `role_dba` | Administrador de bases de datos | Hereda todos los roles con ADMIN OPTION |
| `role_monitoring` | Monitoreo y diagnóstico | pg_signal_backend, acceso de lectura |

### Roles por Base de Datos

Para cada base de datos `mi_db` se crean:

| Rol | Descripción | Permisos |
|-----|-------------|----------|
| `role_owner_mi_db` | Propietario del esquema | Hereda writer + permisos del owner original |
| `role_writer_mi_db` | Escritura de datos | CONNECT, USAGE, SELECT/INSERT/UPDATE/DELETE |
| `role_reader_mi_db` | Solo lectura | CONNECT, USAGE, SELECT |

## Jerarquía de Permisos

```
role_dba (ADMIN OPTION)
    ├── role_monitoring
    ├── role_owner_* (ADMIN OPTION)
    │   ├── role_writer_* (ADMIN OPTION)
    │   │   └── role_reader_*
    │   └── role_monitoring
    └── role_writer_* (ADMIN OPTION)
        └── role_reader_*
```

## Proceso de Ejecución

1. **Conexión**: Se conecta a PostgreSQL usando variables de entorno
2. **Roles Globales**: Crea `role_dba` y `role_monitoring` (si no existen)
3. **Descubrimiento**: Obtiene lista de bases de datos
4. **Filtrado**: Aplica filtro `PG_TARGET_DATABASES` si está definido
5. **Por cada base de datos**:
   - Grant temporal del owner al usuario de conexión
   - Crea roles owner/writer/reader
   - Asigna permisos sobre esquemas, tablas y secuencias
   - Configura privilegios por defecto (ALTER DEFAULT PRIVILEGES)
   - Revoke temporal (siempre se ejecuta)

## Permisos Detallados

### role_writer_*

- `CONNECT` en la base de datos
- `USAGE` en todos los esquemas
- `SELECT, INSERT, UPDATE, DELETE` en todas las tablas
- `USAGE` en todas las secuencias
- Default privileges para objetos futuros

### role_reader_*

- `CONNECT` en la base de datos
- `USAGE` en todos los esquemas
- `SELECT` en todas las tablas
- `USAGE` en todas las secuencias
- Default privileges para objetos futuros

## Seguridad

- Los grants al usuario de conexión son **temporales**
- Se revocan automáticamente al finalizar cada base de datos
- El bloque `finally` garantiza la limpieza incluso si hay errores
- Roles creados con `NOLOGIN` (no pueden conectarse directamente)

## Ejemplo de Salida

```
============================================================
CREACIÓN DE ROLES POSTGRESQL
============================================================

Conectando a: localhost:5432
Usuario: postgres
Base de datos inicial: postgres
Bases de datos objetivo: db_contabilidad, db_marketing

============================================================
CREANDO ROLES GLOBALES
============================================================

Creando role_dba...
Creando role_monitoring...
  Grant pg_signal_backend a role_monitoring...

✓ Roles globales creados exitosamente

============================================================
OBTENIENDO BASES DE DATOS
============================================================

Filtro aplicado: 2 DB(s) especificadas
Bases de datos a procesar: 2
  - db_contabilidad (owner: usr_conta)
  - db_marketing (owner: usr_mkt)

Procesando base de datos: db_contabilidad
------------------------------------------------------------
  Grant usr_conta TO postgres (temporal)...

  Base de datos: db_contabilidad
  Owner: usr_conta
  Esquemas: public
  Creando role_owner_db_contabilidad...
  ...
  ✓ Roles creados para db_contabilidad
  Revoke usr_conta FROM postgres...

============================================================
PROCESO COMPLETADO EXITOSAMENTE
============================================================
```

## Ejemplo SQL Generado

Para una base de datos `mi_app` con owner `postgres` y esquema `public`:

```sql
-- Roles Globales
CREATE ROLE role_dba WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
CREATE ROLE role_monitoring WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
GRANT pg_signal_backend TO role_monitoring;
GRANT postgres TO role_dba WITH ADMIN OPTION;
GRANT role_monitoring TO role_dba WITH ADMIN OPTION;

-- Roles para mi_app
CREATE ROLE role_owner_mi_app WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
GRANT postgres TO role_owner_mi_app;
GRANT role_owner_mi_app TO role_dba WITH ADMIN OPTION;
GRANT role_owner_mi_app TO role_monitoring;

CREATE ROLE role_writer_mi_app WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
GRANT CONNECT ON DATABASE mi_app TO role_writer_mi_app;
GRANT USAGE ON SCHEMA public TO role_writer_mi_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO role_writer_mi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO role_writer_mi_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO role_writer_mi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO role_writer_mi_app;
GRANT role_writer_mi_app TO role_owner_mi_app;
GRANT role_writer_mi_app TO role_dba WITH ADMIN OPTION;

CREATE ROLE role_reader_mi_app WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
GRANT CONNECT ON DATABASE mi_app TO role_reader_mi_app;
GRANT USAGE ON SCHEMA public TO role_reader_mi_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO role_reader_mi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO role_reader_mi_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO role_reader_mi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO role_reader_mi_app;
GRANT role_reader_mi_app TO role_writer_mi_app;
GRANT role_reader_mi_app TO role_dba WITH ADMIN OPTION;
```

## Notas

- Los nombres de bases de datos con guiones se normalizan (ej: `mi-db` → `mi_db`)
- Se ignoran las bases de datos del sistema: `postgres`, `template0`, `template1`, `cloudsqladmin`
- El script es idempotente: puede ejecutarse múltiples veces sin errores

## Licencia

MIT
