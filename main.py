"""Smart Book Library — App Launcher."""
import argparse
import uvicorn

from server.config import DEFAULT_HOST, DEFAULT_PORT


def main():
    parser = argparse.ArgumentParser(description="Smart Book Library")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    parser.add_argument("--network", action="store_true", help="Bind to 0.0.0.0 for LAN access")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    host = "0.0.0.0" if args.network else args.host
    if args.network:
        import socket
        local_ip = socket.gethostbyname(socket.gethostname())
        print("\n  Network mode enabled. Access from other devices at:")
        print(f"  http://{local_ip}:{args.port}\n")

    print(f"  Starting Smart Book Library at http://{host}:{args.port}")
    print(f"  API docs: http://{host}:{args.port}/docs\n")

    uvicorn.run(
        "server.app:app",
        host=host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
