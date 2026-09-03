import logging

from rich.console import Console
from rich.logging import RichHandler

console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        RichHandler(
            console=console,
            show_path=False,
            rich_tracebacks=True,
            markup=True,
        )
    ],
)

logger = logging.getLogger("Arbiter")


def get_logger() -> logging.Logger:
    return logger
