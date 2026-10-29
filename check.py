"""
Wallapop bots - versión "serverless" para GitHub Actions.

Cada ejecución (cada ~5 min, lanzada por el cron de GitHub):
  1. Lee los mensajes pendientes de Telegram y aplica los comandos (crear, pausar, borrar...).
  2. Comprueba en Wallapop cada bot activo y avisa por Telegram de lo nuevo.
  3. Guarda el estado en data/*.json (el workflow lo sube al repo).

Variables de entorno necesarias (GitHub Secrets):
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""
import hashlib
import html
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0") or 0)
API = f"https://api.telegram.org/bot{TOKEN}"

DATA_DIR = Path("data")
BOTS_FILE = DATA_DIR / "bots.json"
META_FILE = DATA_DIR / "meta.json"

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
def tg(method, **params):
    try:
        r = requests.post(f"{API}/{method}", json=params, timeout=20)
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


def bot_text(b):
    emoji = {"running": "▶️", "paused": "⏸"}.get(b["status"], "❓")
    return (
        f"🤖 <b>{esc(b['keywords'])}</b>\n"
        f"💰 {b['min_price']}€ – {fmt_max(b['max_price'])}\n"
        f"Estado: {emoji} {b['status']}"
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
    for u in res.get("result", []):
        meta["offset"] = u["update_id"] + 1
        try:
            if "message" in u:
                on_message(u["message"], bots)
            elif "callback_query" in u:
                on_callback(u["callback_query"], bots)
        except Exception as e:
            print("Error procesando update:", e)


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


def generar_key(nombre, precio):
    return hashlib.md5(f"{nombre}-{precio}".encode()).hexdigest()


def buscar(keywords, min_price, max_price):
    """Lanza excepción si la API falla (así no confundimos 'error' con 'sin resultados')."""
    params = {
        "keywords": keywords,
        "order_by": ORDER_BY,
        "language": "es_ES",
        "filters_source": "default_filters",
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
            if resp.status_code == 404:
                continue  # probamos el siguiente endpoint
            raise
    if data is None:
        raise ultimo_error

    items = extraer_items(data)
    if not items:
        print("Respuesta sin anuncios. Claves:", list(data.keys())[:10], "->", str(data)[:300])

    resultados = []
    for item in items:
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
        resultados.append({
            "nombre": titulo,
            "precio": precio,
            "enlace": f"https://es.wallapop.com/item/{slug}",
        })
    return resultados


def bloque(i, r):
    return f"{i}. 💰 {r['precio']:.2f}€\n📝 {esc(r['nombre'])}\n🔗 {r['enlace']}\n\n"


def comprobar_bots(bots, meta):
    activos = [b for b in bots if b["status"] == "running"]
    errores, ok = [], 0
    ts = ahora().strftime("%d/%m - %H:%M")

    for b in activos:
        try:
            resultados = buscar(b["keywords"], b["min_price"], b["max_price"])
        except Exception as e:
            print(f"[{b['keywords']}] Error: {e}")
            errores.append(f"{b['keywords']}: {e}")
            continue  # no tocamos el estado si falla
        ok += 1

        actuales = {generar_key(r["nombre"], r["precio"]) for r in resultados}
        vistos = set(b.get("seen", []))
        nuevos = [r for r in resultados if generar_key(r["nombre"], r["precio"]) not in vistos]
        b["seen"] = sorted(actuales)

        if not b.get("first_done"):
            b["first_done"] = True
            if resultados:
                send_blocks(
                    f"🔵 <b>Primera comprobación</b> — <i>{esc(b['keywords'])}</i>\n\n",
                    [bloque(i, r) for i, r in enumerate(resultados, 1)],
                )
            else:
                send(f"🔴 Sin resultados para <b>{esc(b['keywords'])}</b>")
        elif nuevos:
            send_blocks(
                f"🆕 <b>NUEVOS</b> — <i>{esc(b['keywords'])}</i>\n📅 {ts}\n\n",
                [bloque(i, r) for i, r in enumerate(nuevos, 1)],
            )
        print(f"[{b['keywords']}] resultados={len(resultados)} nuevos={len(nuevos)}")

    # Aviso (una sola vez) si Wallapop bloquea las peticiones desde GitHub
    if activos and ok == 0 and errores:
        if not meta.get("bloqueado"):
            meta["bloqueado"] = True
            send("⚠️ <b>No consigo consultar Wallapop</b> (posible bloqueo/limitación).\n"
                 f"<code>{esc(errores[0][:300])}</code>")
    elif ok > 0 and meta.get("bloqueado"):
        meta["bloqueado"] = False
        send("✅ Wallapop vuelve a responder.")


# ======================
# MAIN
# ======================
def main():
    if not TOKEN or not CHAT_ID:
        raise SystemExit("Faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID")

    bots = load_json(BOTS_FILE, [])
    meta = load_json(META_FILE, {})

    procesar_updates(bots, meta)
    comprobar_bots(bots, meta)

    # Un cambio al día para que el repo siga "activo" y GitHub no desactive el cron
    meta["heartbeat"] = ahora().strftime("%Y-%m-%d")

    save_json(BOTS_FILE, bots)
    save_json(META_FILE, meta)


if __name__ == "__main__":
    main()
