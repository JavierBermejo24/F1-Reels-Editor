import asyncio
import edge_tts
import os

# Frase de prueba (puedes cambiarla por una de tu guion de F1)
TEXTO_PRUEBA = "Aero Performance and Aero Design are two different roles in Formula 1."
CARPETA_SALIDA = "Muestras_Voces"

async def generar_muestras():
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    
    print("🔍 Obteniendo lista de voces...")
    todas_las_voces = await edge_tts.list_voices()
    
    # --- FILTRO: Solo voces en inglés ---
    # Si quieres TODAS las voces (más de 300), comenta la siguiente línea:
    voces_filtradas = [v for v in todas_las_voces if v["Locale"].startswith("en-")]
    
    # Para generar TODAS las voces, usa esta línea en su lugar:
    # voces_filtradas = todas_las_voces

    total = len(voces_filtradas)
    print(f"🎙️ Generando {total} muestras en la carpeta '{CARPETA_SALIDA}'...\n")

    for i, voz in enumerate(voces_filtradas, 1):
        nombre_voz = voz["ShortName"]
        genero = voz["Gender"]
        localizacion = voz["Locale"]
        
        # Nombre de archivo limpio: ej. "en-US-GuyNeural_Male.mp3"
        nombre_archivo = f"{nombre_voz}_{genero}.mp3"
        ruta_salida = os.path.join(CARPETA_SALIDA, nombre_archivo)

        try:
            communicate = edge_tts.Communicate(TEXTO_PRUEBA, nombre_voz)
            await communicate.save(ruta_salida)
            print(f"[{i}/{total}] ✅ {nombre_voz} ({genero}) -> {nombre_archivo}")
        except Exception as e:
            print(f"[{i}/{total}] ❌ Error con {nombre_voz}: {e}")

    print(f"\n🎉 ¡Listo! Tienes {total} archivos MP3 en la carpeta '{CARPETA_SALIDA}'.")

if __name__ == "__main__":
    asyncio.run(generar_muestras())