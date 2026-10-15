"""Proveedor de recomendaciones con Claude (Anthropic)."""

from __future__ import annotations

import os
from typing import Any

import anthropic
import pydantic

from .esquema import SISTEMA, Salida, construir_prompt

MODELO_POR_DEFECTO = "claude-opus-5"

TARIFAS = {  # (entrada, salida) por millón de tokens, en dólares
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# El pensamiento adaptativo come del mismo presupuesto que la salida, y el
# esquema pasó de 3 a 17 campos de primer nivel. Con 16000 el corte por longitud
# dejó de ser una hipótesis.
MAX_TOKENS = 32000

# El SDK trae 10 minutos de timeout y dos reintentos: en el peor caso son media
# hora bloqueando uno de los 40 hilos del threadpool, porque el endpoint de
# main.py es `def` y no `async def`, con el navegador esperando al otro lado.
TIMEOUT_S = 120.0


def _cliente() -> anthropic.Anthropic:
    # También vale un perfil de `ant auth login`, que deja ANTHROPIC_AUTH_TOKEN:
    # rechazar esa instalación diciendo «falta la API key» era mentira.
    if not (
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    ):
        raise RuntimeError(
            "Falta ANTHROPIC_API_KEY. Copia .env.example a .env y pon tu clave "
            "de https://console.anthropic.com/settings/keys, o inicia sesión con "
            "un perfil (`ant auth login`), que deja ANTHROPIC_AUTH_TOKEN."
        )
    return anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=2)


def modelo_activo(modelo: str | None = None) -> str:
    return modelo or os.environ.get("MODELO_IA") or MODELO_POR_DEFECTO


def generar(
    dossier: dict[str, Any],
    modelo: str | None = None,
    historial_extra: list[tuple[str, str]] | None = None,
) -> tuple[Salida, Any]:
    """Devuelve (salida, uso). El uso ya no se tira: sin él, coste_estimado no
    es «código sin usar», es una función imposible de llamar con datos reales.

    `historial_extra` son los turnos que se añaden después del primer prompt para
    el reintento correctivo: [("asistente", json_anterior), ("usuario", correcciones)].
    """
    cliente = _cliente()
    modelo = modelo_activo(modelo)

    mensajes: list[dict[str, Any]] = [
        {"role": "user", "content": construir_prompt(dossier)}
    ]
    for rol, texto in historial_extra or []:
        mensajes.append(
            {"role": "assistant" if rol == "asistente" else "user", "content": texto}
        )

    if not hasattr(cliente.messages, "parse"):
        raise RuntimeError(
            "Tu versión del paquete anthropic es demasiado antigua para las "
            "salidas estructuradas. Actualiza con `pip install -U anthropic`."
        )

    try:
        respuesta = cliente.messages.parse(
            model=modelo,
            max_tokens=MAX_TOKENS,
            system=SISTEMA,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            messages=mensajes,
            output_format=Salida,
        )
    except anthropic.AuthenticationError as e:
        raise RuntimeError(
            "La API key de Anthropic no es válida. Revisa ANTHROPIC_API_KEY en .env."
        ) from e
    except anthropic.RateLimitError as e:
        raise RuntimeError(
            "Has superado el límite de peticiones de la API. Espera un minuto y "
            "vuelve a intentarlo."
        ) from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError(
            "No se pudo conectar con la API de Anthropic. Revisa tu conexión."
        ) from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Error de la API ({e.status_code}): {e.message}") from e
    except pydantic.ValidationError as e:
        # El corte por longitud revienta AQUÍ DENTRO, no al leer la salida
        # después: messages.parse intenta validar un JSON truncado. Sin este
        # except, FastAPI devuelve un 500 con traza en vez del 502 con mensaje en
        # español, porque el `except RuntimeError` de main.py no lo captura.
        raise RuntimeError(
            f"El modelo no devolvió el formato esperado (posible corte por "
            f"longitud): {e}"
        ) from e
    except TypeError as e:
        raise RuntimeError(
            f"El SDK de anthropic instalado no acepta uno de los parámetros "
            f"({e}). Actualiza el paquete."
        ) from e

    if respuesta.stop_reason == "refusal":
        raise RuntimeError(
            "El modelo declinó generar las recomendaciones para este contenido."
        )
    if respuesta.stop_reason == "max_tokens":
        raise RuntimeError(
            "La respuesta se cortó por longitud. Vuelve a intentarlo; si repite, "
            "sube max_tokens."
        )
    if respuesta.parsed_output is None:
        raise RuntimeError("El modelo no devolvió contenido analizable.")

    # Cuando el frontend tenga AbortController y bandera de envío, lo preferible
    # es `with cliente.messages.stream(...) as s: s.get_final_message()`: quita el
    # timeout HTTP como límite de una salida grande. Hoy tocaría el fetch de
    # resultado.html y de form.js, que son de otra mano.
    return respuesta.parsed_output, respuesta.usage


def coste_estimado(uso: Any, modelo: str | None = None) -> tuple[float, int, int]:
    """Devuelve (coste_usd, tokens_entrada, tokens_salida).

    Sin valor por omisión en `modelo`: con el que había, un cálculo de sonnet
    salía un 50 % caro porque cogía la tarifa de opus.
    """
    modelo = modelo_activo(modelo)
    entrada, salida = TARIFAS.get(modelo, TARIFAS[MODELO_POR_DEFECTO])
    tok_in = int(getattr(uso, "input_tokens", 0) or 0)
    tok_out = int(getattr(uso, "output_tokens", 0) or 0)
    return (tok_in * entrada + tok_out * salida) / 1_000_000, tok_in, tok_out
