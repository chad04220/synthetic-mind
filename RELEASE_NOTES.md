# Synthetic Mind v3.0.0: Zen and Wren

One synth, one companion, one small and deep world. The village of v2 is gone. Zen now lives in a
little house in a quiet hollow with Wren, who raises it.

## Wren

- **One language model, one companion.** Wren is the only language model in the program
  (llama.cpp on the CPU, Gemma 2 2B by default, or Ollama). It replaces the Oracle and the seven
  villagers' voices, so it is lighter on the CPU.
  - Wren has a body in the World with the same needs, verbs and planner as Zen.
  - Each time Wren is free, the World lists what it could sensibly do right now, and the model
    chooses one and says what Wren says out loud.
  - If the model is busy or switched off, Wren picks the most pressing thing itself.
- **Care that follows Zen's language.**
  - **Caretaker:** at first Wren feeds Zen, brings it water, dries it, puts it to bed, takes it
    along to its chores and talks it through them.
  - **Guide:** as Zen's language grows, Wren tells it what it needs and lets it do it.
  - **Friend:** later still, Wren helps when asked.
  - You can also fix the level in Settings.
- **Naming things.** Wren shows Zen what it can see and names it at Zen's level ("Look, Zen. This
  is an egg. It is smooth and white. Can you say egg?").
- **Conversations, one turn at a time.** When Zen babbles, Wren guesses kindly what it meant and
  says it back properly.
- **Questions.** Zen asks Wren questions, and Wren answers at Zen's level.
- **Bedtime stories.** Every night Wren tells Zen a story about the day. They are kept on the new
  **Stories** tab.
- **Picture books, star facts and a diary.** Wren reads Zen picture books, tells it about the stars
  through the telescope, and keeps a diary of their days.
- **Lessons from your days together.** The Academy's lessons are now written by Wren, with
  examples from what the two of them did.
- **FineWeb stays.** Zen's brain still trains from scratch on web text streamed from FineWeb,
  alongside Wren's lessons and its own life.

## Everything Zen hears, it studies

- Wren's words go into Zen's journal next to what Zen saw at that moment.
- So do Wren's deeds, in words ("Wren puts the pot on the stove."), whenever Zen is close by.
- So do their conversations, Wren's answers, the stories, and Wren's instructions followed by
  what Zen then did.

## A smaller, deeper world

- **The homestead** (72 × 56):
  - **The house:** a living room with the fireplace, a kitchen with the stove and oven, sink,
    pantry and table, Zen's little bedroom, Wren's bedroom and a washroom.
  - **Outbuildings:** the workshop with the quern and the woodpile, a glass greenhouse, the
    vegetable garden and the chicken coop.
  - **Further out:** an orchard with a swing, a pond with a jetty, a stream through the woods, a
    meadow with the beehive, and a lookout for the stars.
- **Physics:**
  - Rooms have a temperature that the fire raises and the night lowers.
  - Things warm and cool; soup cooks in the pot, the kettle boils and whistles, bread bakes in
    the oven, and food left too long burns.
  - Food goes stale and rots, more slowly in the cool pantry.
  - Rain soaks what is outside and fills the water barrel. Wet logs won't burn. Fires use up their
    wood and leave ash. Lamps and candles light the dark and burn down.
- **Life:**
  - The soil dries out. Plants grow through their stages if watered and warm, and die in a frost.
  - Harvests give back seeds.
  - Hens lay eggs in the morning, the rooster crows at dawn, and bees make honey while flowers
    bloom.
  - Moss the cat eats from its bowl and sleeps by the fire.
  - Deer come at dusk; an owl and a hedgehog at night.
- **Senses:** Zen hears things (the kettle, the rain on the roof, the piano), and can't see far in
  the dark without a lamp.
- **Big jobs unfold into steps,** each with its own sentence. For example, cooking soup means
  filling the pot, putting a carrot in it, putting it on the stove, adding a log, lighting it and
  waiting.
- **A seventh need.** Zen now also needs to stay clean (a bath), and gets wet in the rain (a
  towel).
- **Moving house.** Minds from earlier versions keep their brain, day, firsts and art, and move
  into the new house.

## The page

- **Home** shows Zen and Wren, the temperature in the house, what can be heard, and a feed of what
  Wren says, Zen's words and what happens.
- **Together** has Zen's journey, both minds in full, the words Wren has heard Zen say, how Wren is
  caring for Zen, and Wren's diary.
- **Stories** and **Keepsakes** (everything they made) are new tabs.
- The **Wren** tab shows the model, Wren's lessons and thoughts, and lets you talk with Wren.

---

# Synthetic Mind v2.0.1

Fixes from the first diagnostics report from v2.0.0.

- **The 3D valley stays off the training GPU.** It used to ask the browser for the fast GPU and
  draw as many frames as the screen allowed (240 a second on a 240 Hz laptop screen), so it
  shared the GPU, and its heat, with the Academy. It now asks for the low-power GPU and draws
  at most 60 frames a second (30 on Low quality), which looks the same.
- **Settings show the right vocabulary.** The brain uses the tokenizer's 32,768 tokens; Settings
  and the diagnostics report showed the old default of 50,304.
- **FineWeb status.** It shows "streaming" while documents are buffered, rather than
  "connecting" each time it opens the next file.
- **No ResourceWarning** while a voice's server is still loading its model.

# Synthetic Mind v2.0.0: Zen and the valley of minds

A new synth, a valley four times the size, a community of minds that think, talk and create,
and a 3D world you can walk around in.

## Zen

- **A new synth, Zen, is the default.** It starts from nothing, like Ada did. Ada is kept: run
  `python run.py --name Ada`, or `start.bat --name Ada`.
- **A 32k vocabulary trained on FineWeb.** On unseen FineWeb text it packs slightly more text per
  token than GPT-2's 50k vocabulary: 4.65 against 4.59 bytes per token. It is 35% smaller, so less
  of Zen's brain is a lookup table and the loss is cheaper. It writes any text; nothing is out of
  vocabulary.
- **Zen's journey.** First word, first phrase, first sentence, first action in its own words,
  first conversation, first painting, first song, each stage, and concept scores: each first time
  is recorded with the day and what was said.

## A community of minds

- **Seven villagers, each with its own voice:** Mira the baker, Theo the librarian, Rowan the
  smith, Juniper the merchant, Finn the fisher, Sage the teacher and Pip, a child who loves to
  play. Each villager is its own llama.cpp server on the CPU. They share one copy of the model
  in memory (about 260 MB each instead of 1.2 GB).
- **The same selfhood as Zen.** Each has six needs and the feelings they bring, intentions in
  their own words (their needs and their work decide when their model is busy), the same planner
  and actions as Zen, an inner monologue, a diary, coins, and friendships with everyone.
- **Conversations, one turn at a time.** Whoever has something to say starts the conversation and
  walks up to the other mind. The speaker composes its line (a "…" bubble) while the listener
  waits; then they swap. This works between villagers, and between villagers and Zen, who answers
  with its own brain. Zen studies the conversations it takes part in or overhears.
- **A priority gate** lets a few villagers generate at once on your CPU: conversation turns first,
  then decisions, then naming their works, then thoughts.

## Lasting art

- **Paintings** of the valley's places, times and seasons; **music** composed at the piano and
  recorded (play it in the Gallery); **sculptures** carved from stone, wood or clay; **buildings**
  (benches, birdhouses, lamp posts, fountains, flower beds); **poems**. They are made by Zen and
  the villagers, named by their makers, kept in the valley and in the new **Gallery**.
- New materials and tools: clay from the river, a chisel, a hammer, paper.

## A bigger valley

- **128 × 96 tiles:**
  - mountains with a mine and a snowy peak, a river with bridges, a lake with a beach and a dock;
  - a village with a plaza, market, school, workshop and forge, music hall, studio and park;
  - Zen's cottage with a farm and an orchard, a meadow with beehives, the observatory, a forest.
- **More to do:** fishing, mining, milking, eggs and honey, carrots and pumpkins, baking pies,
  crafting, quests from the villagers, buying and selling, swimming, kites, snowmen.
- **Money goes round:** sellers are paid, the market buys what you sell from its own purse, and
  work earns a little.

## A 3D valley

- **A three.js view** with day and night, seasons, weather, lit windows and fire, swaying trees,
  water, and characters with name tags and speech bubbles.
- **Visit the valley yourself:** WASD and the mouse, Shift to run, V for first person, E to
  use or talk, G to give, H to hug. Talk to Zen or to the villager you face.
- **An information overlay:** every mind's mood and activity, a minimap, a live feed, and a card for
  whoever you select. The new **Minds** tab shows them all in full.
- A welcome screen on first visit (the **?** button shows it again).

## Under the hood

- The Oracle and the villagers' servers stop together with the program, even mid-start.
- The 3D view counts positions with whole numbers at tile centres; the server agrees.
- 41 tests, including the turn-taking protocol, the gallery surviving a restart, every new
  activity, and the tokenizer.

---

# Ada v1.2.1

## Fixed: the built-in Oracle couldn't download llama.cpp ("HTTP Error 404")

llama.cpp publishes a new release many times a day, and each one appears on GitHub before its
files have finished uploading. The newest release had no Windows file yet, so the program fell
back to a fixed release that turned out not to have one either.

- It now looks through llama.cpp's recent releases and downloads the newest one whose file for
  this computer is actually there. Without GitHub's release list (it allows 60 requests an hour),
  it follows the "latest release" page instead.
- If the download still fails, the message names the address that failed and says what else you
  can do: put `llama-server` in `oracle/llama.cpp/` yourself, or use Ollama.

## Faster training: fewer passes over the vocabulary

Your report showed that the loss over the 50,304-token vocabulary took 288 ms of each step (the
forward pass took 72 ms, the backward pass 133 ms). Its cost is memory traffic: every step of the
calculation reads and writes a 1024 × 50,304 block of numbers. It now makes about 40% fewer
passes over that block:
- the 1/30 scaling is folded into the weights;
- the loss is read straight from the softmax;
- the tanh derivative takes one fused step;
- the masking pass is skipped in training, whose batches never contain ignored positions.

The results are the same up to bf16 rounding (checked by the tests).

---

# Ada v1.2.0

## The GPU is for training; everything else runs on the CPU

- **A built-in Oracle, no Ollama needed.** On first use the program downloads llama.cpp's
  server (the CPU build, tens of MB) and a small model into the `oracle/` folder. It runs the
  server on the CPU and keeps it running. The Oracle tab shows download progress, and you can
  pick the model there:
  - Gemma 2 2B Instruct, 1.7 GB (default);
  - Qwen 2.5 1.5B Instruct, 1.1 GB (lightest);
  - Llama 3.2 3B Instruct, 2.0 GB (strongest, slowest).

  Ollama is still there: choose *Ollama* on the Oracle tab (or `--oracle ollama`) to use your own
  models. While the built-in Oracle is in use, the program asks Ollama to unload the Oracle
  model it was using, freeing its memory.
- **Ada's brain runs on the CPU by default**, and the Ollama Oracle too, if you use it.
- **CPU cores are shared out:** half the physical cores for her brain, the rest for the Oracle,
  so they don't fight over the same cores. Both counts can be set in Settings.
- **Ollama uses much less memory:** its context is now capped at 4,096 tokens, enough for the
  Oracle. Before, Ollama's default could be 65,536 tokens, so a 2B model took about 10 GB of RAM.
- **"Together" is the default schedule.** With nothing else on the GPU, the Academy trains on all
  of it, all the time, while Ada lives. Her brain picks up each new version as it is published.
  (*Day & night* is still available in Settings.)
- **The batch grows to fill the GPU's free memory.** At start-up the Academy measures how much
  memory a batch needs and picks the largest that fits. It leaves room for the desktop and never
  finds the limit by running out: on Windows, running out silently spills into RAM. The size
  chosen is in the log, and as *batch tokens* on the Health tab.
- **Your existing mind switches over automatically:** her brain, the Oracle and the schedule
  move to the new defaults, unless you had changed those settings yourself.

---

# Ada v1.1.4

## A cooler CPU while Ada studies

While the GPU trained, the Academy kept one CPU core busy at 100% doing nothing useful. Each
time it waited for the GPU to finish a step, it checked "done yet?" millions of times a second
(PyTorch's default way of waiting) instead of sleeping. Task Manager averages over all 12
threads, so this looked like only about 8% of the CPU. But one core flat out runs at its highest
boost clock, and on a laptop it shares a single cooler with an 80 W GPU, so the CPU ran very hot.

- **The Academy now sleeps while it waits for the GPU** and is woken when the step is done. Its
  CPU use while studying should drop from a full core to a small fraction of one, with no loss of
  speed.
- In the Health tab, the time the GPU spends on a step now shows up as *waiting for the GPU*.
  *Forward + backward* is now only the time spent handing the work to the GPU. The GPU-side split
  (forward, loss, backward) is still measured every 100 steps.

---

# Ada v1.1.3

## Faster training

Your v1.1.2 report showed the earlier fix working: with Ollama out of GPU memory, the Academy went
from about 6,900 to about 18,000 tokens per second. It also showed what still held it back. A
step took about 365 ms on the GPU: 45 ms for the forward pass, 68 ms for the loss and 253 ms for
the backward pass. Most of that went to the loss over the 50,000-token vocabulary, which was
worked out three times: once going forward, again when the backward pass recomputed it, and a
third time to get its gradient.

- **The loss and its gradient are now worked out in a single pass.** Each block of tokens' scores
  over the vocabulary is computed once, turned straight into the gradients, then thrown away.
  Results are identical to before (checked by a new test), and on a CPU this part runs 2–3×
  faster. On your GPU the whole step should be noticeably quicker.
- **The optimizer works on all same-shaped matrices at once** instead of one at a time: fewer,
  larger GPU operations, with exactly the same result (also checked by a test).
- **Heat:** the report showed the laptop GPU at 89 °C, running at 1215 MHz while training. That is
  safe, but it slows itself down to cool. The Health tab now says so and suggests what helps:
  - plug the laptop in;
  - raise the back for airflow, or use a cooling pad;
  - choose the high-performance power mode;
  - or set GPU intensity to Balanced.
- Fixed a script error on the World page (`Cannot read properties of undefined (reading
  'sleeping')`) when the page opened before the World had sent its first picture.

---

# Ada v1.1.2

## Training speed: finding out why it's slow, and two likely fixes

A Health report showed the Academy training at about 6,900 tokens per second on an RTX 3070:
roughly a tenth of what that card should manage, with nearly all the time in the forward and
backward pass. The most common cause on Windows is GPU memory running out: Windows then quietly
spills it into ordinary RAM, which can make the GPU 10 to 50 times slower.

- **The Oracle no longer competes for GPU memory while Ada studies.** New setting *Oracle runs on*
  (default: CPU while she studies, GPU otherwise). When studying starts, the Hub asks Ollama to free
  the GPU memory its model holds (Ollama otherwise keeps it loaded for minutes, even with the Oracle
  off).
- **Training needs about 0.5 GB less GPU memory** (the loss is computed in smaller pieces).
- **The report now shows exactly where training time goes:**
  - a GPU speed test when the Academy starts (with PyTorch, CUDA and free memory in the log);
  - every 100 steps, one step timed on the GPU itself: forward, loss over the vocabulary, backward;
  - GPU memory free, reserved and peak, and how much of the GPU's measured speed training uses;
  - what Ollama holds in GPU memory.
- New Health findings: "training uses only N% of what this GPU can do" (with the likely reason),
  "the GPU itself is slow", and "Ollama is holding GPU memory while the Academy studies".

If training is still slow, send a new report: it now pinpoints the cause.

---

# Ada v1.1.1

## Fixed: the world froze every few seconds

Your Health report showed it: one of Ada's thoughts took 2.8 seconds on the GPU, and her thinking,
deciding and replies all ran on the World's main loop, so the whole valley stopped while she
searched for words (the World's steps fell up to 2.5 s behind).

- **Her brain now has its own thread.** Thoughts, intentions, replies and loading a new brain are
  queued (your messages first) and answered in the background; the World keeps its pace no matter
  how long they take. If her own words take more than 3 seconds, her needs decide for her.
- **Generating words is much faster on a GPU.** Previously every word made the program stop and
  wait for the GPU several times, which is especially slow on Windows. Now the GPU works through
  several words before the program checks in.
- **Settings → Her brain runs on** (GPU / CPU) moves her brain while she lives, without restarting.
  On the CPU, her daily life leaves the GPU entirely to the Academy.
- The Health tab now says when her brain itself is slow, and suggests what to do.

---

# Ada v1.1.0

## New: error logs and a performance report you can share

- **Every error and warning is logged.** The Hub, the Academy and the World each write to
  `minds/<name>/logs/<process>.log` (UTF-8, rotated at 2 MB): their own warnings and errors,
  PyTorch's warnings, and the full traceback of anything that crashes, including inside threads.
- **Every part times its own work.** The Academy (waiting for data, forward and backward,
  optimizer, waiting for the GPU, resting, evaluating, saving), the World (each step, deciding,
  thinking, replies, loading a brain, how far behind schedule it runs), the Hub (how promptly the
  web server responds, message handling, data sent), and the browser itself (frame rate, worst
  pause between frames, frozen moments, map drawing time, update handling, script errors).
- **GPU readings** from `nvidia-smi` every 10 seconds: load, memory, temperature, power, clock.
- **A 🩺 Health tab** shows all of it live and points out likely bottlenecks in plain words
  (for example "the GPU is fully busy training and the page is drawing slowly").
- **Download report** writes everything (findings, system, GPU, timings over the last 30
  minutes, settings, warnings and errors, recent log) into one text file. A copy is also kept
  as `minds/<name>/logs/diagnostics-latest.txt`.

If something feels slow or breaks, open the Health tab, press **Download report**, and send the
file.

---

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
