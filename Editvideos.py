import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import numpy as np
import imageio_ffmpeg
import PIL.Image
from PIL import Image, ImageDraw, ImageFont, ImageFilter

if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

os.environ["IMAGEIO_FFMPEG_EXE"] = imageio_ffmpeg.get_ffmpeg_exe()

import requests
from dotenv import load_dotenv

load_dotenv()
from moviepy.editor import (
    VideoFileClip, ImageClip, CompositeVideoClip, ColorClip,
    AudioFileClip, CompositeAudioClip, concatenate_videoclips,
)

# ============ CONFIGURACIÓN ============
CARPETA_SCRIPT = os.path.dirname(os.path.abspath(__file__))
CARPETA_VIDEOS = os.path.join(CARPETA_SCRIPT, "Videos")
CARPETA_BRICKS = os.path.join(CARPETA_SCRIPT, "Post Processed Videos")
# Los bricks ya vienen recortados (sin logo F1) y con trims desde
# Postprocess_bricks.py -> NO se aplica el crop anti-logo de nuevo
# (aplicarlo dos veces haría zoom excesivo). Solo se concatena.
BRICKS_YA_RECORTADOS = True
CARPETA_SALIDA = os.path.join(CARPETA_SCRIPT, "Videos_Editados")
ARCHIVO_TEXTO = os.path.join(CARPETA_SCRIPT, "textos.txt")

CROP_TOP_PCT = 0.22  # franja superior eliminada: saca el logo F1 (incl. variante "F1 SPRINT") con margen
CROP_REESCALAR_A_ORIGINAL = True  # tras recortar, reescalar a W×H original (zoom) para salida 1080x1920 sin bandas

# --- B-ROLL aleatorio desde "Post Processed Videos" ---
MARGEN_FINAL = 1.0          # 1s extra al final: video = voz + 1s
BRICK_SPEED_MIN = 0.95      # solo si es estrictamente necesario
BRICK_SPEED_MAX = 1.05      # solo si es estrictamente necesario
BRICK_MIN_FRAGMENTO = 1.0   # evita cortes <1s en el último brick (usa speed o best-fit)
BRICK_EXTS = (".mp4", ".mov", ".m4v")

# --- END CARD: fundido a negro + logo RC 1.5s ---
ENDCARD_ACTIVO = True
ENDCARD_LOGO = os.path.join(CARPETA_SCRIPT, "RC-Logo on Black Full.jpg")
ENDCARD_DUR = 1.5                # el cierre ocupa los últimos 1.5s (no alarga el video)
ENDCARD_ANCHO_PCT = 0.86         # ancho del logo respecto al video
ENDCARD_FADE_NEGRO = 0.9         # fundido del negro (fade-through-black, más progresivo)
ENDCARD_LOGO_DELAY = 0.35        # el logo aparece 0.35s tras empezar el negro
ENDCARD_LOGO_FADE = 0.5          # fundido de entrada del logo (lineal)
ENDCARD_LOGO_ZOOM = (0.94, 1.0)  # escala suave 0.94 -> 1.0 durante su aparición

# --- VOICE OVER: gratis (edge-tts) por defecto / pago (OpenRouter) para final ---
# TTS_BACKEND: "edge" (gratis, AvaNeural) | "openrouter" (elevenlabs/eleven-v4, pago)
# Cambia con env: TTS_BACKEND=openrouter para la voz final de pago.
TTS_BACKEND = os.getenv("TTS_BACKEND", "edge").strip().lower()
EDGE_VOICE = os.getenv("EDGE_VOICE", "en-US-AvaNeural")  # AvaNeural Female USA (gratis)
# --- OpenRouter (pago, voz final) — se conserva para la versión definitiva ---
# Model page: https://openrouter.ai/elevenlabs/eleven-v4
# Endpoint: POST https://openrouter.ai/api/v1/audio/speech
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_TTS_MODEL = os.getenv("OPENROUTER_TTS_MODEL", "elevenlabs/eleven-v4")
OPENROUTER_VOICE = os.getenv("OPENROUTER_VOICE", "george")
OPENROUTER_RESPONSE_FORMAT = os.getenv("OPENROUTER_RESPONSE_FORMAT", "mp3")
VOLUMEN_VIDEO_ORIGINAL = 0.0
GENERAR_SRT = True
# --- ENTREGA VIRAL REELS (Instagram) ---
# Ritmo: narración ~30% más rápida que conversacional (rápida pero inteligible
# en short-form con subtítulos grandes). El atempo local preserva el tono.
# eleven-v4 no acepta `speed` en la API (devuelve 400) -> se acelera con ffmpeg.
VELOCIDAD_VOZ = 1.3
# Tono/energía: la API de OpenRouter ignora `instructions` en elevenlabs
# (solo la honran OpenAI/Gemini/Fish), así que la energía se dirige en el
# TEXTO (100% compatible y sin cambiar nº de palabras -> el alineamiento
# de subtítulos sigue exacto):
#   1) Hook: la 1ª frase termina en "!" (más pegada).
#   2) Frases largas: ", " -> ". " cuando el segmento pasa de 15 palabras
#      (frases cortas y percutivas en vez de enumeraciones planas).
REELS_PUNCH = True

# --- ESTILO DE SUBTÍTULOS (ESTILO REELS / INSTAGRAM) ---
SUBTITULO_Y_PCT = 0.62           # Posición vertical
SUBTITULO_FONT_SIZE_PCT = 0.066  # +20% sobre 0.055 para texto más grande
SUBTITULO_MAX_WORDS_LINE = 20    # Tope de seguridad; el límite real es el ancho de pantalla
SUBTITULO_ESCALA_ACTIVA = 1.10   # La palabra activa se agranda un 10%
SUBTITULO_ADELANTO = 0.04        # Mostrar cada palabra 40ms antes (compensa latencia percibida)
SUBTITULO_COLOR_BASE = (255, 255, 255, 255)      # Palabras inactivas: blanco relleno
# Palabra activa: azul sólido #01abfe, SIN contorno negro
SUBTITULO_COLOR_ACTIVA = (0x01, 0xAB, 0xFE, 255)  # #01abfe sólido
SUBTITULO_USAR_DEGRADADO = False                 # False = relleno sólido (prueba), True = degradado azul
# (degradado anterior, conservado por si se quiere volver)
SUBTITULO_GRADIENT_TOP = (0x00, 0xD9, 0xFD, 255)     # #00d9fd arriba
SUBTITULO_GRADIENT_BOTTOM = (0x01, 0x69, 0xFE, 255)  # #0169fe abajo
SUBTITULO_STROKE_COLOR = (0, 0, 0, 255)          # Contorno negro
SUBTITULO_STROKE_WIDTH = 0                       # Sin contorno negro
# Sombra suave (legibilidad sobre fondos claros sin contorno duro):
SUBTITULO_SOMBRA = True                        # False = sin sombra
SUBTITULO_SOMBRA_COLOR = (0, 0, 0, 170)         # Negro semitransparente
SUBTITULO_SOMBRA_DX = 0                        # Desplazamiento horizontal px
SUBTITULO_SOMBRA_DY = 5                        # Desplazamiento vertical px
SUBTITULO_SOMBRA_BLUR = 8                      # Radio de desenfoque (suavidad)
SUBTITULO_MAX_WIDTH_PCT = 0.96                   # Menos padding: el texto se acerca a los bordes
SUBTITULO_PAUSA_ENTRE_BLOQUES = 0.25             # Pausa (s) entre audios secuenciales

# --- FUENTES (Montserrat ExtraBold primero) ---
FUENTES_MONTSERRAT = [
    "/Library/Fonts/Montserrat-ExtraBold.ttf",
    os.path.expanduser("~/Library/Fonts/Montserrat-ExtraBold.ttf"),
    os.path.join(CARPETA_SCRIPT, "Montserrat-ExtraBold.ttf"),
    "/Library/Fonts/Montserrat-Bold.ttf",
    "/Library/Fonts/Montserrat-Black.ttf",
    os.path.expanduser("~/Library/Fonts/Montserrat-Bold.ttf"),
    os.path.expanduser("~/Library/Fonts/Montserrat-Black.ttf"),
    os.path.join(CARPETA_SCRIPT, "Montserrat-Bold.ttf"),
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf"
]

THREADS = 4
# =======================================

def encontrar_fuente():
    for f in FUENTES_MONTSERRAT:
        if os.path.exists(f):
            print(f"   ✅ Fuente encontrada: {f}")
            return f
    raise FileNotFoundError("No se encontró ninguna fuente válida.")

def cargar_fuente(fuente_path, size):
    """Carga Montserrat ExtraBold. Si es variable, fija variación ExtraBold."""
    font = ImageFont.truetype(fuente_path, size)
    try:
        names = font.get_variation_names() if hasattr(font, "get_variation_names") else []
        if names and any(b'ExtraBold' in n for n in names):
            font.set_variation_by_name(b'ExtraBold')
    except Exception:
        pass
    return font

def parsear_txt(ruta):
    """Multi-video con marcador process Y/N.

    Formato esperado en textos.txt (recomendado):

        Video_1 | process: Y
        Línea de guion 1...
        Línea de guion 2...

        Video_2 | process: N
        Este bloque se ignora...

        Video_3 | process: Y
        (sin texto -> también se ignora)

    Variantes aceptadas para la cabecera:
      - "Video_1 | process: Y" / "Video_1, process=Y" / "Video_1 process: Y"
      - En dos líneas:
            Video_1
            process: Y
      - El nombre puede ser cualquier base de archivo (Video_1, MiVideo, etc.)
        con o sin ".mp4".
      - Y/N insensible a mayúsculas. Si un bloque no tiene marcador,
        se considera process=N (no se procesa).

    Compatibilidad: si el archivo NO contiene ninguna cabecera Video_*,
    se trata como modo un solo video (todas las líneas = guion único)
    y se devuelve {"__SINGLE__": (True, [...])}.

    Devuelve dict ordenado: {nombre: (process_bool, [lineas_guion])}.
    Solo deben procesarse los que tengan process=True Y lista no vacía.
    """
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"No encuentro el archivo: {ruta}")

    with open(ruta, 'r', encoding='utf-8') as f:
        lineas_raw = [l.strip() for l in f]

    # Regex cabecera en una línea: "Video_1 | process: Y"
    re_header_inline = re.compile(
        r'^(.+?)\s*[|,;:-]?\s*process\s*[:=]\s*([YNyn])\s*$'
    )
    # Regex cabecera sola: "Video_1" o "Video_1.mp4" o "MiVideo"
    re_video_solo = re.compile(
        r'^((?:Video_\d+)|[\w\-\. ]+?)(?:\.mp4)?\s*$', re.IGNORECASE
    )
    # Regex línea suelta "process: Y"
    re_process_solo = re.compile(r'^process\s*[:=]\s*([YNyn])\s*$', re.IGNORECASE)

    bloques = {}  # nombre -> [process_bool, guiones]
    orden = []
    actual = None

    def _nuevo_bloque(nombre, process):
        nonlocal actual
        nombre = nombre.strip()
        if nombre.lower().endswith(".mp4"):
            nombre = nombre[:-4]
        if nombre not in bloques:
            bloques[nombre] = [process, []]
            orden.append(nombre)
        else:
            # Si se repite la cabecera, actualiza el flag
            bloques[nombre][0] = process
        actual = nombre

    # Primera pasada: ¿hay alguna cabecera? para decidir modo single vs multi
    hay_cabecera = False
    for linea in lineas_raw:
        if not linea or linea.startswith('#'):
            continue
        if re_header_inline.match(linea) or re_process_solo.match(linea) or re_video_solo.match(linea):
            # Ojo: una línea de guion normal podría coincidir con
            # re_video_solo si es 1-2 palabras; la confirmamos solo si
            # parece nombre de video o viene seguida de process/guion.
            # Criterio: re_header_inline y re_process_solo siempre son cabecera.
            # re_video_solo solo cuenta si es "Video_N" exacto o "X.mp4".
            if re_header_inline.match(linea) or re_process_solo.match(linea):
                hay_cabecera = True
                break
            m = re_video_solo.match(linea)
            if m and (re.fullmatch(r'Video_\d+', m.group(1).strip(), re.IGNORECASE)
                      or linea.lower().endswith('.mp4')):
                hay_cabecera = True
                break

    if not hay_cabecera:
        # Modo legacy: todo el archivo es el guion de UN video
        guiones = []
        for linea in lineas_raw:
            if not linea or linea.startswith('#'):
                continue
            if '|' in linea:
                posible_tiempo, _, posible_texto = linea.rpartition('|')
                if re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*', posible_tiempo):
                    linea = posible_texto.strip()
            if linea:
                guiones.append(linea)
        return {"__SINGLE__": (True, guiones)}

    # Modo multi-video
    for linea in lineas_raw:
        if not linea or linea.startswith('#'):
            continue

        m_inline = re_header_inline.match(linea)
        if m_inline:
            nombre = m_inline.group(1).strip()
            # Evita falsos positivos: el nombre debe ser corto (<=60 chars)
            # y sin espacios excesivos; si no, trátalo como guion.
            if len(nombre) <= 60 and re.fullmatch(r'[\w\-\. ]+', nombre):
                _nuevo_bloque(nombre, m_inline.group(2).upper() == 'Y')
                continue
            # si no parece nombre válido, cae a guion

        m_proc = re_process_solo.match(linea)
        if m_proc:
            if actual is not None:
                bloques[actual][0] = (m_proc.group(1).upper() == 'Y')
            continue

        m_vid = re_video_solo.match(linea)
        if m_vid:
            candidato = m_vid.group(1).strip()
            es_video_n = re.fullmatch(r'Video_\d+', candidato, re.IGNORECASE)
            es_mp4 = linea.lower().endswith('.mp4')
            if es_video_n or es_mp4:
                # Cabecera sin marcador -> default N hasta ver "process: Y"
                _nuevo_bloque(candidato, False)
                continue
            # Si no es Video_N ni .mp4, es guion normal -> sigue abajo

        # Línea de guion (compat: prefijo 'inicio-fin |')
        texto = linea
        if '|' in texto:
            posible_tiempo, _, posible_texto = texto.rpartition('|')
            if re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*', posible_tiempo):
                texto = posible_texto.strip()
        if not texto:
            continue
        if actual is None:
            # Guion antes de cualquier cabecera -> se ignora en modo multi
            continue
        bloques[actual][1].append(texto)

    # Filtrar guiones vacíos/blancos finales
    resultado = {}
    for nombre in orden:
        proc, guiones = bloques[nombre]
        guiones_limpios = [g for g in guiones if g.strip()]
        resultado[nombre] = (proc, guiones_limpios)
    return resultado


def resolver_video_entrada(bloques=None):
    """Resuelve el ÚNICO video a editar (modo legacy / override manual).
    Prioridad: 1) argv[1], 2) env VIDEO_ENTRADA, 3) único .mp4 en Videos/.
    Devuelve (ruta_in, nombre). Si se pasa `bloques` (dict multi-video)
    y el nombre existe ahí, devuelve también sus guiones (ruta, nombre, guiones).
    """
    ruta, nombre = None, None
    if len(sys.argv) > 1:
        ruta = sys.argv[1]
        if not os.path.isabs(ruta):
            ruta = os.path.join(CARPETA_SCRIPT, ruta)
        if not os.path.exists(ruta):
            raise FileNotFoundError(f"No existe el video indicado: {ruta}")
        base = os.path.basename(ruta)
        nombre = base[:-4] if base.lower().endswith(".mp4") else base
    else:
        env_ruta = os.getenv("VIDEO_ENTRADA", "").strip()
        if env_ruta:
            ruta = env_ruta if os.path.isabs(env_ruta) else os.path.join(CARPETA_SCRIPT, env_ruta)
            if not os.path.exists(ruta):
                raise FileNotFoundError(f"No existe VIDEO_ENTRADA: {ruta}")
            base = os.path.basename(ruta)
            nombre = base[:-4] if base.lower().endswith(".mp4") else base
        else:
            return None, None, None
    if bloques is not None and nombre in bloques:
        _, guiones = bloques[nombre]
        return ruta, nombre, guiones
    return ruta, nombre, None

# ---------- TTS (OpenRouter -> elevenlabs/eleven-v4) ----------
# POST https://openrouter.ai/api/v1/audio/speech
# Devuelve audio crudo (no JSON), sin timestamps -> alineación local.
# Si faster-whisper está instalado se usa para word-timestamps reales;
# si no, reparto mejorado por peso de palabra + recorte de silencios.
USAR_WHISPER = True
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

def _peso_palabra(w):
    letras = sum(1 for c in w if c.isalnum())
    base = max(2.0, float(letras))
    if w[-1:] in ",;:":
        base += 2.0
    elif w[-1:] in ".!?":
        base += 3.5
    elif w[-1:] in ("—", "–", "-", chr(34), chr(39), ")", "”"):
        base += 1.0
    return base


def _split_words_fallback(texto, total_dur, inicio=0.0, gap=0.035):
    """Reparto proporcional al nº de letras (no al len bruto) + pausas
    entre palabras y bonus por puntuación. Mucho más cercano al habla real."""
    raw = texto.split()
    if not raw or total_dur <= 0:
        return []
    pesos = [_peso_palabra(w) for w in raw]
    n = len(raw)
    total_gap = gap * (n - 1) if n > 1 else 0.0
    if total_gap >= total_dur * 0.4 and n > 1:
        gap = total_dur * 0.15 / (n - 1)
        total_gap = gap * (n - 1)
    habla = max(0.05, total_dur - total_gap)
    s = sum(pesos) or 1.0
    t = inicio
    out = []
    for i, (w, p) in enumerate(zip(raw, pesos)):
        d = habla * p / s
        out.append((w, t, t + d))
        t += d + (gap if i < n - 1 else 0)
    if out:
        w0, s0, _ = out[-1]
        out[-1] = (w0, s0, inicio + total_dur)
    return out


def _medir_silencios(ruta, sr=16000, umbral=0.02):
    """Mide silencio inicial/final real del mp3 (los TTS suelen dejar
    50-150ms de aire que desfasa todos los subs si se ignora).
    Decodifica con ffmpeg a PCM crudo (evita artefactos de moviepy)."""
    try:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        res = subprocess.run(
            [ffmpeg, "-v", "error", "-i", ruta, "-ac", "1",
             "-ar", str(sr), "-f", "s16le", "-"],
            capture_output=True)
        if res.returncode != 0 or not res.stdout:
            return 0.0, 0.0
        pcm = np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size == 0:
            return 0.0, 0.0
        win = max(1, sr // 50)  # ventanas de 20ms
        nwin = pcm.size // win
        if nwin == 0:
            return 0.0, 0.0
        rms = np.sqrt((pcm[:nwin * win].reshape(nwin, win) ** 2).mean(axis=1))
        voz = rms > umbral
        if not voz.any():
            return 0.0, 0.0
        dur = pcm.size / sr
        i0 = int(np.argmax(voz))
        i1 = len(voz) - 1 - int(np.argmax(voz[::-1]))
        lead = i0 * win / sr
        trail = max(0.0, dur - (i1 + 1) * win / sr)
        return min(lead, dur * 0.3), min(trail, dur * 0.3)
    except Exception:
        return 0.0, 0.0


def _alinear_con_whisper(ruta, texto):
    """Word-timestamps reales con faster-whisper (si está instalado).
    Devuelve [(w, start, end)] con la ortografía del guion, o None."""
    if not USAR_WHISPER:
        return None
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    try:
        script = texto.split()
        if not script:
            return []
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(ruta, word_timestamps=True, vad_filter=True)
        det = [(w.word.strip(), float(w.start), float(w.end))
               for s in segments for w in (s.words or []) if w.word and w.word.strip()]
        if not det:
            return None
        # Solo alineación 1:1 segura; si el conteo difiere, fallback
        if len(det) != len(script):
            print(f"   ⚠️  Whisper detectó {len(det)} palabras vs {len(script)} del guion, uso reparto estimado.")
            return None
        return [(script[i], s, e) for i, (_, s, e) in enumerate(det)]
    except Exception as e:
        print(f"   ⚠️  Whisper falló ({str(e)[:150]}), uso reparto estimado.")
        return None


def _edge_tts(texto, ruta, voice=None):
    """Sintetiza con edge-tts (gratis) y guarda en `ruta` (mp3).

    Voz por defecto: en-US-AvaNeural (AvaNeural Female USA).
    """
    import asyncio
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("Falta edge-tts: pip install edge-tts")
    vid = voice or EDGE_VOICE
    # edge-tts normaliza "en-US-AvaNeural"; acepta alias corto "AvaNeural" por comodidad
    if vid.lower().replace("-", "").replace("_", "") in ("avaneural", "ava"):
        vid = "en-US-AvaNeural"

    async def _run():
        communicate = edge_tts.Communicate(texto, vid)
        await communicate.save(ruta)

    try:
        asyncio.run(_run())
    except RuntimeError as e:
        # Por si ya hay un event loop corriendo (poco común en este script)
        if "already running" in str(e).lower() or "cannot be called" in str(e).lower():
            loop = asyncio.get_event_loop()
            loop.run_until_complete(_run())
        else:
            raise


def _openrouter_tts(texto, ruta, voice=None):
    """Sintetiza con elevenlabs/eleven-v4 vía OpenRouter y guarda en `ruta`.

    Docs: https://openrouter.ai/docs/api/api-reference/tts/create-speech
    Voces: george|sarah|adam|alice|bella|bill|brian|callum|charlie|chris|
           daniel|eric|harry|jessica|laura|liam|lily|matilda|river|roger|will
    response_format: mp3|pcm (mp3 recomendado)
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("Falta OPENROUTER_API_KEY en el entorno (.env).")
    url = "https://openrouter.ai/api/v1/audio/speech"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    }
    payload = {
        "model": OPENROUTER_TTS_MODEL,  # "elevenlabs/eleven-v4"
        "input": texto,
        "voice": voice or OPENROUTER_VOICE,  # ej. "george"
        "response_format": OPENROUTER_RESPONSE_FORMAT,  # "mp3" | "pcm"
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    if resp.status_code != 200:
        # Errores típicos: 400 param no soportado, 401 key inválida,
        # 402 sin créditos, 403 límite/gasto, 404 modelo no disponible,
        # 429 rate-limit, 502 fallo upstream (no facturado)
        try:
            detalle = resp.json()
        except Exception:
            detalle = resp.text[:500]
        raise RuntimeError(f"OpenRouter TTS {resp.status_code}: {detalle}")
    # Éxito = bytes de audio crudo, NO llamar a resp.json()
    # Content-Type será audio/mpeg (mp3) o audio/pcm (pcm)
    with open(ruta, "wb") as f:
        f.write(resp.content)


def _acelerar_audio(ruta, factor):
    """Acelera un mp3 in-place con ffmpeg atempo (preserva el tono).
    eleven-v4 no soporta `speed`, así que se hace localmente."""
    if factor == 1.0:
        return True
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    tmp = ruta + ".fast.mp3"
    # atempo acepta 0.5-2.0 en un solo filtro; 1.3 va directo
    cmd = [ffmpeg, "-y", "-v", "error", "-i", ruta,
           "-filter:a", f"atempo={factor}", "-vn", tmp]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(tmp):
        print(f"   ⚠️  No se pudo acelerar audio ({res.stderr.strip()[:200]}), se usa velocidad normal.")
        return False
    os.replace(tmp, ruta)
    return True


def _estilo_reels(texto):
    """Dirige la entrega viral sin cambiar el nº de palabras (alineamiento intacto).

    1) Hook: la primera frase termina en "!" si terminaba en ".".
    2) Frases largas: ", " -> ". " cuando el segmento supera 15 palabras.
    Devuelve (texto_transformado, cambió_bool).
    """
    if not texto or not texto.strip():
        return texto, False
    original = texto
    # 1) Hook con pegada
    texto = texto.strip()
    m = re.match(r'^([^.!?]+)\.\s+(.*)$', texto, re.DOTALL)
    if m and len(m.group(1).split()) >= 3:
        texto = m.group(1).rstrip() + "! " + m.group(2).lstrip()
    # 2) Partir enumeraciones largas en frases cortas percutivas
    partes = re.split(r'(?<=[.!?])\s+', texto)
    nuevas = []
    for p in partes:
        if p.count(" ") >= 15 and ", " in p:
            # corta por la coma más cercana a la mitad
            trozos = p.split(", ")
            izq, der = [], []
            mitad = len(p.split()) / 2
            acc = 0
            for i, t in enumerate(trozos):
                if acc + len(t.split()) < mitad or not izq:
                    izq.append(t)
                    acc += len(t.split())
                else:
                    der = trozos[i:]
                    break
            if der and len(der[0].split()) >= 3 and not re.search(r'\b(e\.g|i\.e|vs)\.?$', izq[-1].strip(), re.I):
                p = ", ".join(izq).rstrip() + ". " + ", ".join(der).lstrip()
                # mayúscula tras el punto nuevo
                p = re.sub(r'\. ([a-z])', lambda mm: ". " + mm.group(1).upper(), p, count=1)
        nuevas.append(p)
    texto = " ".join(nuevas)
    return texto, (texto != original)


def generar_voz_con_palabras(texto, ruta, target_dur=None, voice_id=None):
    """Genera voz y devuelve ([(w,start,end)], dur).

    Backend según TTS_BACKEND:
      - "edge" (gratis, pruebas): edge-tts en-US-AvaNeural.
      - "openrouter" (pago, final): elevenlabs/eleven-v4 vía OpenRouter.

    Timing (en orden): 1) faster-whisper si disponible (real), 2) reparto
    mejorado por peso de palabra entre silencios medidos. Al final se
    adelanta todo SUBTITULO_ADELANTO para que el highlight no llegue tarde.
    El audio se acelera xVELOCIDAD_VOZ vía ffmpeg atempo.
    Si REELS_PUNCH, el texto se dirige a entrega viral (_estilo_reels).
    """
    if REELS_PUNCH:
        texto, cambio = _estilo_reels(texto)
        if cambio:
            print(f"   ⚡ Reels punch: {texto[:90]}...")
    backend = (TTS_BACKEND or "edge").lower()
    if backend == "openrouter":
        vid = voice_id or OPENROUTER_VOICE
        try:
            _openrouter_tts(texto, ruta, voice=vid)
        except Exception as e:
            print(f"   ❌ TTS OpenRouter eleven-v4 error: {e}")
            return [], 0.0
    else:
        vid = voice_id or EDGE_VOICE
        try:
            _edge_tts(texto, ruta, voice=vid)
        except Exception as e:
            print(f"   ❌ TTS edge-tts ({vid}) error: {e}")
            return [], 0.0
    try:
        if VELOCIDAD_VOZ != 1.0:
            _acelerar_audio(ruta, VELOCIDAD_VOZ)
        a = AudioFileClip(ruta)
        dur = a.duration
        a.close()
    except Exception as e:
        print(f"   ❌ No se pudo leer el audio TTS: {e}")
        return [], 0.0
    # 1) Timestamps reales si hay whisper
    words = _alinear_con_whisper(ruta, texto)
    # 2) Fallback mejorado: recorta aire inicial/final y reparte por peso
    if not words:
        lead, trail = _medir_silencios(ruta)
        ini = min(lead, dur * 0.5)
        fin = max(ini + 0.1, dur - trail)
        words = _split_words_fallback(texto, fin - ini, inicio=ini)
    # Adelanto global para sincronía percibida (nunca < 0)
    if SUBTITULO_ADELANTO:
        words = [(w, max(0.0, s - SUBTITULO_ADELANTO), max(0.01, e - SUBTITULO_ADELANTO))
                 for w, s, e in words]
    return words, dur

# ---------- RENDERIZADO DE SUBTÍTULOS ----------
def _crear_fuentes(fuente_path, video_w):
    base_size = max(30, int(video_w * SUBTITULO_FONT_SIZE_PCT))
    big_size = max(int(base_size * SUBTITULO_ESCALA_ACTIVA), base_size + 2)
    return base_size, big_size

def agrupar_palabras_en_lineas(palabras, video_w, fuente_path):
    """Agrupa palabras hasta llenar el ancho de la línea (como en Reels).
    El ancho se mide con la fuente GRANDE (peor caso: cada palabra activa)."""
    if not palabras:
        return []
    base_size, big_size = _crear_fuentes(fuente_path, video_w)
    font_base = cargar_fuente(fuente_path, base_size)
    font_big = cargar_fuente(fuente_path, big_size)
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    space_w = dummy.textlength(" ", font=font_base)
    max_w = video_w * SUBTITULO_MAX_WIDTH_PCT

    lineas = []
    linea_actual = []
    total = 0.0
    for palabra in palabras:
        w_w = dummy.textlength(palabra[0].strip().upper(), font=font_big)
        candidato = total + (space_w if linea_actual else 0) + w_w
        if linea_actual and (candidato > max_w or len(linea_actual) >= SUBTITULO_MAX_WORDS_LINE):
            lineas.append(linea_actual)
            linea_actual = [palabra]
            total = w_w
        else:
            linea_actual.append(palabra)
            total = candidato
    if linea_actual:
        lineas.append(linea_actual)
    return lineas

def _gradiente_vertical_rgba(w, h, color_top, color_bottom):
    """Degradado vertical RGBA: color_top arriba -> color_bottom abajo."""
    top = np.array(color_top[:3], dtype=np.float32)
    bottom = np.array(color_bottom[:3], dtype=np.float32)
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None]  # 0=arriba, 1=abajo
    col = (top[None, :] * (1 - t) + bottom[None, :] * t)  # (h, 3)
    rgb = np.repeat(col[:, None, :], w, axis=1)  # (h, w, 3)
    alpha_top = color_top[3] if len(color_top) > 3 else 255
    alpha_bottom = color_bottom[3] if len(color_bottom) > 3 else 255
    a_col = (alpha_top * (1 - t[:, 0]) + alpha_bottom * t[:, 0])  # (h,)
    grad = np.zeros((h, w, 4), dtype=np.uint8)
    grad[..., :3] = rgb.astype(np.uint8)
    grad[..., 3] = np.repeat(a_col[:, None], w, axis=1).astype(np.uint8)
    return grad


def crear_subtitulo_linea(linea, video_w, video_h, fuente_path):
    """Para cada palabra de la línea dibuja la línea completa:
    la palabra que se pronuncia, 10% más grande y en azul #01abfe;
    el resto, blancas. Sin contorno: legibilidad vía sombra suave.
    Cuando termina la última palabra, la siguiente línea toma el relevo."""
    if not linea:
        return []

    textos = [w.strip().upper() for w, _, _ in linea]
    base_size, big_size = _crear_fuentes(fuente_path, video_w)
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    max_w = video_w * SUBTITULO_MAX_WIDTH_PCT

    clips = []
    for i, (_, w_start, w_end) in enumerate(linea):
        # Ajustar fuente hasta que la línea (con palabra activa grande) quepa
        sb, sg = base_size, big_size
        while True:
            fb = cargar_fuente(fuente_path, sb)
            fg = cargar_fuente(fuente_path, sg)
            space_w = dummy.textlength(" ", font=fb)
            widths = [dummy.textlength(t, font=(fg if j == i else fb))
                      for j, t in enumerate(textos)]
            total_w = sum(widths) + space_w * (len(textos) - 1)
            if total_w <= max_w or sb <= 20:
                break
            sb -= 2
            sg = max(sb + 2, int(sb * SUBTITULO_ESCALA_ACTIVA))

        asc_b, desc_b = fb.getmetrics()
        asc_g, desc_g = fg.getmetrics()
        max_asc = max(asc_b, asc_g)
        text_h = max_asc + max(desc_b, desc_g)
        margin = SUBTITULO_STROKE_WIDTH * 2 + int(sg * 0.15)
        if SUBTITULO_SOMBRA:
            margin += SUBTITULO_SOMBRA_BLUR + max(abs(SUBTITULO_SOMBRA_DX),
                                                  abs(SUBTITULO_SOMBRA_DY)) + 2
        img_w = int(total_w + margin * 2)
        img_h = int(text_h + margin * 2)

        img_linea = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_linea)
        capa_sombra = (Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
                       if SUBTITULO_SOMBRA else None)
        draw_sombra = ImageDraw.Draw(capa_sombra) if capa_sombra else None

        current_x = margin
        y_base = margin + max_asc  # línea base común (la palabra activa sobresale)
        active_xy = None
        active_text = None
        active_font = None
        for j, t in enumerate(textos):
            font = fg if j == i else fb
            asc, _ = font.getmetrics()
            xy = (current_x, y_base - asc)
            if draw_sombra:
                draw_sombra.text((xy[0] + SUBTITULO_SOMBRA_DX,
                                  xy[1] + SUBTITULO_SOMBRA_DY),
                                 t, font=font, fill=SUBTITULO_SOMBRA_COLOR)
            if j == i:
                # 1) Contorno + base negra para la palabra activa
                draw.text(xy, t, font=font, fill=SUBTITULO_STROKE_COLOR,
                          stroke_width=SUBTITULO_STROKE_WIDTH,
                          stroke_fill=SUBTITULO_STROKE_COLOR)
                active_xy = xy
                active_text = t
                active_font = font
            else:
                draw.text(xy, t, font=font, fill=SUBTITULO_COLOR_BASE,
                          stroke_width=SUBTITULO_STROKE_WIDTH, stroke_fill=SUBTITULO_STROKE_COLOR)
            current_x += widths[j] + space_w

        # 2) Relleno palabra activa: sólido azul #01abfe o degradado
        if active_xy is not None:
            if SUBTITULO_USAR_DEGRADADO:
                mascara = Image.new("L", (img_w, img_h), 0)
                dm = ImageDraw.Draw(mascara)
                dm.text(active_xy, active_text, font=active_font, fill=255)
                grad = _gradiente_vertical_rgba(
                    img_w, img_h, SUBTITULO_GRADIENT_TOP, SUBTITULO_GRADIENT_BOTTOM
                )
                capa_grad = Image.fromarray(grad, mode="RGBA")
                img_linea.paste(capa_grad, (0, 0), mascara)
            else:
                draw.text(active_xy, active_text, font=active_font,
                          fill=SUBTITULO_COLOR_ACTIVA,
                          stroke_width=SUBTITULO_STROKE_WIDTH,
                          stroke_fill=SUBTITULO_STROKE_COLOR)

        # 3) Sombra suave debajo del texto (se difumina y se compone detrás)
        if capa_sombra is not None:
            capa_sombra = capa_sombra.filter(
                ImageFilter.GaussianBlur(SUBTITULO_SOMBRA_BLUR))
            img_linea = Image.alpha_composite(capa_sombra, img_linea)

        # Transición instantánea, sin solape: cada clip termina exactamente
        # cuando empieza la siguiente palabra (w_end ya es contiguo al
        # siguiente w_start). Sin +0.1s que causaba overlay entre líneas.
        if i < len(linea) - 1:
            display_end = linea[i + 1][1]
        else:
            display_end = w_end

        # Guardar solo clips con duración válida
        if display_end <= w_start:
            continue

        arr = np.array(img_linea)
        y_pos = int(video_h * SUBTITULO_Y_PCT) - (img_h // 2)

        clip = (ImageClip(arr, transparent=True)
                .set_start(w_start)
                .set_duration(display_end - w_start)
                .set_position(('center', y_pos)))
        clips.append(clip)

    return clips

def aplicar_crop(video):
    """Recorte anti-logo F1 + zoom para mantener resolución.

    El watermark F1 (incl. "F1 SPRINT") vive arriba a la izquierda,
    aprox. entre el 8-18% superior. Se elimina el CROP_TOP_PCT superior
    (22% por defecto, con margen) y se recortan laterales de forma
    centrada para conservar el aspecto 9:16. Después se reescala al
    tamaño original (zoom ~1.28x), así la salida sigue siendo 1080x1920
    sin bandas negras y el logo nunca reaparece (ya quedó fuera antes
    del reescalado).
    """
    w, h = int(video.w), int(video.h)
    top_cut = int(round(h * CROP_TOP_PCT))
    h_rest = h - top_cut
    # Ancho que mantiene 9:16 con la altura restante
    new_w = int(round(h_rest * 9.0 / 16.0))
    new_w = max(2, min(w, new_w))
    # Centrado horizontal (reparte el recorte lateral a ambos lados)
    side_total = w - new_w
    x1 = side_total // 2
    x2 = x1 + new_w
    recortado = video.crop(x1=x1, y1=top_cut, x2=x2, y2=h)
    if CROP_REESCALAR_A_ORIGINAL and (recortado.w != w or recortado.h != h):
        try:
            # moviepy 1.x: resize(newsize=(w, h)) con LANCZOS por defecto
            recortado = recortado.resize(newsize=(w, h))
        except TypeError:
            recortado = recortado.resize((w, h))
    return recortado

def _mascara_fundido(size, dur_clip, dur_fade):
    """Máscara 0->1 para fundidos de opacidad reales.

    (El fadein/fadeout normal de moviepy 1.0.3 sobre clips NO-máscara solo
    disuelve el RGB hacia negro, no anima la opacidad: un negro fundiendo
    "desde negro" se queda negro = corte seco. Por eso se anima la máscara.)
    """
    return (ColorClip(size=size, color=1.0, ismask=True)
            .set_duration(dur_clip).fadein(dur_fade))


def construir_endcard(video_w, video_h):
    """End card 1.5s: fundido a negro + logo RC centrado con fade y zoom suave.

    El logo (apaisado, fondo negro) se ajusta al 86% del ancho y se centra;
    el negro funde desde el B-roll (fade-through-black) y el logo entra con
    fade + escala 0.94->1.0. Devuelve CompositeVideoClip o None si no hay logo.
    """
    if not ENDCARD_ACTIVO or not os.path.exists(ENDCARD_LOGO):
        if ENDCARD_ACTIVO:
            print(f"   ⚠️  Endcard omitido: no existe {ENDCARD_LOGO}")
        return None, []
    negro = ColorClip(size=(video_w, video_h), color=(0, 0, 0)).set_duration(ENDCARD_DUR)
    negro = negro.set_mask(_mascara_fundido((video_w, video_h), ENDCARD_DUR, ENDCARD_FADE_NEGRO))
    logo_w = int(video_w * ENDCARD_ANCHO_PCT)
    logo = ImageClip(ENDCARD_LOGO).resize(width=logo_w)
    logo = logo.set_position("center").set_duration(ENDCARD_DUR - ENDCARD_LOGO_DELAY)
    # Zoom suave durante la aparición.
    # OJO: el resize animado va ANTES del set_mask (moviepy 1.0.3 rompe
    # la máscara float si se redimensiona después).
    z0, z1 = ENDCARD_LOGO_ZOOM
    try:
        logo = logo.resize(lambda t: z0 + (z1 - z0) * min(max(t, 0.0) / max(logo.duration, 0.01), 1.0))
    except Exception:
        pass
    logo = logo.set_mask(_mascara_fundido(logo.size, logo.duration, ENDCARD_LOGO_FADE))
    logo = logo.set_start(ENDCARD_LOGO_DELAY)  # el fade lo lleva su máscara
    endcard = CompositeVideoClip([negro, logo], size=(video_w, video_h)).set_duration(ENDCARD_DUR)
    return endcard, [logo]


def _fmt_srt(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def escribir_srt(entradas, ruta):
    with open(ruta, "w", encoding="utf-8") as f:
        for i, (ini, fin, texto) in enumerate(entradas, 1):
            f.write(f"{i}\n{_fmt_srt(ini)} --> {_fmt_srt(fin)}\n{texto}\n\n")

# ---------- B-ROLL aleatorio desde "Post Processed Videos" ----------
_CACHE_DUR_BRICKS = {}  # ruta -> duración (se mide una vez por ejecución)

def _listar_bricks():
    """Lista todos los clips utilizables en CARPETA_BRICKS."""
    if not os.path.isdir(CARPETA_BRICKS):
        return []
    archivos = sorted(
        os.path.join(CARPETA_BRICKS, f) for f in os.listdir(CARPETA_BRICKS)
        if f.lower().endswith(BRICK_EXTS)
        and not f.startswith(".")
    )
    return [a for a in archivos if os.path.isfile(a)]

def _duracion_clip(ruta):
    """Duración en segundos de un clip (con caché)."""
    if ruta in _CACHE_DUR_BRICKS:
        return _CACHE_DUR_BRICKS[ruta]
    c = VideoFileClip(ruta)
    try:
        d = float(c.duration or 0.0)
    finally:
        c.close()
    _CACHE_DUR_BRICKS[ruta] = d
    return d

def _evaluar_bricks():
    """Mide todos los bricks y los devuelve como [(ruta, dur)]."""
    bricks = _listar_bricks()
    info = []
    for ruta in bricks:
        try:
            d = _duracion_clip(ruta)
        except Exception as e:
            print(f"   ⚠️  Brick ilegible {os.path.basename(ruta)}: {str(e)[:120]}")
            continue
        if d > 0.2:
            info.append((ruta, d))
    return info

def _aplicar_velocidad(clip, factor):
    """Acelera/ralentiza un clip con factor dado (preserva tono si hay audio)."""
    if abs(factor - 1.0) < 1e-4:
        return clip
    try:
        import moviepy.video.fx.all as vfx
        return clip.fx(vfx.speedx, factor)
    except Exception:
        # Fallback manual: speedx directo si existe
        if hasattr(clip, "speedx"):
            return clip.speedx(factor)
        return clip

def construir_broll(target_dur):
    """Arma un B-roll aleatorio que dure exactamente target_dur.

    - Orden aleatorio distinto en cada llamada (random.shuffle sin semilla).
    - Acumula bricks completos hasta cubrir, recorta el último al resto.
    - Evita fragmentos finales < BRICK_MIN_FRAGMENTO: busca best-fit entre
      los no usados; si no hay, ajusta velocidad global dentro de
      [BRICK_SPEED_MIN, BRICK_SPEED_MAX] solo si es estrictamente necesario.
    - Si los bricks no alcanzan (raro: hay ~11 min), reutiliza barajando de nuevo.

    Devuelve (clip_concatenado_sin_crop, clips_abiertos, seleccion_info).
    seleccion_info = [(basename, usado_ini, usado_fin, dur_original), ...]
    El llamador debe cerrar clips_abiertos + el concatenado tras escribir.
    """
    info = _evaluar_bricks()
    if not info:
        raise RuntimeError(f"No hay clips utilizables en {CARPETA_BRICKS}")
    print(f"   🧱 Bricks evaluados: {len(info)} clips, total {sum(d for _, d in info):.1f}s.")

    orden = info[:]
    random.shuffle(orden)  # diferente en cada generación

    seleccion = []  # (ruta, ini, fin, dur_orig)
    usadas = set()
    total = 0.0

    # 1) Acumular clips completos mientras quepan holgadamente
    idx = 0
    while total < target_dur and idx < len(orden):
        ruta, d = orden[idx]
        idx += 1
        if total + d <= target_dur:
            seleccion.append((ruta, 0.0, d, d))
            usadas.add(ruta)
            total += d
        else:
            # Este clip excedería: lo reservamos como candidato a recorte
            candidato_exceso = (ruta, d)
            break
    else:
        candidato_exceso = None

    if total >= target_dur - 1e-3:
        pass  # caso exacto (raro)
    elif candidato_exceso is not None:
        ruta, d = candidato_exceso
        remain = target_dur - total
        if remain >= BRICK_MIN_FRAGMENTO or d < BRICK_MIN_FRAGMENTO:
            # Recorte normal
            if d >= remain:
                seleccion.append((ruta, 0.0, remain, d))
                usadas.add(ruta)
                total = target_dur
            else:
                seleccion.append((ruta, 0.0, d, d))
                usadas.add(ruta)
                total += d
        else:
            # remain < 1s: recortar aquí dejaría un micro-fragmento.
            # Buscar best-fit entre los no usados: clip con d2 >= remain
            # que minimice el desperdicio (d2 - remain).
            resto = [(r2, d2) for r2, d2 in orden[idx:] if r2 not in usadas]
            best = None
            for r2, d2 in resto:
                if d2 >= remain:
                    exceso = d2 - remain
                    if best is None or exceso < best[2]:
                        best = (r2, d2, exceso)
            if best is not None and best[2] <= 4.0:
                # Hay un clip que encaja casi justo: úsalo recortado
                r2, d2, _ = best
                seleccion.append((r2, 0.0, remain, d2))
                usadas.add(r2)
                total = target_dur
            else:
                # Sin best-fit: toma el clip excedente completo y acelera
                # el conjunto solo si el factor queda en [0.95, 1.05].
                factor = (total + d) / target_dur
                if BRICK_SPEED_MIN <= factor <= BRICK_SPEED_MAX:
                    seleccion.append((ruta, 0.0, d, d))
                    usadas.add(ruta)
                    total += d
                else:
                    # Fuera de rango: acepta el micro-fragmento igualmente
                    seleccion.append((ruta, 0.0, remain, d))
                    usadas.add(ruta)
                    total = target_dur
            candidato_exceso = None

    # 2) Si aún falta (todos los bricks usados o clips muy cortos), reutilizar
    intentos = 0
    while total < target_dur - 1e-3 and intentos < 5:
        intentos += 1
        extra = info[:]
        random.shuffle(extra)
        for ruta, d in extra:
            if total >= target_dur - 1e-3:
                break
            remain = target_dur - total
            if d <= remain:
                seleccion.append((ruta, 0.0, d, d))
                total += d
            else:
                if remain >= BRICK_MIN_FRAGMENTO or True:
                    seleccion.append((ruta, 0.0, remain, d))
                    total = target_dur
                    break
        if total < target_dur - 1e-3:
            print(f"   ⚠️  Bricks insuficientes, reintentando (intento {intentos})...")

    # 3) Abrir + recortar + concatenar
    abiertos = []
    trozos = []
    for ruta, ini, fin, _dorig in seleccion:
        clip = VideoFileClip(ruta)
        abiertos.append(clip)
        if fin - ini < clip.duration - 1e-3:
            # Recorte aleatorio dentro del brick para más variedad:
            # si sobra, elige inicio al azar en vez de siempre 0.
            max_ini = max(0.0, clip.duration - (fin - ini))
            ini_rand = random.uniform(0, max_ini) if max_ini > 0.05 else 0.0
            trozo = clip.subclip(ini_rand, ini_rand + (fin - ini))
        else:
            trozo = clip
        trozos.append(trozo)

    if not trozos:
        raise RuntimeError("No se pudo armar B-roll (selección vacía).")

    concat = concatenate_videoclips(trozos, method="chain")
    concat_dur = float(concat.duration or 0.0)

    # 4) Snap final por velocidad SOLO si es estrictamente necesario
    # (desfase por redondeo de subclip). Fuera de [0.95,1.05] -> recorta/rellena.
    dif = abs(concat_dur - target_dur)
    if dif > 0.08:
        factor = concat_dur / target_dur if target_dur > 0 else 1.0
        if BRICK_SPEED_MIN <= factor <= BRICK_SPEED_MAX:
            print(f"   ⏩ Ajuste fino de velocidad x{factor:.3f} para clavar {target_dur:.2f}s "
                  f"(concat {concat_dur:.2f}s).")
            concat = _aplicar_velocidad(concat, factor)
        elif concat_dur > target_dur:
            concat = concat.subclip(0, target_dur)
        else:
            # Rellena congelando último frame (raro)
            from moviepy.editor import ImageClip as _IC
            faltan = target_dur - concat_dur
            ultimo = trozos[-1].get_frame(trozos[-1].duration - 0.04)
            freeze = _IC(ultimo, transparent=False).set_duration(faltan)
            try:
                freeze = freeze.set_fps(24)
            except Exception:
                pass
            concat = concatenate_videoclips([concat, freeze], method="chain")

    sel_info = [(os.path.basename(r), round(i, 2), round(f, 2), round(d, 2))
                for r, i, f, d in seleccion]
    print(f"   🧱 B-roll: {len(seleccion)} bricks, {float(concat.duration):.2f}s objetivo {target_dur:.2f}s.")
    for b, i, f, d in sel_info:
        print(f"      - {b} [{i}s->{f}s de {d}s]")
    return concat, abiertos, sel_info

# ---------- EDICIÓN (B-roll aleatorio + voz) ----------
def editar_video(nombre, guiones, fuente, carpeta_temp, ruta_in=None):
    """Guion -> TTS -> B-roll aleatorio desde 'Post Processed Videos'.

    1) Genera la voz (1 llamada TTS) y mide dur_audio.
    2) target = dur_audio + MARGEN_FINAL (1s de margen al final).
    3) Evalúa todos los bricks, los baraja (diferente cada vez) y concatena
       hasta cubrir target (recorta el último; velocidad 0.95-1.05 solo si
       es estrictamente necesario).
    4) Subtítulos/SRT sobre el B-roll, voz desde 0s.
    5) Guarda en Videos_Editados/{nombre}.mp4.

    `ruta_in` queda solo como fallback legacy: si no hay bricks pero existe
    ese archivo, se usa como fondo (comportamiento anterior).
    """
    ruta_out = os.path.join(CARPETA_SALIDA, f"{nombre}.mp4")
    guiones_limpios = [t.strip() for t in guiones if t.strip()]
    if not guiones_limpios:
        print(f"   ⏭️  {nombre}: sin texto -> ignorado.")
        return False

    video_original = None   # fondo legacy si no hay bricks
    broll_raw = None        # concatenado de bricks (sin crop)
    broll_abiertos = []     # VideoFileClips de bricks (cerrar al final)
    video = None
    final = None
    capa_audio = None
    endcard = None
    endcard_hijos = []

    try:
        # --- 1) TTS primero para conocer la duración objetivo ---
        texto_full = " ".join(guiones_limpios)
        ruta_audio = os.path.join(carpeta_temp, f"{nombre}_full.mp3")
        _voz_default = OPENROUTER_VOICE if (TTS_BACKEND or "edge").lower() == "openrouter" else EDGE_VOICE
        print(f"   🎙️  TTS {TTS_BACKEND} ({_voz_default}, 1 llamada, {len(guiones_limpios)} bloques): {texto_full[:60]}...")
        words_full, dur_audio = generar_voz_con_palabras(texto_full, ruta_audio, None, None)
        if dur_audio <= 0 or not os.path.exists(ruta_audio):
            print(f"   ❌ TTS falló, no se puede armar B-roll sin duración objetivo.")
            return False
        print(f"   ⏱️  Voz: {dur_audio:.2f}s -> objetivo video: {dur_audio + MARGEN_FINAL:.2f}s (+{MARGEN_FINAL:.1f}s margen).")
        target_dur = dur_audio + MARGEN_FINAL
        dur_usable = dur_audio

        # --- 2) B-roll aleatorio (ya sin logo: no se recorta de nuevo) ---
        try:
            broll_raw, broll_abiertos, _sel = construir_broll(target_dur)
            video = broll_raw if BRICKS_YA_RECORTADOS else aplicar_crop(broll_raw)
        except Exception as e_broll:
            print(f"   ⚠️  B-roll falló ({str(e_broll)[:200]}), intento fallback legacy.")
            broll_raw = None
            if ruta_in and os.path.exists(ruta_in):
                video_original = VideoFileClip(ruta_in)
                video = aplicar_crop(video_original)
                # En fallback, recortar solo si excede el video
                dur_usable = min(dur_audio, video.duration)
                target_dur = video.duration
            else:
                print(f"   ❌ Sin bricks ni video fallback para {nombre}.")
                return False

        capas_subtitulo = []
        entradas_srt = []  # (inicio, fin, texto) reales para el .srt

        # --- 3) Subtítulos repartidos por nº de palabras ---
        idx = 0
        for texto in guiones_limpios:
            n = len(texto.split())
            bloque_words = words_full[idx:idx + n]
            idx += n
            filtradas = []
            for wtext, ws, we in bloque_words:
                if ws >= dur_usable:
                    break
                w_end = min(we, dur_usable)
                if w_end > ws:
                    filtradas.append((wtext, ws, w_end))
            if not filtradas:
                continue
            entradas_srt.append((filtradas[0][1], filtradas[-1][2], texto))
            lineas_bloque = agrupar_palabras_en_lineas(filtradas, video.w, fuente)
            for linea in lineas_bloque:
                clips_linea = crear_subtitulo_linea(linea, video.w, video.h, fuente)
                if clips_linea:
                    capas_subtitulo.extend(clips_linea)

        print(f"      Subtítulos: {len(capas_subtitulo)} clips generados.")

        pistas_audio = []
        if video.audio is not None and VOLUMEN_VIDEO_ORIGINAL > 0:
            pistas_audio.append(video.audio.volumex(VOLUMEN_VIDEO_ORIGINAL))

        if os.path.exists(ruta_audio):
            a = AudioFileClip(ruta_audio)
            if a.duration > dur_usable:
                a = a.subclip(0, dur_usable)
            # 1) Corta todo lo que haya después de la última palabra + 0.20s
            #    de decaimiento natural. Ahí vive el "sonidito": resto de
            #    síntesis tras "around the car". Anclado a palabras, así que
            #    nunca recorta voz real.
            try:
                if words_full:
                    _fin_ultima = max(e for _, _, e in words_full if e <= dur_usable + 0.01)
                    _corte = min(a.duration, _fin_ultima + 0.20)
                    if _corte < a.duration - 0.05 and _corte > 0.5:
                        a = a.subclip(0, _corte)
            except Exception:
                pass
            # 2) Fundido de salida: la voz nunca corta en seco (evita click/pop
            #    justo en "around the car" / última palabra).
            try:
                from moviepy.audio.fx.audio_fadeout import audio_fadeout
                a = a.fx(audio_fadeout, min(0.3, a.duration / 2))
            except Exception:
                pass
            a = a.set_start(0)
            capa_audio = a
            pistas_audio.append(a)

        final = CompositeVideoClip([video] + capas_subtitulo, size=(video.w, video.h))

        # --- End card: fundido a negro + logo RC en los últimos 1.5s ---
        try:
            _d = float(video.duration)
            if ENDCARD_ACTIVO and _d > ENDCARD_DUR + 0.5:
                endcard, endcard_hijos = construir_endcard(video.w, video.h)
                if endcard is not None:
                    final = CompositeVideoClip(
                        [final, endcard.set_start(_d - ENDCARD_DUR)],
                        size=(video.w, video.h)).set_duration(_d)
                    print(f"   🏁 Endcard: fundido a negro + logo últimos {ENDCARD_DUR}s.")
        except Exception as e_ec:
            print(f"   ⚠️  Endcard falló ({str(e_ec)[:150]}), se sigue sin cierre.")

        if pistas_audio:
            final = final.set_audio(CompositeAudioClip(pistas_audio))
        else:
            final = final.without_audio()

        final.write_videofile(
            ruta_out, codec='libx264', audio_codec='aac',
            fps=24, preset='ultrafast', threads=THREADS, logger=None
        )

        if GENERAR_SRT:
            ruta_srt = os.path.join(CARPETA_SALIDA, f"{nombre}.srt")
            escribir_srt(entradas_srt, ruta_srt)

        print(f"   ✅ B-roll {float(video.duration):.2f}s / voz {dur_usable:.2f}s / margen "
              f"{float(video.duration) - dur_usable:.2f}s.")
        return True

    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        try:
            if final is not None:
                final.close()
        except Exception:
            pass
        try:
            if capa_audio is not None:
                capa_audio.close()
        except Exception:
            pass
        # broll_raw puede ser el concat (cerrarlo) + los bricks abiertos
        try:
            if broll_raw is not None:
                broll_raw.close()
        except Exception:
            pass
        for c in broll_abiertos:
            try:
                c.close()
            except Exception:
                pass
        # video puede ser un crop del concat (ya cerrado arriba); si es
        # fallback legacy, cerrar el original
        try:
            if video_original is not None:
                video_original.close()
        except Exception:
            pass
        for c in endcard_hijos:
            try:
                c.close()
            except Exception:
                pass
        try:
            if endcard is not None:
                endcard.close()
        except Exception:
            pass

def main():
    """Modo multi-video con marcador process Y/N + B-roll aleatorio:
    - Solo se procesan bloques con process=Y Y con texto.
    - process=N o sin texto -> se ignoran.
    - El fondo se arma aleatoriamente desde 'Post Processed Videos' en cada
      generación (bricks ya sin logo F1 y con trims): se mide la voz TTS,
      target = voz + 1s, se barajan los bricks y se concatenan hasta cubrir
      el target (velocidad 0.95-1.05 solo si es estrictamente necesario).
      Cada ejecución da una combinación distinta.
    - Override manual: argv[1] o VIDEO_ENTRADA procesa UN solo video
      (ignora el marcador, usa su guion si existe).
    - Legacy: si textos.txt no tiene cabeceras, se procesa 1 video con B-roll.
    """
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    bloques = parsear_txt(ARCHIVO_TEXTO)
    fuente = encontrar_fuente()

    print(f"🔤 Fuente: {fuente}")
    print(f"🧱 Bricks: {CARPETA_BRICKS} (ya sin logo F1, sin re-crop)")
    print(f"🎙️  Voz: backend={TTS_BACKEND} "
          f"({'model=' + OPENROUTER_TTS_MODEL + ' voice=' + OPENROUTER_VOICE if (TTS_BACKEND or '') == 'openrouter' else 'voice=' + EDGE_VOICE + ' (gratis)'}) "
          f"| reels x{VELOCIDAD_VOZ}{'+punch' if REELS_PUNCH else ''}")
    print(f"💬 Subtítulos: Estilo Reels (palabra activa ampliada x{SUBTITULO_ESCALA_ACTIVA}, líneas al ancho de pantalla)")

    # --- Override manual: un solo video indicado por argv/env ---
    ruta_man, nombre_man, guiones_man = resolver_video_entrada(bloques)
    if ruta_man is not None:
        if guiones_man is None:
            # No hay bloque para ese nombre en textos.txt -> ¿modo legacy __SINGLE__?
            if "__SINGLE__" in bloques:
                _, guiones_man = bloques["__SINGLE__"]
            else:
                print(f"   ❌ {nombre_man} no tiene bloque en textos.txt, no hay guion.")
                return
        print(f"\n🎬 {nombre_man} ({len(guiones_man)} bloques) <- {ruta_man} [override manual]")
        carpeta_temp = tempfile.mkdtemp(prefix="voz_")
        try:
            if editar_video(nombre_man, guiones_man, fuente, carpeta_temp, ruta_in=ruta_man):
                print(f"   ✅ Guardado en Videos_Editados/{nombre_man}.mp4")
            else:
                print(f"\n❌ Falló la edición de {nombre_man}.")
        finally:
            shutil.rmtree(carpeta_temp, ignore_errors=True)
        return

    # --- Modo legacy sin cabeceras: 1 guion -> B-roll ---
    if "__SINGLE__" in bloques:
        _, guiones = bloques["__SINGLE__"]
        nombre = "Video_Broll"
        print(f"\n🎬 {nombre} ({len(guiones)} bloques) <- B-roll aleatorio [legacy sin cabeceras]")
        carpeta_temp = tempfile.mkdtemp(prefix="voz_")
        try:
            if editar_video(nombre, guiones, fuente, carpeta_temp, ruta_in=None):
                print(f"   ✅ Guardado en Videos_Editados/{nombre}.mp4")
        finally:
            shutil.rmtree(carpeta_temp, ignore_errors=True)
        return

    # --- Modo multi-video: filtrar por process=Y y con texto ---
    # (el visual sale de 'Video Bricks', no se exige Videos/<nombre>.mp4)
    if not _listar_bricks():
        print(f"\n❌ No hay bricks en {CARPETA_BRICKS}: no se puede armar B-roll.")
        return
    pendientes = []
    for nombre, (proc, guiones) in bloques.items():
        if not proc:
            print(f"⏭️  {nombre}: process=N -> ignorado.")
            continue
        if not guiones:
            print(f"⏭️  {nombre}: process=Y pero sin texto -> ignorado.")
            continue
        pendientes.append((nombre, guiones, None))

    if not pendientes:
        print("\n⚠️  Nada que procesar (ningún bloque con process=Y y texto + .mp4 existente).")
        return

    print(f"\n📋 A procesar: {len(pendientes)}/{len(bloques)} videos.")
    carpeta_temp = tempfile.mkdtemp(prefix="voz_")
    ok, fail = 0, 0
    try:
        for nombre, guiones, ruta_in in pendientes:
            print(f"\n🎬 {nombre} ({len(guiones)} bloques) <- {ruta_in}")
            if editar_video(nombre, guiones, fuente, carpeta_temp, ruta_in=ruta_in):
                print(f"   ✅ Guardado en Videos_Editados/{nombre}.mp4")
                ok += 1
            else:
                print(f"   ❌ Falló {nombre}.")
                fail += 1
        print(f"\n🎉 Terminado. {ok} ok / {fail} fallos / {len(bloques)-len(pendientes)} ignorados.")
    finally:
        shutil.rmtree(carpeta_temp, ignore_errors=True)

if __name__ == "__main__":
    main()