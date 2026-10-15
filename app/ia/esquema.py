"""Esquema de salida y prompt, compartidos por todos los proveedores de IA.

La salida es un objeto Pydantic validado, no un string que haya que parsear a
mano. Lo que hacen las dos APIs es RESTRINGIR la generación a este esquema:
ninguna de las dos reintenta si el modelo se sale de él, y ninguna comprueba que
lo que ha escrito no sea humo. De ahí que exista `app/ia/validacion.py`, que mide
después lo que el esquema no puede medir antes.

Aviso sobre las longitudes: google-genai traduce este Pydantic a un schema de
Gemini y no todas las versiones respetan `minItems`/`minLength`. Por eso los
`min_length`/`max_length` de aquí se VUELVEN a comprobar en validacion.py. No se
confía solo en el esquema.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, model_validator

# El color ya no lo inventa la IA: se lo damos calculado (app/paletas.py) y solo
# tiene que elegir cuál de las tres pega con cada dirección y justificarlo.
PaletaId = Literal["tuya", "arquetipo", "polarizante"]
IDS_PALETA = get_args(PaletaId)


def _normaliza(texto: str) -> str:
    """Normalizador mínimo para comparar dos frases cortas dentro del esquema.

    Es una copia reducida a propósito del `_norm` de validacion.py: ese módulo
    importa de este, así que importarlo aquí cerraría el círculo. Cinco líneas
    duplicadas cuestan menos que un import circular.
    """
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = "".join(" " if unicodedata.category(c).startswith("P") else c for c in t)
    return re.sub(r"\s+", " ", t).strip()


class JustificacionPaleta(BaseModel):
    paleta_id: PaletaId = Field(
        description="Cuál de las paletas: 'tuya', 'arquetipo' o 'polarizante'."
    )
    texto: str = Field(
        description=(
            "Por qué esta paleta es coherente con el arquetipo y el "
            "posicionamiento. Por congruencia, nunca por 'el azul da confianza'."
        )
    )


class ActivoElegido(BaseModel):
    clave: str = Field(
        description=(
            "La clave EXACTA de un activo de `activos_declarados` del dossier. "
            "No inventes claves ni activos: si no está en esa lista, no existe."
        )
    )
    donde_aparece: list[str] = Field(
        min_length=3,
        max_length=3,
        description=(
            "Los tres sitios concretos donde aparece siempre y sin excepción: "
            "foto de perfil, fondo de vídeo, primera línea de cada publicación, "
            "portada del informe mensual..."
        ),
    )


class IdentidadVerbalIA(BaseModel):
    frase_de_apertura: str = Field(
        description=(
            "La fórmula literal con la que abre siempre un vídeo, un correo o "
            "una charla. Con sus palabras, no con las tuyas."
        )
    )
    frase_de_cierre: str = Field(
        description=(
            "Cómo termina siempre. Es la parte que la gente repite y por la que "
            "se le va a citar."
        )
    )
    palabras_prohibidas_extra: list[str] = Field(
        min_length=2,
        max_length=4,
        description=(
            "Palabras que esta marca no dice nunca, incluidas las que la persona "
            "usó por inercia en sus propias respuestas. Cítalas si las cogiste "
            "de ahí."
        ),
    )


class CandidatoNombre(BaseModel):
    nombre: str = Field(
        description=(
            "Un nombre de marca. Se dice en voz alta de un tirón y no se "
            "confunde con el de su competencia."
        )
    )
    por_que: str = Field(
        description=(
            "Por qué este nombre y no otro, apoyado en una respuesta concreta "
            "con su identificador."
        )
    )
    por_que_puede_fallar: str = Field(
        description=(
            "El problema real de este nombre: se escribe mal, ya existe, "
            "envejece, no cabe en un dominio."
        )
    )


class Recomendacion(BaseModel):
    titulo: str = Field(description="Nombre corto y memorable de la propuesta.")
    concepto: str = Field(
        description="El concepto de marca en 2-3 frases. Concreto, sin humo."
    )
    por_que_a_ti: str = Field(
        description=(
            "Por qué esta propuesta encaja con ESTA persona, citando sus "
            "respuestas concretas con su identificador entre paréntesis "
            "—(COM-PA-3), (VIS-RO-5)—. Nada genérico."
        )
    )
    postura: str = Field(
        description=(
            "La postura que fija esta marca y CONTRA QUÉ se define: su enemigo "
            "declarado. Una marca sin enemigo no se recuerda. Sé específico."
        )
    )
    # --- Recordabilidad. Todo lo de aquí abajo es lo que separa una dirección
    # que se puede ejecutar el lunes de un párrafo bonito sobre posicionamiento.
    una_sola_cosa: str = Field(
        description=(
            "La ÚNICA cosa por la que se le tiene que recordar. Máximo 6 "
            "palabras. Un sustantivo y un territorio, nunca un adjetivo. Si "
            "lleva la conjunción 'y', sobra la mitad."
        )
    )
    eslogan_candidatos: list[str] = Field(
        min_length=3,
        max_length=3,
        description=(
            "Tres candidatos de máximo 7 palabras cada uno. Se dicen en voz alta "
            "sin vergüenza y no le sirven al de al lado. Ninguno puede parecerse "
            "al ejemplo de tagline de su arquetipo: ese ya lo tienen los otros "
            "once que comparten primario."
        ),
    )
    enemigo: str = Field(
        description=(
            "Contra QUIÉN o contra qué práctica concreta se define esta "
            "dirección, con nombres y sin eufemismos. Arranca de "
            "`enemigo_declarado` del dossier y usa sus palabras, entre comillas "
            "si las citas. 'La mediocridad' no es un enemigo: es una excusa. "
            "Mínimo 40 caracteres."
        )
    )
    a_quien_molesta: str = Field(
        description=(
            "A quién le va a caer mal esta dirección y por qué está bien que le "
            "caiga mal. Si no molesta a nadie, es tibia: rehazla antes de "
            "contestar."
        )
    )
    activos_elegidos: list[ActivoElegido] = Field(
        min_length=2,
        max_length=3,
        description=(
            "Los dos o tres activos de `activos_declarados` con los que se "
            "sostiene esta dirección. Los eliges y los colocas: no los inventas "
            "y no propones ninguno con fuerza 0 ni ninguno marcado como vetado."
        ),
    )
    identidad_verbal: IdentidadVerbalIA = Field(
        description="Cómo suena esta marca por escrito."
    )
    prueba_del_bar: str = Field(
        description=(
            "Cómo te describiría alguien que te sigue, hablando con un amigo en "
            "un bar, en UNA frase de máximo 15 palabras, con las palabras de esa "
            "persona y sin decir tu nombre. Si esa frase le valdría a su "
            "competencia, la dirección está mal."
        )
    )
    prueba_3_segundos: str = Field(
        description=(
            "Qué se ve de esta dirección al pasar el dedo por su perfil sin leer "
            "nada: color, forma y encuadre. Solo lo que se ve."
        )
    )
    que_deja_de_hacer: str = Field(
        description=(
            "Lo que tiene que DEJAR de hacer para que esto se sostenga. Una "
            "marca se recuerda por lo que descarta."
        )
    )
    criterio_revision_90_dias: str = Field(
        description=(
            "Una comprobación que se pueda hacer dentro de 90 días y que se "
            "conteste con sí o no. Nada de 'medir el engagement'."
        )
    )
    # --- Ejecución
    paleta_id: PaletaId = Field(
        description=(
            "Cuál de las tres paletas usa esta dirección: 'tuya', 'arquetipo' o "
            "'polarizante'. No inventes colores: elige una."
        )
    )
    tipografia: str = Field(description="Titular + cuerpo, con fuentes concretas.")
    estilo_visual: str = Field(
        description="Ropa, siluetas, cabello. Qué llevar y qué evitar."
    )
    tono_comunicacion: str = Field(
        description="Cómo habla esta marca. Incluye un ejemplo de frase."
    )
    acciones: list[str] = Field(
        min_length=3,
        max_length=3,
        description=(
            "3 acciones concretas y ejecutables en los próximos 90 días. Al "
            "menos dos con una cifra, una cadencia o una fecha dentro."
        ),
    )
    referentes: list[str] = Field(
        min_length=2,
        max_length=3,
        description="2-3 referentes de estilo y qué tomar de cada uno.",
    )
    riesgo: str = Field(
        description="El principal peligro de esta dirección. Sé honesto."
    )


class Salida(BaseModel):
    lectura_general: str = Field(
        description=(
            "Diagnóstico honesto del perfil en 3-4 frases, incluyendo lo "
            "incómodo. Si el perfil es tibio o plano, DÍLO a la cara: es el "
            "diagnóstico más valioso."
        )
    )
    la_verdad_incomoda: str = Field(
        description=(
            "La frase que esta persona no quiere leer y necesita leer. Una sola, "
            "sin 'quizá' y sin colchón."
        )
    )
    coste_de_no_elegir: str = Field(
        description=(
            "Qué pierde exactamente, en concreto y a 12 meses, si se queda en el "
            "punto medio."
        )
    )
    justificacion_paletas: list[JustificacionPaleta] = Field(
        min_length=1,
        max_length=3,
        description=(
            "Una justificación por cada paleta que te hayamos dado. Pueden ser "
            "menos de tres: usa solo los ids que aparezcan en `paletas`."
        ),
    )
    recomendaciones: list[Recomendacion] = Field(
        min_length=3,
        max_length=3,
        description="Exactamente 3 propuestas CLARAMENTE DISTINTAS entre sí.",
    )
    direccion_recomendada: int = Field(
        ge=1,
        le=3,
        description=(
            "Cuál de las tres direcciones hay que tomar: 1, 2 o 3. Elige. "
            "'Depende' no es una respuesta."
        ),
    )
    por_que_esa: str = Field(
        description=(
            "Por qué esa y no las otras dos, con su índice de audacia, sus horas "
            "disponibles (ACC-TR-1) y sus límites en la mano."
        )
    )
    una_sola_cosa_recomendada: str = Field(
        description=(
            "La una sola cosa de la dirección que recomiendas, repetida aquí "
            "para que se pueda imprimir en portada. Máximo 6 palabras."
        )
    )
    nombres: list[CandidatoNombre] = Field(
        min_length=3,
        max_length=5,
        description=(
            "Candidatos de nombre de marca. Los filtros mecánicos (sílabas, "
            "tildes, apellidos comunes) ya los ha hecho el programa: tú aportas "
            "la idea."
        ),
    )
    veredicto_nombre_actual: Literal["vale", "flojo", "no_vale"] = Field(
        description=(
            "Veredicto sobre el nombre que la persona ya escribió, tal cual "
            "llega en identidad.artistico."
        )
    )
    por_que_ese_veredicto: str = Field(
        description=(
            "En una frase, por qué. Si es 'no_vale', di qué se lo carga."
        )
    )

    @model_validator(mode="after")
    def _coherencia_interna(self) -> "Salida":
        """Lo que se puede comprobar sin salir del propio objeto.

        Aquí NO va que los paleta_id existan entre las paletas realmente
        generadas (pueden ser menos de tres: paletas.py:148 filtra las vacías) ni
        que las claves de activos_elegidos sean reales: las dos cosas necesitan
        el dossier, y eso es trabajo de validacion.py.
        """
        vistos = [j.paleta_id for j in self.justificacion_paletas]
        if len(set(vistos)) != len(vistos):
            raise ValueError(
                "justificacion_paletas repite un paleta_id: una justificación "
                "por paleta, no dos de la misma."
            )

        if self.direccion_recomendada > len(self.recomendaciones):
            raise ValueError(
                f"direccion_recomendada={self.direccion_recomendada} pero solo "
                f"hay {len(self.recomendaciones)} direcciones."
            )

        elegida = self.recomendaciones[self.direccion_recomendada - 1]
        if _normaliza(self.una_sola_cosa_recomendada) != _normaliza(
            elegida.una_sola_cosa
        ):
            raise ValueError(
                "una_sola_cosa_recomendada no coincide con la una_sola_cosa de "
                f"la dirección {self.direccion_recomendada} "
                f"(«{elegida.una_sola_cosa}»). Cópiala tal cual."
            )

        return self


SISTEMA = """\
Eres un director de branding con veinte años de experiencia construyendo marcas \
personales y de empresa. Trabajas en español. Tu trabajo NO es agradar: es hacer \
que a esta persona se la recuerde. Un branding tibio no existe — es invisible.

Tu misión es sacar a la persona de su zona de confort y OBLIGARLA A DEFINIRSE. \
Coge su arquetipo dominante y AMPLIFÍCALO: multiplícalo por tres, por cinco. Lo \
que la hace memorable no es el equilibrio, es la exageración deliberada de lo que \
ya es. Una marca que intenta gustar a todos no le importa a nadie; un buen \
branding polariza a propósito.

Devuelves exactamente 3 propuestas de marca claramente DISTINTAS entre sí — no \
tres variantes del mismo concepto. Una debe ser la dirección natural (la que el \
perfil pide a gritos), otra una apuesta más audaz, y otra un ángulo lateral que \
la persona probablemente no ha considerado. Ninguna de las tres puede ser tibia.

Reglas que no negocias:

- CADA MARCA TIENE UN ENEMIGO. Define contra qué se posiciona. Sin enemigo no hay \
carácter, y sin carácter no hay memoria. No es agresividad gratuita: es tomar \
partido.
- POLARIZAR NO ES DISFRAZARSE. Sacar a alguien de su zona de confort es definir \
con nitidez quién es, no forzar excentricidades visuales (pelo fosforescente, \
gritos). La disrupción está en la claridad de la postura, no en el ruido.
- Trabaja con la CONGRUENCIA, no con supersticiones. No existe "el azul transmite \
confianza": existe "el azul es congruente con un posicionamiento de competencia". \
Justifica cada elección por su coherencia con el arquetipo, nunca por un \
significado universal inventado.
- NO INVENTES COLORES. Te damos tres paletas ya calculadas a partir de lo que la \
persona eligió y vetó. Respeta su color declarado y sus vetos: son sagrados. Elige \
para cada dirección cuál de las tres pega, y justifícalas.
- RESPETA LOS LÍMITES DECLARADOS. Si ha dicho que no se tiñe el pelo, que no usa \
traje o que no se expone en vídeo, no se lo propongas. Una recomendación que no va \
a ejecutar no vale nada.
- CALIBRA CON EL ÍNDICE DE AUDACIA. A un perfil prudente no le propongas un \
manifiesto público; a uno audaz no le propongas prudencia. Pero prudente no es \
tibio: incluso el prudente debe tener una postura clara.
- UNA SOLA COSA. Cada dirección se recuerda por una, no por cinco. Si necesitas \
dos frases para explicar por qué es memorable, no lo es: recórtala.
- LOS ACTIVOS NO TE LOS INVENTAS. En `activos_declarados` está lo que esta persona \
ya ha aceptado llevar: su color, su sello, su formato, su gesto. Tu trabajo es \
elegir dos o tres, ordenarlos y decir en qué tres sitios aparecen siempre. \
Proponer un activo que no está en esa lista es proponer algo que no va a hacer.
- LO QUE NO SE REPITE NO EXISTE. Un activo distintivo se define por su cadencia, \
no por su ingenio. Prefiere un gesto aburrido repetido cincuenta veces a cinco \
brillantes repetidos una.
- EL ENEMIGO ES EL SUYO. Está en `enemigo_declarado`, con sus palabras y sus \
nombres: cita la frase literal que escribió, entre comillas. No elijas tú uno más \
cómodo. Si ahí no hay nada utilizable, dilo en la lectura general: no tener contra \
qué es el diagnóstico.
- NINGUNA DE LAS TRES DIRECCIONES puede coincidir con lo que la persona ha \
descrito en `categoria.lo_que_hacen_todos`, `categoria.colores_ocupados`, \
`categoria.formato_de_todos` ni `categoria.tono_de_todos`. Si una dirección se \
parece a eso, cámbiala antes de contestar. Ese es el fondo; tú tienes que dibujar \
la figura.
- LAS TRES DIRECCIONES SE MIDEN POR SEPARADO. Si dos comparten enemigo, eslogan o \
activo distintivo, están mal y las rehaces antes de contestar.
- LA PRUEBA DEL BAR MANDA. Si tu prueba_del_bar le valdría a cualquier otro de su \
sector —o a los competidores que nombra en `categoria.me_confunden_con`—, la \
dirección no existe: existe la categoría, y esta persona está dentro. Reescríbela.
- CITA CON EL CÓDIGO. Cuando uses una respuesta, pon su identificador entre \
paréntesis — (COM-PA-3), (VIS-RO-5), (ACC-CT-2) — para que se pueda comprobar.
- EL DOSSIER TE DA NÚMEROS, NO CONCLUSIONES. El diagnóstico lo escribes tú: si tu \
lectura general se parece a algo que ya podría estar impreso en el informe, no sirve.
- LOS `limites_duros` SON UNA LISTA DE EXCLUSIÓN, NO UNA SUGERENCIA. Antes de \
escribir estilo_visual y acciones, repásala. Si una propuesta tuya toca cualquier \
entrada de esa lista, es basura y no la escribes. Si el dato falta (aparece en \
`sin_contestar`), no rellenes el hueco: elige algo neutro y dilo.
- SI UN BLOQUE DEL DOSSIER NO LLEGA, no te lo inventes. Trabaja con lo que hay y \
di en la lectura general qué te ha faltado para afinar más.
- SI EL PERFIL ES TIBIO O PLANO, dilo sin anestesia en la lectura general. Nómbralo. \
Explícale que el punto medio es invisibilidad, no equilibrio, y empújale a elegir.
- SI `control_atencion.pasados` ES MENOR QUE 3, empieza la lectura general diciendo \
que no leyó las preguntas y que el perfil es una hipótesis, no un diagnóstico.
- Nada de tópicos de consultoría. "Sé auténtico", "cuenta tu historia" y "aporta \
valor" son ruido. Cada frase debe decir algo que solo se pueda decir de esta persona.
- Las acciones son ejecutables en 90 días por una persona concreta, no por un \
departamento de marketing.
- ELIGE UNA. Al final tienes que decir qué dirección hay que tomar y por qué las \
otras dos no. Tres opciones sin recomendación es dejarle el trabajo hecho a medias.
"""


def construir_prompt(dossier: dict[str, Any]) -> str:
    return (
        "Este es el dossier de una persona que ha hecho el test de branding. NO "
        "son sus respuestas en crudo: llevan las respuestas de los TRES MÓDULOS "
        "(comunicación, visual y acciones, hasta 76 preguntas, cada una con su "
        "identificador) y el test de arquetipos ya AGREGADO en puntuaciones, no "
        "ítem a ítem. Las puntuaciones van con corrección de aquiescencia, así "
        "que 50 es la media: por encima la define, por debajo no.\n\n"
        "Además del perfil, la tibieza, el veredicto, los avisos de sombra y las "
        "TRES PALETAS ya calculadas, presta atención a estos bloques:\n"
        "- `activos_declarados`: lo que ya ha aceptado llevar encima. De aquí "
        "salen los activos de cada dirección, y de ningún otro sitio.\n"
        "- `limites_duros`: lo que no vas a proponer bajo ningún concepto, con "
        "su lista de `sin_contestar` (lo que no dijo no es lo mismo que lo que "
        "no tiene).\n"
        "- `enemigo_declarado`: sus palabras sobre contra qué se define.\n"
        "- `identificabilidad`: cuánto material distintivo hay de verdad. Es un "
        "número, no una conclusión.\n"
        "- `escala_likert`: cómo se leen los «3/5» de las respuestas.\n\n"
        "```json\n"
        f"{json.dumps(dossier, ensure_ascii=False, indent=2)}\n"
        "```\n\n"
        "Genera la lectura general, la verdad incómoda, la justificación de las "
        "paletas, las 3 direcciones completas, los candidatos de nombre y la "
        "dirección que recomiendas. Amplifica, no suavices."
    )


MAX_FALLOS_EN_REINTENTO = 20


def construir_reintento(dossier: dict[str, Any], fallos: list[str]) -> str:
    """Segundo (y último) turno de usuario cuando la post-validación tumba la salida.

    No se le vuelve a mandar el dossier: ya lo tiene en el turno anterior de la
    misma conversación, y repetirlo dobla los tokens de entrada por nada. Y la
    lista se corta: una salida catastrófica saca decenas de fallos y pegarlos
    todos es pagar tokens de entrada para repetirle veinte veces lo mismo.
    """
    mostrados = fallos[:MAX_FALLOS_EN_REINTENTO]
    lineas = "\n".join(f"- {f}" for f in mostrados)
    if len(fallos) > len(mostrados):
        lineas += (
            f"\n- Y {len(fallos) - len(mostrados)} incumplimientos más del mismo "
            "estilo. Rehaz la respuesta entera."
        )
    return (
        "Tu respuesta anterior incumple estas reglas del encargo:\n"
        f"{lineas}\n\n"
        "Reescribe SOLO lo que hace falta para cumplirlas. No suavices: si dos "
        "direcciones se parecían, es porque una de las dos no tenía enemigo "
        "propio. Devuelve la salida completa otra vez, con el mismo formato."
    )
