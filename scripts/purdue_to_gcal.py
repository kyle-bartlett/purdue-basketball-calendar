#!/usr/bin/env python3
import argparse
import subprocess
import sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yml")
    args = ap.parse_args()
    
    # Ensure project root is in PYTHONPATH for subprocess
    import os
    env = os.environ.copy()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    
    subprocess.check_call(
        [sys.executable, "scripts/purdue_refresh_from_web.py", "--config", args.config],
        env=env
    )

if __name__ == "__main__":
    main()
