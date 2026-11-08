# 🤖 Wallapop Bots

Alertas de **Wallapop** y **Vinted** en tu Telegram, con un panel web para gestionarlas.
Le dices qué buscas (por ejemplo *"layton"*, entre 0 y 25 €) y el bot te avisa en cuanto sale un anuncio nuevo.

- 🔎 Busca en Wallapop, en Vinted o en las dos a la vez.
- 💰 Filtro de precio mínimo y máximo.
- 🌐 Filtro de **idioma**: ver solo los anuncios en un idioma, o excluir idiomas (por ejemplo, no quiero la versión italiana ni la francesa).
- 🚫 **Palabras excluidas**: ignora los anuncios que contengan las palabras que tú elijas ("solo caja", "réplica"...).
- ⚡ **Bots rápidos**: los que marques se revisan cada pocos segundos, y se mide el retraso real de detección.
- 📉 **Bajadas de precio**: si un anuncio que ya viste se abarata, te avisa con el precio anterior y el porcentaje.
- 🔥 **Chollos**: marca los anuncios nuevos con un precio muy por debajo de la mediana de los de tu rango de precio.
- 📊 **Pestaña de estadísticas con gráficos**: precio medio y mediana del mercado *sin límite de precio* y dentro de tu rango, distribución, evolución y actividad.
- ⭐ **Favoritos**, y **búsqueda y orden** dentro de las novedades.
- 📱 Panel web (también se instala como app en el móvil) para crear, editar, pausar y borrar bots.
- ✨ **Novedades**: un muro con foto, precio y plataforma de cada anuncio encontrado, con opción de quitar anuncios a mano.
- 🗄 Cuando borras un bot, sus anuncios pasan a **Archivados** (no se pierden).
- 💬 También se maneja desde Telegram: `/bots`, `/nuevo`, `/stats`.

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

Con el script incluido, **un solo comando** (después de subir los cambios a GitHub):

```bash
cd ~/wallapop-alertas
bash actualizar.sh
```

El script para el servicio (el bot sube su estado a GitHub al pararse), guarda una copia del estado en `~/wallapop-backups/` (conserva las 10 últimas),
trae la última versión, instala las dependencias solo si `requirements.txt` cambió, comprueba que `check.py` compila, arranca el servicio y
verifica que sigue vivo. Además:

- Si ya tienes la última versión, te lo dice y **no reinicia nada** (`bash actualizar.sh --forzar` reinicia igualmente).
- Si la versión nueva no compila o el bot se cae al arrancar, **vuelve solo a la versión anterior** y te enseña el error.
- Si hay conflicto con `data/state.json`, lo resuelve él.
- Si no tiene internet, o tienes cambios tuyos en el código sin guardar, **para antes de tocar nada** y te explica qué ocurre.

Para llamarlo más corto, añade un alias: `echo "alias actualizar='bash ~/wallapop-alertas/actualizar.sh'" >> ~/.bashrc` (vale desde la próxima sesión).
La **primera vez** (cuando todavía no tienes el script) actualiza a mano:

```bash
cd ~/wallapop-alertas
sudo systemctl stop wallapop
git checkout -- data/state.json
git pull --rebase
sudo systemctl start wallapop
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

### Cómo se buscan las palabras

El título del anuncio tiene que contener **todas** las palabras de la búsqueda, **en cualquier orden**: `nendoroid banana fish` encuentra
«Banana Fish Nendoroid Ash». No importan las mayúsculas, los acentos ni los guiones (`Banana-Fish` vale). Las palabras de 4 letras o más
pueden ir dentro de otra (`mario` encuentra «Supermario») y también valen en plural (`nendoroids`). Las muy cortas (`ds`, `ps5`) tienen que
empezar una palabra, para que `ds` no coincida con «kids». Si quieres una búsqueda más amplia, usa menos palabras.

### Palabras excluidas

Si el **título o la descripción** contienen alguna de las palabras, el anuncio se ignora.

- Separa con comas: `solo caja, funda*, réplica`.
- No distingue mayúsculas ni acentos: `réplica` también descarta *REPLICA*.
- Una **frase** debe aparecer tal cual: `solo caja` descarta *"solo caja"*, pero no *"solo la caja"*.
- Un **`*` al final** cubre variantes: `caja*` descarta *caja*, *cajas*, *cajita*...
- Se buscan palabras completas: `caja` no descarta *"cajón"*.

### Novedades y archivados

La pestaña **Novedades** muestra los anuncios que ha ido encontrando el bot.

- **NUEVO**: etiqueta de los últimos 10 minutos.
- **🗑 en cada tarjeta**: quita ese anuncio de Novedades. El bot no volverá a avisarte de él. Es la forma de limpiar los que ya se han vendido.
- **⋯ (arriba a la derecha)**: *Vaciar* un bot concreto, vaciar todo, o los archivados.
- Si **editas** un bot (precio, plataformas, idioma o palabras excluidas), sus anuncios antiguos siguen bajo el mismo nombre,
  pero separados en una sección *"bot anterior"* con la configuración que tenía.
- **Archivados**: al borrar un bot, sus anuncios van aquí, agrupados por bot. Si más tarde creas otro bot con el mismo nombre, vuelven a Novedades.

### Bajadas de precio y chollos

Cuando el bot ve un anuncio por segunda vez lo reconoce por su **enlace**, así que sabe si ha cambiado de precio.

- **📉 Bajada de precio**: te llega un aviso aparte con el precio anterior (`18,00€ (antes 25,00€, −28%)`). Cuenta si baja al menos
  **1 €** y **5 %** (así no te avisa por céntimos). En el panel la tarjeta muestra el precio antiguo tachado y una etiqueta azul, y
  sustituye a la tarjeta anterior del mismo anuncio. Si un anuncio **sube** de precio ya no se cuenta como novedad.
- **🔥 Chollo**: un anuncio *nuevo* cuyo precio está al menos un **40 %** por debajo de la **mediana de los anuncios dentro de tu rango de
  precio** (la mediana es el precio "del medio"; no la distorsionan unos pocos anuncios carísimos o de 1 €). Se compara con tu rango y no con
  todo el mercado, porque es lo que de verdad te interesa. Llega en un mensaje aparte (🔥 *POSIBLES CHOLLOS*) y con etiqueta naranja en el panel.
  Hace falta que el bot tenga estadísticas con 8 anuncios o más dentro de tu rango, y se ignoran los anuncios de menos de 0,50 €.
  Los chips **🔥 Chollos** y **📉 Bajadas** del panel filtran solo esos anuncios.

### ⚡ Bots rápidos y velocidad de detección

Cuando alguien tiene compra automática, un anuncio puede desaparecer a los pocos segundos. Para no llegar tarde:

- **⚡ Bot rápido**: en el formulario de un bot marca *Bot rápido (prioridad)*. Esos bots se revisan cada `FAST_INTERVAL` segundos (**3 por defecto**,
  mínimo 1) en lugar de cada `CHECK_INTERVAL`. Las vueltas rápidas solo consultan lo imprescindible, así que son ligeras. Se pueden marcar varios.
- **Freno automático**: pedir tantas veces puede hacer que Wallapop o Vinted te bloqueen. Si empiezan a rechazar peticiones, los bots rápidos se
  frenan solos (hasta una vez por minuto), te avisan por Telegram y recuperan su ritmo cuando se calma. Con `FAST_INTERVAL=1` el riesgo es mayor:
  pruébalo con uno o dos bots y mira que no te llegan avisos de frenado.
- **Consultas en paralelo**: todas las peticiones de una vuelta salen a la vez, así que cada vuelta tarda lo que tarda la más lenta.

**Medir el retraso real.** Si la plataforma indica cuándo se publicó un anuncio, el aviso de Telegram añade `⏱ Publicado hace 40 s`, cada tarjeta del
panel muestra `⏱` con el tiempo que tardó el bot en verlo, y la pestaña **Estadísticas** dibuja cuántos se ven en menos de 10 s, 30 s, 1 min…,
comparando los bots ⚡ con los normales. Solo se mide con anuncios nuevos (no con la lista inicial ni con bajadas de precio).
Ese retraso suma lo que tarda la propia plataforma en mostrar el anuncio en las búsquedas más lo que tarda el bot en preguntar: el de los bots rápidos
te dice cuánto es lo mínimo que se puede conseguir. Para comprobar qué campos de fecha devuelve cada plataforma:

```bash
cd ~/wallapop-alertas
set -a; . ~/wallapop.env; set +a
./venv/bin/python check.py --campos "layton"
```

Para cada anuncio enseña los campos de tiempo que trae la respuesta y cuál se usaría como hora de publicación (o `NINGUNA` si no hay ninguno reconocible).

### 📊 Pestaña Estadísticas

Una pestaña propia del panel, con gráficos. Arriba eliges **Resumen** o un bot concreto.

**Resumen** (todos tus bots):
- Totales: anuncios guardados, 🔥 chollos, 📉 bajadas de precio y ⭐ favoritos.
- Anuncios encontrados por día (últimos 14 días), reparto Wallapop / Vinted y anuncios por bot.
- Mediana de precio de cada bot y una tabla comparando el **mercado sin límite de precio** con **tu rango**.

**Un bot concreto**:
- Mediana y media del mercado (sin límite de precio), mediana dentro de tu rango y tamaño de la muestra.
- **Distribución de precios**: cuántos anuncios hay a cada precio, con tu rango resaltado y la mediana marcada.
- **Evolución del precio**: mediana y media a lo largo del tiempo (el bot añade un punto cada 6 h).
- Mediana en Wallapop frente a Vinted, y anuncios encontrados por día.

Los datos del mercado se calculan con una muestra de los anuncios **más recientes** de cada plataforma (unas decenas), aplicando tu filtro de idioma
y tus palabras excluidas, y se refrescan cada 6 horas (o enseguida si editas el bot; la gráfica de evolución solo se reinicia si cambias la búsqueda,
las plataformas, el idioma o las exclusiones, no el rango de precio). Son una orientación del precio al que se publica, no de a cuánto se vende.
Las gráficas de actividad usan las novedades guardadas en el panel. En Telegram, `/stats` da un resumen rápido en texto.

### Favoritos, búsqueda y orden

- **☆ / ★** en cada tarjeta: guarda el anuncio en la pestaña **⭐ Favoritos**. Se guardan aparte (`data/favorites.json`), así que no se
  pierden al vaciar las novedades ni al borrar el bot.
- **Buscador** (sobre las tarjetas): filtra por palabras del título, sin importar mayúsculas ni acentos.
- **Orden**: más recientes, precio de menor a mayor, de mayor a menor, o **🔥 mayor descuento** (chollos y bajadas primero).

### Telegram

| Comando | Qué hace |
|---|---|
| `/start`, `/ayuda` | Muestra la ayuda. |
| `/bots` | Lista tus bots con botones para pausar, reanudar o borrar. |
| `/stats` | Muestra el precio medio y la mediana de cada bot (mercado y tu rango). |
| `/nuevo mario party 0 30` | Crea un bot (palabras, precio mínimo y máximo). `/nuevo jamboree 25` pone solo el máximo. |

Los filtros de idioma y las palabras excluidas se configuran desde el panel.

### Avisos si el bot o la Raspberry se caen

Hay dos capas, y conviene activar las dos:

**1. Avisos del propio bot** (`AVISOS_ESTADO=1` en `~/wallapop.env`). Te escribe por Telegram cuando:

| Situación | Mensaje |
|---|---|
| Se apaga o reinicia la Raspberry, o haces `systemctl stop/restart` | 🔴 *Bot detenido* |
| Arranca (tras encender, reiniciar o actualizar) | 🟢 *Bot en marcha*. Si estuvo parado más de 3 min, añade cuánto y desde cuándo. |
| Se cae internet un rato y vuelve | ✅ *Conexión recuperada*, con los minutos que estuvo sin consultar |

Esto cubre los apagados ordenados y los cortes de luz **después de que vuelva la luz** (el aviso de arranque dice cuánto estuvo caído).
Una Raspberry sin corriente no puede mandar nada, así que para enterarte **mientras** está caída necesitas la capa 2.

**2. Vigilante externo** (`HEALTHCHECK_URL`). El bot "late" cada minuto a un servicio externo gratuito; si dejan de llegar latidos, ese servicio te avisa.
Con [healthchecks.io](https://healthchecks.io) (gratis):

1. Crea una cuenta y un *check* nuevo. Pon **Period: 5 minutes** y **Grace Time: 5 minutes**.
2. En *Integrations* añade **Telegram** (o email) y sigue sus pasos para que el aviso te llegue al móvil.
3. Copia la *Ping URL* del check (algo como `https://hc-ping.com/xxxxxxxx-xxxx-...`).
4. Añádela a `~/wallapop.env`:
   ```
   AVISOS_ESTADO=1
   HEALTHCHECK_URL=https://hc-ping.com/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```
5. Reinicia: `sudo systemctl restart wallapop`.

A los ~10 minutos sin latidos (corte de luz, Raspberry colgada, router caído...) te llega el aviso, y otro cuando vuelva a latir.

> Los avisos de estado solo funcionan en modo bucle (opción B). En GitHub Actions no hacen falta y están desactivados por defecto.

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
| `CHOLLO_PCT` | | `40` | Porcentaje por debajo de la mediana para marcar un chollo. `0` lo desactiva. |
| `BAJADA_MIN_EUR`, `BAJADA_MIN_PCT` | | `1`, `5` | Lo mínimo que tiene que bajar un anuncio (en € y en %) para avisar de la bajada. |
| `FAST_INTERVAL` | | `3` | Segundos entre vueltas de los bots ⚡ (mínimo 1). Se frena solo si la plataforma rechaza peticiones. |
| `STATS_EVERY` | | `21600` | Segundos entre recálculos de las estadísticas de cada bot (6 h). |
| `STATE_PUSH_EVERY` | | `900` | Segundos entre copias de `state.json` al repo (también se copia al parar). |
| `AVISOS_ESTADO` | | `0` | `1` = avisos por Telegram al arrancar, detenerse y recuperar la conexión. |
| `HEALTHCHECK_URL` | | | URL de latido (p. ej. healthchecks.io) para enterarte si la Raspberry se apaga. |

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

**Aparece `Aviso al subir el estado a GitHub` en el registro.**
El bot copia `data/state.json` al repo por la API de GitHub (ya no usa `git push`, que fallaba sin credenciales de git). Si el aviso se repite,
revisa que tu `GITHUB_TOKEN` tenga *Contents: Read and write* y que `GITHUB_REPOSITORY` sea correcto. Mientras tanto el estado sigue guardándose en local.

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
├── check.py                    # el bot: búsquedas, filtros, avisos de Telegram
├── actualizar.sh               # actualiza el bot en la Raspberry con un solo comando (opción B)
├── requirements.txt            # requests (y lingua, opcional, para el detector de idioma)
├── data/
│   ├── config.json             # tus bots (lo escriben el panel y Telegram)
│   ├── results.json            # el muro de Novedades (lo escriben el bot y el panel)
│   ├── state.json              # anuncios ya avisados, precios recordados y estado de Telegram (solo el bot)
│   ├── stats.json              # estadísticas de precios por bot, con su historial (se crea solo; lo escribe el bot)
│   └── favorites.json          # tus favoritos (se crea solo; lo escribe el panel)
├── docs/                       # el panel web que publica GitHub Pages
│   ├── index.html
│   ├── manifest.webmanifest
│   └── icon-192.png, icon-512.png
└── .github/workflows/
    └── wallapop.yml            # ejecución en GitHub Actions (opción A)
```

Si cambias algo en `check.py` o en `docs/index.html`, en la opción B reinicia el servicio con `sudo systemctl restart wallapop`;
en la opción A, GitHub lo recoge en la siguiente ejecución.
