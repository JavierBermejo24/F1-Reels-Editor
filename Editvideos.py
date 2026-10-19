import os
import re
import shutil
import asyncio
import tempfile
import numpy as np
import imageio_ffmpeg
import PIL.Image
from PIL import Image, ImageDraw, ImageFont

if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

os.environ["IMAGEIO_FFMPEG_EXE"] = imageio_ffmpeg.get_ffmpeg_exe()

import edge_tts
from moviepy.editor import (
    VideoFileClip, ImageClip, CompositeVideoClip,
    AudioFileClip, CompositeAudioClip,
)

# ============ CONFIGURACIÓN ============
CARPETA_SCRIPT = os.path.dirname(os.path.abspath(__file__))
CARPETA_VIDEOS = os.path.join(CARPETA_SCRIPT, "Videos")
CARPETA_SALIDA = os.path.join(CARPETA_SCRIPT, "Videos_Editados")
ARCHIVO_TEXTO = os.path.join(CARPETA_SCRIPT, "textos.txt")

CROP_PCT = 0.20

# --- VOICE OVER ---
VOZ_TTS = "en-US-GuyNeural"      
VOLUMEN_VIDEO_ORIGINAL = 0.0     
GENERAR_SRT = True

# --- ESTILO DE SUBTÍTULOS (ESTILO HORMOZI / REELS) ---
SUBTITULO_Y_PCT = 0.62           # Posición vertical
SUBTITULO_FONT_SIZE_PCT = 0.085  # Tamaño base (se reducirá si no cabe)
SUBTITULO_MAX_WORDS_LINE = 3     # Recomendado 3 para que se vea grande y quepa bien
SUBTITULO_COLOR_BASE = (255, 255, 255, 255)      # Blanco
SUBTITULO_COLOR_ACTIVE = (57, 255, 20, 255)      # Verde neón (estilo Hormozi)
SUBTITULO_STROKE_COLOR = (0, 0, 0, 255)          # Contorno negro
SUBTITULO_STROKE_WIDTH = 6                       # Grosor del contorno

# --- FUENTES ---
FUENTES_MONTSERRAT = [
    "/Library/Fonts/Montserrat-Bold.ttf",
    "/Library/Fonts/Montserrat-ExtraBold.ttf",
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

def parsear_txt(ruta):
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"No encuentro el archivo: {ruta}")
    bloques = {}
    video_actual = None
    with open(ruta, 'r', encoding='utf-8') as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith('#'): continue
            if re.fullmatch(r'Video_\d+', linea):
                video_actual = linea
                bloques.setdefault(video_actual, [])
                continue
            if '|' in linea and video_actual:
                tiempos, texto = linea.split('|', 1)
                m = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*', tiempos)
                if m:
                    bloques[video_actual].append((float(m.group(1)), float(m.group(2)), texto.strip()))
    return bloques

# ---------- TTS ----------
def _split_words_fallback(texto, total_dur):
    raw = texto.split()
    if not raw: return []
    total_chars = sum(len(w) for w in raw) or 1
    words = []
    t = 0.0
    for w in raw:
        w_dur = (len(w) / total_chars) * total_dur
        words.append((w, t, t + w_dur))
        t += w_dur
    return words

async def _tts_with_words(texto, ruta, voz, rate):
    communicate = edge_tts.Communicate(texto, voz, rate=rate)
    words = []
    with open(ruta, "wb") as f:
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                f.write(chunk["data"])
            elif chunk.get("type") in ("WordBoundary", "SentenceBoundary"):
                text = chunk.get("text", "")
                offset = chunk.get("offset", 0) or 0
                duration = chunk.get("duration", 0) or 0
                start = offset / 10_000_000
                dur = duration / 10_000_000
                if text and dur > 0:
                    words.append((text, start, start + dur))
    return words

def generar_voz_con_palabras(texto, ruta, target_dur, voz):
    best = None
    for rate in ["+0%", "+15%", "+30%", "+45%", "+60%", "+80%"]:
        words = asyncio.run(_tts_with_words(texto, ruta, voz, rate))
        try:
            a = AudioFileClip(ruta)
            dur = a.duration
            a.close()
            if dur <= target_dur:
                if not words: words = _split_words_fallback(texto, dur)
                return words, dur
            best = (words, dur, rate)
        except Exception:
            return [], 0.0
    if best:
        words = best[0] or _split_words_fallback(texto, best[1])
        return words, best[1]
    return [], 0.0

# ---------- RENDERIZADO DE SUBTÍTULOS ----------
def agrupar_palabras_en_lineas(palabras, max_words=3):
    lineas = []
    linea_actual = []
    for palabra in palabras:
        linea_actual.append(palabra)
        if len(linea_actual) >= max_words:
            lineas.append(linea_actual)
            linea_actual = []
    if linea_actual:
        lineas.append(linea_actual)
    return lineas

def crear_subtitulo_linea(linea, video_w, video_h, fuente_path):
    if not linea: return []

    base_size = max(30, int(video_w * SUBTITULO_FONT_SIZE_PCT))
    font = ImageFont.truetype(fuente_path, base_size)
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    space_width = dummy.textlength(" ", font=font)
    
    # Calcular ancho y reducir fuente si no cabe
    total_w = 0
    word_widths = []
    for w, _, _ in linea:
        w_clean = w.strip().upper()
        w_w = dummy.textlength(w_clean, font=font)
        word_widths.append(w_w)
        total_w += w_w + space_width
    total_w -= space_width

    max_w = video_w * 0.9
    while total_w > max_w and base_size > 20:
        base_size -= 2
        font = ImageFont.truetype(fuente_path, base_size)
        total_w = 0
        word_widths = []
        for w, _, _ in linea:
            w_clean = w.strip().upper()
            w_w = dummy.textlength(w_clean, font=font)
            word_widths.append(w_w)
            total_w += w_w + space_width
        total_w -= space_width

    bbox = dummy.textbbox((0, 0), "A", font=font)
    text_h = bbox[3] - bbox[1]
    margin = SUBTITULO_STROKE_WIDTH * 2
    img_w = int(total_w + margin * 2)
    img_h = int(text_h + margin * 2)

    clips = []
    for i, (texto_palabra, w_start, w_end) in enumerate(linea):
        # Duración exacta de la palabra (hasta que empieza la siguiente)
        if i < len(linea) - 1:
            display_end = max(linea[i+1][1], w_start + 0.05)
        else:
            display_end = max(w_end + 0.1, w_start + 0.1)

        img_linea = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img_linea)
        
        current_x = margin
        for j, (w_text, _, _) in enumerate(linea):
            color = SUBTITULO_COLOR_ACTIVE if j == i else SUBTITULO_COLOR_BASE
            draw.text((current_x, margin), w_text.strip().upper(), font=font,
                      fill=color, stroke_width=SUBTITULO_STROKE_WIDTH, stroke_fill=SUBTITULO_STROKE_COLOR)
            current_x += word_widths[j] + space_width

        arr = np.array(img_linea)
        y_pos = int(video_h * SUBTITULO_Y_PCT) - (img_h // 2)
        
        clip = (ImageClip(arr, transparent=True)
                .set_start(w_start)
                .set_duration(display_end - w_start)
                .set_position(('center', y_pos)))
        clips.append(clip)

    return clips

def aplicar_crop(video):
    new_w = int(video.w * (1 - CROP_PCT))
    new_h = int(video.h * (1 - CROP_PCT))
    y1 = video.h - new_h
    return video.crop(x1=0, y1=y1, x2=new_w, y2=video.h)

def _fmt_srt(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def escribir_srt(entradas, ruta):
    with open(ruta, "w", encoding="utf-8") as f:
        for i, (ini, fin, texto) in enumerate(entradas, 1):
            f.write(f"{i}\n{_fmt_srt(ini)} --> {_fmt_srt(fin)}\n{texto}\n\n")

# ---------- EDICIÓN ----------
def editar_video(nombre, entradas, fuente, carpeta_temp):
    ruta_in = os.path.join(CARPETA_VIDEOS, f"{nombre}.mp4")
    ruta_out = os.path.join(CARPETA_SALIDA, f"{nombre}.mp4")

    if not os.path.exists(ruta_in):
        print(f"   ❌ No existe {ruta_in}")
        return False

    try:
        video_original = VideoFileClip(ruta_in)
        video = aplicar_crop(video_original)

        capas_subtitulo = []
        audios = []

        # PROCESAMOS BLOQUE POR BLOQUE (Evita mezclar frases)
        for idx, (inicio, fin, texto) in enumerate(entradas):
            if inicio >= video.duration: continue
            fin_real = min(fin, video.duration)
            dur_texto = fin_real - inicio

            ruta_audio = os.path.join(carpeta_temp, f"{nombre}_{idx}.mp3")
            print(f"   🎙️  TTS: {texto[:40]}...")
            words, _ = generar_voz_con_palabras(texto, ruta_audio, dur_texto, VOZ_TTS)
            audios.append((ruta_audio, inicio, dur_texto))

            palabras_bloque = []
            for wtext, ws, we in words:
                if ws > dur_texto: break
                w_start = inicio + ws
                w_end = inicio + min(we, dur_texto)
                if w_end > w_start:
                    palabras_bloque.append((wtext, w_start, w_end))

            # Agrupar solo las palabras de ESTE bloque
            lineas_bloque = agrupar_palabras_en_lineas(palabras_bloque, max_words=SUBTITULO_MAX_WORDS_LINE)
            
            for linea in lineas_bloque:
                clips_linea = crear_subtitulo_linea(linea, video.w, video.h, fuente)
                if clips_linea:
                    capas_subtitulo.extend(clips_linea)

        print(f"      Subtítulos: {len(capas_subtitulo)} clips generados.")

        pistas_audio = []
        if video.audio is not None and VOLUMEN_VIDEO_ORIGINAL > 0:
            pistas_audio.append(video.audio.volumex(VOLUMEN_VIDEO_ORIGINAL))

        for ruta_audio, inicio, target_dur in audios:
            if not os.path.exists(ruta_audio): continue
            a = AudioFileClip(ruta_audio)
            if a.duration > target_dur:
                a = a.subclip(0, target_dur)
            a = a.set_start(inicio)
            pistas_audio.append(a)

        final = CompositeVideoClip([video] + capas_subtitulo, size=(video.w, video.h))

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
            escribir_srt([(i, min(f, video.duration), t) for i, f, t in entradas], ruta_srt)

        video_original.close()
        final.close()
        return True

    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def main():
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    bloques = parsear_txt(ARCHIVO_TEXTO)
    fuente = encontrar_fuente()
    
    print(f"🔤 Fuente: {fuente}")
    print(f"✂️  Crop: {int(CROP_PCT*100)}% arriba y derecha")
    print(f"🎙️  Voz: {VOZ_TTS}")
    print(f"💬 Subtítulos: Estilo Reels (Máx {SUBTITULO_MAX_WORDS_LINE} palabras por línea)")

    videos_disp = sorted(
        (f.replace(".mp4", "") for f in os.listdir(CARPETA_VIDEOS)
         if re.fullmatch(r'Video_\d+\.mp4', f)),
        key=lambda x: int(x.replace("Video_", ""))
    )

    # videos_disp = videos_disp[:1] # Prueba con 1 video

    carpeta_temp = tempfile.mkdtemp(prefix="voz_")
    total = len(videos_disp)
    exitos = 0

    try:
        for i, nombre in enumerate(videos_disp, start=1):
            entradas = bloques.get(nombre, [])
            print(f"\n[{i}/{total}] 🎬 {nombre} ({len(entradas)} bloques)")
            if editar_video(nombre, entradas, fuente, carpeta_temp):
                print(f"   ✅ Guardado en Videos_Editados/{nombre}.mp4")
                exitos += 1
    finally:
        shutil.rmtree(carpeta_temp, ignore_errors=True)

    print(f"\n🎉 Terminado. {exitos}/{total} videos editados.")

if __name__ == "__main__":
    main()