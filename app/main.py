from __future__ import annotations

import uvicorn

from app.api import api
from app.config import API_HOST, API_PORT


def main() -> None:
    uvicorn.run(api, host=API_HOST, port=API_PORT)


if __name__ == "__main__":
    main()
