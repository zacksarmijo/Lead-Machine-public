#!/usr/bin/env python3
"""Launch the Summit web application."""
from __future__ import annotations

import os
import sys

# Ensure working directory is the summit-web folder so uvicorn finds the app module
os.chdir(os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        import uvicorn
    except ImportError:
        print("Missing dependencies. Run:  pip install -r requirements.txt")
        sys.exit(1)

    host = "127.0.0.1"
    port = int(os.environ.get("PORT", "8000"))

    print(f"\n  Summit is running at http://{host}:{port}\n")
    uvicorn.run("app.main:app", host=host, port=port, reload=False, proxy_headers=False)


if __name__ == "__main__":
    main()
