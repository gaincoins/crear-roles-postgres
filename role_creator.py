import asyncio
import asyncpg
import os
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        raise ImportError(
            "Se requiere 'tomli' en Python < 3.11. Instálalo con: pip install tomli"
        )

load_dotenv()


class PostgreSQLRoleCreator:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str = "postgres",
        target_databases: Optional[List[str]] = None,
        config_path: str = "roles_config.toml",
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.target_databases = target_databases or []
        self.connection = None

        with open(config_path, "rb") as f:
            self.config = tomllib.load(f)

    # -------------------------------------------------------------------------
    # Conexión
    # -------------------------------------------------------------------------

    async def connect(self):
        self.connection = await asyncpg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
        )
        print(f"Conectado a PostgreSQL en {self.host}:{self.port}")

    async def disconnect(self):
        if self.connection:
            await self.connection.close()
            print("Conexión cerrada")

    # -------------------------------------------------------------------------
    # Ejecución de consultas
    # -------------------------------------------------------------------------

    async def execute(self, query: str, *args):
        if not self.connection:
            raise RuntimeError("No hay conexión activa")
        try:
            await self.connection.execute(query, *args)
            return True
        except asyncpg.exceptions.DuplicateObjectError:
            print("  ⚠ El objeto ya existe")
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

    # -------------------------------------------------------------------------
    # Constructores de SQL (leen plantillas del archivo TOML)
    # -------------------------------------------------------------------------

    @staticmethod
    def _qi(identifier: str) -> str:
        """Envuelve un identificador simple en comillas dobles (case-safe para PostgreSQL)."""
        return f'"{identifier}"'

    def _create_role_sql(self, role_name: str) -> str:
        return self.config["sql"]["create_role"].format(role_name=role_name)

    def _grant_sql(self, privilege: str, to_role: str, admin_option: bool = False) -> str:
        """Construye GRANT. 'privilege' puede ser un identificador simple o una cláusula
        compuesta (e.g. 'CONNECT ON DATABASE "mydb"'); 'to_role' siempre es un rol."""
        admin_clause = " WITH ADMIN OPTION" if admin_option else ""
        return self.config["sql"]["grant_role"].format(
            privilege=privilege,
            to_role=self._qi(to_role),
            admin_clause=admin_clause,
        )

    def _revoke_sql(self, privilege: str, from_role: str) -> str:
        return self.config["sql"]["revoke_role"].format(
            privilege=privilege,
            from_role=self._qi(from_role),
        )

    # -------------------------------------------------------------------------
    # Roles globales
    # -------------------------------------------------------------------------

    async def create_global_roles(self):
        print("\n" + "=" * 60)
        print("CREANDO ROLES GLOBALES")
        print("=" * 60)

        for role_def in self.config["roles"]["global"]:
            name = role_def["name"]
            print(f"\nCreando {name}...")
            await self.execute(self._create_role_sql(name))
            for grant in role_def.get("grants", []):
                print(f"  Grant {grant} a {name}...")
                await self.execute(self._grant_sql(self._qi(grant), name))

        for grant_def in self.config["roles"]["global_post_grants"]:
            privilege    = grant_def["privilege"]
            to_role      = grant_def["to_role"]
            admin_option = grant_def.get("admin_option", False)
            print(f"\n  Grant {privilege} a {to_role}...")
            await self.execute(self._grant_sql(self._qi(privilege), to_role, admin_option))

        print("\n✓ Roles globales creados exitosamente")

    # -------------------------------------------------------------------------
    # Bases de datos y esquemas
    # -------------------------------------------------------------------------

    async def get_databases(self) -> List[Dict[str, str]]:
        print("\n" + "=" * 60)
        print("OBTENIENDO BASES DE DATOS")
        print("=" * 60)

        databases = await self.fetch(self.config["sql"]["list_databases"])

        if self.target_databases:
            databases = [
                db for db in databases
                if db["nombre_base_datos"] in self.target_databases
            ]
            print(f"\nFiltro aplicado: {len(self.target_databases)} DB(s) especificadas")

        print(f"\nBases de datos a procesar: {len(databases)}")
        for db in databases:
            print(f"  - {db['nombre_base_datos']} (owner: {db['owner']})")

        return databases

    async def _get_schemas(self, connection) -> List[str]:
        records = await connection.fetch(self.config["sql"]["list_schemas"])
        return [row["schema_name"] for row in records]

    # -------------------------------------------------------------------------
    # Procesamiento por base de datos (genérico — lee [[db_roles]] del TOML)
    # -------------------------------------------------------------------------

    async def _process_database(self, db_name: str, owner: str):
        print(f"\nProcesando base de datos: {db_name}")
        print("-" * 60)

        conn = None
        try:
            conn = await asyncpg.connect(
                host=self.host, port=self.port,
                user=self.user, password=self.password,
                database=db_name,
            )

            # Grant temporal del owner al usuario de conexión
            print(f"  Grant {owner} TO {self.user} (temporal)...")
            await conn.execute(self._grant_sql(self._qi(owner), self.user))

            schemas = await self._get_schemas(conn) or ["public"]
            print(f"\n  Base de datos: {db_name}")
            print(f"  Owner:         {owner}")
            print(f"  Esquemas:      {', '.join(schemas)}")

            normalized = db_name.replace("-", "_").lower()

            # Iterar sobre cada plantilla de rol definida en el TOML
            for role_def in self.config["db_roles"]:
                role_name = role_def["name_pattern"].format(db=normalized)
                print(f"\n  Creando {role_name}...")
                await conn.execute(self._create_role_sql(role_name))

                # Herencia del owner original de la BD
                if role_def.get("inherit_db_owner"):
                    await conn.execute(self._grant_sql(self._qi(owner), role_name))

                # CONNECT en la base de datos
                if role_def.get("connect"):
                    await conn.execute(
                        self._grant_sql(f'CONNECT ON DATABASE {self._qi(db_name)}', role_name)
                    )

                # Privilegios por esquema y tipo de objeto
                for schema in schemas:
                    if role_def.get("schema_usage"):
                        await conn.execute(
                            self._grant_sql(f'USAGE ON SCHEMA {self._qi(schema)}', role_name)
                        )

                    for obj_priv in role_def.get("object_privileges", []):
                        obj_type   = obj_priv["object_type"]
                        privileges = obj_priv["privileges"]

                        # GRANT ... ON ALL {object_type} IN SCHEMA ...
                        await conn.execute(
                            self.config["sql"]["grant_on_all"].format(
                                privileges=privileges, object_type=obj_type,
                                schema=schema, role=role_name
                            )
                        )

                        # ALTER DEFAULT PRIVILEGES (si aplica)
                        if obj_priv.get("default_privileges"):
                            await conn.execute(
                                self.config["sql"]["default_privs"].format(
                                    privileges=privileges, object_type=obj_type,
                                    schema=schema, role=role_name
                                )
                            )

                # Membresías (grants_to)
                for membership in role_def.get("grants_to", []):
                    await conn.execute(
                        self._grant_sql(
                            self._qi(role_name),
                            membership["role"],
                            admin_option=membership.get("admin_option", False),
                        )
                    )

            print(f"\n  ✓ Roles creados para {db_name}")

        except Exception as e:
            print(f"  ✗ Error procesando {db_name}: {e}")

        finally:
            if conn:
                try:
                    print(f"  Revoke {owner} FROM {self.user}...")
                    await conn.execute(self._revoke_sql(self._qi(owner), self.user))
                except Exception as e:
                    print(f"  ⚠ Error al revocar permisos: {e}")
                await conn.close()

    # -------------------------------------------------------------------------
    # Punto de entrada principal
    # -------------------------------------------------------------------------

    async def run(self):
        try:
            await self.connect()
            await self.create_global_roles()

            databases = await self.get_databases()
            for db in databases:
                await self._process_database(db["nombre_base_datos"], db["owner"])

            print("\n" + "=" * 60)
            print("PROCESO COMPLETADO EXITOSAMENTE")
            print("=" * 60)

        except Exception as e:
            print(f"\n✗ Error crítico: {e}")
            raise
        finally:
            await self.disconnect()


# =============================================================================
# Entrada principal
# =============================================================================

async def main():
    host        = os.getenv("PGHOST",     "localhost")
    port        = int(os.getenv("PGPORT", "5432"))
    user        = os.getenv("PGUSER",     "postgres")
    password    = os.getenv("PGPASSWORD", "postgres")
    database    = os.getenv("PGDATABASE", "postgres")
    config_path = os.getenv("ROLES_CONFIG", "roles_config.toml")

    target_databases_env = os.getenv("PG_TARGET_DATABASES", "")
    target_databases = (
        [db.strip() for db in target_databases_env.split(",") if db.strip()]
        if target_databases_env else None
    )

    print("=" * 60)
    print("CREACIÓN DE ROLES POSTGRESQL")
    print("=" * 60)
    print(f"\nConectando a:          {host}:{port}")
    print(f"Usuario:               {user}")
    print(f"Base de datos inicial: {database}")
    print(f"Configuración:         {config_path}")
    if target_databases:
        print(f"Bases de datos objetivo: {', '.join(target_databases)}")
    else:
        print("Bases de datos objetivo: TODAS (no se especificó PG_TARGET_DATABASES)")

    creator = PostgreSQLRoleCreator(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        target_databases=target_databases,
        config_path=config_path,
    )
    await creator.run()


if __name__ == "__main__":
    asyncio.run(main())
