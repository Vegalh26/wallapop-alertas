"""
Wallapop bots - versión "serverless" para GitHub Actions.
Cada ejecución (cada ~5 min, lanzada por el cron de GitHub):
  1. Lee los mensajes pendientes de Telegram y aplica los comandos (crear, pausar, borrar...).
  2. Comprueba en Wallapop cada bot activo y avisa por Telegram de lo nuevo.
  3. Guarda el estado en data/*.json (el workflow lo sube al repo).
Variables de entorno necesarias (GitHub Secrets):
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""
import base64
import hashlib
import html
import json
import os
import re
import signal
import threading
import sys
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0") or 0)
API = f"https://api.telegram.org/bot{TOKEN}"

DATA_DIR = Path("data")
CFG_FILE = DATA_DIR / "config.json"    # bots definidos (lo editan el panel web y Telegram)
STATE_FILE = DATA_DIR / "state.json"   # anuncios ya vistos, offset de Telegram...
REPO = os.environ.get("GITHUB_REPOSITORY", "")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CFG_KEYS = ("id", "keywords", "min_price", "max_price", "status", "source", "lang_mode", "langs", "exclude", "fast")
FUENTES = ("wallapop", "vinted", "ambos")
VINTED_TLD = os.environ.get("VINTED_TLD", "es")

# ---------- Filtro de idioma ----------
# Ni Wallapop ni Vinted dan el idioma como dato: se deduce de palabras del título y de los primeros
# 200 caracteres de la descripción. Solo se usan palabras que NO existen en español (tras quitar
# acentos) para no confundir: "version", "original", "the" (muchos juegos conservan su título inglés)...
IDIOMAS = {
    "it": ("Italiano", ["italiano", "italiana", "italiani", "italian", "italia", "italy", "ita", "ital",
                        "gioco", "giochi", "usato", "nuovo", "edizione", "versione", "della", "dello", "delle",
                        "degli", "dei", "gli", "il", "nel", "nella", "scatola", "originale", "spedizione",
                        "professore", "di", "inglese", "fumetto", "segnalibro", "e il", "e la", "e lo", "e i", "e gli", "e le"]),
    "fr": ("Francés", ["frances", "francesa", "francais", "francaise", "french", "france", "francia", "fra",
                       "fr", "jeu", "jeux", "occasion", "boite", "avec", "livraison", "professeur",
                       "et", "des", "du", "aux", "les", "pour", "dans", "une", "etat"]),
    "en": ("Inglés", ["ingles", "inglesa", "english", "eng", "uk", "ntsc-u"]),
    "de": ("Alemán", ["aleman", "alemana", "alemania", "german", "germany", "deutsch", "deutsche", "ger",
                      "deu", "spiel", "gebraucht", "und", "versand", "der", "die", "dem", "mit", "von",
                      "eine", "fur"]),
    "pt": ("Portugués", ["portugues", "portuguesa", "portuguese", "portugal", "pt", "jogo", "com", "uma",
                         "nao", "e o", "e a", "e os", "e as"]),
    "jp": ("Japonés", ["japones", "japonesa", "japanese", "japan", "japon", "jp", "jpn", "ntsc-j"]),
    "es": ("Español", ["espanol", "espanola", "castellano", "spanish", "spain", "esp", "spa", "profesor"]),
}
_IDI_RE = {c: re.compile(r"\b(?:" + "|".join(re.escape(w) for w in sorted(ws, key=len, reverse=True)) + r")\b")
           for c, (_n, ws) in IDIOMAS.items()}
# Elisiones l'..., d'..., dell'... : son francés o italiano (no español) pero no se sabe cuál -> "?"
_ELISION = re.compile(r"(?<![a-z])(?:l|d|dell|all|nell|sull|qu|j)'[a-z]")
AMBIGUO = {"fr", "it"}


def _sin_acentos(t):
    t = unicodedata.normalize("NFKD", str(t).lower().replace("\u2019", "'"))
    return "".join(c for c in t if not unicodedata.combining(c))


# En la descripción se ignoran los nombres de país: suelen ser avisos de envío ("no envío a Italia").
_PAISES = re.compile(r"\b(?:italia|italy|france|francia|germany|alemania|portugal|japan|japon|spain|uk)\b")


# ---------- Detector estadístico (lingua) ----------
# Se usa SOLO cuando las listas de palabras no encuentran ninguna pista. Si lingua no está instalada,
# el filtro sigue funcionando solo con las listas. Umbrales ajustables:
LG_MIN = 0.50         # confianza mínima del idioma ganador
LG_MARGEN = 0.25      # ventaja mínima sobre el segundo (si dudan entre dos idiomas, no se decide)
LG_MIN_EN = 0.70      # el inglés exige más: muchos juegos/mangas en español conservan el título inglés
_LG_MAP = {"ES": "es", "IT": "it", "FR": "fr", "EN": "en", "DE": "de", "PT": "pt", "JA": "jp"}
_det = None           # None = sin construir; False = lingua no disponible


def _detector():
    global _det
    if _det is None:
        try:
            from lingua import Language, LanguageDetectorBuilder
            langs = [getattr(Language, n) for n in ("SPANISH", "ITALIAN", "FRENCH", "ENGLISH",
                                                    "GERMAN", "PORTUGUESE", "JAPANESE")]
            _det = LanguageDetectorBuilder.from_languages(*langs).build()
        except Exception as e:
            print("Aviso: lingua no disponible, solo se usan las listas de palabras:", e)
            _det = False
    return _det


def idioma_detectado(titulo, desc=""):
    """Código de idioma ('es','it',...) si lingua lo tiene claro; None si no."""
    d = _detector()
    texto = f"{titulo}. {desc}".strip()
    if not d or len(texto) < 8:
        return None
    try:
        c = d.compute_language_confidence_values(texto)
    except Exception:
        return None
    if not c:
        return None
    cod = _LG_MAP.get(c[0].language.iso_code_639_1.name)
    segundo = c[1].value if len(c) > 1 else 0.0
    minimo = LG_MIN_EN if cod == "en" else LG_MIN
    if cod and c[0].value >= minimo and c[0].value - segundo >= LG_MARGEN:
        return cod
    return None


def idiomas_en(titulo, desc=""):
    desc = str(desc or "")[:200]
    t = _sin_acentos(titulo)
    d = _PAISES.sub(" ", _sin_acentos(desc))
    out = {c for c, rx in _IDI_RE.items() if rx.search(t) or rx.search(d)}
    if _ELISION.search(t) or _ELISION.search(d):
        out.add("?")
    if not out:  # sin pistas en las listas: preguntar al detector estadístico
        cod = idioma_detectado(titulo, desc)
        if cod:
            out.add(cod)
    return out


def pasa_idioma(b, r):
    """True si el anuncio 'r' cumple el filtro de idioma del bot 'b'.
    excluir: se descarta si menciona alguno de los idiomas elegidos.
    solo:    se descarta si parece estar en otro idioma y no en alguno de los elegidos
             (los anuncios sin ninguna pista de idioma se mantienen).
    "?" = parece francés o italiano sin poder precisar cuál."""
    modo = b.get("lang_mode", "off")
    langs = set(b.get("langs") or [])
    if modo not in ("excluir", "solo") or not langs:
        return True
    hay = set(r["lg"]) if "lg" in r else idiomas_en(r.get("nombre", ""), r.get("desc", ""))
    if modo == "excluir":
        return not (hay & langs) and not ("?" in hay and AMBIGUO <= langs)
    if not hay:
        return True
    return bool(hay & langs) or ("?" in hay and bool(langs & AMBIGUO))


# ---------- Palabras excluidas ----------
# Cada bot puede llevar una lista de palabras/frases: si el título o la descripción contiene alguna,
# el anuncio se ignora. Se comparan sin acentos ni mayúsculas. Un "*" al final cubre variantes
# ("caja*" -> caja, cajas, cajita...).
MAX_EXCL = 30
_EXCL_CACHE = {}


def limpiar_excl(v):
    """Acepta una lista o un texto separado por comas/saltos de línea y devuelve la lista limpia."""
    if isinstance(v, str):
        v = re.split(r"[,;\n]+", v)
    out, vistos = [], set()
    for t in v or []:
        t = str(t).replace("|", " ").strip()[:40]
        k = t.lower()
        if t and k not in vistos:
            vistos.add(k)
            out.append(t)
    return out[:MAX_EXCL]


def _rx_excl(t):
    t = _sin_acentos(t).strip()
    prefijo = t.endswith("*")
    t = t.rstrip("*").strip()
    if not t:
        return None
    cuerpo = r"\s+".join(re.escape(p) for p in t.split())
    return re.compile(r"(?<!\w)" + cuerpo + (r"\w*" if prefijo else r"(?!\w)"))


def pasa_exclusion(b, r):
    """False si el título o la descripción del anuncio 'r' contiene alguna palabra excluida del bot 'b'."""
    terms = b.get("exclude") or []
    if not terms:
        return True
    clave = tuple(terms)
    rxs = _EXCL_CACHE.get(clave)
    if rxs is None:
        rxs = _EXCL_CACHE[clave] = [rx for rx in map(_rx_excl, terms) if rx]
    texto = _sin_acentos(f"{r.get('nombre', '')} {r.get('desc', '')}")
    return not any(rx.search(texto) for rx in rxs)


def excl_txt(b):
    terms = b.get("exclude") or []
    if not terms:
        return ""
    extra = f" (+{len(terms) - 8})" if len(terms) > 8 else ""
    return f"🚫 Sin: {esc(', '.join(terms[:8]))}{extra}\n"


def filtro_txt(b):
    modo, langs = b.get("lang_mode", "off"), b.get("langs") or []
    if modo not in ("excluir", "solo") or not langs:
        return ""
    nombres = ", ".join(IDIOMAS[c][0] for c in langs if c in IDIOMAS)
    return f"🌐 {'Solo' if modo == 'solo' else 'Sin'}: {nombres}\n"


def idioma_txt(r):
    lg = r.get("lg") or []
    nombres = [IDIOMAS[c][0] for c in lg if c in IDIOMAS]
    if nombres:
        return ", ".join(nombres)
    return "posible francés/italiano" if "?" in lg else "no detectado"


def firma(b):
    """Resumen de la configuración de búsqueda del bot (precio, plataformas, idioma, palabras excluidas).
    Se guarda en cada novedad para poder separar las de una configuración anterior."""
    modo = b.get("lang_mode", "off")
    langs = ",".join(sorted(b.get("langs") or [])) if modo in ("excluir", "solo") else ""
    if not langs:
        modo = "off"
    ex = ",".join(sorted(t.strip().lower() for t in (b.get("exclude") or [])))
    base = f"{b['min_price']}|{b['max_price']}|{b.get('source', 'ambos')}|{modo}:{langs}"
    return base + ("|" + ex if ex else "")  # sin palabras excluidas la firma es la de siempre


ORDER_BY = "newest"
# Wallapop ha ido cambiando de endpoint; se prueban en orden si uno da 404.
SEARCH_URLS = [
    "https://api.wallapop.com/api/v3/search",
    "https://api.wallapop.com/api/v3/general/search",
]
# Coordenadas de referencia de la búsqueda (por defecto Madrid). Se pueden cambiar con
# las variables WALLAPOP_LAT / WALLAPOP_LON.
LAT = os.environ.get("WALLAPOP_LAT", "40.4168")
LON = os.environ.get("WALLAPOP_LON", "-3.7038")
SIN_LIMITE = 1000

# LOOP_SECONDS > 0 -> la ejecución se queda en bucle ese tiempo, comprobando cada CHECK_INTERVAL s.
# LOOP_SECONDS = 0 -> una sola comprobación y termina.
LOOP_SECONDS = int(os.environ.get("LOOP_SECONDS", "0") or 0)
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "10") or 10)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://es.wallapop.com/",
    "Origin": "https://es.wallapop.com",
    "X-DeviceOS": "0",
}


def esc(s):
    return html.escape(str(s))


def ahora():
    return datetime.now(ZoneInfo("Europe/Madrid"))


# ======================
# PERSISTENCIA
# ======================
def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    DATA_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ======================
# TELEGRAM
# ======================
def tg(method, _timeout=20, **params):
    try:
        r = requests.post(f"{API}/{method}", json=params, timeout=_timeout)
        return r.json()
    except Exception as e:
        print("Error Telegram:", e)
        return {}


def send(text, markup=None):
    tg(
        "sendMessage",
        chat_id=CHAT_ID,
        text=text[:4000],
        parse_mode="HTML",
        disable_web_page_preview=True,
        **({"reply_markup": markup} if markup else {}),
    )


def send_blocks(header, blocks):
    """Envía una lista larga troceada para no pasar el límite de 4096 de Telegram."""
    msg = header
    for b in blocks:
        if len(msg) + len(b) > 3500:
            send(msg)
            msg = ""
        msg += b
    if msg.strip():
        send(msg)


def fmt_max(m):
    return "sin límite" if m == SIN_LIMITE else f"{m}€"


ETIQ = {"wallapop": "Wallapop", "vinted": "Vinted", "ambos": "Wallapop + Vinted"}


def bot_text(b):
    emoji = {"running": "▶️", "paused": "⏸"}.get(b["status"], "❓")
    return (
        f"🤖 <b>{esc(b['keywords'])}</b>\n"
        f"💰 {b['min_price']}€ – {fmt_max(b['max_price'])}\n"
        f"🔎 {ETIQ.get(b.get('source', 'ambos'))}\n"
        f"{'⚡ Rápido (prioridad)' + chr(10) if b.get('fast') else ''}"
        f"{filtro_txt(b)}{excl_txt(b)}Estado: {emoji} {b['status']}"
    )


def bot_keyboard(b):
    toggle = (
        {"text": "⏸ Pausar", "callback_data": f"p:{b['id']}"}
        if b["status"] == "running"
        else {"text": "▶️ Reanudar", "callback_data": f"r:{b['id']}"}
    )
    return {"inline_keyboard": [[toggle, {"text": "🗑 Borrar", "callback_data": f"d:{b['id']}"}]]}


AYUDA = (
    "👋 <b>Wallapop Bot Manager</b>\n\n"
    "/bots — ver y controlar tus bots\n"
    "/stats — precio medio y mediana de cada bot\n"
    "/nuevo &lt;palabras&gt; [min] [max] — crear un bot\n"
    "   ej: <code>/nuevo mario party 0 30</code>\n"
    "   ej: <code>/nuevo jamboree 25</code> (solo máximo)\n\n"
    "⏱ Los comandos se aplican en la siguiente comprobación (unos minutos)."
)


def parse_nuevo(args):
    t = args.split()
    nums = []
    while t and t[-1].isdigit() and len(nums) < 2:
        nums.insert(0, int(t.pop()))
    if not t:
        return None
    if len(nums) == 2:
        mn, mx = nums
    elif len(nums) == 1:
        mn, mx = 0, nums[0]
    else:
        mn, mx = 0, SIN_LIMITE
    return " ".join(t), mn, mx


# ======================
# PROCESAR MENSAJES DE TELEGRAM
# ======================
def procesar_updates(bots, meta):
    res = tg("getUpdates", offset=meta.get("offset", 0), timeout=0, allowed_updates=["message", "callback_query"])
    manejar_updates(res.get("result", []), bots, meta)


def manejar_updates(ups, bots, meta):
    for u in ups:
        meta["offset"] = u["update_id"] + 1
        try:
            if "message" in u:
                on_message(u["message"], bots)
            elif "callback_query" in u:
                on_callback(u["callback_query"], bots)
        except Exception as e:
            print("Error procesando update:", e)


def esperar_comandos(bots, meta, hasta):
    """Espera hasta 'hasta' escuchando Telegram (long-polling): responde al instante."""
    while time.time() < hasta:
        espera = int(min(25, hasta - time.time()))
        if espera < 1:
            time.sleep(max(0, hasta - time.time()))  # el resto, sin gastar CPU ni peticiones
            break
        res = tg("getUpdates", _timeout=espera + 10, offset=meta.get("offset", 0), timeout=espera,
                 allowed_updates=["message", "callback_query"])
        if not res:
            time.sleep(2)  # fallo de red
            continue
        ups = res.get("result", [])
        if not ups:
            continue
        remota, sha = leer_config()
        bots[:] = fusionar(remota, meta)
        manejar_updates(ups, bots, meta)
        if cfg_of(bots) != remota:
            escribir_config(cfg_of(bots), sha)
        guardar(bots, meta)


def on_message(m, bots):
    if m.get("from", {}).get("id") != CHAT_ID:
        tg("sendMessage", chat_id=m["chat"]["id"], text="🔒 No tienes permiso para usar este bot.")
        return
    text = (m.get("text") or "").strip()
    cmd, _, args = text.partition(" ")
    cmd = cmd.split("@")[0].lower()

    if cmd in ("/start", "/ayuda", "/help"):
        send(AYUDA)
    elif cmd == "/bots":
        if not bots:
            send("😴 No hay bots. Usa /nuevo para crear uno.")
        for b in bots:
            send(bot_text(b), bot_keyboard(b))
    elif cmd == "/stats":
        if not bots:
            send("😴 No hay bots. Usa /nuevo para crear uno.")
        for b in bots:
            send(f"🤖 <b>{esc(b['keywords'])}</b>\n{stats_txt(b)}")
    elif cmd == "/nuevo":
        p = parse_nuevo(args)
        if not p:
            send("Uso: <code>/nuevo mario party 0 30</code>")
            return
        kw, mn, mx = p
        bots.append({
            "id": uuid.uuid4().hex[:8],
            "keywords": kw,
            "min_price": mn,
            "max_price": mx,
            "status": "running",
            "source": "ambos",
            "lang_mode": "off",
            "langs": [],
            "exclude": [],
            "first_done": False,
            "seen": [],
        })
        send(f"✅ Bot <b>{esc(kw)}</b> creado ({mn}€ – {fmt_max(mx)}). Primera comprobación en unos minutos.")


def on_callback(cq, bots):
    if cq["from"]["id"] != CHAT_ID:
        tg("answerCallbackQuery", callback_query_id=cq["id"], text="🔒 Sin permiso")
        return
    tg("answerCallbackQuery", callback_query_id=cq["id"])
    chat = cq["message"]["chat"]["id"]
    mid = cq["message"]["message_id"]
    accion, _, bid = cq["data"].partition(":")
    b = next((x for x in bots if x["id"] == bid), None)

    def editar(text, markup=None):
        tg("editMessageText", chat_id=chat, message_id=mid, text=text, parse_mode="HTML",
           **({"reply_markup": markup} if markup else {}))

    if b is None:
        editar("⚠️ Bot no encontrado (puede que ya se haya eliminado).")
    elif accion == "p":
        b["status"] = "paused"
        editar(bot_text(b), bot_keyboard(b))
    elif accion == "r":
        b["status"] = "running"
        editar(bot_text(b), bot_keyboard(b))
    elif accion == "d":
        editar(f"⚠️ ¿Eliminar el bot <b>{esc(b['keywords'])}</b>?", {"inline_keyboard": [[
            {"text": "✅ Sí, borrar", "callback_data": f"dd:{b['id']}"},
            {"text": "❌ Cancelar", "callback_data": f"c:{b['id']}"},
        ]]})
    elif accion == "dd":
        bots.remove(b)
        editar(f"🔴 Bot <b>{esc(b['keywords'])}</b> eliminado.")
    elif accion == "c":
        editar(bot_text(b), bot_keyboard(b))


# ======================
# WALLAPOP
# ======================
def _tiene_titulo(x):
    return isinstance(x, dict) and "title" in x.get("content", x)


def _buscar_lista_items(obj):
    """Busca recursivamente la primera lista de anuncios (por si Wallapop cambia la estructura)."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj) and any(_tiene_titulo(x) for x in obj):
            return obj
        for x in obj:
            r = _buscar_lista_items(x)
            if r:
                return r
    elif isinstance(obj, dict):
        for v in obj.values():
            r = _buscar_lista_items(v)
            if r:
                return r
    return []


def extraer_items(data):
    return (
        data.get("search_objects")
        or data.get("data", {}).get("search_objects")
        or data.get("data", {}).get("section", {}).get("items")
        or data.get("data", {}).get("section", {}).get("payload", {}).get("items")
        or data.get("items")
        or _buscar_lista_items(data)
        or []
    )


def _primera_url(x):
    """Primera URL de imagen que encuentre en cualquier estructura (Wallapop/Vinted cambian los nombres)."""
    if isinstance(x, str):
        return x if x.startswith("http") else ""
    if isinstance(x, dict):
        for k in ("big", "xlarge", "large", "medium", "original", "full_size_url", "url", "urls", "small"):
            if k in x:
                r = _primera_url(x[k])
                if r:
                    return r
        for v in x.values():
            r = _primera_url(v)
            if r:
                return r
    if isinstance(x, list):
        for v in x:
            r = _primera_url(v)
            if r:
                return r
    return ""


# ---------- Hora de publicación y retraso de detección ----------
# Si la plataforma indica CUÁNDO se publicó un anuncio, el aviso dice "publicado hace 40 s" y el panel mide cuánto
# tardamos en verlo. Los nombres de los campos no están documentados: se prueban varios y solo se acepta una fecha
# creíble. 'python check.py --campos "texto"' enseña qué campos de tiempo trae de verdad cada plataforma.
_CLAVES_PUB = ("created_at", "creation_date", "creationDate", "created", "publish_date", "publication_date",
               "published_at", "created_at_ts", "first_published_at")


def _epoch(v):
    """Epoch en segundos desde un número (s o ms) o un texto ISO 8601; None si no es una fecha creíble."""
    try:
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            t = float(v)
        elif isinstance(v, str):
            t = float(v) if v.replace(".", "", 1).isdigit() else datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        else:
            return None
        if t > 1e12:
            t /= 1000  # milisegundos
        return t if 1.4e9 < t < time.time() + 600 else None
    except (ValueError, OverflowError, OSError):
        return None


def hora_pub(obj):
    """(epoch, campo) de publicación del anuncio, o (None, '') si la respuesta no la trae."""
    if not isinstance(obj, dict):
        return None, ""
    for k in _CLAVES_PUB:
        t = _epoch(obj.get(k))
        if t:
            return t, k
    hr = (obj.get("photo") or {}).get("high_resolution") if isinstance(obj.get("photo"), dict) else None
    t = _epoch(hr.get("timestamp")) if isinstance(hr, dict) else None  # Vinted: la foto se sube al publicar
    return (t, "photo.timestamp") if t else (None, "")


def _edad(seg):
    seg = int(seg)
    return f"{seg} s" if seg < 90 else _dur(seg)


def generar_key(nombre, precio, plat="Wallapop"):
    pre = "" if plat == "Wallapop" else plat + "|"  # las claves de Wallapop no cambian
    return hashlib.md5(f"{pre}{nombre}-{precio}".encode()).hexdigest()


def key_de(r):
    return generar_key(r["nombre"], r["precio"], r.get("plat", "Wallapop"))


def _wallapop_items(keywords, min_price, max_price):
    """Anuncios en bruto de Wallapop. Lanza excepción si la API falla (así no confundimos 'error' con 'sin resultados')."""
    params = {
        "source": "search_box",
        "keywords": keywords,
        "order_by": ORDER_BY,
        "latitude": LAT,
        "longitude": LON,
    }
    if min_price > 0:
        params["min_sale_price"] = min_price
    if max_price < SIN_LIMITE:
        params["max_sale_price"] = max_price

    ultimo_error = None
    data = None
    for url in SEARCH_URLS:
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.HTTPError as e:
            ultimo_error = e
            print("Respuesta de Wallapop:", resp.status_code, resp.text[:300])
            if resp.status_code == 404:
                continue  # probamos el siguiente endpoint
            raise
    if data is None:
        raise ultimo_error

    items = extraer_items(data)
    if not items:
        print("Respuesta sin anuncios. Claves:", list(data.keys())[:10], "->", str(data)[:300])
    return items


def buscar(keywords, min_price, max_price):
    """Anuncios de Wallapop ya procesados."""
    resultados = []
    for item in _wallapop_items(keywords, min_price, max_price):
        content = item.get("content", item)
        titulo = content.get("title", "")
        if keywords.lower() not in titulo.lower():
            continue
        price_obj = content.get("price", {})
        precio = float(
            price_obj.get("amount", price_obj.get("value", 0))
            if isinstance(price_obj, dict)
            else price_obj or 0
        )
        if max_price < SIN_LIMITE and precio > max_price:
            continue
        slug = content.get("web_slug") or content.get("slug") or content.get("id")
        pub, pk = hora_pub(content)
        if not pub:
            pub, pk = hora_pub(item)
        resultados.append({
            **({"pub": pub, "pub_k": pk} if pub else {}),
            "nombre": titulo,
            "precio": precio,
            "enlace": f"https://es.wallapop.com/item/{slug}",
            "plat": "Wallapop",
            "img": _primera_url(content.get("images")),
            "desc": str(content.get("description") or "")[:600],
        })
    return resultados


# ---------- VINTED ----------
_vinted = {"s": None, "t": 0}


_vinted_lock = threading.Lock()  # las consultas van en paralelo: una sola crea la sesión


def _vinted_sesion():
    with _vinted_lock:
        if _vinted["s"] and time.time() - _vinted["t"] < 1800:
            return _vinted["s"]
        s = requests.Session()
        s.headers.update({"User-Agent": HEADERS["User-Agent"], "Accept-Language": "es-ES,es;q=0.9"})
        r = s.get(f"https://www.vinted.{VINTED_TLD}/", timeout=20)
        r.raise_for_status()
        s.anon = r.headers.get("X-Anon-Id", "")
        _vinted.update(s=s, t=time.time())
        return s


def _vinted_items(keywords, min_price, max_price):
    """Anuncios en bruto de Vinted."""
    base = f"https://www.vinted.{VINTED_TLD}"
    params = {"search_text": keywords, "order": "newest_first", "per_page": 24, "page": 1}
    if min_price > 0:
        params["price_from"] = min_price
    if max_price < SIN_LIMITE:
        params["price_to"] = max_price
    urls = [f"https://api.vinted.{VINTED_TLD}/svc-catalogue/items", f"{base}/api/v2/catalog/items"]
    resp = None
    for url in urls:
        for intento in range(2):
            s = _vinted_sesion()
            h = {"Accept": "application/json, text/plain, */*", "Locale": "es-ES", "Platform": "web",
                 "X-Next-App": "marketplace-web", "Origin": base, "Referer": base + "/"}
            if s.anon:
                h["X-Anon-Id"] = s.anon
            resp = s.get(url, params=params, headers=h, timeout=20)
            if resp.status_code in (401, 403) and intento == 0:
                _vinted["s"] = None  # renovar cookies y reintentar
                continue
            break
        if resp.status_code != 404:
            break
    if resp.status_code >= 400:
        print("Respuesta de Vinted:", resp.status_code, resp.text[:200])
        resp.raise_for_status()

    return _buscar_lista_items(resp.json())


def buscar_vinted(keywords, min_price, max_price):
    base = f"https://www.vinted.{VINTED_TLD}"
    out = []
    for it in _vinted_items(keywords, min_price, max_price):
        titulo = it.get("title", "")
        if keywords.lower() not in titulo.lower():
            continue
        pr = it.get("price", 0)
        try:
            precio = float(pr.get("amount", 0) if isinstance(pr, dict) else pr or 0)
        except (TypeError, ValueError):
            precio = 0.0
        if max_price < SIN_LIMITE and precio > max_price:
            continue
        enlace = it.get("url") or f"/items/{it.get('id')}"
        if enlace.startswith("/"):  # Vinted a veces devuelve solo la ruta
            enlace = base + enlace
        pub, pk = hora_pub(it)
        out.append({**({"pub": pub, "pub_k": pk} if pub else {}),
                    "nombre": titulo, "precio": precio, "plat": "Vinted", "enlace": enlace,
                    "img": _primera_url(it.get("photo")), "desc": str(it.get("description") or "")[:600]})
    return out


# ---------- Precios: bajadas, chollos y estadísticas ----------
# · Bajada: un anuncio que ya conocíamos (se identifica por su enlace) vuelve a salir más barato.
#   Cuenta si baja al menos BAJADA_MIN_EUR € y BAJADA_MIN_PCT %. Si SUBE de precio ya no se avisa como novedad.
# · Chollo: un anuncio nuevo con un precio CHOLLO_PCT % (o más) por debajo de la MEDIANA de los anuncios de esa
#   búsqueda DENTRO DE TU RANGO de precio (ver estadísticas). CHOLLO_PCT=0 lo desactiva.
# · Estadísticas: cada STATS_EVERY segundos se recalcula, para un bot por vuelta, el precio del mercado de su
#   búsqueda SIN límite de precio y dentro de tu rango. Se guardan en data/stats.json (las muestra el panel).
BAJADA_MIN_PCT = float(os.environ.get("BAJADA_MIN_PCT", "5") or 5)
BAJADA_MIN_EUR = float(os.environ.get("BAJADA_MIN_EUR", "1") or 1)
CHOLLO_PCT = float(os.environ.get("CHOLLO_PCT", "40") or 0)
CHOLLO_MIN_N = 8       # muestras mínimas para fiarse de la mediana
PRECIOS_MAX = 2000     # precios recordados por bot
STATS_EVERY = int(os.environ.get("STATS_EVERY", "21600") or 21600)
STATS_PATH = "data/stats.json"
STATS = {}             # id de bot -> estadísticas
_stats_ctl = {"cargadas": False, "fallo": {}}


def ident(r):
    """Identidad estable de un anuncio (su enlace sin parámetros): no cambia aunque cambie el precio."""
    return hashlib.md5(r["enlace"].split("?")[0].split("#")[0].encode()).hexdigest()[:10]


def baja_significativa(antes, ahora_):
    d = antes - ahora_
    return d >= BAJADA_MIN_EUR and d >= antes * BAJADA_MIN_PCT / 100


def _resumen(precios):
    p = sorted(x for x in precios if x > 0)
    if not p:
        return None
    n = len(p)
    med = p[n // 2] if n % 2 else (p[n // 2 - 1] + p[n // 2]) / 2
    return {"n": n, "media": round(sum(p) / n, 2), "mediana": round(med, 2), "min": p[0], "max": p[-1]}


def sig_stats(b):
    """Las estadísticas solo valen para la configuración con la que se calcularon."""
    return b["keywords"].lower() + "|" + firma(b)


def sig_mercado(b):
    """Lo que define el MERCADO de un bot (sin el rango de precio): si cambia, la serie histórica se reinicia."""
    return "|".join([b["keywords"].lower(), b.get("source", "ambos"),
                     b.get("lang_mode", "off") + ":" + ",".join(sorted(b.get("langs") or [])),
                     ",".join(sorted(w.lower() for w in (b.get("exclude") or [])))])


def _hist(precios):
    """Histograma de precios para el panel: barras de ancho 'bonito' hasta el percentil 95; lo más caro va a 'mas'."""
    p = sorted(x for x in precios if x > 0)
    if len(p) < 3:
        return None
    tope = p[min(len(p) - 1, int(len(p) * 0.95))]
    ancho = next((a for a in (0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000) if a >= tope / 10), 1000)
    n = int(tope // ancho) + 1
    c, mas = [0] * n, 0
    for x in p:
        i = int(x // ancho)
        if i >= n:
            mas += 1
        else:
            c[i] += 1
    return {"w": ancho, "c": c, "mas": mas}


def marcar_chollo(b, r):
    if CHOLLO_PCT <= 0:
        return
    s = STATS.get(b["id"])
    if not s or s.get("sig") != sig_stats(b):
        return
    t = s.get("rango") or {}  # la mediana de lo que hay dentro de TU rango de precio, no de todo el mercado
    med = t.get("mediana")
    if not med or t.get("n", 0) < CHOLLO_MIN_N or r["precio"] < 0.5:
        return
    pct = round((1 - r["precio"] / med) * 100)
    if pct >= CHOLLO_PCT:
        r["chollo"], r["mediana"] = pct, med


def _fuentes(b):
    fuente = b.get("source", "ambos")
    return [(n, f) for n, f, fu in (("Wallapop", buscar, ("wallapop", "ambos")),
                                    ("Vinted", buscar_vinted, ("vinted", "ambos"))) if fuente in fu]


def cargar_stats():
    _stats_ctl["cargadas"] = True
    try:
        d, _ = leer_json_repo(STATS_PATH, None)
        STATS.update((d or {}).get("bots", {}))
    except Exception as e:
        print("Aviso al leer estadísticas:", e)


def guardar_stats(bots):
    vivos = {b["id"] for b in bots}
    try:
        sha = leer_json_repo(STATS_PATH, None)[1]
        escribir_json_repo(STATS_PATH, {"bots": {i: v for i, v in STATS.items() if i in vivos}}, sha)
    except Exception as e:
        print("Aviso al guardar estadísticas:", e)


def actualizar_stats(bots):
    """Recalcula las estadísticas de UN bot por vuelta (el que más las necesita)."""
    if not _stats_ctl["cargadas"]:
        cargar_stats()
    ahora_t = time.time()
    pend = [b for b in bots if b["status"] == "running"
            and (STATS.get(b["id"], {}).get("sig") != sig_stats(b)
                 or "serie" not in STATS[b["id"]]  # calculadas con una versión anterior: sin datos para los gráficos
                 or ahora_t - STATS[b["id"]].get("t", 0) >= STATS_EVERY)
            and ahora_t - _stats_ctl["fallo"].get(b["id"], 0) >= 600]
    if not pend:
        return
    b = min(pend, key=lambda x: STATS.get(x["id"], {}).get("t", 0))
    muestras = []
    for nombre, fn in _fuentes(b):
        try:
            muestras += fn(b["keywords"], 0, SIN_LIMITE)  # SIN límite de precio
        except Exception as e:
            print(f"[{b['keywords']}] Estadísticas, error {nombre}: {e}")
    if not muestras:
        _stats_ctl["fallo"][b["id"]] = ahora_t
        return
    for r in muestras:
        r["lg"] = sorted(idiomas_en(r["nombre"], r.get("desc", "")))
    muestras = [r for r in muestras if pasa_idioma(b, r) and pasa_exclusion(b, r)]
    precios = [r["precio"] for r in muestras]
    todo = _resumen(precios)
    antes = STATS.get(b["id"], {})
    msig = sig_mercado(b)
    serie = antes.get("serie", []) if antes.get("msig") == msig else []  # evolución en el tiempo
    if todo:
        serie = (serie + [[int(ahora_t), todo["mediana"], todo["media"], todo["n"]]])[-180:]
    plat = {}
    for nombre in ("Wallapop", "Vinted"):
        sub = _resumen([r["precio"] for r in muestras if r.get("plat") == nombre])
        if sub:
            plat[nombre] = {k: sub[k] for k in ("n", "media", "mediana")}
    STATS[b["id"]] = {
        "kw": b["keywords"], "sig": sig_stats(b), "msig": msig, "t": int(ahora_t),
        "todo": todo,
        "rango": _resumen([r["precio"] for r in muestras if b["min_price"] <= r["precio"] <= b["max_price"]]),
        "hist": _hist(precios), "plat": plat, "serie": serie,
    }
    print(f"[{b['keywords']}] estadísticas: {todo} (serie: {len(serie)} puntos)")
    guardar_stats(bots)


def _fmt_resumen(s):
    return f"media {s['media']:.0f}€ · mediana {s['mediana']:.0f}€ · de {s['min']:.0f}€ a {s['max']:.0f}€ ({s['n']} anuncios)"


def stats_txt(b):
    s = STATS.get(b["id"])
    if not s:
        return "📊 Aún sin estadísticas (se calculan en unos minutos)."
    out = "📊 <b>Mercado</b> (sin límite de precio): " + (_fmt_resumen(s["todo"]) if s.get("todo") else "sin datos")
    if s.get("rango"):
        out += f"\n🎯 <b>Tu rango</b> ({b['min_price']}€ – {fmt_max(b['max_price'])}): " + _fmt_resumen(s["rango"])
    return out


def bloque(i, r, con_idioma=False):
    ic = "🟣 Vinted" if r.get("plat") == "Vinted" else "🟢 Wallapop"
    idi = f"\n🌐 Idioma: {idioma_txt(r)}" if con_idioma else ""
    pr = f"{r['precio']:.2f}€"
    if r.get("antes"):
        pr += f" (antes {r['antes']:.2f}€, −{round((1 - r['precio'] / r['antes']) * 100)}%)"
    ch = f"\n🔥 {r['chollo']}% por debajo de la mediana de tu rango ({r['mediana']:.0f}€)" if r.get("chollo") else ""
    pub = ""
    if r.get("nuevo") and r.get("pub"):
        d = time.time() - r["pub"]
        if 0 <= d <= 86400:
            pub = f"\n⏱ Publicado hace {_edad(d)}"
    return f"{i}. {ic} · 💰 {pr}\n📝 {esc(r['nombre'])}{ch}{pub}{idi}\n🔗 {r['enlace']}\n\n"


def _pedir(t):
    b, nombre, fn = t
    try:
        return fn(b["keywords"], b["min_price"], b["max_price"]), None
    except Exception as e:
        return None, e


def comprobar_bots(bots, meta, solo_rapidos=False):
    """Revisa los bots activos. Con solo_rapidos=True solo los marcados como rápidos (y sin avisos de bloqueo)."""
    activos = [b for b in bots if b["status"] == "running" and (b.get("fast") or not solo_rapidos)]
    ok = 0
    n_err = 0
    stats = {"Wallapop": [0, 0, ""], "Vinted": [0, 0, ""]}  # ok, fallos, último error
    ts = ahora().strftime("%d/%m - %H:%M")
    # Las consultas a las plataformas salen EN PARALELO: tardar menos en preguntar es tardar menos en avisar.
    tareas = [(b, n, f) for b in activos for n, f in _fuentes(b)]
    if len(tareas) > 1:
        with ThreadPoolExecutor(max_workers=min(8, len(tareas))) as ex:
            respuestas = list(ex.map(_pedir, tareas))
    else:
        respuestas = [_pedir(t) for t in tareas]
    it_resp = iter(respuestas)
    for b in activos:
        pedidos = _fuentes(b)
        resultados, fallos = [], 0
        for nombre, fn in pedidos:
            res, e = next(it_resp)
            if e is None:
                resultados += res
                stats[nombre][0] += 1
            else:
                print(f"[{b['keywords']}] Error {nombre}: {e}")
                stats[nombre][1] += 1
                stats[nombre][2] = str(e)
                fallos += 1
                n_err += 1
        if fallos == len(pedidos):
            continue  # todo falló: no tocamos el estado
        for r in resultados:  # idiomas detectados (se guardan para mostrarlos en Telegram y en el panel)
            r["lg"] = sorted(idiomas_en(r["nombre"], r.get("desc", "")))
        resultados = [r for r in resultados if pasa_idioma(b, r)]  # filtro de idioma
        resultados = [r for r in resultados if pasa_exclusion(b, r)]  # palabras excluidas
        fi = filtro_txt(b)
        cab = fi + excl_txt(b)
        ok += 1

        previos = b.get("seen", [])
        vistos = set(previos)
        nuevos = [r for r in resultados if key_de(r) not in vistos]
        # Nunca olvidamos lo ya avisado (los resultados "bailan" entre peticiones): sin duplicados
        añadir = list(dict.fromkeys(key_de(r) for r in nuevos))
        b["seen"] = (previos + añadir)[-2000:]

        # Bajadas de precio: un anuncio conocido (por enlace) que ahora es más barato. Si solo cambió al alza
        # o casi nada, es el mismo anuncio y no se avisa como novedad (antes salía como "NUEVO").
        precios = b.setdefault("prices", {})
        novedades, bajadas = [], []
        primera = not b.get("first_done")
        for r in nuevos:
            ant = precios.get(ident(r))
            if primera or ant is None:
                novedades.append(r)
            elif baja_significativa(ant, r["precio"]):
                r["antes"] = ant
                bajadas.append(r)
        for r in resultados:  # recordar el último precio de cada anuncio
            i = ident(r)
            precios.pop(i, None)
            precios[i] = r["precio"]
        if len(precios) > PRECIOS_MAX:
            for k in list(precios)[:len(precios) - PRECIOS_MAX]:
                del precios[k]
        for r in (resultados if primera else novedades + bajadas):
            marcar_chollo(b, r)
        if not primera:
            for r in novedades:
                r["nuevo"] = True  # una novedad de verdad (no la lista inicial ni una bajada): se mide su retraso
                if r.get("pub") and 0 <= time.time() - r["pub"] <= 86400:
                    print(f"[{b['keywords']}] ⏱ {r['nombre'][:40]}: publicado hace {_edad(time.time() - r['pub'])}"
                          f" ({r.get('pub_k')})")

        if not b.get("first_done"):
            b["first_done"] = True
            if resultados:
                registrar(b, resultados)
                send_blocks(
                    f"🔵 <b>Primera comprobación</b> — <i>{esc(b['keywords'])}</i>\n{cab}\n",
                    [bloque(i, r, bool(fi)) for i, r in enumerate(resultados, 1)],
                )
            else:
                send(f"🔴 Sin resultados para <b>{esc(b['keywords'])}</b>")
        elif novedades or bajadas:
            chollos = [r for r in novedades if r.get("chollo")]
            for titulo, lote in (("🔥 <b>POSIBLES CHOLLOS</b>", chollos),
                                 ("📉 <b>BAJADAS DE PRECIO</b>", bajadas),
                                 ("🆕 <b>NUEVOS</b>", [r for r in novedades if not r.get("chollo")])):
                if lote:
                    registrar(b, lote)
                    send_blocks(
                        f"{titulo} — <i>{esc(b['keywords'])}</i>\n📅 {ts}\n{cab}\n",
                        [bloque(i, r, bool(fi)) for i, r in enumerate(lote, 1)],
                    )
        if not solo_rapidos or novedades or bajadas:  # los bots rápidos no llenan el registro en cada vuelta
            print(f"[{b['keywords']}] resultados={len(resultados)} nuevos={len(novedades)} bajadas={len(bajadas)}")

    # Avisos de bloqueo, una sola vez por plataforma (los bots rápidos no los mandan: lo hace la vuelta normal)
    for nombre, (o, f, ultimo) in ({} if solo_rapidos else stats).items():
        flag = "bloqueado" if nombre == "Wallapop" else "bloqueado_vinted"
        if f and not o:
            if not meta.get(flag):
                meta[flag] = True
                send(f"⚠️ <b>No consigo consultar {nombre}</b> (posible bloqueo/limitación).\n"
                     f"<code>{esc(ultimo[:300])}</code>")
        elif o and meta.get(flag):
            meta[flag] = False
            send(f"✅ {nombre} vuelve a responder.")
    return ok, n_err


# ======================
# CONFIG COMPARTIDA (repo, vía API de GitHub) + ESTADO LOCAL
# ======================
def norm(cfg):
    out = []
    for c in cfg:
        kw = str(c.get("keywords", "")).strip()
        if not kw:
            continue
        mx = c.get("max_price")
        st = c.get("status")
        modo = c.get("lang_mode") if c.get("lang_mode") in ("excluir", "solo") else "off"
        langs = [l for l in (c.get("langs") or []) if l in IDIOMAS] if modo != "off" else []
        out.append({
            "id": str(c.get("id") or hashlib.md5(kw.encode()).hexdigest()[:8]),
            "keywords": kw,
            "min_price": int(c.get("min_price") or 0),
            "max_price": SIN_LIMITE if mx in (None, "") else int(mx),
            "status": st if st in ("running", "paused") else "running",
            "source": c.get("source") if c.get("source") in FUENTES else "ambos",
            "lang_mode": modo if langs else "off",
            "langs": langs,
            "exclude": limpiar_excl(c.get("exclude")),
            "fast": bool(c.get("fast")),
        })
    return out


def _gh(method, path, **kw):
    return requests.request(
        method, f"https://api.github.com/repos/{REPO}/contents/{path}",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"},
        timeout=20, **kw)


def leer_json_repo(path, default):
    if not (REPO and GH_TOKEN):
        return load_json(DATA_DIR / Path(path).name, default), None
    r = _gh("GET", path)
    if r.status_code == 404:
        return default, None
    r.raise_for_status()
    j = r.json()
    return json.loads(base64.b64decode(j["content"]).decode("utf-8") or "null"), j["sha"]


def escribir_json_repo(path, obj, sha):
    if not (REPO and GH_TOKEN):
        save_json(DATA_DIR / Path(path).name, obj)
        return None
    txt = json.dumps(obj, ensure_ascii=False, indent=2 if isinstance(obj, list) else None,
                     separators=None if isinstance(obj, list) else (",", ":"))
    body = {"message": f"{Path(path).stem} [skip ci]", "content": base64.b64encode(txt.encode()).decode()}
    for _ in range(2):
        if sha:
            body["sha"] = sha
        r = _gh("PUT", path, json=body)
        if r.status_code in (409, 422):  # conflicto: releer el sha y reintentar
            sha = leer_json_repo(path, None)[1]
            continue
        r.raise_for_status()
        return r.json()["content"]["sha"]
    return sha


def leer_config():
    cfg, sha = leer_json_repo("data/config.json", [])
    return norm(cfg or []), sha


def escribir_config(cfg, sha):
    escribir_json_repo("data/config.json", cfg, sha)


# ---------- Muro de novedades (lo lee y lo limpia el panel web) ----------
# El panel también escribe data/results.json (botones "Vaciar"), así que aquí NO se guarda una copia
# propia: las novedades nuevas se acumulan en RES["new"] y al guardar se fusionan con lo que haya en el repo.
RES = {"new": [], "upd": {}, "sha": None}  # upd: cambios de estado pendientes de subir (ya sin uso)
RES_MAX = 150   # novedades de bots que existen
ARCH_MAX = 100  # novedades de bots borrados (se muestran en "Archivados")


def registrar(b, items):
    t = int(time.time())
    kwl = b["keywords"].lower()
    ya = {(x["id"], str(x.get("kw", "")).lower()) for x in RES["new"]}  # un mismo anuncio puede salir en varios bots
    lote = []
    for r in items:
        i = key_de(r)
        if (i, kwl) in ya:
            continue
        ya.add((i, kwl))
        it = {"id": i, "t": t, "kw": b["keywords"], "p": r.get("plat", "Wallapop"), "n": r["nombre"],
              "pr": r["precio"], "u": r["enlace"], "im": r.get("img", ""),
              "f": firma(b), "lg": ",".join(r.get("lg", []))}
        if r.get("antes"):
            it["pa"] = r["antes"]                      # precio anterior (bajada de precio)
        if r.get("chollo"):
            it["ch"], it["md"] = r["chollo"], r["mediana"]  # % bajo la mediana y mediana
        if r.get("nuevo") and r.get("pub") and 0 <= t - int(r["pub"]) <= 86400:
            it["pub"] = int(r["pub"])  # cuándo se publicó: el panel mide el retraso de detección (t - pub)
            if b.get("fast"):
                it["rp"] = 1
        lote.append(it)
    if lote:
        RES["new"] = lote + RES["new"]


def recortar(items, kws):
    """Limita el muro: hasta RES_MAX de bots vivos y ARCH_MAX de bots borrados (archivados)."""
    out, na, nr = [], 0, 0
    for x in items:
        if str(x.get("kw", "")).lower() in kws:
            if na < RES_MAX:
                out.append(x)
                na += 1
        elif nr < ARCH_MAX:
            out.append(x)
            nr += 1
    return out


def guardar_recientes(bots=None):
    if not RES["new"] and not RES["upd"]:
        return
    kws = {b["keywords"].lower() for b in bots} if bots is not None else None
    for _ in range(3):
        d, sha = leer_json_repo("data/results.json", {"items": []})
        remoto = (d or {}).get("items", [])
        # una bajada de precio sustituye a la tarjeta anterior del mismo anuncio (misma URL)
        sustituye = {(x.get("u"), str(x.get("kw", "")).lower()) for x in RES["new"] if x.get("pa")}
        if sustituye:
            remoto = [x for x in remoto if (x.get("u"), str(x.get("kw", "")).lower()) not in sustituye]
        ids = {(x["id"], str(x.get("kw", "")).lower()) for x in remoto}
        for x in remoto:  # estados pendientes sobre lo que haya en el repo
            k = (x["id"], str(x.get("kw", "")).lower())
            if k in RES["upd"]:
                if RES["upd"][k]:
                    x["st"] = RES["upd"][k]
                else:
                    x.pop("st", None)
        merged = [x for x in RES["new"] if (x["id"], str(x.get("kw", "")).lower()) not in ids] + remoto
        merged = recortar(merged, kws) if kws is not None else merged[:RES_MAX + ARCH_MAX]
        try:
            RES["sha"] = escribir_json_repo("data/results.json", {"items": merged}, sha)
        except requests.HTTPError as e:
            print("Aviso al guardar novedades (reintento):", e)
            continue
        RES["new"] = []
        RES["upd"] = {}
        return


def cfg_of(bots):
    return [{k: b[k] for k in CFG_KEYS} for b in bots]


def fusionar(cfg, meta):
    est = meta.get("bots", {})
    return [{**c, "seen": est.get(c["id"], {}).get("seen", []),
             "first_done": est.get(c["id"], {}).get("first_done", False),
             "prices": est.get(c["id"], {}).get("prices", {})} for c in cfg]


def guardar(bots, meta):
    meta["bots"] = {b["id"]: {"seen": b.get("seen", []), "first_done": b.get("first_done", False),
                              "prices": b.get("prices", {})} for b in bots}
    meta["heartbeat"] = ahora().strftime("%Y-%m-%d")
    save_json(STATE_FILE, meta)


# ---------- Avisos del estado del propio bot (opcionales) ----------
# AVISOS_ESTADO=1  -> te escribe por Telegram cuando el bot arranca, se detiene (apagado/reinicio/parada del
#                     servicio) y cuando recupera la conexión tras un rato sin poder consultar.
# HEALTHCHECK_URL  -> cada minuto "late" a un vigilante externo (p. ej. healthchecks.io). Si dejan de llegar
#                     latidos (corte de luz, Raspberry colgada, sin internet...) ese servicio te avisa.
#                     Es lo único que detecta un apagón de verdad, porque una Raspberry apagada no puede escribir.
AVISOS_ESTADO = os.environ.get("AVISOS_ESTADO", "0") == "1"
HEALTHCHECK_URL = os.environ.get("HEALTHCHECK_URL", "").strip()
ALIVE_FILE = Path(__file__).resolve().parent / ".alive"  # fuera de data/: git no lo toca
_estado = {"parado": False, "ultimo_ok": time.time(), "ping": 0.0}


def _dur(seg):
    m = int(seg // 60)
    if m < 1:
        return "menos de 1 min"
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} h {m} min" if m else f"{h} h"
    return f"{h // 24} días"


def marcar_vivo():
    try:
        ALIVE_FILE.write_text(str(int(time.time())))
    except OSError:
        pass


def latido():
    """Se llama en cada vuelta: apunta que sigue vivo y avisa al vigilante externo (máx. 1 vez por minuto)."""
    marcar_vivo()
    if HEALTHCHECK_URL and time.time() - _estado["ping"] >= 60:
        _estado["ping"] = time.time()
        try:
            requests.get(HEALTHCHECK_URL, timeout=10)
        except Exception as e:
            print("Aviso healthcheck:", e)


def aviso_arranque():
    """Al arrancar: dice si estuvo parado (corte de luz, reinicio...) y cuánto, según la última vez que latió."""
    try:
        prev = int(ALIVE_FILE.read_text())
    except (OSError, ValueError):
        prev = None
    marcar_vivo()
    if not AVISOS_ESTADO:
        return
    if prev and time.time() - prev > 180:
        desde = datetime.fromtimestamp(prev, ZoneInfo("Europe/Madrid")).strftime("%d/%m %H:%M")
        send(f"🟢 <b>Bot en marcha de nuevo</b>\n⚠️ Estuvo sin funcionar unos <b>{_dur(time.time() - prev)}</b> "
             f"(desde el {desde}).")
    else:
        send("🟢 <b>Bot en marcha</b>")


def _al_parar(signum, frame):
    """SIGTERM = apagado o reinicio de la Raspberry, o 'systemctl stop/restart'."""
    if AVISOS_ESTADO and not _estado["parado"]:
        _estado["parado"] = True
        marcar_vivo()
        send("🔴 <b>Bot detenido</b> (apagado o reinicio de la Raspberry, o parada del servicio).")
    raise SystemExit(0)


def aviso_conexion(ok, err):
    """Si llevaba rato sin poder consultar nada (se cayó internet) y vuelve a funcionar, lo cuenta."""
    if not (ok or not err):  # vuelta fallida
        return
    sin = time.time() - _estado["ultimo_ok"]
    if AVISOS_ESTADO and sin > 300:
        send(f"✅ <b>Conexión recuperada</b>: llevaba unos {_dur(sin)} sin poder consultar Wallapop ni Vinted.")
    _estado["ultimo_ok"] = time.time()


STATE_PUSH_EVERY = int(os.environ.get("STATE_PUSH_EVERY", "900") or 900)
_estado_sub = {"hash": ""}


def subir_estado():
    """Copia data/state.json al repo por la API de GitHub (la misma vía que config.json y results.json).

    Antes se hacía 'git commit' + 'git push' desde la máquina: sin credenciales de git (Raspberry) el push
    fallaba y se acumulaban commits locales sin subir. Por la API solo hace falta el GITHUB_TOKEN que el bot ya
    usa, no se crean commits locales y no hay conflictos al hacer 'git pull'."""
    if not (REPO and GH_TOKEN):
        return  # modo local sin GitHub: el estado queda solo en data/state.json
    try:
        txt = STATE_FILE.read_text(encoding="utf-8")
        h = hashlib.md5(txt.encode()).hexdigest()
        if h == _estado_sub["hash"]:
            return  # nada nuevo desde la última subida
        sha = leer_json_repo("data/state.json", None)[1]
        escribir_json_repo("data/state.json", json.loads(txt), sha)
        _estado_sub["hash"] = h
    except Exception as e:
        print("Aviso al subir el estado a GitHub:", e)


# ---------- Bots rápidos ----------
# Los bots marcados como rápidos (⚡) se revisan cada FAST_INTERVAL segundos en lugar de cada CHECK_INTERVAL.
# Esas vueltas rápidas solo hacen lo imprescindible (no releen la configuración ni las estadísticas). Si la
# plataforma empieza a rechazar peticiones, el ritmo se frena solo (hasta 60 s) y se recupera cuando se calma.
FAST_INTERVAL = max(1.0, float(os.environ.get("FAST_INTERVAL", "3") or 3))
_rapido = {"int": FAST_INTERVAL, "buenos": 0, "avisado": False}


def iteracion_rapida(bots, meta):
    ok, err = comprobar_bots(bots, meta, solo_rapidos=True)
    if RES["new"]:  # solo se escribe cuando hay algo nuevo
        guardar(bots, meta)
        try:
            guardar_recientes(bots)
        except Exception as e:
            print("Aviso al guardar novedades:", e)
    return ok, err


def ajustar_rapido(ok, err):
    r = _rapido
    if err:
        r["int"] = min(r["int"] * 2, 60)
        r["buenos"] = 0
        if not r["avisado"]:
            r["avisado"] = True
            send(f"⚠️ <b>Bots rápidos más lentos</b>: la plataforma está rechazando peticiones, así que los reviso "
                 f"cada {r['int']:.0f} s hasta que se calme.")
    else:
        r["buenos"] += 1
        if r["buenos"] >= 30 and r["int"] > FAST_INTERVAL:
            r["int"] = max(FAST_INTERVAL, r["int"] / 2)
            r["buenos"] = 0
            if r["int"] <= FAST_INTERVAL and r["avisado"]:
                r["avisado"] = False
                send("✅ Los bots rápidos vuelven a su ritmo.")


def iteracion(bots, meta):
    if not _stats_ctl["cargadas"]:
        cargar_stats()
    remota, sha = leer_config()
    bots[:] = fusionar(remota, meta)
    procesar_updates(bots, meta)
    ok, err = comprobar_bots(bots, meta)
    if cfg_of(bots) != remota:  # cambios hechos por Telegram -> al repo
        escribir_config(cfg_of(bots), sha)
    guardar(bots, meta)
    try:
        guardar_recientes(bots)
    except Exception as e:
        print("Aviso al guardar novedades:", e)
    try:
        actualizar_stats(bots)
    except Exception as e:
        print("Aviso en estadísticas:", e)
    return ok, err


def main():
    if not TOKEN or not CHAT_ID:
        raise SystemExit("Faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID")
    meta = load_json(STATE_FILE, {})
    # El "offset" de Telegram es propio de cada bot. Si este estado venía de otro bot (por ejemplo, al copiar
    # el repo de otra persona), se reinicia para no ignorar los mensajes del bot nuevo.
    huella = hashlib.md5(TOKEN.encode()).hexdigest()[:8]
    if meta.get("tg") not in (None, huella):
        print("El estado guardado es de otro bot de Telegram: reinicio el offset.")
        meta["offset"] = 0
    meta["tg"] = huella
    bots = []
    if LOOP_SECONDS <= 0:
        iteracion(bots, meta)
        return

    print(f"Modo bucle: {LOOP_SECONDS}s, cada {CHECK_INTERVAL}s (bots rápidos: cada {FAST_INTERVAL:g}s)")
    signal.signal(signal.SIGTERM, _al_parar)
    aviso_arranque()
    fin = time.time() + LOOP_SECONDS
    ultimo_sub = time.time()
    proximo_normal = 0.0
    bloqueado = False
    try:
        while time.time() < fin:
            t0 = time.time()
            if t0 >= proximo_normal:  # vuelta normal: todos los bots, config, estadísticas...
                try:
                    ok, err = iteracion(bots, meta)
                except Exception as e:
                    print("Error en iteración:", e)
                    ok, err = 0, 1
                latido()
                aviso_conexion(ok, err)
                if time.time() - ultimo_sub > STATE_PUSH_EVERY:
                    subir_estado()
                    ultimo_sub = time.time()
                bloqueado = bool(err and not ok)
                proximo_normal = t0 + (60 if bloqueado else CHECK_INTERVAL)
            else:  # vuelta rápida: solo los bots ⚡
                try:
                    ok, err = iteracion_rapida(bots, meta)
                except Exception as e:
                    print("Error en vuelta rápida:", e)
                    ok, err = 0, 1
                ajustar_rapido(ok, err)
            siguiente = proximo_normal
            if not bloqueado and any(b.get("fast") and b["status"] == "running" for b in bots):
                siguiente = min(proximo_normal, t0 + _rapido["int"])
            try:
                esperar_comandos(bots, meta, min(siguiente, fin))
            except Exception as e:
                print("Error escuchando Telegram:", e)
                time.sleep(5)
    except SystemExit:  # parada ordenada: se guarda el estado para no repetir avisos al volver
        try:
            guardar(bots, meta)
            subir_estado()
        except Exception as e:
            print("Aviso al guardar al parar:", e)
        raise
    guardar(bots, meta)
    subir_estado()


_RX_TIEMPO = re.compile(r"date|time|creat|publi|modif|updat|_at$|^ts$|_ts$|fecha|hora|age$", re.I)


def _campos_tiempo(obj, ruta="", prof=0, out=None):
    out = [] if out is None else out
    if prof > 4:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            r = f"{ruta}.{k}" if ruta else str(k)
            if isinstance(v, (dict, list)):
                _campos_tiempo(v, r, prof + 1, out)
            elif _RX_TIEMPO.search(str(k)):
                out.append((r, v))
    elif isinstance(obj, list) and obj:
        _campos_tiempo(obj[0], ruta + "[0]", prof + 1, out)
    return out


def campos(texto):
    """python check.py --campos "layton": para los primeros anuncios de cada plataforma enseña los campos de TIEMPO
    que trae la respuesta y cuál se usa como hora de publicación (para saber si se puede medir el retraso)."""
    for nombre, fn in (("Wallapop", _wallapop_items), ("Vinted", _vinted_items)):
        print(f"\n===== {nombre} =====")
        try:
            items = fn(texto, 0, SIN_LIMITE)
        except Exception as e:
            print("  error:", e)
            continue
        print(f"  {len(items)} anuncios recibidos")
        for it in items[:4]:
            c = it.get("content", it) if isinstance(it, dict) else {}
            print("\n  •", str(c.get("title", ""))[:60])
            for ruta, v in _campos_tiempo(it):
                t = _epoch(v)
                print(f"      {ruta} = {str(v)[:40]}" + (f"   → hace {_edad(time.time() - t)}" if t else ""))
            pub, pk = hora_pub(c)
            if not pub:
                pub, pk = hora_pub(it)
            print("      ⇒ hora de publicación que se usaría:",
                  f"{pk} (hace {_edad(time.time() - pub)})" if pub else "NINGUNA (no hay un campo reconocible)")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--campos":
        campos(" ".join(sys.argv[2:]))
    else:
        main()
