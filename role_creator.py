import asyncio
import asyncpg
import os
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

load_dotenv()


class PostgreSQLRoleCreator:
    def __init__(self, host: str, port: int, user: str, password: str, database: str = "postgres", target_databases: Optional[List[str]] = None):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.target_databases = target_databases or []
        self.connection = None

    async def connect(self):
        self.connection = await asyncpg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database
        )
        print(f"Conectado a PostgreSQL en {self.host}:{self.port}")

    async def disconnect(self):
        if self.connection:
            await self.connection.close()
            print("Conexión cerrada")

    async def execute(self, query: str, *args):
        if not self.connection:
            raise RuntimeError("No hay conexión activa")
        try:
            await self.connection.execute(query, *args)
            return True
        except asyncpg.exceptions.DuplicateObjectError:
            print(f"  ⚠ El objeto ya existe")
            return False
        except Exception as e:
            print(f"  ✗ Error: {e}")
            return False

    async def fetch(self, query: str, *args) -> List[Dict[str, Any]]:
        if not self.connection:
            raise RuntimeError("No hay conexión activa")
        try:
            return await self.connection.fetch(query, *args)
        except Exception as e:
            print(f"  ✗ Error en consulta: {e}")
            return []

    def _do_block(self, action: str, condition: str = None) -> str:
        """Genera un bloque DO seguro."""
        if condition:
            return f"""
            DO $$
            BEGIN
                IF {condition} THEN
                    {action}
                END IF;
            END $$;
            """
        return f"""
        DO $$
        BEGIN
            {action}
        END $$;
        """

    def _create_role_sql(self, role_name: str) -> str:
        return self._do_block(
            f"""CREATE ROLE {role_name} WITH
                    INHERIT
                    NOLOGIN
                    CONNECTION LIMIT 0;""",
            f"NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_name}')"
        )

    def _grant_sql(self, privilege: str, to_role: str, condition: str = None, admin_option: bool = False) -> str:
        default_condition = f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{to_role}')"
        if condition:
            default_condition += f" AND {condition}"
        admin_clause = " WITH ADMIN OPTION" if admin_option else ""
        return self._do_block(f"GRANT {privilege} TO {to_role}{admin_clause};", default_condition)

    def _revoke_sql(self, privilege: str, from_role: str, condition: str = None) -> str:
        default_condition = f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{from_role}')"
        if condition:
            default_condition += f" AND {condition}"
        return self._do_block(f"REVOKE {privilege} FROM {from_role};", default_condition)

    async def create_global_roles(self):
        print("\n" + "=" * 60)
        print("CREANDO ROLES GLOBALES")
        print("=" * 60)

        roles = [
            ("role_dba", []),
            ("role_monitoring", ["pg_signal_backend"]),
        ]

        for role, grants in roles:
            print(f"\nCreando {role}...")
            await self.execute(self._create_role_sql(role))
            for grant in grants:
                print(f"  Grant {grant} a {role}...")
                await self.execute(self._grant_sql(grant, role))

        print("\n  Grant postgres a role_dba...")
        await self.execute(self._grant_sql("postgres", "role_dba", admin_option=True))

        print("  Grant role_monitoring a role_dba...")
        await self.execute(self._grant_sql(
            "role_monitoring",
            "role_dba",
            "EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'role_monitoring')",
            admin_option=True
        ))

        print("\n✓ Roles globales creados exitosamente")

    async def get_databases(self) -> List[Dict[str, str]]:
        query = """
        SELECT d.datname AS nombre_base_datos, r.rolname AS owner
        FROM pg_database d
        JOIN pg_roles r ON d.datdba = r.oid
        WHERE d.datname NOT IN ('postgres', 'template0', 'template1','cloudsqladmin')
          AND d.datistemplate = false
        ORDER BY d.datname;
        """
        print("\n" + "=" * 60)
        print("OBTENIENDO BASES DE DATOS")
        print("=" * 60)

        databases = await self.fetch(query)

        # Filtrar por bases de datos objetivo si se especificaron
        if self.target_databases:
            databases = [db for db in databases if db['nombre_base_datos'] in self.target_databases]
            print(f"\nFiltro aplicado: {len(self.target_databases)} DB(s) especificadas")

        print(f"\nBases de datos a procesar: {len(databases)}")
        for db in databases:
            print(f"  - {db['nombre_base_datos']} (owner: {db['owner']})")

        return databases

    async def _get_schemas(self, connection) -> List[str]:
        query = """
        SELECT schema_name FROM information_schema.schemata
        WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
          AND schema_name NOT LIKE 'pg_%'
        ORDER BY schema_name;
        """
        records = await connection.fetch(query)
        return [row['schema_name'] for row in records]

    async def _create_db_role(self, conn, name: str):
        print(f"  Creando {name}...")
        await conn.execute(self._create_role_sql(name))

    async def _grant_owner_to_connection_user(self, conn, owner: str):
        """Grant del owner de la base de datos al usuario de conexión."""
        print(f"  Grant {owner} TO {self.user} (temporal)...")
        await conn.execute(self._grant_sql(owner, self.user))

    async def _revoke_owner_from_connection_user(self, conn, owner: str):
        """Revoke del owner de la base de datos al usuario de conexión."""
        print(f"  Revoke {owner} FROM {self.user}...")
        await conn.execute(self._revoke_sql(owner, self.user))

    async def _process_database(self, db_name: str, owner: str):
        print(f"\nProcesando base de datos: {db_name}")
        print("-" * 60)

        conn = None
        try:
            conn = await asyncpg.connect(
                host=self.host, port=self.port, user=self.user,
                password=self.password, database=db_name
            )

            # Grant temporal del owner al usuario de conexión
            await self._grant_owner_to_connection_user(conn, owner)

            schemas = await self._get_schemas(conn) or ['public']
            print(f"\n  Base de datos: {db_name}")
            print(f"  Owner: {owner}")
            print(f"  Esquemas: {', '.join(schemas)}")

            normalized = db_name.replace('-', '_').lower()
            role_owner = f"role_owner_{normalized}"
            role_writer = f"role_writer_{normalized}"
            role_reader = f"role_reader_{normalized}"

            # Owner role
            await self._create_db_role(conn, role_owner)
            await conn.execute(self._grant_sql(owner, role_owner))
            await conn.execute(self._grant_sql(role_owner, "role_dba",
                f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_owner}')", admin_option=True))
            await conn.execute(self._grant_sql(f"{role_owner}", "role_monitoring",
                f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_owner}')"))

            # Writer role
            await self._create_db_role(conn, role_writer)
            await conn.execute(self._grant_sql(f"CONNECT ON DATABASE {db_name}", role_writer))

            for schema in schemas:
                await conn.execute(self._grant_sql(f"USAGE ON SCHEMA {schema}", role_writer))
                await conn.execute(self._grant_sql(
                    f"SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema}", role_writer))
                await conn.execute(self._do_block(f"""
                    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema}
                    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role_writer};""",
                    f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_writer}')"))
                await conn.execute(self._grant_sql(f"USAGE ON ALL SEQUENCES IN SCHEMA {schema}", role_writer))
                await conn.execute(self._do_block(f"""
                    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema}
                    GRANT USAGE ON SEQUENCES TO {role_writer};""",
                    f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_writer}')"))

            await conn.execute(self._grant_sql(f"{role_writer}", role_owner,
                f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_writer}')"))
            await conn.execute(self._grant_sql(role_writer, "role_dba",
                f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_writer}')", admin_option=True))

            # Reader role
            await self._create_db_role(conn, role_reader)
            await conn.execute(self._grant_sql(f"CONNECT ON DATABASE {db_name}", role_reader))

            for schema in schemas:
                await conn.execute(self._grant_sql(f"USAGE ON SCHEMA {schema}", role_reader))
                await conn.execute(self._grant_sql(f"SELECT ON ALL TABLES IN SCHEMA {schema}", role_reader))
                await conn.execute(self._do_block(f"""
                    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema}
                    GRANT SELECT ON TABLES TO {role_reader};""",
                    f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_reader}')"))
                await conn.execute(self._grant_sql(f"USAGE ON ALL SEQUENCES IN SCHEMA {schema}", role_reader))
                await conn.execute(self._do_block(f"""
                    ALTER DEFAULT PRIVILEGES IN SCHEMA {schema}
                    GRANT USAGE ON SEQUENCES TO {role_reader};""",
                    f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_reader}')"))

            await conn.execute(self._grant_sql(f"{role_reader}", role_writer,
                f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_reader}')"))
            await conn.execute(self._grant_sql(role_reader, "role_dba",
                f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_reader}')", admin_option=True))

            print(f"  ✓ Roles creados para {db_name}")

        except Exception as e:
            print(f"  ✗ Error procesando {db_name}: {e}")

        finally:
            # Revoke del grant temporal al finalizar (siempre se ejecuta)
            if conn:
                try:
                    await self._revoke_owner_from_connection_user(conn, owner)
                except Exception as e:
                    print(f"  ⚠ Error al revocar permisos: {e}")
                await conn.close()

    async def run(self):
        try:
            await self.connect()
            await self.create_global_roles()

            databases = await self.get_databases()
            for db in databases:
                await self._process_database(db['nombre_base_datos'], db['owner'])

            print("\n" + "=" * 60)
            print("PROCESO COMPLETADO EXITOSAMENTE")
            print("=" * 60)

        except Exception as e:
            print(f"\n✗ Error crítico: {e}")
            raise
        finally:
            await self.disconnect()


async def main():
    host = os.getenv("PGHOST", "localhost")
    port = int(os.getenv("PGPORT", "5432"))
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "postgres")
    database = os.getenv("PGDATABASE", "postgres")

    # Parsear bases de datos objetivo (separadas por coma)
    target_databases_env = os.getenv("PG_TARGET_DATABASES", "")
    target_databases = [db.strip() for db in target_databases_env.split(",") if db.strip()] if target_databases_env else None

    print("=" * 60)
    print("CREACIÓN DE ROLES POSTGRESQL")
    print("=" * 60)
    print(f"\nConectando a: {host}:{port}")
    print(f"Usuario: {user}")
    print(f"Base de datos inicial: {database}")
    if target_databases:
        print(f"Bases de datos objetivo: {', '.join(target_databases)}")
    else:
        print("Bases de datos objetivo: TODAS (no se especificó PG_TARGET_DATABASES)")

    creator = PostgreSQLRoleCreator(host=host, port=port, user=user,
                                    password=password, database=database,
                                    target_databases=target_databases)
    await creator.run()


if __name__ == "__main__":
    asyncio.run(main())
