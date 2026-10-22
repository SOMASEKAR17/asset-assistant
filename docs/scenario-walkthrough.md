# Scenario walkthrough: one clip, from folder to search result

This follows one real clip through Creator Asset Assistant: how it is indexed when it lands in a watched folder, and what happens when you search for it. Scores marked *illustrative* are examples to show the mechanics; everything else (models, sizes, limits, weights) is what the code does.

The clip: `DJI_20260911131448_0049_D.MP4`, about 55 seconds, 3840×2160 at 59.94 fps, filmed from an airplane window.

## The models involved

| Job | Model | Where it runs | Output |
|---|---|---|---|
| Describe each shot (text) | **NVIDIA Nemotron 3.5 Super VL** (`nvidia/Nemotron-3.5-Super-VL`) | Nebius Token Factory | JSON: description, subjects, setting, action, shot type, camera, mood, colours, on-screen text, background, tags |
| Picture embedding ("look") | **Google SigLIP 2 Base** (`google/siglip2-base-patch16-224`, Apache 2.0) | Your computer (PyTorch, CPU) | 768 numbers per image or per sentence, in one shared space |
| Text embedding ("meaning") | **paraphrase-multilingual-MiniLM-L12-v2** (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, Apache 2.0) | Your computer (PyTorch, CPU) | 384 numbers per piece of text, 50+ languages |
| Speech to text | **NVIDIA Parakeet-TDT 0.6B v3** (`nemo-parakeet-tdt-0.6b-v3`, ONNX, CC-BY-4.0) | Your computer (CPU) | Transcript with word times |
| Describe sounds | **NVIDIA Nemotron 3 Nano Omni** if the account has it, otherwise **NVIDIA Nemotron 3 Nano 30B-A3B** (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`) from local audio analysis | Nebius Token Factory | JSON: type, description, mood, energy, instruments, tags |
| Optional search expansion (off by default) | **NVIDIA Nemotron 3 Nano 30B-A3B** | Nebius Token Factory | Extra keywords and soft hints |
| Plan b-roll (Part 4) | **NVIDIA Nemotron 3 Ultra** (`nvidia/Nemotron-3-Ultra-550b-a55b`; falls back to Nemotron 3 Super, then Nano) | Nebius Token Factory | JSON: title, hook, beats with a shot and search words each, sourced facts |
| Read a licence (Part 4) | **NVIDIA Nemotron 3 Nano 30B-A3B** | Nebius Token Factory | JSON: licence, commercial use, credit needed, credit line, notes |
| Web search and page reading (Part 4) | **Tavily** `/search` and `/extract` (not a model) | Tavily's servers | Web results with images, a short answer, page text as Markdown |

No model is involved in these steps: shot detection (colour histograms), the green-screen check (colour ratios), keyword search (SQLite FTS5 with BM25 scoring), date and time parsing, and combining the results (reciprocal-rank fusion).

Why two embedding models:
- **SigLIP 2** was trained on image–caption pairs, so a frame and a sentence describing it land close together. It compares your words with the **pictures**, even when a clip has no description (Local only mode) or the description missed something. It is strongest in English and works on short phrases (64 tokens).
- **paraphrase-multilingual-MiniLM-L12-v2** only reads text. It compares your words with each shot's **description text**, understands synonyms ("jogger" ≈ "runner") and other languages, but only knows what the text says (128 tokens).

---

## Part 1: Indexing (once, when the file appears)

### Step 1. The watcher notices the file
The folder watcher sees a new file in `C:\soma\…\mobile`. The indexer looks it up in `library.db` by path: no record, so it is queued. (If the record existed with the same size and modified time, nothing would happen. Opening or playing a file never re-indexes it.) Two files are indexed at a time.

### Step 2. Probe and recording metadata
FFprobe reads: duration about 55 s, 3840×2160, 59.94 fps, has audio.
`metadata.py` reads the recording time from the file name `DJI_20260911131448…` → **Friday 11 Sep 2026, 1:14:48 PM**, source "file name". Camera model and GPS are taken from the file's tags when present.

### Step 3. Shot detection (no model)
The video has a keyframe about every second, so only keyframes are decoded (about 55 tiny 64×36 frames instead of 3,300 full 4K frames). Each frame becomes a colour histogram; when neighbouring histograms differ by more than a threshold, that is a cut. Shots shorter than 1 s are merged and shots longer than 12 s are split.

Result: **8 shots** starting at 00:00, 00:08, 00:16, 00:25, 00:27, 00:29, 00:37 and 00:46.

### Step 4. Keyframes
For each shot, 3 frames at ¼, ½ and ¾ of its length, scaled to 768 px wide. 24 frames in total, grabbed by parallel FFmpeg processes because the clip is 4K.

### Step 5. Three jobs at the same time

**5a. Nemotron 3.5 Super VL describes each shot (cloud).**
For each shot, its 3 frames are shrunk to 384 px and sent in one request. All 8 requests go out together (up to 8 at a time). Shot 1 comes back as, for example:

```json
{
  "description": "A view from an airplane window showing the wing and clouds",
  "subjects": ["plane wing", "clouds"],
  "setting": "airplane cabin",
  "shot_type": "medium",
  "camera_motion": "handheld",
  "mood": ["calm"],
  "colors": ["blue", "white"],
  "background": "normal",
  "tags": ["airplane window", "wing", "clouds", "aviation", "window seat", "blue sky", "cruising altitude", "air travel"]
}
```

Shot 4 (00:25), where a phone is held up to the window, gets its own description. That is how a search can land on the right moment inside the clip.

**5b. SigLIP 2 makes the look embeddings (local).**
Each of the shot's 3 frames goes through the SigLIP 2 image encoder and becomes 768 numbers. The three are averaged and normalised into **one look vector per shot**. The middle frame is also saved as a 640 px thumbnail, and the colour ratios are checked for a green or blue screen.

**5c. Parakeet-TDT transcribes speech (local).**
The audio (up to 15 minutes) is transcribed with word times. Each shot gets the words spoken during it.

### Step 6. Save
For each shot, `library.db` stores: start and end time, description, details, tags, transcript, thumbnail path, the look vector (table `embeddings`, float16) and a row in the keyword index (`fts`). The clip itself gets the best description, the top tags, recording time and camera.

### Step 7. paraphrase-multilingual-MiniLM-L12-v2 makes the meaning embeddings (local)
For each shot, one piece of text is assembled, most important part first (the model reads the first 128 tokens):

```
A view from an airplane window showing the wing and clouds airplane cabin medium handheld plane wing clouds calm blue white
 . dji 20260911131448 0049 d
 . airplane window wing clouds aviation window seat blue sky cruising altitude air travel
 . mobile september sep friday 2026 afternoon
 . horizontal video clip recorded on Friday 11 September 2026 in the afternoon
```

The model turns it into 384 numbers: **one meaning vector per shot** (table `text_vectors`, float16).

### What is stored for this clip

| Per shot | Size |
|---|---|
| 1 look vector (SigLIP 2, 768 numbers) | about 1.5 KB |
| 1 meaning vector (MiniLM, 384 numbers) | about 0.75 KB |
| 1 keyword-index row, description, tags, transcript | text |
| 1 thumbnail | about 30–60 KB |

8 shots → **16 embeddings**, about 18 KB of vectors. Nemotron's answers are also cached, so re-indexing the same frames costs no API calls.

---

## Part 2: You search "plane wing above the clouds"

Everything below runs on your computer. No API call is made (unless you turned on Nemotron search expansion).

### Step 1. Date and time words
`timeq.py` looks for dates and times. There are none, so there is no date filter.

### Step 2. Filter words
The query is checked for type ("video", "photo", "music"…), duration ("under 3 seconds"), orientation ("vertical") and "green screen". None here, so nothing is excluded.

### Step 3. Three lookups
Each lookup returns a ranked list of **shots** (up to 300 each).

| Lookup | How | What it finds here (*illustrative*) |
|---|---|---|
| **Keywords** (SQLite FTS5, BM25) | Two queries: your exact words (weight 1.0), and your words plus built-in synonyms (weight 0.6). Matches in the file name count most, then description and tags, then speech, then folder | All 8 DJI shots contain "wing" or "clouds"; shot 1 ranks first |
| **Meaning** (paraphrase-multilingual-MiniLM-L12-v2) | Your sentence → 384 numbers → cosine similarity with every shot's meaning vector. Kept: score ≥ 0.30 and within 0.22 of the best | DJI shot 1: 0.74, shot 2: 0.71 … park clips: 0.08 (dropped) |
| **Look** (SigLIP 2 text encoder) | Your sentence → 768 numbers in the same space as the frames → similarity with every shot's look vector. Kept: within 0.12 of the best | Shots showing sky and a wing score highest; the phone shot (00:25) scores lower |

### Step 4. Combine (reciprocal-rank fusion)
Each shot earns points from every list it appears in:

```
points = weight × (0.4 + 0.6 × how close it is to that list's best) / (60 + its position in the list)
weights: exact words 1.0 · synonyms 0.6 · look 1.2 · meaning 1.3
```

A shot near the top of all three lists beats a shot that is first in only one. Here DJI shot 1 (00:00) wins.

### Step 5. Group by file and apply memory
- Shots are grouped by file. The file's score is its best shot's score plus a small bonus for each other matching shot.
- Memory: each "Good pick" adds 3% (up to 5), each "Show in folder" adds 4% (up to 5), each "Not this" removes 20% (up to 3). A file used in the last 15 minutes is lowered 10% to avoid repeats. The total stays between 40% and 115%.

### Step 6. Top results
Files are sorted and the top N (your choice: 5, 10, 20 or 50) are returned, each with its best 4 shots. The card shows the clip with shot 1's thumbnail. Clicking it opens the detail panel, plays from that shot and loops it, and the Description box shows that shot's description and details.

---

## Part 3: The same clip, other searches

### "phone held up to the plane window"
Keywords and meaning both point at shot 4 (00:25), whose own description mentions the phone. The result opens at **00:25**, not at the start of the clip.

### Hindi: "बादलों के ऊपर हवाई जहाज़" (airplane above the clouds)
- Keywords: no match (the descriptions are in English).
- SigLIP 2: weak, it is English-trained.
- **paraphrase-multilingual-MiniLM-L12-v2**: maps the Hindi sentence close to "airplane above the clouds" and finds the DJI shots.

### The clip indexed in Local only mode (no Nemotron description)
- Keywords and meaning only have the file name, folder and recording details.
- **SigLIP 2** still matches "clouds from a plane window" against the frames, so the clip is found.

### "1:15 pm on 11/9/26"
1. `timeq.py` reads 11/9/26 with your Windows date order (day-month in India) → 11 Sep 2026, around 1:15 PM (±2 minutes).
2. The clip was recorded from 1:14:48 PM for 55 s, so it covers 1:15 PM. It matches, and the time 1:15:00 PM is 12 s into the clip.
3. The result opens the clip at **0:12**.
4. If you had typed it month-first (9/11/26), it would first be read as 9 Nov 2026. Nothing was recorded then, so it is re-read as 11 Sep 2026 and the page says so.

### "Find similar" on shot 1
- **SigLIP 2**: shot 1's look vector against all others → other window and sky shots.
- **paraphrase-multilingual-MiniLM-L12-v2**: shot 1's meaning vector against all others → other flight and travel shots, even if they look different.
- The two lists are combined the same way as a search, the clip itself is left out, and the top N files are shown.

---

## Part 4: Planning a video around the clip (Tavily)

You are making a 60-second short, "A weekend flight to Goa", and open **B-roll plan**.

1. **Research.** Tavily `/search` with the topic, `include_answer: "basic"`, 6 results (1 credit, cached for a day). The answer and the snippets become numbered notes.
2. **Plan.** **Nemotron 3 Ultra** gets the topic, the length and the notes and returns about 10 beats. Two of them:
   - "We took off just after one." Shot: *plane wing above the clouds*, search words `plane wing above clouds`.
   - "By sunset we were on the beach." Shot: *beach shack at sunset*, search words `beach shack sunset`.
3. **Match.** Each beat's search words run through the normal local search (Part 2). The first beat finds this DJI clip, shot 1 at 00:00, plus two other window shots. The second finds nothing.
4. **Gap.** The second beat shows **Find free videos**: Tavily `/search` for `beach shack sunset free stock video` on pexels.com, pixabay.com and mixkit.co (1 credit). Four free clips appear, each with a "Free to use, no credit" badge.
5. **Save to Inbox.** Tavily `/extract` reads the Pexels page (1 credit); the app picks the 1920×1080 file from `videos.pexels.com`; **Nemotron 3 Nano** turns the licence part of the page into a credit line; the file is downloaded to the Inbox as `pexels-beach-shack-at-sunset-….mp4` and indexed exactly like Part 1, with the licence attached. Plan the video again and the beat is covered.
6. **Licences.** An old download in the same folder, `123456__InspectorJ__wind-chime-gamelan.wav`, is recognised by its name. **Check** reads `freesound.org/people/InspectorJ/sounds/123456/`; the rules find "Attribution 4.0" → **CC BY**, credit needed, commercial use allowed. **Copy credits** gives the line for the video description.

Only the topic, the search words, the page addresses and a public licence excerpt left the computer. Details: [tavily.md](tavily.md).

---

## Where this lives in the code

| Step | File |
|---|---|
| Watcher, queue, change check | `engine/caa/watcher.py`, `engine/caa/indexer.py` (`is_current`, `scan`, `_worker`) |
| Probe, shots, keyframes, chroma | `engine/caa/media.py` (`probe`, `detect_shots`, `sample_frames`, `extract_frames`, `chroma_ratios`) |
| Recording time, camera, GPS | `engine/caa/metadata.py` |
| Nemotron requests and cache | `engine/caa/nemotron.py` (`caption_frames`, `describe_audio`) |
| SigLIP 2 | `engine/caa/embed.py` (`SiglipEmbedder`) |
| paraphrase-multilingual-MiniLM-L12-v2 and the per-shot text | `engine/caa/textembed.py` (`TransformerTextEmbedder`, `segment_doc`, `meta_phrase`, `SemanticIndex`) |
| Parakeet | `engine/caa/asr.py` |
| Dates and times | `engine/caa/timeq.py` |
| Search, fusion, memory, find similar | `engine/caa/search.py` (`search`, `_search`, `_memory`, `similar`) |
| Storage | `engine/caa/db.py` (`assets`, `segments`, `fts`, `embeddings`, `text_vectors`, `downloads`) |
| Tavily, free assets, licences | `engine/caa/tavily.py`, `engine/caa/sources.py` (`WebAssets.search`, `save`, `find_source`, `SourceAudit`) |
| B-roll plan | `engine/caa/broll.py` (`BrollPlanner.plan`) |
