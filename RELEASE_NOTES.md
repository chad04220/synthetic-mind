# Synthetic Mind v0.1.0

The first release: a neural network that starts as random weights and learns language while you
watch it think, talk to it and see it live in a small world.

## Getting started (Windows + NVIDIA GPU)

1. Install Python 3.10+ and [Ollama](https://ollama.com), then pull a chat model: `ollama pull llama3.2`.
2. Download `synthetic-mind-v0.1.0.zip` below and unzip it.
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
