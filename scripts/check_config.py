#!/usr/bin/env python3
"""Check a profiles file before restarting the harness.

Applies the same validation as startup (profile settings, prompts, skills and MCP
servers) without touching the running service. Run it inside the container so the
environment and mounted files match what the harness will load:

    docker compose exec -T local-model-harness python scripts/check_config.py

Exits 0 with a per-profile summary, or 1 with the problem.
"""
import argparse
import os
from pathlib import Path
import sys

import yaml
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import load_profiles  # noqa: E402


def reasoning(profile):
    caps = [f"{name}: ratio {p.thinking_budget_ratio}" for name, p in profile.backend_presets.items() if p.thinking_budget_ratio]
    caps += [f"{name}: {p.backend_options['thinking_token_budget']} tokens" for name, p in profile.backend_presets.items()
             if "thinking_token_budget" in p.backend_options]
    if profile.thinking_budget_ratio:
        caps.append(f"ratio {profile.thinking_budget_ratio}")
    if "thinking_token_budget" in profile.backend_options:
        caps.append(f"{profile.backend_options['thinking_token_budget']} tokens")
    return "; ".join(caps) or "none"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", default=os.getenv("HARNESS_CONFIG", "profiles.yaml"))
    args = parser.parse_args(argv)
    try:
        loaded = load_profiles(args.path)
    except ValidationError as exc:
        print(f"INVALID {args.path}")
        for error in exc.errors(include_url=False, include_input=False):
            print("  " + ".".join(str(part) for part in error["loc"]) + ": " + error["msg"])
        return 1
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as exc:
        print(f"INVALID {args.path}\n  {exc}")
        return 1
    settings = loaded.settings
    for name, p in settings.profiles.items():
        timeout = p.request_timeout_seconds or settings.request_timeout_seconds
        print(f"  {name}: output {p.max_output_tokens}, timeout {timeout:g}s, reasoning cap {reasoning(p)}, "
              f"MCP {','.join(p.mcp_servers) or 'none'}")
    print(f"OK {args.path}: {len(settings.profiles)} profiles. Safe to run docker compose restart.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
