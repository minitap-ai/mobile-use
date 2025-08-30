import logging
import sys
from enum import Enum
from pathlib import Path

from colorama import Fore, Style, init

init(autoreset=True)


class LogLevel(Enum):
    DEBUG = ("DEBUG", Fore.MAGENTA, "🔍")
    INFO = ("INFO", Fore.WHITE, "ℹ")
    SUCCESS = ("SUCCESS", Fore.GREEN, "✓")
    WARNING = ("WARNING", Fore.YELLOW, "⚠")
    ERROR = ("ERROR", Fore.RED, "❌")
    CRITICAL = ("CRITICAL", Fore.RED + Style.BRIGHT, "💥")


class MobileUseLogger:
    def __init__(
        self,
        name: str,
        log_file: str | Path | None = None,
        console_level: str = "INFO",
        file_level: str = "DEBUG",
        enable_file_logging: bool = True,
    ):
        """
        Initialize the MobileUse logger.

        Args:
            name: Logger name (usually __name__)
            log_file: Path to log file (defaults to logs/{name}.log)
            console_level: Minimum level for console output
            file_level: Minimum level for file output
            enable_file_logging: Whether to enable file logging
        """
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        self.logger.handlers.clear()

        self._setup_console_handler(console_level)

        if enable_file_logging:
            self._setup_file_handler(log_file, file_level)

    def _setup_console_handler(self, level: str):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper()))

        console_formatter = ColoredFormatter()
        console_handler.setFormatter(console_formatter)

        self.logger.addHandler(console_handler)

    def _setup_file_handler(self, log_file: str | Path | None, level: str):
        if log_file is None:
            log_file = Path("logs") / f"{self.name.replace('.', '_')}.log"

        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(getattr(logging, level.upper()))

        file_formatter = logging.Formatter(
            fmt="%(asctime)s | %(name)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)

        self.logger.addHandler(file_handler)

    def debug(self, message: str, **kwargs):
        self.logger.debug(message, extra={"log_level": LogLevel.DEBUG}, **kwargs)

    def info(self, message: str, **kwargs):
        self.logger.info(message, extra={"log_level": LogLevel.INFO}, **kwargs)

    def success(self, message: str, **kwargs):
        self.logger.info(message, extra={"log_level": LogLevel.SUCCESS}, **kwargs)

    def warning(self, message: str, **kwargs):
        self.logger.warning(message, extra={"log_level": LogLevel.WARNING}, **kwargs)

    def error(self, message: str, **kwargs):
        self.logger.error(message, extra={"log_level": LogLevel.ERROR}, **kwargs)

    def critical(self, message: str, **kwargs):
        self.logger.critical(message, extra={"log_level": LogLevel.CRITICAL}, **kwargs)

    def header(self, message: str, **_kwargs):
        separator = "=" * 60
        colored_separator = f"{Fore.CYAN}{separator}{Style.RESET_ALL}"
        colored_message = f"{Fore.CYAN}{message}{Style.RESET_ALL}"

        print(colored_separator)
        print(colored_message)
        print(colored_separator)
        self.logger.info(f"\n{separator}\n{message}\n{separator}")


class ColoredFormatter(logging.Formatter):
    def format(self, record):
        log_level = getattr(record, "log_level", LogLevel.INFO)
        _level_name, color, symbol = log_level.value

        colored_message = f"{color}{symbol} {record.getMessage()}{Style.RESET_ALL}"

        return colored_message


_loggers = {}


def get_logger(
    name: str,
    log_file: str | Path | None = None,
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    enable_file_logging: bool = False,
) -> MobileUseLogger:
    """
    Get or create a logger instance.

    Args:
        name: Logger name (usually __name__)
        log_file: Path to log file (defaults to logs/{name}.log)
        console_level: Minimum level for console output
        file_level: Minimum level for file output
        enable_file_logging: Whether to enable file logging

    Returns:
        MobileUseLogger instance
    """
    if name not in _loggers:
        _loggers[name] = MobileUseLogger(
            name=name,
            log_file=log_file,
            console_level=console_level,
            file_level=file_level,
            enable_file_logging=enable_file_logging,
        )

    return _loggers[name]


def log_debug(message: str, logger_name: str = "mobile-use"):
    get_logger(logger_name).debug(message)


def log_info(message: str, logger_name: str = "mobile-use"):
    get_logger(logger_name).info(message)


def log_success(message: str, logger_name: str = "mobile-use"):
    get_logger(logger_name).success(message)


def log_warning(message: str, logger_name: str = "mobile-use"):
    get_logger(logger_name).warning(message)


def log_error(message: str, logger_name: str = "mobile-use"):
    get_logger(logger_name).error(message)


def log_critical(message: str, logger_name: str = "mobile-use"):
    get_logger(logger_name).critical(message)


def log_header(message: str, logger_name: str = "mobile-use"):
    get_logger(logger_name).header(message)


def get_server_logger() -> MobileUseLogger:
    return get_logger(
        name="mobile-use.servers",
        console_level="INFO",
        file_level="DEBUG",
    )
