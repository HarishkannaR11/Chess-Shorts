# Deploying: one Short to YouTube every day

`publish.py` is the unattended job. Each run it:

1. picks the next format in the rotation (Flash → Story → Series),
2. renders it and checks it (vertical, has audio, 3 s – 3 min),
3. uploads it to YouTube and records it in the database.

If a format fails it falls back to the next one, and it skips itself if a Short already went out in the last 20 hours, so a late or repeated trigger never double-posts.

```bash
python publish.py                       # what the scheduler runs
python publish.py --no-upload           # dry run: render + checks only
python publish.py --format story --privacy unlisted --force
```

Two ways to run it daily. **Pick one** (running both publishes twice):

- **Option A – GitHub Actions (recommended).** Free for this public repo, no server to maintain.
- **Option B – a VM with cron** (AWS Lightsail, EC2, any Ubuntu box). Use this if you also want the control panel online.

---

## Step 1 – YouTube credentials (both options)

1. In [Google Cloud Console](https://console.cloud.google.com/): enable **YouTube Data API v3**, then **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON into the project folder as `client_secret.json` (it's git-ignored).
2. **OAuth consent screen → Publishing status → "In production".** While it's in "Testing", Google expires refresh tokens after 7 days and the daily job starts failing within a week. Google will show an "unverified app" warning when you sign in. It's your own app, so click through.
3. On your own computer (it opens a browser), run:
   ```bash
   python youtube_auth.py
   ```
   Sign in with the account that owns the channel and copy the three values it prints: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`.

> **Uploads coming out private?** YouTube locks videos uploaded through API projects created after July 2020 to **private** until the project passes the [YouTube API compliance audit](https://support.google.com/youtube/contact/yt_api_form) ([details](https://developers.google.com/youtube/v3/docs/videos/insert)). If videos you've uploaded from the dashboard went public, you're fine. If not, submit the audit form; until it's approved, publish with `--privacy private` and flip videos public by hand.

---

## Option A – GitHub Actions

1. **Merge this work into `main`.** Scheduled workflows only run from the default branch.
2. **Add secrets:** repo **Settings → Secrets and variables → Actions → New repository secret**:

   | Secret | Value |
   |---|---|
   | `YOUTUBE_CLIENT_ID` | from `youtube_auth.py` |
   | `YOUTUBE_CLIENT_SECRET` | from `youtube_auth.py` |
   | `YOUTUBE_REFRESH_TOKEN` | from `youtube_auth.py` |
   | `GROQ_API_KEY` | your Groq key. Optional: without it the Story format is skipped |

3. **Dry run:** **Actions → Daily Short → Run workflow**, untick *Upload to YouTube*, run. When it finishes, download the video from the run's **Artifacts** and watch it.
4. **First real upload:** run it again with upload ticked (choose *unlisted* if you want to check it on YouTube first).

From then on it runs every day at **09:17 UTC**. To change the time, edit the `cron:` line in `.github/workflows/daily-short.yml` (cron times are always UTC). You can still trigger extra runs from the Actions tab with a specific format or privacy.

**How it works**

- **State lives on the `bot-state` branch.** Each run restores `chess_shorts.db` and `uniqueness.db` from it and commits the updated copies back (about 50 KB; the 50k-puzzle cache is re-downloaded each run). Don't delete or merge that branch: it's what stops puzzles repeating and keeps the Series numbering going.
- **Every run attaches the rendered video** (and `last_run.json`) to the run page for 14 days. The run summary shows the YouTube link.
- **Failures** show as a red ❌ in the Actions tab, and GitHub emails you (default notification settings).
- **The Smoke test workflow** renders a Flash and a Series video on every push that touches the pipeline, so breakage shows up before the daily run.
- If GitHub ever pauses the schedule ("disabled because there hasn't been activity in this repository for at least 60 days"), open **Actions → Daily Short → Enable workflow**.

**Optional: carry over your local history.** The cloud starts with an empty database, so the Series would restart at #1 and old puzzles could repeat. To continue from your local database, seed the state branch once, before the first run:

```bash
mkdir seed && cp database/chess_shorts.db database/uniqueness.db seed/
cd seed
git init -b bot-state && git add . && git commit -m "Seed state from local database"
git push https://github.com/HarishkannaR11/Chess-Shorts.git bot-state
```

---

## Option B – VM with cron

Set up the server with sections 1–2 of the control panel guide below (packages, clone, virtualenv), then put these in `.env`:

```env
GROQ_API_KEY=your_groq_key
YOUTUBE_CLIENT_ID=your_client_id
YOUTUBE_CLIENT_SECRET=your_client_secret
YOUTUBE_REFRESH_TOKEN=your_refresh_token
YOUTUBE_PRIVACY=public
```

Check it with a dry run: `venv/bin/python publish.py --no-upload`. Then schedule it with `crontab -e`:

```cron
17 9 * * * cd /var/www/chess_panel && venv/bin/python publish.py >> outputs/publish.log 2>&1
```

Cron uses the server's time zone (UTC on Lightsail by default). `publish.py` reads `.env` itself, and the SQLite files in `database/` stay on the server's disk.

If you run the FastAPI dashboard (`uvicorn main:app`) on the server instead, its built-in daily schedule (enabled from the dashboard) runs this same job and uploads automatically. Set `"auto_upload": false` in `config/schedule.json` to only generate. Don't use both that schedule and the cron entry. Note that the FastAPI dashboard has no login, so don't expose it to the internet. Use the Flask panel below, or an SSH tunnel.

---

# Knightify Chess Control Panel (Flask) on AWS Lightsail

This guide covers deploying the Flask control panel to a fresh AWS Lightsail Ubuntu instance.

## 1. Initial Server Setup
1. Create a new instance in AWS Lightsail using the **Ubuntu 24.04 LTS** (or 22.04) blueprint.
2. Connect to the instance via SSH.
3. Update packages and install system dependencies:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv nginx ffmpeg fonts-dejavu-core
```

## 2. Clone and Setup Environment
1. Clone your repository (or copy your files over via SCP/SFTP) into `/var/www/chess_panel`.
```bash
sudo mkdir -p /var/www/chess_panel
sudo chown ubuntu:ubuntu /var/www/chess_panel
git clone https://github.com/HarishkannaR11/Chess-Shorts.git /var/www/chess_panel
cd /var/www/chess_panel
```

2. Create and activate a Python virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Create the `.env` file for your production environment:
```bash
nano .env
```
Add the following variables:
```env
# Flask App Settings
FLASK_SECRET_KEY=your_secure_random_string
PANEL_PASSWORD=your_secure_login_password

# YouTube Auth (Generate these using the provided auth script)
YOUTUBE_CLIENT_ID=your_client_id
YOUTUBE_CLIENT_SECRET=your_client_secret
YOUTUBE_REFRESH_TOKEN=your_refresh_token
```

## 3. Configure Gunicorn Systemd Service
Create a systemd service file to run the Flask app via Gunicorn.
```bash
sudo nano /etc/systemd/system/chess_panel.service
```
Add the following content:
```ini
[Unit]
Description=Gunicorn instance to serve Knightify Chess Panel
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/chess_panel
Environment="PATH=/var/www/chess_panel/venv/bin"
EnvironmentFile=/var/www/chess_panel/.env
ExecStart=/var/www/chess_panel/venv/bin/gunicorn --workers 3 --timeout 120 --bind unix:chess_panel.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
```

Start and enable the service:
```bash
sudo systemctl start chess_panel
sudo systemctl enable chess_panel
```

## 4. Configure Nginx Reverse Proxy
Create a new Nginx configuration file.
```bash
sudo nano /etc/nginx/sites-available/chess_panel
```
Add the following:
```nginx
server {
    listen 80;
    server_name your_domain.com; # Or your instance's public IP

    # Allow larger uploads if needed
    client_max_body_size 100M;

    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/chess_panel/chess_panel.sock;
        
        # Increase timeouts for long-running generation requests
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
```

Enable the configuration and restart Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/chess_panel /etc/nginx/sites-enabled
sudo nginx -t
sudo systemctl restart nginx
```

## 5. Security (Firewall)
In the AWS Lightsail networking tab, ensure that HTTP (port 80) and HTTPS (port 443) are open to the public.

*Optional but recommended: Run `certbot` to secure the panel with SSL.*
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your_domain.com
```
