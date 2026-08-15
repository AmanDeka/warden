"""Entrypoint: gateway listener and event handlers."""

import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

from bot.indexer import listener
from bot.storage import db

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["GUILD_ID"])

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guild_messages = True
intents.guild_message_reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await db.init()
    print(f"Warden online as {bot.user} (guild {GUILD_ID})")


@bot.event
async def on_message(message: discord.Message):
    await listener.on_message(message)

    if message.author.bot:
        return

    bot_mentioned = bot.user in message.mentions
    reply_to_bot = (
        message.reference is not None
        and message.reference.resolved is not None
        and message.reference.resolved.author == bot.user
    )
    is_dm = isinstance(message.channel, discord.DMChannel)

    if bot_mentioned or reply_to_bot or is_dm:
        # TODO: route to agent orchestrator
        pass

    await bot.process_commands(message)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    await listener.on_message_edit(before, after)


@bot.event
async def on_message_delete(message: discord.Message):
    await listener.on_message_delete(message)


@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    await listener.on_raw_message_delete(payload)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
