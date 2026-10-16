# Synthetic Mind: raise a mind from nothing

**Zen** is a synth: a neural network that starts as random numbers and knows no words at all. You
watch it learn language and live with what it learns, in a 3D valley it shares with seven other
minds. You can visit, talk, give it things and keep it company.

- **It studies.** The Academy trains Zen's brain from scratch on your GPU. It learns from web
  text streamed from FineWeb, lessons from an Oracle, drills on the facts of its world, and its
  own life. Zen goes from static, to babble, to first words, phrases and sentences.
- **It lives.** Zen has six needs, and its own words steer its body. When its brain can write
  "I go fishing at the dock.", it goes fishing. Until then its needs choose for it, and it studies
  those choices.
- **It has neighbours.** Seven villagers are minds too, each with its own small language model
  (a llama.cpp server on your CPU). Each has needs, an inner monologue, intentions, a diary and
  friendships. They work, eat, rest, make art and talk with each other and with Zen.
- **They create.** Paintings, music recordings you can play, sculptures in stone, wood or clay,
  buildings, and poems. Everything they make stays in the valley and in its Gallery.

## Start (Windows with an NVIDIA GPU)

1. Install Python 3.10 or newer from python.org (tick *Add to PATH*).
2. Double-click **`start.bat`**. The first run creates `.venv`, installs PyTorch with CUDA and the
   other requirements, and opens <http://127.0.0.1:8765>.
3. The first time, the voices are downloaded into `oracle/`: llama.cpp (tens of MB), the Oracle's
   model (Gemma 2 2B, 1.7 GB) and the villagers' model (Qwen 2.5 1.5B, 1.1 GB, shared by all seven).
   The Oracle tab shows the progress. [Ollama](https://ollama.com) is optional; choose it on the
   Oracle tab if you'd rather use your own models.

**Linux / macOS:** `./start.sh`. **By hand:** install PyTorch for your machine, then
`pip install -r requirements.txt` and `python run.py`.

Each synth is saved continuously in `minds/<name>/`. Ctrl+C saves everything and stops. Minds made
with earlier versions (Ada) still work: `python run.py --name Ada`.

```
python run.py                              Zen (created on the first run, resumed after)
python run.py --name Kai                   another synth, starting from nothing
python run.py --preset medium              a bigger brain for a new synth (12 GB+ GPU)
python run.py --schedule day_night         study only while it sleeps at night
python run.py --oracle ollama              the Oracle and the villagers speak through Ollama
python run.py --no-fineweb --no-oracle     offline
```

## Playing

**🌍 Valley** is the 3D valley, with an overlay you can hide (◱):

- the strip on the left lists every mind with its mood and what it is doing; click one to follow it
  and see its card;
- the minimap is at the top right (⤢ enlarges it);
- the live feed shows conversations, thoughts and new works;
- the talk bar sits at the bottom.

| mode | controls |
|---|---|
| 👀 **Watch** | drag to orbit, wheel to zoom, click a mind or a work |
| 🧍 **Visit** | click to capture the mouse; **WASD** walk, **Shift** run, **Space** hop, **V** first/third person, **E** use or talk to what you face, **G** give Zen what you carry, **H** hug, **Q** drop, **T** talk, **1–6** inventory, **Esc** free the mouse |
| 🧺 **Add things** | place food, materials, tools, books with your own words, signs and animals on the map |

What you say goes to Zen, or to the villager you are talking to; they answer with their own voices.
Zen's replies are its own (babble at first), and the Oracle suggests the reply it should have given,
which it then studies.

**🧑‍🤝‍🧑 Minds** has Zen's journey (first word, first sentence, first conversation, first song…) and
a card for every mind: needs, feelings, what it is doing and why, its latest thought, how often it
acts in its own words, friendships, works and diary.

**🖼️ Gallery** holds everything made in the valley:

- paintings, painted from each work's recipe;
- songs, played in the browser;
- sculptures, buildings and poems.

**🎓 Academy**, **🧠 Concepts**, **🔮 Oracle**, **⚙️ Settings** and **🩺 Health** show the training,
what Zen understands, the voices, every setting and the program's own performance. **Download
report** on the Health tab saves a diagnostics file you can share.

## The valley

The valley is 128 × 96 tiles:

- **The mountains** have an old mine (ore and crystals) and a snowy peak.
- **A river** runs down to a lake with a beach and Finn's dock.
- **The village** has a plaza with a well and a fire pit, the bakery, the library, the school, the
  workshop and forge, the market, the music hall, the painting studio, a park with swings and a
  frog pond, and the Oracle's shrine on its hill.
- **Zen's cottage** has a farm with fields, a barn and animal pens, next to an apple orchard.
- **To the east** is a meadow with beehives and the observatory; **to the south-west**, a deep forest.

Days, nights, seasons and weather pass.

Things to do:

- farm (wheat, carrots, pumpkins), bake, cook, fish, mine, milk the cow, collect eggs and honey;
- craft tools: axe, fishing rod, pickaxe, chisel, hammer, kite, lantern;
- trade at the market (coins circulate: sellers are paid, work earns wages);
- complete the villagers' quests;
- paint, compose and record, sculpt, build (benches, birdhouses, lamp posts, fountains, flower
  beds), write, read, swim, fly a kite, build a snowman, stargaze.

**The villagers:** Mira (baker), Theo (librarian), Rowan (smith), Juniper (merchant), Finn (fisher),
Sage (teacher) and Pip (a child who loves to play).

**How conversations work.** Whoever has something to say starts the conversation and walks up
to the other mind. Both stop. The speaker composes its line (a "…" bubble shows it thinking) while
the listener waits. Then the listener composes its reply while the first one waits, for a few turns.
Every line comes from that speaker's own mind. When Zen is nearby, it overhears and studies the
conversation.

## How it is built

Three processes, so nothing can freeze anything else:

```
   FineWeb ──┐                                ┌── llama.cpp servers on the CPU: the Oracle + one per villager
             ▼                                ▼
 ┌────────────────────────┐ brain  ┌──────────────────────┐ events ┌─────────────────────────────┐
 │ ACADEMY (GPU)          │───────▶│ HUB                  │◀──────▶│ WORLD (CPU)                 │
 │ trains Zen's brain;    │ files  │ web page, schedule,  │        │ the valley, Zen's body and  │
 │ tests concepts;        │◀───────┤ voices, supervision  │        │ brain, the villagers' minds,│
 │ publishes new brains   │journal └─────────▲────────────┘        │ conversations, art, journal │
 └────────────────────────┘ lessons          │ WebSocket           └─────────────────────────────┘
                                       your browser (three.js)
```

- **Zen's brain:** a modern small transformer (RMSNorm, rotary positions, QK-norm, SwiGLU, tied
  embeddings, logit soft-capping) trained with Muon and AdamW in bf16.
  - **Vocabulary:** 32,768 tokens, trained on FineWeb (`tools/train_tokenizer.py`). It writes any
    text, fits FineWeb a little better than GPT-2's 50,257, and leaves more of a small brain for
    thinking.
  - **Loss:** the vocabulary loss and its gradient are computed in one pass.
  - **Batch:** sized to the GPU's free memory, measured rather than found by running out (on
    Windows that would quietly spill into RAM).
  - **Growth:** the brain grows new layers when learning plateaus.
- **The GPU is for training.** Zen's brain lives on the CPU, sharing the physical cores with the
  Oracle. The villagers' servers share one copy of their model. A priority gate lets a few of them
  generate at once: conversation turns first, then decisions, naming their works, and thoughts.

```
run.py               starts the Hub, which starts the Academy and the World
ada/academy.py       training, evaluation, publishing        ada/model.py    the brain (and the fused loss)
ada/life.py          the World process: Zen's day            ada/community.py the villagers' minds, conversations
ada/world/sim.py     the valley                              ada/world/agent.py  words → plans → actions (for every mind)
ada/world/art.py     paintings, melodies, sculptures         ada/journey.py  Zen's milestones
ada/hub.py           processes, schedule, voices, browser    ada/villagers.py  the villagers' voices and prompts
ada/localllm.py      llama.cpp servers                       ada/oracle.py   the Oracle (built-in or Ollama)
ada/tokenizer.py     fineweb32k / gpt2 / bytes               ada/fineweb.py  FineWeb streaming
web/                 the page: world3d.js (three.js), minds.js, art.js, app.js
tests/               python -m pytest tests
```
