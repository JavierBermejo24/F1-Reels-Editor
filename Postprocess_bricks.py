"""Post-process "Video Bricks": remove F1 watermark + trim heads.

For every .mp4 in "Video Bricks":
  - TL (top-left logo)    -> cut top 22% + centered sides (keeps 9:16), scale back to 1080x1920.
  - BL (bottom-left logo) -> cut bottom 18% + centered sides (keeps 9:16), scale back to 1080x1920.
  - Trim leading seconds where specified (take-specific).
  - Files with no logo and no trim are copied untouched (stream copy).

Aspect ratio is always maintained (no stretching): the crop window itself
is 9:16, then it is scaled back to the original WxH.

Output: "Post Processed Videos/<same filename>.mp4"

Usage:
    python Postprocess_bricks.py
    python Postprocess_bricks.py --overwrite   # re-encode even if output exists
"""
import os
import re
import subprocess
import sys

import imageio_ffmpeg

# ============ CONFIG ============
CARPETA_SCRIPT = os.path.dirname(os.path.abspath(__file__))
CARPETA_BRICKS = os.path.join(CARPETA_SCRIPT, "Video Bricks")
CARPETA_SALIDA = os.path.join(CARPETA_SCRIPT, "Post Processed Videos")

TOP_CUT_PCT = 0.22     # TL logos live in the top ~8-18%: cut 22% + margin
BOTTOM_CUT_PCT = 0.18  # BL logos live in the bottom ~6-11%: cut 18% + margin

# Logo position per Video group (applies to ALL takes of that Video).
# TL = top-left, BL = bottom-left, None = no watermark -> no crop.
LOGO_POR_VIDEO = {
    1: "TL", 2: "TL", 3: "TL", 4: "TL",
    6: "TL", 7: None,  # Video 7: trim only, no watermark spotted
    8: "TL", 9: "BL", 10: "TL",
    11: "TL",  # not in user's list, but TL watermark spotted -> cropped
    12: None, 15: None, 19: None,  # no watermark spotted -> copied as-is
    16: "BL", 17: "BL", 18: "BL",
    20: "TL", 21: "TL", 22: "TL", 23: "TL", 24: "TL", 25: "TL",
    26: "TL", 27: "TL", 28: "TL", 29: "TL", 30: "TL", 31: "TL",
    # Video 5/13/14/32: no bricks in folder -> nothing to do.
}

# Leading seconds to remove, per exact take filename.
TRIM_POR_TAKE = {
    "Video_4_take01.mp4": 6.0,
    "Video_7_take01.mp4": 4.0,
    "Video_8_take01.mp4": 6.0,
    "Video_21_take01.mp4": 2.3,
    "Video_22_take01.mp4": 5.0,
    "Video_25_take01.mp4": 4.0,
    "Video_29_take01.mp4": 4.0,
    "Video_30_take01.mp4": 4.0,
}

SKIP_EXISTING = "--overwrite" not in sys.argv
# =================================


def dims_y_duracion(ruta):
    """Width, height, duration, has_audio via moviepy (no re-encode)."""
    from moviepy.editor import VideoFileClip
    clip = VideoFileClip(ruta)
    try:
        return int(clip.w), int(clip.h), float(clip.duration), clip.audio is not None
    finally:
        clip.close()


def ventana_recorte(w, h, donde):
    """Crop window (w2, h2, x, y) that removes the logo and keeps 9:16."""
    if donde == "TL":
        cut = int(round(h * TOP_CUT_PCT))
        h2 = h - cut
        w2 = int(round(h2 * 9.0 / 16.0)) - (int(round(h2 * 9.0 / 16.0)) % 2)
        x = (w - w2) // 2
        return w2, h2, x, cut
    if donde == "BL":
        cut = int(round(h * BOTTOM_CUT_PCT))
        h2 = h - cut
        w2 = int(round(h2 * 9.0 / 16.0)) - (int(round(h2 * 9.0 / 16.0)) % 2)
        x = (w - w2) // 2
        return w2, h2, x, 0
    raise ValueError(donde)


def procesar_uno(entrada, salida, logo, trim):
    from moviepy.editor import VideoFileClip  # noqa: F401 (kept for parity)
    w, h, dur, has_audio = dims_y_duracion(entrada)
    if trim >= dur - 0.3:
        print(f"   ⚠️  {os.path.basename(entrada)}: trim {trim}s >= duración {dur:.2f}s -> SKIP")
        return False
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-v", "error"]
    if trim > 0:
        cmd += ["-ss", f"{trim:.3f}"]
    cmd += ["-i", entrada]
    if logo in ("TL", "BL"):
        w2, h2, x, y = ventana_recorte(w, h, logo)
        vf = f"crop={w2}:{h2}:{x}:{y},scale={w}:{h}"
        cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]  # no crop -> no re-encode
    if has_audio:
        cmd += ["-c:a", "aac"]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", salida]
    print(f"   {'✂️ ' + logo if logo else '📋 copy'} "
          f"trim={trim:g}s {w}x{h} {dur:.1f}s -> {os.path.basename(salida)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(salida):
        print(f"   ❌ ffmpeg falló: {res.stderr.strip()[:300]}")
        return False
    return True


def main():
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    archivos = sorted(f for f in os.listdir(CARPETA_BRICKS)
                      if f.lower().endswith(".mp4"))
    if not archivos:
        print(f"No hay .mp4 en {CARPETA_BRICKS}")
        return
    print(f"🧱 {len(archivos)} bricks -> {CARPETA_SALIDA} "
          f"({'skip existing' if SKIP_EXISTING else 'overwrite'})")
    ok = omitidos = fallos = 0
    for f in archivos:
        entrada = os.path.join(CARPETA_BRICKS, f)
        salida = os.path.join(CARPETA_SALIDA, f)
        if SKIP_EXISTING and os.path.exists(salida):
            omitidos += 1
            continue
        m = re.match(r"Video_(\d+)_take\d+\.mp4$", f, re.I)
        grupo = int(m.group(1)) if m else None
        logo = LOGO_POR_VIDEO.get(grupo)
        trim = TRIM_POR_TAKE.get(f, 0.0)
        try:
            if procesar_uno(entrada, salida, logo, trim):
                ok += 1
            else:
                fallos += 1
        except Exception as e:
            print(f"   ❌ {f}: {e}")
            fallos += 1
    print(f"\n🎉 {ok} ok / {omitidos} ya existían / {fallos} fallos.")


if __name__ == "__main__":
    main()
