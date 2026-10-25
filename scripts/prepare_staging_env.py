from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ENV = ROOT / ".env"
TARGET_ENV = ROOT / ".env.staging"
TEMPLATE_ENV = ROOT / ".env.staging.example"

COPY_KEYS = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_MANAGER_CHAT_IDS",
    "TELEGRAM_STICKER_WELCOME",
    "TELEGRAM_STICKER_BOOKED",
    "TELEGRAM_STICKER_CANCELLED",
    "TIMEZONE",
    "SLOT_BUFFER_MIN",
    "API_PORT",
    "BOT_POLLING_TIMEOUT",
    "WORKER_POLL_INTERVAL",
}


def parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def main() -> None:
    if not SOURCE_ENV.exists():
        raise SystemExit("Missing .env. Create it first.")
    if not TEMPLATE_ENV.exists():
        raise SystemExit("Missing .env.staging.example.")

    source = parse_env_file(SOURCE_ENV)
    template = parse_env_file(TEMPLATE_ENV)

    for key in COPY_KEYS:
        if key in source and source[key]:
            template[key] = source[key]

    ordered_keys = list(parse_env_file(TEMPLATE_ENV).keys())
    output_lines = [f"{key}={template.get(key, '')}" for key in ordered_keys]
    TARGET_ENV.write_text("\n".join(output_lines) + "\n", encoding="utf-8")

    print(f"Prepared {TARGET_ENV.name}. Review DB/Redis host and passwords before deploy.")


if __name__ == "__main__":
    main()
