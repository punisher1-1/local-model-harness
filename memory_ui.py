"""Public UI shell; every data operation uses existing authenticated memory routes."""
from pathlib import Path
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent / "memory_ui"
HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}

def install_ui(app):
    # Fixed paths, never a user-selected filesystem path.
    for route, filename, media in (("/memory", "index.html", "text/html"),
                                   ("/memory/app.js", "app.js", "text/javascript"),
                                   ("/memory/style.css", "style.css", "text/css")):
        # A closure factory avoids exposing file arguments as query parameters.
        def bind(name, kind):
            def serve():
                return FileResponse(ROOT / name, media_type=kind, headers=HEADERS)
            return serve
        app.add_api_route(route, bind(filename, media), methods=["GET"], include_in_schema=False)
