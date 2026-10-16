"""Start Ada: the Hub (this process) serves the dashboard and starts the Academy and the World.

    python run.py                          create or resume the mind "Ada"
    python run.py --name Bo --preset tiny  another mind, a smaller brain
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


def gpu_present() -> bool:
    """Whether an NVIDIA GPU is usable, without importing PyTorch into the Hub."""
    import shutil
    import subprocess

    if not shutil.which("nvidia-smi"):
        return False
    try:
        return subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="Ada", help="which mind to create or resume")
    ap.add_argument("--preset", choices=["tiny", "small", "medium", "large"], default=None,
                    help="brain size for a NEW mind (default: small with a GPU, tiny without)")
    ap.add_argument("--tokenizer", choices=["gpt2", "bytes"], default=None,
                    help="for a NEW mind (default: gpt2 with a GPU, bytes without)")
    ap.add_argument("--minds", default=str(ROOT / "minds"), help="folder where minds live")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--schedule", choices=["day_night", "together", "academy", "world"], default=None)
    ap.add_argument("--no-fineweb", action="store_true")
    ap.add_argument("--no-oracle", action="store_true")
    ap.add_argument("--ollama-url", default=None)
    ap.add_argument("--world-device", choices=["auto", "cuda", "cpu"], default=None,
                    help="where Ada's brain runs while she lives (cpu leaves the GPU to the Academy)")
    ap.add_argument("--compile", action="store_true", help="torch.compile training (Linux/WSL)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    disable_console_pause()
    # Windows' default text encoding can't hold every character Ada babbles; make every process
    # (the Academy and World inherit this) read and write UTF-8.
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
        gpu = gpu_present()
        # GPT-2's 50k-token vocabulary is a lot for a CPU; raw bytes keep a CPU-only brain quick.
        cfg = AdaConfig(name=args.name, tokenizer=args.tokenizer or ("gpt2" if gpu else "bytes"))
        cfg.apply_preset(args.preset or ("small" if gpu else "tiny"))
        print(f"Creating {cfg.name} with a {cfg.preset} brain.")
    if args.schedule:
        cfg.schedule.mode = args.schedule
    if args.no_fineweb:
        cfg.academy.fineweb = False
    if args.no_oracle:
        cfg.oracle.enabled = False
    if args.ollama_url:
        cfg.oracle.url = args.ollama_url
    if args.world_device:
        cfg.world.device = args.world_device
    if args.compile:
        cfg.academy.compile = True

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
