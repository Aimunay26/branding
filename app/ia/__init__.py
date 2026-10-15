"""Recomendaciones de branding por IA — capa que elige el proveedor.

Única capa del proyecto que toca una API key. Conviven dos proveedores:
Gemini (por defecto: rápido y barato) y Claude. Se elige con PROVEEDOR_IA en el
.env; MODELO_IA fija el modelo concreto dentro del proveedor elegido.

La salida es un objeto Pydantic validado (esquema.Salida). Si el modelo se sale
del esquema o entrega tres direcciones que son la misma idea, la post-validación
de `validacion.py` lo detecta y se reintenta una sola vez con la lista de reglas
incumplidas. Ninguno de los dos SDK reintenta por su cuenta: lo que hacen es
restringir la generación al esquema, que no es lo mismo.

Techo de gasto: DOS llamadas por informe. Ni una más.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from dotenv import load_dotenv

from . import claude, gemini, validacion
from .esquema import Recomendacion, Salida, construir_reintento  # re-export
from .tipos import ResultadoIA

load_dotenv()

PROVEEDOR_POR_DEFECTO = "gemini"
_PROVEEDORES = {"gemini": gemini, "claude": claude}
_PREFIJOS = {"gemini": "gemini-", "claude": "claude-"}

registro = logging.getLogger("branding.ia")


def _proveedor() -> tuple[str, Any]:
    nombre = (os.environ.get("PROVEEDOR_IA") or PROVEEDOR_POR_DEFECTO).lower()
    mod = _PROVEEDORES.get(nombre)
    if mod is None:
        raise RuntimeError(
            f"PROVEEDOR_IA='{nombre}' no reconocido. Usa 'gemini' o 'claude'."
        )

    # PROVEEDOR_IA=gemini con MODELO_IA=claude-opus-5 se mandaba tal cual a
    # Google, y lo que veía el usuario era el 404 crudo de Google. Es un error de
    # configuración y se dice como tal.
    modelo = os.environ.get("MODELO_IA")
    if modelo and modelo not in mod.TARIFAS and not modelo.startswith(_PREFIJOS[nombre]):
        raise RuntimeError(
            f"MODELO_IA='{modelo}' no es un modelo de {nombre}. Cambia uno de "
            "los dos en .env."
        )
    return nombre, mod


def _version_libreria(nombre: str) -> str:
    """La versión del SDK. Cuando esto falle en el portátil de otra persona, es el
    primer dato que va a hacer falta, y hasta hoy no se registraba ninguno."""
    try:
        if nombre == "claude":
            import anthropic

            return anthropic.__version__
        import google.genai as g

        return getattr(g, "__version__", "?")
    except Exception:  # noqa: BLE001 — el registro nunca puede tumbar la petición
        return "?"


def generar_recomendaciones(dossier: dict[str, Any]) -> ResultadoIA:
    """Pide las 3 recomendaciones, las valida y reintenta UNA vez si no cumplen.

    Lanza RuntimeError si la API falla o si el segundo intento sigue incumpliendo
    las reglas duras; main.py lo convierte en un 502 con mensaje en español.
    """
    nombre, mod = _proveedor()
    modelo = mod.modelo_activo()
    arranque = time.monotonic()

    salida, uso = mod.generar(dossier)
    coste, tok_in, tok_out = mod.coste_estimado(uso, modelo)
    intentos = 1

    resultado_validacion = validacion.validar(salida, dossier)
    duros = resultado_validacion["duros"]
    blandos = list(resultado_validacion["blandos"])

    if duros:
        registro.info(
            "ia: primer intento rechazado por %d regla(s) dura(s): %s",
            len(duros),
            " | ".join(duros),
        )
        extra = [
            ("asistente", salida.model_dump_json()),
            ("usuario", construir_reintento(dossier, duros)),
        ]
        salida, uso = mod.generar(dossier, historial_extra=extra)
        coste_2, in_2, out_2 = mod.coste_estimado(uso, modelo)
        coste += coste_2
        tok_in += in_2
        tok_out += out_2
        intentos = 2

        segunda = validacion.validar(salida, dossier)
        blandos.extend(segunda["blandos"])
        if segunda["duros"]:
            # Aquí se para. Un tercer intento no es rigor: es una factura abierta
            # en un endpoint que todavía no pide autenticación.
            raise RuntimeError(
                "Las recomendaciones no cumplen el encargo: "
                + "; ".join(segunda["duros"])
            )

    ms = int((time.monotonic() - arranque) * 1000)
    registro.info(
        "ia: proveedor=%s modelo=%s sdk=%s tokens=%d/%d coste=%.4f USD "
        "intentos=%d avisos=%d ms=%d",
        nombre,
        modelo,
        _version_libreria(nombre),
        tok_in,
        tok_out,
        coste,
        intentos,
        len(blandos),
        ms,
    )

    return ResultadoIA(
        salida=salida,
        proveedor=nombre,
        modelo=modelo,
        tokens_entrada=tok_in,
        tokens_salida=tok_out,
        coste_usd=coste,
        intentos=intentos,
        avisos_validacion=blandos,
        ms=ms,
    )


__all__ = [
    "generar_recomendaciones",
    "Salida",
    "Recomendacion",
    "ResultadoIA",
    "validacion",
]
