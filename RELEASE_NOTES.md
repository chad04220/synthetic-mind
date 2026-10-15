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
