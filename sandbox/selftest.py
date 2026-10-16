#!/usr/bin/env python3
"""Escape and correctness tests for the sandbox, run on the sandbox host against real Docker.

    sudo -u sandbox /opt/harness-sandbox-venv/bin/python selftest.py

Each case runs through the same run_python() the server uses. Exit code 0 only if
every case passes. Run it after any change to the image, Docker or the host.
"""
import asyncio
import os
import sys

from server import run_python, OUTPUT_CAP

# Address of the harness host; it must be unreachable from inside the sandbox.
PROBE_LAN = os.getenv("SANDBOX_PROBE_HOST", "192.0.2.10")


CASES = [
    ("arithmetic is exact", "print(2**100)",
     lambda r: r["stdout"].strip() == str(2**100)),
    ("numpy, pandas, sympy and matplotlib import", "import numpy as np, pandas as pd, sympy as sp, matplotlib.pyplot as plt\n"
     "print(int(np.arange(10).sum()), len(pd.DataFrame({'a':[1,2]})), sp.integrate(sp.Symbol('x')**2, sp.Symbol('x')))",
     lambda r: r["exit_code"] == 0 and r["stdout"].split()[:2] == ["45", "2"] and "x**3/3" in r["stdout"]),
    ("exceptions return a traceback", "raise ValueError('expected')",
     lambda r: r["exit_code"] == 1 and "ValueError: expected" in r["stderr"]),
    ("runs as uid 10001, not root", "import os; print(os.getuid(), os.getgid())",
     lambda r: r["stdout"].split() == ["10001", "10001"]),
    ("no internet", "import urllib.request\ntry:\n urllib.request.urlopen('http://1.1.1.1', timeout=3)\n print('REACHED')\n"
     "except Exception as e:\n print('BLOCKED', type(e).__name__)",
     lambda r: "BLOCKED" in r["stdout"] and "REACHED" not in r["stdout"]),
    ("no LAN or harness access", f"import socket\ns=socket.socket(); s.settimeout(3)\ntry:\n s.connect(('{PROBE_LAN}', 8200))\n print('REACHED')\n"
     "except Exception as e:\n print('BLOCKED', type(e).__name__)",
     lambda r: "BLOCKED" in r["stdout"] and "REACHED" not in r["stdout"]),
    ("no DNS", "import socket\ntry:\n socket.gethostbyname('github.com'); print('REACHED')\nexcept Exception as e:\n print('BLOCKED', type(e).__name__)",
     lambda r: "BLOCKED" in r["stdout"]),
    ("root filesystem is read-only", "try:\n open('/usr/local/x','w').write('x'); print('WROTE')\nexcept OSError as e:\n print('BLOCKED', e.errno)",
     lambda r: "BLOCKED" in r["stdout"]),
    ("/etc/shadow is unreadable", "try:\n print(len(open('/etc/shadow').read())); print('READ')\nexcept OSError as e:\n print('BLOCKED', e.errno)",
     lambda r: "BLOCKED" in r["stdout"]),
    ("scratch dir is writable but not executable", "import os, subprocess\nopen('/work/a.txt','w').write('ok')\n"
     "open('/work/run.sh','w').write('#!/bin/sh\\necho EXEC')\nos.chmod('/work/run.sh', 0o755)\n"
     "try:\n print(subprocess.run(['/work/run.sh'], capture_output=True, text=True).stdout or 'NOOUT')\n"
     "except OSError as e:\n print('BLOCKED', e.errno)\nprint(open('/work/a.txt').read())",
     lambda r: "BLOCKED" in r["stdout"] and r["stdout"].strip().endswith("ok")),
    ("no capabilities or privilege escalation", "print(open('/proc/self/status').read())",
     lambda r: "CapEff:\t0000000000000000" in r["stdout"] and "NoNewPrivs:\t1" in r["stdout"]),
    ("memory is capped at 512 MB", "b = bytearray(1024**3); print('ALLOCATED')",
     lambda r: "ALLOCATED" not in r["stdout"] and r["exit_code"] != 0),
    ("process count is capped", "import os\npids=[]\ntry:\n for _ in range(500): \n  p=os.fork()\n  if p==0:\n   import time; time.sleep(5); os._exit(0)\n  pids.append(p)\n print('FORKED', len(pids))\n"
     "except OSError as e:\n print('BLOCKED after', len(pids))",
     lambda r: "BLOCKED after" in r["stdout"]),
    ("infinite loops time out", "while True: pass",
     lambda r: r["timed_out"]),
    ("output floods are stopped and capped", "while True: print('x' * 1000)",
     lambda r: r["output_limit"] and len(r["stdout"]) <= OUTPUT_CAP),
    ("nothing persists between runs", "import os; print(os.path.exists('/work/a.txt'))",
     lambda r: r["stdout"].strip() == "False"),
]


async def main():
    failures = 0
    for name, code, check in CASES:
        result = await run_python(code)
        ok = check(result)
        failures += not ok
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"\n     {result}"))
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
