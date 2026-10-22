# Creator Asset Assistant: Personal AI Track Plan

An always-on, private assistant that runs locally, indexes a creator's entire asset library (video, photos, templates, audio, SFX, green screen clips), lets them find anything by describing it, and proactively suggests assets while they edit.

---

## 1. Goal

**One-liner:** Ask for an asset in plain language, get it instantly. While you edit, the assistant suggests the right asset at the right moment. All data stays on your machine.

**Track requirements covered**
| Requirement | How we meet it |
|---|---|
| Always-on, private | Local background service, local index, no asset uploads |
| Persistent memory | Creator style profile + accept/reject history |
| Reusable skills | Find b-roll, match music to mood, clean up folder, etc. |
| Access to chosen tools/info | Only user-approved asset folders and editor plugin |
| Carry out tasks in daily workflow | Search, insert into timeline, suggest, organize |
| NVIDIA open source model | NVIDIA Nemotron model for reasoning, captioning, request understanding |
| Tools | NemoClaw, OpenShell (sandbox), Hermes Agent (tool-calling/skills), Nebius Serverless (model hosting) |

---

## 2. Core Features

### MVP (must ship)
1. **Folder indexing:** scan approved folders, process every asset once, cache results.
2. **Natural-language search:** "punchy whoosh for a transition", "guy running in the rain", "green screen of fire".
3. **Timecoded results:** video search returns clip + timestamp, not just filename.
4. **Editor integration (or stand-in):** search panel where results can be dragged or inserted into the timeline.
5. **One proactive suggestion flow:** assistant looks at the current timeline moment and suggests an asset.

### Stretch
- Learning from accepted/rejected suggestions
- Duplicate and unused asset detection
- Auto-organize / rename folder skill
- Voice search
- Hindi / multilingual queries

---

## 3. Architecture

```
┌─────────────────────────── Local machine ───────────────────────────┐
│                                                                     │
│  Asset folders ──► Watcher/Scanner ──► Processing pipeline          │
│                                         ├─ Frame extraction (ffmpeg)│
│                                         ├─ Image embeddings (CLIP/SigLIP)
│                                         ├─ Audio embeddings (CLAP) / Whisper
│                                         ├─ Captions + tags          │
│                                         └─ Green screen detection   │
│                                              │                      │
│                                              ▼                      │
│                              Local store: vector DB + SQLite        │
│                              (embeddings, tags, metadata, memory)   │
│                                              ▲                      │
│  Editor plugin / web timeline ◄──► Local API ┘                      │
│                                      │                              │
│                          Hermes Agent (skills, tool-calling)        │
│                                      │                              │
│                          OpenShell / NemoClaw sandbox               │
│                          (file access limited to approved folders)  │
└──────────────────────────────────────┬──────────────────────────────┘
                                       │ text + small frames only
                                       ▼
                        Nebius Serverless: NVIDIA Nemotron model
                        (captioning, query understanding, suggestions)
```

**Privacy rule:** raw assets never leave the machine. Only small frames or text prompts go to the model, and this is configurable (can run fully local with a smaller model).

---

## 4. Tech Stack

| Layer | Choice |
|---|---|
| Language | Python (backend), TypeScript (plugin/UI) |
| Frame extraction | ffmpeg (every 1-2s or on scene change) |
| Image/text embeddings | CLIP or SigLIP (open source, runs locally) |
| Audio | CLAP for sound-text search, Whisper for speech transcripts |
| Vector DB | LanceDB or Chroma |
| Metadata + memory | SQLite |
| Agent framework | Hermes Agent |
| Security/sandbox | NemoClaw + OpenShell |
| LLM | NVIDIA Nemotron on Nebius Serverless |
| API | FastAPI |
| Editor integration | Pick ONE: Premiere (UXP) or DaVinci Resolve (scripting API). Fallback: web timeline stand-in |

---

## 5. Indexing Pipeline Details

| Asset type | Processing |
|---|---|
| **Video** | Extract frames at interval/scene change → embed each → store with timestamp. Caption a few key frames. Detect green screen. |
| **Photo / template** | Embed image, generate caption, auto-tag |
| **Audio / SFX / music** | CLAP embedding, Whisper transcript if speech, BPM/mood tags |
| **All** | Filename + user description added as searchable text. Hybrid search: vector similarity + tag filters + keyword match |

**Search flow:** query → LLM rewrites into search text and filters → embed → nearest neighbours + filters → rerank with memory (favorites, past picks) → return results with timestamps.

---

## 6. Agent Skills (Hermes)

- `find_asset`: search by description
- `find_broll`: suggest b-roll for a given script line or transcript segment
- `match_music`: pick music for mood/pace of a section
- `suggest_at_playhead`: analyze current timeline context and propose an asset
- `organize_library`: dedupe, tag gaps, rename suggestions
- `remember_preference`: update style profile from user feedback

## 7. Memory Design

- **Style profile:** favorite genres, transition styles, color looks, typical clip lengths
- **Feedback log:** each suggestion with accepted / rejected / ignored
- **Usage stats:** most-used assets, recently used (avoid repeating)
- Use feedback to rerank results and throttle suggestions

## 8. Proactive Suggestions (the differentiator)

- Trigger on: new clip placed, playhead pause, cut point with no audio transition, silence gap, speech segment with no b-roll
- Inputs: nearby transcript, current frame embedding, clip mood, memory
- Rules to avoid annoyance:
  - Max one suggestion per N seconds
  - Only show above a confidence threshold
  - Always dismissible, and dismissals reduce future similar suggestions

---

## 9. Security Plan

- OpenShell sandbox: agent can only read/write the folders the user approves
- NemoClaw policy: explicit allowlist of tools (search, insert, tag), no arbitrary shell or network
- Network: only the model endpoint on Nebius is allowed
- Show the user a "what the agent can touch" panel in the demo

---

## 10. Build Plan (2-day sprint)

### Day 1: Core engine
| Time | Task |
|---|---|
| 0-1 h | Repo setup, sample asset library (video, photos, SFX, green screen) |
| 1-3 h | Scanner + ffmpeg frame extraction |
| 3-5 h | Embeddings (CLIP) + vector DB, basic text search working |
| 5-7 h | Audio indexing (CLAP/Whisper), tags + metadata in SQLite |
| 7-9 h | FastAPI endpoints, Nemotron on Nebius for captions + query rewrite |
| 9-10 h | Hybrid search + timestamps |

### Day 2: Agent, editor, polish
| Time | Task |
|---|---|
| 0-2 h | Hermes Agent skills wired to API |
| 2-4 h | Editor plugin or web timeline with search panel + insert |
| 4-6 h | Proactive suggestion flow + memory (accept/reject) |
| 6-7 h | NemoClaw/OpenShell sandbox + permissions panel |
| 7-9 h | Demo script, polish UI, record backup video |
| 9-10 h | Buffer, bug fixes, README, submission |

---

## 11. Demo Script (3 minutes)

1. **Problem (20s):** "Creators have thousands of assets and can't find anything."
2. **Index (30s):** point to a folder, watch assets get tagged locally.
3. **Search (40s):** type "punchy whoosh", "guy running in rain", "green screen fire". Instant results with timestamps.
4. **Editor (40s):** insert an asset into the timeline.
5. **Proactive suggestion (40s):** playhead pauses on a cut, assistant suggests a transition SFX. Accept it. Show it learned.
6. **Privacy (10s):** permissions panel, "nothing leaves your machine."

---

## 12. Competitors and Positioning

| Product | What it does | Where it falls short for our use case |
|---|---|---|
| **Premiere Pro Media Intelligence** (Adobe) | On-device visual search of footage by typing what you want | Works on imported project clips; editors are asking for whole-library (local drive/NAS) search. Video only, no SFX/template/audio library, no proactive suggestions |
| **ShotAI** | Local-first natural-language search that splits footage into shots | Video only. No SFX, music, templates or green screens, and no live editor suggestions |
| **Envato Elements extension for Premiere** | Analyzes a frame from your project and recommends music, SFX and clips | Pulls from Envato's cloud stock library, not the creator's own private assets. No personal memory |
| **AutoCut AutoB-Rolls** (Premiere, DaVinci) | Auto-inserts stock footage (Pexels, Storyblocks) or AI visuals based on audio | Stock/AI footage only, not your own library. Cloud-based |
| **Moments Lab** | AI-indexed media hub with a Premiere plugin | Cloud-based, enterprise-oriented, built for teams and broadcasters, not individual creators |

**Our gap:** nobody combines (1) fully local and private, (2) every asset type in one index (footage, photos, SFX, music, templates, green screens), (3) search across the whole library, and (4) proactive suggestions from the creator's *own* assets that improve through a memory of their taste.

**Pitch line:** "Envato-style suggestions, but from your own private library, with memory."

**How to answer "isn't this just Premiere's search?"**
- Premiere searches clips in a project. We search the entire library, including audio and templates.
- Premiere waits for a query. We suggest at the right moment.
- Ours learns each creator's preferences and stays on their machine.

*Sources: Adobe Premiere Pro community announcement, GetApp (ShotAI), freevisuals.net (Envato extension), autocut.com, momentslab.com. Checked October 2026; verify before the final submission.*

---

## 13. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Editor plugin takes too long | Build web timeline stand-in first, plugin only if time remains |
| Indexing is slow on big libraries | Index in background, cache, sample frames sparsely |
| Poor search quality | Hybrid search, query rewriting, tune frame interval |
| Suggestions annoy users | Thresholds, rate limits, feedback learning |
| Model latency on Nebius | Cache results, use smaller model for simple queries |
| Demo fails live | Pre-indexed library, recorded backup video |

---

## 14. Success Criteria

- Search returns the right asset in the top 3 for at least 80% of test queries
- Indexing a 100-asset library completes in a few minutes
- Proactive suggestion appears in the demo and feels relevant
- Clear proof that data stays local and the agent is sandboxed
- Uses an NVIDIA open model plus NemoClaw/OpenShell, Hermes Agent, and Nebius Serverless

---

## 15. Open Questions

- Which editor to target first (Premiere vs DaVinci Resolve)?
- Team size and who owns which part (indexing, agent, plugin, demo)?
- Fully local model option, or Nebius-hosted only for the hackathon?
- Final deadline for the submission?
