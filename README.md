# World of Darkness Threat Rating Discord Bot

A small Discord helper for tracking fictional government monitoring heat against vampire characters in a World of Darkness chronicle.

The bot does not infer or assign ratings automatically. Storytellers set and adjust ratings, attach in-fiction reasons, and can review a full audit trail.

## Features

- Slash commands under `/threat`
- SQLite persistence
- Per-server configuration
- Storyteller-only write actions
- Required in-fiction reasons for all rating changes
- Recent history and current leaderboard
- Optional threshold alerts

## Commands

| Command | Description |
| --- | --- |
| `/threat view user` | View a character's current monitoring heat. |
| `/threat set user rating reason` | Set monitoring heat from 0 to 100. |
| `/threat add user amount reason` | Increase monitoring heat. |
| `/threat lower user amount reason` | Decrease monitoring heat. |
| `/threat reset user reason` | Reset monitoring heat to 0. |
| `/threat history user limit` | Show recent monitoring heat changes. |
| `/threat leaderboard limit` | Show the characters with the highest active monitoring heat. |
| `/threat config mod_role alert_channel alert_threshold` | Configure write access and alerts. |

## Setup

1. Create a Discord application and bot at <https://discord.com/developers/applications>.
2. Invite it to your server with these scopes:
   - `bot`
   - `applications.commands`
3. Give the bot permission to send messages in the channels where you will use it.
4. Install Python dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

5. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.
6. For faster command registration while testing, set `DISCORD_GUILD_ID` to your server ID.
7. Start the bot:

   ```powershell
   python bot.py
   ```

## Configuration

Users with **Manage Server** permission can configure the bot:

```text
/threat config mod_role:@Storytellers alert_channel:#chronicle-alerts alert_threshold:80
```

After a storyteller role is configured, members with that role can modify ratings. Users with **Manage Server** or **Administrator** can always use configuration and write commands.

## Chronicle Notes

Treat ratings as fictional chronicle state, such as FBI interest, Project Twilight attention, suspicious surveillance footage, compromised havens, Masquerade breaches, or pressure from mortal agencies. Use the reason field to record what happened in the story so everyone can follow the consequences later.
