# Knightify Chess Control Panel Deployment Guide

This guide covers deploying the Flask control panel to a fresh AWS Lightsail Ubuntu instance.

## 1. Initial Server Setup
1. Create a new instance in AWS Lightsail using the **Ubuntu 24.04 LTS** (or 22.04) blueprint.
2. Connect to the instance via SSH.
3. Update packages and install system dependencies:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv nginx ffmpeg
```

## 2. Clone and Setup Environment
1. Clone your repository (or copy your files over via SCP/SFTP) into `/var/www/chess_panel`.
```bash
sudo mkdir -p /var/www/chess_panel
sudo chown ubuntu:ubuntu /var/www/chess_panel
# Clone or copy files here...
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
