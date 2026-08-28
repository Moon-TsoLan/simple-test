"""Multi-format notice and attachment parser.

The public entry point is :class:`NoticeParser`.
"""

from .pipeline import NoticeParser, ParserConfig

__all__ = ["NoticeParser", "ParserConfig"]

