# Ada v1.0.1

## Fixed: crashes on Windows that made everything choppy

On Windows, Python writes text files in the old "cp1252" encoding unless told otherwise, and
that encoding can't hold the "�" character that appears in Ada's early babbling. Saving the
World (which happens every minute and at nightfall) crashed with `UnicodeEncodeError: 'charmap'
codec can't encode character '\ufffd'`, the Hub restarted it, and it crashed again. Each restart
reloaded PyTorch and her brain onto the GPU, which made the browser and desktop stutter.

- Every file Ada reads or writes is now explicitly UTF-8, and all three processes run in Python's
  UTF-8 mode as a backstop.
- NumPy is now installed, which silences PyTorch's "Failed to initialize NumPy" warning.

Just unzip over your existing folder (or pull) and run `start.bat`; Ada continues where she was.

---

# Ada v1.0.0: a two-part mind

A redesign from the ground up, built on what Synthetic Mind taught us.

## Why the browser was still sluggish, and how that's fixed

Until now one Python process trained the network, ran the mind *and* served the web page, and
Python runs only one thread at a time, so the page was starved whenever training or inference
was busy. Ada is now **three processes**: the **Academy** (only learns), the **World** (only
lives), and the **Hub** (the web page and the Oracle; it never loads PyTorch). Nothing either
of the others does can freeze the dashboard, and the Hub restarts either of them if it ever
stops.

## The two parts

- **The Academy** studies web text streamed from FineWeb, lessons written by the Oracle, concept
  drills, and Ada's journal of her own life. It tests her understanding with concept questions
  worded unlike anything she studies, and publishes a new brain to the World.
- **The World** is a whole valley: cottage, garden, orchard, meadow, forest, lake, a village
  with a bakery, library, workshop, well, fire pit and the Oracle's shrine, and an observatory.
  It has days and nights, seasons, weather, three villagers (Mira the baker, Theo the librarian,
  Rowan the gardener) and animals. Ada has six needs and things to do: grow wheat and bake
  bread, cook mushrooms, make an axe, read, play, stargaze, ask questions.
- **By default they take turns:** Ada lives by day; at night she sleeps and the Academy gets
  the whole GPU. Each morning she wakes with the brain she earned.

## New ideas

- **Her own words steer her body.** Her brain writes an intention ("I bake bread in the
  oven."); if the World understands it, she does it. Until then her needs choose, with a reason,
  and she studies those choices. The share of actions that come from her own words is shown
  live.
- **Concepts you can see.** A concept graph built from the world (and grown by the Oracle) is
  drilled in training and tested separately, with every fact's result on the Concepts page.
- **The Oracle (any Ollama model)** writes lessons pitched at her stage and aimed at what she
  gets wrong, teaches any topic you name, answers her questions at the shrine and yours,
  voices the villagers, writes the library's books, suggests the reply she should have given
  you, and assesses her thoughts.
- **Be there with her:** join the valley, carry things, give them to her, hug her, talk; or
  suggest what she should do and watch her try.

## Upgrading

This is a new design with a new save format: minds from v0.x don't carry over (they remain
usable with the v0.2.0 release). Run `start.bat` as before. The first run creates `minds/Ada/`.

---

# Synthetic Mind v0.2.0

## Study or be awake, never both at once

Training and running the mind at the same time made them fight over the GPU, which caused freezes
and a sluggish browser. The mind now has two modes, switched with the buttons in the header:

- **📚 Study**: all of the GPU goes to learning. No thoughts, no conversation, no body steps.
  (You can still add things to the world and walk around in it.)
- **🌱 Awake**: it thinks, talks and lives in its world, with no training. Everything it lives
  through (your conversations, gifts and hugs, books it reads, its body's experiences) is kept and
  studied in the next study session, including what its body learned about looking after itself.

Also:
- **Alternate automatically** (Settings → *Study and awake*): study for N minutes, then wake for M
  minutes, like sleep and waking. The header shows how long until the next switch.
- Sending a message while it studies asks whether to wake it up.
- *GPU time for training* now defaults to 100%, because studying no longer has to share the GPU
  with anything. (If you saved a mind with v0.1.4, set it back to 100% in Settings.)
- New minds start in Study mode.

---

# Synthetic Mind v0.1.4

## Smoother browser, and pauses that explain themselves

- **The dashboard is much lighter.** It used about 14% of the browser's main thread and 80 KB/s of
  updates; now about 4% and 21 KB/s. The map is redrawn only when something moves or changes
  (and not at all in a hidden tab), the header orb no longer animates nonstop, only the tab you are
  looking at is updated, and the map's terrain and the attention data are sent only when they change.
- **Leaves the GPU room for your desktop.** Settings → *GPU time for training* (default 90%): after
  each step the engine rests briefly, so the browser, which shares the GPU, stays responsive. Set it
  to 100% for maximum training speed, or lower if the desktop still stutters.
- **Every pause is measured and explained.** Any stall longer than a second is timed and attributed
  (training, thinking, moving its body, saving, or the whole program being paused by the system) and
  shown on the Growth tab's status line and in `minds/<name>/engine.log`.
- **Faster saves.** Memories are stored compactly in checkpoints, so autosave no longer stalls.

---

# Synthetic Mind v0.1.3

## New: be there with it

- **Join the world as your own avatar.** Under the map, switch to *🧍 Be there* and press
  *Join the world*. You appear next to the mind and the map zooms in to follow you (🔍 shows the
  whole map again). Walk with WASD or the arrows.
- **Give it things.** Take a new apple, berry, ball, book, block or seed into your hands, or pick
  up anything lying around (F), then walk up to the mind and hand it over (G). A book you hand
  over can contain your own writing, which it reads and studies.
- **Keep it company.** Hug it (H) and talk (T or the conversation box): your words appear above
  you and the mind hears them when it is close. It senses where you are and what you hold, can
  take things from your hands and hug you back, and is rewarded for your company, so it learns to
  come to you.

## Fixed: adding things to the world

- Placing items now happens instantly. Before, every world edit waited in line behind training
  and the mind's thoughts, so when the engine was slow or stalled, clicks seemed to do nothing.
- Clearer controls: the world panel has three modes (*Add things*, *Be there*, *Guide the
  mind*), a preview outline shows where an item will land (red where it can't go), and a short
  message confirms what happened, or explains why not.

---

# Synthetic Mind v0.1.2

## Fixed: freezes, and charts that never fill in

- **An unstable training step can no longer break the network.** A step whose loss or gradients
  are not finite (NaN/infinity) is now skipped before it reaches the weights. Previously it was
  applied, which corrupted the weights for good: every later step failed, so no statistics were
  recorded and the charts stayed on "waiting for data".
- **Broken minds repair themselves.** Corrupted weights are never saved; the previous checkpoint is
  kept as `state.prev.pt`, and a mind whose saved weights are broken resumes from the last good
  checkpoint. If none exists the network restarts from scratch, and its memories, conversations and
  world are kept.
- **No more console freezes on Windows.** Clicking inside the console window put it into
  text-selection mode, which pauses any program writing to it. That mode is now switched off for
  Synthetic Mind's window, and repeated messages are rate-limited and written to
  `minds/<name>/engine.log`.
- **The dashboard keeps updating** even if one message or chart fails. Non-numeric values are never
  sent to the page.
- **Training status on the Growth tab**: learning, waiting for data, unstable steps skipped, and
  the last error, if any. The header shows "not learning" when it isn't.

---

# Synthetic Mind v0.1.1

## Fixed: PyTorch installed without GPU support on Windows

On Python 3.14 and newer, `start.bat` failed to find a CUDA build of PyTorch (CUDA 12.4 builds stop
at Python 3.13) and then silently installed PyPI's CPU-only build, so training ran on the CPU.

`start.bat` now:
- tries CUDA 12.6, 12.8, 13.0 and 12.4 builds in turn and checks that it really got one;
- **repairs an existing `.venv`** that has the CPU-only build: just run `start.bat` again;
- prints the PyTorch version and the GPU it will train on before starting;
- explains what to do for 32-bit Python or a Python version with no CUDA build at all.

`run.py` also warns when an NVIDIA GPU is present but PyTorch can't use it.

---

# v0.1.0

The first release: a neural network that starts as random weights and learns language while you
watch it think, talk to it and see it live in a small world.

## Getting started (Windows + NVIDIA GPU)

1. Install Python 3.10+ and [Ollama](https://ollama.com), then pull a chat model: `ollama pull llama3.2`.
2. Download the `synthetic-mind-….zip` of the latest release and unzip it.
3. Double-click `start.bat`. The first run installs PyTorch (CUDA) and the requirements, then opens
   the dashboard at http://127.0.0.1:8765.

Linux/macOS: `./start.sh`. See the README for options (`--preset`, `--tokenizer`, `--name`, …).

## What's in it

- **A network trained from scratch**: a modern transformer (RMSNorm, rotary positions, QK-norm,
  SwiGLU) trained with the Muon optimizer, bf16 and a memory-saving loss. About 51M parameters by
  default, sized for an 8 GB GPU; tiny, medium and large presets too.
- **Inner monologue**: a thought every few seconds, generated only from its own past thoughts, with
  each token shaded by the network's confidence and real words underlined.
- **Conversation**: talk to it at any stage; 👍 replies to make them study material, or switch to
  *Teach* to hand it text directly.
- **A body in a garden world**: hunger, boredom, a cat, books, a ball, a lamp, a music box, a mirror,
  seeds and a bed. The same network picks its actions and learns from rewards and from your
  demonstrations; what happens is narrated in words it studies.
- **FineWeb streaming**: random 1000-document row groups from across Common Crawl, with flat memory.
- **Ollama teacher**: lists your installed models, writes stage-matched lessons and dialogues,
  rewrites muddled thoughts, suggests ideal replies and scores its language every 5 minutes.
- **Growth**: add layers (by button or automatically on a plateau) without forgetting.
- **Dashboard**: developmental stage, loss and bits-per-byte charts, vocabulary, body reward,
  attention maps, a prediction probe, live settings. Light and dark themes; works on a phone.
- Minds autosave and resume by name, including the monologue, conversations and world.

## Known limits

- Tested on CPU and against a simulated Ollama server; this is the first release on real GPUs and
  real Ollama models, so please report anything odd.
- `--compile` needs Triton (Linux/WSL); it is off by default on Windows.
