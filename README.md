# Creator Asset Assistant

A private assistant for video creators. It indexes your footage, photos, music, sound effects and templates where they already live (local drives and your Google Drive for desktop folder) and lets you find anything by describing it, by when you shot it, or by what it looks like. Your files never leave your computer, and searches run on your computer too.

Built for the **Nebius x NVIDIA Global AI Hackathon**, Personal AI track. Licence: MIT.

Changes are logged in [CHANGELOG.md](CHANGELOG.md). The hackathon plan is in [plan.md](plan.md). A worked example of one clip going through indexing and search, with every model named, is in [docs/scenario-walkthrough.md](docs/scenario-walkthrough.md). Everything that uses the web (Tavily) is in [docs/tavily.md](docs/tavily.md).

## What it does

**Library and indexing**
- Watches the folders you add and indexes new files in the background. A file is indexed once and only re-indexed when its size or modified time changes, so restarting the app or opening a file does not trigger any work.
- Videos: shot detection, three keyframes per shot, thumbnails, green-screen and alpha detection, timecoded results per shot.
- Photos, design templates (`.mogrt`, `.aep`, Resolve, Final Cut, LUTs; preview files inside or next to the package), sounds and music (local analysis: punchy, riser, whoosh-like, tempo, loudness).
- Nemotron describes every shot, photo, template and sound once, at index time: a one-line description plus subjects, setting, action, shot type, camera movement, mood, colours, on-screen text and tags. Parakeet transcribes speech with word timings.
- Recording metadata: when each file was recorded (phone file names like `VID_20260906_115320856` or `DJI_20260911131448_0049_D`, photo EXIF, camera metadata, or the file date), the camera model and the GPS location.

**Search**
- Runs entirely on your computer, with no API call per search. Three signals are combined:
  - **Meaning**: a small multilingual text-embedding model compares your words with each shot's description, tags, speech and recording details. It understands related words ("jogger in a downpour" finds "a man running through heavy rain") and works in 50+ languages.
  - **Keywords**: exact words in names, descriptions, tags, transcripts and folder names (SQLite FTS5, BM25).
  - **Look**: SigLIP 2 matches your words against the frames themselves.
- **Dates and times**: "11:54am on 6/9/26", "dji 9-6-2026", "trees yesterday morning", "clips from last week", "September 2026". A time inside a clip opens it at that second. Dates follow your Windows date format; when a date could be read either way (9-6 is 9 June or 6 September), the app uses the reading that has footage and says so, and offers the other with "Did you mean…".
- **No dead ends**: if nothing was recorded at that moment, it shows the closest recordings in time, or the best matches for your other words from any date, and explains why.
- **Top results**: one ranked list, best match first. Choose to show the top 5, 10, 20 or 50; the choice is remembered. Tabs narrow to videos, images, sounds or templates.
- Filters from your words: type, duration ("under 3 seconds"), orientation ("vertical"), green screen.
- **Find similar** combines look and meaning, for videos, photos and sounds.
- **Memory**: "Good pick" and "Show in folder" rank an asset higher next time; "Not this" ranks it lower.
- Optional: ask Nemotron to expand each search (Settings → Search). Off by default; used automatically only if the meaning model cannot load.

**Web, with Tavily** (only when you ask; details in [docs/tavily.md](docs/tavily.md))
- **Free on the web**: when your library has no shot for a search, the app looks on Pexels, Pixabay, Mixkit, Unsplash and Freesound and shows free items with licence badges. **Save to Inbox** downloads the file into an Inbox folder, reads its licence from the item's page, and indexes it with the licence attached.
- **Where did this file come from?** Stock downloads keep their site's file names (`pexels-cottonbro-5698420.jpg`, `123456__user__name.wav`, `mixkit-…-166.wav`). The **Licences** view finds each file's page with Tavily and reads its licence: free to use, credit needed or not for commercial use, with a ready credit line. **Copy credits** gives the block for a video description.
- **B-roll plan**: type a topic (and paste a script if you have one). Tavily researches it, Nemotron 3 Ultra writes the beats and the shot for each, and every shot is searched in your library. Beats with nothing in the library get free suggestions from the web. Facts come with their sources.

**App**
- Desktop app (Electron) with macOS-style window buttons, a light grid design with orange accents, a monospace typeface and a blocky headline font drawn for this project.
- Home: a scrolling headline, a featured frame from your footage with previous/next arrows, counts per type, and rows of recent videos, sounds, images and templates.
- Detail panel: playable preview that loops the matched shot, the description box (changes per shot), shot strip, tags, speech, recording time, camera and map link.
- Status bar: indexing progress with the current file and count; right-hand rail for engine status, Rescan, Shortcuts and the engine log.
- Two privacy modes, switchable live: **Local only** and **Standard**.

## How we use NVIDIA and Nebius

| Component | Job | Where it runs | Status |
|---|---|---|---|
| Nemotron 3.5 Super VL | Describes keyframe strips, photos and template previews: description, subjects, setting, action, shot type, camera, mood, colours, on-screen text, background (green screen) and search tags. Up to 8 shots are described in parallel | Nebius Token Factory | Built |
| Nemotron 3 Nano Omni | Describes sound effects and music from a 10-second excerpt | Nebius Token Factory | Built (falls back to Nano when the account has no Omni model) |
| Nemotron 3 Nano 30B-A3B | Describes sounds from local audio analysis when Omni is unavailable; reads licence terms from free-asset pages; optional search expansion | Nebius Token Factory | Built |
| Nemotron 3 Super | Agent model for Hermes Agent | Nebius Token Factory | Next |
| Nemotron 3 Ultra | Plans b-roll: beats, shots and facts from Tavily research and your script | Nebius Token Factory | Built (falls back to Super, then Nano) |
| Parakeet-TDT 0.6B v3 | Speech transcripts with word timestamps (ONNX, CPU) | Your computer | Built |
| NemoClaw + OpenShell + Hermes Agent | Sandboxed always-on agent with memory and skills | Your computer (WSL 2 on Windows) | Next |
| Nebius Serverless Endpoint / Jobs, Object Storage | Hosted demo and batch indexing | Nebius AI Cloud | Next |

The model for each role is configurable; at start-up the engine reads `GET /v1/models` and maps each role to a model your Token Factory account actually serves (`caa models --apply` does the same by hand).

Two local models are not NVIDIA's, and why: SigLIP 2 (Google, Apache 2.0) for matching words to frames, because no NVIDIA open embedder covers natural images on a CPU laptop; and `paraphrase-multilingual-MiniLM-L12-v2` (Apache 2.0) for meaning search, because NVIDIA's NeMo Retriever text embedders run as NIM containers on NVIDIA GPUs, which most creators' laptops do not have.

## Privacy

| Mode | What leaves the computer |
|---|---|
| Local only | Nothing. New files are described by local analysis only |
| Standard (default) | For each new file, once: up to 3 downscaled keyframes per shot (384 px JPEG) and a 10-second audio excerpt, sent to Nebius Token Factory. Never full files. Search text stays on the computer unless you turn on Nemotron search expansion |
| Web features (Standard only, when you use them) | To Tavily: the words of a free-asset search, a stock file's **name** or page address, a b-roll topic. To Nemotron: a public licence excerpt, or the topic, your script and the research for a b-roll plan. Never your files |

Turn on **Zero Data Retention** for your Token Factory organisation; without it, Token Factory keeps inputs and outputs for speculative decoding. API keys are read from `.env` or the system keychain (`caa set-key`).

## How it works

```
Folders (local, Drive for desktop)
  │  watcher: new or changed files only (size + modified time)
  ▼
Indexer (2 files at a time)
  video: probe → shots (keyframes only when the video has one every second; else 2 fps with GPU decode) →
         3 frames per shot (parallel ffmpeg for 1440p and up) → thumbnails, chroma check, SigLIP vectors
         ├─ Nemotron Super VL: all shots described in parallel (up to 8 at once)
         └─ Parakeet: speech transcript, in parallel with the above
  photo / template: SigLIP vector + Nemotron description
  sound: local audio analysis + Nemotron Omni (or Nano) description + Parakeet when there is speech
  all: recording date, camera, GPS → SQLite; files saved from the web also get their licence and source page
  ▼
SQLite library.db: assets, shots, descriptions, FTS5 keyword index, SigLIP vectors, meaning vectors, feedback
  ▼
Search (local)
  date/time words → exact filter on recording time (with the either-way date check and fallbacks)
  other words → meaning + keywords + look → rank fusion → memory (good picks up, "not this" down) → top N

Web (Tavily, on request)
  free on the web: /search on free sites → Save to Inbox: /extract → file + licence (rules, Nemotron Nano) → Inbox → indexed
  licences: stock file names → page (address from the name, or /search) → /extract in batches → licence + credit
  b-roll plan: /search with answer → Nemotron Ultra beats → local search per beat → gaps → free on the web
```

The engine is a Python service (Starlette + uvicorn) on `127.0.0.1`; the UI is plain HTML, CSS and JavaScript served by the engine; the Electron app starts the engine, shows a splash screen while it loads and stops it on quit.

## Quick start (Windows)

Requirements: Python 3.10+, FFmpeg (the setup script installs it with winget), Node.js LTS for the desktop app, about 3 GB of disk for model runtimes.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
notepad .env
powershell -ExecutionPolicy Bypass -File scripts\run.ps1 doctor
powershell -ExecutionPolicy Bypass -File scripts\run.ps1 -App
```

Paste your Nebius API key in the app under **Folders & privacy → Keys & connections** (or put `NEBIUS_API_KEY=...` in `.env`). Then click **Add folder** (for Google Drive, add your Drive for desktop folder, for example `G:\My Drive\Assets`).

- `run.ps1 -App` opens the desktop app. The first run installs Electron into `electron\node_modules`. If an engine is already running on port 8765 the app reuses it; otherwise it starts one on the first free port from 8765 to 8784.
- `run.ps1` with no arguments runs the engine only; open http://127.0.0.1:8765 in a browser.
- `doctor` checks FFmpeg, SigLIP, the meaning-search model (including a Hindi query), Parakeet and every Nemotron role on your account.
- The first start downloads SigLIP 2 (~400 MB), the meaning-search model (~470 MB) and Parakeet (~1 GB). `setup.ps1 -NoModels` skips the model runtimes; search then uses keywords, file names, audio analysis and Nemotron descriptions.

macOS / Linux: `scripts/setup.sh` then `scripts/run.sh`.

## Build the Windows installer (.exe)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

Run it after `setup.ps1` on a Windows machine with Node.js, an internet connection and about 6 GB of free disk. It:

1. Downloads the official embeddable Python from python.org that matches the version in `.venv`.
2. Installs the engine's packages into it, pinned to the exact versions in `.venv`.
3. Copies the engine, the UI, the Visual C++ runtime DLLs and the FFmpeg found on the machine into `build\runtime`.
4. Checks that the bundled Python can import everything and starts the bundled engine once on port 8799.
5. Builds the installer with electron-builder (NSIS).

The result is `electron\dist\CreatorAssetAssistant-Setup-0.1.0.exe` plus a `.sha256` file. The installer runs per user without admin rights, lets the user choose the folder (default `%LOCALAPPDATA%\Programs\Creator Asset Assistant`), and adds Start menu and desktop shortcuts. The installed app needs no Python, Node or FFmpeg on the user's machine; on first start it downloads SigLIP 2, the meaning-search model and Parakeet (about 1.9 GB) like the developer setup does.

| Option | Effect |
|---|---|
| `-Lite` | Leaves out PyTorch, Transformers and Parakeet. Much smaller installer; search uses keywords and Nemotron descriptions (meaning and look search off) |
| `-NoFFmpeg` | Does not bundle FFmpeg; the app asks the user to install it |
| `-SkipRuntime` | Reuses `build\runtime` and only rebuilds the installer (after changing `electron\`) |
| `-NoSmokeTest` | Skips starting the bundled engine |

Notes:
- The installer is not code-signed, so Windows SmartScreen shows "Windows protected your PC". Users click **More info → Run anyway**. Publish the SHA-256 next to the download.
- If electron-builder cannot create symbolic links, the script retries without editing the app's `.exe` resources; the app works but its `.exe` keeps Electron's icon. Turn on Windows Developer Mode (Settings → System → For developers) and run the script again to fix that.
- The engine runs from the app's `resources\python` and `resources\engine` folders; data, settings and the log stay in the same places as the developer setup, so a developer install and the installed app share one library.

## Command line

```powershell
scripts\run.ps1 doctor                     # check FFmpeg, models, keys, and test each Nemotron role
scripts\run.ps1 models --apply             # list Token Factory models and map them to roles
scripts\run.ps1 index D:\Footage E:\SFX    # add folders and index them now, with time per file
scripts\run.ps1 search punchy whoosh       # search from the terminal
scripts\run.ps1 set-key NEBIUS_API_KEY xxx # store a key in Windows Credential Manager
scripts\run.ps1 web sunset beach --kind video --save 1   # free assets on the web; save result 1 to the Inbox
scripts\run.ps1 source D:\SFX\123456__user__rain.wav    # where a stock file came from, and its licence
scripts\run.ps1 broll "where coffee comes from"         # research and plan b-roll from your library
```

## Settings

Everything a user needs is in the app under **Folders & privacy**:

- **Keys & connections**: Nebius Token Factory API key (with a **Test** button that lists the models on your account), Tavily API key, Inbox folder for free assets saved from the web, Token Factory URL, date order for searches, FFmpeg folder, and the Nemotron model for each role. API keys are stored in the system keychain (Windows Credential Manager) and only the last four characters are ever shown; if the keychain is unavailable they go into `.env` in the data folder.
- **Privacy**, **Search** (top results, Nemotron search expansion) and **Engine** (what is running).

All other settings live in `settings.json` in the data folder.

| Setting | Default | What it does |
|---|---|---|
| `privacy_mode` | `standard` | `standard` or `local` (in the app: Privacy) |
| `top_results` | `10` | How many results a search shows (in the app: Show top 5 / 10 / 20 / 50) |
| `nemotron_search` | `false` | Also ask Nemotron to expand each search (in the app: Search) |
| `semantic_search` | `true` | Meaning search with the local text-embedding model |
| `text_model` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Model for meaning search |
| `embed_model` | `google/siglip2-base-patch16-224` | Model for matching words to frames |
| `asr_enabled` | `true` | Parakeet speech transcripts |
| `caption_workers` | `8` | Shots described by Nemotron at the same time |
| `index_workers` | `2` | Files indexed at the same time |
| `max_captioned_shots` | `12` | Longest shots per video sent to Nemotron |
| `keyframes_per_shot` | `3` | Frames per shot for descriptions and visual search |
| `models` | see `config.py` | Model ID for each Nemotron role (in the app: Keys & connections) |
| `tokenfactory_base_url` | `https://api.tokenfactory.nebius.com/v1` | OpenAI-compatible endpoint (in the app: Keys & connections) |
| `date_order` | `auto` | `auto` (Windows setting), `DMY`, `MDY` or `YMD` (in the app: Keys & connections) |
| `ffmpeg_dir` | empty | Folder with `ffmpeg.exe` and `ffprobe.exe`; empty = found automatically (in the app: Keys & connections) |
| `inbox_dir` | `%USERPROFILE%\Videos\CreatorAssets\Inbox` | Where free assets saved from the web go; added to the library on the first save (in the app: Keys & connections) |
| `web_results` | `8` | How many free items a web search shows |

Environment variables still work, for developers and scripts:

| Variable | Same as | Priority |
|---|---|---|
| `NEBIUS_API_KEY`, `TAVILY_API_KEY` | Keys & connections | A key saved in the app wins over the variable |
| `CAA_DATE_ORDER` | Date order | The app's setting wins unless it is "Windows setting" |
| `CAA_FFMPEG`, `CAA_FFPROBE` | FFmpeg folder | The app's folder wins when set |
| `CAA_PRIVACY_MODE`, `CAA_TOKENFACTORY_BASE_URL`, `CAA_EMBED_BACKEND` | Privacy, URL, embedder | The variable wins at start-up (the app lists active overrides) |
| `CAA_HOME` | Data folder | Variable only |
| `CAA_ALLOWED_HOSTS` | Host check for the API | Variable only |
| `CAA_PYTHON` | Python used by the desktop app | Variable only |

## Where data lives

| Data | Location |
|---|---|
| Your files | Where they already are. Never copied or moved |
| Free assets saved from the web | The Inbox folder (`%USERPROFILE%\Videos\CreatorAssets\Inbox` by default) |
| Licences and source pages | `library.db`: `assets.license`, `assets.source_url`, and the `downloads` table for saved files |
| Tavily and Nemotron responses | `library.db`, `cache` table (Tavily searches for a day, page reads for 7 days) |
| Index: assets, shots, descriptions, keyword index, SigLIP and meaning vectors, feedback | `%LOCALAPPDATA%\CreatorAssetAssistant\library.db` (SQLite) |
| Thumbnails and waveforms | `%LOCALAPPDATA%\CreatorAssetAssistant\thumbs\` |
| Settings | `%LOCALAPPDATA%\CreatorAssetAssistant\settings.json` |
| Parakeet model | `%LOCALAPPDATA%\CreatorAssetAssistant\models\` |
| SigLIP and meaning-search models | Hugging Face cache (`%USERPROFILE%\.cache\huggingface`) |
| Engine log (desktop app) | `%APPDATA%\Creator Asset Assistant\engine.log` (the page icon on the right of the app opens it) |

Set `CAA_HOME` to use another data folder. On macOS and Linux the data folder is `~/.creator-asset-assistant`.

## Engine API

| Route | Purpose |
|---|---|
| `GET /api/status` | Library counts, indexing progress, model states, meaning-search state |
| `GET/POST /api/folders`, `DELETE /api/folders/{id}`, `POST /api/folders/{id}/rescan`, `POST /api/rescan` | Watched folders |
| `GET /api/search?q=&kind=&limit=&gs=` | Search (`limit` = how many results) |
| `GET /api/assets`, `GET /api/assets/{id}`, `POST /api/assets/{id}/reveal` | Browse, details with shots, show in folder |
| `GET /api/similar/{shot_id}?limit=` | Find similar (look + meaning) |
| `GET /api/home` | Home rows and featured frames |
| `GET /api/thumb/{shot_id}`, `GET /api/poster/{shot_id}`, `GET /api/media/{id}` | Thumbnails, 1600 px frames, media with range requests |
| `POST /api/feedback` | Good pick, Not this, use, preview |
| `GET/POST /api/settings`, `GET /api/models` | Settings and Token Factory models |
| `GET /api/web/search`, `POST /api/web/save`, `POST /api/web/licence` | Free assets on the web, Save to Inbox, read a page's licence |
| `GET /api/licences`, `POST /api/licences/check`, `POST /api/licences/{id}` | Licences view, check one file or all, set a licence by hand |
| `POST /api/broll`, `POST /api/inbox` | B-roll plan; add the Inbox folder now |

Request and response details for the web routes are in [docs/tavily.md](docs/tavily.md#api).

The API only answers on `127.0.0.1` / `localhost` (host check and CORS).

## Project layout

```
engine/caa/
  api.py         HTTP API and static UI
  indexer.py     scanning, per-type indexing, parallel descriptions, change detection
  media.py       FFmpeg discovery (Windows), probing, shot detection, frames, chroma keying, waveforms
  audio.py       local sound analysis
  metadata.py    recording time, camera and GPS from file names, EXIF and container tags
  timeq.py       date and time parsing for search (date order, either-way dates, time windows)
  search.py      search: date filter, meaning + keywords + look fusion, memory, fallbacks, find similar
  textembed.py   meaning search: local text embeddings and the per-shot text
  embed.py       SigLIP 2 image/text embeddings
  vectors.py     in-memory vector index backed by SQLite
  nemotron.py    Token Factory client: model mapping, descriptions, retries, cache
  tavily.py      Tavily client: search, extract (batched), cache, usage counters
  sources.py     free sites, stock file-name recognition, licence reading, Save to Inbox, licence check
  broll.py       research → Nemotron Ultra beats → shots from your library
  asr.py         Parakeet transcripts
  db.py          SQLite schema and queries
  services.py    wiring, background model loading, start-up scan and backfills
  watcher.py     folder watcher
  cli.py         serve, index, search, doctor, models, web, source, broll, set-key
engine/tests/    unittest suite with a generated sample library, a mock Token Factory and a mock text model
ui/              App UI (HTML, CSS, JS; no build step) and ui/fonts/asset-display.ttf
electron/        Desktop app: frameless window, mac-style buttons, splash screen, starts and stops the engine;
                 assets/ holds the app icon; package.json holds the installer settings
scripts/         setup, run and build (installer) scripts; build_font.py regenerates the headline font
docs/            scenario-walkthrough.md: one clip from folder to search result; tavily.md: the web features
plan.md          Hackathon plan
CHANGELOG.md     What was built and changed, by date
```

## Tests

```powershell
cd engine
..\.venv\Scripts\python -m unittest discover -s tests -v
```

65 tests. The suite generates a small media library with FFmpeg, indexes it with a fake Nemotron and a fake text model, and checks: shot detection, chroma keying (including grass that is not a green screen), audio tagging, recording metadata, date and time parsing (either-way dates), time search that jumps inside a clip, fallbacks when nothing matches a date, meaning search without Nemotron, find similar, ranking, filters, feedback memory, that reading a file does not re-index it, parallel shot descriptions, saving keys and connection settings through the API (keys are never sent back), the HTTP API (range requests, host checks) and the folder watcher. `test_web.py` (18 tests) covers the Tavily features with a fake Tavily, a fake download and a fake Nemotron: stock file names, licence rules, Save to Inbox through indexing, the licence check, batched page reads, the b-roll plan and Local only blocking the web.

## Troubleshooting

| Problem | Fix |
|---|---|
| "FFmpeg is not installed" banner | `winget install --id Gyan.FFmpeg -e --source winget`, then press **Check again**. The engine also finds FFmpeg in WinGet, Chocolatey, Scoop and `C:\ffmpeg` |
| Parakeet fails to load | Run `doctor`; the model is stored under the data folder's `models\` to avoid Windows symlink issues |
| Sounds described "from audio analysis" | Your Token Factory account has no Omni model; Nemotron Nano describes the sound from local analysis instead |
| Meaning search shows "Off" | Run `doctor`; it needs `torch` and `transformers` (`pip install -r engine\requirements-ml.txt`) and downloads the model on first start. Search still works with keywords and look |
| A date finds the wrong day | Type it unambiguously ("6 Sep 2026", "Sep 6", "2026-09-06") or pick the date order under Keys & connections |
| Nemotron is off in the installed app | Paste the Nebius API key under Keys & connections and press **Test** |
| Installer build fails at "Downloading the embeddable Python" | python.org has no embeddable package for that exact version; the script tries earlier patch versions of the same Python automatically, so check the internet connection |
| "Tavily is off" | Add the key under Keys & connections and use Standard privacy. `doctor` sends one test search |
| Save to Inbox says "Open the page and download it there" | The site only gives the file to a browser. Download it from the page into the Inbox folder; the next licence check finds its page from the file name |
| Indexing feels slow | The engine log has a line per video with the time of each step (shots, frames, local, describe, speech) |

## Roadmap

Hermes Agent in an OpenShell sandbox with memory and self-written skills; a pre-publish check (licences of the files used in one video); Pexels, Pixabay and Freesound APIs next to Tavily; Google Drive API connector; landing page and hosted demo on Nebius; code signing for the installer.

## Licences of bundled or downloaded models and fonts

- Parakeet-TDT 0.6B v3: CC-BY-4.0 (NVIDIA)
- SigLIP 2: Apache 2.0 (Google)
- paraphrase-multilingual-MiniLM-L12-v2: Apache 2.0 (sentence-transformers)
- Nemotron models are called through Nebius Token Factory under their providers' terms
- Asset Display (the headline font in `ui/fonts`) and the app icon: drawn for this project by `scripts/build_font.py`, MIT
- FFmpeg, when bundled by `build.ps1`: the build installed on the build machine (for example the gyan.dev GPL build), shipped unmodified; source and licence at https://ffmpeg.org
- Python (embeddable package): PSF License
