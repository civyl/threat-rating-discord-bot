# Oracle Cloud Deployment

This guide deploys the bot to an Oracle Cloud Infrastructure Always Free VM and runs it with `systemd`.

## 1. Create The VM

In Oracle Cloud:

1. Open **Compute** > **Instances** > **Create instance**.
2. Pick an Always Free eligible shape. Recommended:
   - **Ampere A1** if your region has capacity
   - **VM.Standard.E2.1.Micro** if Ampere capacity is unavailable
3. Use Oracle Linux 9 or Oracle Linux 8.
4. Add or generate an SSH key.
5. Create the instance and wait for it to become **Running**.

This bot does not need inbound ports. Discord connections are outbound, so you do not need to open HTTP/HTTPS ports for the bot.

## 2. SSH Into The VM

From your machine:

```bash
ssh -i /path/to/private_key opc@YOUR_PUBLIC_IP
```

## 3. Install The Bot

On the VM:

```bash
curl -fsSL https://raw.githubusercontent.com/civyl/threat-rating-discord-bot/main/deploy/oracle/setup-oracle-vm.sh -o setup-oracle-vm.sh
sudo bash setup-oracle-vm.sh
```

## 4. Add Your Discord Settings

Edit the environment file:

```bash
sudo nano /opt/threat-rating-discord-bot/.env
```

Set at least:

```env
DISCORD_TOKEN=your-bot-token
DISCORD_GUILD_ID=your-server-id
DATABASE_PATH=data/threats.sqlite3
```

`DISCORD_GUILD_ID` is optional, but recommended at first because guild slash commands sync much faster than global commands.

## 5. Start The Bot

```bash
sudo systemctl start threat-rating-discord-bot
sudo systemctl status threat-rating-discord-bot
```

Follow logs:

```bash
sudo journalctl -u threat-rating-discord-bot -f
```

If the bot starts correctly, you should see a message like:

```text
Synced slash commands to guild ...
Logged in as ...
```

## Updating Later

```bash
cd /opt/threat-rating-discord-bot
sudo git pull --ff-only
sudo systemctl restart threat-rating-discord-bot
```

## Useful Commands

```bash
sudo systemctl stop threat-rating-discord-bot
sudo systemctl restart threat-rating-discord-bot
sudo journalctl -u threat-rating-discord-bot -n 100
```

## Backups

The SQLite database lives at:

```text
/opt/threat-rating-discord-bot/data/threats.sqlite3
```

Copy this file before rebuilding or replacing the VM.
