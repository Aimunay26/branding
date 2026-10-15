"""Asigna a mano informes huérfanos a una cuenta de Google.

    python scripts/reclamar_informes.py --email tu@correo.com --informes 1,2,3

Por qué esto es un script y no una ruta de la aplicación: reclamar por
`informes.email` desde dentro significa que quien registre ese correo en Google
se lleva el informe ajeno. Los informes que existían antes del login se quedan
con `usuario_id NULL` tras la migración y siguen abriéndose por su
`token_acceso`; si el dueño los quiere en su cuenta, se hace aquí, uno a uno y
con los ojos puestos en la pantalla.

Solo toca informes que están sin dueño. Un informe que ya pertenece a alguien no
se le quita: eso no es reclamar, es robar, y el UPDATE lleva la condición puesta.

La copia previa a la migración está en datos/branding-pre-v2.db. Si algo sale
mal, ahí está la base tal y como estaba antes de que existieran los usuarios.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app import db  # noqa: E402  (hay que arreglar sys.path antes de importar)


def parsear_ids(texto: str) -> list[int]:
    """'1,2,3' -> [1, 2, 3], sin repetidos y en orden.

    Se valida aquí y no en el SQL para que un dedo torcido salga como un error
    legible y no como una consulta que no devuelve nada.
    """
    ids: list[int] = []
    for trozo in texto.split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        if not trozo.isdigit():
            raise ValueError(f"«{trozo}» no es un id de informe. Se esperaban números separados por comas.")
        n = int(trozo)
        if n not in ids:
            ids.append(n)
    if not ids:
        raise ValueError("No has pedido ningún informe.")
    return ids


def version_esquema() -> int:
    with db.conexion() as con:
        return int(con.execute("PRAGMA user_version").fetchone()[0])


def buscar_usuario(email: str) -> dict[str, object] | None:
    """Cuenta de Google con el correo verificado. Nada más vale.

    Sin `google_sub` no hay cuenta de Google detrás, solo un anónimo con un
    correo escrito a mano en el formulario; y sin `email_verificado` el correo
    lo pone quien quiera. Regalar informes a cualquiera de los dos es
    exactamente el agujero que este script existe para no abrir.
    """
    with db.conexion() as con:
        fila = con.execute(
            "SELECT id, email, nombre, anonimo, borrado_en FROM usuarios "
            "WHERE lower(email) = lower(?) AND google_sub IS NOT NULL "
            "  AND email_verificado = 1 AND borrado_en IS NULL "
            "ORDER BY id LIMIT 1",
            (email,),
        ).fetchone()
    return dict(fila) if fila else None


def leer_informes(ids: list[int]) -> dict[int, dict[str, object]]:
    marcas = ",".join("?" * len(ids))
    with db.conexion() as con:
        filas = con.execute(
            f"SELECT id, creado_en, nombre, email, token_acceso, usuario_id "
            f"FROM informes WHERE id IN ({marcas}) ORDER BY id",
            tuple(ids),
        ).fetchall()
    return {int(f["id"]): dict(f) for f in filas}


def reclamar(usuario_id: int, ids: list[int]) -> list[int]:
    """UPDATE condicional y evento, todo en una transacción.

    La condición `usuario_id IS NULL` va en el SQL y no en un `if` de Python:
    entre la comprobación y la escritura hay una ventana, y en esa ventana la
    aplicación puede haber asignado el informe a otra persona.
    """
    reclamados: list[int] = []
    with db.conexion(escritura=True) as con:
        for informe_id in ids:
            cur = con.execute(
                "UPDATE informes SET usuario_id = ? WHERE id = ? AND usuario_id IS NULL",
                (usuario_id, informe_id),
            )
            if cur.rowcount:
                reclamados.append(informe_id)
                db._evento(con, usuario_id, "reclamacion", str(informe_id), "manual")
    return reclamados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reclamar_informes.py",
        description="Asigna informes sin dueño a una cuenta de Google verificada.",
    )
    parser.add_argument("--email", required=True, help="Correo de la cuenta de Google que se queda los informes.")
    parser.add_argument("--informes", required=True, help="Ids separados por comas. Ej.: 1,2,3")
    args = parser.parse_args(argv)

    try:
        ids = parsear_ids(args.informes)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not db.RUTA_DB.exists():
        print(f"ERROR: no existe la base de datos {db.RUTA_DB}.", file=sys.stderr)
        return 2

    # La migración la hace la aplicación al arrancar (db.inicializar). Este script
    # no migra nada a propósito: un script de mantenimiento que además cambia el
    # esquema es la forma más rápida de dejar la base a medias sin que nadie mire.
    version = version_esquema()
    if version < db.VERSION_ESQUEMA:
        print(
            f"ERROR: la base está en el esquema v{version} y aquí hace falta la v{db.VERSION_ESQUEMA}.\n"
            "       Arranca la aplicación una vez (uvicorn app.main:app) para que migre,\n"
            "       comprueba que los informes se siguen abriendo, y vuelve.",
            file=sys.stderr,
        )
        return 2

    usuario = buscar_usuario(args.email)
    if usuario is None:
        print(
            f"ERROR: no hay ninguna cuenta de Google verificada con el correo {args.email}.\n"
            "       Esa persona tiene que entrar una vez con «Continuar con Google» antes\n"
            "       de que se le pueda asignar nada.",
            file=sys.stderr,
        )
        return 1

    encontrados = leer_informes(ids)

    faltan = [i for i in ids if i not in encontrados]
    ajenos = [i for i in ids if i in encontrados and encontrados[i]["usuario_id"] is not None]
    libres = [i for i in ids if i in encontrados and encontrados[i]["usuario_id"] is None]

    print(f"Cuenta destino: id={usuario['id']}  {usuario['email']}  ({usuario['nombre'] or 'sin nombre'})")
    print()
    print("Informes pedidos:")
    for informe_id in ids:
        if informe_id in faltan:
            print(f"  {informe_id:>4}  NO EXISTE")
            continue
        fila = encontrados[informe_id]
        estado = "SIN DUEÑO" if fila["usuario_id"] is None else f"YA ES DE usuario_id={fila['usuario_id']}"
        print(
            f"  {informe_id:>4}  {fila['creado_en']}  {fila['nombre'] or 'sin nombre'}"
            f"  token={fila['token_acceso']}  [{estado}]"
        )
    print()

    if faltan:
        print(f"AVISO: {len(faltan)} id(s) no existen y se ignoran: {', '.join(map(str, faltan))}")
    if ajenos:
        print(f"AVISO: {len(ajenos)} informe(s) ya tienen dueño y NO se tocan: {', '.join(map(str, ajenos))}")
    print(
        "AVISO: la copia de la base anterior a la migración v2 está en "
        f"{db.DIR_DATOS / 'branding-pre-v2.db'}."
    )
    print()

    if not libres:
        print("No hay nada que reclamar. No se ha tocado nada.")
        return 0

    print(f"Se van a asignar {len(libres)} informe(s) ({', '.join(map(str, libres))}) a {usuario['email']}.")
    respuesta = input(f"Escribe el número de informes para confirmar ({len(libres)}), o cualquier otra cosa para abortar: ").strip()
    if respuesta != str(len(libres)):
        print("Abortado. No se ha tocado nada.")
        return 1

    reclamados = reclamar(int(usuario["id"]), libres)
    print(f"Hecho: {len(reclamados)} informe(s) asignados a usuario_id={usuario['id']}: {', '.join(map(str, reclamados))}")
    if len(reclamados) != len(libres):
        perdidos = [i for i in libres if i not in reclamados]
        print(
            f"AVISO: {len(perdidos)} informe(s) cambiaron de dueño mientras mirabas la lista "
            f"y no se han tocado: {', '.join(map(str, perdidos))}"
        )
    print("Los token_acceso NO han cambiado: los enlaces ya compartidos siguen funcionando.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
