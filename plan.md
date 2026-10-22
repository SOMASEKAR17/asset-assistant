# Creator Asset Assistant: Plan v2 (Personal AI Track)

A private, always-on assistant that indexes a creator's whole asset library (video, photos, templates, music, SFX, green screen clips) on their own machine and in their Google Drive, finds anything from a plain-language description, suggests the right asset while they edit, and fills gaps with free, properly licensed assets from the web.

> Updated 20 Oct 2026 (v2.1). The original plan is kept as `plan-v1.md`.
> Changes from v1: real deadline, global framing, every NVIDIA model given a concrete job, three privacy modes, data-storage map, Google Drive, free asset sources with Tavily, desktop app + landing page + hosted demo, 11-day schedule.
> v2.1: section 0.1 records what is built. Decisions that changed while building are marked **Changed** where they appear. The full log is in `CHANGELOG.md`.

---

## 0. Snapshot

| Item | Decision |
|---|---|
| Hackathon | Nebius x NVIDIA Global AI Hackathon (Devpost) |
| Track | Personal AI (also eligible for Best Use of Tavily) |
| Deadline | **Fri 30 Oct 2026, 10:00 AM PDT = 10:30 PM IST**. Internal target: submit by 6:00 PM IST |
| Judging | 1–15 Dec 2026. The demo URL must stay live until then |
| Product form | Windows desktop app (Electron, .exe) + landing page + hosted web demo |
| Core models | Nemotron 3.5 Super VL, Nemotron 3 Nano Omni, Nemotron 3 Super, Nemotron 3 Nano, Nemotron 3 Ultra (all on Token Factory), Parakeet-TDT (local). Local helpers: SigLIP 2 (look) and a multilingual text embedder (meaning search) |
| Agent stack | Hermes Agent inside an OpenShell sandbox (NemoClaw blueprint) |
| Cloud | Token Factory (Zero Data Retention on), Serverless Endpoint (hosted demo), Serverless Jobs (batch indexing + eval), Object Storage |

---

## 0.1 Build status (21 Oct 2026)

| Area | Status |
|---|---|
| Engine | **Built.** Python (Starlette + uvicorn) on `127.0.0.1`; SQLite with FTS5; vectors stored in SQLite and searched in memory; folder watcher; CLI (`serve`, `index`, `search`, `doctor`, `models`, `web`, `source`, `broll`, `set-key`); 65 tests |
| Indexing | **Built.** Videos (shots, keyframes, thumbnails, chroma and alpha), photos, templates, sounds and music. Nemotron Super VL describes shots in parallel (up to 8 at a time), two files at a time, Parakeet in parallel; keyframe-based shot detection (10 s 4K clip: 4.3 s → 0.4 s); a file is re-indexed only when its size or modified time changes |
| Nemotron on Token Factory | **Built** for Super VL (descriptions), Omni (sounds; falls back to Nano from audio analysis because the account has no Omni model) and Nano (optional search expansion). Roles mapped automatically from `GET /v1/models`. Zero Data Retention on |
| Recording metadata | **Built.** Recording time from file names, EXIF, container tags or file date; camera; GPS |
| Search | **Built, changed.** Local only, no API call per search: meaning (multilingual text embeddings of each shot's description, tags, speech and recording details) + keywords (BM25) + look (SigLIP 2), rank fusion, feedback memory, top 5/10/20/50. Date and time filter with either-way dates and fallbacks. Find similar = look + meaning |
| Desktop app | **Built, changed.** Electron (not pywebview), frameless with macOS-style buttons, splash screen, light grid design with orange accents and a custom headline font |
| Built-in timeline | **Dropped** at the creator's request. Results open at the exact second; "Show in folder" hands the file to the editor |
| Tavily: gap filler, licence check, Ultra b-roll planner | **Built** (21 Oct). Free on the web + Save to Inbox; licence check from stock file names with a Licences view and Copy credits; research → Nemotron 3 Ultra beats → shots from the library. Through Tavily only (no per-site APIs yet). See `docs/tavily.md` |
| Proactive suggestions, Hermes Agent + OpenShell | Next |
| Google Drive | Drive for desktop folder works (it is a normal folder). Drive API connector: next |
| Installer | **Build script ready** (`scripts\build.ps1`): embeddable Python + engine + FFmpeg inside the Electron app, NSIS installer, per user. Unsigned |
| Settings for keys | **Built.** Keys & connections panel: API keys in the system keychain, Token Factory URL, date order, FFmpeg folder, model per role |
| Landing page, hosted demo on Nebius | Next |

---

## 1. Hackathon facts and what they mean for us

**Requirements (Devpost)**
- Runs on Nebius Token Factory or Nebius AI Cloud and uses at least one NVIDIA open model.
- Working project + track + description (what, why, how).
- **Working demo URL** (only Physical AI is exempt), so a local-only app is not enough.
- Public YouTube video, 3 minutes or less.
- Public repo with an open-source licence (MIT / Apache 2.0 / MPL 2.0) visible at the top, and a README with setup steps that explains how NVIDIA models, Token Factory and other Nebius tools are used.
- Feedback on the Nebius and NVIDIA tools.

**Judging (equal weight)**

| Criterion | What judges look for | How we score |
|---|---|---|
| Technological implementation | Quality of build, effective use of Token Factory / AI Cloud and Nemotron | Every Nemotron model has a real job (section 4); the sandbox and Zero Data Retention are actually configured; measured search accuracy |
| Design | A complete, coherent product, not a proof of concept | Installable app, landing page, hosted demo, polished search UI |
| Potential impact | Credible case for a real problem and audience | Global creator numbers + time lost searching (section 2) |
| Quality of idea | Creative, non-obvious use of the platform | Proactive suggestions from the creator's *own* library, a self-written-skill memory, and Tavily-backed free-asset gap filling with license checks |

**Prizes:** Grand $20k, 2nd $10k, 3rd $6k, Best Use of Tavily $3k, track winners get a Jetson Orin Nano, Most Valuable Feedback 10 x $100 (+ NVIDIA swag), City Winner $500 (not available in India). The cash is in the overall ranking and the Tavily prize, so we build for the overall ranking. Writing honest, detailed tool feedback is close to free money.

---

## 2. Why this idea (findings)

### 2.1 Track fit
The Personal AI track asks for an always-on private assistant with persistent memory, reusable skills, user-chosen tools and tasks across daily workflows, using NVIDIA open models and tools such as NemoClaw, OpenShell, Hermes Agent and Nebius Serverless. Every one of these maps to a feature here (section 11).

### 2.2 The global test
A global panel will ask "how does this work in the USA or in Greenland?". This idea passes: it depends on no country's laws, insurers or payment systems. A creator in Ohio, Berlin or Nuuk has the same messy drive. Search works on what is in the picture and the sound; the local meaning-search model understands queries in 50+ languages; Creative Commons licences used by the free sources are international.

**Rule for any future change:** if a feature relies on a regulator, an insurer or a national payment system, it fails a global panel.

### 2.3 Evidence for the pitch
| Claim | Number | Source / caveat |
|---|---|---|
| Size of audience | ~50 million creators; ~$250B market heading to ~$480B by 2027 | Goldman Sachs Research, Apr 2023 (a projection) |
| Time lost searching | One-third of marketers spend ~3 weeks a year searching for files | Canto / Civey survey, cited by Moments Lab |
| Video retrieval pain | 72% of teams using cloud storage / PM tools struggle to organise and retrieve video files | MediaValet 2025 DAM Trends report |
| General | Knowledge workers spend ~1.8 h/day hunting for information | McKinsey; **not editor-specific, only use with that caveat** |

### 2.4 Alternatives considered and rejected
| Idea | Why rejected |
|---|---|
| Generic content generator (captions, scripts, posts) | Most common hackathon entry; Jasper, Copy.ai, Opus Clip, Buffer already do it; weak on "quality of idea" |
| Private health-insurance claim agent | Strong pain in India (IRDAI: ~₹26,000 crore disallowed in FY24) and the US (KFF: ~20% of in-network marketplace claims denied in 2023, <1% appealed), but rules differ per country, Greenland has public healthcare, and the US already has Claimable and Counterforce Health. Fails the global test |
| Scam guardian for parents | Real pain (FBI IC3: people 60+ lost $4.8B in 2024) but crowded, and Google ships on-device scam-call detection |
| Gig-worker pay auditor | Most original, but hard to demo without real workers and depends on local labour law |

---

## 3. Product

**One-liner:** Ask for an asset in plain language and get it instantly, with timecodes. While you edit, the assistant suggests the right asset from your own library. When your library has nothing, it finds a free, properly licensed one. Your files stay yours.

**Users:** solo YouTubers, short-form creators, freelance editors, small studios. Anyone with hundreds to tens of thousands of clips, sound effects, music tracks and templates spread across local drives and Google Drive.

### MVP (must ship)
1. Watch approved local folders; index every asset once, incrementally.
2. Natural-language search across video, photos, templates, music and SFX, with timecoded video results.
3. ~~Built-in timeline (inside the app) with drag-and-drop insert.~~ **Changed:** dropped at the creator's request. Results open at the exact second and "Show in folder" hands the file to the editor.
4. One proactive suggestion flow (cut point / silence gap / speech without b-roll).
5. Memory from accept / reject feedback; Hermes writes at least one skill from it.
6. Gap filler: free web assets with licence badges via Tavily + free-source APIs, downloaded into an Inbox folder that is indexed automatically.
7. Pre-publish licence check that generates the credits block for the video description.
8. Sandbox + permissions panel showing exactly what the agent can touch.
9. Google Drive via "Drive for desktop" folder (zero-setup path).
10. Windows installer, landing page and hosted demo.

### Stretch
- Built-in Drive API connector (Picker), Telegram channel, "Plan b-roll for this script" with Nemotron 3 Ultra (**built 21 Oct** as the B-roll plan view), Cosmos-Embed1 accelerated video search, duplicate / unused detection, organise-folder skill with undo, Premiere Pro UXP panel, offline mode with local Nemotron.

---

## 4. NVIDIA ecosystem map (every piece has a job)

| Component | Job in the product | Runs where | Priority |
|---|---|---|---|
| **Nemotron 3.5 Super VL** (image + video in) | Caption keyframe strips and short clips: subject, setting, motion, shot type, mood, on-screen text, green screen yes/no; describe template previews | Token Factory | Core |
| **Nemotron 3 Nano Omni** (text, image, video, audio in) | Describe sound: SFX type and length ("short punchy whoosh"), music mood / energy / instruments, ambience; quick clip summaries | Token Factory | Core |
| **Nemotron 3 Super** | Hermes Agent's main model: chat, tool calls, writing skills | Token Factory | Core |
| **Nemotron 3 Nano 30B-A3B** (or 3.5 Lightning if faster) | Decide when a proactive suggestion is worth showing; parse licence text into fields; describe sounds from local audio analysis when no Omni model is available. **Changed:** query rewrite is now optional (off by default) because searches run locally with meaning search | Token Factory | Core |
| **Nemotron 3 Ultra** | "Plan b-roll for this script": line-by-line edit plan from the creator's own library, gaps flagged for the gap filler; weekly library audit | Token Factory | Core (one feature) |
| **Parakeet-TDT 0.6B v3** | Speech transcripts with native word timestamps for clips and voiceovers (aligns b-roll to words). CPU-friendly, ~1 GB RAM at q8, 25 European languages, CC-BY-4.0 | Local CPU | Core |
| **NemoClaw + OpenShell** | Sandbox for the agent: filesystem limited to approved folders, network allowlist, unknown hosts need approval, credentials brokered (agent never sees keys), inference routed through the gateway | Local (WSL 2 + Docker on Windows) | Core |
| **Hermes Agent** | Agent harness: persistent memory, self-written SKILL.md files, scheduled jobs, MCP client to our engine | Inside the OpenShell sandbox | Core |
| **Nebius Serverless Endpoint** | Hosts the live web demo (UI + engine + sample index) | Nebius AI Cloud (CPU preset) | Core |
| **Nebius Serverless Jobs** | (a) Pre-index the demo library on a GPU; (b) nightly search-accuracy eval; (c) opt-in "Accelerated" indexing of large libraries | Nebius AI Cloud (GPU, billed only while running, min timeout 1 h) | Core (a), stretch (b, c) |
| **Nebius Object Storage** | Demo sample library + prebuilt index, mounted read-only into the endpoint | Nebius AI Cloud | Core |
| **Cosmos-Embed1** (video-text embedder, 8 frames) | Motion-aware video search ("guy running in the rain") | Local RTX GPU or Serverless Job | Stretch |
| **llama-nemotron-embed-vl-1b-v2** (image + text, built for text-heavy images) | Search title cards, lower thirds, thumbnails and template previews that contain text | GPU (Serverless Job) | Stretch |
| **Local Nemotron via Ollama** (Nano class, ~6–7 GB VRAM at Q4) | Offline mode: OpenShell routes the agent's inference to the local model instead of Token Factory, with no agent changes | User's RTX GPU | Stretch |

**Non-NVIDIA pieces, and why:** SigLIP 2 (image/frame embeddings) and an optional CLAP (audio similarity) run locally because no NVIDIA open embedder covers natural images and audio on a CPU laptop. Meaning search uses `paraphrase-multilingual-MiniLM-L12-v2` (Apache 2.0) on the CPU, because NVIDIA's NeMo Retriever text embedders (e.g. llama-3.2-nemoretriever-300m-embed-v2) run as NIM containers on NVIDIA GPUs. Said openly in the README. An NVIDIA embedder can become an optional backend for users with an RTX GPU.

**Before coding:** call `GET https://api.tokenfactory.nebius.com/v1/models` to confirm exact model IDs, and measure latency and cost of Super VL and Omni on 10 sample assets.

---

## 5. Architecture

```
┌──────────────────────────── User's computer (Windows) ─────────────────────────────┐
│                                                                                    │
│  Desktop app (Electron window, plain HTML/CSS/JS UI)                               │
│    Home · Library · Search · Detail panel · Settings · (next: Suggestions, Chat)   │
│                     │ HTTP (localhost)                                             │
│  Engine (Python, Starlette + uvicorn)                                              │
│    Watcher ─► Indexer ─► ffmpeg / shot detect / SigLIP 2 / Parakeet / audio stats  │
│    Search (meaning + keywords + look, local) · date filter · memory · licence store│
│    Connectors: local folders · Drive-for-desktop folder · Drive API (stretch)      │
│    Free sources: Pexels · Pixabay · Openverse · Freesound · Tavily                 │
│    MCP server (tools for the agent)                                                │
│    Storage: SQLite (FTS5, vectors, feedback) · thumbnails · cache                  │
│                     ▲ MCP over HTTP                                                │
│  ┌──────── WSL 2 + Docker: OpenShell sandbox (NemoClaw blueprint) ─────────┐       │
│  │ Hermes Agent: memory · self-written skills · cron jobs · Telegram (opt) │       │
│  │ Policy: read-only asset mounts, write Inbox only, network allowlist     │       │
│  └──────────────────────────────┬───────────────────────────────────────────┘       │
└─────────────────────────────────┼──────────────────────────────────────────────────┘
                                  │ small keyframes, short audio snippets, text only
                                  ▼
      Nebius Token Factory (Zero Data Retention): Super VL · Nano Omni · Super · Nano · Ultra
      Tavily API (text queries only) · Free-source APIs · Google Drive API

Hosted demo (judges):  Landing page ─► Nebius Serverless Endpoint (same UI + engine,
                       read-only CC0 sample library from Object Storage) ─► Token Factory
Batch:                 Nebius Serverless Job (GPU) ─► builds demo index ─► Object Storage
```

---

## 6. Privacy modes (what leaves the machine)

v1 said "nothing leaves your machine". That was inaccurate because keyframes go to Nemotron. The honest version:

| Mode | What leaves the computer | What you get |
|---|---|---|
| **Local only** | Nothing | Visual search (SigLIP), transcripts (Parakeet), filenames / folders / EXIF. No AI captions. Agent only if a local Nemotron runs via Ollama |
| **Standard (default)** | Per asset, once: a few downscaled keyframes (~384 px), a ≤10 s low-bitrate audio snippet, and text. Never full files. Sent to Token Factory with **Zero Data Retention** enabled. **Changed:** search text stays on the computer (meaning search is local); it is sent only if the user turns on Nemotron search expansion | Full captions, audio descriptions, agent |
| **Accelerated (opt-in, per folder)** | Full files are copied to a private bucket for a GPU Serverless Job, deleted when the job ends | Fast bulk indexing of huge libraries, Cosmos-Embed1 video search |

**Token Factory data facts:** by default Token Factory retains inputs and outputs (stored in Finland) to speed up inference through speculative decoding; content is never used for training. With Zero Data Retention enabled at organisation level, no copy is kept beyond in-flight processing. **We turn ZDR on and say so in the app and README.**

Pitch line: "Your files never leave your machine. In Standard mode only small keyframes and short snippets go to Nemotron, with zero data retention, and you can switch that off."

---

## 7. Where data is stored

| Data | Location | Format |
|---|---|---|
| Original assets | Where they already are. Never copied, moved or uploaded (except Accelerated mode, or the organise skill with confirmation + undo log) | — |
| Library database | `%LOCALAPPDATA%\CreatorAssetAssistant\library.db` | SQLite + FTS5: assets, timecoded segments, captions, tags, transcripts, source (path or Drive file ID), licence, feedback, usage |
| Vectors | `library.db` | **Changed:** stored in SQLite (`embeddings` for SigLIP, `text_vectors` for meaning search) and searched in memory with numpy; no LanceDB. Fast enough for tens of thousands of shots on a laptop |
| Thumbnails, keyframe strips | `...\thumbs\` | Small WebP/JPEG |
| Drive cache | `...\cache\drive\` | LRU, default cap 20 GB, user-adjustable; files deleted after indexing unless pinned |
| Downloads from free sources | User-chosen Inbox (default `Videos\CreatorAssets\Inbox\`), itself a watched folder | Original files + licence record in SQLite |
| Agent memory and skills | `HERMES_HOME` inside the sandbox volume (WSL 2) | Hermes memory + SKILL.md files; exportable from Settings |
| Secrets (Token Factory, Tavily, Google, Freesound) | Windows Credential Manager via `keyring`; OpenShell injects them into outbound requests | Never written to plain files, never visible to the agent |
| Hosted demo | Nebius Object Storage bucket (CC0 / free-licence sample library + prebuilt index), mounted read-only | Visitor actions kept in memory per session; nothing persisted |

---

## 8. Google Drive

### Path A: Drive for desktop (MVP, zero setup)
- The user installs Google Drive for desktop and adds e.g. `G:\My Drive\Assets` as a watched folder.
- In streaming mode, reading a file downloads it, so indexing runs in the background with a bandwidth cap; or the user marks the folder "Available offline".
- Works on day 1 with no OAuth work.

### Path B: Built-in Drive connector (stretch)
| Topic | Plan |
|---|---|
| Auth | OAuth desktop flow (loopback redirect) |
| Scope, option 1 (preferred) | `drive.file` + Google Picker for desktop apps: **non-sensitive** scope; the user picks folders/files (`allow_folder_selection=true`). Day-1 test: confirm whether picking a folder also grants its children; if not, the user multi-selects files |
| Scope, option 2 | `drive.readonly`: **restricted** scope. Public launch needs Google's restricted-scope verification. For the hackathon, run in Testing status: max 100 test users, and authorisations expire after 7 days |
| Server-side assessment | Not triggered: Drive data goes Google → user's computer only, never to our servers |
| Fast first pass | List files; store `id`, `md5Checksum`, `videoMediaMetadata` (duration, size); fetch `thumbnailLink` (short-lived, needs a credentialed request) for an instant visual entry |
| Full index | Download to the cache in the background, extract frames / audio, then delete unless pinned |
| Always-on sync | Changes API (`startPageToken` + `changes.list`) polled every 5–10 minutes by a scheduled job |
| Insert | Download on demand to cache, then hand it to the editor ("Show in folder") |

The same connector interface can later cover Dropbox, OneDrive and NAS shares.

---

## 9. Free asset sources (what we suggest and how)

| Source | Content | Access | Licence (summary) | How we use it |
|---|---|---|---|---|
| **Pexels** | Photos, videos | Free API key; 200 req/h, 20k/month | Free to use; API terms require a visible link to Pexels and crediting the creator where possible | API search + download to Inbox |
| **Pixabay** | Photos, videos (API); music + SFX (site only) | Free API key; 100 req/60 s; cache results 24 h; no permanent hotlinking; show the source | Pixabay Content License | API for images / video; Tavily discovers music / SFX pages, user downloads in browser |
| **Openverse** | Images + audio, 600M+ openly licensed works (Wikimedia, Flickr, Smithsonian…) | API, anonymous allowed; token for higher limits; `license_type=commercial` filter | Creative Commons per item; many need attribution | API search; store the attribution text it returns |
| **Freesound** | Sound effects | API token for search + previews; original-file download needs OAuth2; 60/min, 2,000/day | Per sound: CC0, CC-BY or CC-BY-NC | Search + preview in app; download via user's OAuth or link-out; flag NC sounds |
| **Mixkit** (Envato) | Video, music, SFX, templates for Premiere / After Effects / Resolve / Final Cut | No API | Free License: commercial OK, no attribution. Some items use a Restricted (non-commercial) License | Tavily search (`include_domains: mixkit.co`) + Extract to read the licence label; link-out |
| **Sonniss GDC bundles** | Large SFX packs (2026 bundle: 7.47 GB, 17 vendors) | Direct download | Royalty-free, no attribution | Suggested "starter pack" during onboarding; download once and index |
| **YouTube Audio Library** | Music + SFX inside YouTube Studio | No API | Licence varies per track; some need attribution; check before using outside YouTube | Suggestion + link-out only |
| **BBC Sound Effects** | 33,000+ SFX | Website | RemArc licence: personal, educational, research only, **no commercial use** | Show as a licence-risk example: the pre-publish check flags it for monetised videos |

**Onboarding "starter kit":** after the first index, the agent looks at what the library lacks (e.g. no transition SFX, no music under 30 s) and suggests specific free packs from this table.

---

## 10. Tavily features (Best Use of Tavily)

> **Built 21 Oct** (details in `docs/tavily.md`). Changed from the plan below: (1) the gap filler goes through Tavily only, with `include_domains` per type, not the Pexels / Pixabay / Openverse / Freesound APIs, so one key covers every site; it runs by itself only when the library has no match, otherwise on one click, to save credits. (2) Licence extraction also works on files already on disk: stock file names lead to their pages ("Where did this file come from?"), read in batches of 20 per Extract request. Rules read the licence first; Nemotron Nano writes the credit and fills gaps, never overriding a licence found on the page. (3) The Ultra job became the **b-roll planner** (research with `include_answer` → beats → shots from the library → gaps to the gap filler); the weekly audit is the Licences view's "Check N files". (4) The pre-publish check per video is still to do.

Only text queries leave the machine, so Tavily does not weaken the privacy story.

1. **Gap filler.** When the best local result scores below the threshold:
   - `POST /search` with `include_domains` = Mixkit, Pixabay, Pexels, Freesound, Openverse; `include_images: true` for previews; `search_depth: basic` (1 credit; `advanced` costs 2).
   - In parallel, call the Pexels / Pixabay / Openverse / Freesound APIs directly.
   - Merge into a "Free on the web" row with licence badges.
2. **Licence extraction.** `POST /extract` on the asset page → Nemotron 3 Nano turns the licence block into `{licence, commercial_ok, attribution_required, attribution_text, source_url}` → stored in SQLite with the downloaded file.
3. **Pre-publish licence check + credits.** Before export: list the assets used in the video (picked with "Show in folder" or marked as used); re-check licence pages older than 30 days; flag non-commercial or unknown licences; generate the credits block for the video description.
4. **Library audit (weekly, Ultra).** Uses stored licence records to list risky assets (e.g. BBC SFX in a monetised project).

Credits: Nebius Builder Program includes Tavily credits. Cache every search result for 24 h (also required by Pixabay).

---

## 11. Agent design (Hermes + OpenShell)

### 11.1 Tools (engine exposes them as an MCP server)
`search_assets`, `get_asset`, `suggest_for_context`, `plan_broll`, `reveal_in_folder`, `find_free_asset`, `download_to_inbox`, `check_licences`, `find_duplicates`, `organise_preview`, `organise_apply` (with undo), `record_feedback`.

Hermes config: provider = custom OpenAI-compatible endpoint `https://api.tokenfactory.nebius.com/v1` (Nemotron 3 Super); `mcp_servers` → our engine's MCP URL.

### 11.2 Memory and self-written skills
- Style profile: favourite transitions, music moods, typical clip lengths, colour looks.
- Feedback log: every suggestion with accepted / rejected / ignored.
- Hermes writes a SKILL.md when it spots a repeated pattern, e.g. `my-jump-cut-sfx` ("prefers whooshes under 0.6 s, never risers"). **Demo moment:** show the skill file appear, then show the next suggestion following it.

### 11.3 Always-on jobs (Hermes cron)
- Every 10 min: index new files, Drive changes.
- Nightly: retry failed indexes, refresh expiring licence checks.
- Weekly: library health report with Nemotron 3 Ultra (duplicates, unused assets, licence risks, gaps + starter-kit suggestions).

### 11.4 Channels
In-app chat panel (MVP). Telegram via NemoClaw's channel setup (stretch): "find me a rain shot" from a phone returns thumbnails and can queue a download into the Inbox.

### 11.5 Sandbox policy (sketch; confirm exact syntax in the OpenShell docs)
```yaml
filesystem:
  read_only: [<approved asset folders>]
  read_write: [<Inbox folder>, <HERMES_HOME>]
network:
  allow:
    - api.tokenfactory.nebius.com
    - api.tavily.com
    - api.pexels.com
    - pixabay.com
    - api.openverse.org
    - freesound.org
    - www.googleapis.com
    - <engine MCP host:port>
  default: deny        # unknown hosts are blocked and shown to the user for approval
credentials: brokered  # keys added on the way out; the agent never sees them
```
**Demo moment:** the agent tries an unlisted host, gets blocked, and the approval prompt appears.

### 11.6 Platform reality
- OpenShell on Windows: x86_64 via WSL 2 + Docker Desktop, marked **experimental**. macOS (Apple Silicon) and Linux are supported.
- Hermes Agent: Linux, macOS, Windows via WSL 2.
- So the desktop app (engine + UI + search + suggestions) runs natively on Windows; the agent runs in WSL 2. The installer checks for WSL 2 / Docker and runs a setup script if the user enables "Agent mode". Set this up on day 1.

---

## 12. Indexing pipeline

| Asset | Local steps | Nemotron step (Standard mode) |
|---|---|---|
| Video | ffmpeg shot detection (HSV histograms; keyframes only when the video has one every second, otherwise 2 fps with GPU decode and non-reference frames skipped) → 3 keyframes per shot (parallel ffmpeg for 1440p and up) → SigLIP 2 embeddings; Parakeet transcript with word timestamps (in parallel); green-screen pre-check (HSV chroma ratio) | Super VL on the keyframe strip, all shots in parallel (up to 8 at a time) → JSON (description, subjects, setting, action, shot type, camera, mood, colours, on-screen text, background, tags) |
| Photo | SigLIP 2; EXIF (time, camera, GPS) | Super VL caption + tags, started before the local work |
| Template (.mogrt, .aep, Resolve, FCP) | Use the preview file inside the package if present; filename + folder tokens | Super VL on the preview |
| Music / SFX | Loudness, length, tempo and transient estimates (numpy); optional CLAP; Parakeet if speech | Omni → JSON (type, description, mood, energy, instruments, good_for); Nano from the audio analysis when the account has no Omni |
| All | Filename, folder path, recording time / camera / GPS, licence record; then one meaning-search vector per shot | — |

Each asset is processed once; Nemotron answers are cached; a file is re-indexed only when its size or modified time changes (opening or playing a file does not count). Two files are indexed at a time. The engine log records the time of each step per video.

---

## 13. Search and proactive suggestions

**Search (as built):** everything runs on the computer, with no API call per search.
1. Date and time words ("11:54am on 6/9/26", "yesterday morning", "September 2026") become an exact filter on recording time, using the Windows date order. Dates that could be read either way are checked both ways and the reading with footage wins (with a note and a "Did you mean" link). If nothing matches, the closest recordings in time or the other words from any date are shown, with the reason.
2. Filter words from the query (type, duration, orientation, green screen) become hard filters; everything else is ranked.
3. Three local channels: meaning (multilingual text embeddings of each shot's description, tags, speech, file name, folder and recording details), keywords (FTS5 BM25) and look (SigLIP 2 text-to-frame).
4. Reciprocal-rank fusion → memory (good picks and use up, "not this" down, recent repeats slightly down) → one ranked list, top 5/10/20/50 → results with timecodes; a time inside a clip opens it at that second.
5. Optional: Nemotron 3 Nano expands the query (off by default; automatic only when the meaning model is missing).

Measured: a search takes milliseconds locally; the earlier Nano rewrite took about a second (6 s budget) and about $0.00006 per search. **Find similar** fuses look and meaning. Possible later: Super VL rerank of the top 8 thumbnails.

**Proactive suggestions:** triggers = new clip placed, playhead pause, cut with no audio transition, silence gap, speech segment with no b-roll. Context = transcript window (Parakeet) + current frame (SigLIP) + clip caption + memory. Nemotron 3 Nano decides whether to suggest and what type. Rules: at most one per N seconds, confidence threshold, always dismissible, dismissals reduce similar suggestions.

**Plan b-roll (Ultra):** paste a script or use the voiceover transcript → per line: suggested assets from the library with timecodes, or "gap" → gap filler.

**Editor integration:** **Changed:** no built-in timeline. Results open at the exact second and "Show in folder" hands the file to the editor. Premiere Pro UXP panel is a half-day spike on day 8; keep only if insert works. DaVinci Resolve later.

---

## 14. Distribution and deployment

### 14.1 Desktop app or website? Both, with different jobs
| Piece | Why | Where |
|---|---|---|
| **Desktop app (the product)** | Must watch folders and read whole drives (browsers cannot, beyond per-folder permission prompts), run ffmpeg / Parakeet locally, keep files on the device, and later talk to Premiere | `.exe` installer on GitHub Releases |
| **Landing page (the live link)** | One link for judges and users: video, "Try the live demo", "Download for Windows", GitHub, privacy explainer | GitHub Pages or Vercel (free, static) |
| **Hosted demo (the Devpost demo URL)** | Judges will not install an exe; they need something to click | Nebius Serverless Endpoint |

### 14.2 Packaging (Windows)
- **Changed:** the desktop shell is Electron (frameless window, macOS-style buttons, splash screen, starts and stops the engine). The installer (`scripts\build.ps1`) ships the official embeddable Python from python.org with the engine's packages pinned to the developer `.venv`, plus the engine, UI and FFmpeg, inside the Electron app, built with electron-builder (NSIS) → `CreatorAssetAssistant-Setup-0.1.0.exe`. Embeddable Python instead of PyInstaller, because Transformers, keyring and uvicorn import modules dynamically. The UI is plain HTML/CSS/JS, so there is no React build step.
- Original recommendation (not used): pywebview (Edge WebView2) + React build + FastAPI engine + Inno Setup.
- Bundle `ffmpeg.exe`; download SigLIP 2 and Parakeet weights on first run to keep the installer small.
- **Alternative:** Tauri v2 with the PyInstaller-built engine as a sidecar (`externalBin`). Smaller and more polished, but needs the Rust toolchain. Only if a teammate already knows Tauri.
- **Signing:** an unsigned exe shows SmartScreen's "Unknown publisher" screen. Azure Artifact Signing ($9.99/month) is available to individual developers only in the USA and Canada, and even signed apps need time to build reputation. For the hackathon: ship unsigned, put "More info → Run anyway" instructions and the SHA-256 checksum on the landing page.

### 14.3 Hosted demo on Nebius
- Container: same UI + engine, `DEMO_MODE=1` (no local-folder access, no uploads).
- Sample library: ~150 CC0 / free-licence assets (Pexels, Pixabay, Mixkit, Sonniss) in Object Storage, mounted read-only.
- Index pre-built by a GPU Serverless Job, so visitors mostly hit the local index; only query rewrite, suggestions and agent chat call Token Factory.
- Per-IP rate limit on Nemotron calls; endpoint auth off (judges need open access).
- **Cost:** Serverless Endpoints bill wall-clock from create to delete, including idle time, and the URL must stay live until 15 Dec. Check the CPU preset price against our credits on day 1. Fallback: the same container on a free Hugging Face Space, keeping Token Factory for inference.

### 14.4 Repo
- Licence: MIT or Apache 2.0 at the top of the README. Model weights are not committed. Credit Parakeet (CC-BY-4.0) and note the NVIDIA Open Model License for Cosmos / Nemotron embedders.
- README section "How we use NVIDIA and Nebius": copy the table from section 4.

---

## 15. Schedule (Tue 20 Oct → Fri 30 Oct)

Roles (adjust to team size): **A** engine + models, **B** UI + desktop + landing, **C** agent + sandbox + Tavily + Drive, **D** eval + README + video (merge into others if 3 people).

| Day | Date | Goal | Owner |
|---|---|---|---|
| 1 | Tue 20 | Repo + licence; Token Factory key, **ZDR on**, list model IDs; Tavily + Nebius credits; WSL 2 + Docker + OpenShell + Hermes smoke test; sample library (~150 assets); engine + UI skeleton; Drive Picker folder test | All |
| 2 | Wed 21 | Watcher, ffmpeg, scene detect, SigLIP 2, LanceDB; first visual search | A |
| 3 | Thu 22 | Super VL captions, Omni audio captions, Parakeet transcripts; FTS5; hybrid search + timecodes; query rewrite | A |
| 4 | Fri 23 | UI: grid, search, preview, ~~built-in timeline with drag-insert~~ (dropped); 50-query eval set + script | B, D |
| 5 | Sat 24 | Proactive suggestions + feedback memory; MCP server; Hermes connected; first self-written skill | A, C |
| 6 | Sun 25 | OpenShell policy, permissions panel, blocked-host demo; Telegram (stretch) | C, B |
| 7 | Mon 26 | Gap filler (Tavily + Pexels / Pixabay / Openverse / Freesound), Inbox download, licence extract, pre-publish check + credits | C |
| 8 | Tue 27 | Packaging (PyInstaller + pywebview + Inno Setup); hosted demo on Serverless Endpoint + Object Storage; Serverless Job for demo index; landing page. Optional Premiere UXP spike | B, A |
| 9 | Wed 28 | Drive-for-desktop path polished; Drive API connector (stretch); Ultra b-roll planner; run eval, fix search | A, C |
| 10 | Thu 29 | Polish, README, record video, test exe on a clean Windows machine | All |
| 11 | Fri 30 | Buffer; submit on Devpost by 6:00 PM IST; send tool feedback | All |

**Progress, 21 Oct:** the Tavily work planned for day 7 is done early: gap filler with Save to Inbox, licence check with a Licences view and credits, and the Nemotron 3 Ultra b-roll planner (section 10).

**Progress, 20 Oct:** the work planned for days 1–4 on the engine, models, search and UI is done (see section 0.1), plus recording-time search and local meaning search. The timeline was dropped. Next: Hermes Agent + OpenShell and proactive suggestions, the Tavily gap filler and licence check, the Ultra b-roll planner, then packaging, the hosted demo and the landing page.

---

## 16. Demo video (≤ 3:00)

| Time | Scene |
|---|---|
| 0:00–0:15 | Problem: ~50M creators, weeks a year lost searching for files |
| 0:15–0:35 | Point at a local folder and a Drive folder; captions appear live (Super VL / Omni badges) |
| 0:35–1:00 | Search: "punchy whoosh", "guy running in the rain", "green screen fire", a Hindi query, and "11:54am on 6/9/26" jumping to the exact second → instant local results |
| 1:00–1:25 | Show in folder into the editor; suggestion at a cut; accept one, dismiss one; show the SKILL.md Hermes wrote |
| 1:25–1:50 | "Drone shot of snowy mountains" → nothing local → free web results with licence badges → download to Inbox → indexed |
| 1:50–2:10 | Plan b-roll for a script (Ultra) |
| 2:10–2:35 | Privacy: permissions panel, sandbox blocks an unknown host, ZDR on |
| 2:35–2:52 | Pre-publish check: BBC SFX flagged non-commercial; credits block generated |
| 2:52–3:00 | Landing page: live demo + download |

---

## 17. Submission checklist
- [ ] Track: Personal AI
- [ ] Description (what / why / how) with the evidence table
- [ ] Demo URL (hosted demo) live, and kept live until 15 Dec
- [ ] YouTube video ≤ 3:00, public
- [ ] Public repo, licence visible, README with setup + "How we use NVIDIA and Nebius"
- [ ] Feedback on Nebius and NVIDIA tools (also enters Most Valuable Feedback)
- [ ] Landing page with exe download + SmartScreen note + checksum

---

## 18. Competitors and positioning

| Product | What it does | Gap for our user |
|---|---|---|
| Premiere Pro Media Intelligence (Adobe) | On-device visual search of footage in a project | Project clips only, video only, no SFX / music / templates, no proactive suggestions |
| ShotAI | Local-first natural-language shot search | Video only; no audio library, templates, suggestions |
| Envato Elements extension | Recommends Envato stock from a project frame | Envato's cloud library, not your own assets; no memory |
| AutoCut AutoB-Rolls | Auto-inserts stock / AI b-roll from audio | Stock only, cloud-based |
| Moments Lab | AI media hub with a Premiere plugin | Cloud, enterprise, teams and broadcasters |

**Our gap:** private by design, every asset type in one index, local + Drive, proactive suggestions from the creator's own library that improve through memory, and licence-safe free assets when the library has nothing.

**Pitch line:** "Envato-style suggestions, from your own private library, with memory, and licence-safe free assets when you run out."

**Likely judge questions**
- *Isn't this Premiere's search?* Premiere searches clips in one project. We search the whole library including audio and templates, suggest proactively, and learn your taste.
- *How does it work in another country?* Nothing about the problem or product changes by country (section 2.2).
- *What leaves my machine?* Section 6, word for word.

---

## 19. Risks and mitigations

| Risk | Mitigation |
|---|---|
| OpenShell on Windows is experimental | Set up WSL 2 + Docker on day 1; if it fails, run the agent on a Linux / Mac teammate machine or a Nebius VM for the video, and keep the app usable without the agent |
| Super VL / Omni latency or cost | Measure on day 1; caption 3 keyframes per shot, not every frame; cache; fall back to Nemotron 3 Super on text-only metadata |
| Indexing slow on CPU laptops | Background indexing, sparse frames, pre-indexed demo library, Serverless Job for bulk |
| Drive restricted scope | Drive-for-desktop path first; `drive.file` + Picker for the connector |
| SmartScreen / antivirus flags the exe | PyInstaller onedir + Inno Setup; landing-page instructions + checksum; hosted demo as the main judge path |
| Hosted demo cost until 15 Dec | Check pricing against credits; free Hugging Face Space as fallback |
| Licence parsing errors | Always show the source link and "verify before publishing"; never claim legal certainty |
| Suggestions annoy users | Rate limit, threshold, dismissals train memory |
| Demo fails live | Pre-indexed library, recorded backup video |

---

## 20. Success criteria
- Top-3 hit rate ≥ 80% on a 50-query eval set (report the number in the README).
- Indexing ~150 assets in Standard mode finishes in under 10 minutes on a team laptop.
- Proactive suggestion appears in the demo and is accepted; a Hermes skill is created and visibly used.
- In Standard mode, the sandbox egress log shows no full asset file leaving the machine.
- The exe installs and runs on a clean Windows 11 machine.
- Demo URL live through 15 Dec.

---

## 21. Open questions
- Team size and owner for each role (section 15)?
- Does anyone have an NVIDIA RTX GPU? (Decides local Cosmos-Embed1 / offline mode vs Serverless Jobs only.)
- How many Nebius / Tavily credits do we have? (Decides hosted demo on Nebius vs Hugging Face fallback.)
- Product name and domain for the landing page?
- Telegram channel: in or out?
- Premiere version available for a UXP spike?

Resolved from v1: deadline (30 Oct, 10:30 PM IST); local vs Nebius model (Standard mode with ZDR by default, local-only and offline modes available).

Resolved while building (20 Oct): editor (no built-in timeline; open at the exact second + Show in folder); desktop shell (Electron); Omni (not on our Token Factory account, so sounds fall back to Nano from audio analysis); search (local meaning search instead of a Nemotron call per search); Zero Data Retention (on).

---

## 22. Sources
- Devpost rules, tracks, judging, prizes: https://nebiusglobalaihackathon.devpost.com/
- Token Factory Nemotron models: https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/README.md and https://mastra.ai/models/providers/nebius
- Nemotron 3.5 Super VL inputs: https://blog.kilo.ai/p/nvidia-nemotron-35-super-vl
- Nemotron 3 Nano Omni inputs: https://docs.nvidia.com/nemo/megatron-bridge/latest/models/nemotron/nemotron-3-omni.html
- Token Factory data retention / ZDR: https://docs.tokenfactory.nebius.com/legal/legal-quick-guide
- Token Factory API base URL: https://fuma-docs.api7.ai/ai-gateway/providers/nebius-token-factory
- NemoClaw overview: https://docs.nvidia.com/nemoclaw/0.0.43/about/overview.html
- OpenShell support matrix: https://docs.nvidia.com/openshell/latest/reference/support-matrix
- Hermes Agent + NemoClaw: https://developer.nvidia.com/blog/deploy-self-evolving-agents-for-faster-more-secure-research-with-a-hermes-agent-and-nvidia-nemoclaw/
- Hermes Agent setup (custom endpoint, MCP, WSL 2): https://docs.salad.com/container-engine/tutorials/agentic-tools/use-hermes-agent-with-saladcloud
- Serverless Endpoints: https://github.com/nebius/skills/blob/main/skills/nebius-serverless-endpoints/SKILL.md and https://docs.nebius.com/serverless/endpoints/manage
- Serverless Jobs: https://docs.nebius.com/serverless/jobs/manage
- Parakeet-TDT 0.6B v3: https://huggingface.co/OpenASR/parakeet-tdt-0.6b-v3
- Cosmos-Embed1: https://huggingface.co/nvidia/Cosmos-Embed1-224p
- NeMo Retriever 300M embedder (runs as a NIM on NVIDIA GPUs): https://docs.api.nvidia.com/nim/reference/nvidia-llama-3_2-nemoretriever-300m-embed-v2
- Meaning-search model, paraphrase-multilingual-MiniLM-L12-v2: https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- llama-nemotron-embed-vl-1b-v2: https://huggingface.co/nvidia/llama-nemotron-embed-vl-1b-v2
- Nemotron on Ollama (VRAM): https://bestllmfor.com/guide/nemotron-nvidia-local-ollama/
- Drive API scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- Drive File resource: https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- Google Picker for desktop: https://developers.google.com/drive/picker/guides/desktop-mobile-picker
- OAuth Testing status limits: https://support.google.com/cloud/answer/15549945
- Pexels API: https://www.pexels.com/api/documentation/
- Pixabay API: https://pixabay.com/api/docs/
- Freesound API: https://freesound.org/docs/api/overview.html
- Openverse API: https://jentic.com/apis/openverse.org/openverse
- Mixkit licences: https://mixkit.co/license/ and https://mixkit.co/llm-info/
- Sonniss GDC 2026 bundle: https://rekkerd.org/sonniss-releases-gdc-2026-game-audio-bundle/
- BBC Sound Effects licence: https://musictech.com/news/music/the-bbc-sound-effects-archive-over-33000-free-samples
- YouTube Audio Library licences: https://usethirdchair.com/blog/can-you-use-youtube-audio-library-music-on-instagram
- Tavily Search API: https://docs.tavily.com/documentation/api-reference/endpoint/search
- Tauri v2 sidecar: https://v2.tauri.app/develop/sidecar/
- pywebview freezing: https://pywebview.flowrl.com/guide/freezing.html
- Windows code signing / SmartScreen 2026: https://codenote.net/en/posts/windows-desktop-app-code-signing-distribution-japan-2026/
- Goldman Sachs creator economy: https://www.goldmansachs.com/insights/articles/the-creator-economy-could-approach-half-a-trillion-dollars-by-2027
- MediaValet video asset report: https://www.mediavalet.com/resources/video-asset-management-report
- Moments Lab (Canto / Civey, McKinsey): https://www.momentslab.com/blog/how-to-optimize-content-sourcing-in-production
- KFF claim denials 2023: https://www.kff.org/private-insurance/claims-denials-and-appeals-in-aca-marketplace-plans-in-2023/
- IRDAI FY24 claims: https://www.business-standard.com/finance/personal-finance/health-insurance-claims-rejection-up-19-10-in-fy24-irdai-report-124122700754_1.html
- PYMNTS AI appeal tools: https://www.pymnts.com/artificial-intelligence-2/2026/insurance-denials-meet-their-match-in-ai-powered-appeals/
- FBI IC3 2024 elder losses: https://www.yahoo.com/news/cybercrime-topped-16b-2024-seniors-231500370.html
- Google scam protection in India: https://techcrunch.com/2025/11/20/google-steps-up-ai-scam-protection-in-india-but-gaps-remain
