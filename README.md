# 🤖 Wallapop Bots

Alertas de **Wallapop** y **Vinted** en tu Telegram, con un panel web para gestionarlas.
Le dices qué buscas (por ejemplo *"layton"*, entre 0 y 25 €) y el bot te avisa en cuanto sale un anuncio nuevo.

- 🔎 Busca en Wallapop, en Vinted o en las dos a la vez.
- 💰 Filtro de precio mínimo y máximo.
- 🌐 Filtro de **idioma**: ver solo los anuncios en un idioma, o excluir idiomas (por ejemplo, no quiero la versión italiana ni la francesa).
- 🚫 **Palabras excluidas**: ignora los anuncios que contengan las palabras que tú elijas ("solo caja", "réplica"...).
- 📱 Panel web (también se instala como app en el móvil) para crear, editar, pausar y borrar bots.
- ✨ **Novedades**: un muro con foto, precio y plataforma de cada anuncio encontrado, con marca de **vendido / reservado / no disponible** y opción de quitar anuncios a mano.
- 🗄 Cuando borras un bot, sus anuncios pasan a **Archivados** (no se pierden).
- 💬 También se maneja desde Telegram: `/bots`, `/nuevo`.

> **Importante:** esto no es un producto oficial. Usa las mismas direcciones que usan las webs de Wallapop y Vinted,
> que pueden cambiar o limitar el acceso sin avisar. Es para **uso personal**. Úsalo con cabeza
> (no bajes el intervalo de comprobación a cifras absurdas) y respeta los términos de ambas plataformas.

---

## Índice

1. [Cómo funciona](#cómo-funciona)
2. [Lo que necesitas](#lo-que-necesitas)
3. [Paso 1 · Copia el repositorio](#paso-1--copia-el-repositorio)
4. [Paso 2 · Crea tu bot de Telegram](#paso-2--crea-tu-bot-de-telegram)
5. [Paso 3 · Crea un token de GitHub](#paso-3--crea-un-token-de-github)
6. [Paso 4 · Elige dónde se ejecuta](#paso-4--elige-dónde-se-ejecuta)
   - [Opción A · GitHub Actions](#opción-a--github-actions)
   - [Opción B · Raspberry Pi, PC o servidor propio](#opción-b--raspberry-pi-pc-o-servidor-propio)
7. [Paso 5 · Activa el panel web](#paso-5--activa-el-panel-web)
8. [Cómo se usa](#cómo-se-usa)
9. [Variables de configuración](#variables-de-configuración)
10. [Problemas frecuentes](#problemas-frecuentes)
11. [Privacidad y seguridad](#privacidad-y-seguridad)
12. [Estructura del repositorio](#estructura-del-repositorio)

---

## Cómo funciona

```
 ┌────────────┐   crea / pausa / borra bots    ┌──────────────────────┐
 │ Panel web  │ ─────────────────────────────▶ │  tu repositorio      │
 │ (docs/)    │ ◀───────────────────────────── │  data/config.json    │
 └────────────┘      lee Novedades             │  data/results.json   │
                                               └──────────┬───────────┘
 ┌────────────┐   /nuevo, /bots, botones                  │ lee la config
 │ Telegram   │ ◀──────────────┐                          ▼ y guarda novedades
 └────────────┘                │                ┌──────────────────────┐
                               └─────────────── │  check.py (el bot)   │ ── busca en Wallapop y Vinted
                                  avisos        │  en bucle, cada ~30 s│
                                                └──────────────────────┘
```

- **`check.py`** es el bot. Cada pocos segundos lee tu configuración, busca en Wallapop y Vinted,
  descarta lo que no cumple tus filtros y te avisa por Telegram de lo nuevo.
- **El repositorio hace de base de datos.** El panel y el bot comparten `data/config.json` (tus bots) y
  `data/results.json` (el muro de Novedades) a través de la API de GitHub.
- **El panel (`docs/index.html`)** es una sola página web sin servidor: se publica gratis con GitHub Pages.

El bot puede ejecutarse en **GitHub Actions** (sin tener ningún aparato en casa) o en **tu propia máquina**
(Raspberry Pi, PC, servidor...). Más abajo se explican las dos.

---

## Lo que necesitas

- Una cuenta de **GitHub** (gratis).
- **Telegram** en el móvil.
- Opcional, para la opción B: una Raspberry Pi, un PC que esté siempre encendido o un servidor con Python 3.9 o superior.

No hace falta saber programar, pero sí copiar y pegar algunos comandos.

---

## Paso 1 · Copia el repositorio

Entra en la página del repositorio y pulsa **Fork** (arriba a la derecha) para tener tu propia copia en tu cuenta.
Es importante que la copia esté **a tu nombre**: el panel solo deja entrar con un token del dueño del repositorio.

### ⚠️ Vacía los datos de ejemplo

La carpeta `data/` trae datos de otra persona (sus bots, sus anuncios y el estado de su Telegram).
**Bórrala entera antes de empezar**, o recibirías avisos de búsquedas que no son tuyas:

1. En tu copia, abre la carpeta `data/`.
2. Abre cada archivo (`config.json`, `results.json`, `state.json`), pulsa el icono de la papelera 🗑 y confirma con **Commit changes**.

El bot y el panel recrean esos archivos solos. (Si ya sabes usar git, basta con borrarlos y hacer commit.)

---

## Paso 2 · Crea tu bot de Telegram

1. En Telegram busca **@BotFather** y escribe `/newbot`.
2. Elige un nombre y un usuario que termine en `bot`.
3. BotFather te da un **token** parecido a `123456789:AAH...`. Guárdalo: es tu `TELEGRAM_TOKEN`.
   Si lo pierdes, escribe `/mybots`, elige tu bot y pulsa *API Token*.
4. Busca tu bot por su usuario y pulsa **Iniciar** (o escríbele cualquier cosa).
5. Averigua **tu id de chat**: busca el bot **@userinfobot**, pulsa *Start* y te responde con tu `Id`.
   Ese número es tu `TELEGRAM_CHAT_ID`.

> El bot **solo obedece a tu id de chat**. Si otra persona le escribe, responde que no tiene permiso.

---

## Paso 3 · Crea un token de GitHub

El panel (y el bot, si lo ejecutas fuera de GitHub) necesitan un token para leer y escribir en tu repositorio.

1. En GitHub: tu foto › **Settings** › **Developer settings** › **Personal access tokens** › **Fine-grained tokens** › **Generate new token**.
2. *Repository access*: **Only select repositories** y elige tu copia (`wallapop-alertas`).
3. *Permissions* › *Repository permissions* › **Contents: Read and write**.
4. Genera el token y **cópialo** (solo se muestra una vez).

Pon la caducidad que prefieras; cuando caduque tendrás que crear otro y volver a entrar en el panel.

---

## Paso 4 · Elige dónde se ejecuta

### Opción A · GitHub Actions

Es la más cómoda: no necesitas ningún aparato. El flujo de trabajo (`.github/workflows/wallapop.yml`) ejecuta el bot en bucle
y se relevan unas a otras cada pocas horas.

1. En tu copia, ve a **Settings** › **Secrets and variables** › **Actions** › **New repository secret** y crea dos:
   - `TELEGRAM_TOKEN` → el token de BotFather.
   - `TELEGRAM_CHAT_ID` → tu id de chat.
2. Ve a la pestaña **Actions**. En las copias (forks) los flujos vienen desactivados: pulsa
   **"I understand my workflows, go ahead and enable them"**.
3. Abre el flujo **wallapop** y pulsa **Run workflow** para arrancarlo ya. Después se relanza solo.

> ⚠️ **Límites de GitHub.** Este flujo mantiene una máquina de GitHub encendida casi las 24 horas.
> En repositorios **públicos** los minutos de Actions no se cobran, pero GitHub puede limitar o bloquear un uso tan continuo.
> En repositorios **privados** los minutos gratuitos (unos 2000 al mes) se agotan en pocos días.
> Si te pasa, o prefieres no depender de GitHub, usa la opción B.

### Opción B · Raspberry Pi, PC o servidor propio

El bot necesita muy poca memoria (unos 70 MB medidos en una Raspberry Pi, más si usas el detector de idioma opcional)
y funciona en cualquier sistema con Python. La IP de tu casa suele llevarse mejor con Wallapop y Vinted que la de un servidor en la nube.

Estos pasos son para Linux o Raspberry Pi OS. En Windows o Mac es igual, pero los comandos de activación cambian un poco.

**1. Descargar e instalar**

```bash
sudo apt update && sudo apt install -y git python3-venv
git clone https://github.com/TU_USUARIO/wallapop-alertas.git
cd wallapop-alertas
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

> `requirements.txt` incluye `lingua-language-detector`, un detector de idioma **opcional** que ocupa bastante.
> Si tu equipo va justo de memoria, quítalo con `./venv/bin/pip uninstall -y lingua-language-detector`:
> el filtro de idioma sigue funcionando con las listas de palabras.

**2. Guardar tus claves** en un archivo fuera del repositorio:

```bash
nano ~/wallapop.env
```
```
TELEGRAM_TOKEN=el_token_de_botfather
TELEGRAM_CHAT_ID=tu_id_de_chat
GITHUB_REPOSITORY=TU_USUARIO/wallapop-alertas
GITHUB_TOKEN=el_token_personal_del_paso_3
LOOP_SECONDS=31536000
CHECK_INTERVAL=30
GIT_TERMINAL_PROMPT=0
```
```bash
chmod 600 ~/wallapop.env
```

**3. Probarlo a mano**

```bash
set -a; . ~/wallapop.env; set +a
./venv/bin/python -u check.py
```
Deberías ver líneas como `Modo bucle: ...` y `[layton] resultados=7 nuevos=0`. Para pararlo, `Ctrl+C`.

**4. Dejarlo como servicio** (arranca solo al encender y se reinicia si falla). Cambia `TU_USUARIO_LINUX` por tu usuario del sistema:

```bash
sudo nano /etc/systemd/system/wallapop.service
```
```ini
[Unit]
Description=Wallapop alertas
After=network-online.target
Wants=network-online.target

[Service]
User=TU_USUARIO_LINUX
WorkingDirectory=/home/TU_USUARIO_LINUX/wallapop-alertas
EnvironmentFile=/home/TU_USUARIO_LINUX/wallapop.env
ExecStart=/home/TU_USUARIO_LINUX/wallapop-alertas/venv/bin/python -u check.py
Restart=always
RestartSec=20

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wallapop
journalctl -u wallapop -f        # ver el registro en vivo (Ctrl+C para salir)
```

Comandos útiles: `sudo systemctl restart wallapop` (tras cambiar algo), `sudo systemctl stop wallapop` y `systemctl status wallapop`.

**5. Actualizar el bot** cuando haya cambios en el código:

```bash
cd ~/wallapop-alertas
git pull --rebase --autostash
./venv/bin/pip install -r requirements.txt
sudo systemctl restart wallapop
```

> **Usa solo UNA de las dos opciones a la vez.** Si ejecutas el bot en tu Raspberry y además tienes activo el flujo
> de GitHub Actions, recibirás los avisos duplicados. Si te pasas a la opción B, desactiva el flujo
> (**Actions** › *wallapop* › **⋯** › **Disable workflow**).

---

## Paso 5 · Activa el panel web

1. En tu repositorio: **Settings** › **Pages**.
2. *Build and deployment* › *Source*: **Deploy from a branch**.
3. *Branch*: **main** y carpeta **/docs** › **Save**.
4. Espera uno o dos minutos. Tu panel estará en `https://TU_USUARIO.github.io/wallapop-alertas/`.

La primera vez que entres te pide:

- **Repo**: `TU_USUARIO/wallapop-alertas`.
- **Token de GitHub**: el del paso 3.
- **Un PIN** (4 o más caracteres): cifra el token en tu dispositivo, de modo que no se guarda en claro.

Desde el móvil puedes añadirlo a la pantalla de inicio y se comporta como una app.
El panel se bloquea solo tras 2 horas sin usarlo, y si fallas el PIN 5 veces borra el acceso guardado en ese dispositivo.

---

## Cómo se usa

### Crear un bot

En el panel, **Mis bots** › rellena el formulario:

| Campo | Qué hace |
|---|---|
| **Qué buscas** | El texto de la búsqueda. El título del anuncio debe contenerlo. |
| **Mín € / Máx €** | Rango de precio. Un máximo de `1000` significa *sin límite*. |
| **Dónde buscar** | Ambas, solo Wallapop o solo Vinted. |
| **Idioma** | *Todos* (sin filtro), *Excluir* (descarta los idiomas elegidos) o *Solo* (deja los de ese idioma). |
| **Excluir palabras** | Lista separada por comas. Ver abajo. |

Los cambios se aplican en segundos. Cada bot se puede **editar**, **pausar** o **borrar**.

### Filtro de idioma

Ni Wallapop ni Vinted indican el idioma de un juego o libro, así que se deduce del texto del anuncio:
palabras que no existen en español (*professeur*, *gioco*, *und*...), apóstrofos tipo *l'héritage* y, si está instalado, un detector estadístico.

- En *Excluir* se descartan los anuncios que parezcan estar en los idiomas marcados.
- En *Solo* se descartan los que parezcan estar en **otro** idioma; los que no dan ninguna pista se mantienen (si no, perderías casi todos los anuncios en español, que no suelen decirlo).
- Es una **aproximación**: un título en inglés de un juego que se vende igual en España puede colarse, y una descripción rara puede confundir al detector.
  Con el filtro activo, cada aviso de Telegram indica el idioma detectado y cada tarjeta del panel lleva su bandera (o *sin detectar*), para que veas qué ha pensado el filtro.

### Palabras excluidas

Si el **título o la descripción** contienen alguna de las palabras, el anuncio se ignora.

- Separa con comas: `solo caja, funda*, réplica`.
- No distingue mayúsculas ni acentos: `réplica` también descarta *REPLICA*.
- Una **frase** debe aparecer tal cual: `solo caja` descarta *"solo caja"*, pero no *"solo la caja"*.
- Un **`*` al final** cubre variantes: `caja*` descarta *caja*, *cajas*, *cajita*...
- Se buscan palabras completas: `caja` no descarta *"cajón"*.

### Novedades, vendidos y archivados

La pestaña **Novedades** muestra los anuncios que ha ido encontrando el bot.

- **NUEVO**: etiqueta de los últimos 10 minutos.
- **Vendido / No disponible / Reservado**: el bot vuelve a mirar cada anuncio de vez en cuando (como máximo cada 15 minutos por anuncio, durante 45 días)
  y marca el estado. Los vendidos salen en gris con la etiqueta; **no se borran solos**.
  En el menú **⋯** puedes *ocultar* o *borrar* los vendidos de golpe.
  - Wallapop: solo se pueden vigilar los anuncios encontrados **a partir de ahora**. Los guardados antes de esta función no tienen el dato necesario.
  - Si no se entiende la respuesta de la plataforma, el estado **no se toca**.
- **🗑 en cada tarjeta**: quita ese anuncio de Novedades. El bot no volverá a avisarte de él.
- **⋯ (arriba a la derecha)**: *Vaciar* un bot concreto, vaciar todo, o los archivados.
- Si **editas** un bot (precio, plataformas, idioma o palabras excluidas), sus anuncios antiguos siguen bajo el mismo nombre,
  pero separados en una sección *"bot anterior"* con la configuración que tenía.
- **Archivados**: al borrar un bot, sus anuncios van aquí, agrupados por bot. Si más tarde creas otro bot con el mismo nombre, vuelven a Novedades.

### Telegram

| Comando | Qué hace |
|---|---|
| `/start`, `/ayuda` | Muestra la ayuda. |
| `/bots` | Lista tus bots con botones para pausar, reanudar o borrar. |
| `/nuevo mario party 0 30` | Crea un bot (palabras, precio mínimo y máximo). `/nuevo jamboree 25` pone solo el máximo. |

Los filtros de idioma y las palabras excluidas se configuran desde el panel.

### Comprobar que detecta los vendidos

Wallapop y Vinted pueden cambiar sus respuestas. Para ver qué entiende el bot ahora mismo:

```bash
set -a; . ~/wallapop.env; set +a        # carga tus claves (opción B)
./venv/bin/python check.py --probar layton
```

Muestra, para unos anuncios de muestra, el estado detectado y las banderas que ha leído (`sold`, `reserved`...).
Si en `banderas=` aparece *ninguna reconocida*, la plataforma ha cambiado su formato y habrá que adaptar `estado_de_json()`.
Puedes apagar esta función con `CHECK_VENDIDOS=0`.

---

## Variables de configuración

Se definen como *secrets* (Actions) o en `~/wallapop.env` (opción B).

| Variable | Obligatoria | Por defecto | Qué hace |
|---|---|---|---|
| `TELEGRAM_TOKEN` | ✅ | | Token de tu bot (BotFather). |
| `TELEGRAM_CHAT_ID` | ✅ | | Tu id de chat. Solo este usuario puede mandar órdenes. |
| `GITHUB_REPOSITORY` | opción B | | `usuario/repositorio`. En Actions lo pone GitHub. |
| `GITHUB_TOKEN` | opción B | | Token personal con *Contents: Read and write*. En Actions lo pone GitHub. |
| `LOOP_SECONDS` | | `0` | Cuánto tiempo se queda en bucle. `0` = una sola comprobación y sale. |
| `CHECK_INTERVAL` | | `10` | Segundos entre comprobaciones. Recomendado: `30` o más. |
| `WALLAPOP_LAT`, `WALLAPOP_LON` | | Madrid | Coordenadas de referencia de la búsqueda en Wallapop. |
| `VINTED_TLD` | | `es` | Dominio de Vinted (`es`, `fr`, `it`, `de`...). |
| `CHECK_VENDIDOS` | | `1` | `0` desactiva la vigilancia de vendidos. |
| `VENDIDOS_CADA` | | `900` | Segundos mínimos entre dos consultas del mismo anuncio. |
| `VENDIDOS_POR_CICLO` | | `4` | Anuncios que se consultan en cada vuelta. |

Los enlaces de los anuncios de Wallapop apuntan a `es.wallapop.com`; si buscas en otro país tendrás que cambiar ese dominio en `check.py`.

---

## Problemas frecuentes

**No me llega nada a Telegram.**
Comprueba que le has escrito algo a tu bot al menos una vez y que `TELEGRAM_CHAT_ID` es tu id numérico (no el de otro chat).
Mira el registro (`journalctl -u wallapop -f`, o la pestaña *Actions*): si ves `Error Telegram`, el token es incorrecto.

**El bot no responde a `/nuevo` ni a los botones.**
Mira que no haya **dos copias** funcionando a la vez con el mismo bot de Telegram (por ejemplo, Actions y la Raspberry):
se reparten los mensajes. Deja solo una.

**"No puedo acceder a ese repo" o "Este token no es del dueño del repo" al entrar en el panel.**
El repo tiene que estar en **tu** cuenta (haz *Fork*, no solo *Clone*), el token debe ser tuyo y tener *Contents: Read and write* sobre ese repo.

**En los registros aparece `Respuesta sin anuncios`.**
Es normal: significa que Wallapop no devolvió resultados para esa búsqueda en ese momento. Si además hay Vinted, los resultados pueden venir de ahí.

**`No consigo consultar Wallapop` en Telegram.**
Wallapop o Vinted están rechazando las peticiones (límite, bloqueo de IP o cambio de formato). El bot avisa una sola vez y lo vuelve a intentar;
cuando se recupera, te avisa de que vuelve a responder. Si pasa siempre desde un servidor en la nube, prueba desde tu casa.

**Aparece `Aviso git push` o `Aviso git pull` en el registro (opción B).**
Es inofensivo: el bot intenta subir `state.json` y tu máquina no tiene credenciales de escritura de git. El estado se guarda igualmente en local.

**Los cambios del panel no se ven.**
GitHub Pages tarda un par de minutos en publicar. Si usas la app instalada en el móvil, ciérrala del todo y vuelve a abrirla para saltarte la caché.

**Mi cuenta de GitHub dice que Actions está bloqueado por facturación.**
Revisa *Settings › Billing* de tu cuenta. Si no encuentras la causa, escribe a GitHub Support o pasa a la opción B.

---

## Privacidad y seguridad

- Tus bots y los anuncios encontrados viven en `data/config.json` y `data/results.json` de tu repositorio.
  **Si el repositorio es público, cualquiera puede verlos.** Si te importa, hazlo privado y usa la opción B.
  (Las páginas de GitHub Pages para repositorios privados requieren un plan de pago, pero el panel es un único HTML:
  también puedes abrir `docs/index.html` desde tu ordenador.)
- Los tokens de Telegram y de GitHub **nunca van en el repositorio**: se guardan como *secrets* o en `~/wallapop.env`.
  No los pegues en issues, capturas ni mensajes.
- En el panel, el token de GitHub se guarda **cifrado con tu PIN** en el navegador del dispositivo.
- Usa un token de GitHub limitado a **un solo repositorio** y con el único permiso *Contents: Read and write*.

---

## Estructura del repositorio

```
.
├── check.py                    # el bot: búsquedas, filtros, avisos de Telegram, vigilancia de vendidos
├── requirements.txt            # requests (y lingua, opcional, para el detector de idioma)
├── data/
│   ├── config.json             # tus bots (lo escriben el panel y Telegram)
│   ├── results.json            # el muro de Novedades (lo escriben el bot y el panel)
│   └── state.json              # anuncios ya avisados y estado de Telegram (solo el bot)
├── docs/                       # el panel web que publica GitHub Pages
│   ├── index.html
│   ├── manifest.webmanifest
│   └── icon-192.png, icon-512.png
└── .github/workflows/
    └── wallapop.yml            # ejecución en GitHub Actions (opción A)
```

Si cambias algo en `check.py` o en `docs/index.html`, en la opción B reinicia el servicio con `sudo systemctl restart wallapop`;
en la opción A, GitHub lo recoge en la siguiente ejecución.
