SPEC.md — avm: Audio→Video Maker CLI

1) Overview & Goals
	•	Convert a narrated lesson (audio.wav) plus optional slides.md into a polished 1080p/30fps YouTube-ready MP4 with captions, watermark, intro/outro, and thumbnail.
	•	Keep v1 deterministic and local-first (no cloud UI, no LLM dependency).
	•	Provide a clean, modular Python 3.11 pipeline with resumable steps and cached artifacts.

2) User Stories (creator persona)
	•	As a creator, I want to transcribe my narration to SRT so viewers get accurate captions.
	•	As a creator, I want Markdown slides rendered to stylish full-HD images using my brand theme.
	•	As a creator, I want the audio and slides auto-timed with subtle Ken-Burns motion.
	•	As a creator, I want my logo watermark and quick intro/outro stings added automatically.
	•	As a creator, I want a one-liner (avm all) that builds the full video and thumbnail.
	•	As a creator, I need sane defaults but also flags to tweak levels, ducking, caption style, and export settings.

3) Requirements

Functional
	•	Input: projects/<slug>/audio.wav (mono), optional projects/<slug>/slides.md.
	•	Transcription (Whisper/faster-whisper) → captions.srt + captions_words.json (word timestamps).
	•	Slides: Render each top-level Markdown section (# or ##) → 1920×1080 PNG via Playwright+Chromium using templates/slide.html + theming from styles.yml.
	•	Timeline: Distribute total audio across slides using v1 heuristic (see §11).
	•	Ken-Burns: per-slide pan/zoom motion (gentle; defaults tunable).
	•	Captions: Option to burn into video or attach soft SRT (muxed).
	•	Audio: Voice normalized to ≈ −14 LUFS (YouTube loudness target). Add music bed with sidechain ducking (ffmpeg sidechaincompress) with exposed params.
	•	Branding: Optional logo.png bottom-right; optional intro.mp4/outro.mp4.
	•	Export: H.264 (libx264), 1080p, 30 fps, AAC audio, MP4 container. Generate PNG thumbnail.
	•	CLI: avm with subcommands transcribe, slides, render, thumb, all.
	•	Caching: Skip steps if up-to-date unless --force.

Non-Functional
	•	Deterministic, reproducible output given same inputs/config.
	•	Runs on macOS/Linux; CPU-only baseline; optional GPU for faster-whisper.
	•	Structured JSON logging; clear exit codes; graceful error messages.
	•	Unit+golden tests for timing/captions; CI-friendly (no GUI popups).
	•	Average 10-min lesson completes on a modern laptop in reasonable time (see §17).

4) Architecture & Data Flow
	•	Stages: Ingest → Transcribe → Slide Render → Timeline & Motion Plan → Compose Video (visuals) → Audio Master (voice normalize + music duck) → Mux + Captions → Thumbnail.
	•	Artifacts are stored in projects/<slug>/build/ with content-addressed names where relevant.

sequenceDiagram
    participant U as User
    participant CLI as avm (CLI)
    participant TR as Transcriber
    participant SR as SlideRenderer
    participant RL as RenderLogic (timeline/Ken-Burns)
    participant VC as VideoComposer (moviepy/ffmpeg)
    participant AP as AudioProc (ffmpeg)
    participant MX as Muxer (ffmpeg)
    participant TH as Thumbnailer

    U->>CLI: avm all --project mylesson
    CLI->>TR: transcribe(audio.wav) -> captions.srt + words.json
    TR-->>CLI: artifacts
    CLI->>SR: render(slides.md, styles.yml, template) -> slide_###.png
    SR-->>CLI: PNGs
    CLI->>RL: plan(words.json, slides.md) -> timeline.json (segments, motion)
    RL-->>CLI: timeline.json
    CLI->>VC: compose(slide PNGs, timeline, captions[SRT burn?]) -> video_nocap.mp4
    VC-->>CLI: video_nocap.mp4 (or video_with_burned_caps.mp4)
    CLI->>AP: process(audio.wav, music.mp3) -> voice_norm.wav, music_ducked.wav
    AP-->>CLI: mastered audio WAVs
    CLI->>MX: mux(video, audio, srt?) -> final.mp4
    MX-->>CLI: projects/mylesson/final.mp4
    CLI->>TH: generate_thumbnail -> thumb.png
    TH-->>CLI: thumb.png
    CLI-->>U: Done (paths, metrics)

5) Dependencies (versions range)
	•	Python: 3.11
	•	Core:
	•	faster-whisper>=0.10,<0.12 (or openai-whisper>=20231117 if CPU-only fallback)
	•	moviepy>=2.0,<3.0
	•	ffmpeg CLI >=6.0 (must be on PATH), libx264, aac
	•	playwright>=1.47,<1.60 (+ playwright install chromium)
	•	markdown-it-py>=3.0,<4.0
	•	jinja2>=3.1,<4.0
	•	PyYAML>=6.0,<7.0
	•	pydantic>=2.7,<3.0
	•	srt>=3.5,<4.0 (or pysrt>=1.1,<2.0)
	•	Pillow>=10.2,<12.0
	•	numpy>=1.26,<2.0
	•	rich>=13.7,<14.0 or structlog>=24.1,<25.0 for logs
	•	typer>=0.12,<0.13 (CLI)
	•	Optional:
	•	onnxruntime-gpu>=1.18,<1.20 (GPU)
	•	llvmlite (if needed by whisper variants)

6) File/Folder Layout (final tree)

avm/
  avm.py                      # CLI entry (Typer)
  pipeline/
    __init__.py
    io_paths.py               # path helpers, cache checks
    transcribe.py             # Whisper/faster-whisper wrapper
    slides.py                 # Markdown → HTML → PNG via Playwright
    timeline.py               # slide timing, Ken-Burns plan
    captions.py               # SRT helpers, burn/soft attach
    audio.py                  # normalize, music duck, export WAVs
    video.py                  # stitch slides + motion, overlay watermark, intro/outro
    mux.py                    # final muxing
    thumb.py                  # thumbnail generation
    logging.py                # JSON logging config
    errors.py                 # custom exceptions + exit codes
    testing.py                # test utilities & goldens harness
  templates/
    slide.html                # HTML skeleton (see below)
    thumb.html                # optional HTML for thumbnail
  styles.yml                  # global theme defaults
  examples/
    slides.md                 # example (see below)
    logo.png
    intro.mp4
    outro.mp4
    music.mp3
  projects/
    mylesson/
      audio.wav
      slides.md               # optional
      config.yml              # per-project overrides
      build/                  # all artifacts written here
        captions.srt
        captions_words.json
        slides/
          slide_001.png
          ...
        timeline.json
        video_nocap.mp4
        voice_norm.wav
        music_ducked.wav
        final.mp4
        thumb.png
  tests/
    test_timeline.py
    test_captions.py
    goldens/
      10s.wav ...
  pyproject.toml
  README.md
  LICENSE

7) Configuration Files

styles.yml (global theme defaults)

theme: "dark"            # dark|light
font_family: "Inter, system-ui, sans-serif"
brand_color: "#56B3F1"
text_color: "#EDEDED"
bg_color: "#0B0B0E"
heading_size: 64         # px
body_size: 40
margin_px: 96
logo:
  path: "examples/logo.png"
  opacity: 0.85
  width_px: 220
  position: "bottom-right"   # bottom-right|top-right|bottom-left|top-left
caption:
  max_lines: 2
  font_size: 40
  stroke_px: 3
  safe_bottom_pct: 12       # keep captions above 12% from bottom
kenburns:
  zoom_start: 1.05
  zoom_end: 1.12
  pan: "auto"               # auto|left|right|up|down
  easing: "easeInOutSine"
export:
  fps: 30
  crf: 18
  preset: "medium"
audio:
  target_lufs: -14.0
  music_db: -28
  ducking:
    threshold: -20
    ratio: 8
    attack_ms: 50
    release_ms: 300

projects/<slug>/config.yml (per-video overrides)

slug: "mylesson"
title: "Intro to Cell Membranes"
author: "J. Hong"
watermark: true
intro: "examples/intro.mp4"
outro: "examples/outro.mp4"
music: "examples/music.mp3"
burn_captions: false          # false = soft subs
slides:
  theme: "dark"
  background_image: null
  max_chars_per_line: 52
timeline:
  method: "weighted"          # weighted|even
  min_slide_sec: 5.0
  max_slide_sec: 60.0
  gap_sec: 0.25               # crossfade/transition spacing
thumbnail:
  title: "Cell Membrane Basics"
  subtitle: "Phospholipids, Proteins, Transport"
  bg: "#10121A"
  use_html: true

8) Storyboard JSON Schema (v1.5)

(Not used by v1 pipeline; reserved for LLM-assisted planning.)

JSON Schema (schema/storyboard.schema.json):

{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Storyboard",
  "type": "object",
  "required": ["beats", "meta"],
  "properties": {
    "meta": {
      "type": "object",
      "required": ["title", "duration_sec"],
      "properties": {
        "title": {"type": "string"},
        "duration_sec": {"type": "number", "minimum": 0},
        "fps": {"type": "integer", "minimum": 1, "default": 30}
      }
    },
    "beats": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["start", "end", "title", "bullets"],
        "properties": {
          "start": {"type": "number", "minimum": 0},
          "end": {"type": "number", "exclusiveMinimum": 0},
          "title": {"type": "string"},
          "bullets": {"type": "array", "items": {"type": "string"}},
          "latex": {"type": "array", "items": {"type": "string"}},
          "overlays": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["type", "start", "end"],
              "properties": {
                "type": {"type": "string", "enum": ["callout", "equation", "image"]},
                "start": {"type": "number"},
                "end": {"type": "number"},
                "text": {"type": "string"},
                "src": {"type": "string"},
                "x_pct": {"type": "number", "minimum": 0, "maximum": 100},
                "y_pct": {"type": "number", "minimum": 0, "maximum": 100}
              }
            }
          }
        }
      }
    }
  }
}

Minimal example:

{
  "meta": {"title": "Acids & Bases", "duration_sec": 600, "fps": 30},
  "beats": [
    {"start": 0, "end": 120, "title": "Definition", "bullets": ["Arrhenius", "Bronsted-Lowry"]},
    {"start": 120, "end": 360, "title": "pH Scale", "bullets": ["Log scale", "Neutral 7.0"]},
    {"start": 360, "end": 600, "title": "Titrations", "bullets": ["Equivalence", "Indicators"]}
  ]
}

9) CLI Spec

Executable: avm

Global flags
	•	--project, -p <slug> (required for all commands)
	•	--root <path> (default: repo root)
	•	--force (recompute even if cached)
	•	--verbose, -v (increase log level)
	•	--quiet, -q (errors only)
	•	--json-logs (structured logs)
	•	--tmpdir <path> (work dir override)
	•	--gpu (enable GPU for faster-whisper if available)

Subcommands

transcribe
	•	Args: --model <small|medium|large-v3> (default: small)
	•	Options: --language <auto|en|...>, --diarize (ignored v1), --threads <int>
	•	Output: build/captions.srt, build/captions_words.json

slides
	•	Args: --md <path> (default: projects/<slug>/slides.md)
	•	Options: --styles <path> (default styles.yml), --template <path> (default templates/slide.html)
	•	Output: build/slides/slide_###.png

render
	•	Options:
	•	--burn-captions/--no-burn-captions (default from config)
	•	--watermark/--no-watermark
	•	--intro <path>, --outro <path>
	•	--music <path> (or disable if unset)
	•	--method <weighted|even> (timeline method)
	•	--crf <int> (default 18), --preset <ultrafast..veryslow> (default medium)
	•	Output: build/final.mp4

thumb
	•	Options: --title <str>, --subtitle <str>, --use-html/--use-pillow
	•	Output: build/thumb.png

all
	•	Runs transcribe → slides → render → thumb with applicable flags.

Exit Codes
	•	0 success
	•	10 invalid project/paths
	•	11 ffmpeg missing/unsupported
	•	12 Chromium/Playwright not installed
	•	13 transcription failure
	•	14 render failure
	•	15 mux failure
	•	16 config parse error
	•	20 unknown error

Examples

avm all -p mylesson --gpu --burn-captions --watermark
avm transcribe -p mylesson --model medium
avm slides -p mylesson --styles styles.yml
avm render -p mylesson --music examples/music.mp3 --crf 20 --preset slow
avm thumb -p mylesson --title "Stoichiometry" --subtitle "Tips for AP Chem"

10) Module Responsibilities
	•	io_paths.py: Resolve inputs/outputs, cache checks, hash helpers.
	•	transcribe.py: Wrapper for faster-whisper; write SRT + per-word JSON with {word, start, end, prob}.
	•	slides.py: Parse Markdown sections → render HTML (Jinja2 + template + styles.yml) → Playwright screenshot to PNG.
	•	timeline.py: Map total audio to slide durations; compute Ken-Burns params; emit timeline.json with per-slide {start,end,zoom_from,zoom_to,pan}.
	•	captions.py: SRT read/write; line reflow to max chars; burn overlay spec (position, stroke).
	•	audio.py: Two-pass loudnorm on voice to −14 LUFS; mix music at target level; apply sidechaincompress.
	•	video.py: Build visual track with moviepy: slide PNGs + transforms; add watermark; splice intro/outro; optional burned captions.
	•	mux.py: ffmpeg muxing of video+audio; attach soft SRT if requested; set metadata (title, chapters TBD).
	•	thumb.py: Generate thumbnail via HTML→PNG or Pillow composition.
	•	logging.py: JSON logger (module, step, duration, err).
	•	errors.py: Exception classes mapped to exit codes.
	•	testing.py: Utilities to generate fixtures, compare goldens (SSIM/PSNR for images; byte-tolerant SRT compare).

11) Rendering Algorithm

Slide Segmentation (v1 heuristic)
	•	If slides.md exists:
	•	Split on top-level headers (^#  or ^## ). Each section = one slide.
	•	Weighted method (default): weight by token count (words) per section.
	•	dur_i = clamp( min_slide_sec, max_slide_sec, total_audio_sec * (tokens_i / tokens_total) )
	•	Even method: dur_i = total_audio_sec / N.
	•	If no slides.md: create 1 slide spanning full duration (plus watermark/branding).

Motion (Ken-Burns)
	•	Defaults from styles.yml.kenburns. For slide with duration d:
	•	zoom(t) = lerp(zoom_start, zoom_end, ease(t/d))
	•	Pan direction alternates L→R, R→L, U→D cycling per slide.
	•	Pan offset limited to keep content inside frame (no letterboxing).
	•	Crossfade between slides: gap_sec (default 0.25s) with 12-frame dissolve at 30fps.

Caption Placement
	•	Two lines max (caption.max_lines), centered, bottom safe area:
	•	Baseline Y = 1.0 - safe_bottom_pct/100 - line_height*lines
	•	Outline stroke to ensure readability on bright backgrounds.
	•	If burned, apply drop shadow or stroke defined in styles.yml.

Safe Title Area
	•	Keep essential text within 10% margin on all sides for YouTube UI overlays.

12) Audio Pipeline

Voice Normalization (two-pass loudnorm)
	•	Measure pass:
ffmpeg -i audio.wav -af loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json -f null -
	•	Apply pass with measured measured_*:
-af loudnorm=I=-14:TP=-1.0:LRA=11:measured_I=...:measured_LRA=...:measured_TP=...:measured_thresh=...:linear=true

Music Bed & Sidechain Ducking
	•	Music pre-gain to ~−28 dBFS (configurable), loop/trim to duration.
	•	Sidechain chain (example):

[voice]aformat=channel_layouts=stereo,volume=1.0[lv];
[music]aformat=channel_layouts=stereo,volume=-12dB[lm];
[lm][lv]sidechaincompress=threshold=-20dB:ratio=8:attack=50:release=300:makeup=0[mduck];
[lv]alimiter=limit=-1dB[lv2];
[mduck]alimiter=limit=-1dB[m2];
[lv2][m2]amix=inputs=2:weights=1 1:duration=longest[out]

	•	Output mastered WAV at 48kHz stereo, final limiter to avoid clipping (−1 dBTP ceiling).

13) Captions
	•	Transcription output: captions.srt with standard HH:MM:SS,mmm timing; captions_words.json with granular word timings.
	•	Burned captions: moviepy textclip overlay (fallback) or ffmpeg subtitles= filter. Use font, size, stroke from styles.yml.
	•	Soft subs: Attach captions.srt as a subtitle stream:
-i final_video.mp4 -i captions.srt -c copy -c:s mov_text -metadata:s:s:0 language=eng out.mp4
	•	Line wrapping at max chars; split on space; never exceed 2 lines; adjust timing to avoid overlap across slide cuts.

14) Thumbnail Generation
	•	Option A (default): HTML (templates/thumb.html) → Playwright screenshot at 1280×720 or 1920×1080.
	•	Option B: Pillow composition (gradient bg, title, subtitle, logo).
	•	Layout spec:
	•	Background: solid or gradient.
	•	Title: bold, 2–3 lines max, left or center aligned.
	•	Subtitle: smaller, single line.
	•	Logo: top-right with 10% margin.
	•	Safe margins: 8% on edges.
	•	Auto text scaling to fit.

15) Logging & Error Handling
	•	Use JSON logs with fields: ts, level, step, project, msg, duration_ms, extra.
	•	Wrap external calls (ffmpeg, playwright) with timeouts and retries (2 attempts; exponential backoff starting 1s).
	•	Catch and map errors to exit codes; print actionable hints (e.g., playwright install chromium).
	•	Progress bars for long ops (rich); write a build/manifest.json with artifact paths & timing.

16) Testing Strategy
	•	Unit:
	•	timeline.py: token weighting → durations sum to total; clamping; min/max respected.
	•	captions.py: wrap/split, no overlap; timing shift around slide transitions.
	•	Golden samples:
	•	10-second audio + 3-slide markdown → verify exact timeline.json and slide PNG SSIM ≥ 0.98.
	•	Audio pipeline: measure LUFS ≈ −14 ±0.5.
	•	Integration:
	•	avm all on example project; assert artifacts exist; ffprobe stream maps correct.
	•	CI:
	•	Headless Playwright; ffmpeg presence check; skip GPU tests if unavailable.

17) Performance Notes
	•	10-minute mono WAV, CPU-only:
	•	Transcribe (small model): ~3–6 min
	•	Slides (5–10 slides): ~10–20 s
	•	Compose (moviepy transforms): ~2–4 min
	•	Audio normalize/mix: ~20–40 s
	•	Mux: ~10–20 s
	•	Cache captions.srt & word JSON; re-use slides unless md/styles changed (hash inputs).

18) Risks & Mitigations
	•	Whisper performance: Offer --model small default; GPU flag when available.
	•	Playwright headless issues: Pin Chromium revision via Playwright; retry screenshots.
	•	ffmpeg variance: Require ≥6.0; probe features; fail fast with guidance.
	•	Caption legibility: Stroke/outline defaults; safe area enforcement.
	•	Font availability: Bundle web-safe stack; allow user font override in styles.yml.

19) Milestones
	•	v1 (2 days):
	•	CLI skeleton; transcription; slides; timeline heuristic; Ken-Burns; audio normalize+duck; watermark; intro/outro; export; thumbnail; tests; docs.
	•	v1.5 (1 weekend):
	•	Storyboard JSON + Gemini Flash integration; chapter markers; SEO pack; problem-card PNG generator.

⸻

Minimal slides.md Example (3 sections)

# What is Diffusion?
- Random motion of particles
- Net movement from high → low concentration

# Fick's Laws (Intuition)
- Flux proportional to gradient
- Area and thickness matter

# Real-World Example
- Oxygen across alveolar membrane
- Implications for exercise physiology

Minimal templates/slide.html Skeleton

<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    :root {
      --bg: {{ bg_color }};
      --text: {{ text_color }};
      --brand: {{ brand_color }};
      --font: {{ font_family }};
      --margin: {{ margin_px }}px;
      --hsize: {{ heading_size }}px;
      --bsize: {{ body_size }}px;
    }
    html, body { margin:0; padding:0; width:1920px; height:1080px; background:var(--bg); color:var(--text); font-family:var(--font); }
    .wrap { box-sizing:border-box; padding: var(--margin); display:flex; flex-direction:column; gap:32px; height:100%; }
    h1 { font-size: var(--hsize); line-height:1.1; margin:0; color: var(--text); }
    ul { font-size: var(--bsize); line-height:1.35; margin:0; padding-left: 1.2em; }
    li + li { margin-top: 10px; }
    .accent { height:8px; width:240px; background:var(--brand); border-radius:4px; }
    .footer { margin-top:auto; opacity:.7; font-size:28px; display:flex; justify-content:space-between; align-items:center; }
    .logo { position:relative; right:0; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="accent"></div>
    <h1>{{ title }}</h1>
    <div class="content">{{ content|safe }}</div>
    <div class="footer">
      <div>{{ author or "" }}</div>
      {% if logo_path %}
      <img class="logo" src="{{ logo_path }}" style="width:{{ logo_width }}px; opacity:{{ logo_opacity }};">
      {% endif %}
    </div>
  </div>
</body>
</html>


⸻

Acceptance Criteria (“Definition of Done”) for v1
	•	avm installs with pinned deps; ffmpeg -version check passes; playwright install chromium documented.
	•	avm transcribe -p <slug> produces build/captions.srt and build/captions_words.json.
	•	avm slides -p <slug> produces 1920×1080 PNGs for each Markdown section using styles.yml.
	•	avm render -p <slug> outputs build/final.mp4 (H.264, 1080p, 30fps) with:
- [ ] Intro/outro (if provided) concatenated.
- [ ] Watermark in configured corner.
- [ ] Ken-Burns motion present on each slide.
- [ ] Voice normalized to −14 LUFS ±0.5; no clipping (−1 dBTP).
- [ ] Music bed ducked under voice (audibly effective).
- [ ] Captions burned or soft attached per config.
	•	avm thumb -p <slug> outputs build/thumb.png at 1280×720+.
	•	avm all -p <slug> performs full pipeline idempotently; rerun without --force skips unchanged steps.
	•	Unit tests pass; golden tests confirm timelines and slide rendering stability (SSIM ≥ 0.98).
	•	Structured logs emitted; build/manifest.json lists artifacts with durations.
	•	README documents setup, CLI usage, config, and troubleshooting.

⸻
