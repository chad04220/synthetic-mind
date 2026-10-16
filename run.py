"""Start Synthetic Mind: the Hub (this process) serves the page, runs the inhabitant's model and
starts the World.

    python run.py                          create or resume Zen and its world
    python run.py --name Bo --seed 42      another inhabitant in another world
    python run.py --model llama-3.2-3b     a different model (also in Settings)
"""
from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def disable_console_pause():
    """Windows consoles freeze a program that prints while text is selected (QuickEdit mode)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            k32.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="Zen", help="which inhabitant to create or resume")
    ap.add_argument("--minds", default=str(ROOT / "minds"), help="folder where inhabitants and their worlds live")
    ap.add_argument("--model", default=None, help="its language model (see the Settings tab): " + ", ".join(
        __import__("ada.localllm", fromlist=["CATALOG"]).CATALOG))
    ap.add_argument("--cpu", action="store_true", help="run its model on the CPU even when there is a GPU")
    ap.add_argument("--seed", type=int, default=None, help="the seed of a new world")
    ap.add_argument("--peaceful", action="store_true", help="no hostile creatures")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    disable_console_pause()
    os.environ.setdefault("PYTHONUTF8", "1")

    import uvicorn

    from ada.config import AdaConfig
    from ada.hub import Hub
    from ada.web import create_app

    root = Path(args.minds)
    path = root / args.name / "config.json"
    if path.exists():
        cfg = AdaConfig.load(path)
        print(f"Resuming {cfg.name}.")
    else:
        cfg = AdaConfig(name=args.name)
        if args.seed:
            cfg.world.seed = args.seed
        print(f"Creating {cfg.name} and a new world.")
    if args.model:
        cfg.mind.model = args.model
    if args.cpu:
        cfg.mind.gpu = False
    if args.peaceful:
        cfg.world.peaceful = True

    hub = Hub(cfg, root)
    hub.start()
    url = f"http://{args.host}:{args.port}"
    print(f"Dashboard: {url}   (Ctrl+C saves and stops)")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(create_app(hub), host=args.host, port=args.port, log_level="warning")
    finally:
        print("Saving and stopping…")
        hub.stop()


if __name__ == "__main__":
    main()
