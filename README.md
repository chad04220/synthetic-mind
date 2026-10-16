# Synthetic Mind: a mind that makes itself

**Zen** is a synth: a neural network that starts as random numbers, knowing no words and no way to
move. It lives alone in an **endless world**: forests, meadows, rivers and lakes, deserts and
snowfields, mountains, caves and old ruins, with weather, seasons, days and nights. Everything Zen
does, its own brain decides: every step, every word, every brushstroke and every note. Beside it
floats the **Sprite of All Knowing**, which answers whatever Zen asks, and looks at (and listens to)
what Zen makes.

- **Zen learns language** from scratch on your GPU: web text streamed from FineWeb, its own life,
  the Sprite's answers, and drills on the facts of its world. It goes from static to babble, to
  first words, phrases and sentences.
- **Zen learns to live by living.** Its brain chooses each action from 14 motor words (*forward,
  back, left, right, wait, take, drop, eat, drink, use, sleep, look, speak, ask*). Nothing else moves
  it: there is no planner and no script. The world answers with what happens: hunger eased by
  berries, thirst by the stream, cold by the fire, wonder at a new place, pain at a wall. From those
  consequences its brain learns what to do, and also learns to predict what its deeds lead to.
- **Zen asks.** When its brain chooses *ask*, its brain also writes the question, in whatever words
  it has. The Sprite answers, in plain words, and Zen waits for the answer (its thoughts go on).
- **Zen makes art from nothing.** At the easel, the piano or with a lump of clay, its brain chooses
  every mark: where the brush goes, when it presses, which colour; every note and its length;
  every bit of clay added or cut. No templates, no brushes that paint for it. The Sprite then
  *sees* the painting or the sculpture and *hears* the song (it is a vision-and-audio model), says
  what it sees, and scores it. That verdict is what Zen learns from, and so can your ♥.

## Start (Windows with an NVIDIA GPU)

1. Install Python 3.10 or newer from python.org (tick *Add to PATH*).
2. Double-click **`start.bat`**. The first run:
   - creates `.venv`;
   - installs PyTorch with CUDA and the other requirements;
   - opens <http://127.0.0.1:8765>.
3. The first time, the Sprite's mind is downloaded into `oracle/`: llama.cpp (tens of MB) and the
   model, Qwen 2.5 Omni 3B with its eyes and ears (3.6 GB). The **Sprite** tab shows the progress.
   [Ollama](https://ollama.com) is optional (the Sprite then answers but can't see or hear).

**Linux / macOS:** `./start.sh`. **By hand:** install PyTorch for your machine, then
`pip install -r requirements.txt` and `python run.py`.

Each synth is saved continuously in `minds/<name>/`. Ctrl+C saves everything and stops. A synth
from an earlier version keeps its brain, its journey and its keepsakes, and starts its life over in
the endless world.

```
python run.py                              Zen (created on the first run, resumed after)
python run.py --name Kai --seed 7          another synth, in another world, starting from nothing
python run.py --preset medium              a bigger brain for a new synth (12 GB+ GPU)
python run.py --schedule day_night         study only while it sleeps at night
python run.py --oracle ollama              the Sprite's mind runs in Ollama
python run.py --no-fineweb --no-oracle     offline (Zen's questions go unanswered)
```

## What you see

- **🏡 Home:** the world in 3D around Zen, streamed as it roams, with an overlay: the time and
  weather, where Zen is, a local map, Zen's needs and feelings, what its brain just chose, and a live
  feed. While Zen paints, plays or sculpts, the piece grows in a panel as each mark is made.
  - **Watch:** drag to orbit, wheel to zoom, click anything.
  - **Visit:** walk in with WASD and the mouse; talk to Zen (it hears you, and you are part of its
    stream), give it what you carry, put things down for it to find.
- **🌱 Zen:** its journey (first step, first meal, first question, first word, first painting…), its
  body, its art, and its motor mind: how often it chooses each action, how sure it is, how its
  rewards are going, and the stream of what it just did.
- **💭 Thoughts** and **🗣️ Conversations:** everything it thought, did and said, whole and searchable
  (with you, with the Sprite, and the Sprite's verdicts on its work).
- **🗺️ Atlas:** the map of everywhere Zen has been, the places it found, and its trail.
- **🖼️ Keepsakes:** every painting, song, sculpture and piece of writing, with what the Sprite saw and
  said. Replay any piece mark by mark as a time-lapse. ♥ a piece to tell Zen you love it: every mark
  that made it counts for more in its learning.
- **🎓 Academy**, **🧠 Concepts**, **✨ Sprite**, **⚙️ Settings** and **🩺 Health:** the training
  (including how much it is learning from its own life), what Zen understands, the Sprite (ask it
  anything about Zen), every setting, and the program's own performance (**Download report**).

## How Zen's mind works

Zen lives one continuous stream, the same one its brain reads and learns from:

```
<|world|> Meadow, morning, mild. Ahead: a stream. I see a berry bush 2 ahead. I am thirsty.
<|act|> forward
<|world|> I step forward. I wade into the water.
<|thought|> (whatever its brain thinks)
<|act|> drink
<|world|> I drink the cool water. I am less thirsty.
<|act|> ask
<|mind|> (the question its brain writes)
<|oracle|> (the Sprite's answer)
```

- **Choosing.** At each beat its brain reads the stream and the next word after `<|act|>` is sampled
  from its own probabilities over the motor words (at the easel: over the brush's words; at the
  piano: notes; with clay: the sculptor's words). The cache of what it has read is kept between
  beats, so a choice takes tens of milliseconds on the CPU.
- **Learning.** The World scores each action (needs relieved or worsened, pain, novelty, answers
  received; for art, the Sprite's verdict). The Academy trains on windows of the stream with:
  - the ordinary language-model loss, so Zen learns what follows what it does (its understanding);
  - a policy-gradient loss on its own choices, weighted by how each turned out compared with what it
    usually gets, with a small bonus for staying curious.
  Together with FineWeb and the Sprite's words, the same brain learns to speak, to understand and
  to act.

## The world

Endless and generated from a seed, in chunks of 32×32 tiles as Zen (or you) goes:

- **Land:** meadow, grassland, forest, pine forest, jungle, swamp, savanna, desert, tundra, snow,
  mountains and rock; lakes, rivers and the sea; beaches.
- **Places:** ruins with chests and readable books, abandoned cabins, caves, standing stones,
  springs, cairns to climb and look far from, beehives, nests and old wells, each with a name.
- **Life:** deer, rabbits, foxes, birds, fish, frogs and owls at night, fireflies in summer, goats and
  lizards, and the rare bear. Berries, apples, mushrooms (some of them poisonous), honey, eggs.
- **Physics:** day and night, seasons, rain, storms, snow, fog and wind; temperature by land, height
  and hour; shelter and fire for warmth; darkness without light; getting wet and drying. Zen gets
  hungry, thirsty, tired and cold; it falls asleep when exhausted and faints (waking at home) when
  its health runs out.
- **Home:** a cabin at the start with a bed, a fireplace with wood and a flint, a bookshelf, a chest,
  an easel with paper, a piano, a desk, a rain barrel, and a pond and a beehive nearby.

## How it is built

```
   FineWeb ──┐                                ┌── the Sprite: llama.cpp on the CPU (Qwen 2.5 Omni 3B: sees and hears)
             ▼                                ▼
 ┌────────────────────────┐ brain  ┌──────────────────────┐ events ┌─────────────────────────────┐
 │ ACADEMY (GPU)          │───────▶│ HUB                  │◀──────▶│ WORLD (CPU)                 │
 │ trains Zen's brain on  │ files  │ web page, schedule,  │        │ the endless world; Zen's    │
 │ text and on its own    │◀───────┤ the Sprite's words,  │        │ brain choosing every deed,  │
 │ experience; publishes  │ exp.   │ supervision          │        │ word and mark               │
 └────────────────────────┘journal └─────────▲────────────┘        └─────────────────────────────┘
                                              │ WebSocket
                                       your browser (three.js)
```

- **Zen's brain:** a small modern transformer (RMSNorm, rotary positions, QK-norm, SwiGLU, tied
  embeddings, logit soft-capping) trained with Muon and AdamW in bf16; a 32,768-token vocabulary
  trained on FineWeb; the batch sized to the GPU; new layers grown when learning plateaus.
- **The GPU is for training.** Zen's brain lives on the CPU (half the physical cores, at most 4); the
  Sprite gets the rest and runs only when asked. The 3D view draws at most 60 frames a second.

```
run.py               starts the Hub, which starts the Academy and the World
ada/academy.py       training (text + experience), evaluation, publishing    ada/model.py   the brain
ada/life.py          the World process: Zen's stream, choices, words, art    ada/motor.py   choosing and experience
ada/world/terrain.py the endless land                 ada/world/sim.py   things, beings, physics, senses, rewards
ada/world/studio.py  the easel, piano and clay        ada/world/render.py  pictures and sounds for the Sprite
ada/sprite.py        what the Sprite is asked         ada/hub.py         processes, schedule, the Sprite's model
ada/localllm.py      llama.cpp servers                ada/oracle.py      reaching the model (built-in or Ollama)
ada/archive.py       thoughts and conversations kept whole                 ada/journey.py Zen's milestones
web/                 the page (three.js)              docs/DESIGN-v4.md  the design
tests/               python -m pytest tests
```
