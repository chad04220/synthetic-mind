"""Start a synthetic mind and its dashboard.

    python run.py                      # create or resume the mind "Ada"
    python run.py --name Bo --preset tiny --tokenizer bytes
"""
from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="Ada", help="which mind to create or resume")
    ap.add_argument("--preset", default=None, choices=["tiny", "small", "medium", "large"],
                    help="network size for a NEW mind (default: small on a GPU, tiny on CPU)")
    ap.add_argument("--tokenizer", default=None, choices=["gpt2", "bytes"],
                    help="for a NEW mind (default: gpt2 on a GPU, bytes on CPU)")
    ap.add_argument("--minds", default=str(ROOT / "minds"), help="folder where minds are saved")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--cpu", action="store_true", help="force CPU even if a GPU is available")
    ap.add_argument("--no-fineweb", action="store_true", help="do not stream FineWeb")
    ap.add_argument("--no-teacher", action="store_true", help="do not use Ollama")
    ap.add_argument("--ollama-url", default=None)
    ap.add_argument("--compile", action="store_true", help="torch.compile the training graph (needs Triton)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    import torch
    import uvicorn

    from mind.brain import Mind, pick_device
    from mind.config import MindConfig
    from mind.server import create_app

    root = Path(args.minds)
    device = torch.device("cpu") if args.cpu else pick_device()
    cfg_path = root / args.name / "config.json"
    if cfg_path.exists():
        cfg = MindConfig.load(cfg_path)
        print(f"Resuming {cfg.name} ({cfg.preset}, {cfg.model.n_layers} layers, {cfg.tokenizer} tokens)")
    else:
        cfg = MindConfig(name=args.name, tokenizer=args.tokenizer or ("bytes" if device.type == "cpu" else "gpt2"))
        cfg.apply_preset(args.preset or ("tiny" if device.type == "cpu" else "small"))
        print(f"Creating a new mind {cfg.name} ({cfg.preset})")
    if args.no_fineweb:
        cfg.data.fineweb_enabled = False
    if args.no_teacher:
        cfg.teacher_enabled = False
    if args.ollama_url:
        cfg.ollama_url = args.ollama_url
    if args.compile:
        cfg.train.compile = True

    mind = Mind(cfg, root, device)
    print(f"Device: {mind.device}  parameters: {mind.model.n_params():,}")
    mind.start()
    url = f"http://{args.host}:{args.port}"
    print(f"Dashboard: {url}")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(create_app(mind), host=args.host, port=args.port, log_level="warning")
    finally:
        print("Saving...")
        mind.stop()


if __name__ == "__main__":
    main()
