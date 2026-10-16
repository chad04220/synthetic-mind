# Synthetic Mind: a living world, and a mind inside it that teaches itself

**Zen** lives in a world of blocks you can change completely, like Minecraft.
- **The world:** endless land with forests, plains, deserts, jungles, snowy mountains, oceans and
  rivers. There are caves full of ore, ruins with chests, and a small cabin where Zen starts.
- **What happens in it:** water and lava flow, sand falls, fire spreads, and crops grow.
  - Levers, wire, lamps, doors, pistons and TNT work.
  - Furnaces smelt, and chests hold things.
  - Creatures wander; at night, hollows come out of the dark.
- **Zen's mind:** a small pretrained language model running on your GPU with llama.cpp. It sees
  its surroundings, decides, acts and talks, fast.

You can talk to Zen in the chat, or walk into its world yourself to dig, build and hand it things.

Zen can also **improve itself**:
- It knows its mind is a model that can learn.
- It can **reflect**: judge its own recent decisions, write down what it should have done instead,
  and keep lessons.
- It can **practise**: lie down while its model is trained on the decisions it judged good and
  the better choices it wrote for its failures. It wakes up running what it learned.
- Every practice round starts from the last one, so better decisions become better training
  material for the next round.
- Your 👍/👎 and corrections count too.
- A practice round that makes it worse in the world is undone automatically, and Zen is told why.

## Start

1. Install Python 3.10 or newer from python.org (on Windows tick *Add to PATH*).
2. **Windows:** double-click **`start.bat`**. **Linux / macOS:** `./start.sh`. **By hand:**
   `pip install -r requirements.txt`, then `python run.py`.
3. <http://127.0.0.1:8765> opens. The first time, Zen's model is downloaded into `oracle/`:
   - **llama.cpp:** the CUDA build on Windows with an NVIDIA card, the Vulkan build for other GPUs,
     Metal on Apple silicon, or the CPU build as a fallback.
   - **The model:** Qwen 2.5 1.5B Instruct by default (1.1 GB).
   - The Settings tab shows the progress, and lets you choose another model:
     - Llama 3.2 1B or 3B;
     - Gemma 3 1B;
     - Qwen 2.5 0.5B, 3B or 7B.

Everything is saved continuously in `minds/<name>/`: the world (`region/`), Zen's memory
(`mind.json`), every decision it made (`decisions.jsonl`) and its practice adapters (`adapters/`).
Ctrl+C saves and stops.

```
python run.py                          Zen and its world (created on the first run, resumed after)
python run.py --name Kai --seed 42     another inhabitant, in another world
python run.py --model llama-3.2-3b     a different model (also in Settings)
python run.py --cpu                    its model on the CPU (slow: seconds per decision)
python run.py --peaceful               no hostile creatures
```

## How Zen decides

A decision happens when one of these occurs:
- an action ends;
- someone speaks to it;
- something important happens (it's hurt, night falls, someone gives it something);
- it has been idle for a while.

Each time, Zen's model reads one short observation, written in plain words from what its body
perceives. The observation is built in this order:
1. Its notes, lessons, named places and goal.
2. Its learning: how often it has practised, and how many of its actions work.
3. What it perceives: the time and weather, its health, food and inventory, and what it's looking
   at. Also nearby blocks of interest with counts and directions, creatures and people.
4. Recent events and the conversation.
5. Its last few actions and what came of them.
6. Why it is thinking now.

The model answers with one decision, and a JSON schema (enforced by llama.cpp's grammar) guarantees
the reply is always valid:

```json
{"thought": "...", "action": {"skill": "craft", "args": {"item": "wooden_pickaxe"}},
 "say": null, "note": null, "goal": "Make a wooden pickaxe"}
```

The action starts the moment it has streamed in, before the rest of the reply. The fixed
instructions stay in llama.cpp's prompt cache, so only the observation is new each time. On a GPU
with the default model a decision takes a few hundred milliseconds.

Its body carries out **skills**, all of them fast, deterministic and done the way a competent player
would:

| Kind | Skills |
|---|---|
| Moving and looking | `go_to` (A* path-finding with jumping, swimming and climbing), `look_at`, `follow` |
| Gathering | `mine`, `mine_nearest` |
| Building | `place`, `build` (named blueprints or its own list of blocks) |
| Making | `craft`, `smelt` |
| Containers and blocks | `use`, `put`, `take` |
| Food and farming | `eat`, `plant`, `till`, `harvest` |
| Creatures and people | `attack`, `give` |
| Inventory | `equip`, `drop` |
| Itself | `sleep`, `say`, `wait`, `stop` |

Three more skills belong to its mind:
- `reflect`: judge its recent decisions and keep lessons;
- `practice`: train its model;
- `name_place`: remember a spot by name, to find it again with `go_to`.

## Practice: how it teaches itself

1. **Everything is recorded.** Each decision is saved with the exact instructions and
   observation Zen saw, its reply and what came of it (`decisions.jsonl`). Every judgement of it
   is saved too (`judgements.jsonl`), whether its own from `reflect` or yours from the page.
2. **Examples are chosen.**
   - **Kept:** decisions that worked and that nobody judged bad. One you 👍'd counts twice.
   - **Replaced:** a decision that went wrong is replaced by the better action Zen wrote for it
     when it reflected.
   - **Left out:** bad decisions with no better action.
   - **Balanced:** no one skill may be more than a third of the examples, and older examples are
     replayed alongside new ones so it keeps what it learned before.
3. **Training.** A LoRA adapter (rank 16 on every attention and MLP projection) is trained on the
   model's original weights (downloaded once from Hugging Face), on the reply tokens only. The
   model server stops while it trains, so the GPU can do the work, and Zen sleeps.
4. **Into use.** The adapter is written as a llama.cpp LoRA GGUF, and the server restarts with it
   (`--lora`).
5. **Checked.** Once Zen has made 30 decisions with the new adapter, their success rate is
   compared with the old one's. If it fell by more than 12 points, Zen goes back to the previous
   adapter, gets a lesson about it, and is told.

Practice needs PyTorch, transformers, safetensors and gguf. The **Install training tools** button
on the page installs them; with an NVIDIA GPU it installs the CUDA build of PyTorch.
- **Speed:** a 1.5B model practises in a few minutes on an 8 GB GPU.
- **On the CPU:** practice works, but slowly.
- **Starting it:** Zen chooses when to practise. You can also press **Start practice**, or let it
  practise automatically when it sleeps in a bed. Any adapter, or none, can be put back on the
  Settings tab.

## What you see

- **🏡 Home:** the world in 3D, with sky, sun and moon, clouds, rain and snow, and block light. Zen
  has a name tag and speech bubble, and a glow that pulses while it thinks. Beside it:
  - its mind card: thought, goal, current skill, health and food, and the last decision with
    👍/👎;
  - the chat, its inventory, live events and a minimap.

  The view has two modes:
  - **Watch:** orbit around Zen.
  - **Visit:** walk in yourself.
    - WASD, Space to jump, Shift to sneak, Ctrl to sprint, the mouse to look.
    - Hold the left button to dig, right-click to place or use.
    - 1–9 and the wheel for the hotbar, E for the inventory, Q to drop, G to give to Zen, V for
      third person.
- **🧠 Mind:** every decision, with the following:
  - its latency, what it saw, thought and did, and what came of it;
  - 👍/👎 and *show it what it should have done*;
  - a latency chart and its practice;
  - its notes, lessons, places and goals.
- **🗣️ Conversations / 💭 Thoughts:** everything it said and heard, and every thought and reflection,
  in full, searchable.
- **🗺️ Map:** the explored land from above, with Zen, you and its named places.
- **⚙️ Settings:**
  - the model, and whether it runs on the GPU;
  - how adventurous its decisions are and how often it thinks;
  - radio chat (whether it hears the chat box from anywhere);
  - practice, day length, hostiles, and render distance.
- **🩺 Health:** what each process is doing, decision latency, the GPU, warnings, and a downloadable
  diagnostics report.

## Layout

```
run.py                the launcher
ada/hub.py            the Hub: web server, its model server, practice (coach.py), archives, health
ada/web.py            HTTP + WebSocket API
ada/localllm.py       llama.cpp: picking the build (CUDA / Vulkan / Metal / CPU), models, adapters
ada/coach.py          practice rounds: stop the model, train, swap in the adapter
ada/life.py           the World process: the world at 20 Hz, its body and skills, its mind
ada/agent/mind.py     observation, decisions, memory, reflect / practice / name_place, rollback
ada/agent/practice.py examples from judged decisions, LoRA training, GGUF export
ada/agent/skills.py   the 24 skills, as state machines
ada/vox/              blocks, items, recipes, terrain, simulation, body physics, A*, descriptions
web/                  the page (three.js, chunk meshing in a worker)
docs/DESIGN-v5.md     the design
```

Tests: `python -m pytest -q tests`.
