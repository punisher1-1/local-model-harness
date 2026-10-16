"""Static chat shell; API requests retain the existing bearer authentication."""
from pathlib import Path
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent / 'frontend' / 'dist'
HEADERS = {
    'Cache-Control': 'no-store',
    'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; font-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Frame-Options': 'DENY',
}


def install_chat_ui(app):
    if not (ROOT / 'index.html').is_file():
        return
    @app.get('/chat', include_in_schema=False)
    async def redirect_chat():
        return RedirectResponse('/chat/')
    @app.get('/chat/', include_in_schema=False)
    async def chat_shell():
        return FileResponse(ROOT / 'index.html', headers=HEADERS)
    app.mount('/chat/assets', StaticFiles(directory=ROOT / 'assets'), name='chat-assets')
