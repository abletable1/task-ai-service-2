import uvicorn

from task_ai_service.api.app import create_app
from task_ai_service.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == "__main__":
    main()
