# PostgreSQL Role Creator

Script en Python para la creación automatizada de roles y permisos en PostgreSQL, diseñado para gestionar múltiples bases de datos con un esquema de seguridad definido por configuración.

## Características

- **Motor genérico**: Los roles, privilegios y tipos de objeto se definen 100% en el archivo TOML
- **Roles globales**: `role_dba`, `role_monitoring` (configurables)
- **Roles por base de datos**: `role_owner_*`, `role_writer_*`, `role_reader_*` (extensibles)
- **Extensible**: Agregar un nuevo rol o tipo de objeto requiere solo editar `roles_config.toml`
- **Filtrado por bases de datos**: Procesa todas o solo las especificadas
- **Idempotente**: Puede ejecutarse múltiples veces sin errores
- **SQL directo**: Sin bloques `DO $$` ni lógica procedural

## Estructura del Proyecto

```
creación de roles/
├── role_creator.py       ← Motor genérico (no necesita modificarse)
├── roles_config.toml     ← Definición de roles, privilegios y plantillas SQL
├── .env                  ← Credenciales de conexión (no versionado)
├── .gitignore
└── README.md
```

## Requisitos

- **Python 3.11+** (usa `tomllib` de la biblioteca estándar)
- Si usas **Python < 3.11**, instala `tomli` adicionalmente

```bash
# Python >= 3.11
pip install asyncpg python-dotenv

# Python < 3.11 (requiere tomli como dependencia extra)
pip install asyncpg python-dotenv tomli
```

## Configuración

### Paso 1 — Variables de entorno

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

# Opcional: Roles EXTRA (además del owner de cada BD) sobre los que se
# ejecutará ALTER DEFAULT PRIVILEGES para cubrir objetos futuros.
# Roles separados por coma. Deben existir previamente en el servidor:
# si alguno NO existe, el script ABORTA antes de crear cualquier rol.
# Si no se define, solo se usa el owner de cada BD.
PG_DEFAULT_PRIV_ROLES=usr_conta,usr_mkt

# Opcional: Ruta al archivo de configuración TOML (por defecto: roles_config.toml)
ROLES_CONFIG=roles_config.toml
```

> **Validación temprana de `PG_DEFAULT_PRIV_ROLES`:** al iniciar, el script
> consulta `pg_roles` para confirmar que cada rol declarado exista. Si falta
> alguno, imprime la lista de roles inexistentes y aborta con `RuntimeError`
> **sin haber creado todavía ningún rol ni ejecutado ningún GRANT**. Esto
> evita aplicar cambios parciales cuando la variable está mal escrita.

### Paso 2 — Archivo de configuración TOML

El archivo `roles_config.toml` contiene **tres secciones principales**:

| Sección | Propósito |
|---------|-----------|
| `[sql]` | Plantillas SQL genéricas con placeholders `{variable}` |
| `[roles]` | Definición de roles globales y sus grants |
| `[[db_roles]]` | Plantillas de roles por base de datos (extensible) |

---

## Estructura del TOML

### Sección `[sql]` — Plantillas SQL

Todas las sentencias son SQL directo. Sin bloques `DO $$`.

```toml
[sql]
create_role   = "CREATE ROLE {role_name} WITH INHERIT NOLOGIN CONNECTION LIMIT 0;"
grant_role    = "GRANT {privilege} TO {to_role}{admin_clause};"
revoke_role   = "REVOKE {privilege} FROM {from_role};"
grant_on_all  = "GRANT {privileges} ON ALL {object_type} IN SCHEMA {schema} TO {role};"
default_privs = "ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA {schema} GRANT {privileges} ON {object_type} TO {role};"
list_databases = '''SELECT d.datname AS nombre_base_datos, r.rolname AS owner
                   FROM pg_database d JOIN pg_roles r ON d.datdba = r.oid
                   WHERE d.datname NOT IN ('postgres','template0','template1','cloudsqladmin')
                     AND d.datistemplate = false
                   ORDER BY d.datname;'''
list_schemas  = '''SELECT schema_name FROM information_schema.schemata
                   WHERE schema_name NOT IN ('pg_catalog','information_schema')
                     AND schema_name NOT LIKE 'pg_%'
                   ORDER BY schema_name;'''
```

> - `CREATE ROLE` duplicado → Python captura `DuplicateObjectError` y muestra `⚠ El objeto ya existe`.
> - `GRANT` duplicado → PostgreSQL lo ignora silenciosamente (idempotente nativo).
> - `list_databases` se ejecuta en la BD de conexión (`PGDATABASE`) y devuelve `nombre_base_datos` + `owner`.
> - `list_schemas` se ejecuta **dentro de cada BD procesada** y devuelve los esquemas de usuario (excluye `pg_*`, `information_schema`).

**Columnas devueltas por las plantillas de descubrimiento:**

| Plantilla | Columna | Tipo | Descripción |
|-----------|---------|------|-------------|
| `list_databases` | `nombre_base_datos` | string | Nombre de la BD de usuario |
| `list_databases` | `owner` | string | Rol propietario (`pg_database.datdba`) |
| `list_schemas`  | `schema_name` | string | Nombre del esquema en la BD actual |

**Placeholders disponibles:**

| Placeholder | Descripción | Usado en |
|-------------|-------------|----------|
| `{role_name}` | Nombre del rol | `create_role` |
| `{privilege}` | Privilegio a otorgar/revocar | `grant_role`, `revoke_role` |
| `{to_role}` | Rol que recibe el permiso | `grant_role` |
| `{from_role}` | Rol al que se revoca el permiso | `revoke_role` |
| `{admin_clause}` | ` WITH ADMIN OPTION` o vacío | `grant_role` |
| `{owner}` | Owner de la base de datos (para default privileges) | `default_privs` |
| `{privileges}` | Privilegios sobre objetos | `grant_on_all`, `default_privs` |
| `{object_type}` | Tipo de objeto PostgreSQL | `grant_on_all`, `default_privs` |
| `{schema}` | Nombre del esquema | `grant_on_all`, `default_privs` |
| `{role}` | Rol que recibe los privilegios | `grant_on_all`, `default_privs` |

### Sección `[roles]` — Roles globales

```toml
[roles]

[[roles.global]]
name   = "role_dba"
grants = []

[[roles.global]]
name   = "role_monitoring"
grants = ["pg_signal_backend"]

[[roles.global_post_grants]]
privilege    = "postgres"
to_role      = "role_dba"
admin_option = true

[[roles.global_post_grants]]
privilege    = "role_monitoring"
to_role      = "role_dba"
admin_option = true
```

### Sección `[[db_roles]]` — Roles por base de datos

Cada bloque `[[db_roles]]` define un tipo de rol que se crea por cada base de datos procesada.

**Propiedades del rol:**

| Propiedad | Tipo | Descripción |
|-----------|------|-------------|
| `name_pattern` | string | Nombre del rol. `{db}` se reemplaza por el nombre normalizado de la BD |
| `inherit_db_owner` | bool | Si `true`, recibe GRANT del owner original de la BD |
| `connect` | bool | Si `true`, recibe `GRANT CONNECT ON DATABASE` |
| `schema_usage` | bool | Si `true`, recibe `GRANT USAGE ON SCHEMA` en cada esquema |

**Privilegios por tipo de objeto (`[[db_roles.object_privileges]]`):**

| Propiedad | Tipo | Descripción |
|-----------|------|-------------|
| `object_type` | string | Tipo de objeto PostgreSQL: `TABLES`, `SEQUENCES`, `FUNCTIONS`, `ROUTINES`, `TYPES` |
| `privileges` | string | Privilegios a otorgar: `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `USAGE`, `EXECUTE`, etc. |
| `default_privileges` | bool | Si `true`, también ejecuta `ALTER DEFAULT PRIVILEGES` para objetos futuros |

**Membresías (`[[db_roles.grants_to]]`):**

| Propiedad | Tipo | Descripción |
|-----------|------|-------------|
| `role` | string | Rol global al que se asigna este rol |
| `admin_option` | bool | Si `true`, el grant incluye `WITH ADMIN OPTION` |

**Configuración actual (3 roles):**

```toml
# Owner: hereda el owner de la BD
[[db_roles]]
name_pattern     = "role_owner_{db}"
inherit_db_owner = true
connect          = false
schema_usage     = false

    [[db_roles.grants_to]]
    role         = "role_dba"
    admin_option = true

    [[db_roles.grants_to]]
    role         = "role_monitoring"


# Writer: CRUD sobre tablas + uso de secuencias
[[db_roles]]
name_pattern     = "role_writer_{db}"
connect          = true
schema_usage     = true

    [[db_roles.object_privileges]]
    object_type        = "TABLES"
    privileges         = "SELECT, INSERT, UPDATE, DELETE"
    default_privileges = true

    [[db_roles.object_privileges]]
    object_type        = "SEQUENCES"
    privileges         = "USAGE"
    default_privileges = true

    [[db_roles.grants_to]]
    role         = "role_dba"
    admin_option = true


# Reader: solo lectura sobre tablas + uso de secuencias
[[db_roles]]
name_pattern     = "role_reader_{db}"
connect          = true
schema_usage     = true

    [[db_roles.object_privileges]]
    object_type        = "TABLES"
    privileges         = "SELECT"
    default_privileges = true

    [[db_roles.object_privileges]]
    object_type        = "SEQUENCES"
    privileges         = "USAGE"
    default_privileges = true

    [[db_roles.grants_to]]
    role         = "role_dba"
    admin_option = true
```

---

## Uso

### Ejecutar con todas las bases de datos

```bash
python role_creator.py
```

### Ejecutar con bases de datos específicas

```bash
# Vía .env
PG_TARGET_DATABASES=mi_app,db_reportes

# Vía variable de entorno
export PG_TARGET_DATABASES="mi_app,db_reportes"
python role_creator.py
```

### Usar un archivo TOML personalizado

```bash
export ROLES_CONFIG="/ruta/a/mi_config.toml"
python role_creator.py
```

## Estructura de Roles

### Roles Globales

| Rol | Descripción | Permisos |
|-----|-------------|----------|
| `role_dba` | Administrador de bases de datos | Hereda todos los roles con ADMIN OPTION |
| `role_monitoring` | Monitoreo y diagnóstico | pg_signal_backend |

### Roles por Base de Datos

Para cada base de datos `mi_db` se crean (según la configuración actual):

| Rol | Descripción | Permisos |
|-----|-------------|----------|
| `role_owner_mi_db` | Propietario del esquema | Hereda owner original de la BD |
| `role_writer_mi_db` | Escritura de datos | CONNECT, USAGE, CRUD en tablas, USAGE en secuencias |
| `role_reader_mi_db` | Solo lectura | CONNECT, USAGE, SELECT en tablas, USAGE en secuencias |

### Jerarquía

Cada rol tiene sus privilegios asignados **explícitamente**. Solo el `role_dba` hereda todos los roles:

```
role_dba (gestiona todos los roles con ADMIN OPTION)
    ├── role_monitoring (pg_signal_backend)
    ├── role_owner_*    ← hereda owner original + monitoring
    ├── role_writer_*   ← CONNECT + CRUD explícito
    └── role_reader_*   ← CONNECT + SELECT explícito
```

## Proceso de Ejecución

1. **Carga del TOML**: Lee `roles_config.toml`
2. **Conexión**: Se conecta al servidor PostgreSQL
3. **Validación de `PG_DEFAULT_PRIV_ROLES`**: Si está definida, comprueba que todos los roles existan en el servidor. Si falta alguno → **aborta con `RuntimeError` antes de crear nada**
4. **Roles Globales**: Crea los roles de `[roles.global]`
5. **Post-Grants**: Ejecuta los grants de `[roles.global_post_grants]`
6. **Descubrimiento**: Obtiene lista de bases de datos (`list_databases`)
7. **Filtrado**: Aplica filtro `PG_TARGET_DATABASES` si está definido
8. **Por cada base de datos:**
   - Grant temporal del owner al usuario de conexión
   - Grant temporal adicional de cada rol en `PG_DEFAULT_PRIV_ROLES` (para poder emitir `ALTER DEFAULT PRIVILEGES FOR ROLE <rol>`)
   - **Para cada `[[db_roles]]` del TOML:**
     - Crea el rol (si ya existe, lo omite con `⚠`)
     - Si `inherit_db_owner`: GRANT del owner
     - Si `connect`: GRANT CONNECT ON DATABASE
     - Para cada esquema:
       - Si `schema_usage`: GRANT USAGE ON SCHEMA
       - Para cada `[[db_roles.object_privileges]]`:
         - GRANT privilegios ON ALL {object_type}
         - `ALTER DEFAULT PRIVILEGES` por cada rol efectivo (owner + `PG_DEFAULT_PRIV_ROLES`), si `default_privileges = true`
     - Para cada `[[db_roles.grants_to]]`: GRANT al rol global
   - Revoke temporal del owner y de los roles extra (en bloque `finally`, se ejecuta incluso ante errores)
9. **Generación del log**: Al finalizar, crea `scripts_{dbs}_{timestamp}.txt` con todas las sentencias ejecutadas (ver [Archivo de salida de scripts](#archivo-de-salida-de-scripts))

---
## Eliminación de roles

El script actual **no incluye funcionalidad automática para eliminar roles** por razones de seguridad. Eliminar un rol en PostgreSQL requiere verificar dependencias y seguir un proceso cuidadoso para evitar romper permisos o objetos dependientes.

### Validación de dependencias

Antes de intentar eliminar un rol, debe verificar si existen objetos que dependan de él utilizando la vista del sistema `pg_shdepend`:

```sql
SELECT 
    d.classid::regclass,
    pg_describe_object(d.classid, d.objid, d.objsubid) AS dependent_object
FROM pg_shdepend d
JOIN pg_roles r ON r.oid = d.refobjid
WHERE r.rolname = '<role_name>';
```

Este query mostrará qué tipos de objetos (tablas, funciones, etc.) dependen del rol especificado.

### Validación de privilegios por defecto

Además de verificar dependencias directas, debe comprobar si existen privilegios por defecto (default ACLs) asignados al rol que se pretende eliminar. Estos privilegios se aplican automáticamente a los nuevos objetos creados en ciertos esquemas y deben ser eliminados antes de dropping el rol.

```sql
SELECT
    defaclrole::regrole AS owner_role,
    defaclnamespace::regnamespace AS schema_name,
    defaclobjtype AS object_type,
    defaclacl
FROM pg_default_acl
WHERE defaclacl::text LIKE '%<role_name>%';
```

Este query mostrará si el rol tiene privilegios por defecto configurados en algún esquema. Si se encuentran resultados, debe revocar esos privilegios por defecto antes de proceder con la eliminación del rol utilizando:
```sql
ALTER DEFAULT PRIVILEGES IN SCHEMA <schema_name> REVOKE <privileges> ON <object_type> FROM <role_name>;
```

### Proceso seguro de eliminación

Para eliminar un rol creado por este script, siga estos pasos:

1. **Verificar dependencias**: Ejecute el query anterior para identificar objetos dependientes
2. **Revocar permisos explícitos**: Si el rol tiene permisos directos sobre objetos, revóquelos:
   ```sql
   REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM <role_name>;
   REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM <role_name>;
   -- Repetir para otros esquemas y tipos de objeto según sea necesario
   ```
3. **Eliminar membresías**: Revocar el rol de cualquier otro rol al que haya sido otorgado:
   ```sql
   REVOKE <role_name> FROM <grantee_role>;
   ```
4. **Eliminar el rol**: Finalmente, eliminar el rol:
   ```sql
   DROP ROLE <role_name>;
   ```

### Consideraciones importantes

- **Roles con `WITH ADMIN OPTION`**: Roles creados con `admin_option = true` permiten a sus miembros otorgar el rol a otros. Antes de eliminar dicho rol, asegúrese de que no haya sido otorgado a otros roles.
- **Jerarquía de roles**: En la configuración actual, `role_dba` hereda todos los demás roles con `ADMIN OPTION`. Eliminar un rol heredado por `role_dba` podría afectar sus permisos efectivos.
- **Roles por base de datos**: Los roles siguen el patrón `role_*_{db}` (ej: `role_writer_mi_app`). Asegúrese de especificar el nombre exacto al verificar y eliminar.
- **Transaccionalidad**: Si bien `DROP ROLE` es transaccional en PostgreSQL, los `REVOKE` previos lo son también, por lo que se recomienda ejecutar todo en una sola transacción si se automatiza el proceso.

### Ejemplo práctico

Para eliminar `role_writer_mi_app`:

```sql
-- 1. Verificar dependencias
SELECT 
    d.classid::regclass,
    pg_describe_object(d.classid, d.objid, d.objsubid) AS dependent_object
FROM pg_shdepend d
JOIN pg_roles r ON r.oid = d.refobjid
WHERE r.rolname = 'role_writer_mi_app';

-- 2. Si no hay dependencias críticas o se han gestionado, proceder con:
REVOKE role_writer_mi_app FROM role_dba;  -- Si fue otorgado con ADMIN OPTION
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM role_writer_mi_app;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM role_writer_mi_app;
DROP ROLE role_writer_mi_app;
```

## Archivo de salida de scripts

Tras una ejecución exitosa (o con errores parciales) el script genera automáticamente un archivo `.txt` en el directorio de trabajo con todas las sentencias SQL ejecutadas, útil para auditoría, versionado o reproducción manual.

**Nombre del archivo:**

```
scripts_{dbs}_{YYYYMMDD_HHMMSS}.txt
```

Donde `{dbs}` se forma así:
- Si se procesaron **más de 3 bases de datos** → `Ndbs` (ej: `7dbs`).
- Si se procesaron **3 o menos** → concatenación de los nombres normalizados con `_` (ej: `db_contabilidad_db_marketing`).

**Contenido (estructura por secciones):**

```text
-- =============================================================================
-- ROLES GLOBALES
-- =============================================================================
CREATE ROLE "role_dba" ...
GRANT "role_monitoring" TO "role_dba" WITH ADMIN OPTION;

-- =============================================================================
-- BASE DE DATOS: db_contabilidad
-- =============================================================================
CREATE ROLE "role_owner_db_contabilidad" ...;
GRANT "usr_conta" TO "role_owner_db_contabilidad";
...
```

Las sentencias que fallaron se incluyen igual, seguidas de un comentario:

```sql
CREATE ROLE "role_dba" ...;
-- ERROR: DuplicateObjectError: El objeto ya existe
```

Las sentencias que no se ejecutaron (por ejemplo, las de una BD que falló en mitad del proceso) **no aparecen** en el archivo.

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

Conectando a:          localhost:5432
Usuario:               postgres
Base de datos inicial: postgres
Configuración:         roles_config.toml
Bases de datos objetivo: db_contabilidad, db_marketing
Roles default privileges extra: usr_conta, usr_mkt

============================================================
CREANDO ROLES GLOBALES
============================================================

Creando role_dba...
Creando role_monitoring...
  Grant pg_signal_backend a role_monitoring...

  Grant postgres a role_dba...
  Grant role_monitoring a role_dba...

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

  Base de datos:   db_contabilidad
  Owner:           usr_conta
  Esquemas:        public

  Creando role_owner_db_contabilidad...
  Creando role_writer_db_contabilidad...
  Creando role_reader_db_contabilidad...

  ✓ Roles creados para db_contabilidad
  Revoke usr_conta FROM postgres...

============================================================
PROCESO COMPLETADO EXITOSAMENTE
============================================================
```

## Ejemplo SQL Generado

Para una base de datos `mi_app` con owner `postgres` y esquema `public`:

```sql
-- =============================================
-- ROLES GLOBALES
-- =============================================

CREATE ROLE role_dba WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
CREATE ROLE role_monitoring WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
GRANT pg_signal_backend TO role_monitoring;
GRANT postgres TO role_dba WITH ADMIN OPTION;
GRANT role_monitoring TO role_dba WITH ADMIN OPTION;

-- =============================================
-- ROLES POR BASE DE DATOS: mi_app
-- =============================================

-- Owner role (inherit_db_owner = true)
CREATE ROLE role_owner_mi_app WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
GRANT postgres TO role_owner_mi_app;
GRANT role_owner_mi_app TO role_dba WITH ADMIN OPTION;
GRANT role_owner_mi_app TO role_monitoring;

-- Writer role (object_privileges: TABLES + SEQUENCES)
CREATE ROLE role_writer_mi_app WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
GRANT CONNECT ON DATABASE mi_app TO role_writer_mi_app;
GRANT USAGE ON SCHEMA public TO role_writer_mi_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO role_writer_mi_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO role_writer_mi_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO role_writer_mi_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT USAGE ON SEQUENCES TO role_writer_mi_app;
GRANT role_writer_mi_app TO role_dba WITH ADMIN OPTION;

-- Reader role (object_privileges: TABLES + SEQUENCES)
CREATE ROLE role_reader_mi_app WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
GRANT CONNECT ON DATABASE mi_app TO role_reader_mi_app;
GRANT USAGE ON SCHEMA public TO role_reader_mi_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO role_reader_mi_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON TABLES TO role_reader_mi_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO role_reader_mi_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT USAGE ON SEQUENCES TO role_reader_mi_app;
GRANT role_reader_mi_app TO role_dba WITH ADMIN OPTION;
```

---

## Guía: Cómo agregar un nuevo rol

Para agregar un nuevo tipo de rol, solo edita `roles_config.toml`. **No es necesario modificar el código Python.**

### Ejemplo 1: Agregar `role_executor` (ejecución de funciones)

Agrega este bloque al final de `roles_config.toml`:

```toml
[[db_roles]]
name_pattern     = "role_executor_{db}"
connect          = true
schema_usage     = true

    [[db_roles.object_privileges]]
    object_type        = "FUNCTIONS"
    privileges         = "EXECUTE"
    default_privileges = true

    [[db_roles.grants_to]]
    role         = "role_dba"
    admin_option = true
```

**SQL que generará para la BD `mi_app`:**
```sql
CREATE ROLE role_executor_mi_app WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
GRANT CONNECT ON DATABASE mi_app TO role_executor_mi_app;
GRANT USAGE ON SCHEMA public TO role_executor_mi_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO role_executor_mi_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO role_executor_mi_app;
GRANT role_executor_mi_app TO role_dba WITH ADMIN OPTION;
```

### Ejemplo 2: Agregar ejecución de funciones al writer existente

Agrega un nuevo `[[db_roles.object_privileges]]` dentro del bloque del writer:

```toml
# Dentro del [[db_roles]] del writer, agregar:
    [[db_roles.object_privileges]]
    object_type        = "FUNCTIONS"
    privileges         = "EXECUTE"
    default_privileges = true
```

### Ejemplo 3: Agregar un rol global nuevo

```toml
# En la sección [roles]:
[[roles.global]]
name   = "role_auditor"
grants = ["pg_read_all_data"]

# Grant cruzado al DBA:
[[roles.global_post_grants]]
privilege    = "role_auditor"
to_role      = "role_dba"
admin_option = true
```

### Tipos de objeto soportados en PostgreSQL

| `object_type` | Privilegios comunes | Descripción |
|---|---|---|
| `TABLES` | `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER` | Tablas, vistas y vistas materializadas |
| `SEQUENCES` | `USAGE`, `SELECT`, `UPDATE` | Secuencias (autoincrement, seriales) |
| `FUNCTIONS` | `EXECUTE` | Funciones definidas por el usuario |
| `ROUTINES` | `EXECUTE` | Funciones + procedimientos (PG 11+) |
| `TYPES` | `USAGE` | Tipos de dato personalizados |

---

## Notas

- Los nombres de bases de datos con guiones se normalizan (ej: `mi-db` → `mi_db`)
- Se ignoran las bases de datos del sistema: `postgres`, `template0`, `template1`, `cloudsqladmin`
- El script es idempotente: puede ejecutarse múltiples veces sin errores
- Compatible con **Python 3.11+** (usa `tomllib` stdlib) y versiones anteriores (requiere `tomli`)
- Las vistas materializadas están cubiertas por `TABLES` para `GRANT`, pero `ALTER DEFAULT PRIVILEGES ON TABLES` solo aplica a tablas y vistas regulares (limitación de PostgreSQL)

## Licencia

MIT
