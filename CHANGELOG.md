# Changelog

What was built and changed, newest first. Dates are IST.

## 21 Oct 2026 · Web features with Tavily: free assets, licences, b-roll plans

Details, requests, credits and limits: [docs/tavily.md](docs/tavily.md).

- **Free on the web.** Search results end with a "Free on the web" section. When the library has no match it runs by itself; otherwise one click. One Tavily search on the free sites for that type (videos: Pexels, Pixabay, Mixkit; photos: + Unsplash, Openverse; sounds: Freesound, Pixabay, Mixkit; templates: Mixkit). Item pages come first, each with its own thumbnail and the site's usual licence as a badge.
- **Save to Inbox.** Reads the item's page with Tavily Extract, picks the file (right type, site file server, largest size), reads the licence, downloads the file into the Inbox folder (`.part` until complete, 800 MB cap, web pages refused, nothing overwritten), adds the Inbox to the library and indexes the file with its licence and source page attached.
- **Where did this file come from?** Recognises stock file names from Pexels, Pixabay, Mixkit, Unsplash and Freesound (`pexels-cottonbro-5698420.jpg`, `3195394-uhd_3840_2160_25fps.mp4`, `123456__user__name.wav`, `mixkit-…-166.wav`, …), finds each page (address from the name, or a Tavily search that must match the item number) and reads the licence.
- **Licence reading.** Rules first (CC0, CC BY, CC BY-SA, CC BY-NC, Sampling+, Mixkit Free or Restricted, the Pexels, Pixabay and Unsplash licences), then Nemotron Nano for the credit line and anything the rules could not decide. A licence found on the page is never replaced by the model's wording. Creative Commons licences link to their deed.
- **Licences view** (new nav item): counts that double as filters (credit needed, not commercial, check the item, not checked), one row per file with licence, credit, Copy, Page and Check, **Check N files** in the background with progress, **Copy credits** for a video description. Pages are read in batches of up to 20 per request, about 1 credit per 5 files.
- **Details panel**: a Licence block with badges, licence, source page, credit (Copy), note and how it was checked; "Find the licence" for files that look like stock downloads.
- **B-roll plan** (new nav item): topic, optional script, length, research on or off. Tavily researches the topic (with an answer), Nemotron 3 Ultra writes a title, hook, beats with a shot each and sourced facts, and each shot is searched in the library (top 3, video shots open at their timecode). Beats with no footage offer free items from the web. Copy plan. Falls back to Super, then Nano, then a split of the script.
- **Settings**: Inbox folder; Tavily key help; Tavily requests, cache hits and credits in the Engine panel; the Privacy panel says what goes to Tavily.
- **CLI**: `web`, `source`, `broll`; `doctor` sends a Tavily test search.
- Every Tavily response is cached in `library.db` (searches 1 day, page reads 7 days). Local only turns all web features off.
- New: `engine/caa/tavily.py`, `engine/caa/sources.py`, `engine/caa/broll.py`, `downloads` table, settings `inbox_dir` and `web_results`, `tavily` and `audit` in `/api/status`, `source_guess` in asset details, 8 API routes. 18 new tests (65 in total).

## 20 Oct 2026 · Windows installer, keys and connections in Settings

- **Installer.** `scripts\build.ps1` builds `CreatorAssetAssistant-Setup-0.1.0.exe`: the official embeddable Python matching `.venv`, the engine's packages pinned to the versions in `.venv`, the engine, the UI, the Visual C++ runtime DLLs and FFmpeg, wrapped in the Electron app by electron-builder (NSIS, per-user, no admin, choice of folder, Start menu and desktop shortcuts). The script checks the bundle's imports and starts the bundled engine once before building. Options: `-Lite`, `-NoFFmpeg`, `-SkipRuntime`, `-NoSmokeTest`. Embeddable Python was chosen over PyInstaller because Transformers, keyring and uvicorn load modules dynamically, which PyInstaller misses.
- The desktop app runs the bundled engine from `resources\python` and `resources\engine` when installed, and the developer `.venv` otherwise. New app icon (`electron\assets`), also used for the window and the installer.
- **Keys & connections** in Settings: paste the Nebius Token Factory and Tavily API keys (stored in the system keychain, only the last four characters shown), **Test** the Nebius key (lists the models on the account and fills the model pickers), Token Factory URL, date order for searches, FFmpeg folder, the Nemotron model for each role, and the data folder. Changes apply without a restart. Environment variables still work; keys saved in the app take priority, and environment variables that override the app are listed.
- API: `POST /api/settings` accepts `nebius_api_key`, `tavily_api_key`, `tokenfactory_base_url`, `date_order`, `ffmpeg_dir` and `models`, validates them, and never returns a key.

## 20 Oct 2026 · Dates in search, revisited

- **Either-way dates.** A date like `9-6-2026` is 9 June in day-month order (the Windows setting in India) and 6 September in month-day order. When both numbers are 12 or under, search now checks both: it uses the reading that has footage and says so ("Read 9-6-2026 as 6 Sep 2026, because nothing was recorded on 9 Jun 2026"). If both readings have footage it keeps your Windows order and offers "Did you mean 6 Sep 2026?".
- **No dead ends.** If nothing was recorded at the date or time asked, search shows the closest recordings in time, or the best matches for the other words from any date, labelled "No exact match for" with the reason.
- **Recording details in meaning search.** Each shot's text now also says how and when it was recorded, for example "vertical video clip recorded on Sunday 6 September 2026 in the morning, shot on Samsung SM-S928B", so "sunday morning clips", "september footage" or "shot on samsung" match by meaning. Exact dates and times still go through the date filter, because embeddings do not match numbers exactly. The vectors are rebuilt once at start-up, locally, with no re-indexing.
- Meaning and look searches are now limited to the files from the requested date before ranking, so a date plus words ranks only that day's footage.

## 20 Oct 2026 · Local meaning search (no API call per search)

- Added meaning search with a local multilingual text-embedding model, `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions, Apache 2.0). Each shot is embedded once from its Nemotron description, tags, speech, file name and folder; a search is embedded on the computer and compared in milliseconds. Works across 50+ languages.
- Search now fuses three local signals (meaning, keywords, look) instead of calling Nemotron Nano for every search. Before: about a second per search (budget up to 6 s) and roughly $0.00006 per search. Now: no API call and no cost per search.
- Nemotron search expansion became an option (Settings → Search, off by default). It is used automatically only while the meaning model is unavailable.
- **Find similar** now combines look (SigLIP) and meaning, and works for sounds too.
- Existing libraries get meaning vectors at start-up from the saved descriptions, with no re-indexing and no API calls.
- Privacy: in Standard mode search text no longer leaves the computer.
- `doctor` loads the meaning model and checks that "jogger in a storm", "fire for chroma keying", "relaxing beats" and a Hindi query each find the right description.
- New: `engine/caa/textembed.py`, `text_vectors` table, `semantic` block in `/api/status`, settings `semantic_search`, `text_model`, `nemotron_search`.

## 20 Oct 2026 · Re-indexing fix, faster indexing, details panel, top results

- **Fixed: files were re-indexed after every restart.** Windows reports a file being opened as a change, and the app opens videos itself to show frames and play clips. The watcher queued those files again. Files are now re-indexed only when their size or modified time changes; files that failed before are retried only when you press Rescan. Paths are normalised before they are looked up, so a watcher event and a folder scan find the same record.
- **Parallel descriptions.** All shots of a video are sent to Nemotron Super VL at once (up to 8 at a time, `caption_workers`) instead of one after another. While they run, thumbnails, chroma checks and SigLIP vectors are computed, and Parakeet transcribes the speech in parallel.
- **Two files at a time** (`index_workers`). Photos and templates start their Nemotron request before the local work.
- **Faster shot detection.** When a video has a keyframe at least every second (phones and DJI usually do), shots are found from keyframes only. On a 10-second 4K 60 fps test clip this step went from 4.3 s to 0.4 s. Other videos decode at 2 fps, skipping non-reference frames and trying GPU decoding first.
- Frames from 1440p and larger videos are grabbed by parallel FFmpeg processes.
- The engine log has one line per video with the time of each step (shots, frames, local, describe, speech).
- **Details panel fix.** With many tags and shots, the video preview was drawn over the title, description and buttons. Fixed. The panel now has a Description box: the sentence plus subjects, setting, action, shot type, camera, mood, colours and on-screen text, and it changes when you click a shot. The extra details are stored for files indexed from this version on (`segments.details`).
- **Top results.** Search shows one ranked list, best first, numbered 01, 02, … with "Show top 5 / 10 / 20 / 50" above it (`top_results`, also in Settings → Search). Tabs narrow to one type.
- Find similar is limited to the same number of results.
- Settings: new Search panel; Engine panel shows how many shots and files are described at a time.

## 20 Oct 2026 · New look

- Restyled the whole app to the reference design: light grey grid with thin lines, orange accents (`#ff6d1f`), monospace text, cut-corner orange buttons, corner brackets on frames, small orange square markers.
- Top navigation replaces the sidebar: wordmark ("Creator / ASSET ASSISTANT", no icon), Home, Videos, Images, Sounds, Templates with counts, Folders & privacy, Add folder. The macOS-style window buttons stay.
- Home: a large scrolling headline, an intro with the library count and quick searches, a featured frame with previous/next arrows and a preview of the next one, a strip of counts per type, and rows of recent assets.
- Search row across the top with indexing progress beside it (current file shortened with "…", count, progress line). A right-hand rail holds engine status, Rescan all, Shortcuts and Open engine log.
- **Asset Display**: a blocky headline font drawn for this project with fontTools (`scripts/build_font.py` → `ui/fonts/asset-display.ttf`), because fonts could not be downloaded and a local-first app should not load fonts from Google.
- Splash screen and window background restyled to match. The engine serves `.ttf` and `.woff2` with the right type on Windows.
- Earlier the same day: removed the square icon beside the wordmark and stopped long file names overflowing the indexing card.

## 19–20 Oct 2026 · Recording metadata and time search

- `metadata.py`: recording time from file names (`VID_`, `IMG_`, `PXL_`, `DJI_`, `dji_mimo_`, screen recordings, WhatsApp), photo EXIF, container tags (`creation_time`, QuickTime creation date) or the file date; GPS from ISO 6709 and EXIF; camera make and model. Stored on each asset and backfilled for files already indexed.
- `timeq.py`: dates and times in searches ("11:54am on 6/9/26", "yesterday morning", "last week", "September 2026"), using the Windows date order (`CAA_DATE_ORDER` overrides it). A time inside a clip returns the offset, and the clip opens at that second.
- Details panel: Recorded (with the source), Camera, Location with a map link. Cards show the recording date.
- The Nemotron search call got a 6-second budget with one quick retry, after a search took 15 s.

## 19–20 Oct 2026 · Search and green-screen accuracy

- Nemotron's guess about the type of asset is now a soft boost, not a filter. Before, "trees" showed only photos because Nemotron guessed "photo". Hard filters come only from words you type or from the tabs.
- Feedback memory became small and multiplicative, and your own words weigh more than Nemotron's added words.
- Green screen false positive (park grass flagged as keyable) fixed: all chroma measurements averaged across a shot's frames, stricter thresholds (hue spread under 3, saturation 140 and up), and Nemotron's "normal background" overrides the local flag. Files flagged before were re-checked once (`INDEX_VERSION` 2).

## 19–20 Oct 2026 · Desktop app

- Electron app: frameless window with macOS-style close, minimise and maximise buttons; starts the Python engine, shows a splash screen while it loads, reuses an engine already running on port 8765, single instance, engine log in the app's data folder, folder picker.
- First UI (dark, with a sidebar) built from the first reference screenshot; replaced by the new look on 20 Oct.
- The built-in timeline was removed at the creator's request; "Show in folder" is the main action.
- `scripts\run.ps1 -App` installs Electron on first run and starts the app.

## 19–20 Oct 2026 · Windows setup fixes

- FFmpeg discovery on Windows: environment variable, bundled `bin\`, PATH, the registry PATH, WinGet links and packages, `C:\ffmpeg`, Chocolatey, Scoop. A banner explains when FFmpeg is missing and offers "Check again". winget needs `--source winget` when the Microsoft Store source fails.
- Parakeet loads from a local model folder under the data folder, which avoids the ONNX external-data check failing on Hugging Face cache symlinks.
- `run.ps1` passes arguments straight to the engine (`run.ps1 doctor` used to fail).
- Token Factory roles are mapped to the models the account actually serves; when no Omni model exists, sounds are described by Nano from local audio analysis. Zero Data Retention turned on.

## 19 Oct 2026 · First build

- Engine (`engine/caa`): folder watcher, indexer, shot detection, keyframes, thumbnails, chroma and alpha detection, local audio analysis, template previews, SigLIP 2 vectors, Parakeet transcripts, Nemotron descriptions (Super VL for frames, Omni for sound, Nano for queries), SQLite with FTS5, an in-memory vector index stored in SQLite, hybrid search with feedback memory, HTTP API, and a CLI (`serve`, `index`, `search`, `doctor`, `models`, `set-key`).
- Privacy modes Local only and Standard; keys from `.env` or Windows Credential Manager.
- Test suite with a generated media library and a mock Token Factory.
- Setup and run scripts for Windows, macOS and Linux.

## 19 Oct 2026 · Plan

- Checked the idea against the Personal AI track and the judging criteria; researched other ideas and rejected country-specific ones because a global panel would ask how they work elsewhere.
- Wrote `plan.md` (v2): NVIDIA model for every job, privacy modes, data storage, Google Drive, free asset sources with Tavily, desktop app plus landing page plus hosted demo, schedule. The first plan is kept as `plan-v1.md`.
