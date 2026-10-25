from setuptools import find_packages, setup


setup(
    name="tg-booking-bot",
    version="0.1.0",
    description="Telegram booking bot MVP with FastAPI, aiogram, PostgreSQL, and Redis",
    packages=find_packages(include=["app", "app.*"]),
    install_requires=[
        "aiogram>=3.7.0,<4.0.0",
        "alembic>=1.13.2,<2.0.0",
        "fastapi>=0.115.0,<1.0.0",
        "pydantic-settings>=2.3.4,<3.0.0",
        "python-json-logger>=2.0.7,<3.0.0",
        "redis>=5.0.7,<6.0.0",
        "sqlalchemy[asyncio]>=2.0.31,<3.0.0",
        "asyncpg>=0.29.0,<1.0.0",
        "psycopg[binary]>=3.2.1,<4.0.0",
        "uvicorn[standard]>=0.30.0,<1.0.0",
    ],
    extras_require={
        "dev": [
            "httpx>=0.27.0,<1.0.0",
            "pytest>=8.2.0,<9.0.0",
            "pytest-asyncio>=0.23.7,<1.0.0",
            "ruff>=0.5.5,<1.0.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "api=app.api.main:run",
            "bot=app.bot.main:run",
            "worker=app.worker.main:run",
        ]
    },
)
