# Synthetic Mind v4.0.0: a mind that makes itself

A new design. Zen is alone in an endless world, and everything it does comes from its own brain.

## Zen's own mind, all the way down
- **No caretaker, no planner, no script.** Wren is gone, and so is every rule that chose for Zen.
  Its brain (the language model the Academy trains) chooses every action, one word at a time,
  from 14 motor words: forward, back, left, right, wait, take, drop, eat, drink, use, sleep, look,
  speak, ask. The only things that happen by themselves are physics: Zen falls asleep when exhausted
  and faints (waking at home) when its health runs out.
- **It learns from what happens.** The world reports the consequence of every deed and how it
  felt: hunger eased, thirst quenched, warmth from a fire, a new place found, pain at a wall. The
  Academy learns from Zen's own stream two ways: predicting what follows what it does (its
  understanding of the world) and a policy gradient on its own choices (doing more of what turned out
  well). Its past choices are never copied as text, so chance can't harden into habit.
- **Boredom**, a sixth need: waiting around and doing the same thing with nothing new coming of it
  makes Zen bored, which feels bad; new places, new things, varied deeds, making art and the
  Sprite's answers relieve it.
- **Real deeds are worth something.** Eating, drinking clean water, lighting a fire, cooking,
  reading a book, chopping a tree, opening a chest, sleeping in a bed and more earn a reward of their
  own, worth less each time they are repeated soon after, so only genuine doing pays.
- **Thoughts, words and deeds in one stream.** What Zen perceives, thinks, says, is told and does is
  one continuous text its brain reads, so language and action grow together.

## The Sprite of All Knowing
- A small glowing sprite floats beside Zen and answers whatever Zen asks. When Zen's brain chooses
  *ask*, its brain also writes the question; its body waits for the answer while its thoughts go on.
  Early questions are babble; the Sprite guesses kindly what Zen likely means and answers that.
- It runs on llama.cpp on your CPU and costs nothing unless asked. Its default model, **Qwen 2.5
  Omni 3B**, can see and hear (3.6 GB with its projector). You can ask it about Zen on its tab.

## Art from nothing, one mark at a time
- At the easel, the piano, with clay or at the desk, Zen's brain chooses every mark: where the
  brush moves, when it presses and lifts, which of 12 colours; every note, octave, length and rest;
  every bit of clay added, cut or smoothed; every written word. No templates, no composers.
- **The Sprite looks and listens**: it sees each painting and sculpture and hears each song, says
  what it sees, tells Zen something kind and honest, and scores it. That verdict is the reward for
  every mark that made the piece (with the studio's own measures as a smaller part, and as a
  fallback).
- **♥ Love** a piece in Keepsakes: every mark that made it counts for more in Zen's learning.
- **Time-lapse**: replay any piece mark by mark. Watch Zen paint live on Home.

## An endless world
- Generated from a seed in 32×32 chunks as Zen goes: meadow, grassland, forest, pine forest, jungle,
  swamp, savanna, desert, tundra, snow, mountains and rock; lakes, rivers and the sea.
- Named places: ruins with chests and real books to read, abandoned cabins, caves, standing stones,
  springs, cairns to climb and look far from, beehives, nests and old wells.
- Animals that wander, flee and sleep; fruit in season, poisonous mushrooms, honey, fish and eggs.
- Day and night, seasons, rain, storms, snow, fog and wind; temperature by land, height and hour;
  shelter, fire, darkness, getting wet. A cabin at home with a bed, fireplace, books, an easel,
  a piano, a desk and a rain barrel.

## The page
- **Home**: the world in 3D, streamed around Zen, with the Sprite, live art, a local map and Zen's
  needs (including boredom) and choices. Follow, Free and Visit modes.
- New tabs: **Zen** (journey, body, motor mind), **Atlas** (everywhere Zen has been), **Sprite**.
- **Thoughts** now shows every action and its consequence too; **Conversations** shows its
  questions, the Sprite's answers and verdicts, and your talks.
- **Keepsakes**: what the Sprite saw and said, the piece's measures, time-lapse replay, ♥ Love.
- **Academy**: "learning from its own life" (policy loss, choice entropy, return).

## Under the hood
- Fixed: feeding several tokens at once into the brain's attention cache gave wrong results (Zen's
  continuous stream depends on it).
- Zen's brain chooses an action in about 40 ms on 4 CPU threads (small brain).
- Upgrading keeps Zen's brain, journey and keepsakes; its life starts over in the endless world.
- 64 tests, including a real (tiny) brain living, painting, asking and being judged end to end.

---

# Synthetic Mind v3.3.1

- **The Thoughts tab shows what Zen decides, too.** In your report, Zen's brain was brand new
  (training step 0), so its own monologue was still silence, and the tab stayed empty, even though
  Zen was plainly thinking "I look in the mirror. I wonder what I look like." That line is Zen's
  decision and its reason, which the tab didn't keep. Now it does:
  - each decision, with its reason and where it came from (its needs, its own words, Wren's words
    or your idea);
  - its monologue in its own words, as before. A new brain's monologue is mostly silence; words
    come as it learns;
  - **All / Decisions / Monologue** to show one or the other; search covers both.
- Decisions are kept from this version on.

---

# Synthetic Mind v3.3.0

- **💭 Thoughts, a tab of its own.** Every thought Zen has, kept whole on disk
  (`minds/<name>/thoughts.jsonl`) and shown in full, newest first, with a header for each day.
  - Shading shows how sure its brain was of each word; switch it off to read plain text.
  - Search for a word, and page back as far as the very first thought.
  - New thoughts appear at the top as Zen has them.
- **🗣️ Conversations, a tab of its own.** Every conversation Zen has, kept whole on disk
  (`minds/<name>/conversations.jsonl`), every line in full as a chat:
  - its conversations with Wren, with what they were about;
  - its questions to Wren and Wren's answers;
  - its talks with you. Messages a few minutes apart read as one conversation.
  - Show all of them, only Wren's or only yours, and search them.
- Nothing is cut off any more: the boxes on Home show only the latest, but these tabs keep and
  show everything.
- Thoughts and conversations are kept from this version on; earlier ones weren't stored in full.

---

# Synthetic Mind v3.2.0

**Keepsakes that grow into real art.** Zen and Wren can now make richer, more crafted pieces, and
both get better with practice.

- **Paintings** are now composed scenes instead of a few shapes:
  - layered land (hills, forest, water, fields, snow or a room), a sky for the hour, weather and light;
  - the things the painter chose (the moon, hens, an apple tree, fireflies…);
  - a palette from the season and the mood;
  - seven styles: naive, watercolour, impressionist, oil, pastel, ink and pointillist.
- **Songs** have a key, a mode, a tempo, chords, a melody grown from a motif, a bass line and a form
  such as AABA. They are played with real instruments (piano, flute, strings, music box, bell,
  guitar, voice) and a little reverb.
- **Sculptures** are built from parts, so a sleeping owl or a sitting cat looks like one. They come in
  clay, wood or stone, with a rough, smooth or polished finish and sometimes a glaze. Turn them in 3D
  on the Keepsakes tab.
- **Skill.** Each of them has a skill for every medium, shown on the Together tab.
  - Every piece is practice, and so is Wren's feedback, looking at a piece and working side by side.
  - Zen's growing language helps too. Its first paintings are lopsided and naive; later ones have
    composition, harmony and light.
  - Wren starts as a fair amateur and gets better.
- **Zen paints what it says.** "I paint the moon over the pond" becomes a night painting of the moon
  and the pond.
- **Wren plans its pieces with its language model:** title, subject, style, colours, mode, tempo and
  form. The World then makes the piece from that plan.
- **Wren looks at Zen's work** and says something kind and useful about it. Its words are kept
  with the piece.
- **Ask Wren to make something** on the Keepsakes tab, for example "a song about the hens at dusk".
- **Art in the house.** Paintings hang on the walls in frames. Sculptures stand on plinths in the
  yard. Either of them can stop to look at a piece. Click one in the 3D view to open it.
- **The Keepsakes tab** is a gallery:
  - framed paintings, songs with a piano roll, 3D sculptures and typeset poems;
  - filters by kind and by maker, sorted newest or best first;
  - a viewer with the full piece, its description, the maker's skill and Wren's words, and
    previous/next with the arrow keys;
  - download a painting or sculpture as PNG, a song as WAV, a poem as text.
- **Wren finishes what it starts.** If Zen comes to it or starts a conversation mid-piece, Wren
  goes back to the piece afterwards. A commission stays open until it is made, and if Wren's
  model is too slow to plan it, Wren still makes it about what you asked for.
- **One look for every tab.** Each tab opens with the same header (an icon, its name, what it is
  for, and its main buttons), then evenly spaced cards with titled sections, in a warmer theme in
  both light and dark mode. Labels in Settings no longer break apart around a name.

---

# Synthetic Mind v3.1.0

- **60 frames a second, whatever the screen.** The 3D view drew at most 60 frames a second before,
  but on a 240 Hz laptop screen the browser still woke the page 240 times a second, and the
  minimap's loop as well.
  - Now the browser isn't asked for a frame until the next one is due, so the page wakes about
    60 times a second (30 on Low quality).
  - The minimap wakes about 30 times a second.
  - On every tab but Home the 3D view sleeps completely, and it picks up again when you come back.
  - The Health tab reports the frames the 3D view actually drew.
- **Separate tabs for what's happening** (below the 3D view):
  - **💬 You & Zen**: your conversation with Zen;
  - **🗣️ Zen & Wren**: only what the two of them say to each other, as a chat: their
    conversations, Wren's words to Zen (naming things, talking it through, looking after it) and
    Zen's questions with Wren's answers;
  - **💭 Zen's thoughts**: its inner monologue;
  - **🪶 Wren's thoughts**: what Wren thinks to itself, and what it decides to do and why;
  - **📔 Deeds**: what each of them did, with a switch to show only Zen's or only Wren's.
- **Fixed: lost updates.** When something happened in the house that carried a detail of its own
  (a fire going out), the Hub crashed on the World's message, so that update to the page was lost.
- **Faster Wren.** Your report showed Wren's decisions taking about 14 seconds.
  - Its model now gets more of the CPU: 4 of 6 physical cores. Zen's small brain keeps 2.
  - Its long, unchanging instructions are cached between requests.
  - Its decision prompt is shorter.
- **No false "page is drawing slowly" warning** while the page is in the background or on
  another tab.
- Wren names plural things properly ("These are some wooden blocks.").

---

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
