"""Root package logger configuration."""
import sys

from loguru import logger

# Remove default handler
logger.remove()

# Configure output format
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",
    colorize=True,
)

# Configure file rotation for production
# logger.add(
#     "logs/app_{time:YYYY-MM-DD}.log",
#     rotation="00:00",
#     retention="30 days",
#     level="INFO",
#     compression="zip",
# )
