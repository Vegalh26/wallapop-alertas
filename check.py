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
import subprocess
import time
import uuid
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
CFG_KEYS = ("id", "keywords", "min_price", "max_price", "status", "source")
FUENTES = ("wallapop", "vinted", "ambos")
VINTED_TLD = os.environ.get("VINTED_TLD", "es")

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
# LOOP_SECONDS > 0  -> la ejecución se queda en bucle ese tiempo, comprobando cada CHECK_INTERVAL s.
# LOOP_SECONDS = 0  -> una sola comprobación y termina.
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


def generar_key(nombre, precio, plat="Wallapop"):
    pre = "" if plat == "Wallapop" else plat + "|"  # las claves de Wallapop no cambian
    return hashlib.md5(f"{pre}{nombre}-{precio}".encode()).hexdigest()


def key_de(r):
    return generar_key(r["nombre"], r["precio"], r.get("plat", "Wallapop"))


def buscar(keywords, min_price, max_price):
    """Lanza excepción si la API falla (así no confundimos 'error' con 'sin resultados')."""
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
            "plat": "Wallapop",
            "img": _primera_url(content.get("images")),
        })
    return resultados


# ---------- VINTED ----------
_vinted = {"s": None, "t": 0}


def _vinted_sesion():
    if _vinted["s"] and time.time() - _vinted["t"] < 1800:
        return _vinted["s"]
    s = requests.Session()
    s.headers.update({"User-Agent": HEADERS["User-Agent"], "Accept-Language": "es-ES,es;q=0.9"})
    r = s.get(f"https://www.vinted.{VINTED_TLD}/", timeout=20)
    r.raise_for_status()
    s.anon = r.headers.get("X-Anon-Id", "")
    _vinted.update(s=s, t=time.time())
    return s


def buscar_vinted(keywords, min_price, max_price):
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
    items = _buscar_lista_items(resp.json())

    out = []
    for it in items:
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
        out.append({"nombre": titulo, "precio": precio, "plat": "Vinted", "enlace": enlace,
                    "img": _primera_url(it.get("photo"))})
    return out


def bloque(i, r):
    ic = "🟣 Vinted" if r.get("plat") == "Vinted" else "🟢 Wallapop"
    return f"{i}. {ic} · 💰 {r['precio']:.2f}€\n📝 {esc(r['nombre'])}\n🔗 {r['enlace']}\n\n"


def comprobar_bots(bots, meta):
    activos = [b for b in bots if b["status"] == "running"]
    ok = 0
    n_err = 0
    stats = {"Wallapop": [0, 0, ""], "Vinted": [0, 0, ""]}  # ok, fallos, último error
    ts = ahora().strftime("%d/%m - %H:%M")

    for b in activos:
        fuente = b.get("source", "ambos")
        pedidos = [(n, f) for n, f, fu in (("Wallapop", buscar, ("wallapop", "ambos")),
                                           ("Vinted", buscar_vinted, ("vinted", "ambos"))) if fuente in fu]
        resultados, fallos = [], 0
        for nombre, fn in pedidos:
            try:
                resultados += fn(b["keywords"], b["min_price"], b["max_price"])
                stats[nombre][0] += 1
            except Exception as e:
                print(f"[{b['keywords']}] Error {nombre}: {e}")
                stats[nombre][1] += 1
                stats[nombre][2] = str(e)
                fallos += 1
                n_err += 1
        if fallos == len(pedidos):
            continue  # todo falló: no tocamos el estado
        ok += 1

        previos = b.get("seen", [])
        vistos = set(previos)
        nuevos = [r for r in resultados if key_de(r) not in vistos]
        # Nunca olvidamos lo ya avisado (los resultados "bailan" entre peticiones): sin duplicados
        añadir = list(dict.fromkeys(key_de(r) for r in nuevos))
        b["seen"] = (previos + añadir)[-2000:]

        if not b.get("first_done"):
            b["first_done"] = True
            if resultados:
                registrar(b["keywords"], resultados)
                send_blocks(
                    f"🔵 <b>Primera comprobación</b> — <i>{esc(b['keywords'])}</i>\n\n",
                    [bloque(i, r) for i, r in enumerate(resultados, 1)],
                )
            else:
                send(f"🔴 Sin resultados para <b>{esc(b['keywords'])}</b>")
        elif nuevos:
            registrar(b["keywords"], nuevos)
            send_blocks(
                f"🆕 <b>NUEVOS</b> — <i>{esc(b['keywords'])}</i>\n📅 {ts}\n\n",
                [bloque(i, r) for i, r in enumerate(nuevos, 1)],
            )
        print(f"[{b['keywords']}] resultados={len(resultados)} nuevos={len(nuevos)}")

    # Avisos de bloqueo, una sola vez por plataforma
    for nombre, (o, f, ultimo) in stats.items():
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
        out.append({
            "id": str(c.get("id") or hashlib.md5(kw.encode()).hexdigest()[:8]),
            "keywords": kw,
            "min_price": int(c.get("min_price") or 0),
            "max_price": SIN_LIMITE if mx in (None, "") else int(mx),
            "status": st if st in ("running", "paused") else "running",
            "source": c.get("source") if c.get("source") in FUENTES else "ambos",
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
    txt = json.dumps(obj, ensure_ascii=False, indent=2 if isinstance(obj, list) else None, separators=None if isinstance(obj, list) else (",", ":"))
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


# ---------- Muro de novedades (lo lee el panel web) ----------
RES = {"items": [], "sha": None, "dirty": False}
RES_MAX = 150


def registrar(kw, items):
    t = int(time.time())
    ya = {x["id"] for x in RES["items"]}
    lote = []
    for r in items:
        i = key_de(r)
        if i in ya:
            continue
        ya.add(i)
        lote.append({"id": i, "t": t, "kw": kw, "p": r.get("plat", "Wallapop"), "n": r["nombre"],
                     "pr": r["precio"], "u": r["enlace"], "im": r.get("img", "")})
    if lote:
        RES["items"] = (lote + RES["items"])[:RES_MAX]
        RES["dirty"] = True


def guardar_recientes():
    if RES["dirty"]:
        RES["sha"] = escribir_json_repo("data/results.json", {"items": RES["items"]}, RES["sha"])
        RES["dirty"] = False


def cfg_of(bots):
    return [{k: b[k] for k in CFG_KEYS} for b in bots]


def fusionar(cfg, meta):
    est = meta.get("bots", {})
    return [{**c, "seen": est.get(c["id"], {}).get("seen", []),
             "first_done": est.get(c["id"], {}).get("first_done", False)} for c in cfg]


def guardar(bots, meta):
    meta["bots"] = {b["id"]: {"seen": b.get("seen", []), "first_done": b.get("first_done", False)} for b in bots}
    meta["heartbeat"] = ahora().strftime("%Y-%m-%d")
    save_json(STATE_FILE, meta)


def iteracion(bots, meta):
    remota, sha = leer_config()
    bots[:] = fusionar(remota, meta)
    procesar_updates(bots, meta)
    ok, err = comprobar_bots(bots, meta)
    if cfg_of(bots) != remota:  # cambios hechos por Telegram -> al repo
        escribir_config(cfg_of(bots), sha)
    guardar(bots, meta)
    try:
        guardar_recientes()
    except Exception as e:
        print("Aviso al guardar novedades:", e)
    return ok, err


def main():
    if not TOKEN or not CHAT_ID:
        raise SystemExit("Faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID")
    meta = load_json(STATE_FILE, {})
    bots = []
    try:
        d, RES["sha"] = leer_json_repo("data/results.json", {"items": []})
        RES["items"] = (d or {}).get("items", [])
    except Exception as e:
        print("Aviso al leer novedades:", e)
    if LOOP_SECONDS <= 0:
        iteracion(bots, meta)
        return
    print(f"Modo bucle: {LOOP_SECONDS}s, cada {CHECK_INTERVAL}s")
    fin = time.time() + LOOP_SECONDS
    ultimo_git = time.time()
    while time.time() < fin:
        t0 = time.time()
        try:
            ok, err = iteracion(bots, meta)
        except Exception as e:
            print("Error en iteración:", e)
            ok, err = 0, 1
        if time.time() - ultimo_git > 600:
            git_guardar()
            ultimo_git = time.time()
        pausa = 60 if (err and not ok) else CHECK_INTERVAL
        try:
            esperar_comandos(bots, meta, min(t0 + pausa, fin))
        except Exception as e:
            print("Error escuchando Telegram:", e)
            time.sleep(5)
    guardar(bots, meta)


if __name__ == "__main__":
    main()
