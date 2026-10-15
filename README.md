# Generador de Branding

Software que perfila la marca de una persona o empresa, la contrasta con lo que
esa persona está realmente dispuesta a hacer, y produce un informe —en web y en
PDF— con tres direcciones concretas propuestas por una IA.

Python 3.13 + FastAPI + SQLite + Jinja2 + WeasyPrint. El frontend es JavaScript
a pelo: sin Node, sin build, sin framework.

---

## Arranque en Windows

Esto es lo que se ejecutó en esta máquina el 03/09/2026 y funciona:

```powershell
winget install Python.Python.3.13
py -m venv .venv-win
.\.venv-win\Scripts\pip install -r requirements.txt
.\.venv-win\Scripts\uvicorn.exe app.main:app --reload
```

Abre <http://127.0.0.1:8000>.

**El `.venv/` que viene en la carpeta no sirve en Windows.** Es un entorno de
Linux: su `pyvenv.cfg` dice `home = /usr/bin` y su `command` apunta a una ruta
`/home/...` de otra máquina. Los ejecutables de dentro son ELF, no PE. No lo borres
si vas a volver a Linux, pero en Windows créate el tuyo (`.venv-win`) y usa ese.
Los dos están ignorados en `.gitignore` (`.venv/` y `.venv-win/`).

En Linux o macOS es lo de siempre:

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --reload
```

### El PDF necesita GTK/Pango, y en esta máquina no está

WeasyPrint es un paquete de Python que carga por `ctypes` las librerías nativas
de GTK/Pango. En Windows esas librerías **no vienen con pip**. Aquí el paquete
está instalado y `import weasyprint` sigue fallando: es un hecho de esta máquina,
no un fallo del proyecto.

Consecuencia real: **todo funciona menos la descarga del PDF.** `app/pdf.py`
importa WeasyPrint dentro de `generar()`, no en la cabecera, así que el servidor
arranca, el cuestionario va, el informe web se pinta entero y la IA responde.
Solo `GET /informe/{id}/pdf` devuelve **503** con un mensaje que dice exactamente
qué falta, en vez de tumbar el proceso al importar `app.main`.

Si quieres el PDF en Windows, instala el runtime de GTK (el instalador de
`gtk3-runtime` de tzenner/msys2, o `pacman -S mingw-w64-x86_64-pango` en MSYS2) y
asegúrate de que su `bin\` está en el `PATH` **antes** de arrancar uvicorn. En
Debian/Ubuntu: `apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b`.

---

## La IA: proveedor, modelo y lo que cuesta

Para las tres direcciones hace falta una clave. Conviven dos proveedores y se
elige con `PROVEEDOR_IA` en `.env`:

```bash
cp .env.example .env
# PROVEEDOR_IA=gemini  + GEMINI_API_KEY   (clave en https://aistudio.google.com/apikey)
# PROVEEDOR_IA=claude  + ANTHROPIC_API_KEY (clave en https://console.anthropic.com/settings/keys)
```

Sin clave el software funciona igual: hace el test, calcula el perfil y los
índices, dibuja los gráficos, genera las paletas y el sistema de activos. Solo se
queda sin la sección de las tres direcciones; la web deja un botón para generarla
más tarde.

`MODELO_IA` fija el modelo concreto dentro del proveedor. Déjalo vacío para el de
por defecto: **`gemini-3.5-flash`** o **`claude-opus-5`**. Si escribes un modelo
del otro proveedor, `app/ia/__init__.py` lo detecta y da un error de
configuración en español, en vez del 404 crudo de Google.

**Las tarifas son en dólares por millón de tokens** (entrada / salida), no en
euros. Salen de `TARIFAS` en `app/ia/claude.py` y `app/ia/gemini.py`:

| Modelo | Entrada | Salida |
| --- | --- | --- |
| `claude-opus-5` (por defecto) | 5,00 $ | 25,00 $ |
| `claude-opus-4-8` | 5,00 $ | 25,00 $ |
| `claude-sonnet-5` | 2,00 $ | 10,00 $ |
| `claude-sonnet-4-6` | 3,00 $ | 15,00 $ |
| `claude-haiku-4-5` | 1,00 $ | 5,00 $ |
| `gemini-3.5-flash` (por defecto) | 0,30 $ | 2,50 $ |
| `gemini-2.5-flash` | 0,30 $ | 2,50 $ |
| `gemini-2.5-pro` | 1,25 $ | 10,00 $ |

Dos avisos honestos: **las tarifas de Gemini y los identificadores de sus modelos
están sin verificar** contra la documentación de Google —compruébalos antes de
facturarle esto a nadie— y **el coste por informe lo domina la ENTRADA**, no la
salida: el dossier lleva hasta 86 respuestas de módulo en texto legible. Un
modelo que no esté en la tabla genera el informe igual, pero el coste sale a 0;
no es que sea gratis, es que no se sabe.

---

## El acceso: Google o sin cuenta

### Cómo se saca el `GOOGLE_CLIENT_ID`

1. Entra en <https://console.cloud.google.com/> y crea un proyecto (o usa uno).
2. **APIs y servicios → Pantalla de consentimiento de OAuth.** Tipo «Externo»,
   rellena nombre de la aplicación y correo de asistencia. No hace falta publicar
   ni pasar verificación mientras solo entres tú y los usuarios de prueba.
3. **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de
   OAuth.** Tipo de aplicación: **Aplicación web**.
4. En **Orígenes autorizados de JavaScript** añade `http://localhost:8000` y
   `http://127.0.0.1:8000` (y tu dominio con https cuando lo despliegues).
   **No hace falta URI de redirección** ni secreto de cliente: aquí solo se
   verifica el ID token que devuelve el botón de Google, no hay flujo de código.
5. Copia el ID (`...apps.googleusercontent.com`) a `.env`:

```bash
GOOGLE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com
COOKIE_SEGURA=0   # 1 solo cuando sirvas por https
```

### Qué pasa si no lo pones

Nada se rompe. `auth.google_activo()` devuelve `False`, `index.html` **no carga
el script de accounts.google.com** —no se manda ni una petición a Google— y el
paso de acceso enseña solo **«Continuar sin cuenta»**. Ese botón crea un usuario
anónimo de verdad, con su fila en la tabla `usuarios`, y a partir de ahí se
guarda todo igual. Lo único que se pierde es poder recuperar el cuestionario
desde otro dispositivo.

El servidor lo avisa por consola al arrancar, junto con el otro error que cuesta
horas: `COOKIE_SEGURA=1` sobre http hace que el navegador **descarte la cookie
sin un solo mensaje de error**, y entonces cada petición crea un usuario nuevo.

### Cómo funciona la sesión

- El ID token de Google se verifica **localmente** con `google-auth` (firma,
  emisor, caducidad y `aud`), no llamando a `tokeninfo`. `audience` es siempre el
  `CLIENT_ID`: con `audience=None` se aceptaría un token legítimo de Google
  emitido para otra aplicación.
- La sesión es un **token opaco de 256 bits**. En la tabla `sesiones` se guarda
  su **sha256**, nunca el token: un volcado de `branding.db` no permite
  suplantar a nadie.
- Cookie `HttpOnly`, `SameSite=Lax`, `Secure` según `COOKIE_SEGURA`. Un año de
  vida con renovación deslizante (como mucho una escritura al día por sesión) y
  rotación preventiva del token a los 30 días.
- CSRF sin tokens por formulario: no hay un solo `<form>` clásico, todo es
  `fetch` del mismo origen. `SameSite=Lax` más el middleware
  `bloquear_origen_cruzado` de `app/main.py` cubren el resto.
- Diez logins fallidos de Google desde la misma IP truncada en 15 minutos → 429.

---

## Qué hace, exactamente

1. **Identidad.** Nombre, marca personal o de empresa, y email. El **nombre de
   marca se pregunta al final**, no aquí: las sugerencias automáticas necesitan
   el territorio, el color, el sello y el formato, y nada de eso existe en la
   pregunta 3.
2. **Test de arquetipos.** 48 ítems Likert 1-5 (4 por cada uno de los 12
   arquetipos de Mark y Pearson) + **3 controles de atención** intercalados + 8
   bloques de elección forzada para desempatar. **59 pasos.**
3. **Tres módulos: 86 preguntas.**
   - Comunicación: 34 preguntas en 7 bloques (`categoria`, `tono_voz`,
     `promesa_audiencia`, `postura`, `narrativa`, `canales`, `limites`).
   - Visual: 27 preguntas en 8 bloques (`coloracion`, `cabello`, `ropa_tipos`,
     `colores_ropa`, `vibra`, `duelos`, `audacia`, `limites_corporales`).
   - Acciones: 25 preguntas en 8 bloques (`disposicion`, `dilemas`,
     `tiempo_recursos`, `contenido`, `red`, `causas`, `rituales`, `horizonte`).
4. **Informe**, en web y en PDF.

**145 preguntas en total: 59 del test + 86 de los módulos.** Contadas sobre
`contenido/*.json`, no de memoria; es lo mismo que devuelve `totalPreguntas()` en
`form.js`, que además excluye a propósito las preguntas de desempate para que
repetir no infle la barra de progreso. Con los cuatro campos de identidad, la
pantalla de acceso, la portada, los rótulos de módulo y los de cada bloque, el
navegador pinta unas **181 pantallas**.

**La portada anuncia «~35 minutos»**, no 25: con 145 preguntas, prometer 25 y
tardar 35 es la primera causa de abandono a mitad.

Los nueve tipos de pregunta de los módulos, con su reparto real:

| Tipo | Cuántas | Qué es |
| --- | --- | --- |
| `unica` | 21 | Una opción de varias. |
| `likert5` | 18 | Escala 1-5. |
| `multiple` | 12 | Varias, con `min` y `max`. |
| `texto_largo` | 11 | Textarea con mínimo de caracteres. |
| `texto` | 10 | Campo corto con mínimo de caracteres. |
| `bipolar` | 9 | Siete posiciones entre dos polos, sin valor por defecto. |
| `duelo` | 3 | Dos referentes reales; eliges uno y escribes qué NO le copiarías. |
| `ranking` | 1 | Tres de ocho, en orden. COM-NA-3. |
| `reparto100` | 1 | 100 puntos entre ocho opciones. VIS-VI-1. |

Se contestan de una en una, a pantalla completa, con avance automático al elegir
y atajos de teclado.

---

## La idea rectora: cero tibieza

Un buen branding **polariza**. Lo que intenta gustar a todos no le importa a
nadie, y el punto medio no es equilibrio: es invisibilidad. Por eso el software
no se limita a medir, **interviene**.

### El muro

Antes de emitir el informe se mide cuánto te has escondido, **por sección y no en
un único saco** (con un saco único el test se llevaba el 62 % del denominador y
contestar 3 en los 48 ítems salía gratis):

- Test de arquetipos: dispara por encima del **15 %** de ítems contestados.
- Cada módulo: por encima del **22 %** de sus preguntas puntuables.
- Global: por encima del **20 %** del denominador combinado.

Y hay **cuatro** motivos de parada, no uno, en este orden de gravedad
(`scoring.veredicto_definicion`):

| Motivo | Estado | Qué te devuelve |
| --- | --- | --- |
| `sin_validez` | `sin_validez` | El test entero. Falla siempre, sin tope de rondas: un informe inventado no mejora por insistir. |
| `texto_pobre` | — | Las respuestas escritas que no dicen nada (a partir de **2**). |
| `tibieza` | `tibio` / `tibio_persistente` | Las preguntas donde te escondiste. |
| `plano` | `plano_sin_tibieza` | Los ítems donde tu respuesta empata con tu propia media, más los bloques de desempate que falten. |

Cuando devuelve preguntas, las devuelve **sin el punto medio**: el Likert pierde
el 3, el bipolar se vuelve botones sin centro, las opciones evasivas desaparecen.
Máximo **2 rondas** (`MAX_RONDAS_TIBIEZA`); si sigues igual, el informe se emite
con veredicto duro en portada. Con `plano_sin_tibieza` **el texto de portada no
habla del punto medio**: son dos diagnósticos distintos y decir «te escondiste en
el centro» a quien tiene 0 % de tibieza es mentir.

**La ronda la decide el servidor**, columna `borradores.ronda`. Mientras la
mandaba el cliente, un POST con `ronda: 2` —o pulsar F5— se saltaba el muro
entero. `POST /api/informe` recalcula el veredicto **antes** de guardar y
responde **409** con el mismo cuerpo que `/api/tibieza` si toca repetir:
`/api/tibieza` es una cortesía para el navegador, la puerta de verdad es la otra.

### Los controles de atención sí se usan

Antes no los miraba nadie: `valor_esperado` llevaba en el JSON desde el primer
día y el filtro que parecía leerlo cruzaba `test['items']` con ids que viven en
`test['control']`, otro array, así que nunca casaba. Un cuestionario contestado
al azar producía un informe con la misma pinta que uno honesto.

Ahora `scoring.validar_atencion` comprueba los **3** controles: dos por
`valor_esperado` y uno de consistencia (dos frases opuestas cuyos valores tienen
que sumar lo esperado, con tolerancia). Uno fallado → aviso «tómalo como
hipótesis». Dos o más → **el informe se declara sin validez** y el muro devuelve
el test completo.

### Amplificación en las recomendaciones

El prompt de la IA no busca el consenso: coge tu arquetipo dominante y lo
multiplica. Cada dirección lleva una **postura**, un **enemigo declarado** con
nombres y **a quién le va a caer mal**. Una marca sin enemigo no se recuerda, y
la post-validación rechaza «la mediocridad» como enemigo.

---

## Y lo que ya lo diferenciaba

**Corrección de aquiescencia.** La gente puntúa alto en todo: «sí, mi marca es
sabia… y heroica… y creativa». Se resta la media global de cada escala, así que
el resultado no es cuánto te gusta cada arquetipo sino tu perfil *relativo*. Sin
esta corrección, un test de arquetipos mide sobre todo deseabilidad social.

**El hueco en cabeza manda sobre sigma.** Si tus doce puntuaciones salen
apelotonadas, tu marca no tiene personalidad definida, y eso es un diagnóstico
más valioso que el arquetipo.

**Triangulación.** El test mide lo que *crees* que eres. Los módulos miden lo que
estás dispuesto a *hacer*. Cuando no coinciden —dices ser Mago pero tus acciones
son de Cuidador— ahí está el trabajo real.

---

## Las paletas: fieles a lo que elegiste, con una excepción declarada

Antes la paleta salía solo de la ficha del arquetipo: si elegías verde, te salía
el burdeos del Amante y ni rastro del verde. Corregido. Ahora el color que
declaras (**VIS-CR-3**) es el protagonista de «La tuya», y VIS-CR-3 se pregunta
**antes** que los vetos (VIS-CR-2) en el bloque `colores_ropa`.

Se generan **tres** paletas (`app/paletas.py`, determinista, sin IA):

1. **La tuya** — tu color de dominante, con acentos del arquetipo que no vetes.
2. **La del arquetipo** — la del arquetipo puro, filtrando tus vetos y
   reponiendo con neutros seguros lo que el veto se lleve.
3. **La polarizante** — tu color saturado al máximo + negro + blanco.

**Lo que el README decía y era falso: «lo que vetas no aparece en ninguna
paleta».** La verdad de hoy, comprobable en `pruebas/test_paletas.py`:

- En «La tuya» y «La del arquetipo» el veto **se respeta**.
- En **«La polarizante» el veto se salta a propósito** para el color declarado:
  satura tu color al máximo aunque hayas vetado los colores vivos. Es coherente
  con lo que esa paleta promete —«tu color al extremo, sin puntos medios»— e
  incoherente con la frase de siempre. Está fijado por la prueba
  `test_la_polarizante_se_salta_el_veto_a_proposito`, que falla si alguien
  cambia una de las dos cosas sin decidirlo. El veto al **negro** y al **blanco**
  sí manda ahí: se sustituyen por grafito y piedra clara.
- Si tu color declarado **cae dentro de una familia que has vetado**, la paleta
  no lo resuelve a tus espaldas: el sistema de activos lo **declara en
  conflicto** (`activos._filtrar`), lo dice en el informe y le baja la fuerza al
  activo de color. Lo declarado manda; el conflicto se cuenta, no se esconde.

---

## La salida memorable (`app/activos.py`)

Un posicionamiento perfecto que nadie puede describir de memoria no sirve. Este
módulo es determinista y sin IA, igual que el scoring, y sale de las preguntas
que ya se contestan.

**`sistema_activos()`** compone la lista de activos distintivos: color dominante
(VIS-CR-3 + la paleta ya generada), silueta (VIS-RO-3/4), sellos (VIS-RO-5),
peinado (VIS-CA-3, VIS-CA-7), uniforme (VIS-AU-3), encuadre (VIS-AU-1), formatos
y gestos (ACC-CT-2, ACC-RI-1, ACC-RI-2) y palabras propias (COM-PA-*, COM-NA-4).
Cada activo lleva `fuerza` (0-3), si es `declarado` por la persona o heredado del
arquetipo, sus `fuente_ids` y su regla de uso. La **tipografía** entra en la
lista pero no cuenta como activo: viene de la ficha del arquetipo, no la ha
elegido nadie. Menos de 2 activos fuertes → aviso «no tienes con qué te
reconozcan»; más de 6 → «seis sellos no son un sistema, son un disfraz». Los
vetos de ropa eliminan el activo que los contradice; el bloque
`limites_corporales` (VIS-LM-1..5) **no genera ni activo ni veto**, porque
promete que ninguna respuesta suma ni resta y aquí se cumple.

**`indice_identificabilidad()`** — ¿hay algo que repetir? Pesos reales:

| Componente | Peso | De dónde sale |
| --- | --- | --- |
| color | 25 | VIS-CR-3 (100 si es declarado y fuerte, 60 si es monocromo o está en conflicto con su propio veto, 0 si es el del arquetipo) |
| sello | 20 | VIS-RO-5 |
| formato | 20 | ACC-CT-2 + ACC-RI-1 (`formato_fijo` / `seccion`) |
| gesto | 20 | ACC-RI-1 / ACC-RI-2, con nombre propio |
| repetición | 15 | media de COM-LI-6, ACC-HO-3, VIS-AU-3, VIS-CA-7 |

Los pesos se **renormalizan sobre los componentes con dato**, así que un
cuestionario a medias no sale artificialmente bajo. Cortes: `<35` invisible ·
`<65` reconocible con esfuerzo · resto inconfundible.

Además: `reconocimiento_3s()` (cuatro comprobaciones de lo que le queda a quien
pasa el dedo por tu perfil), `regla_repeticion()` (los doce meses calculados, no
escritos por la IA), `identidad_verbal()` (palabras propias y prohibidas) y
`una_sola_cosa_borrador()`, que arma un borrador de «la única cosa» con el
territorio de COM-NA-3 y los mapas de `contenido/nombres.json`.

---

## El motor de puntuación (`app/scoring.py`)

Es donde está la ventaja competitiva. Los umbrales de esta tabla salen de las
constantes reales del fichero, no del JSON.

| Cálculo | Cómo |
| --- | --- |
| Puntuación por arquetipo | Se recodifican los ítems inversos (`6 - x`), se resta la media global (aquiescencia) y se normaliza a 0-100 sobre una **escala teórica fija** `[-16, +16]`, no min-max sobre el sujeto. |
| Orden y desempate | Se ordena por (puntuación, tasa de elección forzada, afinidad global, id). Si otro arquetipo está a menos de **5,0** puntos y gana en **tasa** de elección forzada, se lleva el primer puesto. Se usa la tasa y no los puntos brutos porque los 8 bloques reparten los arquetipos de forma desigual. |
| Secundario / terciario | **Absolutos**: secundario si llega a **60,0** y no se aleja más de **15,0** del primario; terciario si llega a **55,0**. Los umbrales relativos de antes (0,80 y 0,70 de p1) hacían que definirse quitara arquetipos y ser tibio los regalara. |
| Empates sin resolver | Se **declaran** (`empate_secundario`, `empate_terciario`) en vez de resolverse por orden de fichero. |
| Coherencia | Manda el **hueco en cabeza** (p1 − p4): `<6,0` plano; `≥12,0` con sigma `≥8,5` definido; el resto moderado. Sigma (desviación típica poblacional de las 12) se sigue publicando pero ya no decide sola. **El techo teórico de sigma es 25,0**, no 13,8. |
| Estilo de respuesta | Si la varianza *dentro* de cada arquetipo es ≥ **2,5** veces la varianza *entre* arquetipos, no hay perfil: hay ruido, y se dice en portada. |
| Familias cardinales | Media de las puntuaciones de cada una de las 4 familias. Se acusa de tensión de identidad solo con **5,0** puntos de diferencia entre familias: sin ese margen, cuatro familias empatadas a 50,0 emitían el aviso más grave del informe con 0,0 de diferencia. |
| Avisos de sombra | Sobreexpresión (p1 ≥ **85** y distancia al mínimo > 30), punto ciego (opuesto < **20**), aquiescencia (media global ≥ **4,2** o ≤ **1,8**) y tensión entre opuestos (ambos > **70**). |
| Afinidad por módulo | Cada opción lleva etiquetas de arquetipo. Likert solo cuenta con 4-5, peso `(v−3)/2`. Bipolar reparte por distancia al centro. **`ranking`** pesa 3/2/1 por puesto. **`reparto100`** pesa `puntos/25`. **`duelo`** anota el arquetipo primario y los secundarios del referente elegido, peso 1,0. Los textos pesan 0 a propósito. |
| Triangulación | Si el arquetipo líder de un módulo no es el primario del test (y tiene ≥20 de afinidad), se emite un hallazgo. |
| Índice de audacia | Media de los 7 Likert de `disposicion` (6) y `causas` (ACC-CA-1), llevada a 0-100. `<35` prudente · `<65` equilibrado · resto audaz. |
| Índice de tibieza | Ver «El muro». Devuelve `preguntas_tibias` con id, motivo y `valor_previo`, para que el muro pueda comprobar que la respuesta nueva no es la misma. |
| Calidad de textos | Las **19** preguntas abiertas obligatorias (`lexico_evasion.obligatorias_para_el_muro`) más los tres «lo que NO le copiaría» de los duelos, contra un léxico de 28 frases vacías, 26 muletillas y 16 enemigos tópicos. |
| Índice de distinción | Cuánto te separas de tu categoría **tal como la describes tú** (COM-CX-3/4/5). Pesos: color 30, tono 20, formato 20, sello 20, diferir 10. `<35` · `<65` · resto. No entra ni un ACC-DI-*: distinción no es audacia. |
| Índice de consistencia | Aguante: la probabilidad de que esto siga en pie dentro de un año (COM-LI-6, ACC-HO-3, cadencia COM-CA-3, rituales ACC-RI-1/2…). `<40` · `<70` · resto. Es el único índice que compensa la falta de audacia. |
| Índice de invisibilidad | El que va a portada. `100 − (0,30·distinción + 0,25·consistencia + 0,20·sigma + 0,15·(100−tibieza) + 0,10·activos)`. `≥60` riesgo alto · `≥35` riesgo medio · resto bajo. El orden de los pesos no es decorativo: distinción y consistencia miden cómo se va a **ver** la marca; sigma y tibieza solo miden cómo se contestó el formulario. |

**Por qué escala teórica y no min-max:** un min-max forzaría al primario a 100 y
al último a 0 *siempre*, y haría invisible el caso más informativo, el perfil
plano.

**Cuidado con la frase de siempre.** «Quien contesta lo mismo a todo sale con
doce cincuentas» **solo es cierto contestando 3**. Comprobado ejecutando el
motor: con 5 en todo salen **54,2** para los ocho arquetipos sin ítem inverso y
**41,7** para BUF, EXP, INO y GOB; con 1 en todo, 45,8 y 58,3. Los cuatro ítems
inversos (BUF-4, EXP-4, INO-4, GOB-4) rompen la simetría de la corrección de
aquiescencia porque no hay uno por arquetipo. Lo correcto serían 12 de 48, uno
por arquetipo; está documentado y no se toca en esta versión para no mezclar el
cambio del instrumento con el cambio de las preguntas de módulo.

**Nota:** los umbrales están duplicados como documentación en la clave `scoring`
de `test_arquetipos.json`, pero **el código no los lee de ahí**: son constantes
en `scoring.py`. Si cambias uno, cambia los dos. A día de hoy coinciden: se
retiraron del JSON los antiguos `umbral_secundario: 0.8` y `umbral_terciario:
0.7`, porque el código va por absolutos (`umbral_secundario_abs: 60` y
`umbral_terciario_abs: 55`).

### Detección de tibieza: qué cuenta y qué no

Antes, cualquier `unica`/`multiple` sin opción marcada `evasiva` no entraba ni en
el numerador ni en el denominador: 39 de las 41 preguntas de opción no contaban y
el 62 % del denominador eran los ítems del test.

Ahora **cuenta todo lo que se puede contestar**, y la tibieza tiene cuatro
formas: el centro (Likert 3, bipolar en el punto muerto), la
opción-escape (las **6** opciones marcadas `evasiva`: VIS-CA-2, VIS-CA-5,
VIS-RO-2, VIS-RO-5, VIS-CR-2 y ACC-CA-2), la dilución (marcar el máximo de una
múltiple, o repartir los 100 puntos entre demasiadas opciones) y el texto que no
dice nada.

Dos exclusiones deliberadas, y solo dos:

- **VIS-CO-4** (oro/plata) tiene un «no noto ninguna diferencia» que **no está
  marcado como evasiva**: ahí es una respuesta legítima de piel neutra, no
  cobardía de marca. Es la única pregunta de opción con escape que no penaliza.
- **Los textos opcionales** (VIS-LM-5, ACC-CA-3) no son terreno de tibieza: no
  contestar dónde está tu límite no es esconderse. Y los cinco de `nunca_al_muro`
  se validan al pasar de pantalla pero no se reofrecen: «escribe otra vez tu
  opinión impopular, más impopular» produce material falso, que es peor que
  material tibio.

---

## La IA (`app/ia/`)

Única capa que toca una API key.

```
app/ia/
  __init__.py    Despacha al proveedor, valida y reintenta. generar_recomendaciones().
  esquema.py     El Pydantic compartido (Salida) y el prompt de sistema.
  validacion.py  Post-validación determinista: 6 reglas duras y 5 blandas.
  tipos.py       ResultadoIA: salida + tokens + coste + intentos + ms.
  gemini.py      Proveedor Gemini (por defecto). google-genai + response_schema.
  claude.py      Proveedor Claude. anthropic messages.parse.
```

### Qué se le manda

Un **dossier**, no el informe entero. Mandar el informe completo sería tirar
tokens y enterrar la señal.

**La frase «la IA recibe las 134 respuestas traducidas a texto legible» era
falsa.** `informe.dossier_para_ia` solo traduce a texto legible las respuestas de
los **tres módulos** —hasta **86**, y descartando las vacías— más el test en
forma de **puntuaciones**. Los 48 ítems Likert no viajan como respuestas.

Además del texto legible de los módulos, el dossier lleva: identidad reducida
(nombre, nombre de marca y tipo de marca; **no** apellidos ni email), los números
crudos del perfil (sigma, hueco, media global, techo teórico, opuesto con su
puntuación), avisos sin su párrafo ya redactado, triangulación, audacia, los
índices con su número y su nivel **pero sin su lectura**, las **tres paletas ya
calculadas**, los activos declarados, los límites duros con la consecuencia de
cada opción, el enemigo declarado, la categoría descrita por la persona, la
elección forzada, el control de atención, dónde se escondió y la escala Likert
explicada una vez en la cabecera. Se le quitan a propósito los párrafos que ya
ha escrito el software: a un modelo al que le das el diagnóstico redactado, lo
parafrasea.

### Qué devuelve, y qué pasa si se sale del esquema

La respuesta es un `Salida` de Pydantic: lectura general, la verdad incómoda, el
coste de no elegir, justificación de las paletas, **3 recomendaciones** (título,
concepto, por-qué-a-ti, postura, **una sola cosa**, 3 eslóganes de máximo 7
palabras, **enemigo**, a quién molesta, 2-3 **activos elegidos** de los que ya se
le han dado, identidad verbal, prueba del bar, prueba de 3 segundos, qué deja de
hacer, criterio de revisión a 90 días, **paleta elegida entre las tres**,
tipografía, estilo visual, tono, 3 acciones, 2-3 referentes y riesgo), la
dirección recomendada, 3-5 candidatos de nombre y el veredicto sobre el nombre
actual.

**La IA ya no inventa colores**: recibe las tres paletas y solo elige una por
dirección y la justifica.

**Lo que decía el README y no es cierto: «si el modelo se sale del esquema, el
SDK reintenta».** No lo hace ninguno de los dos. Lo que hacen las APIs es
*restringir la generación* al esquema, que es otra cosa, y ninguna comprueba que
lo escrito no sea humo. Lo que hay de verdad es **post-validación propia** en
`app/ia/validacion.py`, sin dependencias externas:

- **Reglas duras (bloquean y provocan UN reintento correctivo):** tres títulos
  distintos; las tres direcciones no pueden compartir más del **18 %** de
  trigramas de palabra ni los enemigos más del **25 %**; el enemigo tiene mínimo
  40 caracteres y no puede ser un tópico de la lista; las paletas elegidas tienen
  que existir entre las realmente generadas; «una sola cosa» máximo 6 palabras;
  los activos elegidos tienen que existir en el dossier y no estar vetados.
- **Reglas blandas (solo se anotan):** tópicos de consultoría, anclaje en ids de
  pregunta concretos, cifras en las acciones, identidad verbal y prueba del bar.

Si el segundo intento sigue incumpliendo una regla dura, se para con un
`RuntimeError` que `main.py` convierte en **502**. **Techo: dos llamadas por
informe.** Un bucle de reintentos en un endpoint sería una factura abierta.

Encima de eso hay tres topes más en `main.py`: **200** llamadas al modelo en 24 h
para todo el servidor, **3** por informe (columna `informes.ia_intentos`,
reservada en su propia transacción antes de llamar), y las recomendaciones ya
generadas se devuelven sin gastar llamada salvo `?forzar=1`.

La llamada va **separada de la creación del informe** (`POST
/api/informe/{id}/ia`) para que el usuario vea su perfil al instante. El token de
lectura **no** abre esa ruta: compartir un informe no puede significar compartir
la clave de API del dueño.

---

## Rutas

| Ruta | Qué hace |
| --- | --- |
| `GET /` | El cuestionario (una sola página; `form.js` lo monta todo). |
| `GET /privacidad` | La página de privacidad. |
| `GET /api/contenido` | Arquetipos, familias, test, módulos, referentes, léxico de evasión, tablas de categoría y versión del contenido. |
| `POST /api/auth/google` | Verifica el ID token de Google y abre sesión. 503 si no hay `GOOGLE_CLIENT_ID`, 401 si el token no vale, 429 con 10 fallos en 15 min. |
| `POST /api/auth/anonimo` | «Continuar sin cuenta». Idempotente: con sesión válida no crea nada. |
| `POST /api/auth/salir` | Cierra la sesión. `?todos=1` cierra las de todos los dispositivos. 204 aunque no hubiera sesión. |
| `GET /api/yo` | Quién eres, tu borrador y tus informes. **200 siempre**, nunca 401. |
| `DELETE /api/yo` | Derecho de supresión. Exige `{"confirmacion": "BORRAR"}`. Aquí sí caen los informes por cascada. |
| `GET /api/yo/export` | Todo lo tuyo en un JSON descargable. Artículos 15 y 20 del RGPD sin montar un panel. |
| `PUT /api/borrador` | Autoguardado. `contestadas` lo recalcula siempre el servidor. **409** con el estado del servidor si dos dispositivos chocan. **413** por encima de 256 KiB. |
| `GET /api/borrador` | Tu borrador. **204** si no hay. |
| `POST /api/borrador/descartar` | «Empezar de cero» sin destruir nada: la fila se archiva en `borradores_descartados`. |
| `POST /api/borrador/recuperar` | Restaura el último borrador archivado. |
| `POST /api/tibieza` | Índice, veredicto y la lista exacta de preguntas donde te escondiste. No crea informe. La ronda sale de la base. |
| `POST /api/informe` | Calcula, guarda y devuelve `{id, token_acceso, resultado}`. **409** con el veredicto si el muro dice repetir. Idempotente por `clave_idem`. |
| `POST /api/informe/{id}/ia` | Llama al proveedor. 404 si no es tuyo, 429 por cupo, 502 si la API falla o la validación no pasa. |
| `GET /informe/{id}` | El informe en web. Dueño o `?t=<token_acceso>`. |
| `GET /informe/{id}/pdf` | El informe en PDF. **503** si falta GTK/Pango. El nombre del fichero ya no lleva el nombre de la persona. |
| `GET /api/yo/informes` | Los informes del usuario de la sesión. |
| `GET /admin/informes` | El listado global, detrás de la cabecera `X-Admin-Token`. **Sin `ADMIN_TOKEN` configurado la ruta devuelve 404**: una puerta sin llave es peor que ninguna puerta. |

Sustituye al viejo `GET /api/informes`, que servía los últimos 50 informes con
nombre y email **a cualquiera**.

**Un informe ajeno responde 404, nunca 403.** Un 403 confirma que el informe
existe y convierte el barrido de ids en un censo de clientes.

---

## Los datos: qué se guarda y cuándo

### Cuándo

**Desde la primera respuesta.** Ya no es `localStorage` y punto. Cada respuesta
se guarda en el servidor, en la tabla `borradores`, con antirrebote de 1,5 s y
subida forzada al cruzar cada rótulo de sección y antes de enviar; `localStorage`
se queda como caché para trabajar sin conexión. Al cerrar la pestaña sale un
`fetch` con `keepalive: true` —**no** un `sendBeacon`, que solo sabe hacer POST y
se comería un 405 contra un endpoint que es PUT—. Si abandonas en la pregunta 90,
en la base hay 90 respuestas. Y si entraste con Google, sigues donde estabas al abrirlo en otro
dispositivo.

El borrador **no se borra al enviar**: se le anota de qué informe salió. «Volver
a hacerlo» no puede destruir el intento anterior.

### El esquema (`PRAGMA user_version = 2`)

| Tabla | Para qué |
| --- | --- |
| `usuarios` | Una fila por persona, con o sin Google. `google_sub` único, email, si está verificado, nombre, foto, `anonimo`, y `visto_en` para la purga. |
| `sesiones` | Una por dispositivo. `id` = **sha256 del token**, nunca el token. Con `ua_hash`, `ip_trunc` y `expira_en`. |
| `borradores` | Una por usuario. El cuestionario en curso: respuestas, paso, `ultimo_id`, **`ronda`** (el árbitro del muro), `contestadas` y `version` para el bloqueo optimista. |
| `borradores_descartados` | Lo que se archiva al «empezar de cero», recuperable. |
| `informes` | Los informes emitidos. Desde v2 con `usuario_id`, `token_acceso` único, `publico`, `clave_idem` (idempotencia del POST), `ia_generada_en` e `ia_intentos`. |
| `eventos` | Contadores y auditoría: llamadas a la IA (los topes se cuentan **en la base**, porque `uvicorn --reload` reinicia el proceso y cualquier contador en RAM vuelve a cero), logins fallidos, creación de anónimos. |

Detalles que importan: cada conexión enciende `PRAGMA foreign_keys` a mano
—SQLite lo trae apagado y es por conexión, así que sin esa línea todos los
`ON DELETE CASCADE` son decoración—, `busy_timeout` a 15 s por el volumen de
escrituras del autoguardado, y `journal_mode = WAL`.

### La migración

`db.inicializar()` corre en el arranque. Si `PRAGMA user_version` es menor que 2:

1. Hace una **copia consistente en caliente** con `VACUUM INTO` en
   **`datos/branding-pre-v2.db`** (solo si no existe ya). Es el seguro.
2. Aplica las sentencias de `_MIGRACION_2` una a una dentro de un
   `BEGIN IMMEDIATE`, y sube `user_version` **dentro** de la misma transacción:
   o migra entero o no migra.

**Los informes que ya existían se quedan con `usuario_id NULL`.** Nadie los
reclama automáticamente: cruzar `informes.email` con el email de Google le
regalaría el informe a quien registrase ese correo. Lo que sí reciben es un
`token_acceso` nuevo, así que **se siguen abriendo por `/informe/{id}?t=<token>`**.
Probado sobre una copia de `datos/branding.db`: los 3 informes reales sobreviven
a la migración y salen legibles. Para meterlos en una cuenta:

```bash
.\.venv-win\Scripts\python.exe scripts/reclamar_informes.py --email tu@correo --informes 1,2,3
```

A mano, uno a uno, con confirmación escrita y sin tocar nunca un informe que ya
tenga dueño.

### Aviso: esa base viaja con el código

**`datos/branding.db` contiene nombres y correos electrónicos reales.** Hoy hay 3
informes y los 3 tienen nombre y email rellenos. Con el esquema v2 se le suma la
tabla `usuarios` con identificadores de Google.

Y **este proyecto no es un repositorio git**: no hay carpeta `.git`, así que
`.gitignore` **no está ignorando nada** —`datos/*.db` y `.env` no filtran nada
porque no hay índice donde filtrar—. Si copias o comprimes la carpeta, la base de
datos con los datos personales se va dentro.

Antes del primer `git add`:

```bash
git init
git check-ignore -v datos/branding.db .env    # tiene que decir que están ignorados
```

Los anónimos inactivos se purgan a los `DIAS_RETENCION_ANONIMOS` (30 por defecto)
contados desde su última visita; sus informes ya emitidos no se borran.

---

## Honestidad intelectual

El informe separa explícitamente qué es sólido y qué es folclore de industria:

- **Real:** los 12 arquetipos (Mark y Pearson, 2001, sobre base junguiana); el
  contraste simultáneo de Chevreul (1839) —la ropa junto a la cara cambia de
  verdad cómo se percibe la piel—; y que un rostro se percibe más sano cuanto
  más rojo, amarillo y luminoso (Stephen et al., 2009).
- **Heurística, no ciencia:** las estaciones cromáticas, los tipos de Kibbe y las
  tipologías de estilo personal. Nadie ha demostrado que dos analistas coincidan.
  David Kibbe ha repudiado su propio test de los años ochenta. Se usan porque
  acotan decisiones, no porque diagnostiquen.
- **Descartado:** «el 90 % de la decisión de compra depende del color» (no tiene
  ningún estudio detrás) y el sistema *Dressing Your Truth* (pseudociencia
  comercial).

**Sesgo racial en el cabello.** Hay investigación sólida (Perception Institute;
Koval y Rosette, Duke) de que el cabello afro, las trenzas y los locs se perciben
como «menos profesionales». El software informa de que ese sesgo existe pero
**nunca lo convierte en recomendación**: no penaliza ninguna textura de cabello.

Todo esto va impreso en la **nota metodológica** al final del PDF. No lo quites:
es lo que separa esto de un test de revista.

---

## Las imágenes de los referentes

Hay **35 fichas** en `contenido/referentes.json` y **35 ficheros** en
`app/static/refs/`: todas las fichas tienen foto local y todas están marcadas
como licencia verificada. Contadas una a una:

| Licencia | Fichas |
| --- | --- |
| Dominio público | 8 |
| CC0 | 1 |
| CC BY-SA 3.0 / 3.0 nl | 7 |
| CC BY-SA 2.0 / 2.0 fr | 7 |
| CC BY-SA 4.0 | 5 |
| CC BY 2.0 | 5 |
| CC BY 4.0 | 2 |

**26 de las 35 exigen atribución visible** (todas las CC BY y CC BY-SA). Ya se
pinta bajo cada foto, en la web y en el PDF. No la quites.

Si borras la carpeta o añades un referente:

```bash
.\.venv-win\Scripts\python.exe scripts/descargar_imagenes.py
```

**No enlaces a Wikimedia en caliente.** Se probó: devuelve 429 y el informe sale
con unas fotos sí y otras no. En el propio mensaje de error piden que no se haga.
Cuando un referente no tenga foto libre, el software pinta un *mood board* con su
paleta en lugar de usar una foto con copyright.

### Cuántos referentes ves de verdad

**No siempre son 6.** `contenido.referentes_afines()` pide 6 con un tope de 2 por
arquetipo primario (sin ese tope, un Creador+Mago vería seis Creadores y ningún
Mago, justo la mitad que le falta), pero solo puede devolver candidatos con
afinidad > 0. Ejecutado sobre las 35 fichas, con solo un primario: **el Hombre
Común devuelve 1 referente, el Cuidador 2, el Héroe 4 y el Explorador 5**; los
otros ocho llegan a 6. Con primario y secundario el mínimo sube a 3. El PDF lleva **una foto por referente mostrado**,
así que **como mucho 6 fotos, no 35**.

### Antes de vender esto

La licencia CC resuelve el **copyright de la foto**, pero no los **derechos de
imagen de la persona retratada**, que son un asunto legal distinto. El fichero
no registra si alguien está vivo; lo que sí registra es la época, y **19 de las
35 tienen la época abierta** (`…-actualidad`), lo que es un indicio, no un dato.
La cifra de «27 vivos» que estaba escrita aquí no sale de ningún sitio.

Usarlos como referencia editorial y analítica —que es lo que hace este
software— es la posición defendible; usarlos en publicidad o en el packaging no
lo sería, porque insinuaría un aval que no existe. **Si vas a vender esto, que lo
mire un abogado.** Cambiar cualquier imagen es editar una línea de
`referentes.json`.

---

## Estructura

```
contenido/                El cerebro del cuestionario, en JSON. Editable sin tocar Python.
  arquetipos.json           Los 12 arquetipos: familia, opuesto, deseo, miedo, sombra,
                            paleta, tipografía, tono, acciones, marcas, iconos.
  test_arquetipos.json      48 ítems + 3 controles + 8 bloques de desempate + umbrales
                            duplicados como documentación.
  referentes.json           35 iconos de estilo, con licencia de imagen verificada.
  colores.json              Hex protagonistas por color declarado y vocabulario de veto.
  lexico_evasion.json       Frases vacías, muletillas, enemigos tópicos, mínimos por
                            pregunta y qué textos van o no van al muro.
  categoria.json            Tablas que traducen «lo que hace todo mi sector» a algo
                            comparable, para el índice de distinción.
  activos.json              Pesos, reglas de uso y vetos del sistema de activos.
  nombres.json              50 apellidos comunes, territorios y artículos, para las
                            sugerencias de nombre de marca.
  modulo_comunicacion.json  7 bloques, 34 preguntas.
  modulo_visual.json        8 bloques, 27 preguntas.
  modulo_acciones.json      8 bloques, 25 preguntas.

app/
  main.py               Rutas FastAPI, topes, muro del servidor y control de acceso.
  auth.py               Google Sign-In verificado en local + sesión por token opaco.
  db.py                 SQLite: esquema v2, migración y bloqueo optimista del borrador.
  scoring.py            El motor: arquetipos, tibieza, atención, textos, distinción,
                        consistencia, invisibilidad, audacia.
  activos.py            La salida memorable: activos, identificabilidad, 3 segundos,
                        regla de repetición, identidad verbal.
  paletas.py            Las tres paletas deterministas con veto (HSL).
  informe.py            Ensambla el resultado y el dossier para la IA.
  graficos.py           Radar, familias y triangulación → SVG con matplotlib.
  contenido.py          Carga los JSON (con caché) y elige los referentes afines.
  ia/                   Recomendaciones por IA, con post-validación propia.
  pdf.py                Jinja2 + WeasyPrint → bytes. Import perezoso de weasyprint.
  templates/
    index.html            Cascarón del cuestionario; lo monta form.js.
    resultado.html        El informe en web.
    informe_pdf.html      El informe en papel. Plantilla distinta a propósito.
    privacidad.html       Qué se guarda y por cuánto tiempo.
  static/
    js/form.js            El cuestionario entero: pasos, muro, autoguardado, teclado.
    css/app.css           La web.
    css/pdf.css           El papel (@page A4). Separado a propósito.
    refs/                 Las 35 fotos con licencia libre.

pruebas/                116 pruebas de pytest. Ver más abajo.
scripts/
  descargar_imagenes.py Baja las fotos de Wikimedia una sola vez.
  reclamar_informes.py  Asigna a mano informes huérfanos a una cuenta.
datos/
  branding.db           SQLite. Se crea y se migra sola al arrancar.
  branding-pre-v2.db    Copia previa a la migración. La crea db.inicializar().

PROMPT.md               Para analizar tu PDF con una IA sin usar la API.
```

---

## Decisiones técnicas

- **Backend obligatorio.** La API key no puede vivir en el navegador. Una vez que
  existe el backend, generar el PDF en el servidor sale casi gratis.
- **WeasyPrint** en vez de ReportLab: el PDF se maqueta con HTML y CSS normales
  (`@page`, saltos de página, tipografía), sin calcular coordenadas a mano.
- **Matplotlib → SVG inline**, no Chart.js: WeasyPrint no ejecuta JavaScript. Los
  SVG **no se guardan en la base**: se regeneran en cada render.
- **El contenido, en JSON.** Reescribir una pregunta, una paleta o un referente
  no debería obligar a tocar Python. `contenido.recargar()` vacía la caché.
- **SQLite con las respuestas como blob JSON**, sin normalizar en cien filas.
  Para este volumen sobra, y SQLite sabe consultar dentro con `json_extract()`.
- **Sesión con token opaco y no cookie firmada.** Una cookie firmada no se
  revoca, no permite «salir de todos los dispositivos» y no ahorra la fila: de
  todas formas hace falta un usuario en la base para colgar el borrador.
- **Versiones fijadas con `==` en `requirements.txt`.** Son exactamente las
  probadas. Subir una versión es una decisión, no un efecto secundario de
  instalar.
- **Sin Node, sin build.** Un `uvicorn` y ya.

---

## Las pruebas

```powershell
.\.venv-win\Scripts\pip install -r requirements-dev.txt
.\.venv-win\Scripts\python.exe -m pytest -q
```

**116 pruebas, todas en verde** (0,7 s). Solo tocan lo que es puro y
determinista: nada de red, nada de claves de API y nada que arrastre WeasyPrint.

| Fichero | Pruebas | Qué vigila |
| --- | --- | --- |
| `pruebas/test_contenido.py` | 48 | Que los JSON parsean, que no hay ids duplicados y que siguen existiendo las claves que el código busca por su nombre. La prueba más barata y la que más disgustos evita: renombrar VIS-CR-3 rompe a la vez las paletas, los activos y el índice de distinción, en silencio. |
| `pruebas/test_scoring.py` | 29 | Perfil, corrección de aquiescencia, tibieza por sección y controles de atención. Los números con `approx` (41,7 · 54,2 · 45,8 · 58,3) salen de la escala teórica ±16; si cambian, algo se ha movido y hay que decidirlo. |
| `pruebas/test_reclamar_informes.py` | 14 | Que el script no le quite un informe a nadie, no acepte una cuenta sin verificar y la confirmación escrita sirva de algo. Contra una base de usar y tirar; `datos/branding.db` no se toca ni de lectura. |
| `pruebas/test_activos.py` | 13 | Que un cuestionario vacío devuelva estructura utilizable, que renunciar al sello no fabrique un sello, y que un color declarado que choca con su veto se **diga**. |
| `pruebas/test_paletas.py` | 12 | Que el color declarado manda, que el veto se respeta donde se promete, y que la polarizante se lo salta **a propósito** (con el comentario que explica por qué). |

Lo que **no** cubren: las rutas de FastAPI de punta a punta, `app/auth.py` contra
Google, la generación del PDF y la llamada real a los proveedores de IA.

---

## Lo que no está verificado

Con nombres, no con eufemismos:

- **La llamada real a Gemini o a Claude no se ha ejecutado en vivo.** No hay
  clave de API en este entorno. El esquema, el despacho de proveedor, la
  post-validación, el reintento correctivo y los caminos de error sí están
  escritos y se importan sin problema; queda hacer un informe con
  `GEMINI_API_KEY` o `ANTHROPIC_API_KEY` puesta para confirmar la ida y vuelta.
  Los identificadores de los modelos de Gemini y sus tarifas siguen sin
  contrastar contra la documentación de Google.
- **El PDF no se ha podido generar en esta máquina.** Falta el runtime de
  GTK/Pango, así que la ruta se ha probado solo hasta el 503. La maquetación de
  las secciones nuevas en `informe_pdf.html` no se ha visto impresa.
- **El acceso con Google no se ha probado contra Google.** Sin
  `GOOGLE_CLIENT_ID` el modo degradado sí funciona: se entra sin cuenta, se crea
  el usuario y se guarda todo.
- **Pendientes conocidos, ninguno bloqueante:** el bloque `audacia` del módulo
  visual no cuenta para el índice de audacia (que solo lee el módulo de
  acciones); y `ResultadoIA.meta()`
  se guarda como clave `_meta` dentro del JSON de recomendaciones mientras no
  exista una tabla propia para el coste y los tokens.
