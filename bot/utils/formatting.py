"""Status-box embed (editable) and final-answer embed builders."""

import discord

STATUS_COLOR = discord.Color.light_grey()
ANSWER_COLOR = discord.Color.blue()


def status_embed(text: str) -> discord.Embed:
    return discord.Embed(description=text, color=STATUS_COLOR)


def answer_embed(text: str, title: str = "Warden") -> discord.Embed:
    return discord.Embed(title=title, description=text, color=ANSWER_COLOR)


def diff_lines(changes: list[tuple[str, str]]) -> str:
    """Format a list of (action, description) pairs as a readable diff."""
    return "\n".join(f"**{action}:** {desc}" for action, desc in changes)
