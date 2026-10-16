# Synthetic Mind: raise a mind from nothing

**Zen** is a synth: a neural network that starts as random numbers and knows no words at all. It
lives in a little house in a quiet hollow with **Wren**, who raises it. You watch Zen learn
language and live with what it learns. You can visit, talk with both of them, and bring them
things.

- **Zen studies.** The Academy trains Zen's brain from scratch on your GPU. Its sources:
  - web text streamed from FineWeb;
  - lessons Wren writes from the days they spent together;
  - drills on the facts of its world;
  - its own life.

  Zen goes from static, to babble, to first words, phrases and sentences.
- **Wren raises it.** Wren is one language model (llama.cpp on your CPU, or Ollama). It already
  knows language, so it doesn't train. Each moment the World lists what Wren could sensibly do, and
  the model chooses one and says what Wren says out loud. Wren:
  - cooks, gardens, keeps the fire going and looks after Zen;
  - names things for Zen and talks with it, one turn at a time;
  - answers Zen's questions and tells it a bedtime story about the day, every night.
- **Zen grows up in Wren's words.** Everything Wren says near Zen, Zen hears. It studies those
  words next to what it saw at that moment, and so it studies Wren's deeds too, in words ("Wren puts
  the pot on the stove."). When Zen's brain can write "I feed the cat.", Zen feeds the cat.
- **A small world that is deep.**
  - Rooms warm by the fire and cool at night.
  - Soup cooks, the kettle boils, bread bakes, and anything left too long burns.
  - Food goes stale and rots, more slowly in the cool pantry.
  - Rain soaks what is outside, and wet logs won't burn.
  - Plants need water and die in a frost.
  - Hens lay eggs in the morning, bees make honey while flowers bloom, and Moss the cat finds the
    warmest spot.

## Start (Windows with an NVIDIA GPU)

1. Install Python 3.10 or newer from python.org (tick *Add to PATH*).
2. Double-click **`start.bat`**. The first run:
   - creates `.venv`;
   - installs PyTorch with CUDA and the other requirements;
   - opens <http://127.0.0.1:8765>.
3. The first time, Wren's mind is downloaded into `oracle/`: llama.cpp (tens of MB) and the model
   (Gemma 2 2B, 1.7 GB). The **Wren** tab shows the progress. [Ollama](https://ollama.com) is
   optional; choose it on the Wren tab if you'd rather use your own models.

**Linux / macOS:** `./start.sh`. **By hand:** install PyTorch for your machine, then
`pip install -r requirements.txt` and `python run.py`.

Each synth is saved continuously in `minds/<name>/`. Ctrl+C saves everything and stops. Minds made
with earlier versions keep their brain, their days and their art, and move into the new house.

```
python run.py                              Zen (created on the first run, resumed after)
python run.py --name Kai                   another synth, starting from nothing
python run.py --preset medium              a bigger brain for a new synth (12 GB+ GPU)
python run.py --schedule day_night         study only while it sleeps at night
python run.py --oracle ollama              Wren's mind runs in Ollama
python run.py --no-fineweb --no-oracle     offline (Wren lives by simple rules)
```

## Playing

**🏡 Home** is the 3D homestead, with an overlay you can hide (◱):

- **Top left:** the time, the weather, the temperature outside and in the house, and what can be
  heard.
- **Left:** Zen and Wren, with their mood and what they are doing. Click one to follow it and see
  its card.
- **Top right:** the minimap. ⤢ enlarges it.
- **Bottom left:** the live feed: what Wren says, Zen's attempts at words, their conversations, and
  what happens (a new egg, the kettle whistling, a rainbow).
- **Bottom:** the talk bar.

| mode | controls |
|---|---|
| 👀 **Watch** | drag to orbit, wheel to zoom, click Zen, Wren or anything to look closer |
| 🧍 **Visit** | click to capture the mouse; **WASD** walk, **Shift** run, **Space** hop, **V** first/third person, **E** use or talk to what you face, **G** give Zen what you carry, **H** hug, **Q** drop, **T** talk, **1–6** inventory, **Esc** free the mouse |
| 🧺 **Add things** | place food, toys, books with your own words, signs and animals |

- **Talking to Zen:** it answers with its own brain (babble at first), and Wren suggests the reply
  Zen should learn to give.
- **Talking to Wren:** Wren tells you how Zen is doing.
- **Suggesting a deed:** type something like "feed the cat" and Zen tries to do it.

### The other tabs

- **🌱 Together:**
  - Zen's journey (first word, first sentence, first conversation, first song…);
  - both minds in full;
  - the words Wren has heard Zen say;
  - how Wren is looking after Zen right now;
  - Wren's diary.
- **💭 Thoughts** has every thought Zen has had, whole and newest first, grouped by day. Shading
  shows how sure its brain was of each word. You can search for a word and page back to the very
  first thought.
- **🗣️ Conversations** has every conversation Zen has had, line by line and in full: its talks with
  Wren, its questions to Wren, and its talks with you. You can show only Wren's or only yours, and
  search them.
- **📖 Stories** collects Wren's bedtime stories, one per night.
- **🖼️ Keepsakes** holds everything either of them made:
  - paintings from the easel: layered landscapes and rooms in one of seven styles (naive, watercolour,
    impressionist, oil, pastel, ink, pointillist), with light, weather and the things they chose to paint;
  - songs with chords, a melody and a form (AABA and the like), which you can play back;
  - clay, wood and stone sculptures you can turn in 3D;
  - poems and birdhouses.

  Each piece shows who made it, how skilled they were, what it is and what Wren said about it.
  **Ask Wren to make something** gives Wren a commission ("a song about the hens at dusk").

**How their art grows.** Every piece is practice, and so are Wren's words about Zen's work, looking
at a piece, and making things side by side.
- **Zen** starts with lopsided naive pictures and one-line hums. As it practises, and as its language
  grows, its pictures gain composition, harmony and light, its songs gain chords and form, and its
  sculptures gain detail and a glaze. What Zen says it will paint ("I paint the moon over the pond")
  is what it paints.
- **Wren** starts as a fair amateur. Its language model plans each piece (title, subject, style,
  colours, mode, tempo, form), and the World turns that plan into the real thing.
- Paintings hang on the walls of the house; sculptures stand on plinths outside.
- The Together tab shows each mind's skill in every medium.
- **🎓 Academy**, **🧠 Concepts**, **🪶 Wren**, **⚙️ Settings** and **🩺 Health** show:
  - the training;
  - what Zen understands;
  - Wren's model and its lessons;
  - every setting;
  - the program's own performance.

  **Download report** on the Health tab saves a diagnostics file you can share.

## How Wren raises Zen

How much Wren does for Zen follows Zen's language (Settings → *How Wren cares for Zen*):

- **Caretaker (Static to First words):**
  - Wren feeds Zen, brings it water, dries it and puts it to bed;
  - Wren takes Zen along to its chores and talks it through everything ("Look, Zen! I put the log
    in the fireplace.");
  - Wren shows Zen things and names them ("Look, Zen. This is an egg. It is smooth and white. Can
    you say egg?").
- **Guide (Phrases, Sentences):** Wren tells Zen what it needs and lets it do it ("You look
  thirsty, Zen. You can drink water at the sink."). Zen's next deed follows Wren's words, so it
  learns how the words and the deed go together.
- **Friend (Conversational and up):** Zen looks after itself; Wren helps when asked.

**Conversations.** Whoever has something to say starts the conversation. If they are apart, that
one walks up to the other, and both stop. Then they take turns:

1. The speaker composes a line (a "…" bubble shows it is thinking) while the other waits.
2. Then the other composes its reply while the first one waits.

They go on for a few turns. Zen's lines come from its own brain. When they are babble, Wren guesses
kindly what Zen meant and says it back properly.

**Big jobs unfold into steps.** "Cook soup" means:

1. take the pot and fill it at the sink;
2. take a carrot from the pantry and put it in the pot;
3. put the pot on the stove;
4. fetch a log from the woodpile and put it in the stove;
5. take the matches and light the stove;
6. wait until it bubbles.

Each step is a sentence Zen can learn ("I fill the pot at the sink."), whether Zen does it or
watches Wren do it.

## The homestead

- **The house:**
  - a living room with the fireplace, the sofa, the bookshelf and the piano;
  - the kitchen with the stove and oven, the sink, the table, the pantry and the cat's bowl;
  - Zen's little bedroom (bed, toy chest, music box);
  - Wren's bedroom with a desk;
  - the washroom with a bathtub and a mirror.
- **Outside:**
  - the porch;
  - the workshop (workbench, quern, woodpile, seeds, tools, easel);
  - the glass greenhouse, warm even in winter;
  - the vegetable garden with its water barrel and scarecrow;
  - the chicken coop;
  - a small orchard with a swing;
  - a pond with ducks, frogs and a jetty;
  - a stream through the woods, a meadow with the beehive, and a lookout on the hill for the stars.

Days, nights, seasons and weather pass:

- rain, storms, fog, wind and snow;
- a rainbow after the rain;
- deer at dusk, an owl and a hedgehog at night.

## How it is built

Three processes, so nothing can freeze anything else:

```
   FineWeb ──┐                                ┌── Wren's mind: one llama.cpp server on the CPU (or Ollama)
             ▼                                ▼
 ┌────────────────────────┐ brain  ┌──────────────────────┐ events ┌─────────────────────────────┐
 │ ACADEMY (GPU)          │───────▶│ HUB                  │◀──────▶│ WORLD (CPU)                 │
 │ trains Zen's brain;    │ files  │ web page, schedule,  │        │ the homestead and its       │
 │ tests concepts;        │◀───────┤ Wren's words and     │        │ physics, Zen's body and     │
 │ publishes new brains   │journal │ lessons, supervision │        │ brain, Wren's body and mind │
 └────────────────────────┘ lessons└─────────▲────────────┘        └─────────────────────────────┘
                                              │ WebSocket
                                       your browser (three.js)
```

- **Zen's brain:** a modern small transformer (RMSNorm, rotary positions, QK-norm, SwiGLU, tied
  embeddings, logit soft-capping) trained with Muon and AdamW in bf16.
  - **Vocabulary:** 32,768 tokens, trained on FineWeb (`tools/train_tokenizer.py`).
  - **Loss:** the vocabulary loss and its gradient are computed in one pass.
  - **Batch:** sized to the GPU's free memory.
  - **Growth:** the brain grows new layers when learning plateaus.
- **The GPU is for training.** Zen's brain thinks on the CPU, sharing the physical cores with
  Wren's model. The 3D view asks the browser for the low-power GPU and draws at most 60 frames a
  second.

```
run.py               starts the Hub, which starts the Academy and the World
ada/academy.py       training, evaluation, publishing        ada/model.py      the brain (and the fused loss)
ada/life.py          the World process: Zen's day            ada/companion.py  Wren's body and mind, conversations
ada/world/sim.py     the homestead and its physics           ada/world/agent.py  words → plans → steps → deeds
ada/world/art.py     art: plans, composers, skill            ada/journey.py    Zen's milestones
ada/hub.py           processes, schedule, Wren's model       ada/wren.py       everything Wren's model is asked
ada/localllm.py      llama.cpp servers                       ada/oracle.py     reaching the model (built-in or Ollama)
ada/tokenizer.py     fineweb32k / gpt2 / bytes               ada/fineweb.py    FineWeb streaming
web/                 the page: world3d.js (three.js), minds.js, art.js, app.js
tests/               python -m pytest tests
```
