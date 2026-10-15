/* Cuestionario de una pregunta por pantalla.
 *
 * Ciento cuarenta y cinco preguntas apiladas en una página son un muro: nadie
 * sabe cuánto le queda y se pierde al hacer scroll. De una en una, con avance
 * automático al elegir, se contestan casi tan rápido como se leen.
 *
 * Tres reglas que mandan sobre todo lo demás en este fichero:
 *
 *  1. El autoguardado NUNCA bloquea. localStorage es síncrono y va primero; la
 *     red va después y siempre en segundo plano. Ni un `await` entra en el
 *     camino de anotar(), siguiente() o pintar(). Si el servidor no contesta,
 *     se sigue contestando.
 *  2. El muro no es decorativo. En una pantalla de desempate se borra el valor
 *     anterior, se exige una respuesta nueva, distinta y no tibia, y Enter no
 *     vale: hay que elegir con el ratón o con la barra espaciadora.
 *  3. Nada se rellena solo. Un deslizador sin tocar no es una respuesta; un
 *     punto medio puesto por el programa es tibieza fabricada por el programa,
 *     y es justo lo que el informe castiga después.
 */

const CLAVE = 'branding_borrador_v4';
const RETARDO_AVANCE = 220;     // ms: se ve el clic marcado antes de pasar
const MAX_RONDAS_TIBIEZA = 2;   // debe coincidir con scoring.MAX_RONDAS_TIBIEZA
const ANTIRREBOTE = 1500;       // ms de antirrebote del PUT /api/borrador
const TIMEOUT_SUBIDA = 4000;    // ms de AbortController por subida
const ESPERA_MURO = 1200;       // ms mínimos en una pantalla de desempate
const ESPERAS_PUERTA = [1000, 3000, 8000]; // reintentos de /api/tibieza

const estado = {
  identidad: {},
  arquetipos: {},
  comunicacion: {},
  visual: {},
  acciones: {},
};

const SECCIONES = ['identidad', 'arquetipos', 'comunicacion', 'visual', 'acciones'];

let CONTENIDO = null;
let PASOS = [];
let i = 0;                    // índice del paso actual
let ronda = 0;                // cuántas veces se ha hecho repetir por tibieza
let YO = null;                // lo que devuelve GET /api/yo
let VERSION_BORRADOR = null;  // bloqueo optimista del servidor
let CLAVE_IDEM = null;        // randomUUID() para POST /api/informe
let localGuardado = null;     // lo que había en localStorage al arrancar
let DECISION = null;          // tarjeta de decisión que tapa el paso actual
let sinConexion = false;
let versionDudosa = false;    // hubo una subida cuya respuesta no pudimos leer
let muroReciente = false;     // el muro acaba de vaciar respuestas a propósito
let sinAlmacenamiento = false;
let avisadoSinAlmacenamiento = false;
let enviando = false;
let informeEmitido = null;    // {id, token} cuando ya se ha emitido

const $ = (id) => document.getElementById(id);
const escena = () => $('escena');
const pasoActual = () => DECISION || PASOS[i];
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

/* ================= Estilos que el CSS del proyecto todavía no trae =========
 *
 * app.css es de otro dueño y en esta tanda no se toca. Los tipos nuevos
 * (ranking, reparto100, duelo), los contadores de caracteres y —sobre todo— el
 * anillo de foco necesitan reglas que allí no existen. Se inyectan desde aquí
 * en vez de dejar la pantalla rota: es una deuda anotada, no una decisión de
 * arquitectura. */

const ESTILOS = `
/* El foco era invisible: los radios están a opacity 0 y width 0, así que el
   anillo del navegador se pintaba sobre nada. Sin esto el cuestionario no se
   puede recorrer con el teclado. */
.likert input:focus-visible + label,
.opciones input:focus-visible + label,
.escala-botones input:focus-visible + label,
.duelo input:focus-visible + .duelo-tarjeta {
  outline: 3px solid var(--marca); outline-offset: 3px;
}
.tarjeta-paso :focus-visible { outline: 3px solid var(--marca); outline-offset: 2px; }
.tarjeta-paso[tabindex="-1"]:focus { outline: none; }

.aviso-campo { font-size: 13px; color: var(--marca); margin: 6px 0 0; min-height: 1em; }
.contador-chars {
  font-size: 12px; color: var(--tenue); text-align: right;
  font-variant-numeric: tabular-nums; margin-top: 4px;
}
.contador-chars.corto { color: var(--marca); }
.texto-previo {
  border-left: 4px solid var(--linea); padding: 8px 0 8px 14px; margin: 0 0 14px;
  font-style: italic; color: var(--tinta-suave); white-space: pre-wrap;
}
.texto-previo .rotulo {
  display: block; font-style: normal; font-size: 11px; letter-spacing: .12em;
  text-transform: uppercase; color: var(--tenue); margin-bottom: 6px;
}
.atajos { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.atajo {
  font: inherit; font-size: 13.5px; padding: 7px 12px; cursor: pointer;
  border: 1px solid var(--linea); border-radius: 999px; background: transparent;
  color: var(--tinta-suave);
}
.atajo:hover { border-color: var(--marca); color: var(--tinta); }
.sugerencia { cursor: pointer; }
.sugerencia-caja { width: 100%; }
.sugerencia-aviso { font-size: 12px; color: var(--tenue); margin: 4px 0 0 6px; }

/* El bipolar pasa a botones también fuera del desempate, así que los polos
   necesitan aquí la descripción que antes solo tenía el deslizador. */
.bipolar-desempate .polo strong { display: block; font-size: 16px; margin-bottom: 2px; }
.bipolar-desempate .polo span { font-size: 13px; color: var(--tenue); }

/* ---- ranking ---- */
.ranking-rotulo {
  font-size: 11px; letter-spacing: .12em; text-transform: uppercase;
  color: var(--tenue); margin: 0 0 8px;
}
.ranking-elegidos { margin-bottom: 22px; }
.ranking-lista { display: grid; gap: 8px; }
.ranking-pool .ranking-lista { grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (max-width: 640px) { .ranking-pool .ranking-lista { grid-template-columns: 1fr; } }
.ranking-op {
  display: flex; gap: 12px; align-items: flex-start; text-align: left; width: 100%;
  font: inherit; cursor: pointer; padding: 11px 13px;
  border: 1px solid var(--linea); border-radius: 10px; background: transparent;
  color: var(--tinta);
}
.ranking-op:hover { border-color: var(--marca); }
.ranking-op .et { display: block; font-size: 14.5px; font-weight: 500; }
.ranking-op .de { display: block; font-size: 12px; line-height: 1.4; color: var(--tenue); margin-top: 1px; }
.ranking-op .puesto {
  flex-shrink: 0; width: 24px; height: 24px; border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700; background: var(--marca); color: #fff;
}
.ranking-elegidos .ranking-op { border-color: var(--marca); }
.ranking-pool .ranking-op { opacity: .62; }
.ranking-pool .ranking-op:hover { opacity: 1; }
.ranking-hueco {
  border: 1px dashed var(--linea); border-radius: 10px; padding: 11px 13px;
  font-size: 14px; color: var(--tenue);
}

/* ---- reparto100 ---- */
.reparto-marcador {
  position: sticky; top: 0; z-index: 2; background: var(--fondo, #fff);
  padding: 10px 0 12px; margin-bottom: 6px; font-size: 15px; font-weight: 600;
  border-bottom: 1px solid var(--linea);
}
.reparto-marcador .n { font-variant-numeric: tabular-nums; color: var(--marca); }
.reparto-fila {
  display: flex; gap: 12px; align-items: center;
  padding: 9px 0; border-bottom: 1px solid var(--linea);
}
.reparto-fila.sacude { animation: sacude 0.35s; }
.reparto-fila .cuerpo { flex: 1; min-width: 0; }
.reparto-fila .et { display: block; font-size: 15px; font-weight: 500; }
.reparto-fila .de { display: block; font-size: 12px; line-height: 1.4; color: var(--tenue); }
.reparto-mando { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.reparto-mando button {
  width: 34px; height: 34px; border-radius: 8px; border: 1px solid var(--linea);
  background: transparent; color: var(--tinta); font-size: 17px; cursor: pointer; line-height: 1;
}
.reparto-mando button:hover { border-color: var(--marca); }
.reparto-mando .puntos {
  min-width: 46px; text-align: center; font-variant-numeric: tabular-nums;
  font-size: 16px; font-weight: 600;
}
.reparto-fila.con-puntos .puntos { color: var(--marca); }

/* ---- duelo ---- */
.duelo { display: flex; gap: 16px; margin: 4px 0 18px; }
.duelo input { position: absolute; opacity: 0; width: 0; height: 0; }
.duelo > div { flex: 1; min-width: 0; }
.duelo-tarjeta {
  display: block; cursor: pointer; height: 100%;
  border: 1px solid var(--linea); border-radius: 12px; padding: 14px; background: transparent;
}
.duelo-tarjeta:hover { border-color: var(--marca); }
.duelo input:checked + .duelo-tarjeta { border-color: var(--marca); box-shadow: inset 0 0 0 1px var(--marca); }
.duelo-tarjeta img {
  width: 100%; aspect-ratio: 1 / 1; object-fit: cover;
  border-radius: 8px; background: var(--linea); display: block;
}
.duelo-tarjeta .nombre { font-size: 17px; font-weight: 600; margin-top: 10px; }
.duelo-tarjeta .titular { font-size: 13.5px; color: var(--tinta-suave); margin-top: 2px; }
.duelo-tarjeta .estilo { font-size: 12.5px; color: var(--tenue); margin-top: 8px; max-height: 8.5em; overflow: auto; }
.duelo-tarjeta .prendas { list-style: none; padding: 0; margin: 8px 0 0; }
.duelo-tarjeta .prendas li { font-size: 12.5px; padding: 1px 0; }
.duelo-tarjeta .atribucion { font-size: 10.5px; color: var(--tenue); margin-top: 8px; }
@media (max-width: 640px) { .duelo { flex-direction: column; } }
`;

function inyectarEstilos() {
  if ($('estilos-form')) return;
  const s = document.createElement('style');
  s.id = 'estilos-form';
  s.textContent = ESTILOS;
  document.head.appendChild(s);
}

/* ================= Utilidades ================= */

function escapar(s) {
  const d = document.createElement('div');
  d.textContent = s ?? '';
  return d.innerHTML;
}

/* Misma normalización que contenido/lexico_evasion.json declara para el
   servidor: minúsculas, sin tildes, puntuación a espacio, espacios colapsados. */
function normalizar(s) {
  return String(s ?? '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9ñ\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const NOMBRES_SECCION = {
  identidad: 'Quién eres',
  arquetipos: 'Arquetipo',
  comunicacion: 'Comunicación',
  visual: 'Visual',
  acciones: 'Acciones',
};

// Las preguntas de desempate son un extra sobre el cuestionario: no cuentan para
// el total ni mueven la barra de progreso.
const totalPreguntas = () =>
  PASOS.filter((p) => p.tipo === 'pregunta' && !p.desempate).length;
const preguntasHasta = (n) =>
  PASOS.slice(0, n + 1).filter((p) => p.tipo === 'pregunta' && !p.desempate).length;

function vacio(v) {
  if (v === undefined || v === null) return true;
  if (typeof v === 'string') return v.trim() === '';
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === 'object') return Object.keys(v).length === 0;
  return false;
}

/* El mismo recuento que db.contar_contestadas: es el árbitro de los conflictos
   entre este navegador y la cuenta, y dos recuentos distintos acaban divergiendo
   justo el día que hay que arbitrar. */
function contarContestadasDe(datos) {
  let n = 0;
  SECCIONES.forEach((sec) => {
    const bloque = datos?.[sec];
    if (!bloque || typeof bloque !== 'object') return;
    Object.values(bloque).forEach((v) => {
      if (!vacio(v)) n += 1;
    });
  });
  return n;
}
const contarContestadas = () => contarContestadasDe(estado);

function referentesIndice() {
  const crudo = CONTENIDO?.referentes;
  const lista = Array.isArray(crudo) ? crudo : (crudo?.referentes || []);
  const idx = {};
  lista.forEach((r) => { if (r?.id) idx[r.id] = r; });
  return idx;
}

function lexico() {
  return CONTENIDO?.lexico_evasion || {};
}

/* Mínimo de caracteres de un texto: el del contenido y el del léxico son la
   misma regla escrita dos veces; se aplica el más exigente para que el cliente
   nunca deje pasar algo que el servidor va a rechazar. */
function minCaracteres(id, propio) {
  const lex = (lexico().minimos || {})[id] || {};
  return Math.max(Number(propio) || 0, Number(lex.min_chars) || 0);
}

const usoAtajo = (id) => estado.identidad[`_atajo_${id}`] === true;

/* ================= Persistencia local ================= */

function guardar() {
  try {
    localStorage.setItem(CLAVE, JSON.stringify({
      v: 4,
      estado,
      ronda,
      contestadas: contarContestadas(),
      version: VERSION_BORRADOR,
      idem: CLAVE_IDEM,
      ultimoId: PASOS[i]?.pregunta?.id ?? null,
      tipoPaso: PASOS[i]?.tipo ?? null,
      usuario_id: YO?.usuario_id ?? null,
      informe_id: informeEmitido?.id ?? null,
    }));
  } catch {
    // Nada de removeItem aquí: cuando el accesor está bloqueado (iOS Safari con
    // «bloquear todas las cookies», iframe de tercero) el remove vuelve a lanzar
    // y la excepción sale de anotar(), que corta antes de repintar el pie. Sin
    // localStorage se degrada a «solo servidor» y se sigue contestando.
    sinAlmacenamiento = true;
    avisarSinAlmacenamiento();
  }
  programarSubida();
}

function restaurar() {
  try {
    const c = JSON.parse(localStorage.getItem(CLAVE) || 'null');
    if (!c || c.v !== 4) return null;
    if (c.estado) Object.assign(estado, c.estado);
    ronda = Number(c.ronda) || 0;
    VERSION_BORRADOR = c.version ?? null;
    CLAVE_IDEM = c.idem || null;
    return c;
  } catch {
    return null;
  }
}

function avisarSinAlmacenamiento() {
  if (avisadoSinAlmacenamiento || !sinConexion) return;
  avisadoSinAlmacenamiento = true;
  marcarEstado(
    'Tu navegador no deja guardar y el servidor no contesta. No cierres esta pestaña: si la cierras, pierdes lo contestado.',
    { sinRed: true, persistente: true },
  );
}

/* ================= Autoguardado en el servidor ================= */

let subiendo = false;
let pendienteSubida = false;
let relojSubida = null;
let relojEstado = null;
let espera = 2000;

function cuerpoBorrador() {
  return {
    respuestas: estado,
    paso: i,
    ronda,
    ultimo_id: PASOS[i]?.pregunta?.id ?? null,
    // Tras una subida a ciegas (pagehide) no sabemos qué versión quedó en el
    // servidor. Mandar null fuerza un 409 con sus cifras y lo resolvemos allí.
    version: versionDudosa ? null : VERSION_BORRADOR,
  };
}

function marcarEstado(texto, { sinRed = false, persistente = false } = {}) {
  const el = $('estado-guardado');
  if (!el) return;
  el.textContent = texto;
  el.classList.toggle('sin-red', sinRed);
  clearTimeout(relojEstado);
  if (!persistente) {
    relojEstado = setTimeout(() => {
      if (!sinConexion && el.textContent === texto) el.textContent = '';
    }, 2000);
  }
}

function programarSubida() {
  // Antes de pasar la puerta no hay cuenta: subir aquí crearía un usuario
  // anónimo a espaldas de quien todavía no ha decidido nada.
  if (!YO?.autenticado) return;
  clearTimeout(relojSubida);
  relojSubida = setTimeout(() => subirBorrador(), ANTIRREBOTE);
}

async function subirBorrador({ forzar = false } = {}) {
  if (!YO?.autenticado) return;
  if (forzar) clearTimeout(relojSubida);
  if (subiendo) { pendienteSubida = true; return; }
  subiendo = true;
  marcarEstado('Guardando…');

  const ctl = new AbortController();
  const reloj = setTimeout(() => ctl.abort(), TIMEOUT_SUBIDA);
  try {
    const r = await fetch('/api/borrador', {
      method: 'PUT',
      signal: ctl.signal,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpoBorrador()),
    });
    if (r.status === 409) {
      versionDudosa = false;
      return resolverConflicto(await r.json());
    }
    if (!r.ok) throw new Error(String(r.status));
    const d = await r.json();
    VERSION_BORRADOR = d.version;
    versionDudosa = false;
    espera = 2000;
    sinConexion = false;
    marcarEstado('Guardado');
  } catch {
    sinConexion = true;
    marcarEstado('Sin conexión — guardado en este navegador', { sinRed: true, persistente: true });
    if (sinAlmacenamiento) avisarSinAlmacenamiento();
    setTimeout(() => subirBorrador({ forzar: true }), espera);
    espera = Math.min(espera * 2.5, 30000); // 2 / 5 / 12,5 / 30 s
  } finally {
    clearTimeout(reloj);
    subiendo = false;
    if (pendienteSubida) { pendienteSubida = false; programarSubida(); }
  }
}

/* El servidor tiene otra versión. `contestadas` es el árbitro, nunca el reloj:
   el reloj del cliente es del cliente, y un móvil con la hora adelantada pisaría
   96 respuestas con 3. El umbral de 5 existe para no interrumpir por un
   desajuste de una respuesta y sí preguntar cuando hay trabajo en juego. */
function resolverConflicto(cuerpo) {
  const s = cuerpo?.servidor || {};
  const nServidor = Number(s.contestadas) || 0;
  const nLocal = contarContestadas();

  /* El muro acaba de borrar del estado las respuestas que va a repreguntar, y
     el servidor ha subido la versión del borrador al anotar la ronda. Ese 409
     no es otro dispositivo: es este. Sin esta rama, la tarjeta de las dos
     versiones tapaba el muro entero y su botón «seguir con las de mi cuenta»
     devolvía las respuestas tibias, deshaciéndolo. Manda lo que hay aquí. */
  if (muroReciente) {
    muroReciente = false;
    VERSION_BORRADOR = s.version ?? null;
    return subirBorrador({ forzar: true });
  }

  if (nServidor > nLocal + 5) { pedirDecision('conflicto', { servidor: s, nLocal }); return; }
  if (nServidor > nLocal) return adoptarServidor();
  VERSION_BORRADOR = s.version ?? null;
  return subirBorrador({ forzar: true });
}

async function adoptarServidor() {
  const ctl = new AbortController();
  const reloj = setTimeout(() => ctl.abort(), TIMEOUT_SUBIDA);
  try {
    // Con reloj: esto se llama desde el arranque y una lectura colgada dejaría
    // la pantalla en blanco esperando a un servidor que no va a contestar.
    const r = await fetch('/api/borrador', { credentials: 'same-origin', signal: ctl.signal });
    if (r.status === 204 || !r.ok) return;
    const d = await r.json();
    SECCIONES.forEach((sec) => { estado[sec] = {}; });
    Object.assign(estado, d.respuestas || {});
    ronda = Math.max(ronda, Number(d.ronda) || 0);
    VERSION_BORRADOR = d.version ?? null;
    versionDudosa = false;
    guardarLocalSinSubir();
    marcarEstado(`He recuperado ${contarContestadas()} respuestas de tu cuenta.`, { persistente: true });
    setTimeout(() => marcarEstado(''), 6000);
    if (PASOS.length) { DECISION = null; i = posicionInicial(); pintar(); }
  } catch {
    sinConexion = true;
    marcarEstado('Sin conexión — guardado en este navegador', { sinRed: true, persistente: true });
  } finally {
    clearTimeout(reloj);
  }
}

/* Escribe en el navegador sin disparar una subida: se usa justo después de
   adoptar el estado del servidor, donde volver a subirlo no aporta nada. */
function guardarLocalSinSubir() {
  const antes = YO;
  YO = { ...(YO || {}), autenticado: false };
  guardar();
  YO = antes;
}

/* Al cerrar la pestaña, `fetch` normal no se entrega. `keepalive` sí.
   No se usa sendBeacon aunque la especificación lo pedía: /api/borrador es PUT
   y sendBeacon solo sabe hacer POST, así que el beacon se comería un 405. */
function subidaDeCierre() {
  if (!YO?.autenticado) return;
  try {
    const cuerpo = JSON.stringify(cuerpoBorrador());
    versionDudosa = true; // no vamos a poder leer la respuesta
    fetch('/api/borrador', {
      method: 'PUT',
      keepalive: true,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: cuerpo,
    }).catch(() => {});
  } catch { /* la pestaña se está yendo: no hay a quién avisar */ }
}

function engancharCiclo() {
  document.addEventListener('visibilitychange', () => {
    // Oculta pero viva: cabe una subida normal y sí podemos leer la versión.
    if (document.visibilityState === 'hidden') subirBorrador({ forzar: true });
  });
  window.addEventListener('pagehide', subidaDeCierre);
  window.addEventListener('online', () => {
    sinConexion = false;
    espera = 2000;
    subirBorrador({ forzar: true });
  });
  window.addEventListener('offline', () => {
    sinConexion = true;
    marcarEstado('Sin conexión — guardado en este navegador', { sinRed: true, persistente: true });
  });
}

/* ================= Acceso ================= */

async function entrar(url, cuerpo) {
  const r = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cuerpo || {}),
  });
  if (!r.ok) {
    let detalle = 'No se ha podido abrir la sesión.';
    try { detalle = (await r.json()).detail || detalle; } catch { /* cuerpo no JSON */ }
    throw new Error(detalle);
  }
  return r.json();
}

async function tramitarAcceso(url, cuerpo) {
  const aviso = $('aviso-acceso');
  if (aviso) aviso.textContent = 'Un momento…';
  try {
    YO = await entrar(url, cuerpo);
    sinConexion = false;
    reconstruirTrasAcceso();
  } catch (e) {
    if (aviso) {
      aviso.textContent = e.message;
      const salida = $('acceso-sin-servidor');
      if (salida) salida.hidden = false;
    }
  }
}

/* Sin puerta y sin cuenta: se sigue con localStorage y se deja marcado para que
   el autoguardado lo reintente en cuanto haya sesión. El cuestionario no se
   bloquea jamás por la puerta. */
function seguirSinServidor() {
  sinConexion = true;
  YO = { ...(YO || {}), autenticado: false, sinServidor: true };
  PASOS = construirPasos({ conAcceso: false });
  i = posicionInicial();
  marcarEstado('Sin conexión — guardado en este navegador', { sinRed: true, persistente: true });
  pintar();
}

async function reconstruirTrasAcceso() {
  PASOS = construirPasos({ conAcceso: false });
  await resolverBorrador(localGuardado);
  // La fusión solo llega en la respuesta de /api/auth/google, no en /api/yo.
  avisarFusion();
  if (!DECISION) {
    i = posicionInicial();
    pintar();
  }
  guardar();
}

// El callback que declara data-callback en index.html.
window.alEntrarConGoogle = async (resp) => {
  await tramitarAcceso('/api/auth/google', { credential: resp?.credential });
};

function hayGoogle() {
  return document.body.dataset.google === '1';
}

function pintarBotonGoogle() {
  const hueco = $('boton-google');
  if (!hueco || !hayGoogle()) return;
  const gis = window.google?.accounts?.id;
  if (!gis) {
    // La librería llega con async defer; si aún no está, se reintenta un par de
    // veces antes de rendirse. Sin ella queda «Continuar sin cuenta», que basta.
    if ((pintarBotonGoogle.intentos = (pintarBotonGoogle.intentos || 0) + 1) < 12) {
      setTimeout(pintarBotonGoogle, 250);
    }
    return;
  }
  pintarBotonGoogle.intentos = 0;
  try {
    gis.renderButton(hueco, {
      theme: 'outline', size: 'large', text: 'continue_with',
      locale: 'es', width: 320, shape: 'rectangular',
    });
  } catch { /* si GIS falla, el otro botón sigue ahí */ }
}

/* ================= Borrador: servidor contra navegador ================= */

/* Las subidas van SIN await a propósito: esto se llama desde el arranque y
   esperar a un PUT dejaría la primera pantalla en blanco hasta cuatro segundos.
   Solo se espera a `adoptarServidor`, porque sin esos datos no hay nada que
   pintar. El árbitro es `contestadas`, nunca el reloj. */
async function resolverBorrador(local) {
  const s = YO?.borrador || null;
  const nLocal = local ? contarContestadasDe(local.estado) : 0;
  if (!s && !local) return;
  if (!s) { VERSION_BORRADOR = null; subirBorrador({ forzar: true }); return; }

  ronda = Math.max(ronda, Number(s.ronda) || 0);
  if (!local || nLocal === 0) return adoptarServidor();

  const nServidor = Number(s.contestadas) || 0;
  if (nServidor > nLocal + 5) { pedirDecision('conflicto', { servidor: s, nLocal }); return; }
  if (nServidor > nLocal) return adoptarServidor();
  VERSION_BORRADOR = s.version ?? null;
  subirBorrador({ forzar: true });
}

/* Al entrar con Google después de haber empezado sin cuenta puede haber dos
   cuestionarios a medias. db.entrar_con_google devuelve
   {ganador: {contestadas, actualizado_en}, descartado: {...}}: el servidor ya ha
   elegido el de más respuestas y ha archivado el otro. Aquí solo se cuenta lo
   que ha pasado y se ofrece deshacerlo. */
function avisarFusion() {
  const f = YO?.fusion;
  if (!f?.ganador || !f?.descartado) return;
  pedirDecision('fusion', {
    mayor: Number(f.ganador.contestadas) || 0,
    menor: Number(f.descartado.contestadas) || 0,
  });
}

function pedirDecision(clave, datos) {
  DECISION = { tipo: 'decision', clave, datos };
  if (PASOS.length) pintar();
}

/* ================= Construcción de los pasos ================= */

function construirPasos({ conAcceso = false } = {}) {
  const pasos = [];
  if (conAcceso) pasos.push({ tipo: 'acceso' });
  pasos.push({ tipo: 'intro' });

  // --- Identidad, también de una en una.
  pasos.push({ tipo: 'seccion', seccion: 'identidad', titulo: 'Quién eres',
               sub: 'Tres datos y empezamos.' });
  pasos.push({ tipo: 'nombre', seccion: 'identidad' });
  pasos.push({ tipo: 'tipo_marca', seccion: 'identidad' });
  pasos.push({ tipo: 'email', seccion: 'identidad' });

  // --- Test de arquetipos.
  const test = CONTENIDO.test;
  pasos.push({
    tipo: 'seccion',
    seccion: 'arquetipos',
    titulo: 'Tu arquetipo',
    sub: test.instrucciones,
  });

  const items = [...test.items];
  // Los controles de atención se intercalan para que no canten.
  (test.control || []).forEach((c, n) => {
    items.splice(Math.floor(((n + 1) * items.length) / 3), 0, { ...c, control: true });
  });
  items.forEach((it) =>
    pasos.push({
      tipo: 'pregunta',
      seccion: 'arquetipos',
      pregunta: { ...it, tipo: 'likert5', escala: test.escala },
    }),
  );

  pasos.push({
    tipo: 'seccion',
    seccion: 'arquetipos',
    titulo: 'Desempate',
    sub: 'Aquí no hay respuestas cómodas: las cuatro opciones son igual de respetables. Elige la que tu marca defendería si tuviera que renunciar a las otras tres.',
  });
  (test.eleccion_forzada || []).forEach((fc) =>
    pasos.push({ tipo: 'pregunta', seccion: 'arquetipos', pregunta: preguntaFC(fc) }),
  );

  // --- Los tres módulos, bloque a bloque.
  ['comunicacion', 'visual', 'acciones'].forEach((clave) => {
    const modulo = CONTENIDO.modulos[clave];
    pasos.push({
      tipo: 'seccion',
      seccion: clave,
      titulo: modulo.nombre,
      sub: modulo.descripcion,
      grande: true,
    });
    (modulo.bloques || []).forEach((b) => {
      pasos.push({
        tipo: 'seccion',
        seccion: clave,
        titulo: b.nombre,
        sub: b.descripcion || '',
      });
      (b.preguntas || []).forEach((p) =>
        pasos.push({ tipo: 'pregunta', seccion: clave, pregunta: p }),
      );
    });
  });

  // El nombre de marca, al final: las sugerencias necesitan el territorio, el
  // color, el sello y el formato, y ninguno de esos existe en la pregunta 3.
  pasos.push({ tipo: 'artistico', seccion: 'identidad' });
  pasos.push({ tipo: 'final' });
  return pasos;
}

function preguntaFC(fc) {
  return {
    id: fc.id,
    tipo: 'unica',
    texto: fc.enunciado,
    opciones: (fc.opciones || []).map((o, n) => ({ valor: n, etiqueta: o.texto })),
  };
}

/* Índice {seccion: {id: pregunta}} para reconstruir un paso a partir del id que
   devuelve /api/tibieza. Las preguntas del test se guardan con la forma con la
   que se pintan, y los bloques de elección forzada entran también: el muro por
   perfil plano los reofrece cuando están sin contestar. */
let INDICE_CACHE = null;
const indiceCacheado = () => (INDICE_CACHE = INDICE_CACHE || indicePreguntas());

/* Las opciones de una pregunta, resolviendo `opciones_de`.
 *
 * COM-CA-2 («¿cuál será tu casa principal?») no tiene opciones propias: se
 * elige entre lo que se marcó en COM-CA-1. Hasta hoy nadie resolvía esa
 * referencia en el navegador y la pantalla reventaba con «Cannot read
 * properties of undefined», dejando el cuestionario muerto en la pregunta 20.
 * El servidor (informe._opciones) resuelve la lista COMPLETA; aquí se enseña
 * solo lo que la persona marcó, que es lo que la pregunta promete. */
function opcionesDe(paso) {
  const p = paso.pregunta || {};
  if (p.opciones?.length) return p.opciones;
  if (!p.opciones_de) return [];

  const idx = indiceCacheado();
  let origen = null;
  let seccionOrigen = null;
  Object.keys(idx).forEach((sec) => {
    if (idx[sec][p.opciones_de]) { origen = idx[sec][p.opciones_de]; seccionOrigen = sec; }
  });
  if (!origen) return [];

  const todas = origen.opciones || [];
  const previas = estado[seccionOrigen]?.[p.opciones_de];
  const marcadas = Array.isArray(previas)
    ? previas.map(String)
    : (previas === undefined || previas === null ? [] : [String(previas)]);
  const filtradas = todas.filter((o) => marcadas.includes(String(o.valor)));
  // Si todavía no ha contestado la pregunta de la que depende, se enseñan
  // todas: una pantalla vacía es peor que una lista de más.
  return filtradas.length ? filtradas : todas;
}

function indicePreguntas() {
  const idx = { arquetipos: {}, comunicacion: {}, visual: {}, acciones: {} };
  const test = CONTENIDO.test;
  [...(test.items || []), ...(test.control || [])].forEach((it) => {
    idx.arquetipos[it.id] = { ...it, tipo: 'likert5', escala: test.escala };
  });
  (test.eleccion_forzada || []).forEach((fc) => { idx.arquetipos[fc.id] = preguntaFC(fc); });
  ['comunicacion', 'visual', 'acciones'].forEach((sec) => {
    (CONTENIDO.modulos[sec].bloques || []).forEach((b) =>
      (b.preguntas || []).forEach((p) => { idx[sec][p.id] = p; }),
    );
  });
  return idx;
}

/* ================= Validación ================= */

function valorDe(paso) {
  if (paso.tipo === 'pregunta') return estado[paso.seccion][paso.pregunta.id];
  if (paso.tipo === 'nombre') return estado.identidad.nombre;
  if (paso.tipo === 'artistico') return estado.identidad.artistico;
  if (paso.tipo === 'tipo_marca') return estado.identidad.tipo_marca;
  return undefined;
}

/* Qué le falta a esta respuesta, con el texto que se le enseña debajo del
   campo. `null` significa que está bien. Es la única fuente de verdad de
   contestado(): dos reglas paralelas se separan a la tercera semana. */
function problema(paso) {
  if (paso.tipo !== 'pregunta') return null;
  const p = paso.pregunta;
  const v = valorDe(paso);

  if (p.tipo === 'multiple') {
    const sel = Array.isArray(v) ? v : [];
    const min = Number.isFinite(Number(p.min)) ? Number(p.min) : 1;
    if (sel.length < min) {
      if (min === 0) return null;
      return `Marca ${min === 1 ? 'al menos una' : `al menos ${min}`}.`;
    }
    if (p.max && sel.length > p.max) return `Ya tienes ${p.max}; desmarca una para cambiar.`;
    return null;
  }

  if (p.tipo === 'ranking') {
    const sel = Array.isArray(v) ? v : [];
    const n = Number(p.exactamente) || 3;
    if (sel.length < n) {
      const faltan = n - sel.length;
      return `${faltan === 1 ? 'Te falta 1' : `Te faltan ${faltan}`} por elegir. Son ${n}, en orden.`;
    }
    if (sel.length > n) return `Son ${n}, ni uno más.`;
    return null;
  }

  if (p.tipo === 'reparto100') {
    const rep = (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};
    const suma = Object.values(rep).reduce((a, b) => a + (Number(b) || 0), 0);
    const objetivo = Number(p.suma) || 100;
    const conPuntos = Object.values(rep).filter((x) => Number(x) > 0).length;
    const mayor = Object.values(rep).reduce((a, b) => Math.max(a, Number(b) || 0), 0);
    if (suma !== objetivo) {
      return suma < objetivo
        ? `Reparte los ${objetivo - suma} que te sobran.`
        : `Te has pasado en ${suma - objetivo}: quita puntos de algún sitio.`;
    }
    if (p.min_dominante && mayor < p.min_dominante) {
      return `Ninguna llega a ${p.min_dominante}: así no se nota en ninguna foto.`;
    }
    if (p.max_con_puntos && conPuntos > p.max_con_puntos) {
      return `Has repartido entre ${conPuntos}: deja ${p.max_con_puntos} y las otras a cero.`;
    }
    return null;
  }

  if (p.tipo === 'duelo') {
    const d = (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};
    if (!d.elegido) return 'Elige uno de los dos. Empatar aquí no es una respuesta.';
    const min = minCaracteres(`${p.id}.no_copio`, p.no_copio?.min_chars);
    const texto = String(d.no_copio || '').trim();
    if (texto.length < min) {
      return `Te faltan ${min - texto.length} caracteres. No es burocracia: ahí es donde apareces tú.`;
    }
    return null;
  }

  if (p.tipo === 'texto' || p.tipo === 'texto_largo') {
    if (usoAtajo(p.id)) return null;
    const texto = String(v || '').trim();
    const min = minCaracteres(p.id, p.min_chars);
    if (!texto) return min ? `Te faltan ${min} caracteres.` : 'Escribe algo.';
    if (texto.length < min) {
      return `Te faltan ${min - texto.length} caracteres. No es burocracia: con menos de eso no hay nada que un desconocido pueda repetir sobre ti.`;
    }
    return null;
  }

  // COM-CA-2 hereda sus opciones de COM-CA-1: si se desmarca allí el sitio que
  // aquí era la casa principal, esto deja de ser una respuesta válida.
  if (p.opciones_de && !vacio(v)) {
    const hay = opcionesDe(paso).some((o) => String(o.valor) === String(v));
    if (!hay) return 'Eso ya no está entre lo que has elegido antes. Elige otra vez.';
  }
  return vacio(v) ? 'Elige una opción.' : null;
}

/* ¿Está tibia esta respuesta? Solo se pregunta en las pantallas del muro: en el
   cuestionario normal la tibieza se mide en el servidor y no se castiga aquí. */
function esTibio(paso, v) {
  const p = paso.pregunta;
  if (!p) return false;

  if (p.tipo === 'likert5') return Number(v) === 3;
  if (p.tipo === 'bipolar') {
    const max = Number(p.escala) || 7;
    return Number(v) === Math.ceil(max / 2);
  }
  if (p.tipo === 'unica') {
    const elegida = (p.opciones || []).find((o) => String(o.valor) === String(v));
    return Boolean(elegida?.evasiva);
  }
  if (p.tipo === 'multiple') {
    const sel = Array.isArray(v) ? v : [];
    const min = Number.isFinite(Number(p.min)) ? Number(p.min) : 1;
    if (sel.length < min) return true;
    if (p.max && sel.length >= p.max) return true; // marcarlo todo es no elegir
    const evasivas = new Set((p.opciones || []).filter((o) => o.evasiva).map((o) => String(o.valor)));
    return sel.length > 0 && sel.every((x) => evasivas.has(String(x)));
  }
  if (p.tipo === 'reparto100') {
    const rep = (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};
    const mayor = Object.values(rep).reduce((a, b) => Math.max(a, Number(b) || 0), 0);
    return mayor < (Number(p.min_dominante) || 0);
  }
  if (p.tipo === 'duelo') {
    const d = (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};
    if (!d.elegido) return true;
    const min = minCaracteres(`${p.id}.no_copio`, p.no_copio?.min_chars);
    return String(d.no_copio || '').trim().length < min;
  }
  if (p.tipo === 'texto' || p.tipo === 'texto_largo') {
    return problema(paso) !== null;
  }
  return false;
}

function contestado(paso) {
  if (!paso) return true;
  if (paso.tipo === 'email') return true; // opcional

  // El muro. Aquí no vale el valor viejo: insertarDesempate lo ha borrado del
  // estado y lo guarda en paso.valorPrevio, así que valorDe() devuelve undefined
  // y no hay dos fuentes de verdad. Además la respuesta nueva tiene que ser
  // distinta de la anterior y no puede volver a ser tibia.
  if (paso.sinCentro) {
    const v = valorDe(paso);
    if (vacio(v)) return false;
    if (mismaRespuesta(v, paso.valorPrevio)) return false;
    if (problema(paso) !== null) return false;
    return !esTibio(paso, v);
  }
  if (paso.rehacer) {
    const v = valorDe(paso);
    if (vacio(v)) return false;
    return problema(paso) === null;
  }

  // Intros, interludios y tarjetas no se contestan: nunca bloquean el pie.
  if (paso.tipo !== 'pregunta') return true;
  if (paso.pregunta.opcional) return true;
  return problema(paso) === null;
}

function mismaRespuesta(a, b) {
  if (b === undefined || b === null) return false;
  if (typeof a === 'object' && a !== null) {
    try { return JSON.stringify(a) === JSON.stringify(b); } catch { return false; }
  }
  return String(a) === String(b);
}

/* ================= Render ================= */

function pintar() {
  const paso = pasoActual();
  const e = escena();
  e.className = 'entrando';
  e.innerHTML = plantilla(paso);
  requestAnimationFrame(() => { e.className = ''; });

  if (paso.sinCentro && !paso.desde) paso.desde = Date.now();

  actualizarProgreso();
  actualizarPie(paso);
  enlazar(paso);

  // El foco tiene que entrar en la tarjeta nueva o el cuestionario no se puede
  // recorrer con el teclado: hoy se quedaba en el botón del pie para siempre.
  const campo = e.querySelector('input[type="text"], input[type="email"], textarea');
  if (campo) {
    campo.focus();
  } else {
    const tarjeta = e.querySelector('.tarjeta-paso');
    if (tarjeta) { tarjeta.setAttribute('tabindex', '-1'); tarjeta.focus(); }
  }
  window.scrollTo(0, 0);
}

function plantilla(paso) {
  switch (paso.tipo) {
    case 'acceso':
      return plantillaAcceso();

    case 'decision':
      return plantillaDecision(paso);

    case 'intro':
      return `
        <div class="tarjeta-paso portada-intro">
          <h1>Averigua qué marca eres<br>y qué estás dispuesto a hacer.</h1>
          <p class="entradilla">
            Un test de arquetipos y tres módulos: comunicación, visual y acciones.
            Al final, un informe en PDF con tres direcciones concretas.
          </p>
          <div class="nota">
            <strong>Contesta como quieres ser percibido, no como te ves hoy.</strong>
            Y usa todo el rango de la escala: si lo puntúas todo alto, el resultado
            no te servirá de nada — solo dirá que todos los arquetipos te parecen
            simpáticos.
          </div>
          <div class="datos-intro">
            <div><strong>${totalPreguntas()}</strong> preguntas</div>
            <div><strong>~35</strong> minutos</div>
            <div><strong>Se guarda</strong> solo</div>
          </div>
        </div>`;

    case 'seccion':
      return `
        <div class="tarjeta-paso interstitial ${paso.grande ? 'grande' : ''}">
          <div class="kicker">${escapar(NOMBRES_SECCION[paso.seccion] || '')}</div>
          <h2>${escapar(paso.titulo)}</h2>
          ${paso.sub ? `<p class="entradilla">${escapar(paso.sub)}</p>` : ''}
        </div>`;

    case 'nombre':
      return `
        <div class="tarjeta-paso">
          <h2>¿Cómo te llamas?</h2>
          <div class="fila">
            <div class="campo">
              <label for="c-nombre">Nombre</label>
              <input type="text" id="c-nombre" autocomplete="given-name"
                     value="${escapar(estado.identidad.nombre || '')}">
            </div>
            <div class="campo">
              <label for="c-apellidos">Apellidos</label>
              <input type="text" id="c-apellidos" autocomplete="family-name"
                     value="${escapar(estado.identidad.apellidos || '')}">
            </div>
          </div>
        </div>`;

    case 'artistico':
      return `
        <div class="tarjeta-paso">
          <h2>¿Y cómo quieres que te llamen?</h2>
          <p class="ayuda-paso" id="ayuda-artistico">
            Tu nombre artístico o de marca. Un buen nombre es fácil de decir en voz
            alta, fácil de buscar y difícil de confundir con otro. Abajo tienes seis
            hechos con lo que acabas de contestar: el territorio que has puesto
            primero, tu sello, tu color y tu formato fijo.
          </p>
          <div class="campo">
            <input type="text" id="c-artistico" placeholder="Tu nombre de marca"
                   aria-describedby="ayuda-artistico"
                   value="${escapar(estado.identidad.artistico || '')}">
          </div>
          <div class="sugerencias" id="sugerencias"></div>
        </div>`;

    case 'tipo_marca':
      return `
        <div class="tarjeta-paso">
          <h2 id="titulo-paso">¿Qué estás construyendo?</h2>
          <div class="opciones" role="group" aria-labelledby="titulo-paso">
            ${[
              ['personal', 'Marca personal', 'La marca eres tú: tu cara, tu nombre, tu criterio.'],
              ['empresa', 'Marca de empresa', 'La marca sobrevive a las personas que la hacen.'],
            ]
              .map(
                ([v, et, de], n) => `
              <div class="opcion">
                <input type="radio" name="tipo_marca" id="tm-${n}" value="${v}"
                       ${estado.identidad.tipo_marca === v ? 'checked' : ''}>
                <label for="tm-${n}">
                  <span class="tecla">${n + 1}</span>
                  <span class="cuerpo">
                    <span class="et">${et}</span>
                    <span class="de">${de}</span>
                  </span>
                </label>
              </div>`,
              )
              .join('')}
          </div>
        </div>`;

    case 'email':
      return `
        <div class="tarjeta-paso">
          <h2>¿Dónde te mandamos el informe?</h2>
          <p class="ayuda-paso" id="ayuda-email">Opcional. Puedes dejarlo en blanco y descargarlo directamente.</p>
          <div class="campo">
            <input type="email" id="c-email" autocomplete="email" placeholder="tu@email.com"
                   aria-describedby="ayuda-email"
                   value="${escapar(estado.identidad.email || '')}">
          </div>
        </div>`;

    case 'muro':
      return plantillaMuro(paso);

    case 'pregunta':
      return `<div class="tarjeta-paso ${paso.desempate ? 'desempate' : ''}">${pregunta(paso)}</div>`;

    case 'final':
      return `
        <div class="tarjeta-paso portada-intro">
          <h1>Ya está.</h1>
          <p class="entradilla">
            Has contestado ${totalPreguntas()} preguntas. Ahora calculamos tu perfil,
            detectamos tus puntos ciegos y le pedimos a la IA tres direcciones
            concretas para tu marca.
          </p>
          <div id="zona-final"></div>
        </div>`;
  }
  return '';
}

/* ---- Paso 0: la puerta ---- */

const NOTA_DATOS_GOOGLE = `Qué guardamos: tus respuestas, tu nombre y, si entras con Google, tu email y tu foto de perfil. Para qué: para devolverte tu informe y para que puedas volver a él. No vendemos nada, no publicamos nada y no te vamos a mandar correos: hoy este programa no envía ni un email. Tus respuestas solo salen de aquí cuando pides las tres direcciones a la IA, y eso lo pides tú con un botón. Lo borras todo de un clic, cuando quieras.`;
const NOTA_DATOS_SIN_GOOGLE = `Qué guardamos: tus respuestas y tu nombre. Para qué: para devolverte tu informe y para que puedas volver a él. No vendemos nada, no publicamos nada y no te vamos a mandar correos: hoy este programa no envía ni un email. Tus respuestas solo salen de aquí cuando pides las tres direcciones a la IA, y eso lo pides tú con un botón. Lo borras todo de un clic, cuando quieras. Se guarda 30 días desde tu última visita.`;

function plantillaAcceso() {
  const n = totalPreguntas();
  if (hayGoogle()) {
    return `
      <div class="tarjeta-paso acceso">
        <h1>Antes de empezar: ¿dónde guardamos esto?</h1>
        <p class="entradilla">
          Son ${n} preguntas y unos 35 minutos. Se guarda solo, respuesta a
          respuesta, en cuanto la contestas. Lo que hay que decidir ahora es dónde.
        </p>
        <div class="acceso-botones">
          <div id="boton-google"></div>
          <p class="ayuda-paso">
            Con cuenta, tu cuestionario queda atado a ti: cierras el portátil, lo
            retomas en el móvil y sigues en la pregunta 87.
          </p>
          <button type="button" class="btn-secundario" id="btn-anonimo" style="width:100%">Continuar sin cuenta</button>
          <p class="ayuda-paso">
            Sin cuenta también se guarda en el servidor, pero atado a este
            navegador. Si borras los datos del navegador o pasas 30 días sin
            volver, se pierde. Puedes entrar con Google más tarde y lo tuyo se
            conserva: no vas a repetir nada.
          </p>
          <button type="button" class="btn-secundario" id="acceso-sin-servidor" hidden style="width:100%">
            Seguir sin guardar en el servidor
          </button>
        </div>
        <p class="aviso-campo" id="aviso-acceso" role="status" aria-live="polite"></p>
        <div class="nota">${escapar(NOTA_DATOS_GOOGLE)}</div>
        <a class="enlace-privacidad" href="/privacidad" target="_blank" rel="noopener">Qué guardamos exactamente</a>
      </div>`;
  }
  return `
    <div class="tarjeta-paso acceso">
      <h1>Antes de empezar.</h1>
      <p class="entradilla">
        Son ${n} preguntas y unos 35 minutos. Se guarda solo, respuesta a
        respuesta, en el servidor: puedes cerrar y volver desde este mismo navegador.
      </p>
      <div class="acceso-botones">
        <button type="button" class="btn-primario" id="btn-anonimo" style="width:100%">Empezar</button>
        <button type="button" class="btn-secundario" id="acceso-sin-servidor" hidden style="width:100%">
          Seguir sin guardar en el servidor
        </button>
      </div>
      <p class="aviso-campo" id="aviso-acceso" role="status" aria-live="polite"></p>
      <div class="nota">${escapar(NOTA_DATOS_SIN_GOOGLE)}</div>
      <a class="enlace-privacidad" href="/privacidad" target="_blank" rel="noopener">Qué guardamos exactamente</a>
    </div>`;
}

/* ---- Tarjetas de decisión ---- */

function fechaCorta(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString('es-ES', { day: 'numeric', month: 'long' });
}

function plantillaDecision(paso) {
  const d = paso.datos || {};
  if (paso.clave === 'conflicto') {
    const nServidor = Number(d.servidor?.contestadas) || 0;
    const cuando = fechaCorta(d.servidor?.actualizado_en);
    return `
      <div class="tarjeta-paso decision">
        <h1>Hay dos versiones de esto.</h1>
        <p class="entradilla">
          En este navegador tienes ${d.nLocal} respuestas. En tu cuenta hay
          ${nServidor}${cuando ? `, guardadas el ${escapar(cuando)}` : ''}. No voy
          a decidir yo: dime con cuál sigo. La otra no se borra.
        </p>
        <div class="decision-botones">
          <button type="button" class="btn-primario" id="dec-a">Seguir con las ${nServidor} de mi cuenta</button>
          <button type="button" class="btn-secundario" id="dec-b">Seguir con las ${d.nLocal} de este navegador</button>
        </div>
      </div>`;
  }
  if (paso.clave === 'fusion') {
    return `
      <div class="tarjeta-paso decision">
        <h1>Tenías dos cuestionarios a medias.</h1>
        <p class="entradilla">
          Uno con ${d.mayor} respuestas y otro con ${d.menor}. Sigo con el de
          ${d.mayor}, que es el que más trabajo tiene. El de ${d.menor} no se ha borrado.
        </p>
        <div class="decision-botones">
          <button type="button" class="btn-primario" id="dec-a">Seguir con el de ${d.mayor}</button>
          <button type="button" class="btn-secundario" id="dec-b">Usar el de ${d.menor}</button>
        </div>
      </div>`;
  }
  // Reanudación normal.
  const cuando = fechaCorta(d.actualizado_en);
  return `
    <div class="tarjeta-paso decision">
      <h1>Lo tenías a medias.</h1>
      <p class="entradilla">
        Llevas ${d.hechas} de ${d.total} respuestas${cuando ? ` y la última fue el ${escapar(cuando)}` : ''}.
        Sigo donde lo dejaste.
      </p>
      <div class="decision-botones">
        <button type="button" class="btn-primario" id="dec-a">Seguir donde lo dejé</button>
        <button type="button" class="btn-secundario" id="dec-b">Empezar de cero</button>
      </div>
    </div>`;
}

/* ---- El muro ---- */

function plantillaMuro(paso) {
  const textos = {
    tibieza: {
      h1: 'Estás siendo tibio.',
      entradilla: `De tus respuestas, <strong>${paso.tibias}</strong> se quedaron en el
        «a veces», el «depende» o el punto muerto del deslizador. Una marca así no se
        recuerda: no se ve. El punto medio no es equilibrio, es invisibilidad.`,
      nota: `Te devuelvo esas ${paso.tibias}. Ahora <strong>sin el centro</strong>:
        elige un lado. Es incómodo a propósito — de eso va tener una marca.`,
    },
    plano: {
      h1: 'No eres tibio: has puntuado casi igual los doce arquetipos.',
      entradilla: `Doce cincuentas no son una marca. Te devuelvo los
        <strong>${paso.cuantas}</strong> ítems donde tu respuesta empata con tu propia
        media, y los bloques de desempate que te falten.`,
      nota: 'Elige cuáles te definen de verdad y cuáles no.',
    },
    texto_pobre: {
      h1: 'Tus respuestas escritas no dicen nada tuyo.',
      entradilla: `${paso.cuantas} de tus respuestas escritas no dicen nada que no
        pudiera decir cualquiera de tu sector. Te las devuelvo con lo que escribiste
        a la vista.`,
      nota: 'Esto no lo puede rellenar el programa.',
    },
    // El servidor no manda cuántos controles se han fallado (validar_atencion no
    // viaja en el cuerpo de /api/tibieza), así que el texto no inventa un número.
    sin_validez: {
      h1: 'Esto no vale.',
      entradilla: `Has fallado las preguntas de control: las tres que dicen
        literalmente qué hay que marcar. No hay perfil que sacar de aquí.`,
      nota: 'Vamos a repetir el test entero: son ocho minutos y esta vez lee las frases.',
    },
  };
  const t = textos[paso.motivo] || textos.tibieza;
  return `
    <div class="tarjeta-paso muro">
      <div class="muro-icono" aria-hidden="true">⚠</div>
      <h1>${t.h1}</h1>
      <p class="entradilla">${t.entradilla}</p>
      <div class="nota">${t.nota}</div>
    </div>`;
}

/* ---- Preguntas ---- */

function pregunta(paso) {
  const p = paso.pregunta;
  const v = estado[paso.seccion][p.id];
  const idTitulo = `titulo-${p.id}`;
  const idAyuda = `ayuda-${p.id}`;
  const cabecera = `
    <h2 class="texto-pregunta" id="${idTitulo}">${escapar(p.texto)}</h2>
    ${p.ayuda ? `<p class="ayuda-paso" id="${idAyuda}">${escapar(p.ayuda)}</p>` : ''}
    ${paso.textoPrevio ? `<p class="texto-previo"><span class="rotulo">Esto es lo que escribiste. Escríbelo otra vez con algo que solo puedas decir tú.</span>${escapar(paso.textoPrevio)}</p>` : ''}`;
  const describe = p.ayuda ? ` aria-describedby="${idAyuda}"` : '';
  const grupo = ` role="group" aria-labelledby="${idTitulo}"${describe}`;

  if (p.tipo === 'likert5') {
    let etiquetas = (p.escala?.etiquetas) || [
      { valor: 1, texto: 'Nada' },
      { valor: 2, texto: 'Poco' },
      { valor: 3, texto: 'A veces' },
      { valor: 4, texto: 'Bastante' },
      { valor: 5, texto: 'Totalmente' },
    ];
    // En una ronda de desempate quitamos el punto medio: no vale esconderse.
    if (paso.sinCentro) etiquetas = etiquetas.filter((et) => Number(et.valor) !== 3);
    return `${cabecera}
      <div class="likert"${grupo}>
        ${etiquetas
          .map(
            (et) => `
          <input type="radio" name="${p.id}" id="${p.id}-${et.valor}" value="${et.valor}"
                 ${String(v) === String(et.valor) ? 'checked' : ''}>
          <label for="${p.id}-${et.valor}">
            <span class="n">${et.valor}</span>
            <span class="t">${escapar(et.texto_corto || et.texto)}</span>
          </label>`,
          )
          .join('')}
      </div>
      ${avisoHueco(p.id)}`;
  }

  const base = opcionesDe(paso);
  // A partir de siete opciones, una sola columna obliga a hacer scroll en cada
  // pregunta — justo lo que esta pantalla venía a evitar. Pasamos a dos columnas.
  const denso = base.length >= 7 ? 'densa' : '';

  if (p.tipo === 'unica') {
    // En desempate retiramos las salidas evasivas: hay que posicionarse.
    const opciones = paso.sinCentro ? base.filter((o) => !o.evasiva) : base;
    // Solo se anuncian teclas si TODAS las opciones caben en el 1-9: prometer
    // atajos que no existen en una pregunta de doce opciones es mentir.
    const conTeclas = opciones.length <= 9;
    return `${cabecera}
      <div class="opciones ${denso}"${grupo}>
        ${opciones
          .map(
            (o, n) => `
          <div class="opcion">
            <input type="radio" name="${p.id}" id="${p.id}-${n}" value="${escapar(o.valor)}"
                   ${String(v) === String(o.valor) ? 'checked' : ''}>
            <label for="${p.id}-${n}">
              ${conTeclas ? `<span class="tecla">${n + 1}</span>` : ''}
              <span class="cuerpo">
                <span class="et">${escapar(o.etiqueta)}</span>
                ${o.descripcion ? `<span class="de">${escapar(o.descripcion)}</span>` : ''}
              </span>
            </label>
          </div>`,
          )
          .join('')}
      </div>
      ${avisoHueco(p.id)}`;
  }

  if (p.tipo === 'multiple') {
    const sel = Array.isArray(v) ? v : [];
    const min = Number.isFinite(Number(p.min)) ? Number(p.min) : 1;
    const conTeclas = base.length <= 9;
    const limite = [
      min > 1 ? `Elige al menos ${min}.` : (min === 0 ? 'Puedes no marcar ninguna.' : 'Marca al menos una.'),
      p.max ? `Hasta ${p.max}.` : '',
    ].filter(Boolean).join(' ');
    return `${cabecera}
      <p class="limite">Puedes marcar varias. ${escapar(limite)}</p>
      <div class="opciones ${denso}"${grupo}>
        ${base
          .map(
            (o, n) => `
          <div class="opcion">
            <input type="checkbox" name="${p.id}" id="${p.id}-${n}" value="${escapar(o.valor)}"
                   ${sel.includes(o.valor) ? 'checked' : ''}>
            <label for="${p.id}-${n}">
              ${conTeclas ? `<span class="tecla">${n + 1}</span>` : ''}
              <span class="cuerpo">
                <span class="et">${escapar(o.etiqueta)}</span>
                ${o.descripcion ? `<span class="de">${escapar(o.descripcion)}</span>` : ''}
              </span>
            </label>
          </div>`,
          )
          .join('')}
      </div>
      ${avisoHueco(p.id)}`;
  }

  if (p.tipo === 'bipolar') {
    const max = Number(p.escala) || 7;
    const medio = Math.ceil(max / 2);
    const valores = Array.from({ length: max }, (_, n) => n + 1)
      .filter((n) => !paso.sinCentro || n !== medio);
    // Siempre botones, nunca deslizador. El deslizador se anotaba solo en el
    // punto medio sin que nadie lo tocara: nueve respuestas tibias fabricadas
    // por el propio programa, que es justo lo que el informe castiga luego.
    return `${cabecera}
      <div class="bipolar-desempate">
        <div class="polos">
          <div class="polo"><strong>${escapar(p.polo_izq)}</strong>
            ${p.desc_izq ? `<span>${escapar(p.desc_izq)}</span>` : ''}</div>
          <div class="polo der"><strong>${escapar(p.polo_der)}</strong>
            ${p.desc_der ? `<span>${escapar(p.desc_der)}</span>` : ''}</div>
        </div>
        <div class="escala-botones"${grupo}>
          ${valores
            .map(
              (n) => `
            <input type="radio" name="${p.id}" id="${p.id}-${n}" value="${n}"
                   ${String(v) === String(n) ? 'checked' : ''}>
            <label for="${p.id}-${n}" class="${n < medio ? 'izq' : (n > medio ? 'der' : '')}">${n}</label>`,
            )
            .join('')}
        </div>
      </div>
      ${avisoHueco(p.id)}`;
  }

  if (p.tipo === 'ranking') {
    return `${cabecera}
      <div class="ranking" id="ranking-${p.id}"${grupo}>${cuerpoRanking(paso)}</div>
      ${avisoHueco(p.id)}`;
  }

  if (p.tipo === 'reparto100') {
    return `${cabecera}
      <div class="reparto" id="reparto-${p.id}"${grupo}>${cuerpoReparto(paso)}</div>
      ${avisoHueco(p.id)}`;
  }

  if (p.tipo === 'duelo') {
    return `${cabecera}${cuerpoDuelo(paso)}${avisoHueco(p.id)}`;
  }

  if (p.tipo === 'texto_largo' || p.tipo === 'texto') {
    const tope = Number(p.max_chars) || (p.tipo === 'texto_largo' ? 500 : 220);
    const texto = String(v || '');
    const largo = p.tipo === 'texto_largo';
    const campo = largo
      ? `<textarea name="${p.id}" maxlength="${tope}"${describe}
                   placeholder="${escapar(p.placeholder || '')}">${escapar(texto)}</textarea>`
      : `<input type="text" name="${p.id}" maxlength="${tope}"${describe}
                placeholder="${escapar(p.placeholder || '')}" value="${escapar(texto)}">`;
    return `${cabecera}
      <div class="campo">
        ${campo}
        <div class="contador-chars" id="cuenta-${p.id}"></div>
      </div>
      ${(p.atajos || []).length ? `
      <div class="atajos" id="atajos-${p.id}">
        ${p.atajos.map((a, n) => `<button type="button" class="atajo" data-n="${n}">${escapar(a.etiqueta || a.valor)}</button>`).join('')}
      </div>` : ''}
      ${avisoHueco(p.id)}`;
  }

  return `${cabecera}
    <div class="campo">
      <input type="text" name="${p.id}"${describe} placeholder="${escapar(p.placeholder || '')}"
             value="${escapar(v || '')}">
      <div class="contador-chars" id="cuenta-${p.id}"></div>
    </div>
    ${avisoHueco(p.id)}`;
}

const avisoHueco = (id) => `<p class="aviso-campo" id="aviso-${id}" role="status" aria-live="polite"></p>`;

/* ---- ranking ---- */

function cuerpoRanking(paso) {
  const p = paso.pregunta;
  const v = estado[paso.seccion][p.id];
  const validos = new Set(p.opciones.map((o) => String(o.valor)));
  const sel = (Array.isArray(v) ? v : []).filter((x) => validos.has(String(x)));
  const n = Number(p.exactamente) || 3;
  const resto = p.opciones.filter((o) => !sel.includes(o.valor));

  const boton = (o, puesto) => `
    <button type="button" class="ranking-op" data-valor="${escapar(o.valor)}"
            aria-pressed="${puesto ? 'true' : 'false'}">
      ${puesto ? `<span class="puesto" aria-hidden="true">${puesto}</span>` : ''}
      <span class="cuerpo">
        <span class="et">${escapar(o.etiqueta)}</span>
        ${o.descripcion ? `<span class="de">${escapar(o.descripcion)}</span>` : ''}
      </span>
    </button>`;

  const elegidos = sel.map((valor, k) => {
    const o = p.opciones.find((x) => String(x.valor) === String(valor));
    return boton(o, k + 1);
  });
  for (let k = sel.length; k < n; k += 1) {
    elegidos.push(`<div class="ranking-hueco">${k + 1}. —</div>`);
  }

  return `
    <div class="ranking-elegidos">
      <p class="ranking-rotulo">Tus ${n}, en orden</p>
      <div class="ranking-lista">${elegidos.join('')}</div>
    </div>
    <div class="ranking-pool">
      <p class="ranking-rotulo">${escapar(p.rotulo_descartes || 'Renuncias a:')}</p>
      <div class="ranking-lista">${resto.map((o) => boton(o, 0)).join('')}</div>
    </div>`;
}

/* ---- reparto100 ---- */

function repartoDe(paso) {
  const v = estado[paso.seccion][paso.pregunta.id];
  const rep = {};
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    paso.pregunta.opciones.forEach((o) => {
      const n = Number(v[o.valor]) || 0;
      if (n > 0) rep[o.valor] = n;
    });
  }
  return rep;
}

function cuerpoReparto(paso) {
  const p = paso.pregunta;
  const rep = repartoDe(paso);
  const objetivo = Number(p.suma) || 100;
  const suma = Object.values(rep).reduce((a, b) => a + b, 0);
  const quedan = objetivo - suma;

  return `
    <p class="reparto-marcador" aria-live="polite">
      ${quedan >= 0 ? `Te quedan <span class="n">${quedan}</span> puntos` : `Te has pasado en <span class="n">${-quedan}</span>`}
    </p>
    ${p.opciones.map((o) => {
      const puntos = rep[o.valor] || 0;
      return `
      <div class="reparto-fila ${puntos > 0 ? 'con-puntos' : ''}" data-valor="${escapar(o.valor)}">
        <span class="cuerpo">
          <span class="et">${escapar(o.etiqueta)}</span>
          ${o.descripcion ? `<span class="de">${escapar(o.descripcion)}</span>` : ''}
        </span>
        <span class="reparto-mando">
          <button type="button" data-delta="-1" aria-label="Quitar ${Number(p.paso) || 5} a ${escapar(o.etiqueta)}">−</button>
          <span class="puntos" role="status" aria-label="${escapar(o.etiqueta)}: ${puntos} puntos">${puntos}</span>
          <button type="button" data-delta="1" aria-label="Dar ${Number(p.paso) || 5} a ${escapar(o.etiqueta)}">+</button>
        </span>
      </div>`;
    }).join('')}`;
}

/* ---- duelo ---- */

function cuerpoDuelo(paso) {
  const p = paso.pregunta;
  const v = estado[paso.seccion][p.id];
  const actual = (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};
  const idx = referentesIndice();
  const campos = p.campos_ficha || ['titular', 'estilo_visual', 'prendas_firma'];
  const nc = p.no_copio || {};
  const tope = Number(nc.max_chars) || 120;

  const tarjetas = (p.referentes || []).map((id, n) => {
    const r = idx[id];
    if (!r) return '';
    const img = r.imagen || {};
    const prendas = campos.includes('prendas_firma') ? (r.prendas_firma || []).slice(0, 3) : [];
    return `
      <div>
        <input type="radio" name="${p.id}-duelo" id="${p.id}-d${n}" value="${escapar(id)}"
               ${String(actual.elegido) === String(id) ? 'checked' : ''}>
        <label class="duelo-tarjeta" for="${p.id}-d${n}">
          ${img.local ? `<img src="/static/${escapar(img.local)}" alt="${escapar(r.nombre)}" loading="lazy">` : ''}
          <div class="nombre">${escapar(r.nombre)}</div>
          ${campos.includes('titular') && r.titular ? `<div class="titular">${escapar(r.titular)}</div>` : ''}
          ${campos.includes('estilo_visual') && r.estilo_visual ? `<div class="estilo">${escapar(r.estilo_visual)}</div>` : ''}
          ${prendas.length ? `<ul class="prendas">${prendas.map((x) => `<li>· ${escapar(x)}</li>`).join('')}</ul>` : ''}
          ${img.atribucion ? `<div class="atribucion">${escapar(img.atribucion)}</div>` : ''}
        </label>
      </div>`;
  }).join('');

  return `
    <div class="duelo">${tarjetas}</div>
    <div class="campo">
      <label for="${p.id}-nocopio">${escapar(nc.etiqueta || 'Lo que NO le copiaría:')}</label>
      <input type="text" id="${p.id}-nocopio" name="${p.id}-nocopio" maxlength="${tope}"
             placeholder="${escapar(nc.placeholder || '')}" value="${escapar(actual.no_copio || '')}">
      <div class="contador-chars" id="cuenta-${p.id}"></div>
    </div>`;
}

/* ================= Progreso y pie ================= */

function actualizarProgreso() {
  const paso = pasoActual();
  const total = totalPreguntas();
  const hechas = preguntasHasta(i);
  const pct = paso.tipo === 'final' ? 100 : (total ? (hechas / total) * 100 : 0);

  $('barra').style.width = `${pct}%`;
  $('etiqueta-seccion').textContent =
    (paso.tipo === 'intro' || paso.tipo === 'acceso' || paso.tipo === 'decision')
      ? '' : NOMBRES_SECCION[paso.seccion] || '';
  $('contador').textContent =
    paso.tipo === 'pregunta' ? `${hechas} de ${total}` :
    paso.tipo === 'final' ? '¡Completo!' : '';
}

function actualizarPie(paso) {
  const pie = $('pie');
  const atras = $('btn-atras');
  const sig = $('btn-siguiente');
  const pista = $('pista-teclado');

  const sinPie = paso.tipo === 'final' || paso.tipo === 'acceso' || paso.tipo === 'decision';
  pie.hidden = sinPie;

  // El desempate va hacia adelante: no se puede retroceder para esquivarlo.
  const enDesempate = paso.tipo === 'muro' || paso.desempate;
  atras.style.visibility = i === 0 || enDesempate ? 'hidden' : 'visible';

  sig.textContent =
    paso.tipo === 'intro' ? 'Empezar' :
    paso.tipo === 'muro' ? 'Defínete →' :
    paso.tipo === 'seccion' ? 'Vamos' :
    i === PASOS.length - 2 ? 'Terminar' : 'Continuar';

  let bloqueado = paso.tipo === 'pregunta' && !contestado(paso);
  // Un desempate atravesado a golpe de Enter en medio segundo no es una
  // decisión: se pide un mínimo de permanencia en la pantalla.
  if (paso.sinCentro && paso.desde && Date.now() - paso.desde < ESPERA_MURO) {
    bloqueado = true;
    setTimeout(() => { if (pasoActual() === paso) actualizarPie(paso); }, ESPERA_MURO);
  }
  sig.disabled = bloqueado;
  sig.setAttribute('aria-disabled', bloqueado ? 'true' : 'false');

  const p = paso.pregunta;
  const nOpciones = p ? opcionesDe(paso).length : 0;
  pista.textContent =
    paso.sinCentro ? 'Aquí hay que elegir con el ratón o con la barra espaciadora' :
    p?.tipo === 'likert5' ? 'Pulsa 1-5, o haz clic' :
    p?.tipo === 'unica' ? (nOpciones <= 9 ? 'Pulsa el número, o haz clic' : 'Haz clic, o muévete con Tab y las flechas') :
    p?.tipo === 'multiple' ? (nOpciones <= 9 ? 'Marca varias con los números y pulsa Continuar' : 'Marca varias y pulsa Continuar') :
    p?.tipo === 'ranking' ? 'Pulsa tres, en orden' :
    p?.tipo === 'reparto100' ? 'Reparte con + y −' :
    p?.tipo === 'texto_largo' ? 'Enter hace un salto de línea; Ctrl+Enter continúa' :
    paso.tipo === 'intro' || paso.tipo === 'seccion' ? 'Pulsa Enter' : '';
}

function mostrarAviso(paso) {
  const p = paso.pregunta;
  if (!p) return;
  const el = $(`aviso-${p.id}`);
  if (!el) return;
  // Una opcional no reclama nada: fuera del muro, se puede dejar a medias.
  if (p.opcional && !paso.sinCentro && !paso.rehacer) { el.textContent = ''; return; }
  if (paso.sinCentro && !vacio(valorDe(paso)) && mismaRespuesta(valorDe(paso), paso.valorPrevio)) {
    el.textContent = 'Esa es exactamente la que diste antes. Aquí toca mojarse.';
    return;
  }
  if (paso.sinCentro && !vacio(valorDe(paso)) && esTibio(paso, valorDe(paso))) {
    el.textContent = 'Eso sigue siendo el centro. Elige un lado.';
    return;
  }
  el.textContent = vacio(valorDe(paso)) ? '' : (problema(paso) || '');
}

function contadorTexto(p, valor, min) {
  const el = $(`cuenta-${p.id}`);
  if (!el) return;
  const tope = Number(p.max_chars) || Number(p.no_copio?.max_chars) || 0;
  const n = String(valor || '').trim().length;
  el.textContent = tope ? `${n}/${tope}` : `${n}`;
  el.classList.toggle('corto', Boolean(min) && n < min);
}

/* ================= Interacción ================= */

function anotar(paso, valor) {
  if (paso.tipo === 'pregunta') estado[paso.seccion][paso.pregunta.id] = valor;
  guardar();
  actualizarPie(paso);
  mostrarAviso(paso);
}

/* Las flechas movían el foco Y marcaban la opción: el navegador contestaba por
   el usuario y el avance automático se lo llevaba a la siguiente pregunta. Aquí
   las flechas solo mueven el foco; para elegir hay que pulsar espacio o hacer
   clic. */
function flechasSoloMueven(contenedor) {
  const radios = () => [...contenedor.querySelectorAll('input[type="radio"]')];
  contenedor.addEventListener('keydown', (ev) => {
    const dir = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ev.key];
    if (!dir) return;
    const lista = radios();
    const n = lista.indexOf(document.activeElement);
    if (n < 0) return;
    ev.preventDefault();
    const destino = lista[(n + dir + lista.length) % lista.length];
    destino.focus();
  });
}

function enlazar(paso) {
  const e = escena();

  if (paso.tipo === 'acceso') {
    pintarBotonGoogle();
    $('btn-anonimo')?.addEventListener('click', () => tramitarAcceso('/api/auth/anonimo', {}));
    $('acceso-sin-servidor')?.addEventListener('click', seguirSinServidor);
    return;
  }

  if (paso.tipo === 'decision') {
    $('dec-a')?.addEventListener('click', () => resolverDecision(paso, 'a'));
    $('dec-b')?.addEventListener('click', () => resolverDecision(paso, 'b'));
    return;
  }

  // Campos de identidad.
  const identidad = {
    'c-nombre': 'nombre',
    'c-apellidos': 'apellidos',
    'c-artistico': 'artistico',
    'c-email': 'email',
  };
  Object.entries(identidad).forEach(([id, clave]) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener('input', () => {
      estado.identidad[clave] = el.value;
      guardar();
      actualizarPie(paso);
      if (clave === 'nombre' || clave === 'apellidos') pintarSugerencias();
    });
  });
  if (paso.tipo === 'artistico') pintarSugerencias();

  e.querySelectorAll('input[name="tipo_marca"]').forEach((r) =>
    r.addEventListener('change', () => {
      estado.identidad.tipo_marca = r.value;
      guardar();
      avanzarPronto();
    }),
  );

  if (paso.tipo !== 'pregunta') {
    if (paso.tipo === 'final') lanzar();
    return;
  }

  const p = paso.pregunta;

  if (p.tipo === 'likert5' || p.tipo === 'unica' || p.tipo === 'bipolar') {
    const cont = e.querySelector('.likert, .opciones, .escala-botones');
    if (cont) flechasSoloMueven(cont);
    e.querySelectorAll('input[type="radio"]').forEach((r) =>
      r.addEventListener('change', () => {
        anotar(paso, isNaN(Number(r.value)) ? r.value : Number(r.value));
        if (contestado(paso)) avanzarPronto();
      }),
    );
  } else if (p.tipo === 'multiple') {
    e.querySelectorAll('input[type="checkbox"]').forEach((c) =>
      c.addEventListener('change', () => {
        const marcados = [...e.querySelectorAll('input[type="checkbox"]:checked')];
        if (p.max && marcados.length > p.max) {
          // Desmarcar en silencio parecía un fallo del navegador: se avisa.
          c.checked = false;
          sacudir();
          const el = $(`aviso-${p.id}`);
          if (el) el.textContent = `Ya tienes ${p.max}; desmarca una para cambiar.`;
          return;
        }
        anotar(paso, marcados.map((x) => x.value));
      }),
    );
  } else if (p.tipo === 'ranking') {
    enlazarRanking(paso);
  } else if (p.tipo === 'reparto100') {
    enlazarReparto(paso);
  } else if (p.tipo === 'duelo') {
    enlazarDuelo(paso);
  } else {
    const c = e.querySelector('input[type="text"], textarea');
    if (!c) return;
    const min = minCaracteres(p.id, p.min_chars);
    contadorTexto(p, c.value, min);
    c.addEventListener('input', () => {
      // Escribir a mano invalida el atajo: el texto vuelve a ser suyo.
      if (usoAtajo(p.id)) delete estado.identidad[`_atajo_${p.id}`];
      anotar(paso, c.value);
      contadorTexto(p, c.value, min);
    });
    const atajos = $(`atajos-${p.id}`);
    if (atajos) {
      atajos.querySelectorAll('.atajo').forEach((b) =>
        b.addEventListener('click', () => {
          const a = p.atajos[Number(b.dataset.n)];
          c.value = a.valor;
          // El atajo es una respuesta válida por decisión de producto: con saber
          // en qué moneda pagó ya hay bastante, y el mínimo no se le aplica.
          estado.identidad[`_atajo_${p.id}`] = true;
          anotar(paso, a.valor);
          contadorTexto(p, c.value, 0);
        }),
      );
    }
  }
}

function enlazarRanking(paso) {
  const p = paso.pregunta;
  const cont = $(`ranking-${p.id}`);
  if (!cont) return;
  cont.querySelectorAll('.ranking-op').forEach((b) =>
    b.addEventListener('click', () => {
      const valor = b.dataset.valor;
      const opcion = p.opciones.find((o) => String(o.valor) === String(valor));
      if (!opcion) return;
      const v = estado[paso.seccion][p.id];
      const sel = Array.isArray(v) ? [...v] : [];
      const n = sel.indexOf(opcion.valor);
      if (n >= 0) {
        sel.splice(n, 1); // volver a pulsar la saca y renumera
      } else if (sel.length >= (Number(p.exactamente) || 3)) {
        sacudir();
        const el = $(`aviso-${p.id}`);
        if (el) el.textContent = `Ya tienes ${p.exactamente}; quita una para cambiar.`;
        return;
      } else {
        sel.push(opcion.valor);
      }
      anotar(paso, sel);
      cont.innerHTML = cuerpoRanking(paso);
      enlazarRanking(paso);
    }),
  );
}

function enlazarReparto(paso) {
  const p = paso.pregunta;
  const cont = $(`reparto-${p.id}`);
  if (!cont) return;
  const salto = Number(p.paso) || 5;
  const objetivo = Number(p.suma) || 100;

  cont.querySelectorAll('.reparto-mando button').forEach((b) =>
    b.addEventListener('click', () => {
      const fila = b.closest('.reparto-fila');
      const valor = fila.dataset.valor;
      const rep = repartoDe(paso);
      const suma = Object.values(rep).reduce((a, x) => a + x, 0);
      const delta = Number(b.dataset.delta) * salto;
      const actual = rep[valor] || 0;
      const nuevo = actual + delta;

      if (nuevo < 0) return;
      if (delta > 0 && suma + delta > objetivo) {
        // No se puede pasar de 100: la fila se sacude y se dice por qué.
        fila.classList.remove('sacude');
        void fila.offsetWidth;
        fila.classList.add('sacude');
        const el = $(`aviso-${p.id}`);
        if (el) el.textContent = `Solo te quedan ${objetivo - suma}. Quítalos de otra antes.`;
        return;
      }
      if (nuevo > 0) rep[valor] = nuevo; else delete rep[valor];
      anotar(paso, rep);
      cont.innerHTML = cuerpoReparto(paso);
      enlazarReparto(paso);
    }),
  );
}

function enlazarDuelo(paso) {
  const p = paso.pregunta;
  const e = escena();
  const cont = e.querySelector('.duelo');
  if (cont) flechasSoloMueven(cont);
  const campo = $(`${p.id}-nocopio`);
  const min = minCaracteres(`${p.id}.no_copio`, p.no_copio?.min_chars);
  const leer = () => {
    const v = estado[paso.seccion][p.id];
    return (v && typeof v === 'object' && !Array.isArray(v)) ? { ...v } : {};
  };

  e.querySelectorAll(`input[name="${p.id}-duelo"]`).forEach((r) =>
    r.addEventListener('change', () => {
      const d = leer();
      d.elegido = r.value;
      anotar(paso, d);
    }),
  );

  if (campo) {
    contadorTexto(p, campo.value, min);
    campo.addEventListener('input', () => {
      const d = leer();
      d.no_copio = campo.value;
      anotar(paso, d);
      contadorTexto(p, campo.value, min);
    });
  }
}

let temporizador = null;
function avanzarPronto() {
  const paso = pasoActual();
  // En un desempate se respeta el tiempo mínimo de permanencia: si no, el
  // avance automático se lo saltaría por la puerta de atrás.
  let retardo = RETARDO_AVANCE;
  if (paso?.sinCentro && paso.desde) {
    retardo = Math.max(retardo, ESPERA_MURO - (Date.now() - paso.desde) + 60);
  }
  clearTimeout(temporizador);
  temporizador = setTimeout(siguiente, retardo);
}

function siguiente() {
  const paso = pasoActual();
  if (paso.tipo === 'acceso' || paso.tipo === 'decision') return; // hay que elegir
  if (paso.tipo === 'pregunta' && !contestado(paso)) {
    sacudir();
    mostrarAviso(paso);
    return;
  }
  if (paso.sinCentro && paso.desde && Date.now() - paso.desde < ESPERA_MURO) {
    sacudir();
    return;
  }
  if (i < PASOS.length - 1) {
    i += 1;
    guardar();
    // Los interludios de sección son los cinco puntos de control naturales del
    // cuestionario: subida forzada, sin esperar al antirrebote.
    if (PASOS[i]?.tipo === 'seccion') subirBorrador({ forzar: true });
    pintar();
  }
}

function atras() {
  clearTimeout(temporizador);
  const paso = pasoActual();
  if (paso.tipo === 'muro' || paso.desempate || paso.tipo === 'decision') return;
  if (i > 0) {
    i -= 1;
    guardar();
    pintar();
  }
}

function sacudir() {
  const t = escena().querySelector('.tarjeta-paso');
  if (!t) return;
  t.classList.remove('sacude');
  void t.offsetWidth; // reinicia la animación
  t.classList.add('sacude');
}

/* ================= Decisiones ================= */

async function resolverDecision(paso, cual) {
  const clave = paso.clave;
  DECISION = null;
  if (clave === 'conflicto') {
    if (cual === 'a') return adoptarServidor();
    VERSION_BORRADOR = paso.datos?.servidor?.version ?? null;
    await subirBorrador({ forzar: true });
  } else if (clave === 'fusion') {
    if (cual === 'b') {
      try {
        const r = await fetch('/api/borrador/recuperar', { method: 'POST', credentials: 'same-origin' });
        if (r.ok) {
          const d = await r.json();
          SECCIONES.forEach((sec) => { estado[sec] = {}; });
          Object.assign(estado, d.respuestas || {});
          ronda = Math.max(ronda, Number(d.ronda) || 0);
          VERSION_BORRADOR = d.version ?? null;
        }
      } catch { /* si no se puede recuperar, se sigue con el que ya está */ }
    }
  } else if (clave === 'reanudar' && cual === 'b') {
    try {
      await fetch('/api/borrador/descartar', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motivo: 'reinicio' }),
      });
    } catch { /* archivar es del servidor; si falla, se empieza igual */ }
    SECCIONES.forEach((sec) => { estado[sec] = {}; });
    ronda = 0;
    VERSION_BORRADOR = null;
    CLAVE_IDEM = nuevaClave();
  }
  i = posicionInicial();
  guardar();
  pintar();
}

/* ================= Sugerencias de nombre ================= */

/* Estas dos tablas viven en contenido/nombres.json, pero /api/contenido no lo
   sirve y main.py es de otro dueño en esta tanda. Se copian aquí y se prefiere
   siempre lo que mande el servidor si algún día lo expone. */
const NOMBRES_LOCAL = {
  apellidos_comunes: [
    'garcia', 'rodriguez', 'gonzalez', 'fernandez', 'lopez',
    'martinez', 'sanchez', 'perez', 'gomez', 'martin',
    'jimenez', 'ruiz', 'hernandez', 'diaz', 'moreno',
    'muñoz', 'alvarez', 'romero', 'alonso', 'gutierrez',
    'navarro', 'torres', 'dominguez', 'vazquez', 'ramos',
    'gil', 'ramirez', 'serrano', 'blanco', 'molina',
    'morales', 'suarez', 'ortega', 'delgado', 'castro',
    'ortiz', 'rubio', 'marin', 'sanz', 'nuñez',
    'iglesias', 'medina', 'garrido', 'cortes', 'castillo',
    'santos', 'lozano', 'guerrero', 'cano', 'prieto',
  ],
  territorios: {
    tecnica: 'Oficio', oficio: 'Oficio', critica: 'Crítica', datos: 'Datos',
    personas: 'Personas', innovacion: 'Frontera', liderazgo: 'Mando',
    negocio: 'Cuenta', cultura: 'Cultura', humor: 'Guasa',
  },
};

const SELLOS = {
  gafas: (n) => `Las gafas de ${n}`,
  gafas_sol: (n) => `Las gafas de sol de ${n}`,
  sombrero: (n) => `El sombrero de ${n}`,
  joya: (n) => `La joya de ${n}`,
  calzado: (n) => `Los zapatos de ${n}`,
  prenda: (n) => `El uniforme de ${n}`,
};

const COLORES = {
  rojo: 'en rojo', azul: 'en azul', verde: 'en verde',
  amarillo: 'en amarillo', naranja: 'en naranja', morado: 'en morado',
  rosa: 'en rosa', negro_blanco: 'en blanco y negro',
};

const FORMATOS = {
  post_semanal: (n) => `El semanal de ${n}`,
  newsletter: (n) => `El boletín de ${n}`,
  video_semanal: (n) => `El vídeo de ${n}`,
  podcast_ancla: (n) => `El podcast de ${n}`,
  directo_ancla: (n) => `El directo de ${n}`,
  informe: (n) => `El informe de ${n}`,
};

const RITUALES = {
  formato_fijo: (n) => `Los martes de ${n}`,
  seccion: (n) => `La sección de ${n}`,
};

function tablaNombres() {
  const del_servidor = CONTENIDO?.nombres;
  return {
    apellidos_comunes: del_servidor?.apellidos_comunes || NOMBRES_LOCAL.apellidos_comunes,
    territorios: del_servidor?.territorios || NOMBRES_LOCAL.territorios,
  };
}

function silabas(texto) {
  return (normalizar(texto).match(/[aeiou]+/g) || []).length;
}

const tieneTildeONe = (texto) => /[áéíóúüñ]/i.test(String(texto));

function nombresDeReferentes() {
  const crudo = CONTENIDO?.referentes;
  const lista = Array.isArray(crudo) ? crudo : (crudo?.referentes || []);
  return new Set(lista.map((r) => normalizar(r?.nombre)));
}

/* Cinco fábricas con material del cuestionario, no siete permutaciones del
   nombre legal. Ahora sí se puede: el paso vive al final y el arquetipo, el
   territorio, el sello, el color y el formato ya están contestados. */
function sugerirNombres() {
  const nombre = String(estado.identidad.nombre || '').trim();
  if (!nombre) return [];
  const apellidos = String(estado.identidad.apellidos || '').trim().split(/\s+/).filter(Boolean);
  const [ap1 = '', ap2 = ''] = apellidos;
  const tabla = tablaNombres();
  const comunes = new Set(tabla.apellidos_comunes.map(normalizar));
  const referentes = nombresDeReferentes();
  const com = estado.comunicacion || {};
  const vis = estado.visual || {};
  const acc = estado.acciones || {};

  const ideas = [];
  const mete = (texto, fabrica) => {
    const limpio = String(texto || '').trim().replace(/\s+/g, ' ');
    if (!limpio || limpio === String(estado.identidad.artistico || '').trim()) return;
    if (ideas.some((x) => normalizar(x.nombre) === normalizar(limpio))) return;
    ideas.push({ nombre: limpio, fabrica });
  };

  // F1 TERRITORIO: el primero de COM-NA-3, que es el que va a repetir hasta hartarse.
  const territorio = Array.isArray(com['COM-NA-3']) ? com['COM-NA-3'][0] : null;
  if (territorio && tabla.territorios[territorio]) {
    mete(`${nombre} · ${tabla.territorios[territorio]}`, 'territorio');
  }

  // F2 SELLO O COLOR.
  const sellos = Array.isArray(vis['VIS-RO-5']) ? vis['VIS-RO-5'] : [];
  const sello = sellos.find((s) => SELLOS[s]);
  if (sello) mete(SELLOS[sello](nombre), 'sello');
  // El color va aunque haya sello: son las dos mitades de la misma fábrica y la
  // lista sale corta si solo se ofrece una.
  const color = vis['VIS-CR-3'];
  if (COLORES[color]) mete(`${nombre} ${COLORES[color]}`, 'color');

  // F3 FORMATO: la cita fija de ACC-CT-2, o el ritual de ACC-RI-1.
  const formato = acc['ACC-CT-2'];
  if (FORMATOS[formato]) mete(FORMATOS[formato](nombre), 'formato');
  const rituales = Array.isArray(acc['ACC-RI-1']) ? acc['ACC-RI-1'] : [];
  const ritual = rituales.find((r) => RITUALES[r]);
  if (ritual) mete(RITUALES[ritual](nombre), 'ritual');

  // F4 APELLIDO MENOS COMÚN.
  const raros = [ap1, ap2].filter((a) => a && !comunes.has(normalizar(a)));
  if (raros.length) mete(`${nombre} ${raros[0]}`, 'apellido');
  else if (ap1) mete(`${nombre} ${ap1}`, 'apellido');

  // F5 INICIALES, solo si forman sílaba pronunciable en español.
  const iniciales = [nombre, ap1, ap2].filter(Boolean).map((x) => x[0]).join('');
  const silaba = normalizar(iniciales);
  if (/^[bcdfghjklmnpqrstvwxyz][aeiou][bcdfghjklmnprstz]?$/.test(silaba)) {
    mete(silaba.charAt(0).toUpperCase() + silaba.slice(1), 'iniciales');
  }

  // Estudio {apellido} solo si NO es marca personal: ahora sí sabemos el tipo.
  if (ap1 && estado.identidad.tipo_marca && estado.identidad.tipo_marca !== 'personal') {
    mete(`Estudio ${ap1}`, 'estudio');
  }

  ideas.forEach((idea) => {
    const s = silabas(idea.nombre);
    const palabras = idea.nombre.split(/\s+/).filter(Boolean);
    const ultima = normalizar(palabras[palabras.length - 1]);
    const avisos = [];
    let puntos = 0;

    if (s <= 5) puntos += 2;
    else avisos.push(`${s} sílabas: nadie lo va a repetir bien por teléfono.`);

    if (!tieneTildeONe(idea.nombre)) puntos += 1;
    else avisos.push('La ñ y las tildes te van a costar en dominios y buscadores.');

    if (!comunes.has(ultima)) puntos += 2;
    else avisos.push(`${palabras[palabras.length - 1]} está entre los 50 apellidos más comunes de España: te van a confundir.`);

    if (palabras.length === 1) puntos += 1;

    if (!referentes.has(normalizar(idea.nombre))) puntos += 1;
    else avisos.push('Ese nombre ya es de un referente conocido: no vas a ganar esa batalla en Google.');

    idea.puntos = puntos;
    idea.avisos = avisos;
  });

  ideas.sort((a, b) => b.puntos - a.puntos);
  return ideas.slice(0, 6);
}

function pintarSugerencias() {
  const cont = $('sugerencias');
  if (!cont) return;
  const ideas = sugerirNombres();
  cont.innerHTML = ideas
    .map((idea, n) => `
      <div class="sugerencia-caja">
        <button type="button" class="sugerencia" data-n="${n}">${escapar(idea.nombre)}</button>
        ${idea.avisos.length ? `<p class="sugerencia-aviso">${escapar(idea.avisos[0])}</p>` : ''}
      </div>`)
    .join('');
  cont.querySelectorAll('.sugerencia').forEach((b) =>
    b.addEventListener('click', () => {
      const idea = ideas[Number(b.dataset.n)];
      $('c-artistico').value = idea.nombre;
      estado.identidad.artistico = idea.nombre;
      guardar();
      pintarSugerencias();
    }),
  );
}

/* ================= Teclado ================= */

function teclado(ev) {
  const paso = pasoActual();
  if (!paso) return;
  const el = ev.target;
  const etiqueta = el?.tagName || '';
  const enCampo = etiqueta === 'TEXTAREA' ||
    (etiqueta === 'INPUT' && ['text', 'email', 'search', 'number', 'url', 'tel'].includes(el.type));

  if (ev.key === 'Enter') {
    // Entrar en una cuenta o renunciar a ella no se hace por inercia, y un
    // desempate atravesado con el dedo en Enter no es una decisión.
    if (paso.tipo === 'acceso' || paso.tipo === 'decision' || paso.sinCentro) return;
    // Que el botón o el enlace hagan lo suyo.
    if (etiqueta === 'BUTTON' || etiqueta === 'A') return;
    // En un textarea, Enter escribe: es donde el usuario suelta su personalidad
    // y hasta hoy no se podía hacer un salto de línea en ninguna de las 19
    // respuestas largas obligatorias. Ctrl/Cmd+Enter avanza.
    if (etiqueta === 'TEXTAREA' && !(ev.ctrlKey || ev.metaKey)) return;
    ev.preventDefault();
    siguiente();
    return;
  }

  if (enCampo) return; // en un campo de texto, los números se escriben

  if (/^[1-9]$/.test(ev.key)) {
    const n = Number(ev.key);
    const e = escena();
    const opciones = [...e.querySelectorAll('.likert input, .opciones input')];
    if (opciones.length > 9) return; // no se anuncian atajos que no existen
    const objetivo = opciones[n - 1];
    if (objetivo) {
      ev.preventDefault();
      objetivo.checked = objetivo.type === 'checkbox' ? !objetivo.checked : true;
      objetivo.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }
}

/* ================= Envío ================= */

function cargando(texto) {
  return `<div class="cargando"><div class="pulso"></div>
    <p id="estado-final">${escapar(texto)}</p></div>`;
}

function estadoFinal(texto) {
  const el = $('estado-final');
  if (el) el.textContent = texto;
}

/* Puerta de tibieza. Ya no es una cortesía que se salta sola: si /api/tibieza no
   contesta, se reintenta y, si sigue sin contestar, se PARA. Dejar pasar un
   fallo de red significaba emitir el informe tibio, que es exactamente lo que
   esta pantalla existe para impedir. */
async function lanzar() {
  const zona = $('zona-final');
  if (!zona) return;
  if (informeEmitido) { pintarEnlaceInforme(informeEmitido); return; }
  if (enviando) return;
  enviando = true;
  zona.innerHTML = cargando('Comprobando si te has definido…');

  await subirBorrador({ forzar: true });

  for (let intento = 0; intento <= ESPERAS_PUERTA.length; intento += 1) {
    try {
      const r = await fetch('/api/tibieza', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ respuestas: estado, ronda }),
      });
      if (!r.ok) throw new Error(String(r.status));
      const d = await r.json();
      if (d.veredicto?.repetir) { enviando = false; insertarDesempate(d); return; }
      enviando = false;
      return enviar();
    } catch {
      if (intento === ESPERAS_PUERTA.length) {
        enviando = false;
        zona.innerHTML = `
          <div class="nota" style="border-left-color:var(--marca)">
            La comprobación previa no contesta y no voy a emitir el informe a ciegas:
            justo ahí es donde se cuela el informe tibio. Revisa tu conexión y dale otra vez.
          </div>
          <button class="btn-primario" id="btn-reintentar-puerta">Reintentar</button>`;
        $('btn-reintentar-puerta')?.addEventListener('click', () => lanzar());
        return;
      }
      estadoFinal(`Sin respuesta. Reintento en ${Math.round(ESPERAS_PUERTA[intento] / 1000)} s…`);
      await dormir(ESPERAS_PUERTA[intento]);
    }
  }
}

/* Reconstruye las pantallas del muro a partir de lo que dice el servidor. Cuatro
   motivos y cuatro fuentes distintas: con un perfil plano no hay tibias que
   devolver, y hasta hoy eso pintaba «Te devuelvo esas 0» y un pasillo sin salida. */
function insertarDesempate(datos) {
  const v = datos?.veredicto || {};
  const motivo = v.motivo || 'tibieza';
  // La ronda la manda el servidor: la del cliente se reseteaba con F5.
  ronda = Math.min((Number(v.ronda) || 0) + 1, MAX_RONDAS_TIBIEZA + 1);

  const idx = indicePreguntas();
  const test = CONTENIDO.test;
  let fuente = [];
  let sinCentro = true;
  let rehacer = false;

  if (motivo === 'plano') {
    const planas = datos.planas || {};
    fuente = [...(planas.preguntas || [])];
    (planas.bloques_fc_pendientes || []).forEach((id) =>
      fuente.push({ seccion: 'arquetipos', id }));
  } else if (motivo === 'texto_pobre') {
    fuente = (datos.textos?.pobres || []).filter((t) => t.al_muro !== false);
  } else if (motivo === 'sin_validez') {
    // Repetir el test entero. Aquí NO se quita el centro: cambiar la escala a
    // media faena convertiría el instrumento en otro distinto.
    sinCentro = false;
    rehacer = true;
    fuente = (test.items || []).map((it) => ({ seccion: 'arquetipos', id: it.id }));
  } else {
    fuente = (datos.tibieza?.preguntas_tibias || []).filter((t) => t.al_muro !== false);
  }

  const nuevos = [{
    tipo: 'muro',
    motivo,
    tibias: Number(datos.tibieza?.tibias) || 0,
    cuantas: fuente.length,
  }];

  fuente.forEach((entrada) => {
    const p = idx[entrada.seccion]?.[entrada.id];
    if (!p) return;
    const paso = {
      tipo: 'pregunta',
      seccion: entrada.seccion,
      pregunta: p,
      desempate: true,
      sinCentro,
      rehacer,
      // La respuesta vieja sale del estado y se guarda en el paso: mientras
      // seguía en estado[seccion][id], contestado() la daba por buena y el muro
      // se cruzaba entero manteniendo Enter con el valor tibio intacto.
      valorPrevio: estado[entrada.seccion]?.[entrada.id],
      textoPrevio: entrada.texto_previo || null,
    };
    delete estado[entrada.seccion][entrada.id];
    nuevos.push(paso);
  });

  // Nunca un muro sin preguntas detrás: si no hay nada que repreguntar, el muro
  // es un callejón y lo honesto es emitir.
  if (nuevos.length <= 1) { enviar(); return; }

  // Insertar justo antes del paso final; al terminarlos se vuelve a la puerta.
  const posFinal = PASOS.length - 1;
  PASOS.splice(posFinal, 0, ...nuevos);
  i = posFinal;
  // La bajada de `contestadas` que viene ahora la hemos provocado nosotros, y
  // el servidor ya ha subido la versión del borrador al anotar la ronda: se
  // avisa a resolverConflicto para que no lo lea como otro dispositivo.
  muroReciente = true;
  guardar();
  subirBorrador({ forzar: true });
  pintar();
}

function nuevaClave() {
  try {
    if (crypto?.randomUUID) return crypto.randomUUID();
  } catch { /* navegador viejo o contexto no seguro */ }
  return `idem-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function pintarEnlaceInforme({ id, token }) {
  const zona = $('zona-final');
  if (!zona) return;
  const url = token ? `/informe/${id}?t=${encodeURIComponent(token)}` : `/informe/${id}`;
  zona.innerHTML = `
    <p class="entradilla">Tu informe ya está guardado, puedes verlo ya.</p>
    <a class="btn-primario" href="${escapar(url)}" style="display:inline-block">Ver mi informe</a>`;
}

async function enviar() {
  const zona = $('zona-final');
  if (!zona) return;
  if (informeEmitido) { pintarEnlaceInforme(informeEmitido); return; }
  if (enviando) return; // volver atrás y adelante creaba dos informes y dos llamadas a la IA
  enviando = true;
  zona.innerHTML = cargando('Calculando tu perfil…');

  try {
    const resp = await fetch('/api/informe', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...estado, clave_idem: CLAVE_IDEM }),
    });

    // El 409 es la misma respuesta que /api/tibieza: el muro de verdad está aquí.
    if (resp.status === 409) {
      enviando = false;
      insertarDesempate(await resp.json());
      return;
    }
    if (!resp.ok) {
      let detalle = 'Error del servidor';
      try { detalle = (await resp.json()).detail || detalle; } catch { /* cuerpo no JSON */ }
      throw new Error(detalle);
    }

    const { id, token_acceso: token } = await resp.json();
    informeEmitido = { id, token };
    // El borrador NO se borra: «volver a hacerlo» no puede destruir el intento
    // anterior. Solo se le anota de qué informe salió.
    guardar();

    const url = token ? `/informe/${id}?t=${encodeURIComponent(token)}` : `/informe/${id}`;
    zona.innerHTML = `
      ${cargando('Perfil listo. Pidiendo a la IA tus tres direcciones… (tarda un poco)')}
      <p><a class="enlace-privacidad" href="${escapar(url)}">Tu informe ya está guardado, puedes verlo ya</a></p>`;

    // Si la IA falla, el informe existe igual: no bloqueamos por ella.
    try {
      await fetch(`/api/informe/${id}/ia`, { method: 'POST', credentials: 'same-origin' });
    } catch { /* se mostrará sin recomendaciones */ }

    window.location.href = url;
  } catch (e) {
    enviando = false;
    zona.innerHTML = `<div class="nota" style="border-left-color:var(--marca)">
      No se pudo generar el informe: ${escapar(e.message)}
    </div>
    <button class="btn-primario" id="btn-reintentar-envio">Reintentar</button>`;
    $('btn-reintentar-envio')?.addEventListener('click', () => enviar());
  }
}

/* ================= Arranque ================= */

/* Se reanuda por ID de pregunta, no por posición. `i` era un índice contra un
   array que insertarDesempate muta, así que al recargar se aterrizaba en la
   penúltima pregunta del módulo de acciones sin haber contestado nada. */
function posicionInicial() {
  const ultimo = PASOS.length - 2; // el paso anterior al final

  /* Los pasos de identidad (nombre, tipo de marca) NO son de tipo 'pregunta', y
     contestado() les devuelve true siempre para no bloquear el pie. Buscando
     solo pasos de tipo 'pregunta', la primera sin contestar de un cuestionario
     vacío era el ítem 1 del test: el visitante nuevo aterrizaba ahí de golpe,
     sin puerta de acceso, sin portada y sin que nadie le preguntara su nombre.
     Se considera pendiente también el paso de identidad con el valor vacío. */
  const pendiente = (p) =>
    (p.tipo === 'pregunta' && !contestado(p)) ||
    ((p.tipo === 'nombre' || p.tipo === 'tipo_marca') && vacio(valorDe(p)));
  const primeraSinContestar = () => {
    const n = PASOS.findIndex(pendiente);
    return n >= 0 ? n : Math.max(0, ultimo);
  };

  // Sin una sola respuesta no hay nada que reanudar: se empieza por el
  // principio, que es la puerta de acceso o la portada.
  if (contarContestadas() === 0) return 0;

  // Con ronda abierta no se reanuda en un desempate inyectado: se vuelve a la
  // primera sin contestar y lanzar() vuelve a pedir la puerta, que ahora conoce
  // la ronda real porque vive en el servidor.
  if (ronda > 0) return primeraSinContestar();

  const id = YO?.borrador?.ultimo_id || localGuardado?.ultimoId || null;
  if (id) {
    const n = PASOS.findIndex((p) => p.pregunta?.id === id);
    if (n > 0) return Math.min(n, ultimo);
  }
  const n = primeraSinContestar();
  if (n > 0) return n;
  return PASOS[0]?.tipo === 'acceso' ? 0 : (YO?.autenticado ? 0 : 0);
}

function pintarErrorArranque() {
  const e = escena();
  if (!e) return;
  e.innerHTML = `
    <div class="tarjeta-paso">
      <h1>No he podido cargar el cuestionario.</h1>
      <p class="entradilla">
        El servidor no ha devuelto el contenido. No es cosa tuya y no has perdido
        nada de lo que hubieras contestado antes.
      </p>
      <button class="btn-primario" id="btn-recargar">Reintentar</button>
    </div>`;
  $('btn-recargar')?.addEventListener('click', () => location.reload());
  $('pie').hidden = true;
}

async function iniciar() {
  inyectarEstilos();
  localGuardado = restaurar();

  // Con reloj los dos: un servidor que acepta la conexión y no contesta dejaba
  // la página en blanco para siempre, sin intro y con dos botones muertos.
  const conReloj = async (url, ms) => {
    const ctl = new AbortController();
    const reloj = setTimeout(() => ctl.abort(), ms);
    try {
      const r = await fetch(url, { credentials: 'same-origin', signal: ctl.signal });
      if (!r.ok) throw new Error(String(r.status));
      return await r.json();
    } finally { clearTimeout(reloj); }
  };

  try {
    YO = await conReloj('/api/yo', TIMEOUT_SUBIDA);
  } catch {
    YO = { autenticado: false, google_disponible: document.body.dataset.google === '1' };
  }

  try {
    CONTENIDO = await conReloj('/api/contenido', 15000);
  } catch {
    // Hasta hoy no había try/catch: la página se quedaba en blanco con dos
    // botones muertos en el pie y ni un mensaje.
    pintarErrorArranque();
    return;
  }

  CLAVE_IDEM = CLAVE_IDEM || nuevaClave();
  INDICE_CACHE = null;
  PASOS = construirPasos({ conAcceso: !YO.autenticado });

  await resolverBorrador(localGuardado);

  // Reanudación normal: hay trabajo hecho en la cuenta y no hay conflicto.
  const sb = YO?.borrador;
  if (!DECISION && sb && Number(sb.contestadas) > 0 && !localGuardado) {
    // `contestadas` lo cuenta el servidor sobre las CINCO secciones, identidad
    // incluida, así que con el cuestionario entero da 147 sobre 145 preguntas.
    // Es el árbitro de conflictos, no un contador de preguntas: aquí se topa
    // para que la tarjeta no diga «llevas 147 de 145».
    const total = totalPreguntas();
    pedirDecision('reanudar', {
      hechas: Math.min(Number(sb.contestadas) || 0, total),
      total,
      actualizado_en: sb.actualizado_en,
    });
  }
  avisarFusion();

  i = posicionInicial();

  $('btn-siguiente').addEventListener('click', siguiente);
  $('btn-atras').addEventListener('click', atras);
  document.addEventListener('keydown', teclado);
  engancharCiclo();

  pintar();
}

// En un DOM simulado (las pruebas del scratchpad) no hay escena que pintar: el
// fichero se carga para ejercitar la lógica pura y arrancar solo sobraría.
if (typeof document !== 'undefined' && document.getElementById('escena')) {
  iniciar();
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    estado, construirPasos, indicePreguntas, contestado, problema, esTibio,
    sugerirNombres, contarContestadasDe, silabas, normalizar,
    plantilla, pregunta, plantillaMuro, plantillaAcceso, plantillaDecision,
    opcionesDe,
    fijarContenido: (c) => { CONTENIDO = c; INDICE_CACHE = null; },
    fijarPasos: (p) => { PASOS = p; },
  };
}
