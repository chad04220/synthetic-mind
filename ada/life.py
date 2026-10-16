"""The World process: the voxel world at 20 ticks a second, the inhabitant's body and skills, and its mind.

Each tick: commands from the Hub (your chat, your visitor's actions, ratings, practice news), one
world tick (blocks, fluids, creatures, the running skill), then the mind: what happened becomes
events it will see, a decision that streamed in starts its action, a finished action becomes the
outcome of its decision, and when it is time to think, the mind is handed what its body perceives.
Ten times a second the changes go to the Hub for the page.
"""
from __future__ import annotations

import json
import math
import queue
import random
import time
from pathlib import Path

from .agent.mind import Mind
from .config import AdaConfig
from .proc import Link

TICK = 1 / 20
SEND_EVERY = 0.1
SAVE_EVERY = 30.0


def describe_event(e: dict, me: int) -> tuple[str, bool] | None:
    """A world event as the inhabitant would notice it: (text, important), or None if it's not worth it."""
    t, who = e.get("type"), e.get("who")
    mine = who == me
    name = e.get("name") or "someone"
    item = str(e.get("item", "")).replace("_", " ")
    if t == "hurt" and mine:
        return f"You were hurt ({e.get('cause', 'something')}, -{e.get('amount', '?')}).", True
    if t == "died" and mine:
        return f"You died ({e.get('cause', '?')}) and woke up at your spawn point.", True
    if t == "gave" and e.get("to") == me:
        return f"{name} gave you {e.get('count', 1)} {item}.", True
    if t == "joined":
        return f"{name} came into the world.", True
    if t == "left":
        return f"{name} left the world.", False
    if t == "weather":
        return f"The weather turned {e.get('weather')}.", False
    if t == "morning":
        return f"Morning came (day {e.get('day')}).", False
    if t == "tool_broke" and mine:
        return f"Your {item} broke.", True
    if t == "explosion":
        return "Something exploded nearby!", True
    if t == "creature_died" and e.get("by") == me:
        return f"You killed a {e.get('kind')}.", False
    if t in ("broke", "placed") and who not in (None, me) and e.get("name"):
        return f"{name} {'broke' if t == 'broke' else 'placed'} {str(e.get('block', '')).replace('_', ' ')} at " \
               f"{e.get('x')},{e.get('y')},{e.get('z')}.", False
    return None


class World:
    def __init__(self, folder: Path, link: Link | None, cfg: AdaConfig | None = None, threaded: bool = True):
        from .agent.skills import SKILLS
        from .vox.sim import VoxelWorld

        self.folder, self.link = Path(folder), link
        self.cfg = cfg or AdaConfig.load(self.folder / "config.json")
        if not self.cfg.world.seed:
            self.cfg.world.seed = random.randrange(1, 2**31)
            self.cfg.save(self.folder / "config.json")
        c = self.cfg
        self.w = VoxelWorld.open(c.world.seed, self.folder, agent_name=c.name, peaceful=c.world.peaceful,
                                 day_seconds=c.world.day_minutes * 60, sim_radius=c.world.view_chunks, threaded=threaded)
        self.me = self.w.agent.id
        self.mind = Mind(self.folder, c.name, SKILLS, c.mind, log=self.log)
        for k, v in self.mind.places.items():          # its named places are places go_to knows
            self.w.places.setdefault(k, v)
        self.started_actions: queue.SimpleQueue = queue.SimpleQueue()    # (decision, action) from the model thread
        self.running: dict | None = None               # the decision whose action the body is carrying out
        self.practising: dict | None = None            # the decision that asked to practise, while it does
        self.event_seq = self.w._seq
        self.was_night = self.w.is_night()
        self.last_send = self.last_save = self.last_mind = 0.0
        self.mind_sig = None
        self.stopping = False

    # ------------------------------------------------------------------ plumbing
    def log(self, text: str, *a, **k):
        if self.link:
            self.link.log(text)

    def send(self, type_: str, **d):
        if self.link:
            self.link.send(type_, **d)

    def event(self, kind: str, **d):
        self.send("event", kind=kind, **d)

    # ------------------------------------------------------------------ the loop
    def run(self):
        next_t = time.perf_counter()
        self.send_world(full=True)
        while not self.stopping:
            for cmd in self.link.commands():
                self.handle(cmd)
            with self.link.perf.time("world tick"):
                self.w.tick()
            with self.link.perf.time("mind"):
                self.step()
            now = time.perf_counter()
            if now - self.last_send >= SEND_EVERY:
                self.last_send = now
                with self.link.perf.time("snapshot"):
                    self.send_world()
            if now - self.last_save >= SAVE_EVERY:
                self.last_save = now
                self.save(partial=True)
            self.link.maybe_send_perf()
            if not self.link.hub_alive():
                break
            next_t += TICK
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -1.0:
                next_t = time.perf_counter()               # fell far behind: don't try to catch up
        self.save()
        self.w.close()

    def save(self, partial: bool = False):
        self.w.save(partial=partial)
        self.mind.save()

    def send_world(self, full: bool = False):
        snap = self.w.snapshot(full)
        if full:
            snap["full"] = True
        self.send("world", snap=snap)
        sig = (self.mind.thinking, self.mind.busy_with, len(self.mind.recent), self.mind.goal,
               self.mind.recent[-1].get("outcome") is not None if self.mind.recent else None, self.mind.paused,
               json.dumps(self.mind.learning.get("history", [])[-1:]))
        now = time.time()
        if full or sig != self.mind_sig or now - self.last_mind > 2.0:
            self.mind_sig, self.last_mind = sig, now
            self.send("mind", mind=self.mind.public())

    # ------------------------------------------------------------------ the mind
    def step(self):
        m, w = self.mind, self.w
        # what happened in the world
        for e in w.events_since(self.event_seq):
            self.event_seq = e["seq"]
            if e.get("type") == "said" and e.get("who") != self.me:
                if self.near(e):
                    m.hear(e.get("name") or "someone", e.get("text", ""))
                continue
            d = describe_event(e, self.me)
            if d:
                m.hear_event(*d)
        night = w.is_night()
        if night != self.was_night:
            self.was_night = night
            m.hear_event("Night is falling." if night else "The sun is up.", important=night)
        # replies from its model
        while True:
            try:
                kind, *rest = m.inbox.get_nowait()
            except queue.Empty:
                break
            if kind == "decided":
                rec, res = rest
                started = rec.get("_started")
                d = m.finish(rec, res)
                if d is None:
                    self.event("log", text="its reply couldn't be read; it will think again", src="world")
                    m.wake("your last thought was garbled")
                    continue
                if d.get("say"):
                    w.say(w.agent, d["say"])
                    self.event("said", text=d["say"], to="you" if m.convo else "world")
                if not started:
                    self.start(d, d.get("action") or {})
                w.agent_info.update(goal=m.goal, thought=d.get("thought", ""))
                self.event("decision", decision=m.brief(d))
            elif kind == "failed":
                rec, err = rest
                m.failed(rec, err)
                self.event("log", text=f"deciding failed: {err}", src="world")
            elif kind == "reflected":
                todo, text = rest
                said = m.reflected(todo, text)
                self.event("reflection", text=said)
                self.end(True, said)
            elif kind == "reflect_failed":
                todo, err = rest
                m.thinking, m.busy_with = False, ""
                self.end(False, f"I couldn't gather my thoughts ({err}).")
        # actions that streamed in early
        while True:
            try:
                rec, action = self.started_actions.get_nowait()
            except queue.Empty:
                break
            rec["_started"] = True
            self.start(rec, action)
        # the body finished something
        r = w.skills.take_result()
        if r is not None and self.running is not None and self.running.get("action", {}).get("skill") not in ("reflect", "practice"):
            self.end(r.ok, r.text, r.details)
            if r.ok and r.details.get("skill") == "sleep" and self.cfg.mind.practice_auto and m.practice_need() is None:
                self.event("practice_request", by="auto")
        # time to think?
        reason = m.due(time.time(), w.skills.busy or self.running is not None)
        if reason:
            m.think(self.perceive(), reason, lambda rec, a: self.started_actions.put((rec, a)))

    def perceive(self) -> str:
        from .vox.describe import summary_text

        w = self.w
        text = "What you perceive now:\n" + summary_text(w, w.agent)
        if w.skills.busy:
            text += f"\nYou are busy: {w.skills.current} ({round(100 * w.skills.progress)}%) {w.skills.status}"
        return text

    def near(self, e: dict) -> bool:
        if self.cfg.mind.radio:
            return True
        a = self.w.agent
        return math.dist((a.x, a.y, a.z), (e.get("x", 1e9), e.get("y", 1e9), e.get("z", 1e9))) <= self.cfg.mind.hear_radius

    def start(self, rec: dict, action: dict):
        """Carry out a decision's action."""
        m, w = self.mind, self.w
        if rec.get("_begun"):
            return
        rec["_begun"] = True
        if self.running is not None and self.running is not rec and self.practising is None:
            # it changed its mind: the old decision ends here, and its interruption is not the new one's outcome
            old = self.running.get("action", {}).get("skill")
            if w.skills.busy:
                w.skills.interrupt("changed my mind")
            w.skills.take_result()
            self.end(False, f"You stopped {old or 'that'} to do something else.", wake=False)
        skill = str((action or {}).get("skill") or "")
        args = (action or {}).get("args") or {}
        rec["action"] = {"skill": skill, "args": args}
        self.running = rec
        m.pending = rec
        if skill == "reflect":
            err = m.reflect(lambda: None)
            if err:
                self.end(False, err)
        elif skill == "practice":
            need = m.practice_need()
            if need:
                self.end(False, need)
            else:
                self.practising = rec
                m.busy_with = "practising"
                w.skills.interrupt("practising")
                self.event("practice_request", by="self")
        elif skill == "name_place":
            a = w.agent
            text = m.name_place(args.get("name"), (a.x, a.y, a.z))
            if args.get("name"):
                w.places[str(args["name"]).strip()[:40]] = m.places.get(str(args["name"]).strip()[:40])
            self.end(True, text)
        else:
            err = w.skills.start(action)
            if err:
                self.end(False, err)

    def end(self, ok: bool, text: str, details: dict | None = None, wake: bool = True):
        rec = self.running
        self.running = None
        if rec is None:
            return
        self.mind.outcome(rec, ok, text, details)
        if wake:
            self.mind.wake("your last action ended" if ok else "your last action failed")
        self.event("outcome", id=rec["id"], ok=ok, text=text)
        back = self.mind.check_practice()
        if back:
            self.event("use_adapter", name=back["rollback_to"])
            self.mind.hear_event(back["text"], important=True)
            self.event("reflection", text=back["text"])

    # ------------------------------------------------------------------ commands from the Hub
    def handle(self, c: dict):
        cmd, rid = c["cmd"], c.get("rid")
        try:
            result = self._handle(cmd, c)
            if rid is not None:
                self.link.reply(rid, result)
        except Exception as e:  # noqa: BLE001 - report it, keep living
            self.log(f"command {cmd} failed: {type(e).__name__}: {e}")
            if rid is not None:
                self.link.reply(rid, error=f"{type(e).__name__}: {e}")

    def _handle(self, cmd: str, c: dict):
        m, w = self.mind, self.w
        if cmd == "stop":
            self.stopping = True
        elif cmd == "full":
            self.send_world(full=True)
        elif cmd == "chunk":
            return w.chunk_bytes(int(c["cx"]), int(c["cz"]))
        elif cmd == "chat":
            text = str(c.get("text") or "").strip()[:500]
            who = c.get("who") or (w.visitor.name if w.visitor else "Visitor")
            v = w.visitor
            heard = self.cfg.mind.radio or (v is not None and math.dist((v.x, v.y, v.z), (w.agent.x, w.agent.y, w.agent.z))
                                             <= self.cfg.mind.hear_radius)
            if v is not None:
                w.say(v, text)                       # a bubble over your avatar too
                self.event_seq = w._seq              # (not heard twice)
            if heard:
                m.hear(who, text)
            return {"heard": heard}
        elif cmd == "visitor":
            args = {k: v for k, v in c.items() if k not in ("cmd", "rid") and v is not None}
            return w.visitor_action(args)
        elif cmd == "agent":
            a = c.get("action")
            if a == "stop":
                w.skills.interrupt("stopped by your visitor")
            elif a == "pause":
                m.paused = True
                w.skills.interrupt("paused")
            elif a == "resume":
                m.paused = False
                m.wake("you can move again")
            elif a == "rate":
                v = int(c.get("value") or 0)
                m.judge(str(c.get("id")), "visitor", value=max(-1, min(1, v)))
            elif a == "correct":
                m.judge(str(c.get("id")), "visitor", correction=str(c.get("text") or "")[:300])
                m.lessons.append({"text": str(c.get("text") or "")[:160], "by": "visitor", "t": time.time()})
                del m.lessons[:-20]
            elif a == "reflect":
                m.wake("your visitor asked you to look back on what you've done")
            elif a == "practice":
                self.event("practice_request", by="visitor")
            else:
                raise ValueError(f"unknown agent action {a}")
            self.mind_sig = None
            return {"ok": True}
        elif cmd == "decisions":
            n = int(c.get("limit") or 100)
            p = self.folder / "decisions.jsonl"
            rows = []
            if p.exists():
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]:
                    try:
                        rows.append(m.brief(json.loads(line)))
                    except (ValueError, KeyError):
                        pass
            return rows
        elif cmd == "config":
            self.cfg = AdaConfig.from_dict(c["config"])
            m.cfg = self.cfg.mind
            w.peaceful = self.cfg.world.peaceful
            frac = w.time_of_day()
            w.day_ticks = int(self.cfg.world.day_minutes * 60 * 20)
            w.set_time(frac)
            w.sim_radius = self.cfg.world.view_chunks
            w.keep_radius = w.sim_radius + 6
        elif cmd == "model":
            m.url = c.get("url") or ""
            if c.get("ready") and c.get("adapter") != m.learning.get("adapter"):
                m.learning["adapter"] = c.get("adapter")
        elif cmd == "practice":
            self.on_practice(c.get("event"), c)
        else:
            raise ValueError(f"unknown command {cmd}")
        return None

    def on_practice(self, ev: str, c: dict):
        m, w = self.mind, self.w
        if ev == "started":
            m.busy_with = "practising"
            w.skills.interrupt("practising")
            w.agent.sleeping = True
            m.hear_event("You lay down to practise.")
        elif ev == "done":
            w.agent.sleeping = False
            text = m.practised(c.get("name"), c.get("info") or {})
            m.hear_event(text, important=True)
            self.event("reflection", text=text)
            if self.practising is not None:
                self.running = self.practising
                self.end(True, text)
            self.practising = None
        elif ev in ("failed", "refused"):
            w.agent.sleeping = False
            m.busy_with = ""
            why = c.get("error") or "it didn't work"
            m.hear_event(f"Practice didn't happen: {why}", important=True)
            if self.practising is not None:
                self.running = self.practising
                self.end(False, f"Practice didn't happen: {why}")
            self.practising = None
        elif ev == "switched":
            m.learning["adapter"] = c.get("name")
            m.hear_event(f"Your visitor switched you to {c.get('name') or 'your base model'}.")
        self.mind_sig = None


def run(name: str, root: str, inbox, outbox):
    folder = Path(root) / name
    link = Link("world", inbox, outbox, folder)
    try:
        World(folder, link).run()
    except Exception as e:  # noqa: BLE001
        link.crash(e)
        raise
