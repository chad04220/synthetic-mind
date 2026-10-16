"""Tests for the v4 World: terrain, physics, senses, rewards, persistence and the page schema."""
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ada.ontology import BIOME_KIND, FEATURE_KIND, KINDS, triples  # noqa: E402
from ada.world import terrain as T  # noqa: E402
from ada.world.sim import MOTOR, PLACEABLE, World  # noqa: E402
from ada.world.terrain import BIOMES, FEATURES, F, Terrain  # noqa: E402


def put(w, x, y, facing):
    """Move Zen by hand; what is new there is noticed now, so it does not count in the next reward."""
    w.zen.x, w.zen.y, w.zen.facing = x, y, facing
    w._ensure_area()
    w._notice()


def kinds_at(w, x, y):
    return [e["kind"] for e in w.at(x, y)]


# ---------------------------------------------------------------------- terrain
def test_same_seed_same_chunk():
    a, b = Terrain(5), Terrain(5)
    for cx, cy in ((0, 0), (3, -2), (-40, 17), (1000, -999)):
        assert a.payload(cx, cy) == b.payload(cx, cy)
        assert a.spawns(cx, cy) == b.spawns(cx, cy)
    assert Terrain(6).payload(3, -2)["h"] != a.payload(3, -2)["h"]


def test_chunk_generation_is_fast():
    t = Terrain(123)
    t0 = time.perf_counter()
    n = 0
    for cx in range(50, 60):
        for cy in range(-3, 0):
            t.chunk(cx, cy)
            n += 1
    assert (time.perf_counter() - t0) / n < 0.040


def test_biome_variety_over_a_large_area():
    t = Terrain(11)
    seen = set()
    for cx in range(-300, 300, 30):
        for cy in range(-300, 300, 30):
            seen.update(t.chunk(cx, cy).biome)
    names = {BIOMES[b] for b in seen}
    assert len(names) >= 13, names


def test_home_is_a_cabin_on_a_meadow_by_water():
    w = World(3)
    ter = w.terrain
    assert BIOMES[ter.biome(0, 0)] == "meadow"
    assert ter.feature(0, 3) == F["door"] and ter.feature(-4, 0) == F["wall"] and ter.feature(0, 0) == F["floor"]
    assert any(ter.water(x, y) for x in range(-15, 16) for y in range(-15, 16))
    kinds = [e["kind"] for x in range(-4, 5) for y in range(-3, 5) for e in w.at(x, y)]
    for k in ("bed", "fireplace", "woodpile", "flint", "table", "bookshelf", "easel", "piano", "desk", "chest",
              "bucket", "axe"):
        assert k in kinds, k
    shelf = next(e for e in w.at(-3, -2) if e["kind"] == "bookshelf")
    assert len(shelf["items"]) >= 3 and all(i["kind"] == "book" for i in shelf["items"])
    chest = next(e for e in w.at(-3, -1) if e["kind"] == "chest")
    assert "cup" in [i["kind"] for i in chest["items"]]
    assert next(e for e in w.at(3, -2) if e["kind"] == "easel")["paper"] >= 1
    # every seed gets the same home
    assert kinds_at(World(99), 0, -2) == ["fireplace"]


def test_points_of_interest_have_names_and_lie_inside_their_chunk():
    t = Terrain(11)
    pois = []
    for cx in range(-8, 8):
        for cy in range(-8, 8):
            for p in t.chunk(cx, cy).pois:
                assert p["x"] >> 5 == cx and p["y"] >> 5 == cy
                pois.append(p)
    kinds = {p["kind"] for p in pois}
    assert len(pois) > 20 and len(kinds) >= 7
    assert all(p["name"] for p in pois)


# ---------------------------------------------------------------------- acting
def test_every_motor_word_returns_a_result():
    for word in MOTOR:
        w = World(11)
        r = w.act(word)
        assert set(r) >= {"ok", "text", "reward", "events"}, word
        assert isinstance(r["text"], str) and -1.0 <= r["reward"] <= 1.0
        if word in ("speak", "ask"):
            assert r["ok"] and r["text"] == "" and r["needs_words"] == word
        if not r["ok"]:
            assert r["text"], word
    w = World(11)
    assert w.act("fly")["ok"] is False


def test_moving_and_turning():
    w = World(11)
    put(w, 0, 0, 2)
    assert w.act("forward")["text"] == "I step forward." and (w.zen.x, w.zen.y) == (0, 1)
    assert w.act("back")["ok"] and (w.zen.x, w.zen.y) == (0, 0) and w.zen.facing == 2
    w.act("left")
    assert w.zen.facing == 1
    w.act("right"), w.act("right")
    assert w.zen.facing == 3


def test_blocked_movement():
    w = World(11)
    put(w, -3, 0, 3)                 # a wall to the west
    w.act("wait")
    r = w.act("forward")
    assert r["ok"] is False and r["text"] == "A wall is in the way." and r["reward"] < 0
    assert (w.zen.x, w.zen.y) == (-3, 0)
    put(w, 0, -1, 0)
    assert w.act("forward")["text"] == "The fireplace is in the way."


def test_taking_eating_and_drinking_change_needs():
    w = World(11)
    put(w, 1, 1, 1)                  # the table, with apples and a flint, is to the east
    r = w.act("take")
    assert r["ok"] and r["text"].startswith("I take the") and len(w.zen.hands) == 1
    while w.act("take")["ok"]:
        pass
    assert {e["kind"] for e in w.zen.hands} >= {"apple", "flint"}
    w.zen.needs["energy"] = 30.0
    r = w.act("eat")
    assert r["ok"] and "I eat the apple." in r["text"] and w.zen.needs["energy"] > 30 and r["reward"] > 0
    w.zen.needs["energy"] = 99.0
    r = w.act("eat")
    assert r["ok"] is False and r["text"] == "I am too full to eat."
    put(w, 1, 4, 1)                  # the rain barrel by the door
    w.zen.needs["water"] = 20.0
    r = w.act("drink")
    assert r["ok"] and w.zen.needs["water"] == 50.0 and r["reward"] > 0
    put(w, 0, 0, 2)
    assert w.act("drink")["text"] == "There is no water here."


def test_poison_and_hands_limit():
    w = World(11)
    w.firsts.update(MOTOR)
    put(w, 0, 6, 2)
    t = w.make("toadstool")
    w.zen.hands.append(t)
    w.zen.needs["energy"] = 50
    h = w.zen.needs["health"]
    r = w.act("eat")
    assert "I feel sick." in r["text"] and w.zen.needs["health"] < h and r["reward"] < 0
    for _ in range(4):
        w.zen.hands.append(w.make("stone"))
    w.place(w.make("stick"), 0, 7)
    assert w.act("take")["text"] == "My hands are full."
    assert w.act("drop")["text"] == "I drop the stone."


def test_fire_warms_the_cabin_and_books_are_read():
    w = World(11)
    w.day = 13                       # winter
    put(w, 0, -1, 0)
    cold = w.air_temp(0, 0)
    w.zen.hands.append(w.make("flint"))
    r = w.act("use")
    assert r["ok"] and "fire burns" in r["text"]
    assert w.air_temp(0, 0) >= 21 > cold
    w.zen.hands.append(w.make("raw fish"))
    r = w.act("use")
    assert r["ok"] and "cooked fish" in r["text"]
    put(w, -2, -2, 3)
    r = w.act("use")
    assert r["ok"] and r["text"].startswith('I read "') and len(r["text"]) > 150


def test_chop_tree_and_studio():
    w = World(11)
    put(w, -8, -3, 0)                # an apple tree at (-8, -4)
    assert w.act("use")["text"].startswith("I need an axe")
    w.zen.hands.append(w.make("axe"))
    for _ in range(3):
        r = w.act("use")
    assert "It falls!" in r["text"] and w.terrain.feature(-8, -4) == F["stump"]
    assert kinds_at(w, -8, -4).count("log") == 2
    put(w, 3, -1, 0)
    r = w.act("use")
    assert r["ok"] and r["needs_words"] == "paint"
    put(w, 2, -1, 0)
    assert w.act("use")["needs_words"] == "compose"
    put(w, 2, 0, 1)
    assert w.act("use")["needs_words"] == "write"
    w.zen.hands.append(w.make("clay"))
    put(w, 0, 0, 2)
    r = w.act("use")
    assert r["needs_words"] == "sculpt" and not any(e["kind"] == "clay" for e in w.zen.hands)
    w.set_studio({"medium": "painting", "w": 64, "h": 48, "cursor": [32, 24]})
    w.snapshot(True)
    assert "studio" not in w.snapshot(False)
    w.set_studio({"medium": "painting", "cursor": [33, 24]})
    assert w.snapshot(False)["studio"]["cursor"] == [33, 24]
    c = w.create("painting", "Zen", {"v": 3, "pixels": "."}, "Dots")
    assert c["id"] == 1 and w.love(1)["loves"] == 1
    w2 = World.from_state(json.loads(json.dumps(w.state())))
    assert w2.creations[0]["title"] == "Dots" and w2.creations[0]["loves"] == 1


def test_novelty_rewards():
    w = World(11)
    put(w, 0, 2, 2)
    r1 = w.act("forward")            # out of the door: a new tile and many new kinds of thing
    assert r1["reward"] > 0.2 and any(e["kind"] == "new_kind" for e in r1["events"])
    w.act("back")
    r2 = w.act("forward")            # nothing new now
    assert r2["reward"] < 0.02
    w.zen.x, w.zen.y = 9, 7          # near the Home Pond
    r = w.act("wait")
    assert "I find the Home Pond." in r["text"] and r["reward"] >= 0.5


def test_faint_and_wake_at_home():
    w = World(11)
    put(w, 5, 10, 2)
    w.zen.hands.append(w.make("stone"))
    w.zen.needs.update(health=0.05, water=0.0)
    w.reward_since_last()
    for _ in range(4):
        w.advance(0.5)
    assert (w.zen.x, w.zen.y) == (-3, 1) and w.zen.hands == [] and w.faints == 1
    assert "stone" in kinds_at(w, 5, 10)
    assert w.reward_since_last() <= -1.0
    assert not w.zen.sleeping and w.zen.needs["health"] > 0


def test_involuntary_sleep_and_waking():
    w = World(11)
    put(w, 0, 6, 2)
    w.zen.needs["rest"] = 0.01
    w.advance(0.5)
    assert w.zen.sleeping and w.act("forward")["text"] == "I am asleep."
    assert w.perceive() == "I am asleep."
    n = 0
    while w.zen.sleeping and n < 20000:
        w.advance(0.5)
        n += 1
    assert not w.zen.sleeping and w.phase == "day" and w.zen.needs["rest"] >= 60
    w.zen.needs["rest"] = 95
    assert w.act("sleep")["text"] == "I am not tired."


def test_sprite_follows_zen():
    w = World(11)
    put(w, 0, 6, 2)
    for i in range(30):
        w.act("forward" if i % 5 else "left")
        for _ in range(4):
            w.advance(0.25)
        s = w.sprite
        assert max(abs(s.x - w.zen.x), abs(s.y - w.zen.y)) <= 2
    w.sprite_state("answering"), w.sprite_say("Water is wet.")
    snap = w.snapshot(True)["sprite"]
    assert snap["state"] == "answering" and snap["said"] == "Water is wet."


def test_perception_is_short_and_deterministic():
    a, b = World(11), World(11)
    rng = random.Random(4)
    for _ in range(300):
        word = rng.choice(["forward", "forward", "left", "right", "take", "back"])
        a.act(word), b.act(word)
        pa, pb = a.perceive(), b.perceive()
        assert pa == pb
        assert len(pa.split()) <= 50, pa
        assert len(a.look().split()) <= 125, a.look()
    p = a.perceive()
    assert "Ahead:" in p and "Left:" in p and "Right:" in p and "Here:" in p


def test_state_round_trip_keeps_changes():
    w = World(11)
    w.zen.hands.append(w.make("axe"))
    put(w, -8, -3, 0)
    for _ in range(3):
        w.act("use")                  # fell the apple tree
    w.zen.hands.clear()
    put(w, -5, 6, 3)                 # a berry bush at (-6, 6)
    assert w.act("take")["text"] == "I pick some berries from the berry bush."
    put(w, 1, 1, 1)
    w.act("take")                    # an apple off the table
    for _ in range(50):
        w.advance(0.5)
    s = json.loads(json.dumps(w.state()))
    w2 = World.from_state(s)
    assert w2.terrain.feature(-8, -4) == F["stump"]
    assert not w2.has_fruit(-6, 6)
    assert [e["kind"] for e in w2.zen.hands] == [e["kind"] for e in w.zen.hands]
    assert kinds_at(w2, 2, 1).count("apple") == kinds_at(w, 2, 1).count("apple") == 1
    assert kinds_at(w2, -8, -4).count("log") == 2
    assert (w2.day, w2.phase, w2.zen.x, w2.zen.y) == (w.day, w.phase, w.zen.x, w.zen.y)
    assert w2.perceive() == w.perceive()
    assert w2.terrain.payload(-1, -1)["feat"][((-4) & 31) * 32 + ((-8) & 31)] == F["stump"]
    assert len(json.dumps(s)) < 200_000


def test_snapshot_schema():
    w = World(11)
    w.visitor_join()
    s = w.snapshot(True)
    for k in ("tick", "day", "phase", "season", "weather", "time", "light", "sun", "temperature", "zen", "sprite",
              "visitor", "ents", "removed", "animals", "home", "places", "mind", "creations", "skills", "log"):
        assert k in s, k
    for k in ("x", "y", "fx", "fy", "facing", "needs", "feelings", "hands", "sleeping", "activity", "said",
              "waiting", "biome", "place"):
        assert k in s["zen"], k
    for k in ("x", "y", "fx", "fy", "state", "said"):
        assert k in s["sprite"]
    assert s["mind"]["motor"]["autonomy"] == 1
    assert all({"id", "kind", "x", "y"} <= set(e) for e in s["ents"])
    assert all(max(abs(e["x"]), abs(e["y"])) <= 50 for e in s["ents"])
    assert all({"id", "kind", "x", "y", "fx", "fy", "facing", "state"} <= set(a) for a in s["animals"])
    assert len(json.dumps(s)) <= 80_000
    d = w.snapshot(False)
    assert d["ents"] == [] and d["removed"] == []
    put(w, 1, 1, 1)
    w.act("take")
    d = w.snapshot(False)
    assert len(d["removed"]) == 1 and d["zen"]["hands"]


def test_chunk_payload_and_atlas():
    w = World(11)
    p = w.chunk_payload(0, 0)
    assert p["size"] == 32 and (p["cx"], p["cy"]) == (0, 0)
    for k in ("h", "biome", "water", "feat"):
        assert len(p[k]) == 1024 and all(isinstance(v, int) for v in p[k])
    assert max(p["biome"]) < len(BIOMES) and max(p["feat"]) < len(FEATURES) and set(p["water"]) <= {0, 1, 2, 3}
    assert any(q["kind"] == "home" for q in p["meta"]["pois"])
    put(w, 0, 6, 2)
    for _ in range(5):
        w.act("forward")
    a = w.atlas()
    assert {"explored", "places", "trail", "zen", "home"} <= set(a)
    assert all(len(e) == 3 for e in a["explored"]) and a["zen"] == {"x": w.zen.x, "y": w.zen.y}
    assert w.world_meta()["BIOMES"] == BIOMES


def test_visitor():
    w = World(11)
    put(w, 0, 6, 2)
    v = w.visitor_join()
    w.visitor_move(0, 7, 2)
    assert (v.x, v.y) == (0, 7)
    e = w.visitor_place("apple", 1, 7)
    assert e and w.visitor_take(e["id"]) is e
    assert w.visitor_give() is e and w.zen.hands[-1] is e
    assert w.visitor_say("hello") is True
    assert w.heard("hi there") is True
    assert w.visitor_place("dragon", 1, 7) is None
    assert set(PLACEABLE) <= set(KINDS)
    w.visitor_leave()
    assert w.visitor is None


def test_answer_reward_and_passive_reward():
    w = World(11)
    w.reward_since_last()
    w.answer_arrived()
    assert abs(w.reward_since_last() - 0.4) < 0.05
    w.zen.needs["energy"] = 0.0
    for _ in range(40):
        w.advance(0.5)
    assert w.reward_since_last() < 0


def test_day_night_and_seasons():
    w = World(11)
    assert w.phase == "day" and w.season == "spring"
    for _ in range(int((w.day_seconds + w.night_seconds) / 5) + 2):
        w.advance(5.0)
    assert w.day == 2 and w.phase == "day"
    w.advance(1.0, day_seconds=60, night_seconds=60)
    assert w.day_seconds == 60
    w.day = 5
    assert w.season == "summer"
    assert w.weather in ("clear", "cloudy", "rain", "storm", "snow", "fog", "wind")


def test_timing_budgets():
    w = World(11)
    w.visitor_join()
    for _ in range(50):
        w.advance(0.25)
    t0 = time.perf_counter()
    for _ in range(400):
        w.advance(0.25)
    assert (time.perf_counter() - t0) / 400 < 0.003
    rng = random.Random(1)
    t0 = time.perf_counter()
    for _ in range(300):
        w.act(rng.choice(["left", "right", "take", "drop", "use", "eat", "drink", "wait"]))
    assert (time.perf_counter() - t0) / 300 < 0.002
    t0 = time.perf_counter()
    for _ in range(200):
        w.advance(0.25)
        w.snapshot(False)
    assert (time.perf_counter() - t0) / 200 < 0.004


def test_ontology_covers_the_world():
    for name in FEATURES[1:]:
        assert FEATURE_KIND[name] in KINDS, name
    for name in BIOMES:
        assert BIOME_KIND[name] in KINDS, name
    for k, v in KINDS.items():
        assert {"noun", "glyph", "is_a", "color", "props"} <= set(v), k
        if v.get("fruit"):
            assert v["fruit"] in KINDS
        if v.get("cooks_to"):
            assert v["cooks_to"] in KINDS
    facts = triples()
    assert ("Zen", "is a", "synth") in facts and len(facts) > 300
    assert ("toadstool", "is", "poisonous") in facts
    assert len(T.BOOKS) >= 25


def test_boredom_grows_with_sameness_and_fades_with_new_things():
    w = World(11)
    b0 = w.zen.needs["boredom"]
    rewards = [w.act("wait")["reward"] for _ in range(20)]
    assert w.zen.needs["boredom"] > b0 + 20 and sum(rewards) < 0        # waiting around is dull and feels bad
    for _ in range(15):
        w.act("left")                                                    # turning in circles: still dull
    w.amuse(50)
    bored = w.zen.needs["boredom"]
    w.advance(120)
    assert w.zen.needs["boredom"] > bored                               # time with nothing new makes it worse
    assert "bored" in " ".join(w.feelings()) or w.zen.needs["boredom"] <= 60
    w.amuse(30)
    assert w.zen.needs["boredom"] < bored                                # making things or hearing answers helps
    fresh = World(11)                                                    # going somewhere new helps too:
    fresh.zen.needs["boredom"] = 40.0                                    # out of the cabin and into the forest
    for _ in range(8):
        assert fresh.act("forward")["ok"]
    assert fresh.zen.needs["boredom"] < 10
    for _ in range(12):                                                  # but bumping round the same trees bores
        if not fresh.act("forward")["ok"]:
            fresh.act("right")
    circling = fresh.zen.needs["boredom"]
    for _ in range(12):
        if not fresh.act("forward")["ok"]:
            fresh.act("right")
    assert fresh.zen.needs["boredom"] > circling


def test_real_deeds_are_rewarded_and_repeating_them_counts_less():
    w = World(11)
    gains = []
    for _ in range(4):
        w.zen.needs["energy"] = 85.0                    # the same small hunger each time
        w.zen.hands.append(w.make("apple"))
        r = w.act("eat")
        assert r["ok"]
        gains.append(r["reward"])
    assert gains[0] > 0.1 and gains[1] > gains[2] > gains[3]           # repeating a deed soon after counts less
    assert w._deed("drink", "sea", "I drink the sea water.") == 0.0       # not every deed is worth something
    v1 = w._deed("use", "book", 'I read "Fables".')
    v2 = w._deed("use", "book", 'I read "Fables".')
    assert v1 == 0.5 and v2 < v1
    assert w._deed("use", "flint", "I strike the flint. A spark catches and the fire burns.") == 0.6
