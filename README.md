# nano-banana-swap-v2

Pipeline limpo de geração de fotos e vídeos de IA com base em **referência (cena/vídeo)** + **foto da modelo**.
Versão enxuta do projeto `nano-banana-swap`, sem logs, scripts de retry e variações scratch.

## APIs (compartilhadas com o projeto antigo)

Mesmas keys Freepik (formato `FPSX...`):

```bash
# uma chave só
export FREEPIK_API_KEY="FPSX..."

# pool (recomendado para Kling V3 — daily cap por key)
export FREEPIK_API_KEYS="FPSX_key1,FPSX_key2,FPSX_key3"
```

## Antes de rodar

1. **Definir a modelo** (qualquer um dos dois caminhos):
   - **Drive público** — subir a foto-referência no Drive como link público e colocar:
     ```bash
     export MODEL_REF_ID="<drive_file_id>"
     export MODEL_REF_MIME="image/png"   # ou image/jpeg
     ```
     Usado por `swap.py` e `batch.py`.
   - **Arquivo local** — colocar na raiz da pasta:
     - `modelo_ref.png` — foto full-body (referência principal para `kling_pipeline.py`)
     - `modelo_face.png` — recorte do rosto (opcional)

2. **Ajustar o prompt** em cada script conforme a persona da nova modelo (idade, etnia, restrições). O prompt atual é genérico.

## Scripts

| Script | O que faz | Entrada | Saída |
|---|---|---|---|
| `swap.py` | Coloca a modelo numa cena (single-shot, cena no Drive) | `<scene_drive_id> <filename>` | `out/<name>_swap.<ext>` |
| `batch.py` | Lote: percorre subpastas do Drive, faz swap em todas as imagens | `subfolders.json` + `MODEL_REF_ID` | `out/<sub>/<name>_swap.<ext>` + `state.json` |
| `outfit_swap.py` | Mantém imagem local, troca só a roupa | `<input_path> --prompt "<...>" --output-dir <dir>` | `<dir>/<name>` |
| `bg_swap.py` | Mantém o sujeito local, troca só o fundo | `<input> --prompt "<...>" --out <path>` | `<path>` |
| `kling_pipeline.py` | Vídeo-ref → 1º frame → swap → Kling V3 motion control → vídeo final | `kling_folder_list.json` + `modelo_ref.png` | `kling_out/fotos/`, `kling_out/finals/` |

## Exemplos

```bash
# 1. Single-shot swap
export FREEPIK_API_KEY="FPSX..."
export MODEL_REF_ID="<drive_id>"
python swap.py 1AbCxyz... cena.png --resolution 2K

# 2. Batch de subpastas Drive
echo '[["1","<folder_id_1>"],["2","<folder_id_2>"]]' > subfolders.json
python batch.py

# 3. Trocar só a roupa
python outfit_swap.py out/1/cena_swap.png \
  --prompt "swap outfit to bodycon black dress, knee-length, fitted at waist" \
  --output-dir out_outfit

# 4. Trocar só o fundo
python bg_swap.py out/1/cena_swap.png \
  --prompt "replace background with copacabana beach at golden hour, keep subject pixel-perfect" \
  --out out_scenes/cena_beach.png

# 5. Pipeline completo de vídeo (precisa modelo_ref.png + kling_folder_list.json)
export FREEPIK_API_KEYS="key1,key2,key3"
python kling_pipeline.py --phase fotos          # só gera fotos a partir dos frames
python kling_pipeline.py --phase videos         # só completa Kling onde já tem foto
python kling_pipeline.py                        # tudo de ponta a ponta
```

## Dependências Python

- Stdlib (urllib, json, base64, etc.)
- `opencv-python` (só `kling_pipeline.py`)
- `imageio-ffmpeg` (só `kling_pipeline.py`, opcional — re-encoda vídeo final pra IG)
- `curl` no PATH (upload pra catbox.moe / tmpfiles.org)

## Estado / retomada

- `batch.py` → `state.json` (done/failed por scene_id)
- `kling_pipeline.py` → `kling_state.json` (estágios por vídeo)

Apagar esses arquivos zera o progresso — guarde-os.
