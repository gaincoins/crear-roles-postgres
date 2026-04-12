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
crear-roles-postgres/
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

# Opcional: Ruta al archivo de configuración TOML (por defecto: roles_config.toml)
ROLES_CONFIG=roles_config.toml
```

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
default_privs = "ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT {privileges} ON {object_type} TO {role};"
```

> - `CREATE ROLE` duplicado → Python captura `DuplicateObjectError` y muestra `⚠ El objeto ya existe`.
> - `GRANT` duplicado → PostgreSQL lo ignora silenciosamente (idempotente nativo).

**Placeholders disponibles:**

| Placeholder | Descripción | Usado en |
|-------------|-------------|----------|
| `{role_name}` | Nombre del rol | `create_role` |
| `{privilege}` | Privilegio a otorgar/revocar | `grant_role`, `revoke_role` |
| `{to_role}` | Rol que recibe el permiso | `grant_role` |
| `{from_role}` | Rol al que se revoca el permiso | `revoke_role` |
| `{admin_clause}` | ` WITH ADMIN OPTION` o vacío | `grant_role` |
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
3. **Roles Globales**: Crea los roles de `[roles.global]`
4. **Post-Grants**: Ejecuta los grants de `[roles.global_post_grants]`
5. **Descubrimiento**: Obtiene lista de bases de datos
6. **Filtrado**: Aplica filtro `PG_TARGET_DATABASES` si está definido
7. **Por cada base de datos:**
   - Grant temporal del owner al usuario de conexión
   - **Para cada `[[db_roles]]` del TOML:**
     - Crea el rol (si ya existe, lo omite)
     - Si `inherit_db_owner`: GRANT del owner
     - Si `connect`: GRANT CONNECT ON DATABASE
     - Para cada esquema:
       - Si `schema_usage`: GRANT USAGE ON SCHEMA
       - Para cada `[[db_roles.object_privileges]]`:
         - GRANT privilegios ON ALL {object_type}
         - ALTER DEFAULT PRIVILEGES (si `default_privileges = true`)
     - Para cada `[[db_roles.grants_to]]`: GRANT al rol global
   - Revoke temporal del owner

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
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO role_writer_mi_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO role_writer_mi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO role_writer_mi_app;
GRANT role_writer_mi_app TO role_dba WITH ADMIN OPTION;

-- Reader role (object_privileges: TABLES + SEQUENCES)
CREATE ROLE role_reader_mi_app WITH INHERIT NOLOGIN CONNECTION LIMIT 0;
GRANT CONNECT ON DATABASE mi_app TO role_reader_mi_app;
GRANT USAGE ON SCHEMA public TO role_reader_mi_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO role_reader_mi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO role_reader_mi_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO role_reader_mi_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO role_reader_mi_app;
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
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO role_executor_mi_app;
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
