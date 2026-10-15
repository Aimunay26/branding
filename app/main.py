"""Generador de Branding — servidor FastAPI.

    ./.venv/bin/uvicorn app.main:app --reload

El backend no es opcional: la API key de Claude no puede vivir en el navegador.
Una vez que existe, generar el PDF en el servidor sale casi gratis.

Tres reglas que explican la forma de este fichero:

1. NADA de dict[str, Any] a pelo en los cuerpos de petición. Todo entra por un
   modelo Pydantic y con tope de tamaño. Antes, `ronda: "x"` reventaba con un
   ValueError sin capturar y `respuestas: []` con un AttributeError dentro del
   motor: dos 500 con traza que el usuario veía como «error del servidor».

2. Un informe ajeno responde 404, nunca 403. Un 403 confirma que el informe
   existe y convierte el barrido de ids en un censo de clientes. El mismo 404
   vale para «no existe», «no es tuyo» y «el token no cuadra».

3. La ronda del muro de tibieza la decide el SERVIDOR (columna borradores.ronda).
   Mientras la mandaba el cliente, un POST con ronda:2 —o pulsar F5— saltaba el
   muro entero. El navegador puede pedir, no puede declarar en qué ronda va.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import auth, contenido, db, informe as informe_mod, pdf, scoring

RAIZ = Path(__file__).resolve().parent
plantillas = Jinja2Templates(directory=str(RAIZ / "templates"))
registro = logging.getLogger("branding")

# Topes. Los de la IA se cuentan en la BASE y no en memoria: `uvicorn --reload`
# reinicia el proceso a cada guardado y cualquier contador en RAM vuelve a cero.
TOPE_IA_DIARIO = 200          # llamadas al modelo en 24 h, para todo el servidor
TOPE_IA_POR_INFORME = 3       # llamadas por informe, columna informes.ia_intentos
TOPE_BORRADOR = 262144        # 256 KiB; los tres informes reales ocupan ~4 KB
TOPE_CUERPO = 1048576         # 1 MiB para cualquier otro cuerpo


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    """Sustituye a @app.on_event('startup'), que está deprecado desde FastAPI 0.93."""
    db.inicializar()
    db.purgar_sesiones_caducadas()
    db.purgar_anonimos(_dias_retencion())

    # Los dos avisos que ahorran horas de depuración a ciegas:
    if not auth.cookie_segura():
        registro.warning(
            "COOKIE_SEGURA no está a 1: la cookie de sesión viaja sin el flag "
            "Secure. Correcto en local sobre http; en producción sobre https, "
            "ponlo a 1. Al revés (Secure sobre http) el navegador DESCARTA la "
            "cookie sin un solo error visible y cada petición crea un usuario."
        )
    if not auth.google_activo():
        registro.warning(
            "GOOGLE_CLIENT_ID vacío: todo el mundo entra como anónimo y nadie "
            "podrá recuperar su cuestionario desde otro dispositivo."
        )
    yield


app = FastAPI(title="Generador de Branding", lifespan=ciclo_de_vida)
app.mount("/static", StaticFiles(directory=str(RAIZ / "static")), name="static")


@app.middleware("http")
async def bloquear_origen_cruzado(request: Request, call_next):
    """CSRF sin tokens por formulario: no hay un solo <form> clásico en el
    proyecto, todo es fetch del mismo origen. SameSite=Lax cubre casi todo, y
    estas ocho líneas cubren el POST de navegación de primer nivel que Lax no
    cubre. Ningún GET cambia estado, así que los métodos seguros pasan.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origen = request.headers.get("origin")
        if origen and urlsplit(origen).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
        if _tamano(request) > TOPE_CUERPO:
            return JSONResponse({"detail": "Petición demasiado grande."}, status_code=413)
    return await call_next(request)


# ------------------------------------------------------------------ utilidades

def _dias_retencion() -> int:
    try:
        return int(os.environ.get("DIAS_RETENCION_ANONIMOS", str(db.DIAS_RETENCION_ANONIMOS)))
    except ValueError:
        registro.warning("DIAS_RETENCION_ANONIMOS no es un número; uso el valor por defecto.")
        return db.DIAS_RETENCION_ANONIMOS


def _tamano(request: Request) -> int:
    try:
        return int(request.headers.get("content-length") or 0)
    except ValueError:
        return 0


def _ahora_menos(**delta: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _llamar(funcion: Callable[..., Any], *args: Any, **extras: Any) -> Any:
    """Llama pasando solo los argumentos con nombre que la función acepta.

    scoring.py e informe.py están creciendo con parámetros nuevos (`lexico`,
    `categoria`, `atencion`, `textos`, `ronda`) en otra tanda de cambios que
    aterriza por su cuenta. Filtrar por la firma real deja este fichero
    funcionando con las dos versiones, en vez de romperse el día que una llegue
    antes que la otra. Cuando todas hayan aterrizado, esto sobra y se quita.
    """
    acepta = inspect.signature(funcion).parameters
    return funcion(*args, **{k: v for k, v in extras.items() if k in acepta})


def _si_existe(nombre: str, *args: Any, **extras: Any) -> Any:
    """Llama a scoring.<nombre> si ya existe; si no, devuelve None."""
    funcion = getattr(scoring, nombre, None)
    if funcion is None:
        return None
    return _llamar(funcion, *args, **extras)


def _lexico() -> dict[str, Any] | None:
    fn = getattr(contenido, "lexico_evasion", None)
    return fn() if fn else None


def _categoria() -> dict[str, Any] | None:
    fn = getattr(contenido, "categoria", None)
    return fn() if fn else None


@lru_cache(maxsize=1)
def _ids_del_test() -> frozenset[str]:
    """Ids de los ítems Likert del test, controles incluidos. Los bloques de
    elección forzada NO están: sus respuestas son índices de opción (0..3) y
    validarlos como escala 1-5 rechazaría datos correctos."""
    test = contenido.test_arquetipos()
    return frozenset(
        [i["id"] for i in test.get("items", [])] + [c["id"] for c in test.get("control", [])]
    )


@lru_cache(maxsize=1)
def _version_contenido() -> str:
    """sha1 de los JSON que se sirven en /api/contenido.

    Sirve para que un borrador guardado sepa que las preguntas han cambiado
    debajo. Se cachea porque contenido.py también cachea: editar un JSON ya
    obligaba a reiniciar el servidor, y esto no cambia esa regla.
    """
    h = hashlib.sha1()
    for nombre in sorted(
        (
            "arquetipos.json",
            "test_arquetipos.json",
            "modulo_comunicacion.json",
            "modulo_visual.json",
            "modulo_acciones.json",
            "referentes.json",
            "lexico_evasion.json",
            "categoria.json",
        )
    ):
        ruta = contenido.DIR_CONTENIDO / nombre
        if ruta.exists():
            h.update(nombre.encode("utf-8"))
            h.update(ruta.read_bytes())
    return h.hexdigest()[:12]


def _sin_svg(resultado: dict[str, Any]) -> dict[str, Any]:
    """Los SVG se regeneran en cada render; no engordamos la base con ellos."""
    copia = dict(resultado)
    copia.pop("graficos", None)
    return copia


def _construir(respuestas: dict[str, Any], ronda: int = 0) -> dict[str, Any]:
    try:
        return _llamar(
            informe_mod.construir,
            respuestas,
            ronda=ronda,
            lexico=_lexico(),
            categoria=_categoria(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _ronda_guardada(resultado: dict[str, Any]) -> int:
    """La ronda con la que se EMITIÓ un informe ya guardado.

    Al reconstruir un informe viejo hay que usar su ronda, no cero: con cero, el
    veredicto volvería a pedir repetir y la portada mentiría sobre un informe que
    ya está emitido y no se puede repetir.
    """
    if not isinstance(resultado, dict):
        return scoring.MAX_RONDAS_TIBIEZA
    ronda = resultado.get("ronda")
    if ronda is None:
        ronda = (resultado.get("veredicto") or {}).get("ronda")
    try:
        return int(ronda)
    except (TypeError, ValueError):
        return scoring.MAX_RONDAS_TIBIEZA


def _evaluar_definicion(respuestas: dict[str, Any], ronda: int) -> dict[str, Any]:
    """El muro, en un solo sitio: lo usan /api/tibieza y la puerta de /api/informe.

    Devuelve el mismo cuerpo en los dos, para que el frontend reutilice
    `insertarDesempate` sin una rama nueva por endpoint.
    """
    test = contenido.test_arquetipos()
    mods = contenido.modulos()
    fichas = contenido.arquetipos()["fichas"]
    lexico = _lexico()

    atencion = _si_existe("validar_atencion", respuestas, test)
    textos = _si_existe("calidad_textos", respuestas, mods, lexico)
    tibieza = _llamar(scoring.indice_tibieza, respuestas, test, mods, lexico=lexico)

    # El perfil hace falta para saber si sale plano; se calcula sin montar el
    # informe entero. Si el test está a medias, `plano` es la respuesta honesta.
    try:
        perfil = scoring.puntuar_arquetipos(respuestas.get("arquetipos") or {}, test, fichas)
    except ValueError:
        perfil = {"coherencia": None}

    veredicto = _llamar(
        scoring.veredicto_definicion,
        tibieza,
        perfil,
        ronda=ronda,
        atencion=atencion,
        textos=textos,
    )
    planas = _si_existe("preguntas_planas", respuestas, test) or []

    return {"tibieza": tibieza, "veredicto": veredicto, "textos": textos, "planas": planas}


def _tope_ronda(pedida: Any) -> int:
    try:
        return max(0, min(int(pedida), scoring.MAX_RONDAS_TIBIEZA))
    except (TypeError, ValueError):
        return 0


def _ronda_del_muro(usuario_id: int, pedida: int, confiar_en_el_cliente: bool) -> int:
    """En qué ronda del muro va esta persona, según el SERVIDOR.

    Manda la columna `borradores.ronda`. `confiar_en_el_cliente` solo lo pone a
    True /api/tibieza, que es un oráculo asesor y además persiste lo que
    calcula; la puerta de /api/informe no mira el número del cliente en absoluto,
    porque si lo mirara el muro se saltaría con una cabecera y un curl.

    Sin fila de borrador la ronda es 0, y no hace falta más: el primer 409 crea
    la fila con ronda 1, así que el contador avanza solo aunque el navegador no
    haya guardado nada todavía.
    """
    borrador = db.obtener_borrador(usuario_id)
    guardada = int(borrador["ronda"]) if borrador else 0
    return max(guardada, _tope_ronda(pedida)) if confiar_en_el_cliente else guardada


def _fijar_ronda(usuario_id: int, ronda: int, respuestas: dict[str, Any]) -> None:
    """Sube la ronda en la fila del borrador, y la crea si aún no existe.

    Crearla importa: si el muro solo escribiera cuando ya hay fila, un cliente
    sin autoguardado nunca subiría de ronda y se quedaría dando vueltas en el
    409 para siempre. Se escribe con la versión que acabamos de leer porque la
    columna es del borrador; el UPDATE guarda MAX(ronda, recibida), así que dos
    pestañas a la vez no pueden bajarla. Si otra escritura se cruza, el
    conflicto se ignora: quien escribió tiene una ronda igual o mayor.
    """
    borrador = db.obtener_borrador(usuario_id)
    if borrador is None:
        db.guardar_borrador(usuario_id, respuestas, 0, ronda, None, None)
        return
    if ronda <= int(borrador["ronda"]):
        return
    try:
        db.guardar_borrador(
            usuario_id,
            borrador["respuestas"],
            int(borrador["paso"]),
            ronda,
            borrador["ultimo_id"],
            int(borrador["version"]),
        )
    except db.ConflictoVersion:
        pass


def _informe_accesible(informe_id: int, usuario: dict[str, Any] | None, t: str | None) -> dict[str, Any]:
    """Dueño o token de lectura. Cualquier otra cosa: 404, nunca 403."""
    reg = db.obtener_informe(informe_id)
    if reg is None:
        raise HTTPException(status_code=404, detail="Informe no encontrado")
    if usuario and reg["usuario_id"] == usuario["id"]:
        return reg
    if t and reg["token_acceso"] and hmac.compare_digest(str(t), str(reg["token_acceso"])):
        return reg
    raise HTTPException(status_code=404, detail="Informe no encontrado")


def _cuerpo_yo(usuario: dict[str, Any] | None) -> dict[str, Any]:
    """Lo que ve el cliente de sí mismo. Nunca `google_sub` ni las respuestas:
    el borrador entero se pide aparte, en GET /api/borrador."""
    base: dict[str, Any] = {
        "autenticado": usuario is not None,
        "anonimo": bool(usuario["anonimo"]) if usuario else False,
        "usuario_id": usuario["id"] if usuario else None,
        "nombre": usuario["nombre"] if usuario else None,
        "email": usuario["email"] if usuario else None,
        "foto": usuario["foto_url"] if usuario else None,
        "google_disponible": auth.google_activo(),
        "borrador": None,
        "borrador_descartado": None,
        "informes": [],
    }
    if usuario is None:
        return base

    borrador = db.obtener_borrador(usuario["id"])
    if borrador:
        base["borrador"] = {
            "paso": borrador["paso"],
            "ultimo_id": borrador["ultimo_id"],
            "ronda": borrador["ronda"],
            "contestadas": borrador["contestadas"],
            "version": borrador["version"],
            "actualizado_en": borrador["actualizado_en"],
            "informe_id": borrador["informe_id"],
        }
    descartado = db.ultimo_descartado(usuario["id"])
    if descartado:
        base["borrador_descartado"] = {
            "contestadas": descartado["contestadas"],
            "actualizado_en": descartado["creado_en"],
        }
    base["informes"] = [
        {
            "id": f["id"],
            "creado_en": f["creado_en"],
            "token_acceso": f["token_acceso"],
            "tiene_ia": bool(f["tiene_ia"]),
        }
        for f in db.listar_informes_de(usuario["id"])
    ]
    return base


def _cuerpo_borrador(borrador: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": borrador["version"],
        "paso": borrador["paso"],
        "ultimo_id": borrador["ultimo_id"],
        "ronda": borrador["ronda"],
        "contestadas": borrador["contestadas"],
        "actualizado_en": borrador["actualizado_en"],
        "informe_id": borrador["informe_id"],
        "respuestas": borrador["respuestas"],
    }


# ------------------------------------------------------------------ modelos

class Respuestas(BaseModel):
    """Las cinco secciones del cuestionario.

    `extra='ignore'` a propósito: db.SECCIONES son exactamente estas cinco, y una
    clave suelta del cliente no debe entrar en la base ni provocar un 422 que
    haga perder el borrador entero.
    """

    model_config = ConfigDict(extra="ignore")

    identidad: dict[str, Any] = Field(default_factory=dict)
    arquetipos: dict[str, Any] = Field(default_factory=dict)
    comunicacion: dict[str, Any] = Field(default_factory=dict)
    visual: dict[str, Any] = Field(default_factory=dict)
    acciones: dict[str, Any] = Field(default_factory=dict)

    @field_validator("arquetipos")
    @classmethod
    def _escala_del_test(cls, valores: dict[str, Any]) -> dict[str, Any]:
        """Los ítems del test son escala 1-5 y nadie lo comprobaba.

        Sin esto se podía fabricar un perfil «definido» mandando 9 en cuatro
        ítems. Los bloques de elección forzada (FC-*) quedan fuera: su valor es
        el índice de la opción elegida y empieza en 0.
        """
        for id_item in _ids_del_test():
            if id_item not in valores or valores[id_item] is None:
                continue
            try:
                n = int(valores[id_item])
            except (TypeError, ValueError):
                raise ValueError(f"{id_item}: la escala del test va de 1 a 5")
            if not 1 <= n <= 5:
                raise ValueError(f"{id_item}: la escala del test va de 1 a 5, llegó {n}")
            valores[id_item] = n
        return valores


class CuerpoTibieza(BaseModel):
    model_config = ConfigDict(extra="ignore")
    respuestas: Respuestas
    ronda: int = Field(0, ge=0, le=99)


class CuerpoInforme(Respuestas):
    # clave_idem: un randomUUID() que el cliente guarda en su estado. Con ella,
    # el doble envío devuelve el mismo informe en vez de crear dos.
    clave_idem: str | None = Field(None, max_length=64)


class CuerpoBorrador(BaseModel):
    model_config = ConfigDict(extra="ignore")
    respuestas: Respuestas
    paso: int = Field(0, ge=0, le=1000)
    ultimo_id: str | None = Field(None, max_length=64)
    ronda: int = Field(0, ge=0, le=99)
    version: int | None = Field(None, ge=0)


class CuerpoDescartar(BaseModel):
    model_config = ConfigDict(extra="ignore")
    motivo: Literal["reinicio", "conflicto_local", "fusion"] = "reinicio"


class CuerpoGoogle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # `Any` y no `str` a propósito: el 400 con mensaje propio es más útil que el
    # 422 de Pydantic para el único campo que el usuario no escribe a mano.
    credential: Any = None


class CuerpoBorrarCuenta(BaseModel):
    model_config = ConfigDict(extra="ignore")
    confirmacion: str = ""


# ------------------------------------------------------------------ páginas

@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    # Firma moderna de Starlette: (request, nombre, contexto). La antigua
    # (nombre, {"request": ...}) revienta con las versiones actuales.
    return plantillas.TemplateResponse(
        request,
        "index.html",
        {"google_client_id": auth.CLIENT_ID, "google_activo": auth.google_activo()},
    )


@app.get("/privacidad", response_class=HTMLResponse)
def privacidad(request: Request):
    if not (RAIZ / "templates" / "privacidad.html").exists():
        raise HTTPException(status_code=404, detail="Página no encontrada")
    return plantillas.TemplateResponse(request, "privacidad.html", {})


@app.get("/api/contenido")
def api_contenido() -> dict[str, Any]:
    """Todo lo que el frontend necesita para pintar el cuestionario."""
    datos = contenido.arquetipos()
    return {
        "arquetipos": datos["lista"],
        "familias": datos["familias"],
        "test": contenido.test_arquetipos(),
        "modulos": contenido.modulos(),
        "referentes": contenido.referentes(),
        # Los dos que form.js necesita para aplicar los mínimos en el cliente:
        # sin ellos la validación de textos solo existe en el servidor y el
        # usuario se entera al final, que es cuando ya no quiere volver.
        "lexico_evasion": _lexico(),
        "categoria": _categoria(),
        # Las tablas de las sugerencias de nombre. form.js llevaba una copia
        # dentro; servirlas deja una sola fuente de verdad.
        "nombres": contenido.nombres(),
        "version": _version_contenido(),
    }


# ------------------------------------------------------------------ acceso

@app.post("/api/auth/google")
def api_entrar_google(request: Request, respuesta: Response, cuerpo: CuerpoGoogle) -> dict[str, Any]:
    if not auth.google_activo():
        raise HTTPException(
            status_code=503,
            detail="El acceso con Google no está configurado en este servidor. Entra sin cuenta.",
        )
    if not isinstance(cuerpo.credential, str) or not cuerpo.credential.strip():
        raise HTTPException(status_code=400, detail="Falta el credential de Google.")

    ip = auth.ip_trunc(request)
    if ip and db.contar_eventos_por_clave("login_fallido", ip, _ahora_menos(minutes=15)) >= 10:
        raise HTTPException(
            status_code=429, detail="Demasiados intentos desde tu conexión. Espera un rato."
        )

    try:
        datos = auth.verificar_id_token(cuerpo.credential)
    except auth.ErrorAuth as e:
        # Se registra el MOTIVO, nunca el credential: es un token de acceso.
        motivo = str(e.args[0]) if e.args else "desconocido"
        db.registrar_evento(None, "login_fallido", clave=ip, valor=motivo)
        registro.info("login con Google rechazado: %s", motivo)
        raise HTTPException(
            status_code=401, detail="Ese acceso de Google no vale. Vuelve a intentarlo."
        ) from e

    usuario_id, fusion = auth.entrar_con_google(request, respuesta, datos)
    salida = _cuerpo_yo(db.obtener_usuario(usuario_id))
    salida["fusion"] = fusion
    return salida


@app.post("/api/auth/anonimo")
def api_entrar_anonimo(request: Request, respuesta: Response) -> dict[str, Any]:
    """«Continuar sin cuenta». Idempotente: si ya hay sesión válida no crea
    nada, para que un doble clic no deje usuarios huérfanos por la base."""
    sesion = auth.sesion_actual(request)
    if sesion is not None:
        return _cuerpo_yo(sesion["usuario"])

    usuario_id = db.crear_usuario_anonimo()
    auth.abrir_sesion(respuesta, usuario_id, request)
    db.registrar_evento(usuario_id, "anonimo", valor="explicito")
    respuesta.status_code = 201
    return _cuerpo_yo(db.obtener_usuario(usuario_id))


@app.post("/api/auth/salir")
def api_salir(request: Request, respuesta: Response, todos: int = 0):
    """Sin sesión también devuelve 204: salir dos veces no es un error."""
    sesion = auth.sesion_actual(request)
    if todos and sesion is not None and not sesion["usuario"]["anonimo"]:
        db.borrar_sesiones_de(sesion["usuario_id"])
    auth.cerrar_sesion(request, respuesta)
    respuesta.status_code = 204
    return respuesta


@app.get("/api/yo")
def api_yo(usuario: dict[str, Any] | None = Depends(auth.usuario_opcional)) -> dict[str, Any]:
    """200 SIEMPRE, nunca 401: el cliente decide qué pintar sin manejar errores."""
    return _cuerpo_yo(usuario)


@app.delete("/api/yo")
def api_borrar_cuenta(
    request: Request,
    respuesta: Response,
    cuerpo: CuerpoBorrarCuenta,
    usuario: dict[str, Any] = Depends(auth.usuario_actual),
):
    """Derecho de supresión. Aquí SÍ se van los informes por cascada: es lo que
    diferencia el borrado voluntario de la purga de anónimos inactivos."""
    if cuerpo.confirmacion != "BORRAR":
        raise HTTPException(
            status_code=400, detail='Para borrar la cuenta hay que confirmar con la palabra BORRAR.'
        )
    db.borrar_usuario(usuario["id"])
    auth.quitar_cookie(respuesta)
    respuesta.status_code = 204
    return respuesta


@app.get("/api/yo/export")
def api_exportar(usuario: dict[str, Any] = Depends(auth.usuario_actual)):
    """Todo lo que hay de esta persona, en un JSON. Cuatro SELECT y cierra los
    artículos 15 y 20 del RGPD sin montar un panel."""
    informes = []
    for fila in db.listar_informes_de(usuario["id"], limite=200):
        completo = db.obtener_informe(int(fila["id"]))
        if completo is not None:
            informes.append(completo)

    datos = {
        "usuario": {k: v for k, v in usuario.items() if k != "google_sub"},
        "borrador": db.obtener_borrador(usuario["id"]),
        "borrador_descartado": db.ultimo_descartado(usuario["id"]),
        "informes": informes,
    }
    return JSONResponse(
        datos,
        headers={"Content-Disposition": 'attachment; filename="mis-datos-branding.json"'},
    )


# ------------------------------------------------------------------ borrador

@app.put("/api/borrador")
def api_guardar_borrador(
    request: Request,
    respuesta: Response,
    cuerpo: CuerpoBorrador,
    usuario: dict[str, Any] = Depends(auth.usuario_garantizado),
) -> dict[str, Any]:
    """Autoguardado. `contestadas` lo recalcula SIEMPRE el servidor: el número
    del cliente es cosmético, y dos implementaciones de la misma regla acaban
    divergiendo justo el día que hay que arbitrar un conflicto."""
    if _tamano(request) > TOPE_BORRADOR:
        raise HTTPException(status_code=413, detail="Borrador demasiado grande.")

    try:
        salida = db.guardar_borrador(
            usuario["id"],
            cuerpo.respuestas.model_dump(),
            cuerpo.paso,
            min(cuerpo.ronda, scoring.MAX_RONDAS_TIBIEZA),
            cuerpo.ultimo_id,
            cuerpo.version,
        )
    except db.ConflictoVersion as e:
        # 409 con las cifras del servidor. Se responde con la Response inyectada
        # y no con una JSONResponse nueva: si no, se pierde el Set-Cookie que
        # usuario_garantizado acaba de poner y el siguiente PUT vuelve a chocar.
        respuesta.status_code = 409
        return {"conflicto": True, "servidor": e.servidor}
    return salida


@app.get("/api/borrador")
def api_leer_borrador(usuario: dict[str, Any] | None = Depends(auth.usuario_opcional)):
    if usuario is None:
        return Response(status_code=204)
    borrador = db.obtener_borrador(usuario["id"])
    if borrador is None:
        return Response(status_code=204)
    return _cuerpo_borrador(borrador)


@app.post("/api/borrador/descartar")
def api_descartar_borrador(
    cuerpo: CuerpoDescartar,
    usuario: dict[str, Any] = Depends(auth.usuario_actual),
) -> dict[str, Any]:
    """«Empezar de cero» sin destruir nada: la fila se archiva en
    borradores_descartados y se puede recuperar."""
    db.descartar_borrador(usuario["id"], cuerpo.motivo)
    return {"archivado": True}


@app.post("/api/borrador/recuperar")
def api_recuperar_borrador(
    usuario: dict[str, Any] = Depends(auth.usuario_actual),
) -> dict[str, Any]:
    """El «usar el otro» de la tarjeta de fusión."""
    borrador = db.restaurar_descartado(usuario["id"])
    if borrador is None:
        raise HTTPException(status_code=404, detail="No hay ningún borrador archivado.")
    return _cuerpo_borrador(borrador)


# ------------------------------------------------------------------ el muro

@app.post("/api/tibieza")
def api_tibieza(
    cuerpo: CuerpoTibieza,
    usuario: dict[str, Any] = Depends(auth.usuario_garantizado),
) -> dict[str, Any]:
    """¿El usuario está siendo tibio? Se llama antes de emitir el informe.

    Devuelve el índice, el veredicto y la lista exacta de preguntas donde se
    escondió, para que el frontend se las devuelva sin el punto medio. La
    `ronda` sale de la fila del borrador: mientras la mandaba el cliente,
    recargar la página la reseteaba a 0 y el tope de rondas no ataba nada.
    """
    respuestas = cuerpo.respuestas.model_dump()
    ronda = _ronda_del_muro(usuario["id"], cuerpo.ronda, confiar_en_el_cliente=True)
    salida = _evaluar_definicion(respuestas, ronda)
    if salida["veredicto"].get("repetir"):
        _fijar_ronda(usuario["id"], ronda + 1, respuestas)
    return salida


@app.post("/api/informe")
def api_crear_informe(
    respuesta: Response,
    cuerpo: CuerpoInforme,
    usuario: dict[str, Any] = Depends(auth.usuario_garantizado),
) -> dict[str, Any]:
    """La puerta de verdad del muro.

    /api/tibieza era una cortesía del navegador: un curl directo a esta ruta
    emitía el informe tibio igual. Ahora el veredicto se calcula aquí ANTES de
    guardar y, si dice repetir, esto responde 409 con el mismo cuerpo que
    /api/tibieza para que el cliente reutilice `insertarDesempate`.

    La ronda sale SOLO de la fila del borrador. Aquí no hay parámetro de ronda
    ni en el cuerpo ni en cabecera a propósito: cualquier número que ponga el
    cliente es una llave para saltarse el muro, y no hace falta ninguno porque
    cada 409 sube la ronda en la base.
    """
    respuestas = cuerpo.model_dump(exclude={"clave_idem"})
    ronda = _ronda_del_muro(usuario["id"], 0, confiar_en_el_cliente=False)

    evaluacion = _evaluar_definicion(respuestas, ronda)
    if evaluacion["veredicto"].get("repetir"):
        _fijar_ronda(usuario["id"], ronda + 1, respuestas)
        respuesta.status_code = 409
        return evaluacion

    resultado = _construir(respuestas, ronda)
    informe_id, token = db.guardar_informe(
        respuestas,
        _sin_svg(resultado),
        usuario_id=usuario["id"],
        clave_idem=cuerpo.clave_idem,
    )
    # El borrador NO se borra: «volver a hacerlo» no puede destruir el intento
    # anterior. Solo se le anota de qué informe salió.
    db.marcar_borrador_enviado(usuario["id"], informe_id)
    return {"id": informe_id, "token_acceso": token, "resultado": resultado}


@app.post("/api/informe/{informe_id}/ia")
def api_recomendaciones(
    informe_id: int,
    forzar: int = 0,
    usuario: dict[str, Any] = Depends(auth.usuario_actual),
) -> dict[str, Any]:
    """Llama al modelo. Se separa de la creación del informe para que el usuario
    vea su resultado al instante y solo espere si pide las recomendaciones.

    El token de lectura NO abre esta ruta: compartir un informe no puede
    significar compartir la clave de API del dueño.
    """
    registro_informe = db.obtener_informe(informe_id)
    if registro_informe is None or registro_informe["usuario_id"] != usuario["id"]:
        raise HTTPException(status_code=404, detail="Informe no encontrado")

    # (b) Idempotencia: lo ya generado se devuelve sin gastar una llamada.
    if registro_informe["recomendaciones"] is not None and not forzar:
        return registro_informe["recomendaciones"]

    # (c) Techo global del servidor, contado en la tabla de eventos.
    if db.contar_eventos("ia", _ahora_menos(hours=24)) >= TOPE_IA_DIARIO:
        raise HTTPException(
            status_code=429,
            detail="Hoy ya se han generado demasiadas recomendaciones. Prueba mañana.",
        )

    # (d) Cupo por informe. Se reserva ANTES de llamar al modelo y en su propia
    # transacción: dos peticiones simultáneas no pueden gastar cuatro llamadas.
    if db.reservar_intento_ia(informe_id, TOPE_IA_POR_INFORME) is None:
        raise HTTPException(
            status_code=429,
            detail=f"Ya has generado {TOPE_IA_POR_INFORME} veces las recomendaciones de este informe.",
        )

    # El import va aquí dentro: la capa de IA carga SDK y .env, y quien solo
    # rellena el cuestionario no tiene por qué pagar ese arranque.
    from . import ia

    resultado = _construir(
        registro_informe["respuestas"], _ronda_guardada(registro_informe["resultado"])
    )
    dossier = informe_mod.dossier_para_ia(registro_informe["respuestas"], resultado)

    try:
        salida = ia.generar_recomendaciones(dossier)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    datos = salida.model_dump()
    db.guardar_recomendaciones(informe_id, datos)
    db.registrar_evento(usuario["id"], "ia", clave=str(informe_id))
    return datos


# ------------------------------------------------------------------ informes

@app.get("/informe/{informe_id}", response_class=HTMLResponse)
def ver_informe(
    request: Request,
    informe_id: int,
    t: str | None = None,
    usuario: dict[str, Any] | None = Depends(auth.usuario_opcional),
):
    reg = _informe_accesible(informe_id, usuario, t)
    resultado = _construir(reg["respuestas"], _ronda_guardada(reg["resultado"]))
    return plantillas.TemplateResponse(
        request,
        "resultado.html",
        {
            "informe": reg,
            "r": resultado,
            "recomendaciones": reg["recomendaciones"],
            # Para que el enlace del PDF y el de compartir arrastren el token
            # cuando quien mira no es el dueño.
            "t": t,
            "es_dueno": bool(usuario and reg["usuario_id"] == usuario["id"]),
        },
    )


@app.get("/informe/{informe_id}/pdf")
def descargar_pdf(
    informe_id: int,
    t: str | None = None,
    usuario: dict[str, Any] | None = Depends(auth.usuario_opcional),
):
    reg = _informe_accesible(informe_id, usuario, t)
    resultado = _construir(reg["respuestas"], _ronda_guardada(reg["resultado"]))

    try:
        bytes_pdf = pdf.generar(reg, resultado, reg["recomendaciones"])
    except RuntimeError as e:
        # Falta GTK/Pango en el servidor: es un 503, no un 500 con traza. El
        # informe web sigue funcionando y el mensaje dice exactamente qué falta.
        raise HTTPException(status_code=503, detail=str(e)) from e

    # El nombre del fichero ya no lleva el nombre de la persona: un PDF en la
    # carpeta de descargas compartida no tiene por qué cantar de quién es.
    sufijo = str(reg["token_acceso"] or informe_id)[:8]
    return Response(
        content=bytes_pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="branding-{sufijo}.pdf"'},
    )


@app.get("/api/yo/informes")
def api_mis_informes(
    usuario: dict[str, Any] = Depends(auth.usuario_actual),
) -> list[dict[str, Any]]:
    return db.listar_informes_de(usuario["id"])


@app.get("/admin/informes")
def api_admin_informes(x_admin_token: str | None = Header(None)) -> list[dict[str, Any]]:
    """El listado global que antes servía /api/informes a cualquiera.

    Sin ADMIN_TOKEN configurado la ruta no existe (404): una puerta sin llave es
    peor que ninguna puerta.
    """
    esperado = os.environ.get("ADMIN_TOKEN", "").strip()
    if not esperado:
        raise HTTPException(status_code=404, detail="No encontrado")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, esperado):
        raise HTTPException(status_code=404, detail="No encontrado")
    return db.listar_informes()
