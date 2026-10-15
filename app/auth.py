"""Identidad: entrar con Google o entrar sin cuenta, y sesión por token opaco.

Dos decisiones que explican todo lo demás:

1. El ID token de Google se verifica LOCALMENTE con google-auth (firma, emisor,
   caducidad y `aud`), no llamando al endpoint `tokeninfo`. tokeninfo está
   documentado como herramienta de depuración con cuota, y cada login se comería
   un hilo del threadpool esperando una respuesta ajena. `audience` es SIEMPRE
   CLIENT_ID: con audience=None se aceptaría un ID token legítimo de Google
   emitido para OTRA aplicación, que es exactamente el agujero.

2. La sesión es un TOKEN OPACO de 256 bits guardado como sha256 en la tabla
   `sesiones`, no una cookie firmada. Una cookie firmada no se revoca, no
   permite «salir de todos los dispositivos» y no ahorra la fila: de todas
   formas hace falta un usuario en la base para colgar el borrador. Además
   itsdangerous no está instalado, así que firmar tampoco salía gratis.

Sin GOOGLE_CLIENT_ID el módulo entra en modo degradado: google_activo() es
False, la plantilla no carga el script de Google y «continuar sin cuenta» sigue
funcionando igual. Nadie se queda fuera por una variable de entorno vacía.

Este módulo NO importa app.main ni app.informe: solo db. Cualquier import hacia
arriba monta un círculo.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

import google.auth.exceptions
import google.auth.transport.requests
import requests
from dotenv import load_dotenv
from fastapi import HTTPException, Request, Response
from google.oauth2 import id_token

from . import db

# El único sitio del proyecto que cargaba el .env era app/ia/__init__.py, y se
# importa tarde y solo si alguien pide recomendaciones. Aquí hace falta antes:
# CLIENT_ID se lee al importar. load_dotenv() no pisa variables ya definidas.
load_dotenv()

COOKIE_NOMBRE = "sesion"
DIAS_SESION = 365
DIAS_ROTACION = 30          # rotación preventiva del token de sesión
DIAS_RECLAMACION_MAX = 30   # antigüedad máxima de una sesión anónima reclamable
HORAS_RENOVACION = 24       # como mucho una escritura al día por sesión

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()

# Sesión HTTP de módulo: reutiliza la conexión TLS con googleapis.com. El coste
# real de la verificación local es UN GET de certificados por LOGIN, no por
# petición. Si algún día hay volumen: instalar cachecontrol y pasar su sesión.
_SESION_HTTP = requests.Session()


class ErrorAuth(Exception):
    """Cualquier fallo de acceso. El motivo va en args[0] para el registro;
    al usuario se le devuelve siempre el mismo 401, sin pistas."""


class DatosGoogle(NamedTuple):
    sub: str
    email: str | None
    email_verificado: bool
    nombre: str | None
    foto_url: str | None


def google_activo() -> bool:
    return bool(CLIENT_ID)


def cookie_segura() -> bool:
    return os.environ.get("COOKIE_SEGURA") == "1"


# ------------------------------------------------------------------ ID token

def verificar_id_token(credential: str) -> DatosGoogle:
    """Verificación local de la firma del ID token del botón de Google.

    Lo que la librería comprueba sola: firma, `iss`, `exp` y `aud`. Lo que NO
    comprueba y hacemos aquí: `email_verified`. Si es falso el acceso sigue
    adelante, pero el email queda a NULL: la identidad es `sub` y solo `sub`,
    porque Google permite cambiar el email de una cuenta. Por eso google_sub es
    UNIQUE y email no lo es.
    """
    if not CLIENT_ID:
        raise ErrorAuth("sin_client_id")          # el endpoint lo traduce a 503
    if not isinstance(credential, str) or not (100 < len(credential) < 4096):
        raise ErrorAuth("credential_malformado")
    try:
        datos = id_token.verify_oauth2_token(
            credential,
            google.auth.transport.requests.Request(session=_SESION_HTTP),
            CLIENT_ID,                            # NUNCA audience=None
            clock_skew_in_seconds=10,
        )
    except (ValueError, google.auth.exceptions.GoogleAuthError) as e:
        # Se distingue el fallo de red del token inválido: sin salida a
        # googleapis.com el botón de Google falla y el diagnóstico no es obvio.
        motivo = "sin_red" if isinstance(e, google.auth.exceptions.TransportError) else "token_invalido"
        raise ErrorAuth(motivo) from e

    if datos.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise ErrorAuth("emisor_no_valido")
    sub = datos.get("sub")
    if not sub:
        raise ErrorAuth("sin_sub")

    verificado = datos.get("email_verified") is True
    return DatosGoogle(
        sub=str(sub),
        email=datos.get("email") if verificado else None,
        email_verificado=verificado,
        nombre=datos.get("name") or datos.get("given_name"),
        foto_url=datos.get("picture"),
    )


# ------------------------------------------------------------------ token y huellas

def nuevo_token() -> str:
    return secrets.token_urlsafe(32)              # 256 bits


def id_de_token(token: str) -> str:
    """El id de sesión es el sha256 del token. En la base no entra el secreto."""
    return db.id_de_token(token)


def hash_ua(request: Request) -> str | None:
    """sha256 del User-Agent truncado a 16 hex. No se guarda en claro: sirve
    para el guardián de reclamación, no para llevar un registro de navegación."""
    ua = request.headers.get("user-agent")
    if not ua:
        return None
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()[:16]


def ip_trunc(request: Request) -> str | None:
    """/24 en IPv4 y /48 en IPv6. Nunca la IP entera: con esto basta para
    limitar los intentos de acceso por conexión y no convierte la base en un
    registro de quién se conecta desde dónde."""
    cliente = request.client
    if cliente is None or not cliente.host:
        return None
    try:
        ip = ipaddress.ip_address(cliente.host)
    except ValueError:
        return None
    red = ipaddress.ip_network(f"{ip}/{24 if ip.version == 4 else 48}", strict=False)
    return str(red)


# ------------------------------------------------------------------ cookie

def poner_cookie(respuesta: Response, token: str) -> None:
    """httponly: un XSS no se lleva la sesión. samesite lax: un POST de otro
    origen no lleva la cookie. Sin `domain`: cookie de host, ningún subdominio
    la ve. `secure` sale del .env porque COOKIE_SEGURA=1 sobre http hace que el
    navegador la descarte SIN un solo error visible."""
    respuesta.set_cookie(
        COOKIE_NOMBRE,
        token,
        httponly=True,
        samesite="lax",
        secure=cookie_segura(),
        max_age=60 * 60 * 24 * DIAS_SESION,
        path="/",
    )


def quitar_cookie(respuesta: Response) -> None:
    respuesta.delete_cookie(
        COOKIE_NOMBRE, path="/", samesite="lax", secure=cookie_segura()
    )


# ------------------------------------------------------------------ sesión

def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def sesion_actual(request: Request) -> dict[str, Any] | None:
    """Helper, no dependencia. Devuelve la fila de sesión con el usuario dentro
    y el token en `_token`, o None si no hay, caducó o el usuario está borrado."""
    token = request.cookies.get(COOKIE_NOMBRE)
    if not token:
        return None
    s = db.obtener_sesion(id_de_token(token))
    if s is None:
        return None
    s["_token"] = token
    return s


def usuario_opcional(request: Request) -> dict[str, Any] | None:
    s = sesion_actual(request)
    if s is None:
        return None
    # Renovación deslizante, con tope de una escritura al día por sesión: un
    # UPDATE por petición sobraría y en SQLite se nota.
    if s["visto_en"] < (_ahora() - timedelta(hours=HORAS_RENOVACION)).isoformat():
        db.tocar_sesion(s["id"], DIAS_SESION)
        db.tocar_usuario(s["usuario_id"])
    return s["usuario"]


def usuario_actual(request: Request) -> dict[str, Any]:
    u = usuario_opcional(request)
    if u is None:
        raise HTTPException(
            status_code=401, detail="No hay sesión. Recarga la página y entra otra vez."
        )
    return u


def usuario_garantizado(request: Request, respuesta: Response) -> dict[str, Any]:
    """El «sí o sí» del dueño: aquí nadie se queda sin fila donde guardar.

    Si el POST de acceso falló antes, PUT /api/borrador y POST /api/informe
    siguen funcionando: se crea el usuario anónimo y se pone la cookie en la
    misma respuesta, en vez de devolver un 401 y dejar un callejón sin salida.
    """
    s = sesion_actual(request)
    if s is not None:
        if s["visto_en"] < (_ahora() - timedelta(hours=HORAS_RENOVACION)).isoformat():
            db.tocar_sesion(s["id"], DIAS_SESION)
            db.tocar_usuario(s["usuario_id"])
        # Rotación preventiva: sesión vieja, token nuevo y fila vieja borrada.
        # Solo se puede hacer aquí y en abrir_sesion, que son los dos sitios con
        # una Response a mano para reescribir la cookie.
        if s["creado_en"] < (_ahora() - timedelta(days=DIAS_ROTACION)).isoformat():
            abrir_sesion(respuesta, s["usuario_id"], request)
            db.borrar_sesion(s["id"])
        return s["usuario"]

    uid = db.crear_usuario_anonimo()
    abrir_sesion(respuesta, uid, request)
    db.registrar_evento(uid, "anonimo", valor="implicito")
    usuario = db.obtener_usuario(uid)
    assert usuario is not None  # acabamos de crearlo en esta misma petición
    return usuario


def abrir_sesion(respuesta: Response, usuario_id: int, request: Request) -> str:
    token = nuevo_token()
    db.crear_sesion(
        id_de_token(token), usuario_id, hash_ua(request), ip_trunc(request), DIAS_SESION
    )
    poner_cookie(respuesta, token)
    return token


def cerrar_sesion(request: Request, respuesta: Response) -> None:
    """Idempotente: sin cookie o con una cookie muerta, también sale bien."""
    token = request.cookies.get(COOKIE_NOMBRE)
    if token:
        db.borrar_sesion(id_de_token(token))
    quitar_cookie(respuesta)


# ------------------------------------------------------------------ reclamación

def anonimo_reclamable(request: Request) -> int | None:
    """Guardián de reclamación: ¿esta sesión anónima puede fusionarse con la
    cuenta de Google que está entrando?

    El peligro no está en la fusión, está en la promoción: con una cookie
    anónima robada, un atacante inicia sesión con SU Google y un solo UPDATE le
    regala el borrador Y los informes de la víctima, sin fusión que arbitrar ni
    archivo donde mirar. Por eso se exige que la sesión sea reciente y que el
    User-Agent coincida.

    Se equivoca a la baja a propósito: quien cambie de navegador o actualice el
    sistema pierde el ua_hash y entra limpio; su borrador anónimo se queda en la
    base (huérfano hasta la purga) y se puede recuperar a mano. Exigir además la
    IP rompería a cualquiera que cambie de red.
    """
    s = sesion_actual(request)
    if s is None:
        return None
    usuario = s["usuario"]
    if not usuario or not usuario["anonimo"]:
        return None
    if s["creado_en"] < (_ahora() - timedelta(days=DIAS_RECLAMACION_MAX)).isoformat():
        return None
    if s["ua_hash"] != hash_ua(request):
        return None
    return int(s["usuario_id"])


def entrar_con_google(
    request: Request, respuesta: Response, datos: DatosGoogle
) -> tuple[int, dict[str, Any] | None]:
    """Paso completo del acceso con Google: guardián, fusión en la base y cookie
    nueva. Devuelve (usuario_id, info_fusion|None).

    La cookie nueva es obligatoria al subir de nivel (anónimo → Google): token
    nuevo y filas de sesión anteriores borradas dentro de la misma transacción,
    para cerrar la fijación de sesión.
    """
    usuario_id, token, fusion = db.entrar_con_google(
        sub=datos.sub,
        email=datos.email,
        email_verificado=datos.email_verificado,
        nombre=datos.nombre,
        foto_url=datos.foto_url,
        usuario_anonimo_id=anonimo_reclamable(request),
        ua_hash=hash_ua(request),
        ip_trunc=ip_trunc(request),
    )
    poner_cookie(respuesta, token)
    return usuario_id, fusion
