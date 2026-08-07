from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable

from .analyzer import EuroAnalyzer
from .config import Config, load_config
from .database import DrawDatabase
from .generator import CombinationGenerator, format_grouped_combinations_message, generate_hybrid_combinations
from .logging_setup import setup_logging
from .scheduler import run_weekly
from .scraper import EuroScraper
from .telegram_bot import TelegramCommandBot
from .telegram_client import TelegramClient, TelegramConfigError

LOGGER = logging.getLogger(__name__)


def year_range(config: Config, start_year: int | None, end_year: int | None) -> range:
    start = start_year or config.start_year
    end = end_year or config.end_year
    if start > end:
        raise ValueError("start-year cannot be greater than end-year")
    return range(start, end + 1)


def smart_year_range(config: Config, database: DrawDatabase, lookback_years: int = 1) -> range:
    latest_draw_date = database.latest_draw_date()
    if latest_draw_date is None:
        years = year_range(config, None, None)
        LOGGER.info(
            "No local draw history found; bootstrapping all years %s-%s",
            years.start,
            years.stop - 1,
        )
        return years

    start_year = max(config.start_year, latest_draw_date.year - max(0, lookback_years))
    years = year_range(config, start_year, None)
    LOGGER.info(
        "Local history found through %s; incrementally refreshing years %s-%s",
        latest_draw_date.isoformat(),
        years.start,
        years.stop - 1,
    )
    return years


def refresh_data(config: Config, database: DrawDatabase, years: Iterable[int]) -> int:
    year_list = list(years)
    LOGGER.info("Refreshing Euro draw data for years: %s", ", ".join(map(str, year_list)))
    scraper = EuroScraper()
    draws = scraper.scrape_years(year_list)
    stored = database.upsert_draws(draws)
    LOGGER.info("Refresh complete: %s draws scraped/stored", stored)
    return stored


def refresh_data_smart(
    config: Config,
    database: DrawDatabase,
    force_full: bool = False,
    start_year: int | None = None,
    end_year: int | None = None,
    lookback_years: int = 1,
) -> int:
    if force_full or start_year is not None or end_year is not None:
        years = year_range(config, None if force_full else start_year, end_year)
        if force_full:
            LOGGER.info("Forced full refresh requested")
        return refresh_data(config, database, years)
    return refresh_data(config, database, smart_year_range(config, database, lookback_years))


def generate_message(database: DrawDatabase, count: int) -> str:
    if database.draw_count() == 0:
        raise RuntimeError("No historical draws found. Run the refresh command first.")
    analyzer = EuroAnalyzer(database)
    generator = CombinationGenerator(analyzer)
    groups = generate_hybrid_combinations(generator, count=count)
    return format_grouped_combinations_message(groups)


def send_weekly_message(config: Config, database: DrawDatabase, count: int, refresh_first: bool) -> None:
    if refresh_first:
        try:
            refresh_data_smart(config, database)
        except Exception:
            LOGGER.exception("Refresh failed; continuing with local database if available")
    message = generate_message(database, count=count)
    TelegramClient(config.telegram_bot_token, config.telegram_chat_id).send_message(message)


def run_telegram_command_bot(
    config: Config,
    database: DrawDatabase,
    count: int,
    refresh_first: bool,
    poll_timeout_seconds: int,
    process_pending: bool,
) -> None:
    if not config.telegram_chat_id:
        raise TelegramConfigError("TELEGRAM_CHAT_ID must be set in .env")

    client = TelegramClient(config.telegram_bot_token, config.telegram_chat_id)

    def generate_for_chat(_chat_id: str | int) -> str:
        if refresh_first:
            try:
                refresh_data_smart(config, database)
            except Exception:
                LOGGER.exception("Refresh failed; generating from local database")
        return generate_message(database, count=count)

    TelegramCommandBot(
        client=client,
        allowed_chat_id=config.telegram_chat_id,
        state_path=config.bot_state_path,
        generate_callback=generate_for_chat,
        poll_timeout_seconds=poll_timeout_seconds,
        drop_pending_on_first_start=not process_pending,
    ).run_forever()


def print_analysis(database: DrawDatabase, top_n: int) -> None:
    analyzer = EuroAnalyzer(database)
    main_ranked, euro_ranked = analyzer.hot_cold_table(top_n=top_n)
    print("\nHoofdnummers:")
    print(main_ranked.to_string(index=False))
    print("\nEuro-nummers:")
    print(euro_ranked.to_string(index=False))


def check_telegram(config: Config) -> None:
    token_set = bool(config.telegram_bot_token)
    chat_id_set = bool(config.telegram_chat_id)
    print(f"TELEGRAM_BOT_TOKEN: {'set' if token_set else 'missing'}")
    print(f"TELEGRAM_CHAT_ID: {'set' if chat_id_set else 'missing'}")

    if not token_set or not chat_id_set:
        raise TelegramConfigError(
            "Create euro_telegram/.env from .env.example and fill TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        )

    bot = TelegramClient(config.telegram_bot_token, config.telegram_chat_id)
    bot_info = bot.check_connection()
    print(f"Bot API ok: @{bot_info.get('username', '<unknown>')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Euro analyzer and Telegram sender")
    parser.add_argument("--env", help="Path to .env file", default=None)
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")

    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser("refresh", help="Smart update the local SQLite database")
    refresh.add_argument("--start-year", type=int, default=None)
    refresh.add_argument("--end-year", type=int, default=None)
    refresh.add_argument("--full", action="store_true", help="Force all years from 2012 to current year")
    refresh.add_argument(
        "--lookback-years",
        type=int,
        default=1,
        help="When updating an existing database, also refresh this many previous years",
    )

    analyze = sub.add_parser("analyze", help="Show hot/cold number frequency tables")
    analyze.add_argument("--top", type=int, default=10)

    generate = sub.add_parser("generate", help="Generate combinations and print them")
    generate.add_argument("--count", type=int, default=10)

    send = sub.add_parser("send", help="Generate and send combinations via Telegram")
    send.add_argument("--count", type=int, default=10)
    send.add_argument("--no-refresh", action="store_true", help="Do not refresh data before sending")

    once = sub.add_parser("once", help="Refresh, generate and send once")
    once.add_argument("--count", type=int, default=10)

    schedule_cmd = sub.add_parser("schedule", help="Run continuously and send weekly")
    schedule_cmd.add_argument("--count", type=int, default=10)

    bot_cmd = sub.add_parser("bot", help="Listen for Telegram /generate commands")
    bot_cmd.add_argument("--count", type=int, default=10)
    bot_cmd.add_argument("--no-refresh", action="store_true", help="Do not refresh data before replying")
    bot_cmd.add_argument("--poll-timeout", type=int, default=30)
    bot_cmd.add_argument(
        "--process-pending",
        action="store_true",
        help="Process already queued Telegram updates on startup",
    )

    test = sub.add_parser("telegram-test", help="Send a small test message to Telegram")
    test.add_argument("--text", default="Telegram test vanuit Euro bot.")

    sub.add_parser("telegram-check", help="Check Telegram env vars and bot API connection")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.env)
    setup_logging(config.log_file, verbose=args.verbose)

    database = DrawDatabase(config.db_path)
    database.initialize()

    try:
        if args.command == "refresh":
            refresh_data_smart(
                config,
                database,
                force_full=args.full,
                start_year=args.start_year,
                end_year=args.end_year,
                lookback_years=args.lookback_years,
            )
        elif args.command == "analyze":
            print_analysis(database, top_n=args.top)
        elif args.command == "generate":
            print(generate_message(database, count=args.count))
        elif args.command == "send":
            send_weekly_message(config, database, count=args.count, refresh_first=not args.no_refresh)
        elif args.command == "once":
            send_weekly_message(config, database, count=args.count, refresh_first=True)
        elif args.command == "schedule":
            run_weekly(
                config.run_day,
                config.run_time,
                lambda: send_weekly_message(
                    config,
                    database,
                    count=args.count,
                    refresh_first=True,
                ),
            )
        elif args.command == "bot":
            run_telegram_command_bot(
                config,
                database,
                count=args.count,
                refresh_first=not args.no_refresh,
                poll_timeout_seconds=args.poll_timeout,
                process_pending=args.process_pending,
            )
        elif args.command == "telegram-test":
            TelegramClient(config.telegram_bot_token, config.telegram_chat_id).send_message(args.text)
        elif args.command == "telegram-check":
            check_telegram(config)
        else:
            parser.error(f"Unknown command: {args.command}")
    except KeyboardInterrupt:
        LOGGER.info("Stopped by user")
        return 130
    except Exception:
        LOGGER.exception("Command failed")
        return 1
    return 0
