# Server Deploy (Linux)

1. Upload the `telegram-bot` folder to your server.
2. Connect via SSH and go to folder:
   ```bash
   cd telegram-bot
   ```
3. Open `.env` and set token:
   ```bash
   nano .env
   ```
   Required:
   - `TELEGRAM_BOT_TOKEN=...`
   Optional:
   - `MANAGER_CHAT_ID=...`
4. Run bot:
   ```bash
   chmod +x start.sh
   ./start.sh
   ```

## Optional: run as service (systemd)

Create file `/etc/systemd/system/raffle-bot.service`:

```ini
[Unit]
Description=Telegram raffle bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/telegram-bot
ExecStart=/root/telegram-bot/.venv/bin/python /root/telegram-bot/bot.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Then run:
```bash
systemctl daemon-reload
systemctl enable raffle-bot
systemctl start raffle-bot
systemctl status raffle-bot
```
