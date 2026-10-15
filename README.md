# Synthetic Mind

A neural network that starts as random weights and learns language while you watch, think
along with it, and talk to it. It lives in a small garden world through a body, has a
free-running inner monologue, studies web text streamed from **FineWeb**, and is tutored
by whichever **Ollama** model you have installed.

Everything it knows it learns itself, by gradient descent on its own predictions. Ollama
never touches its weights: the teacher only writes text, which goes into the training mix
like any other experience.

```
                ┌──────────────── one engine thread owns the network ────────────────┐
 FineWeb ──►    │  training step  ◄── data mix: web text · teacher lessons · lived   │
 (streamed)     │       │                          experience (chats, books, world)  │
                │       ▼                                                            │
 Ollama  ──►    │  MindNet (transformer trained from scratch)                         │
 (teacher)      │    ├─ language head ──► inner monologue · replies · speech          │
                │    └─ policy + value heads ──► body actions in the world (RL)       │
                └──────────────────────────────▲─────────────────────────────────────┘
                                               │ WebSocket (4×/s)
                                     browser dashboard (you)
```

## Quick start (Windows + NVIDIA GPU)

1. Install Python 3.10+ from python.org (tick *Add to PATH*).
2. Install [Ollama](https://ollama.com) and pull at least one chat model, for example
   `ollama pull llama3.2` (3B is plenty; a 7–8B model writes better lessons).
3. Double-click **`start.bat`**. The first run creates `.venv`, installs PyTorch with CUDA
   and the other requirements, then opens the dashboard at <http://127.0.0.1:8765>.

Linux/macOS: `./start.sh`. Manual setup:

```
pip install torch --index-url https://download.pytorch.org/whl/cu124   # or the CPU build
pip install -r requirements.txt
python run.py
```

On start it queries Ollama's `/api/tags`, lists every installed chat model (embedding
models are filtered out) and picks one; switch models any time in the **Teacher** tab.
Without Ollama it still learns from FineWeb and from you.

## Options

```
python run.py --name Ada              # create or resume a mind (saved in minds/<name>/)
python run.py --name Bo --preset tiny --tokenizer bytes
python run.py --preset medium         # bigger brain for a 12 GB+ GPU
python run.py --no-fineweb            # learn only from the teacher, you and the world
python run.py --ollama-url http://192.168.1.20:11434
python run.py --compile               # torch.compile (Linux/WSL with Triton): ~1.3–2x faster
python run.py --cpu                   # force CPU
```

| preset | width × layers | context | parameters (GPT-2 tokens) | suits |
|---|---|---|---|---|
| tiny   | 256 × 4  | 256  | ~16M  | CPU, quick experiments |
| small  | 512 × 8  | 512  | ~51M  | **8 GB GPUs (RTX 3070) – default on GPU** |
| medium | 768 × 12 | 1024 | ~124M | 12–16 GB GPUs |
| large  | 1024 × 16| 1024 | ~250M | 24 GB GPUs |

`--tokenizer gpt2` (default on GPU) uses GPT-2's BPE, so each training step covers ~4.4
bytes of text per token. `--tokenizer bytes` (default on CPU) reads raw UTF-8 bytes, so
you can watch it learn to spell, letter by letter.

Minds autosave every 10 minutes and on Ctrl+C. Restarting with the same `--name` resumes
everything: weights, optimizer, monologue, conversations, memories and the world.

## The dashboard

**Header.** Its developmental stage (Static → Babbling → First words → Phrases →
Sentences → Conversational → Articulate, judged from held-out bits per byte), age, tokens
read, brain size, speed and how many real words it has used. *Pause learning*, *Think*,
*Grow* and *Save*.

**World.** A garden with a pond, trees, a bed, a lamp, a mirror, a music box, books, balls,
blocks, seeds, berries, apples and a cat. The body gets hungry and bored; eating, playing,
reading, petting the cat and discovering new places are rewarding. Each step the body's
senses are written as first-person text ("I feel hungry. I see a red apple 2 north…"); the
same network that learns language reads it and chooses one of 12 actions. What happens is
narrated back and studied, so its words are grounded in what it does. Books it reads
contain FineWeb pages (or text you write) and become study material.
- Click an item in the palette, then click the map to place it (signs and books ask for text).
- Drive the body with the d-pad or keys (WASD/arrows, E use, F take, G drop, L look,
  V speak, Z sleep, Q approach). Driving is a *demonstration*: it learns to imitate you.
- *What it wants to do* shows the policy's current action probabilities.

**Inner monologue.** A thought every few seconds, generated freely: the only input is its
own previous thoughts. Every token is shaded by the probability the network gave it (hover
for exact numbers) and real words are underlined. Switch on *Grounded* to let it sense the
world before each thought.

**Conversation.** *Talk* to it at any stage and it answers with whatever it has; hearing
you is training data. With the teacher on, each reply gets a *Teacher suggests* line,
which it then studies. 👍 a reply to make that exchange a study example. *Teach* mode sends
text straight into its studies.

**Growth tab.** Training and held-out FineWeb loss, bits per byte, share of real words in
its thoughts, vocabulary, body reward, tokens/s and the teacher's 0–10 assessments of
spelling, grammar, coherence and meaning (every 5 minutes).

**Brain tab.** Attention map of the last thought, activation size and attention spread per
layer, a *probe* that shows how surprised it is by each token of your text and what it
expects next, and its anatomy.

**Teacher tab.** Model picker, status and the teacher's notebook: lessons, dialogues, rewritten
thoughts and ideal replies. **Data tab.** FineWeb status, the file it is reading, and
sliders for the diet (web text / teacher lessons / lived experience). **Settings.** Thought
rate, length and temperature, monologue memory, reply length, body speed, learning rates,
autosave and automatic growth.

## How it learns as fast as it can

- **Modern architecture**: RMSNorm, rotary positions, QK-norm, SwiGLU, tied embeddings,
  logit soft-capping, zero-initialised residual outputs.
- **Muon optimizer** for the transformer's matrices (orthogonalised momentum, the optimizer
  behind the fastest GPT-2 speedruns) with AdamW for embeddings and heads.
- **bf16 autocast, TF32, fused AdamW**, optional `torch.compile`, and a chunked
  cross-entropy that never materialises the full logits tensor (with a 50k vocabulary that
  tensor would otherwise be the largest thing in GPU memory).
- **Lean FineWeb streaming**: random 1000-document parquet row groups fetched by HTTP
  range requests from random Common Crawl dumps, tokenized on a background thread into a
  2048-document buffer. Memory stays flat and the GPU never waits. Two batches are held out
  as a clean validation set.
- **Curriculum**: the teacher writes toddler sentences while the mind is babbling, picture
  book text at first words, short stories, explanations and essays as it matures, plus
  dialogues in the same format as your conversations.
- **Distilled self-correction**: the teacher rewrites muddled thoughts into the clear
  thought they reach for, and the mind studies them.
- **Growth without forgetting**: a new transformer block starts as the identity, so
  *Grow* (or auto-growth on a plateau) adds depth without changing what the network
  computes, then lets it use the new capacity.
- **One network, many signals**: language modelling, the body's actor-critic loss and
  imitation of your demonstrations all train the same trunk in the same step.

## What to expect

On an RTX 3070 the *small* preset trains at very roughly 50–100k tokens per second.
Expect babbling within minutes, real words within the first hour, grammatical phrases
after a few hundred million tokens and coherent sentences after a few billion (a day or
more). A 50M-parameter network will not become an assistant like the teacher; it becomes a
small, genuinely self-trained language model whose growth you can watch and shape. Larger
presets go further if your GPU allows.

## Files

```
run.py              entry point and command-line options
mind/config.py      all settings (saved as minds/<name>/config.json)
mind/model.py       the transformer, its body heads and growth
mind/optim.py       Muon + AdamW
mind/data.py        FineWeb streaming, replay pools, batch mixing
mind/tokenizer.py   GPT-2 BPE or raw bytes, plus role tokens
mind/brain.py       the Mind: engine loop, training, thoughts, chat, body, saving
mind/teacher.py     the Ollama curriculum, tutor and assessor
mind/ollama.py      Ollama HTTP client
mind/world.py       the garden world and the body
mind/server.py      FastAPI + WebSocket server
web/                the dashboard (no external dependencies, works offline)
tests/              offline tests:  python -m pytest tests
```
