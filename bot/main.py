"""Entrypoint: gateway listener and event handlers."""

import asyncio
import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from bot.agent import orchestrator
from bot.indexer import backfill, listener
from bot.storage import db
from bot.utils.formatting import answer_embed, status_embed

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
    guild_obj = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild_obj)
    print(f"Warden online as {bot.user} (guild {GUILD_ID})")

    guild = bot.get_guild(GUILD_ID)
    if guild is not None:
        asyncio.create_task(backfill.backfill_guild(guild))


@bot.tree.command(
    name="search-mode",
    description="Switch the search backend (admin only)",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(mode="fts = keyword search, semantic = AI similarity search")
@app_commands.choices(mode=[
    app_commands.Choice(name="FTS — fast keyword search (no API cost)", value="fts"),
    app_commands.Choice(name="Semantic — AI similarity search (Gemini embeddings)", value="semantic"),
])
async def search_mode_cmd(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "Only server administrators can change the search mode.", ephemeral=True
        )
        return
    await db.set_setting("search_method", mode.value)
    label = "FTS (keyword)" if mode.value == "fts" else "Semantic (Gemini embeddings)"
    await interaction.response.send_message(
        f"Search mode switched to **{label}**.", ephemeral=True
    )


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    if channel.guild.id != GUILD_ID or not isinstance(channel, discord.TextChannel):
        return
    asyncio.create_task(backfill.backfill_channel(channel))


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
        guild = message.guild
        status_msg = await message.channel.send(embed=status_embed("🧠 Thinking..."))
        try:
            answer = await orchestrator.run(message, guild, bot.user, status_msg)
            await message.channel.send(embed=answer_embed(answer))
        except Exception as exc:
            await status_msg.edit(embed=status_embed(f"⚠️ Something went wrong: {exc}"))
            raise

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
