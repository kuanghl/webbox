"""BabelDOC WebUI - A modern web UI for BabelDOC PDF translation tool."""

import argparse
import logging
import sys
import multiprocessing as mp

from ui.app import run


def main():
    """Main entry point."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="BabelDOC WebUI")
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to run the web server on (default: 8080)",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Suppress noisy loggers
    for logger_name in ["httpx", "httpcore", "openai", "pdfminer"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    run(port=args.port)


if __name__ == "__main__":
    # Set multiprocessing start method
    if sys.platform == "darwin" or sys.platform == "win32":
        mp.set_start_method("spawn", force=True)
    else:
        mp.set_start_method("forkserver", force=True)

    main()
