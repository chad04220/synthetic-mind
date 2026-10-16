# Synthetic Mind v5: a living voxel world, and a fast mind inside it

A deep, fully editable voxel sandbox, and one inhabitant: a small pretrained language model running
on your GPU with llama.cpp, which perceives the world, decides, acts and talks, fast. You can talk
to it, and you can walk into its world and dig, build and hand it things.

No Academy: the GPU belongs to the inhabitant's model (low latency) and the browser, except while it
practises (§3.4), when its model server is stopped and the GPU trains its adapter.

## 1. Processes
- **Hub** (FastAPI, no torch): serves the page, carries messages, runs the model server (llama.cpp
  on the GPU: CUDA on Windows with an NVIDIA card, Vulkan elsewhere, CPU as a fallback), supervises.
- **World** (Python + numpy): the voxel simulation at 20 ticks a second, the inhabitant's body and
  skills, and its mind loop (which calls the model through the Hub's model server URL directly over
  HTTP, so a decision never waits on the Hub's message queue).

## 2. The world (`ada/vox/`)
### 2.1 Blocks (`blocks.py`)
A registry of ~100 block types, each with: `id` (uint16), `name`, `color` (hex) and optional
`colors` (top/side/bottom), flags `solid`, `transparent`, `liquid`, `gravity` (falls), `flammable`,
`burn_time`, `light` (0–15 emitted), `hardness` (seconds by hand), `tool` (pickaxe/axe/shovel/
hoe/shears/none) and `tool_level`, `drops` (item and count), `soil`, `plant` (growth stages),
`replaceable`, `climbable`, `conductive` (signal), `friction`, `sound`. Categories:
- terrain: air, stone, deepstone, dirt, grass, sand, red sand, gravel, clay, snow, ice, packed ice,
  mud, bedrock, sandstone, granite, basalt, obsidian;
- ores: coal, iron, copper, gold, diamond, redstone-like *spark ore*, crystal;
- life: oak/birch/pine/jungle/acacia logs and leaves, cactus, tall grass, fern, flowers (6
  colours), mushroom (red/brown), sugarcane, pumpkin, melon, wheat/carrot/potato crops (stages),
  saplings, vines, lily pad, moss, coral, kelp, berry bush;
- fluids: water (levels 0–7, source/flowing), lava (levels), steam (short-lived);
- made: planks (per wood), cobblestone, stone bricks, glass, bricks, clay tiles, wool (8 colours),
  torches, lantern, campfire, crafting table, furnace (lit/unlit), chest, door (open/closed,
  upper/lower), ladder, fence, bed, farmland (wet/dry), path, sign (text), lamp (on/off), lever
  (on/off), button, wire (spark dust, powered level), pressure plate, piston (extended), bell,
  bookshelf, hay, scaffolding, TNT, fire.
### 2.2 Items (`items.py`)
Every block is an item; plus tools (wood/stone/iron/diamond pickaxe, axe, shovel, hoe, sword,
shears, bucket (empty/water/lava), flint and steel), materials (stick, coal, iron/copper/gold
ingot, raw ore, diamond, string, leather, feather, bone, wheat, seeds, flour), food (apple, bread,
berries, carrot, potato, baked potato, cooked/raw meat and fish, pumpkin pie, mushroom stew) with
`food` values, and `book` (writable text).
### 2.3 Rules (`sim.py`, block updates on a queue, capped per tick)
- **Gravity:** sand/gravel/snow fall; unsupported blocks of `gravity` type drop as falling blocks.
- **Fluids:** water and lava spread with levels (water 7 steps, lava 3, slower), sources stay,
  two water sources make a new source; water + lava → obsidian (source) or cobblestone (flowing);
  water puts out fire; lava sets flammables near it alight.
- **Fire:** spreads to flammable neighbours by chance, burns them away over their burn time,
  rain puts it out; campfires and torches give light and warmth.
- **Light:** sky light (by day) and block light, propagated per chunk (0–15); used for plant
  growth, mob spawning and darkness in the agent's perception.
- **Plants:** saplings grow into trees, crops grow through stages on farmland (faster when wet,
  near water), grass spreads to dirt in light, leaves decay without a log nearby, cactus/sugarcane
  grow up, berries regrow.
- **Signals:** levers/buttons/pressure plates power wire up to 15 blocks; powered lamps light,
  doors open, pistons push up to 12 blocks, TNT explodes (crater, drops).
- **Containers and stations:** chests (27 slots), furnace (smelting by fuel time: raw ore →
  ingot, sand → glass, clay → brick, raw food → cooked, logs → charcoal), crafting by recipe
  (shapeless list of inputs → output, ~120 recipes; 2×2 by hand, 3×3 needs a crafting table within
  4 blocks).
- **Time and weather:** day/night (20 min a day by default), moon, rain/snow/thunder, seasons
  optional (off by default), temperature by biome and height.
- **Creatures:** passive (chicken, cow, sheep, pig, rabbit, fish, bee), neutral (wolf, bear),
  night creatures (slime, skeleton-like *hollow*, avoid light); simple AI (wander, flee, follow
  food, attack when hostile), drops. Hostiles can be turned off (`world.peaceful`).
### 2.4 Terrain (`terrain.py`)
Endless in x/z, height 0–255, chunk columns 16×16×256 stored as `uint16` numpy arrays. Biomes from
noise (plains, forest, birch forest, taiga, jungle, desert, savanna, swamp, mountains, snowy
tundra, ocean, beach, river), 3D noise caves and overhangs, ore veins by depth, lakes, rivers,
trees and plants per biome, villages-ruins (a few buildings with chests) and a starting cabin at
spawn. Deterministic from a seed; modified chunks saved compactly (zlib) in `minds/<name>/region/`.
### 2.5 Interface (World process)
```
w = VoxelWorld(seed, folder)
w.tick()                               # 20 Hz: block updates, fluids, fire, plants, creatures, time
w.get(x, y, z) -> id; w.set(x, y, z, id, by=...)    # every change is an event for the page
w.raycast(origin, dir, reach) -> hit
w.chunk_bytes(cx, cz) -> bytes          # zlib(uint16 little-endian, index = x + 16*(z + 16*y))
w.snapshot(full) -> dict                # §4
w.state() / VoxelWorld.load(folder)
```

## 3. The inhabitant (`ada/agent/`)
### 3.1 Body
A 0.6×1.8 block body with position (float), yaw/pitch, velocity, on-ground, health 0–20, food
0–20, air, inventory (36 slots + hand), held item, armour (none in v5.0), xp-free. Physics:
gravity, collision against solid blocks, step-up 0.6, swimming, ladders. Same body type for you
(the visitor), so the page can drive yours.
### 3.2 Skills (fast, deterministic, executed by the World at 20 Hz)
`go_to(x,y,z | entity | "name")` (A* over walkable voxels with jumping, swimming, ladders, and
digging through soft blocks only if allowed), `look_at`, `mine(x,y,z)` / `mine_nearest(block,
count)` (path, equip best tool, break over hardness time, collect drops), `place(block, x,y,z)`,
`build(blueprint)` (a list of relative block placements, done in order with scaffolding where
needed), `craft(item, count)` (fetching from inventory; uses a nearby table if needed), `smelt(item,
count, fuel)`, `use(x,y,z)` (doors, levers, chests open, beds, furnaces), `put/take(chest, item,
count)`, `eat(item)`, `attack(entity)`, `follow(entity, distance)`, `give(entity, item, count)`,
`plant(seed, x,y,z)`, `till`, `harvest`, `sleep`, `say(text)`, `wait(seconds)`, `stop`. Every
skill reports progress and ends with `{ok, result text, details}`; a skill can be interrupted.
### 3.3 Mind (`mind.py`)
- **When it thinks:** whenever a skill ends, when someone speaks to it, when something important
  happens (hurt, hungry, night falls, a creature attacks, its name is said), and at most every
  `idle_seconds` otherwise.
- **What it sees:** a compact observation (≤ ~350 tokens): time/weather/biome/light; its health,
  food, held item and inventory summary; what it is looking at; nearby blocks of interest
  (counted and located relative to it: "oak log ×6 at 4–7 east"), creatures and people with
  distance/bearing; recent events and the last skill result; the conversation so far; its notes
  (a short memory it writes itself) and its current goal.
- **How it decides:** one call to the model with a fixed system prompt (cached), the observation,
  and a JSON schema grammar (llama.cpp `json_schema`), so the reply is always one valid action:
  `{"thought": "...", "say": "..." | null, "action": {"skill": "...", "args": {...}}, "note": "..." | null, "goal": "..." | null}`.
  Latency target: < 250 ms to first action on an 8 GB GPU with a 1–2B model (prompt cache keeps the
  fixed part; only the observation is new).
- **Memory:** its notes (≤ 30 lines, it adds and replaces them), named places (it can name the spot
  it stands on), its goal, the last 12 turns of conversation and the last 20 events, all in the
  observation. Persisted.
- **Talking:** your messages arrive as events and interrupt idle skills; it answers with `say`
  (shown as a chat reply and as a speech bubble in the world). It hears you only within 24 blocks
  when you are in the world, or always through the chat box (configurable: "radio").

### 3.4 Practice (`practice.py`, `ada/coach.py`)
- It knows it can learn: `reflect` (judge recent decisions against their outcomes, write the better
  action for bad ones, keep lessons) and `practice` (train its own model) are skills of its mind, and
  its observation shows how often it has practised and how many of its actions work.
- Every decision is logged with the exact system prompt and observation, the reply and the outcome;
  every judgement (its own, yours) too. Examples: decisions that worked and nobody judged bad (yours
  liked ×2), the better action for ones that went wrong, nothing else; no skill above a third.
- A LoRA adapter (rank 16, all attention and MLP projections) on the original Hugging Face weights,
  loss on the reply tokens only (logits only there), continuing from the previous adapter with older
  examples replayed; exported as a llama.cpp LoRA GGUF and loaded with `--lora`.
- After 30 decisions with a new adapter, their success rate is compared with the previous one's;
  a drop of more than 12 points rolls it back, and it is told.

## 4. Page protocol
- `GET /api/blocks` → the registry (for colours and flags), `GET /api/items`, `GET /api/recipes`.
- `GET /api/chunk?cx=&cz=` → zlib bytes (`application/octet-stream`); the page inflates with
  `DecompressionStream("deflate")`.
- WebSocket `/ws`: init payload, then ~10 Hz `tick` messages with `world` deltas:
  `{t, day, time, weather, light, blocks: [[x,y,z,id], ...] (changes since last), entities:
  [{id, kind, x,y,z, yaw, pitch, name?, said?, held?, health?, anim?}], removed: [ids], agent:
  {..., skill, progress, goal, thought, inventory}, events: [...]}`.
- Commands (POST /api/<name>): `chat {text}`, `visitor {action: join|leave|move|dig|place|use|
  give|drop|select, ...}`, `set {key, value}`, `agent {action: stop|pause|resume}`.
- Archives (Thoughts, Conversations) as in v4.

## 5. The page
Home: first/third-person 3D voxel view (three.js, chunk meshes built in a worker with face culling
and ambient occlusion, a procedural texture atlas, water/lava/glass transparency, sky, sun/moon,
clouds, rain/snow, block light), the inhabitant with name tag, bubble and held item, creatures,
dropped items; your avatar in Visit mode (WASD, jump, sneak, mouse look, left-click dig with
crack animation, right-click place/use, hotbar 1–9 and inventory, give to the inhabitant).
Panels: chat, the inhabitant's mind (thought, goal, current skill with progress, notes, recent
decisions with latency), inventory, a minimap. Tabs: Home, Mind, Conversations, Thoughts, Map,
Settings (model choice and download, latency, world rules), Health.
