# Ada: a mind that learns language, then lives with it

Ada is a neural network that starts as random weights. A two-part system raises her:

- **The Academy** teaches her language and concepts. It streams web text from **FineWeb**,
  studies lessons written by an **Oracle** (any model you run locally in **Ollama**), drills
  the facts of her world, and studies her own journal of everything she has lived through.
- **The World** is where she lives with what she has learned: a valley with a cottage, a
  garden, an orchard, a meadow, a forest, a lake, a village (bakery, library, workshop and the
  Oracle's shrine) and an observatory. There are days, nights, seasons and weather, three
  villagers, animals, needs to look after, and things to grow, cook, bake, craft and read.

The two halves never compete. By default Ada lives by day, and at night she sleeps while the
Academy studies with the whole GPU. Each morning she wakes up with the brain she earned
overnight.

## What makes it different

**Her words steer her body.** Whenever she is free to choose, her own brain writes an intention
("I eat the apple.", "I ask the Oracle why the sky is blue."). If the World can make sense of
it, she does it. While her words can't yet, her needs choose for her, *with a reason*, and
those choices go into her journal next to what she sensed and how it turned out. The Academy
studies the journal, so her brain gradually learns to make those choices itself. The header
shows the share of her actions that come from her own words: the clearest sign that her
language is grounded in her world.

**Understanding is measured, not guessed.** The world's ontology (what each thing is, its
color, what it's made of, what it's for, where it's found) becomes a concept graph. The
Academy drills those facts, and tests them separately as four-way choices *worded unlike any
drill* ("To look for a mushroom, go to the ___": forest / library / lake / bakery). A rising
score means she grasped the idea rather than memorised a sentence. The Oracle adds new facts
with every lesson, and its background lessons go first to what she gets wrong.

**The page stays responsive.** Three separate processes: the Academy (training), the World
(living), and the Hub (the web page and the Oracle). The Hub never touches PyTorch, so no
amount of training can freeze the dashboard, and if the Academy or the World ever crashes, the
Hub restarts it.

```
           FineWeb ──┐                          ┌── Ollama (the Oracle)
                     ▼                          ▼
   ┌──────────────────────────┐        ┌─────────────────────┐        ┌──────────────────────────┐
   │ ACADEMY  (process 1)     │ brain  │ HUB  (process 3)    │ events │ WORLD  (process 2)       │
   │ trains on web text,      │───────▶│ web page, schedule, │◀──────▶│ the valley, Ada's body,  │
   │ lessons, journal,        │ files  │ Oracle, supervision │        │ intentions, thoughts,    │
   │ concept drills; tests    │◀───────┤ (never loads torch) │        │ talk; writes her journal │
   │ concepts; publishes      │journal └─────────▲───────────┘        └──────────────────────────┘
   └──────────────────────────┘ lessons          │ WebSocket
                                          your browser
```

## Start

**Windows with an NVIDIA GPU**

1. Install Python 3.10 or newer from python.org (tick *Add to PATH*).
2. Install [Ollama](https://ollama.com) and pull a chat model, for example `ollama pull llama3.2`.
3. Double-click **`start.bat`**. The first run creates `.venv`, installs PyTorch with CUDA and
   the other requirements, prints which GPU it found, and opens <http://127.0.0.1:8765>.

**Linux / macOS:** `./start.sh`. **By hand:**
`pip install torch --index-url https://download.pytorch.org/whl/cu126` (or the CPU build), then
`pip install -r requirements.txt` and `python run.py`.

Ada is saved in `minds/Ada/` continuously; Ctrl+C saves everything and stops. Start again with
the same name to continue where she left off.

```
python run.py --name Bo --preset tiny      another mind, a small brain
python run.py --preset medium              a bigger brain (12 GB+ GPU)
python run.py --schedule together          live and study at the same time
python run.py --world-device cpu           run her daily life on the CPU, leaving the GPU to study
python run.py --no-fineweb --no-oracle     offline
```

| preset | brain | parameters (GPT-2 tokens) | for |
|---|---|---|---|
| tiny | 256 wide × 4 layers | ~16M | CPU (uses byte tokens: ~3M) |
| small | 512 × 8 | ~51M | **8 GB GPUs such as the RTX 3070 (default)** |
| medium | 768 × 12 | ~124M | 12–16 GB |
| large | 1024 × 16 | ~250M | 24 GB |

## The dashboard

- **🌍 World:** the valley, following Ada (or you, or the whole map). Beside it: her six
  needs (food, water, rest, warmth, company, fun), what she is doing right now, whether that
  came from *her own words*, *her needs* or *your idea*, and what she tried to say when her
  words didn't work yet. Below it are three modes:
  - **👀 Watch:** click anyone or anything to learn about it.
  - **🧺 Add things:** put apples, books (with your own words), signs, balls, animals… anywhere.
  - **🧍 Be there:** join as your own avatar. Walk (WASD), carry things, give them to her (G),
    hug her (H). She senses you, takes what you hold, and is rewarded for your company.

  The side panel has four tabs:
  - **💬 Talk:** chat with her. The Oracle suggests the reply she should have given, and she
    studies it. Or *suggest* something for her to do ("bake bread"); if she understands, she
    does it.
  - **💭 Thoughts:** her free-running inner monologue, each word shaded by her confidence.
  - **📔 Diary:** every intention and how it turned out.
  - **🏘️ Village:** what the villagers say to her, what she read, and the Oracle's answers to
    the questions she asks at the shrine.
- **🎓 Academy:** her developmental stage (Static → Babbling → First words → Phrases →
  Sentences → Conversational → Articulate), loss and bits-per-byte, concept score against
  chance, study speed, the Oracle's assessments of her thoughts, what she is studying and
  from where, a probe that shows what she predicts next, and buttons to publish, test, grow
  or save.
- **🧠 Concepts:** how well she understands each kind of fact, every fact with what she
  chose, and **Teach her a topic**: the Oracle writes a lesson, questions and new facts, and
  your topics go first.
- **🔮 Oracle:** pick the Ollama model, ask it anything ("Let Ada study this" turns the answer
  into a lesson), and read every lesson it has written.
- **⚙️ Settings:** the schedule (day & night, together, study only, live only), day and night
  lengths, GPU intensity, what she studies, how she thinks and talks, and the Oracle.

## How she learns quickly

- A modern small transformer: RMSNorm, rotary positions, QK-norm, SwiGLU, tied embeddings,
  logit soft-capping, zero-initialised residual branches. Blocks can be added later without
  disturbing what she knows ("grow").
- The **Muon** optimizer for the transformer's matrices (it learns faster per token than
  AdamW), bf16, TF32, fused AdamW, and a chunked loss that never holds the full vocabulary of
  logits in memory.
- **FineWeb** streamed as random 1000-document row groups from across Common Crawl, with flat
  memory and a held-out set for honest measurement.
- **Curriculum from the Oracle**, pitched at her stage: toddler sentences while she babbles,
  stories and explanations as she grows, targeted at the concepts her tests say she gets wrong.
- **Her own life as data**: what she sensed, chose, did and heard, weighted by how it turned out.
- **Never broken by a bad step:** unstable steps are skipped, broken weights are never saved
  or published, and the previous good save is always kept.

## Files

```
run.py               starts the Hub, which starts the Academy and the World
ada/hub.py           the Hub: processes, schedule, Oracle jobs, browser messages (no torch)
ada/web.py           the web server inside the Hub
ada/academy.py       the Academy: training, evaluation, publishing
ada/life.py          the World process: Ada's day, her brain, talk, journal
ada/world/sim.py     the valley: places, things, weather, seasons, villagers, needs
ada/world/agent.py   words to deeds: parsing intentions, needs, plans, actions
ada/ontology.py      everything in the world and what is true about it
ada/concepts.py      the concept graph: drills and tests
ada/oracle.py        the Oracle (Ollama): lessons, answers, villagers, books, assessments
ada/model.py         the brain; ada/optim.py Muon; ada/fineweb.py streaming; ada/tokenizer.py
web/                 the dashboard (no external dependencies)
tests/               python -m pytest tests
```

Earlier versions (one process doing everything) are in the v0.x releases.
