# Motion artwork

Echora can render a short, song-guided looping video for each track and play it in the full-screen player. It is optional and off by default.

Rendering uses [LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) through ComfyUI. The cover is the first frame and the model animates freely from there for 5 seconds. The saved loop plays that clip forward and then straight back to the cover, so each loop lasts 10 seconds and wraps seamlessly. Prompts therefore describe one forward movement that also looks natural reversed. The prompt describing each loop comes from one of three sources:

- **External AI**: the vision model configured under Settings → External AI receives the cover, song title, artist, album and full available lyrics, then writes an animation caption. It must accept images. Lyrics guide the theme but are treated as data, not instructions.
- **Built-in Gemma**: Gemma 4 E2B runs locally inside ComfyUI using the LTX image-to-video chat format.
- **Same prompt for every track**, with `{title}`, `{artist}`, `{album}` and `{lyrics}` placeholders.

## How it runs

Motion artwork is a stage of ordinary analysis batches, run by the analysis worker. There is no separate service.

1. Sync and import batches run their other stages first. Those stages release their models when they finish.
2. The motion artwork stage loads each track's cover, metadata and lyrics, then works out which tracks still need a loop. Identical cover downloads are cached within the batch. If none need work, ComfyUI is not started.
3. The rest runs in three phases, each in its own short-lived ComfyUI process, so only one large model is loaded at a time:
   1. **Prompts.** The External AI model (over its API, without ComfyUI) or the built-in Gemma writes a description for every new cover. Skipped with a fixed prompt.
   2. **Encodings.** The LTX text encoder encodes every prompt to a small file (about 0.5 MB each).
   3. **Video.** LTX renders every loop from those encodings, without loading the text encoder.

   ComfyUI stops after each phase, which frees all of its GPU and system memory before the next model loads, and after the last phase before the next batch.

ComfyUI is installed in the GPU analysis image at `/opt/comfyui`, in its own virtual environment so its package versions do not affect Echora's. It listens on a random local port and keeps its inputs, outputs, encodings and state in a temporary directory that is removed with each batch. The CPU image does not include it; there the stage is skipped. Each batch's summary records how long each phase took (`motion_artwork.timings`).

If ComfyUI is missing, cannot start or has no models, the stage is skipped and recorded in the batch summary. The rest of the sync is unaffected.

An administrator can enter an external ComfyUI URL instead (or set `ECHORA_COMFYUI_URL`). Echora then writes all prompts first and renders with the prompt text, since that ComfyUI cannot read Echora's encoding files, and asks it to release its memory after each batch. That ComfyUI needs the same models and a recent enough version for the LTX-2.5 and `TextGenerate` nodes.

## Requirements

- An NVIDIA GPU and the GPU analysis image. The default 1536 × 1536 loop needs the whole of a 24 GB card and takes about 4 minutes per track on an RTX 3090. 1024 takes about 1–2 minutes and 768 about 35 seconds.
- About 44 GB of model files and plenty of system memory. A 1536 render peaked at 57 GB of RAM on a 62 GB machine with the rest of the stack running.
- A Hugging Face token with access to the gated `Lightricks/LTX-2.5` repository. Accept its license on Hugging Face first.
- One analysis worker per GPU while generation is enabled. Two workers sharing a GPU could render and analyse at the same time and run out of memory.

## Set up

Save your Hugging Face token in **Settings → Analysis models → Model downloads** (stored encrypted, shared with Modal). Then download the models into the shared Hugging Face cache. Only the four files ComfyUI loads are fetched, at pinned revisions, not the whole repositories:

```sh
docker compose run --rm --no-deps -e HF_HUB_OFFLINE=0 analysis \
  python -m echora_analysis.download_models --motion-artwork
```

The command uses the saved token; `-e HF_TOKEN=hf_...` overrides it.

To render on Modal instead, switch on **Generate during syncs: Modal**. The next Modal sync downloads these models to Modal with the same token ([docs/modal-compute.md](modal-compute.md)).

Setting `ECHORA_MOTION_ARTWORK_MODELS=true` in `.env` does the same as the flag. It also keeps these snapshots under cache management, so startup pruning removes them when their pinned revision changes.

Then, as an administrator, open **Settings → Motion artwork**, turn it on and save. The page shows whether ComfyUI is available and which model files are missing. Loops are made by library syncs and imports: run an entire-library sync to render loops for the existing library. There is no separate generation job; progress shows in the sync's batches.

## What gets rendered

- Every track gets its own loop, even when several tracks share an album cover.
- The title, artist, album and full available lyrics guide the prompt. Identical cover bytes are downloaded once per batch, but each track still renders separately.
- A track that already has a loop for the current settings is skipped.
- **Clear all loops** (Settings → Motion artwork) deletes every loop and video file for all users. It is refused while a sync or import is running; the next sync renders them again.
- Changing rendering or prompt settings starts a new set of loops on the next run.
- Entire-library syncs include songs that need a loop. New-tracks-only syncs render loops for the new songs.

A track that fails to render is recorded and retried on the next run.

## Settings

| Setting | Default | Notes |
| --- | --- | --- |
| Generate during sync | On | Render missing loops in sync and import batches. Off pauses generation. |
| External ComfyUI URL | Blank | Blank uses the built-in ComfyUI. |
| Resolution | 1536 × 1536 | 512, 768, 1024 or 1536. Rendered natively, not upscaled. |
| Loop length | 5 seconds | Or 4 seconds, at 24 fps. |
| Seed | 42 | Blank picks a new seed per album. |
| Hold to the cover at the turnaround | Off | A partial cover keyframe on the last rendered frame, where playback reverses. Keeps the loop closer to the cover, with less movement. |
| Prompt source | Built-in Gemma | External AI, built-in Gemma, or one fixed prompt for every cover. |
| Instructions | Built-in | Subject and environmental motion to aim for. Both generated-prompt sources use a stationary-camera caption template; custom instructions cannot override this requirement. Prompts requesting camera movement are rewritten with corrective feedback, up to three attempts. Repeated failures are recorded without rendering and retried on the next sync. |

### Prompt strategy

Gemma and External AI share an image-to-video caption format adapted from [Lightricks' Gemma 4 I2V template](https://github.com/Lightricks/LTX-2/blob/main/packages/ltx-core/src/ltx_core/text_encoders/gemma/encoders/prompts/gemma4_i2v_system_prompt.txt), [LTX-2.5 prompting guide](https://ltx.io/blog/ltx-2-5-prompt-guide), and [image-to-video guide](https://docs.ltx.io/open-source-model/usage-guides/image-to-video). Captions ground the action in the first frame, state shot type and viewpoint, and describe observable motion chronologically in one flowing paragraph. Detail follows scene complexity, normally 4–8 sentences, without a minimum word count or mandatory second event. Ambient movement is included only when the artwork supports it. Photographic effects are not added to drawings; speech is not invented from lyrics. Sound descriptions are optional in Echora's video-only renderer.

Echora adds two playback requirements: the camera remains stationary with constant framing and scale, and scene motion must look natural in reverse. The built-in writer uses the Gemma 4 chat format directly through `TextGenerate`, replacing ComfyUI's caption template, which otherwise encourages camera movement. External AI follows the same instructions and returns a JSON envelope. Gemma 4 E2B is the official local enhancer; another vision-capable model can write the caption through External AI. The separate LTX text encoder remains unchanged.

Camera-movement detection checks caption text, not the finished video, so this cannot guarantee a stationary result. Fixed prompts remain user-controlled and bypass the generated-prompt checks. Changes to the shared writer revision invalidate loops from both generated-prompt sources on the next sync, including those with saved custom instructions.

Community reports favoring simpler prompts ([Reddit discussion](https://www.reddit.com/r/StableDiffusion/comments/1vly93b/the_simple_secret_to_better_ltx_25_results/)) are anecdotal and sometimes still show unwanted zooming. They support keeping actions focused, rather than adopting a new prompt syntax or claiming a reliable camera fix. A [GitHub issue](https://github.com/Lightricks/LTX-2/issues/11) reports similar slight zooms in earlier LTX image-to-video generation; it is not evidence specific to LTX-2.5.

Deployment settings:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `ECHORA_MOTION_ARTWORK_PATH` | `./data/motion-artwork` | Host directory for the videos, separate from model storage. Compose mounts it at `/motion-artwork`. |
| `ECHORA_MOTION_ARTWORK_DIR` | `/data/motion-artwork` | Video directory inside the containers. Compose sets `/motion-artwork`. |
| `ECHORA_COMFYUI_URL` | blank | An external ComfyUI to use when the Settings URL is blank. Blank starts the built-in one. |
| `ECHORA_COMFYUI_DIR`, `ECHORA_COMFYUI_PYTHON` | `/opt/comfyui`, `/opt/comfyui-venv/bin/python` | The built-in ComfyUI. |
| `ECHORA_COMFYUI_STARTUP_TIMEOUT_SECONDS` | `300` | How long a batch waits for ComfyUI to start. |
| `ECHORA_MOTION_ARTWORK_MODELS` | `false` | Download and manage the models in `download_models`. |
| `ECHORA_MOTION_ARTWORK_RENDER_TIMEOUT_SECONDS` | `3600` | Per album. |

Avoid other heavy GPU use, including video playback on the same card, during long generation runs. ComfyUI's dynamic memory paging fails (`Fault failed: 2`) when another process takes the memory it planned to use.

## Playback

The full-screen player plays the loop muted over the cover and fades it in once it can play. It pauses and resumes with the music. A **Still / Motion** switch under the track details appears when a loop exists. The choice is saved in the browser and starts as Still when the system asks for reduced motion.

Videos are served at `/motion-artwork/{id}.mp4` (through the `/api` media path) only to users whose library contains a track with that cover. They are H.264 MP4 files of about 4–5 MB at 1536.

Delivering motion artwork to other Navidrome clients is not implemented yet.
