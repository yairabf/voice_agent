import uvicorn

from voice_agent.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "voice_agent.api.app:app",
        host="0.0.0.0",
        port=settings.voice_runtime_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
