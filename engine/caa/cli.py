from __future__ import annotations

import argparse
import logging
import platform
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import __version__
from .config import load_settings

OK, BAD, WARN = "[ok]", "[!!]", "[--]"


def _services(args, start_worker=True, watch=True):
    from .services import Services

    settings = load_settings(args.home)
    return Services(settings, start_worker=start_worker, watch=watch)


def cmd_serve(args) -> None:
    import uvicorn

    from .api import create_app

    services = _services(args)
    port = args.port or services.settings.port
    app = create_app(services)
    url = f"http://127.0.0.1:{port}"
    print(f"Creator Asset Assistant {__version__} running at {url}")
    print(f"Data folder: {services.settings.home}")
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host or services.settings.host, port=port, log_level="warning")


def cmd_index(args) -> None:
    services = _services(args, start_worker=False, watch=False)
    if hasattr(services.embedder, "wait"):
        print("Loading embedding model...")
        services.embedder.wait()
    for raw in args.paths:
        p = Path(raw).expanduser().resolve()
        if not p.is_dir():
            print(f"{BAD} not a folder: {p}")
            continue
        services.db.add_folder(str(p))
    services.indexer.scan()
    total = services.indexer.q.qsize()
    print(f"Indexing {total} files (embedder: {services.embedder.name}, Nemotron: {'on' if services.tf.available else 'off'})")
    t0 = time.time()
    done = 0
    while not services.indexer.q.empty():
        path = services.indexer.q.get()
        done += 1
        t1 = time.time()
        try:
            services.indexer.index_file(path)
            print(f"  [{done}/{total}] {Path(path).name} ({time.time() - t1:.1f}s)")
        except Exception as exc:
            print(f"  [{done}/{total}] {BAD} {Path(path).name}: {exc}")
        finally:
            services.indexer.release(path)
    print(f"Done in {time.time() - t0:.1f}s. {services.db.stats()}")


def cmd_search(args) -> None:
    services = _services(args, start_worker=False, watch=False)
    if hasattr(services.embedder, "wait"):
        services.embedder.wait()
    res = services.search.search(" ".join(args.query), kind=args.kind, limit=args.limit)
    print(f"plan: {res['plan']}")
    for i, r in enumerate(res["results"], 1):
        h = r["hits"][0] if r["hits"] else {}
        print(f"{i:2}. [{r['kind']}] {r['name']}  {h.get('tc', '')}  score={r['score']}  {r.get('caption') or ''}")
        print(f"     {r['path']}")


def cmd_models(args) -> None:
    from .nemotron import TokenFactory

    s = load_settings(args.home)
    tf = TokenFactory(s)
    try:
        ids = tf.list_models()
    except Exception as exc:
        print(f"{BAD} {exc}")
        sys.exit(1)
    print(f"Your Token Factory account serves {len(ids)} models (* = NVIDIA):")
    for i in ids:
        mark = "*" if "nvidia" in i.lower() or "nemotron" in i.lower() else " "
        print(f"  {mark} {i}")
    resolved = tf.resolve_models(ids, apply=args.apply)
    print("\nRole -> model" + (" (saved)" if args.apply else " (dry run, add --apply to save)"))
    for k, v in resolved.items():
        print(f"  {k:10} {v or '(none on your account)'}")


def cmd_set_key(args) -> None:
    try:
        import keyring

        keyring.set_password("CreatorAssetAssistant", args.name, args.value)
        print(f"{OK} Stored {args.name} in the system keychain.")
    except Exception as exc:
        print(f"{BAD} Could not use the system keychain ({exc}). Put {args.name}=... in a .env file instead.")


def cmd_web(args) -> None:
    services = _services(args, start_worker=False, watch=False)
    why = services.tavily.why_off()
    if why:
        print(f"{BAD} {why}")
        sys.exit(1)
    res = services.web.search(" ".join(args.query), args.kind, args.limit)
    print(f"Free {args.kind or 'assets'} on {', '.join(res.get('sites') or [])}:")
    for i, it in enumerate(res["items"], 1):
        lic = it["licence"]
        print(f"{i:2}. [{it['site_name']}{' item' if it['item'] else ''}] {it['title']}")
        print(f"     {it['url']}\n     {lic['licence']}; commercial {_yn(lic['commercial_ok'])}; credit {_yn(lic['attribution_required'])}")
    if args.save and res["items"]:
        it = res["items"][args.save - 1]
        out = services.web.save(it["url"], args.kind)
        print(f"{OK} Saved {out['name']} to {out['inbox']} ({out['licence']['licence']})")


def cmd_source(args) -> None:
    from .sources import identify

    services = _services(args, start_worker=False, watch=False)
    for name in args.files:
        ident = identify(name)
        if not ident:
            print(f"{WARN} {Path(name).name}: not a recognised stock file name")
            continue
        lic = services.web.find_source(name) if services.tavily.available else None
        if not lic:
            print(f"{OK} {Path(name).name}: looks like {ident['site']} ({ident.get('url') or ident['query']}); add a Tavily key to look it up")
            continue
        print(f"{OK} {Path(name).name}: {lic.get('status')} {lic.get('source_url') or ''}")
        print(f"     {lic['licence']}; commercial {_yn(lic['commercial_ok'])}; credit {_yn(lic['attribution_required'])}")
        if lic.get("credit"):
            print(f"     credit: {lic['credit']}")


def cmd_broll(args) -> None:
    services = _services(args, start_worker=False, watch=False)
    if hasattr(services.text_embedder, "wait"):
        services.text_embedder.wait()
    services.semantic.sync()
    script = Path(args.script).read_text(encoding="utf-8") if args.script else ""
    plan = services.broll.plan(" ".join(args.topic), script, args.seconds, not args.no_research)
    print(f"{plan['title']}  ({plan['model'] or 'no Nemotron'}, {len(plan['sources'])} sources, {plan['took_ms']} ms)")
    if plan["hook"]:
        print(f"Hook: {plan['hook']}")
    for i, b in enumerate(plan["beats"], 1):
        print(f"{i:2}. {b['shot'] or b['line']}  [{b['search']}]  {b['seconds'] or ''}s")
        for m in b["matches"]:
            print(f"     -> {m['name']} {m.get('tc') or ''}")
        if b["gap"]:
            print("     -> nothing in your library; try: caa web " + b["search"] + (f" --kind {b['kind']}" if b["kind"] != "video" else " --kind video"))
    for f in plan["facts"]:
        print(f"  fact: {f['fact']}" + (f"  ({f['source']['url']})" if f.get("source") else ""))


def _yn(v) -> str:
    return "yes" if v is True else "no" if v is False else "check"


def cmd_doctor(args) -> None:
    import numpy as np
    from PIL import Image, ImageDraw

    from . import media
    from .nemotron import TokenFactory

    s = load_settings(args.home)
    print(f"Creator Asset Assistant {__version__} | Python {platform.python_version()} | {platform.system()} {platform.release()}")
    print(f"Data folder: {s.home}\nPrivacy mode: {s.privacy_mode}\n")
    ok = sys.version_info >= (3, 10)
    print(f"{OK if ok else BAD} Python >= 3.10")
    loc = media.ffmpeg_location() if media.ffmpeg_available() else None
    print(f"{OK} FFmpeg: {loc}" if loc else f"{BAD} FFmpeg not found  -> winget install Gyan.FFmpeg, then open a new terminal")
    try:
        from .embed import get_embedder

        t = time.time()
        emb = get_embedder("siglip" if s.embed_backend != "fallback" else "fallback", s.embed_model)
        print(f"{OK} Embedder {emb.name} (dim {emb.dim}, loaded in {time.time() - t:.1f}s)")
        if emb.supports_text:
            red = Image.new("RGB", (224, 224), (220, 30, 30))
            sea = Image.new("RGB", (224, 224), (40, 110, 200))
            ImageDraw.Draw(sea).rectangle([0, 150, 224, 224], fill=(230, 200, 140))
            iv = emb.embed_images([red, sea])
            tv = emb.embed_texts(["a plain red square", "a blue sea above a sandy beach"])
            sims = iv @ tv.T
            good = sims[0, 0] > sims[0, 1] and sims[1, 1] > sims[1, 0]
            print(f"{OK if good else BAD} Text-to-picture matching sanity check "
                  f"(red {sims[0, 0]:.3f} vs {sims[0, 1]:.3f}, beach {sims[1, 1]:.3f} vs {sims[1, 0]:.3f})")
    except Exception as exc:
        print(f"{BAD} SigLIP embedder failed: {exc}\n     -> pip install torch transformers sentencepiece (see README)")
    if s.semantic_search:
        try:
            from .textembed import TransformerTextEmbedder

            t = time.time()
            te = TransformerTextEmbedder(s.text_model)
            print(f"{OK} Meaning search model {s.text_model} (dim {te.dim}, loaded in {time.time() - t:.1f}s)")
            docs = ["A man running through heavy rain at night", "Flames burning against a green screen background",
                    "A mellow lo-fi chill music loop"]
            queries = ["jogger in a storm", "fire for chroma keying", "relaxing beats", "\u092c\u093e\u0930\u093f\u0936 \u092e\u0947\u0902 \u0926\u094c\u0921\u093c\u0924\u093e \u0906\u0926\u092e\u0940"]
            t = time.time()
            sims = te.embed(queries) @ te.embed(docs).T
            ms = (time.time() - t) * 1000
            picks = [int(row.argmax()) for row in sims]
            good = picks == [0, 1, 2, 0]
            print(f"{OK if good else WARN} Meaning sanity check in {ms:.0f} ms: "
                  + ", ".join(f"'{q}' -> {docs[i][:22]}... ({sims[k, i]:.2f})" for k, (q, i) in
                              enumerate(zip(queries[:3] + ["Hindi: man running in rain"], picks))))
        except Exception as exc:
            print(f"{WARN} Meaning search model failed: {exc}\n     -> pip install -r engine/requirements-ml.txt")
    if s.asr_enabled:
        try:
            from .asr import ParakeetTranscriber

            t = time.time()
            tr = ParakeetTranscriber(s.asr_model, s.asr_model_dir(), s.asr_quantization)
            sr = 16000
            tone = (0.1 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)).astype(np.float32)
            tr.transcribe(tone, sr)
            print(f"{OK} Parakeet ASR ({s.asr_model}, {time.time() - t:.1f}s) in {s.asr_model_dir()}")
        except Exception as exc:
            print(f"{WARN} Parakeet ASR unavailable: {exc}\n     -> pip install -r engine/requirements-ml.txt (optional)")
    key = s.nebius_api_key
    print(f"{OK if key else WARN} NEBIUS_API_KEY " + ("found" if key else "missing -> captions and query understanding off"))
    print(f"{OK if s.tavily_api_key else WARN} TAVILY_API_KEY " + ("found" if s.tavily_api_key else "missing -> free assets on the web, licence checks and b-roll research off"))
    if s.tavily_api_key and s.privacy_mode != "local":
        from .sources import identify
        from .tavily import Tavily

        t = time.time()
        try:
            print(f"{OK} Tavily reachable ({Tavily(s).ping()}, {time.time() - t:.1f}s)")
        except Exception as exc:
            print(f"{BAD} Tavily: {exc}")
        demo = identify("pexels-cottonbro-5698420.jpg")
        print(f"{OK if demo else BAD} Source from a file name: pexels-cottonbro-5698420.jpg -> {demo and demo.get('url')}")
    if key and s.privacy_mode != "local":
        tf = TokenFactory(s)
        try:
            ids = tf.list_models()
            print(f"{OK} Token Factory reachable ({len(ids)} models)")
            resolved = tf.resolve_models(ids, apply=True)
            for role, mid in resolved.items():
                print(f"     {role:10} {mid if mid else '(none on your account)'}{'' if not mid or mid in ids else ' (NOT AVAILABLE)'}")
        except Exception as exc:
            print(f"{BAD} Token Factory: {exc}")
            return
        img = Image.new("RGB", (384, 216), (0, 177, 64))
        ImageDraw.Draw(img).ellipse([150, 60, 240, 160], fill=(255, 120, 0))
        t = time.time()
        cap = tf.caption_frames([img], "doctor_test.png", what="image")
        print(f"{OK if cap else BAD} Vision caption ({s.models['vision']}, {time.time() - t:.1f}s): {cap and cap.get('description')}")
        sr = 16000
        x = np.random.default_rng(0).normal(0, 0.3, sr // 2).astype(np.float32) * np.hanning(sr // 2).astype(np.float32)
        t = time.time()
        from . import audio as audiofx

        feat = audiofx.features(x, sr)
        ad = tf.describe_audio(media.wav_bytes(x, sr), "whoosh_fast.wav", 0.5, 0.5, feat, folder="sfx transitions",
                               local_tags=audiofx.tags_for(feat))
        if ad:
            how = ad.get("_model", "?") + ("; from audio analysis, no audio-input model on your account" if ad.get("_source") == "analysis" else "")
        else:
            how = s.models.get("omni") or s.models.get("fast")
        print(f"{OK if ad else WARN} Audio description ({how}, {time.time() - t:.1f}s): {ad and ad.get('description')}")
        t = time.time()
        plan = tf.rewrite_query("punchy whoosh for a jump cut")
        print(f"{OK if plan else BAD} Query rewrite ({s.models['fast']}, {time.time() - t:.1f}s): {plan}")
        if tf.stats["last_error"]:
            print(f"     last error: {tf.stats['last_error']}")
    print("\nZero Data Retention can't be checked from here: confirm it is ticked and saved in your Token Factory organisation settings.")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="caa", description="Creator Asset Assistant engine")
    ap.add_argument("--home", help="data folder (default: %%LOCALAPPDATA%%\\CreatorAssetAssistant)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("serve", help="run the local app (default)")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("index", help="add folders and index them now")
    p.add_argument("paths", nargs="+")
    p.set_defaults(fn=cmd_index)
    p = sub.add_parser("search", help="search from the terminal")
    p.add_argument("query", nargs="+")
    p.add_argument("--kind", choices=["video", "image", "audio", "template"])
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(fn=cmd_search)
    p = sub.add_parser("doctor", help="check FFmpeg, models and API keys")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("models", help="list Token Factory models and map them to roles")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_models)
    p = sub.add_parser("web", help="find free assets on the web with Tavily")
    p.add_argument("query", nargs="+")
    p.add_argument("--kind", choices=["video", "image", "audio", "template"])
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--save", type=int, help="download result N to the Inbox")
    p.set_defaults(fn=cmd_web)
    p = sub.add_parser("source", help="find where stock files came from and their licence")
    p.add_argument("files", nargs="+")
    p.set_defaults(fn=cmd_source)
    p = sub.add_parser("broll", help="research a topic and plan b-roll from your library")
    p.add_argument("topic", nargs="+")
    p.add_argument("--script", help="a text file with your script")
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--no-research", action="store_true")
    p.set_defaults(fn=cmd_broll)
    p = sub.add_parser("set-key", help="store an API key in the system keychain")
    p.add_argument("name", choices=["NEBIUS_API_KEY", "TAVILY_API_KEY"])
    p.add_argument("value")
    p.set_defaults(fn=cmd_set_key)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if not getattr(args, "fn", None):
        args.fn, args.host, args.port, args.no_browser = cmd_serve, None, None, False
    args.fn(args)


if __name__ == "__main__":
    main()
