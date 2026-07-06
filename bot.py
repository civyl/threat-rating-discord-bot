from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from storage import ThreatRecord, ThreatStore, clamp_rating


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def optional_int(name: str) -> Optional[int]:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/threats.sqlite3"))
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = BASE_DIR / DATABASE_PATH

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = optional_int("DISCORD_GUILD_ID")
DEFAULT_MOD_ROLE_ID = optional_int("DEFAULT_MOD_ROLE_ID")
DEFAULT_ALERT_CHANNEL_ID = optional_int("DEFAULT_ALERT_CHANNEL_ID")
DEFAULT_ALERT_THRESHOLD = clamp_rating(int(os.getenv("DEFAULT_ALERT_THRESHOLD", "8")))

store = ThreatStore(DATABASE_PATH)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
threat = app_commands.Group(
    name="threat",
    description="Track World of Darkness government monitoring heat.",
)


def rating_label(rating: int) -> str:
    if rating >= 9:
        return "Critical"
    if rating >= 7:
        return "High"
    if rating >= 4:
        return "Medium"
    if rating > 0:
        return "Low"
    return "None"


def target_display(record: ThreatRecord) -> str:
    if record.user_id is not None:
        return f"<@{record.user_id}>"
    return record.target_name


def make_record_embed(target_name: str, target_value: str, record: Optional[ThreatRecord]) -> discord.Embed:
    rating = record.rating if record else 0
    embed = discord.Embed(
        title=f"Monitoring heat: {target_name}",
        description=f"**{rating}/10** ({rating_label(rating)})",
        color=discord.Color.red() if rating >= 7 else discord.Color.orange() if rating >= 4 else discord.Color.green(),
    )
    embed.add_field(name="Target", value=target_value, inline=True)
    if record:
        embed.add_field(name="Last updated", value=record.updated_at, inline=True)
        embed.add_field(name="Last reason", value=record.last_reason or "No reason stored", inline=False)
        if record.updated_by:
            embed.add_field(name="Updated by", value=f"<@{record.updated_by}>", inline=True)
    else:
        embed.add_field(name="Status", value="No rating has been recorded.", inline=False)
    return embed


async def ensure_guild_context(interaction: discord.Interaction) -> Optional[int]:
    if interaction.guild is None:
        await interaction.response.send_message(
            "Monitoring heat is server-specific. Use this command inside a server.",
            ephemeral=True,
        )
        return None
    store.ensure_guild(
        interaction.guild.id,
        default_mod_role_id=DEFAULT_MOD_ROLE_ID,
        default_alert_channel_id=DEFAULT_ALERT_CHANNEL_ID,
        default_alert_threshold=DEFAULT_ALERT_THRESHOLD,
    )
    return interaction.guild.id


async def ensure_moderator(interaction: discord.Interaction) -> bool:
    guild_id = await ensure_guild_context(interaction)
    if guild_id is None:
        return False

    user = interaction.user
    if not isinstance(user, discord.Member):
        await interaction.response.send_message("Could not verify your server roles.", ephemeral=True)
        return False

    if user.guild_permissions.manage_guild or user.guild_permissions.administrator:
        return True

    settings = store.get_settings(guild_id)
    if settings.mod_role_id and any(role.id == settings.mod_role_id for role in user.roles):
        return True

    await interaction.response.send_message(
        "You need Manage Server permission or the configured storyteller role to use this command.",
        ephemeral=True,
    )
    return False


async def maybe_send_threshold_alert(
    interaction: discord.Interaction,
    target_name: str,
    target_value: str,
    record: ThreatRecord,
    old_rating: int,
) -> None:
    if interaction.guild is None:
        return

    settings = store.get_settings(interaction.guild.id)
    if not settings.alert_channel_id:
        return
    if old_rating >= settings.alert_threshold or record.rating < settings.alert_threshold:
        return

    channel = interaction.guild.get_channel(settings.alert_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    embed = discord.Embed(
        title="Government monitoring threshold reached",
        description=f"{target_value} now has **{record.rating}/10** monitoring heat.",
        color=discord.Color.red(),
    )
    embed.add_field(name="Target", value=target_name, inline=True)
    embed.add_field(name="Previous rating", value=str(old_rating), inline=True)
    embed.add_field(name="Threshold", value=str(settings.alert_threshold), inline=True)
    embed.add_field(name="Reason", value=record.last_reason or "No reason stored", inline=False)
    await channel.send(embed=embed)


@threat.command(name="view", description="View a character's government monitoring heat.")
@app_commands.describe(user="The character/player to inspect.")
async def view_threat(interaction: discord.Interaction, user: discord.User) -> None:
    guild_id = await ensure_guild_context(interaction)
    if guild_id is None:
        return
    record = store.get_user_record(guild_id, user.id)
    await interaction.response.send_message(embed=make_record_embed(str(user), user.mention, record), ephemeral=True)


@threat.command(name="npc-view", description="View an NPC's government monitoring heat.")
@app_commands.describe(name="The NPC to inspect.")
async def view_npc_threat(interaction: discord.Interaction, name: str) -> None:
    guild_id = await ensure_guild_context(interaction)
    if guild_id is None:
        return
    try:
        record = store.get_npc_record(guild_id, name)
        display_name = record.target_name if record else " ".join(name.strip().split())
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    await interaction.response.send_message(embed=make_record_embed(display_name, display_name, record), ephemeral=True)


@threat.command(name="set", description="Set monitoring heat from 0 to 10.")
@app_commands.describe(user="The character/player to rate.", rating="A number from 0 to 10.", reason="What happened in the fiction.")
async def set_threat(interaction: discord.Interaction, user: discord.User, rating: app_commands.Range[int, 0, 10], reason: str) -> None:
    if not await ensure_moderator(interaction):
        return
    record, old_rating = store.change_user_rating(
        interaction.guild_id,
        user.id,
        str(user),
        action="set",
        new_rating=rating,
        reason=reason,
        moderator_id=interaction.user.id,
    )
    await interaction.response.send_message(embed=make_record_embed(str(user), user.mention, record), ephemeral=True)
    await maybe_send_threshold_alert(interaction, str(user), user.mention, record, old_rating)


@threat.command(name="npc-set", description="Set an NPC's monitoring heat from 0 to 10.")
@app_commands.describe(name="The NPC to rate.", rating="A number from 0 to 10.", reason="What happened in the fiction.")
async def set_npc_threat(interaction: discord.Interaction, name: str, rating: app_commands.Range[int, 0, 10], reason: str) -> None:
    if not await ensure_moderator(interaction):
        return
    try:
        record, old_rating = store.change_npc_rating(
            interaction.guild_id,
            name,
            action="set",
            new_rating=rating,
            reason=reason,
            moderator_id=interaction.user.id,
        )
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    await interaction.response.send_message(embed=make_record_embed(record.target_name, record.target_name, record), ephemeral=True)
    await maybe_send_threshold_alert(interaction, record.target_name, record.target_name, record, old_rating)


@threat.command(name="raise", description="Raise a character's monitoring heat.")
@app_commands.describe(user="The character/player to update.", amount="How many points to raise.", reason="What happened in the fiction.")
async def raise_threat(interaction: discord.Interaction, user: discord.User, amount: app_commands.Range[int, 1, 10], reason: str) -> None:
    if not await ensure_moderator(interaction):
        return
    current = store.get_user_record(interaction.guild_id, user.id)
    record, old_rating = store.change_user_rating(
        interaction.guild_id,
        user.id,
        str(user),
        action="raise",
        new_rating=(current.rating if current else 0) + amount,
        reason=reason,
        moderator_id=interaction.user.id,
    )
    await interaction.response.send_message(embed=make_record_embed(str(user), user.mention, record), ephemeral=True)
    await maybe_send_threshold_alert(interaction, str(user), user.mention, record, old_rating)


@threat.command(name="npc-raise", description="Raise an NPC's monitoring heat.")
@app_commands.describe(name="The NPC to update.", amount="How many points to raise.", reason="What happened in the fiction.")
async def raise_npc_threat(interaction: discord.Interaction, name: str, amount: app_commands.Range[int, 1, 10], reason: str) -> None:
    if not await ensure_moderator(interaction):
        return
    try:
        current = store.get_npc_record(interaction.guild_id, name)
        record, old_rating = store.change_npc_rating(
            interaction.guild_id,
            name,
            action="raise",
            new_rating=(current.rating if current else 0) + amount,
            reason=reason,
            moderator_id=interaction.user.id,
        )
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    await interaction.response.send_message(embed=make_record_embed(record.target_name, record.target_name, record), ephemeral=True)
    await maybe_send_threshold_alert(interaction, record.target_name, record.target_name, record, old_rating)


@threat.command(name="lower", description="Decrease a character's monitoring heat.")
@app_commands.describe(user="The character/player to update.", amount="How many points to subtract.", reason="What changed in the fiction.")
async def lower_threat(interaction: discord.Interaction, user: discord.User, amount: app_commands.Range[int, 1, 10], reason: str) -> None:
    if not await ensure_moderator(interaction):
        return
    current = store.get_user_record(interaction.guild_id, user.id)
    record, _old_rating = store.change_user_rating(
        interaction.guild_id,
        user.id,
        str(user),
        action="lower",
        new_rating=(current.rating if current else 0) - amount,
        reason=reason,
        moderator_id=interaction.user.id,
    )
    await interaction.response.send_message(embed=make_record_embed(str(user), user.mention, record), ephemeral=True)


@threat.command(name="npc-lower", description="Decrease an NPC's monitoring heat.")
@app_commands.describe(name="The NPC to update.", amount="How many points to subtract.", reason="What changed in the fiction.")
async def lower_npc_threat(interaction: discord.Interaction, name: str, amount: app_commands.Range[int, 1, 10], reason: str) -> None:
    if not await ensure_moderator(interaction):
        return
    try:
        current = store.get_npc_record(interaction.guild_id, name)
        record, _old_rating = store.change_npc_rating(
            interaction.guild_id,
            name,
            action="lower",
            new_rating=(current.rating if current else 0) - amount,
            reason=reason,
            moderator_id=interaction.user.id,
        )
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    await interaction.response.send_message(embed=make_record_embed(record.target_name, record.target_name, record), ephemeral=True)


@threat.command(name="reset", description="Reset a character's monitoring heat to zero.")
@app_commands.describe(user="The character/player to reset.", reason="What cleared the monitoring heat.")
async def reset_threat(interaction: discord.Interaction, user: discord.User, reason: str) -> None:
    if not await ensure_moderator(interaction):
        return
    record, _old_rating = store.reset_user_rating(
        interaction.guild_id,
        user.id,
        str(user),
        reason=reason,
        moderator_id=interaction.user.id,
    )
    await interaction.response.send_message(embed=make_record_embed(str(user), user.mention, record), ephemeral=True)


@threat.command(name="npc-reset", description="Reset an NPC's monitoring heat to zero.")
@app_commands.describe(name="The NPC to reset.", reason="What cleared the monitoring heat.")
async def reset_npc_threat(interaction: discord.Interaction, name: str, reason: str) -> None:
    if not await ensure_moderator(interaction):
        return
    try:
        record, _old_rating = store.reset_npc_rating(
            interaction.guild_id,
            name,
            reason=reason,
            moderator_id=interaction.user.id,
        )
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    await interaction.response.send_message(embed=make_record_embed(record.target_name, record.target_name, record), ephemeral=True)


@threat.command(name="history", description="Show recent monitoring heat changes.")
@app_commands.describe(user="The character/player to inspect.", limit="How many entries to show, up to 25.")
async def threat_history(interaction: discord.Interaction, user: discord.User, limit: app_commands.Range[int, 1, 25] = 10) -> None:
    if not await ensure_moderator(interaction):
        return
    rows = store.user_history(interaction.guild_id, user.id, limit)
    if not rows:
        await interaction.response.send_message("No history found for that user.", ephemeral=True)
        return

    lines = [
        f"`{row['created_at']}` {row['action']} {row['old_rating']} -> {row['new_rating']} by <@{row['moderator_id']}>: {row['reason']}"
        for row in rows
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@threat.command(name="npc-history", description="Show recent monitoring heat changes for an NPC.")
@app_commands.describe(name="The NPC to inspect.", limit="How many entries to show, up to 25.")
async def npc_threat_history(interaction: discord.Interaction, name: str, limit: app_commands.Range[int, 1, 25] = 10) -> None:
    if not await ensure_moderator(interaction):
        return
    try:
        rows = store.npc_history(interaction.guild_id, name, limit)
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    if not rows:
        await interaction.response.send_message("No history found for that NPC.", ephemeral=True)
        return

    lines = [
        f"`{row['created_at']}` {row['action']} {row['old_rating']} -> {row['new_rating']} by <@{row['moderator_id']}>: {row['reason']}"
        for row in rows
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@threat.command(name="leaderboard", description="Show the characters with the highest monitoring heat.")
@app_commands.describe(limit="How many entries to show, up to 25.")
async def threat_leaderboard(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 25] = 10) -> None:
    if not await ensure_moderator(interaction):
        return
    records = store.leaderboard(interaction.guild_id, limit)
    if not records:
        await interaction.response.send_message("No active monitoring heat found.", ephemeral=True)
        return

    lines = [
        f"**{index}.** {target_display(record)} - **{record.rating}/10** ({rating_label(record.rating)})"
        for index, record in enumerate(records, start=1)
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@threat.command(name="config", description="Configure storyteller role and alert settings.")
@app_commands.describe(
    mod_role="Role allowed to modify monitoring heat.",
    alert_channel="Channel that receives threshold alerts.",
    alert_threshold="Monitoring heat that triggers alerts.",
)
async def threat_config(
    interaction: discord.Interaction,
    mod_role: discord.Role = None,
    alert_channel: discord.TextChannel = None,
    alert_threshold: app_commands.Range[int, 0, 10] = None,
) -> None:
    if not await ensure_moderator(interaction):
        return

    settings = store.update_settings(
        interaction.guild_id,
        mod_role_id=mod_role.id if mod_role else ...,
        alert_channel_id=alert_channel.id if alert_channel else ...,
        alert_threshold=alert_threshold if alert_threshold is not None else ...,
    )
    await interaction.response.send_message(
        "\n".join(
            [
                "Monitoring heat configuration updated.",
                f"Storyteller role: {f'<@&{settings.mod_role_id}>' if settings.mod_role_id else 'Manage Server permission only'}",
                f"Alert channel: {f'<#{settings.alert_channel_id}>' if settings.alert_channel_id else 'Disabled'}",
                f"Alert threshold: {settings.alert_threshold}",
            ]
        ),
        ephemeral=True,
    )


@bot.event
async def on_ready() -> None:
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"Synced slash commands to guild {GUILD_ID}.")
    else:
        await bot.tree.sync()
        print("Synced global slash commands.")
    print(f"Logged in as {bot.user}.")


bot.tree.add_command(threat)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is missing. Copy .env.example to .env and add your token.")
    bot.run(TOKEN)
