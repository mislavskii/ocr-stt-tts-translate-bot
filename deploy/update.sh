#!/bin/sh

echo "Starting deployment..."

# Navigate to the bot directory
cd /home/mcloud/projects/ocr-stt-tts-translate-bot || exit 1

# Pull latest changes from GitHub
git pull origin main

# Activate virtual environment
# source /home/mcloud/projects/ocr-stt-tts-translate-bot/.venv/bin/activate

# Install/update dependencies if requirements.txt changed
pip install -r requirements.txt

# Reload systemd in case service file changed (optional)
sudo systemctl daemon-reload

# Restart the bot service
sudo systemctl restart ocr-stt-tts-translate-bot.service

echo "Deployment completed."
