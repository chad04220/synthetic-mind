# Synthetic Mind v4: Zen alone, in an endless world

Zen is the only mind. Everything Zen does comes from its own brain: no planner, no scripted
choices, no caretaker. The World is physics and consequences; the Academy turns Zen's experience
into learning; the Sprite of All Knowing answers when Zen asks.

## 1. Principles

- **Every deed is Zen's.** Each motor action is sampled from Zen's brain (the language model it is
  training), restricted to the motor vocabulary. Nothing else moves Zen's body. The only
  involuntary things are physics: Zen collapses asleep when its rest reaches 0 and wakes when rested
  in daylight; cold, hunger and thirst hurt.
- **Learning from consequences.** The World scores each action (reward) from what changed:
  needs relieved or worsened, pain, novelty (new tiles, new kinds of thing, new chunks), answers
  received. The Academy trains the brain with a policy-gradient loss on its own actions, and with the
  ordinary language-model loss on the experience text, so Zen also learns to predict what its actions
  lead to.
- **Words and deeds in one stream.** Zen's experience is one text stream: what it perceives, what it
  thinks, what it does and what happens. Its thoughts sit in the same context as its actions, so
  language can come to steer the body.
- **No LLM cost unless Zen asks.** The only language model is the Sprite (llama.cpp, CPU), used only
  when Zen asks a question (and when you ask it from its tab).

## 2. Tokens

Role tokens (ids unchanged from v3; two renamed):
`<|endoftext|> <|thought|> <|user|> <|mind|> <|oracle|> <|world|> <|intent|> <|act|>`
- `<|act|>` (was `<|npc|>`) precedes one motor word.
- `<|oracle|>` precedes the Sprite's answer. `<|mind|>` precedes what Zen says or asks.
- `<|world|>` precedes a perception or a consequence. `<|thought|>` precedes an inner thought.
- `<|intent|>` is unused (kept for old minds).

Motor vocabulary (each a single fineweb32k token with a leading space):

| word | effect |
|---|---|
| forward | step one tile ahead (blocked by water deeper than wading, trees, rock, walls) |
| back | step one tile back, keeping the facing |
| left / right | turn 90° |
| wait | do nothing for one beat |
| take | pick up the takeable thing ahead or underfoot (hands hold up to 4 things) |
| drop | put down the last thing held |
| eat | eat the edible thing held (or underfoot/ahead, e.g. berries on a bush) |
| drink | drink from water ahead/underfoot or a held water vessel |
| use | use the thing ahead (open a chest, read a book, light the fire with a held flint, sit, play the piano, paint at the easel, chop a tree with a held axe, fill a held bucket…) |
| sleep | lie down and sleep (wakes when rested, or by morning) |
| look | look around: a longer description of everything in sight |
| speak | say something aloud: Zen's brain writes the words (heard by you if near) |
| ask | ask the Sprite a question: Zen's brain writes the question; Zen's body waits for the answer |

The World also returns `ok=false` with a reason ("A tree is in the way.") for actions that don't work.

## 3. The World (`ada/world/`)

### 3.1 Terrain (`terrain.py`)
- Endless, deterministic from `seed`. Tiles are integer (x, y), any value. Chunks are 32×32
  (`cx = x // 32`).
- Fields from fractal value noise: elevation, moisture, temperature (latitude-free; varies with
  noise and elevation). Biomes: `ocean`, `lake`, `beach`, `meadow`, `grassland`, `forest`,
  `pine_forest`, `jungle`, `swamp`, `desert`, `savanna`, `tundra`, `snow`, `mountain`, `rock`.
  Rivers carve along noise ridges. Water depth: `shallow` (wadeable), `deep` (blocked).
- Static features per tile (part of chunk data, not entities): trees (by biome: oak, birch, pine,
  palm, cactus, jungle tree, dead tree), bushes (berry bush, plain), rocks/boulders, tall grass,
  flowers, reeds, snow drifts. A feature may be removed or changed (a felled tree becomes a
  stump); such changes are stored as chunk diffs.
- Points of interest, placed by hashed chance per chunk: ruins (stone walls, a chest, books with
  real text, tools), an abandoned cabin, a cave mouth, standing stones, a spring, a lookout hill,
  a beehive, a bird's nest, an old well. Each has a generated name ("the Grey Ruins").
- **Home**: a small cabin at the origin (bed, fireplace, wood, flint, table, bookshelf with a few
  books, easel with paper, piano, chest with a cup, bucket, axe), on meadow near water.

### 3.2 Things and beings (`sim.py`)
- Entities (takeable things and placed objects): `{id, kind, x, y, ...state}` generated per chunk on
  first load (berries, apples under trees, mushrooms, sticks, stones, flint, clay, feathers, shells,
  eggs in nests, honey, fish in water…), kept in a chunk index; removed/added ones persist.
- Animals (in loaded chunks only): deer, rabbit, fox, bird, fish, frog (night), owl (night),
  fireflies (summer nights), bees near hives, bear (rare, far from home, avoids Zen unless
  cornered). They wander, flee when Zen comes close, sleep at night/day by species.
- **Zen's body**: x, y, facing (0=N,1=E,2=S,3=W), hands (list of held entities, max 4), needs 0–100:
  `energy` (food), `water`, `rest`, `warmth`, `health`; derived feelings. Wet in rain/swimming,
  dries by fire or sun. Warmth follows the air temperature (biome, elevation, time, weather,
  shelter, fire nearby). Health drops when energy, water or warmth is near 0 and slowly recovers
  otherwise. At health 0 Zen faints and wakes at home (the cabin), hands empty: a big negative
  reward, not death.
- **The Sprite**: a small glowing being always within 1–2 tiles of Zen (it floats along; never
  blocks). State: `idle | listening | answering`. It never acts on the World.
- **You (the visitor)**: as before: walk, say, give a held thing, place things from a list.
- Day/night (`day_minutes`, `night_minutes`), seasons (a season per 4 days), weather (clear,
  cloudy, rain, storm, snow, fog, wind) per region over time, temperature.
- Light: darkness limits sight at night except near fire, a lit lantern held, or moonlight.

### 3.3 Senses (`perceive`)
Egocentric, short, deterministic English (the words the brain must learn), e.g.
`Forest, morning, cool, light rain. Ahead: an oak tree. Left: grass. Right: a stream. Here: grass.
I see a berry bush 2 ahead and 1 left, a deer 5 to the right. I hold a stick. I am hungry.`
- `perceive()` ≤ ~45 words. `look()` returns a fuller description (≤ ~120 words) including
  named places in sight and what things are.
- Consequence texts for actions: `I step forward.`, `I take the berries.`, `A tree is in the way.`,
  `I drink the cold water. I am less thirsty.`, `I read the book. It says: "…"` (book text in full).

### 3.4 Rewards (`act` returns them)
`reward = 0.6·Δwellbeing + novelty + pain + events`, where wellbeing is a weighted mean of needs
(health counts double), novelty: new tile +0.01, new kind of thing seen +0.25, new chunk +0.1, new
named place +0.5; pain: blocked −0.02, failed action −0.01, health loss −0.2/point; events:
answer received +0.4, first time doing an action successfully +0.3, eating when hungry/drinking
when thirsty are already in Δwellbeing. Rewards are per action and also accumulate between actions
(e.g. getting colder while waiting).

### 3.5 Interface used by Life
```
w = World(seed)                       # or World.from_state(dict)
w.advance(dt)                         # time, weather, animals, physiology, sprite follows
r = w.act(word)                       # -> {"ok": bool, "text": str, "reward": float, "events": [..]}
w.perceive() -> str; w.look() -> str
w.reward_since_last()                 # passive reward accumulated by advance() since last call
w.zen                                 # body (x, y, facing, hands, needs, sleeping, said, activity)
w.sprite                              # {x, y, state, said}
w.wellbeing() -> float; w.feelings() -> list[str]
w.time_of_day(), w.day, w.phase ("day"|"night"), w.season, w.weather
w.snapshot(full: bool) -> dict        # §5
w.chunk_payload(cx, cy) -> dict       # §5
w.atlas() -> dict                     # §5
w.state() -> dict; World.from_state(d)
w.visitor_* (join, leave, move, say, give, place)
w.creations / w.create(...)           # art Zen makes with `use` at the easel/piano
```

### 3.6 Ontology
`ada/ontology.py` keeps `K(...)`, `KINDS` and `triples(synth)` (facts for the concept graph),
describing every kind in the new world (biomes and features too), `GENERAL_FACTS`.

## 4. Life (`ada/life.py`): Zen's control loop
- Every motor beat (0.5 s of world time while awake and not waiting for the Sprite): append
  `<|world|> perception` to Zen's stream if it changed, then `<|act|>` and sample the next token
  from the brain's logits restricted to the 14 motor words (temperature `motor_temperature`,
  default 1.0). Run it on the brain thread (KV cache over a rolling window).
- Append the consequence `<|world|> text` to the stream. Record `(position, action, reward)`.
- Thoughts: as before, every `thought_seconds`, `<|thought|>` + generated text into the same stream.
- `speak`: generate `<|mind|>` text (≤ `reply_tokens`) → said aloud; `ask`: generate `<|mind|>`
  question → sent to the Sprite; motor beats pause until the answer (`<|oracle|> answer`) arrives,
  thoughts continue; then reward +0.4.
- Every 64 motor beats (and at sleep), the segment is written to `minds/<name>/experience.jsonl`:
  `{t, ids: [...], acts: [[pos, action_index, advantage], ...], ret, steps}` where advantages are
  discounted returns (γ=0.95) minus a running baseline, normalised by a running std.
- Chats with you: Zen answers with its brain as before.

## 5. Messages to the page
`world` snapshot (full, then deltas merged by the Hub as now):
```
{tick, day, phase, season, weather, time, light, sun, temperature,
 zen: {x, y, fx, fy, facing, needs, feelings, hands:[kind], sleeping, activity, said, waiting, biome, place},
 sprite: {x, y, fx, fy, state, said},
 visitor: {...} | null,
 ents: [ {id, kind, x, y, ...} ] (within 48 tiles of Zen or you), removed: [id],
 animals: [ {id, kind, x, y, fx, fy, facing, state} ],
 home: {x, y}, places: [ {name, kind, x, y} ] (known),
 mind: {...as before: plan→"", motor: {last, autonomy:1, entropy, reward_rate, steps}},
 creations: [...] (new ones), skills, log}
```
Chunks: `GET /api/chunk?cx=&cy=` → `{cx, cy, size: 32, h: [1024 ints, decimetres], biome: [1024
ints → BIOMES list], water: [1024: 0 none, 1 shallow, 2 deep, 3 river], feat: [1024 ints → FEATURES
list, 0 none], meta: {pois: [{kind, name, x, y}]}}` plus `GET /api/world_meta` → `{BIOMES, FEATURES,
seed, home}`. Atlas: `GET /api/atlas` → `{explored: [[cx, cy, biome_index]...], places: [...], trail:
[[x, y]...], zen: {x, y}, home: {x, y}}`.

## 6. Academy
- Pools: FineWeb, journal (Zen's own talk/answers), concept drills, **experience**.
- Experience segments are trained with the LM loss (world model) and, on `<|act|>` positions, a
  policy-gradient loss: `−A·log π(a)` where π is the softmax over the 14 motor-word logits, plus a
  small entropy bonus. Mixed into every training step with weight `mix_experience`.
- Metrics: policy loss, mean advantage, action entropy; published with the brain.

## 7. The page
Tabs: Home (3D world + overlay), Zen (journey, body, skills, motor stats), Thoughts, Conversations
(with you, with the Sprite), Atlas (explored map), Keepsakes, Academy, Concepts, Sprite (model,
its answers, ask it yourself), Settings, Health.

## 8. The studio: art made from scratch, one mark at a time

Zen makes art the way it moves: its brain chooses every mark, one word at a time, from a small
vocabulary (constrained decoding, exactly like the motor words). No templates, no composers, no
premade strokes. The World only provides the instrument; `ada/world/studio.py` holds the rules,
which the page re-implements exactly so it can replay any piece as a time-lapse.

`use` facing the **easel** (with paper), the **piano**, a **clay** lump held (sculpting) or the **desk**
(with paper, writing) returns `{"ok": true, "text": "...", "needs_words": "paint"|"compose"|"sculpt"|"write"}`
and Zen enters a creative session; motor beats pause until the session ends (`done`, the step limit,
or Zen falling asleep/fainting).

### Painting (vocabulary `PAINT`)
Canvas 64×48 cells, all paper (`.`) at first. Cursor starts at (32, 24), pen up, colour black, size 1.
Words: `up down left right` (move 1 cell; clamp to the canvas; if the pen is down, paint every cell
moved onto), `jump` (move 6 cells in the last direction moved, painting along if the pen is down;
the last direction starts as `right`), `press` (pen down and paint the cursor cell), `lift` (pen up), `dot` (paint the cursor cell, pen unchanged),
`big` (brush 3×3 centred on the cursor) / `small` (brush 1 cell), colours `black white red orange
yellow green blue purple pink brown grey gold` (palette index 0–11, see `studio.PALETTE`), `done`.
Painting a cell with the 3×3 brush paints the 3×3 square clipped to the canvas. Max 900 words.
Data: `{"v": 3, "w": 64, "h": 48, "palette": [12 hex], "pixels": "<3072 chars: '.' or 0-9,a,b>",
"ops": "<one char per word, see studio.PAINT_CODES>", "skill", "score": {...}}`.

### Music (vocabulary `MUSIC`)
Words: `C D E F G A B` (play that note in the current octave for the current length), `high` / `low`
(octave up/down, octaves 3–6, start 4), `long` (length 2 beats) / `short` (½ beat) — the length
stays until changed; `rest` (silence for the current length), `fast` / `slow` (tempo ±12, 60–180,
start 100), `done`. Max 200 words. Data: `{"v": 3, "tempo": n, "notes": [[midi or -1, beats], ...],
"tempo_changes": [[note_index, tempo], ...], "ops": "...", "score": {...}}`. Played on the piano.

### Sculpture (vocabulary `SCULPT`)
A 12×12×12 grid, empty. Cursor at (6, 0, 6) (x, y up, z). Words: `up down left right in out`
(move 1, clamped), `add` (put clay at the cursor), `cut` (remove clay at the cursor), `smooth`
(fill empty cells that have ≥4 clay neighbours among the 6 around the cursor's 3×3×3 block), `done`. Max 600 words. Clay
that isn't supported (nothing below it, down to the floor, through clay) still stays: it is a sculpture.
Data: `{"v": 3, "n": 12, "voxels": "<1728 chars '0'/'1', index x + 12*(z + 12*y)>", "material", "ops", "score"}`.

### Writing
At the desk Zen's brain writes freely (`<|mind|>` text, up to 120 tokens): a poem or a note.

### What Zen learns from it
Each word in a session is an action in the experience stream (vocabulary recorded with it). At the end
**the Sprite judges the piece with its own eyes and ears**: its model (Qwen 2.5 Omni 3B through
llama.cpp with its vision+audio projector, on the CPU) is shown the painting or the sculpture as a
picture (`world/render.py` makes the PNG) or hears the song (a WAV), and replies with a score (0–10),
what it sees or hears, and a few words to Zen. Zen hears those words (`<|oracle|>` in its stream), so it
also learns how its work is described. The reward for every mark of the session is
`2·(quality − Zen's running average for that medium)`, with `quality = 0.75·Sprite score/10 + 0.25·intrinsic`.
Writing is judged from its text. When the Sprite is off, slow (> 10 min) or can't see, the studio's
intrinsic measures stand in alone (no notion of what a picture "should" be):
- painting: coverage in a pleasant range, colour variety and harmony, contrast, balance, structure
  (edges, connected shapes, some symmetry or repetition), difference from Zen's earlier paintings;
- music: melodic steps mostly small with some leaps, motifs that repeat and vary, a home note, a
  range, rhythmic variety, length;
- sculpture: mass in a sensible range, connected, standing on the floor, volume variety, symmetry.
The score (0–1), relative to Zen's running average for that medium, is the reward for the session.
You can **love** a piece on the Keepsakes tab: that sends a strong extra reward back to every mark of
that session (`POST /api/love {id}`), so your taste can teach Zen too.
While Zen works, the snapshot carries `studio: {medium, w, h, pixels | notes | voxels, cursor, color,
size, pen, steps}` (pixels/notes/voxels only every 1 s, cursor every tick) so the page can show the piece growing live.
