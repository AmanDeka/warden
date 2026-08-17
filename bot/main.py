"""Entrypoint: gateway listener and event handlers."""

import asyncio
import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

from bot.agent import orchestrator
from bot.guardrails import auth
from bot.indexer import backfill, listener
from bot.storage import db
from bot.utils.formatting import answer_embed, status_embed

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = int(os.environ["GUILD_ID"])

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guild_messages = True
intents.reactions = True

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


@bot.tree.command(
    name="ask",
    description="Ask Warden something in natural language",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(question="What do you want to ask?")
async def ask_cmd(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    status_msg = await interaction.followup.send(embed=status_embed("🧠 Thinking..."))
    try:
        # Build a minimal pseudo-message so the orchestrator can work with it.
        # We pass None as guild when invoked from a DM context.
        guild = interaction.guild
        answer = await orchestrator.run_from_slash(
            question, interaction.user, guild, bot.user, status_msg, bot
        )
        await interaction.followup.send(embed=answer_embed(answer))
    except Exception as exc:
        await status_msg.edit(embed=status_embed(f"⚠️ Something went wrong: {exc}"))
        raise


index_group = app_commands.Group(
    name="index-channels",
    description="Manage which channels Warden indexes",
)


@index_group.command(name="list", description="Show all channels currently being indexed")
async def index_list(interaction: discord.Interaction) -> None:
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Only administrators can manage indexed channels.", ephemeral=True)
        return
    ids = await db.get_indexed_channel_ids()
    if not ids:
        await interaction.response.send_message(
            "No channel whitelist configured — **all channels** are currently being indexed.", ephemeral=True
        )
        return
    lines = []
    for cid in sorted(ids):
        ch = interaction.guild.get_channel(cid)
        lines.append(f"• #{ch.name}" if ch else f"• <deleted channel {cid}>")
    await interaction.response.send_message(
        "**Indexed channels:**\n" + "\n".join(lines), ephemeral=True
    )


@index_group.command(name="add", description="Add a channel to the index whitelist and backfill it")
@app_commands.describe(channel="Channel to start indexing")
async def index_add(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Only administrators can manage indexed channels.", ephemeral=True)
        return
    ids = await db.get_indexed_channel_ids()
    if channel.id in ids:
        await interaction.response.send_message(f"#{channel.name} is already in the index list.", ephemeral=True)
        return
    await db.add_indexed_channel(channel.id, interaction.guild.id)
    await interaction.response.send_message(
        f"Added #{channel.name} to the index list. Backfilling history now...", ephemeral=True
    )
    asyncio.create_task(backfill.backfill_channel(channel))


@index_group.command(name="remove", description="Remove a channel from the index whitelist")
@app_commands.describe(channel="Channel to stop indexing")
async def index_remove(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Only administrators can manage indexed channels.", ephemeral=True)
        return
    ids = await db.get_indexed_channel_ids()
    if channel.id not in ids:
        await interaction.response.send_message(f"#{channel.name} is not in the index list.", ephemeral=True)
        return
    await db.remove_indexed_channel(channel.id)
    await interaction.response.send_message(
        f"Removed #{channel.name} from the index list. Existing indexed messages are kept.", ephemeral=True
    )


bot.tree.add_command(index_group, guild=discord.Object(id=GUILD_ID))


# ---------------------------------------------------------------------------
# /permissions-allowlist — owner-only: controls who can invoke write tools
# ---------------------------------------------------------------------------

allowlist_group = app_commands.Group(
    name="permissions-allowlist",
    description="Manage which roles can use Warden's write/permission tools (owner only)",
)


def _is_owner_or_admin(interaction: discord.Interaction) -> bool:
    return (
        interaction.user.id == interaction.guild.owner_id
        or interaction.user.guild_permissions.administrator
    )


@allowlist_group.command(name="add", description="Grant a role access to write/permission tools")
@app_commands.describe(role="Role to allow")
async def allowlist_add(interaction: discord.Interaction, role: discord.Role) -> None:
    if not _is_owner_or_admin(interaction):
        await interaction.response.send_message(
            "Only the server owner or an administrator can modify the permissions allowlist.",
            ephemeral=True,
        )
        return
    current = await db.get_allowlist_role_ids()
    if role.id in current:
        await interaction.response.send_message(
            f"**{role.name}** is already on the allowlist.", ephemeral=True
        )
        return
    await auth.add_to_allowlist(role, interaction.user)
    await interaction.response.send_message(
        f"Added **{role.name}** to the permissions allowlist. "
        "Members with this role can now invoke Warden's write tools.",
        ephemeral=True,
    )


@allowlist_group.command(name="remove", description="Revoke a role's access to write/permission tools")
@app_commands.describe(role="Role to remove")
async def allowlist_remove(interaction: discord.Interaction, role: discord.Role) -> None:
    if not _is_owner_or_admin(interaction):
        await interaction.response.send_message(
            "Only the server owner or an administrator can modify the permissions allowlist.",
            ephemeral=True,
        )
        return
    removed = await auth.remove_from_allowlist(role)
    if not removed:
        await interaction.response.send_message(
            f"**{role.name}** is not on the allowlist.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        f"Removed **{role.name}** from the permissions allowlist.", ephemeral=True
    )


@allowlist_group.command(name="list", description="Show all roles that can use write/permission tools")
async def allowlist_list(interaction: discord.Interaction) -> None:
    if not _is_owner_or_admin(interaction):
        await interaction.response.send_message(
            "Only the server owner or an administrator can view the permissions allowlist.",
            ephemeral=True,
        )
        return
    entries = await auth.list_allowlist()
    if not entries:
        await interaction.response.send_message(
            "The permissions allowlist is empty — no roles can use write tools yet.\n"
            "Use `/permissions-allowlist add @role` to grant access.",
            ephemeral=True,
        )
        return
    lines = []
    for entry in entries:
        role = interaction.guild.get_role(entry["role_id"])
        role_label = f"**{role.name}**" if role else f"<deleted role {entry['role_id']}>"
        adder = interaction.guild.get_member(entry["added_by"])
        adder_label = adder.display_name if adder else f"<user {entry['added_by']}>"
        lines.append(f"• {role_label} — added by {adder_label} on {entry['added_at'][:10]}")
    await interaction.response.send_message(
        "**Permissions allowlist:**\n" + "\n".join(lines), ephemeral=True
    )


bot.tree.add_command(allowlist_group, guild=discord.Object(id=GUILD_ID))


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
            answer = await orchestrator.run(message, guild, bot.user, status_msg, bot)
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


def main():
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
