"""Local static preview with HTTP Range support for timestamped video seeking."""
from pathlib import Path
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
import uvicorn

if __name__ == '__main__':
    output = Path(__file__).resolve().parent / 'public'
    uvicorn.run(Starlette(routes=[Mount('/', StaticFiles(directory=output, html=True))]),
                host='127.0.0.1', port=8093)
