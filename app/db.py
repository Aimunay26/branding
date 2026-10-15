"""Persistencia en SQLite.

Las respuestas se guardan como un blob JSON en una columna de texto en vez de
normalizarlas en cien filas. Para este volumen es más que suficiente, y SQLite
sabe consultar dentro del JSON con json_extract() si algún día hace falta.

Dos decisiones que conviene entender antes de tocar nada aquí:

1. Cada conexión enciende `PRAGMA foreign_keys` a mano. SQLite lo trae APAGADO
   por compilación y es una opción POR CONEXIÓN: sin esa línea, todos los
   ON DELETE CASCADE de este esquema son decoración y borrar una cuenta dejaría
   sesiones y borradores detrás sin dar un solo error.

2. La fila de `borradores` es la fuente de verdad del cuestionario, no el
   localStorage del navegador. De ahí el bloqueo optimista por `version` y el
   contador `contar_contestadas()`, que SIEMPRE lo calcula el servidor: si el
   cliente pudiera mandar su propia cuenta, inflarla sería la forma de ganar
   cualquier conflicto entre dispositivos.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "datos"
RUTA_DB = DIR_DATOS / "branding.db"

# Versión del esquema, en PRAGMA user_version. Sube cuando cambie el DDL.
VERSION_ESQUEMA = 2

# Las cinco secciones del cuestionario. Vive aquí porque contar_contestadas()
# es el árbitro de conflictos y no puede depender de contenido/*.json.
SECCIONES = ("identidad", "arquetipos", "comunicacion", "visual", "acciones")

# Días por defecto de vida de una sesión y de retención de un anónimo inactivo.
DIAS_SESION = 365
DIAS_RETENCION_ANONIMOS = 30

ESQUEMA_V1 = """
CREATE TABLE IF NOT EXISTS informes (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  creado_en       TEXT NOT NULL,
  nombre          TEXT,
  email           TEXT,
  tipo_marca      TEXT,
  respuestas      TEXT NOT NULL,
  resultado       TEXT NOT NULL,
  recomendaciones TEXT
);
"""

# Sentencia a sentencia y en este orden. No se usa executescript() porque hace
# COMMIT implícito y partiría en trozos la transacción de la migración.
_MIGRACION_2: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS usuarios (
      id               INTEGER PRIMARY KEY AUTOINCREMENT,
      google_sub       TEXT UNIQUE,
      email            TEXT,
      email_verificado INTEGER NOT NULL DEFAULT 0,
      nombre           TEXT,
      foto_url         TEXT,
      anonimo          INTEGER NOT NULL DEFAULT 1,
      creado_en        TEXT NOT NULL,
      visto_en         TEXT NOT NULL,
      borrado_en       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_usuarios_email ON usuarios(email)",
    "CREATE INDEX IF NOT EXISTS ix_usuarios_visto ON usuarios(anonimo, visto_en)",
    """
    CREATE TABLE IF NOT EXISTS sesiones (
      id         TEXT PRIMARY KEY,
      usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
      creado_en  TEXT NOT NULL,
      visto_en   TEXT NOT NULL,
      expira_en  TEXT NOT NULL,
      ua_hash    TEXT,
      ip_trunc   TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_sesiones_usuario ON sesiones(usuario_id)",
    "CREATE INDEX IF NOT EXISTS ix_sesiones_expira  ON sesiones(expira_en)",
    """
    CREATE TABLE IF NOT EXISTS borradores (
      usuario_id     INTEGER PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
      respuestas     TEXT NOT NULL,
      paso           INTEGER NOT NULL DEFAULT 0,
      ultimo_id      TEXT,
      ronda          INTEGER NOT NULL DEFAULT 0,
      contestadas    INTEGER NOT NULL DEFAULT 0,
      version        INTEGER NOT NULL DEFAULT 1,
      informe_id     INTEGER REFERENCES informes(id) ON DELETE SET NULL,
      actualizado_en TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS borradores_descartados (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      usuario_id  INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
      respuestas  TEXT NOT NULL,
      paso        INTEGER,
      ronda       INTEGER,
      contestadas INTEGER,
      motivo      TEXT NOT NULL,
      creado_en   TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_descartados_usuario ON borradores_descartados(usuario_id, id DESC)",
    """
    CREATE TABLE IF NOT EXISTS eventos (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
      tipo       TEXT NOT NULL,
      clave      TEXT,
      valor      TEXT,
      creado_en  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_eventos_usuario ON eventos(usuario_id, id DESC)",
    "CREATE INDEX IF NOT EXISTS ix_eventos_tipo    ON eventos(tipo, creado_en)",
    # Los informes que ya existen se quedan con usuario_id NULL: NADIE los reclama
    # automáticamente. Cruzar informes.email con el email de Google regalaría el
    # informe a quien registrase ese correo. Si el dueño los quiere en su cuenta,
    # scripts/reclamar_informes.py, a mano y con confirmación escrita.
    "ALTER TABLE informes ADD COLUMN usuario_id     INTEGER REFERENCES usuarios(id) ON DELETE CASCADE",
    "ALTER TABLE informes ADD COLUMN token_acceso   TEXT",
    "ALTER TABLE informes ADD COLUMN publico        INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE informes ADD COLUMN clave_idem     TEXT",
    "ALTER TABLE informes ADD COLUMN ia_generada_en TEXT",
    "ALTER TABLE informes ADD COLUMN ia_intentos    INTEGER NOT NULL DEFAULT 0",
    "UPDATE informes SET token_acceso = lower(hex(randomblob(16))) WHERE token_acceso IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_informes_token   ON informes(token_acceso)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_informes_idem    ON informes(clave_idem) WHERE clave_idem IS NOT NULL",
    "CREATE INDEX        IF NOT EXISTS ix_informes_usuario ON informes(usuario_id, id DESC)",
)


class ConflictoVersion(Exception):
    """Dos dispositivos escribiendo el mismo borrador.

    Lleva el estado del servidor para que main.py pueda montar el 409 sin
    saber nada de sqlite3.
    """

    def __init__(self, servidor: dict[str, Any]):
        super().__init__("El borrador cambió en otro sitio")
        self.servidor = servidor


# ------------------------------------------------------------------ conexión

def _conectar() -> sqlite3.Connection:
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(RUTA_DB, timeout=15.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    # Por conexión y sin excepciones: sin esto la cascada no existe.
    con.execute("PRAGMA foreign_keys = ON")
    # Los 5 s por defecto se quedan cortos: el autoguardado mete ~130 escrituras
    # por usuario y los endpoints corren en un threadpool de 40 hilos.
    con.execute("PRAGMA busy_timeout = 15000")
    return con


@contextlib.contextmanager
def conexion(escritura: bool = False) -> Iterator[sqlite3.Connection]:
    """Transacción explícita que además CIERRA.

    El gestor de contexto de sqlite3.Connection hace COMMIT/ROLLBACK pero deja
    la conexión abierta, que es justo lo que hacía el código anterior cinco
    veces. BEGIN IMMEDIATE en las escrituras coge el bloqueo de escritura ya,
    en vez de descubrir a mitad de transacción que otro lo tiene.
    """
    con = _conectar()
    try:
        con.execute("BEGIN IMMEDIATE" if escritura else "BEGIN")
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def inicializar() -> None:
    con = _conectar()
    try:
        # WAL y VACUUM INTO no se pueden ejecutar dentro de una transacción.
        # WAL persiste en el fichero: se pone una vez y se queda.
        con.execute("PRAGMA journal_mode = WAL")
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version >= VERSION_ESQUEMA:
            return
        con.executescript(ESQUEMA_V1)
        copia = DIR_DATOS / f"branding-pre-v{VERSION_ESQUEMA}.db"
        if not copia.exists():
            # Copia consistente en caliente. Es el seguro de la migración.
            con.execute("VACUUM INTO ?", (str(copia),))
        con.execute("BEGIN IMMEDIATE")
        try:
            for sentencia in _MIGRACION_2:
                con.execute(sentencia)
            # PRAGMA user_version no admite parámetros: se interpola el entero
            # de la constante. Vive en la cabecera y su cambio es transaccional,
            # así que va DENTRO del BEGIN: o migra entero o no migra.
            con.execute(f"PRAGMA user_version = {int(VERSION_ESQUEMA)}")
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


# ------------------------------------------------------------------ utilidades

def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _desde(dias: int) -> str:
    """Marca de tiempo de hace N días, en el MISMO formato que se guarda.

    No se usa datetime('now', '-N days') de SQLite: escribe '2026-09-03 10:28:00'
    y aquí se guarda '2026-09-03T10:28:00+00:00'. Comparar las dos cadenas es
    comparar formatos distintos, y la 'T' pesa más que el espacio.
    """
    return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()


def id_de_token(token: str) -> str:
    """sha256 del token de sesión. En la base NUNCA entra el token en claro:
    un volcado de branding.db no permite suplantar a nadie."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def contar_contestadas(respuestas: dict[str, Any]) -> int:
    """Árbitro de conflictos entre dispositivos.

    Cuenta valores no vacíos en las cinco secciones. No lee `opcional` ni sabe
    de tipos: solo necesita ser determinista y monótona. La calcula SIEMPRE el
    servidor; el número que manda el cliente es cosmético y se ignora.
    """
    n = 0
    for sec in SECCIONES:
        bloque = respuestas.get(sec)
        if not isinstance(bloque, dict):
            continue
        for valor in bloque.values():
            if valor is None:
                continue
            if isinstance(valor, str) and valor.strip() == "":
                continue
            if isinstance(valor, (list, dict)) and len(valor) == 0:
                continue
            n += 1
    return n


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False)


def _evento(
    con: sqlite3.Connection,
    usuario_id: int | None,
    tipo: str,
    clave: str | None = None,
    valor: str | None = None,
) -> None:
    """Registra dentro de una transacción ajena. registrar_evento() es la
    versión pública, que abre la suya."""
    con.execute(
        "INSERT INTO eventos (usuario_id, tipo, clave, valor, creado_en) VALUES (?, ?, ?, ?, ?)",
        (usuario_id, tipo, clave, valor, _ahora()),
    )


# ------------------------------------------------------------------ usuarios

def crear_usuario_anonimo() -> int:
    ahora = _ahora()
    with conexion(escritura=True) as con:
        cur = con.execute(
            "INSERT INTO usuarios (anonimo, creado_en, visto_en) VALUES (1, ?, ?)",
            (ahora, ahora),
        )
        return int(cur.lastrowid)


def obtener_usuario(usuario_id: int) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT * FROM usuarios WHERE id = ? AND borrado_en IS NULL",
            (usuario_id,),
        ).fetchone()
    return dict(fila) if fila else None


def usuario_por_google_sub(sub: str) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT * FROM usuarios WHERE google_sub = ? AND borrado_en IS NULL",
            (sub,),
        ).fetchone()
    return dict(fila) if fila else None


def tocar_usuario(usuario_id: int) -> None:
    with conexion(escritura=True) as con:
        con.execute("UPDATE usuarios SET visto_en = ? WHERE id = ?", (_ahora(), usuario_id))


def borrar_usuario(usuario_id: int) -> None:
    """Baja física. Aquí SÍ se van los informes por cascada: es el derecho de
    supresión, no la purga de inactivos."""
    with conexion(escritura=True) as con:
        _evento(con, None, "borrado_cuenta", valor=str(usuario_id))
        con.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))


# ------------------------------------------------------------------ sesiones

def crear_sesion(
    token: str,
    usuario_id: int,
    ua_hash: str | None,
    ip_trunc: str | None,
    dias: int = DIAS_SESION,
) -> None:
    """`token` es ya el sha256 (lo que auth llama id_de_token), no el secreto."""
    ahora = datetime.now(timezone.utc)
    with conexion(escritura=True) as con:
        con.execute(
            "INSERT OR REPLACE INTO sesiones "
            "(id, usuario_id, creado_en, visto_en, expira_en, ua_hash, ip_trunc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                token,
                usuario_id,
                ahora.isoformat(),
                ahora.isoformat(),
                (ahora + timedelta(days=dias)).isoformat(),
                ua_hash,
                ip_trunc,
            ),
        )


def obtener_sesion(sesion_id: str) -> dict[str, Any] | None:
    """None si no existe, si caducó o si el usuario está borrado. Trae el
    usuario entero en la clave `usuario` para ahorrar un SELECT por petición."""
    with conexion() as con:
        fila = con.execute(
            "SELECT s.*, u.id AS u_id, u.google_sub, u.email, u.email_verificado, "
            "       u.nombre, u.foto_url, u.anonimo, u.creado_en AS u_creado_en, "
            "       u.visto_en AS u_visto_en "
            "FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id "
            "WHERE s.id = ? AND u.borrado_en IS NULL",
            (sesion_id,),
        ).fetchone()
    if fila is None:
        return None
    if fila["expira_en"] <= _ahora():
        return None
    return {
        "id": fila["id"],
        "usuario_id": fila["usuario_id"],
        "creado_en": fila["creado_en"],
        "visto_en": fila["visto_en"],
        "expira_en": fila["expira_en"],
        "ua_hash": fila["ua_hash"],
        "ip_trunc": fila["ip_trunc"],
        "usuario": {
            "id": fila["u_id"],
            "google_sub": fila["google_sub"],
            "email": fila["email"],
            "email_verificado": fila["email_verificado"],
            "nombre": fila["nombre"],
            "foto_url": fila["foto_url"],
            "anonimo": fila["anonimo"],
            "creado_en": fila["u_creado_en"],
            "visto_en": fila["u_visto_en"],
        },
    }


def tocar_sesion(sesion_id: str, dias: int = DIAS_SESION) -> None:
    """Renovación deslizante. La llama auth como mucho una vez al día por
    sesión: no hace falta una escritura por petición."""
    ahora = datetime.now(timezone.utc)
    with conexion(escritura=True) as con:
        con.execute(
            "UPDATE sesiones SET visto_en = ?, expira_en = ? WHERE id = ?",
            (ahora.isoformat(), (ahora + timedelta(days=dias)).isoformat(), sesion_id),
        )


def borrar_sesion(sesion_id: str) -> None:
    with conexion(escritura=True) as con:
        con.execute("DELETE FROM sesiones WHERE id = ?", (sesion_id,))


def borrar_sesiones_de(usuario_id: int) -> int:
    """«Salir de todos los dispositivos». Esto es lo que una cookie firmada
    nunca habría podido hacer."""
    with conexion(escritura=True) as con:
        cur = con.execute("DELETE FROM sesiones WHERE usuario_id = ?", (usuario_id,))
        return int(cur.rowcount or 0)


def purgar_sesiones_caducadas() -> int:
    with conexion(escritura=True) as con:
        cur = con.execute("DELETE FROM sesiones WHERE expira_en < ?", (_ahora(),))
        return int(cur.rowcount or 0)


# ------------------------------------------------------------------ borradores

def _fila_borrador(fila: sqlite3.Row) -> dict[str, Any]:
    return {
        "usuario_id": fila["usuario_id"],
        "respuestas": json.loads(fila["respuestas"]),
        "paso": fila["paso"],
        "ultimo_id": fila["ultimo_id"],
        "ronda": fila["ronda"],
        "contestadas": fila["contestadas"],
        "version": fila["version"],
        "informe_id": fila["informe_id"],
        "actualizado_en": fila["actualizado_en"],
    }


def obtener_borrador(usuario_id: int) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT * FROM borradores WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
    return _fila_borrador(fila) if fila else None


def guardar_borrador(
    usuario_id: int,
    respuestas: dict[str, Any],
    paso: int,
    ronda: int,
    ultimo_id: str | None,
    version_cliente: int | None,
) -> dict[str, Any]:
    """Bloqueo optimista por `version`.

    La `ronda` se guarda como max(guardada, recibida): no puede bajar nunca, y
    esa es la única razón por la que pulsar F5 deja de resetear el muro de
    tibieza. `contestadas` se recalcula aquí y solo aquí.
    """
    contestadas = contar_contestadas(respuestas)
    ahora = _ahora()
    with conexion(escritura=True) as con:
        fila = con.execute(
            "SELECT * FROM borradores WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
        if fila is None:
            con.execute(
                "INSERT INTO borradores "
                "(usuario_id, respuestas, paso, ultimo_id, ronda, contestadas, version, actualizado_en) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (usuario_id, _json(respuestas), int(paso), ultimo_id, int(ronda), contestadas, ahora),
            )
            return {"version": 1, "contestadas": contestadas, "actualizado_en": ahora}

        if version_cliente is None or int(version_cliente) != fila["version"]:
            raise ConflictoVersion(
                {
                    "version": fila["version"],
                    "contestadas": fila["contestadas"],
                    "paso": fila["paso"],
                    "ronda": fila["ronda"],
                    "actualizado_en": fila["actualizado_en"],
                }
            )

        nueva = fila["version"] + 1
        con.execute(
            "UPDATE borradores SET respuestas = ?, paso = ?, ultimo_id = ?, "
            "ronda = MAX(ronda, ?), contestadas = ?, version = ?, actualizado_en = ? "
            "WHERE usuario_id = ?",
            (_json(respuestas), int(paso), ultimo_id, int(ronda), contestadas, nueva, ahora, usuario_id),
        )
        return {"version": nueva, "contestadas": contestadas, "actualizado_en": ahora}


def _archivar(con: sqlite3.Connection, fila: sqlite3.Row, usuario_id: int, motivo: str) -> int:
    cur = con.execute(
        "INSERT INTO borradores_descartados "
        "(usuario_id, respuestas, paso, ronda, contestadas, motivo, creado_en) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            usuario_id,
            fila["respuestas"],
            fila["paso"],
            fila["ronda"],
            fila["contestadas"],
            motivo,
            _ahora(),
        ),
    )
    return int(cur.lastrowid)


def descartar_borrador(usuario_id: int, motivo: str) -> int | None:
    """Archiva y borra. Devuelve el id archivado, o None si no había borrador.

    Nada se tira: ni el perdedor de una fusión ni el «empezar de cero». Siempre
    queda la vía de /api/borrador/recuperar.
    """
    with conexion(escritura=True) as con:
        fila = con.execute(
            "SELECT * FROM borradores WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
        if fila is None:
            return None
        id_archivado = _archivar(con, fila, usuario_id, motivo)
        con.execute("DELETE FROM borradores WHERE usuario_id = ?", (usuario_id,))
        return id_archivado


def ultimo_descartado(usuario_id: int) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT * FROM borradores_descartados WHERE usuario_id = ? ORDER BY id DESC LIMIT 1",
            (usuario_id,),
        ).fetchone()
    if fila is None:
        return None
    return {
        "id": fila["id"],
        "respuestas": json.loads(fila["respuestas"]),
        "paso": fila["paso"],
        "ronda": fila["ronda"],
        "contestadas": fila["contestadas"],
        "motivo": fila["motivo"],
        "creado_en": fila["creado_en"],
    }


def restaurar_descartado(usuario_id: int) -> dict[str, Any] | None:
    """El enlace «usar el otro» de la tarjeta de fusión.

    Archiva el borrador vivo (motivo `conflicto_local`) y repone el último
    descartado como borrador con `version = 1`. Todo en una transacción: si se
    hiciera en dos llamadas, una caída en medio dejaría al usuario sin ninguno.
    Devuelve el borrador resultante, o None si no había nada archivado.
    """
    ahora = _ahora()
    with conexion(escritura=True) as con:
        arch = con.execute(
            "SELECT * FROM borradores_descartados WHERE usuario_id = ? ORDER BY id DESC LIMIT 1",
            (usuario_id,),
        ).fetchone()
        if arch is None:
            return None
        vivo = con.execute(
            "SELECT * FROM borradores WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
        if vivo is not None:
            _archivar(con, vivo, usuario_id, "conflicto_local")
            con.execute("DELETE FROM borradores WHERE usuario_id = ?", (usuario_id,))
        con.execute(
            "INSERT INTO borradores "
            "(usuario_id, respuestas, paso, ultimo_id, ronda, contestadas, version, actualizado_en) "
            "VALUES (?, ?, ?, NULL, ?, ?, 1, ?)",
            (
                usuario_id,
                arch["respuestas"],
                arch["paso"] or 0,
                arch["ronda"] or 0,
                arch["contestadas"] or 0,
                ahora,
            ),
        )
        con.execute("DELETE FROM borradores_descartados WHERE id = ?", (arch["id"],))
        fila = con.execute(
            "SELECT * FROM borradores WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
        return _fila_borrador(fila)


def marcar_borrador_enviado(usuario_id: int, informe_id: int) -> None:
    """Se anota el informe y el borrador SE QUEDA. «Volver a hacerlo» no puede
    destruir el intento anterior."""
    with conexion(escritura=True) as con:
        con.execute(
            "UPDATE borradores SET informe_id = ? WHERE usuario_id = ?",
            (informe_id, usuario_id),
        )


# ------------------------------------------------------------------ informes

def _fila_informe(fila: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": fila["id"],
        "creado_en": fila["creado_en"],
        "nombre": fila["nombre"],
        "email": fila["email"],
        "tipo_marca": fila["tipo_marca"],
        "respuestas": json.loads(fila["respuestas"]),
        "resultado": json.loads(fila["resultado"]),
        "recomendaciones": json.loads(fila["recomendaciones"]) if fila["recomendaciones"] else None,
        "usuario_id": fila["usuario_id"],
        "token_acceso": fila["token_acceso"],
        "publico": fila["publico"],
        "clave_idem": fila["clave_idem"],
        "ia_generada_en": fila["ia_generada_en"],
        "ia_intentos": fila["ia_intentos"],
    }


def guardar_informe(
    respuestas: dict[str, Any],
    resultado: dict[str, Any],
    usuario_id: int | None = None,
    clave_idem: str | None = None,
    recomendaciones: dict[str, Any] | None = None,
) -> tuple[int, str]:
    """Devuelve (id, token_acceso).

    Con `clave_idem` el doble envío no crea dos informes: si esa clave ya está,
    se devuelve el informe que ya existe.
    """
    identidad = respuestas.get("identidad", {}) or {}
    token = secrets.token_urlsafe(24)
    with conexion(escritura=True) as con:
        if clave_idem:
            previo = con.execute(
                "SELECT id, token_acceso FROM informes WHERE clave_idem = ?", (clave_idem,)
            ).fetchone()
            if previo is not None:
                return int(previo["id"]), str(previo["token_acceso"])
        cur = con.execute(
            """
            INSERT INTO informes
              (creado_en, nombre, email, tipo_marca, respuestas, resultado, recomendaciones,
               usuario_id, token_acceso, clave_idem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _ahora(),
                identidad.get("nombre"),
                identidad.get("email"),
                identidad.get("tipo_marca"),
                _json(respuestas),
                _json(resultado),
                _json(recomendaciones) if recomendaciones else None,
                usuario_id,
                token,
                clave_idem,
            ),
        )
        return int(cur.lastrowid), token


def guardar_recomendaciones(informe_id: int, recomendaciones: dict[str, Any]) -> None:
    with conexion(escritura=True) as con:
        con.execute(
            "UPDATE informes SET recomendaciones = ?, ia_generada_en = ? WHERE id = ?",
            (_json(recomendaciones), _ahora(), informe_id),
        )


def obtener_informe(informe_id: int) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute("SELECT * FROM informes WHERE id = ?", (informe_id,)).fetchone()
    return _fila_informe(fila) if fila else None


def informe_por_token(token_acceso: str) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT * FROM informes WHERE token_acceso = ?", (token_acceso,)
        ).fetchone()
    return _fila_informe(fila) if fila else None


def listar_informes_de(usuario_id: int, limite: int = 50) -> list[dict[str, Any]]:
    with conexion() as con:
        filas = con.execute(
            "SELECT id, creado_en, nombre, tipo_marca, token_acceso, "
            "       (recomendaciones IS NOT NULL) AS tiene_ia "
            "FROM informes WHERE usuario_id = ? ORDER BY id DESC LIMIT ?",
            (usuario_id, limite),
        ).fetchall()
    return [dict(f) for f in filas]


def listar_informes(limite: int = 50) -> list[dict[str, Any]]:
    """Listado global. Ya no lo sirve /api/informes: solo /admin/informes."""
    with conexion() as con:
        filas = con.execute(
            "SELECT id, creado_en, nombre, tipo_marca FROM informes ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    return [dict(f) for f in filas]


def reservar_intento_ia(informe_id: int, tope: int) -> int | None:
    """Cupo de llamadas al modelo, contado en la base y no en memoria.

    Se reserva ANTES de llamar al modelo y en su propia transacción: dos
    peticiones simultáneas no pueden gastar cuatro llamadas. Devuelve el nuevo
    contador, o None si el cupo está agotado. Un contador en RAM no vale: con
    uvicorn --reload cada recarga lo pondría a cero.
    """
    with conexion(escritura=True) as con:
        cur = con.execute(
            "UPDATE informes SET ia_intentos = ia_intentos + 1 WHERE id = ? AND ia_intentos < ?",
            (informe_id, int(tope)),
        )
        if not cur.rowcount:
            return None
        fila = con.execute("SELECT ia_intentos FROM informes WHERE id = ?", (informe_id,)).fetchone()
        return int(fila["ia_intentos"])


def reasignar_informes(de_usuario: int, a_usuario: int) -> int:
    """El token_acceso NO cambia: los enlaces ya compartidos siguen vivos."""
    with conexion(escritura=True) as con:
        cur = con.execute(
            "UPDATE informes SET usuario_id = ? WHERE usuario_id = ?", (a_usuario, de_usuario)
        )
        return int(cur.rowcount or 0)


# ------------------------------------------------------------------ eventos

def registrar_evento(
    usuario_id: int | None,
    tipo: str,
    clave: str | None = None,
    valor: str | None = None,
) -> None:
    with conexion(escritura=True) as con:
        _evento(con, usuario_id, tipo, clave, valor)


def reasignar_eventos(de_usuario: int, a_usuario: int) -> int:
    with conexion(escritura=True) as con:
        cur = con.execute(
            "UPDATE eventos SET usuario_id = ? WHERE usuario_id = ?", (a_usuario, de_usuario)
        )
        return int(cur.rowcount or 0)


def contar_eventos(tipo: str, desde_iso: str) -> int:
    with conexion() as con:
        fila = con.execute(
            "SELECT COUNT(*) AS n FROM eventos WHERE tipo = ? AND creado_en >= ?",
            (tipo, desde_iso),
        ).fetchone()
    return int(fila["n"])


def contar_eventos_por_clave(tipo: str, clave: str, desde_iso: str) -> int:
    with conexion() as con:
        fila = con.execute(
            "SELECT COUNT(*) AS n FROM eventos WHERE tipo = ? AND clave = ? AND creado_en >= ?",
            (tipo, clave, desde_iso),
        ).fetchone()
    return int(fila["n"])


# ------------------------------------------------------------------ fusión

def _resumen_borrador(fila: sqlite3.Row) -> dict[str, Any]:
    return {"contestadas": fila["contestadas"], "actualizado_en": fila["actualizado_en"]}


def entrar_con_google(
    sub: str,
    email: str | None,
    email_verificado: bool,
    nombre: str | None,
    foto_url: str | None,
    usuario_anonimo_id: int | None,
    ua_hash: str | None,
    ip_trunc: str | None,
) -> tuple[int, str, dict[str, Any] | None]:
    """Entrada con Google: promoción, login, reclamación o alta, en UNA transacción.

    Devuelve (usuario_id, token_de_sesion_nuevo, info_fusion|None). El token va
    en claro solo aquí, de vuelta a auth para la cookie; en la base entra su
    sha256.

    El guardián de reclamación (antigüedad de la sesión anónima y ua_hash) lo
    aplica auth ANTES de llamar: si no pasa, llega usuario_anonimo_id=None y
    esto se comporta como un login limpio. Aquí solo se comprueba que ese
    usuario siga existiendo y siga siendo anónimo.

    Lo que serializa dos entradas simultáneas del mismo `sub` es el BEGIN
    IMMEDIATE, no el ON CONFLICT; el ON CONFLICT es el cinturón.
    """
    ahora = _ahora()
    token = secrets.token_urlsafe(32)
    fusion: dict[str, Any] | None = None

    with conexion(escritura=True) as con:
        fila_g = con.execute(
            "SELECT id FROM usuarios WHERE google_sub = ? AND borrado_en IS NULL", (sub,)
        ).fetchone()
        u_google = int(fila_g["id"]) if fila_g else None

        u_anon = None
        if usuario_anonimo_id is not None:
            fila_a = con.execute(
                "SELECT id FROM usuarios WHERE id = ? AND anonimo = 1 AND borrado_en IS NULL",
                (usuario_anonimo_id,),
            ).fetchone()
            if fila_a:
                u_anon = int(fila_a["id"])

        if u_google is None and u_anon is not None:
            # (a) PROMOVER. Ni se copia ni se mueve nada: el borrador y los
            # informes ya cuelgan de ese usuario_id. Es el 90% de los casos.
            con.execute(
                "UPDATE usuarios SET google_sub = ?, email = ?, email_verificado = ?, "
                "nombre = ?, foto_url = ?, anonimo = 0, visto_en = ? WHERE id = ?",
                (sub, email, 1 if email_verificado else 0, nombre, foto_url, ahora, u_anon),
            )
            uid = u_anon
            _evento(con, uid, "reclamacion", clave=ip_trunc, valor="promocion")

        elif u_google is not None and u_anon is not None and u_anon != u_google:
            # (d) RECLAMAR: dos usuarios reales que pasan a ser uno.
            uid = u_google
            con.execute(
                "UPDATE usuarios SET email = ?, email_verificado = ?, nombre = ?, "
                "foto_url = ?, anonimo = 0, visto_en = ? WHERE id = ?",
                (email, 1 if email_verificado else 0, nombre, foto_url, ahora, uid),
            )
            con.execute("UPDATE informes SET usuario_id = ? WHERE usuario_id = ?", (uid, u_anon))
            con.execute("UPDATE eventos  SET usuario_id = ? WHERE usuario_id = ?", (uid, u_anon))
            # Los archivados del anónimo se reasignan en vez de dejarlos morir
            # en la cascada del DELETE: «nada se tira» también vale aquí.
            con.execute(
                "UPDATE borradores_descartados SET usuario_id = ? WHERE usuario_id = ?",
                (uid, u_anon),
            )

            b_anon = con.execute(
                "SELECT * FROM borradores WHERE usuario_id = ?", (u_anon,)
            ).fetchone()
            b_goo = con.execute(
                "SELECT * FROM borradores WHERE usuario_id = ?", (uid,)
            ).fetchone()
            if b_anon is not None and b_goo is not None:
                # Gana el de más respuestas contestadas. El reloj solo desempata:
                # un móvil con la hora adelantada no puede pisar 96 respuestas con 3.
                clave_a = (b_anon["contestadas"], b_anon["actualizado_en"])
                clave_g = (b_goo["contestadas"], b_goo["actualizado_en"])
                if clave_a > clave_g:
                    ganador, perdedor = b_anon, b_goo
                else:
                    ganador, perdedor = b_goo, b_anon
                _archivar(con, perdedor, uid, "fusion")
                con.execute(
                    "DELETE FROM borradores WHERE usuario_id = ?", (perdedor["usuario_id"],)
                )
                if ganador["usuario_id"] != uid:
                    con.execute(
                        "UPDATE borradores SET usuario_id = ? WHERE usuario_id = ?",
                        (uid, ganador["usuario_id"]),
                    )
                fusion = {
                    "ganador": _resumen_borrador(ganador),
                    "descartado": _resumen_borrador(perdedor),
                }
            elif b_anon is not None:
                con.execute(
                    "UPDATE borradores SET usuario_id = ? WHERE usuario_id = ?", (uid, u_anon)
                )

            con.execute("DELETE FROM usuarios WHERE id = ?", (u_anon,))
            _evento(
                con,
                uid,
                "reclamacion",
                clave=ip_trunc,
                valor="fusion" if fusion else "traspaso",
            )

        elif u_google is not None:
            # (b) y (c): login normal. Se refrescan nombre, foto y email porque
            # el email de una cuenta de Google puede cambiar; la identidad es el sub.
            uid = u_google
            con.execute(
                "UPDATE usuarios SET email = ?, email_verificado = ?, nombre = ?, "
                "foto_url = ?, anonimo = 0, visto_en = ? WHERE id = ?",
                (email, 1 if email_verificado else 0, nombre, foto_url, ahora, uid),
            )

        else:
            # (e) alta limpia.
            con.execute(
                "INSERT INTO usuarios "
                "(google_sub, email, email_verificado, nombre, foto_url, anonimo, creado_en, visto_en) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, ?) "
                "ON CONFLICT(google_sub) DO UPDATE SET email = excluded.email, "
                "  email_verificado = excluded.email_verificado, nombre = excluded.nombre, "
                "  foto_url = excluded.foto_url, anonimo = 0, visto_en = excluded.visto_en",
                (sub, email, 1 if email_verificado else 0, nombre, foto_url, ahora, ahora),
            )
            fila = con.execute("SELECT id FROM usuarios WHERE google_sub = ?", (sub,)).fetchone()
            uid = int(fila["id"])

        # Rotación obligatoria al subir de nivel: la sesión anónima se BORRA, no
        # se reutiliza. Quien plante una cookie anónima en el navegador de otro
        # no se queda dentro después de que la víctima inicie sesión.
        if usuario_anonimo_id is not None:
            con.execute("DELETE FROM sesiones WHERE usuario_id = ?", (usuario_anonimo_id,))

        con.execute(
            "INSERT OR REPLACE INTO sesiones "
            "(id, usuario_id, creado_en, visto_en, expira_en, ua_hash, ip_trunc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                id_de_token(token),
                uid,
                ahora,
                ahora,
                (datetime.now(timezone.utc) + timedelta(days=DIAS_SESION)).isoformat(),
                ua_hash,
                ip_trunc,
            ),
        )
        _evento(con, uid, "login", clave=ip_trunc)

    return uid, token, fusion


# ------------------------------------------------------------------ purga

def purgar_anonimos(dias: int = DIAS_RETENCION_ANONIMOS) -> int:
    """Limpieza de anónimos inactivos. El orden NO es estilo.

    Primero se DESENGANCHAN los informes (usuario_id = NULL) y solo después se
    borran los usuarios. Sin ese paso, el ON DELETE CASCADE de informes.usuario_id
    borraría informes ya emitidos, con su enlace posiblemente compartido. La
    cascada de informes solo debe dispararse en el borrado voluntario de cuenta.
    """
    corte = _desde(dias)
    with conexion(escritura=True) as con:
        con.execute(
            "UPDATE informes SET usuario_id = NULL WHERE usuario_id IN "
            "(SELECT id FROM usuarios WHERE anonimo = 1 AND borrado_en IS NULL AND visto_en < ?)",
            (corte,),
        )
        cur = con.execute(
            "DELETE FROM usuarios WHERE anonimo = 1 AND borrado_en IS NULL AND visto_en < ? "
            "AND id NOT IN (SELECT usuario_id FROM informes WHERE usuario_id IS NOT NULL)",
            (corte,),
        )
        n = int(cur.rowcount or 0)
        if n:
            _evento(con, None, "purga", valor=str(n))
    return n
