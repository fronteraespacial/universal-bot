# Guardia de subida de audio y video

Caso **2026-09-30**, hilo de Santi en el foro prueba: un cuerpo de error de **223 bytes** se subió como `How_To_Orbit_8db623fe72.mp4` y el bot dijo que estaba listo. El archivo no reproducía.

El gateway que use este molde tiene que llamar `validate_media_download` **antes** de adjuntar, y `verify_attachment` con el `size` que devuelve Discord.

Rechaza:

- status HTTP fuera de 2xx (`http_status`)
- video de menos de 50 KB, o audio de menos de 1 KB, cuando el nombre o el mime dicen que es media (`suspicious_small_file`)
- HTML, XML o JSON disfrazados de archivo
- `Content-Length` distinto de los bytes recibidos (salvo corte explícito por el tope)
- magic bytes que no coinciden con la extensión (`ftyp` para mp4/m4a, EBML para webm/mkv, `OggS`, `ID3`/frame MP3, `fLaC`, `RIFF`/`WAVE`)

El filtro viejo (menos de 32 bytes, o mime con `html`) **acepta** el stub de 223 bytes. Este módulo no.

No descarga ni habla con Discord. Quien integre el gateway pasa los bytes, el status y los headers.
