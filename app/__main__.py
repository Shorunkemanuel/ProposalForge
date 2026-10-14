"""Run the ProposalForge development server.

    python -m app [--host 127.0.0.1] [--port 8000]

Binds to localhost by default so the development server is not exposed
publicly. Set PROPOSALFORGE_MODEL (and optionally the other
PROPOSALFORGE_* variables) before starting.
"""

import argparse

from .server import create_server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the ProposalForge server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    try:
        server = create_server(host=args.host, port=args.port)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"ProposalForge serving on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
