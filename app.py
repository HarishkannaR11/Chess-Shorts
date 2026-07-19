import os
import subprocess
import threading
import json
import logging
from datetime import datetime
import shutil

from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for, send_from_directory
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_secret_key_123")
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "knightify")

# State for background generation
gen_state = {
    "status": "idle", # idle, running, checking, done, failed
    "logs": [],
    "process": None,
    "qa_results": None,
}

OUTPUT_DIR = "outputs"
LATEST_VIDEO = os.path.join(OUTPUT_DIR, "latest.mp4")
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, "archive")
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# ----------------- QA LOGIC -----------------

def run_qa_checks(video_path):
    results = {
        "passed": True,
        "duration": {"pass": False, "msg": "", "val": 0},
        "silence": {"pass": False, "msg": ""},
        "frozen": {"pass": False, "msg": ""}
    }
    
    # 1. Duration check
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
        dur_out = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
        dur = float(dur_out)
        results["duration"]["val"] = dur
        if 5.0 <= dur <= 60.0:
            results["duration"]["pass"] = True
            results["duration"]["msg"] = f"Duration {dur:.1f}s is within 5-60s range."
        else:
            results["passed"] = False
            results["duration"]["msg"] = f"Duration {dur:.1f}s is OUTSIDE 5-60s range!"
    except Exception as e:
        results["passed"] = False
        results["duration"]["msg"] = f"Error checking duration: {e}"

    # 2. Silence check (gap > 1.5s)
    try:
        cmd = ["ffmpeg", "-i", video_path, "-af", "silencedetect=noise=-35dB:d=1.5", "-f", "null", "-"]
        out = subprocess.run(cmd, stderr=subprocess.STDOUT, stdout=subprocess.PIPE).stdout.decode()
        if "silence_start" in out:
            results["passed"] = False
            results["silence"]["msg"] = "Silence gap > 1.5s detected!"
        else:
            results["silence"]["pass"] = True
            results["silence"]["msg"] = "No excessive silence gaps detected."
    except Exception as e:
        results["passed"] = False
        results["silence"]["msg"] = f"Error checking silence: {e}"

    # 3. Frozen/Black frames check
    try:
        cmd = ["ffmpeg", "-i", video_path, "-vf", "blackdetect=d=0.1:pix_th=0.1", "-f", "null", "-"]
        out = subprocess.run(cmd, stderr=subprocess.STDOUT, stdout=subprocess.PIPE).stdout.decode()
        if "black_start" in out:
            results["passed"] = False
            results["frozen"]["msg"] = "Black/frozen frames detected!"
        else:
            results["frozen"]["pass"] = True
            results["frozen"]["msg"] = "No black frames detected."
    except Exception as e:
        results["passed"] = False
        results["frozen"]["msg"] = f"Error checking black frames: {e}"

    return results

# ----------------- BACKGROUND GEN -----------------

def background_generation():
    global gen_state
    gen_state["status"] = "running"
    gen_state["logs"] = ["Starting generation pipeline..."]
    gen_state["qa_results"] = None
    
    try:
        # Run subprocess
        process = subprocess.Popen(
            ["python", "run.py", "--format", "story"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        gen_state["process"] = process
        
        for line in process.stdout:
            gen_state["logs"].append(line.strip())
            
        process.wait()
        
        if process.returncode != 0:
            gen_state["status"] = "failed"
            gen_state["logs"].append(f"Pipeline exited with code {process.returncode}")
            return
            
        gen_state["status"] = "checking"
        gen_state["logs"].append("Running QA Checks on latest.mp4...")
        
        if not os.path.exists(LATEST_VIDEO):
            gen_state["status"] = "failed"
            gen_state["logs"].append("Error: latest.mp4 not found after generation.")
            return
            
        qa = run_qa_checks(LATEST_VIDEO)
        gen_state["qa_results"] = qa
        
        if qa["passed"]:
            gen_state["status"] = "done"
            # Archive it
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy(LATEST_VIDEO, os.path.join(ARCHIVE_DIR, f"archive_{stamp}.mp4"))
            gen_state["logs"].append("QA Passed! Archived copy saved.")
        else:
            gen_state["status"] = "needs_review"
            gen_state["logs"].append("QA Failed. Video needs review.")

    except Exception as e:
        gen_state["status"] = "failed"
        gen_state["logs"].append(f"Exception in thread: {str(e)}")

# ----------------- ROUTES -----------------

@app.before_request
def require_login():
    if request.path.startswith("/static"):
        return
    if request.path == "/login":
        return
    if not session.get("logged_in"):
        return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == PANEL_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        return "Invalid Password", 401
    return '''
    <form method="post" style="text-align:center; margin-top:100px; font-family:sans-serif;">
        <h2>Knightify Chess Panel</h2>
        <input type="password" name="password" placeholder="Password" />
        <button type="submit">Login</button>
    </form>
    '''

@app.route("/")
def index():
    return render_template_string(open("templates/index.html").read())

@app.route("/generate", methods=["POST"])
def generate():
    global gen_state
    if gen_state["status"] in ["running", "checking"]:
        return jsonify({"error": "Already running"}), 400
    
    thread = threading.Thread(target=background_generation)
    thread.daemon = True
    thread.start()
    return jsonify({"success": True})

@app.route("/status")
def status():
    return jsonify(gen_state)

@app.route("/videos/<path:filename>")
def videos(filename):
    return send_from_directory(OUTPUT_DIR, filename)

@app.route("/upload", methods=["POST"])
def upload_video():
    title = request.form.get("title", "Knightify Chess Brilliancy")
    description = request.form.get("description", "Daily chess puzzle and brilliancy! #chess #shorts")
    tags_str = request.form.get("tags", "chess,shorts,tactics")
    privacy = request.form.get("privacy", "public")
    
    tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    
    if not os.path.exists(LATEST_VIDEO):
        return jsonify({"success": False, "error": "No latest.mp4 found."})
        
    try:
        client_id = os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
        
        if not all([client_id, client_secret, refresh_token]):
            return jsonify({"success": False, "error": "YouTube Auth env vars missing (Client ID, Secret, or Refresh Token)."})
            
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token"
        )
        
        youtube = build("youtube", "v3", credentials=credentials)
        
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "20" # Gaming
            },
            "status": {
                "privacyStatus": privacy
            }
        }
        
        media = MediaFileUpload(LATEST_VIDEO, mimetype='video/mp4', resumable=True)
        request_cmd = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        response = request_cmd.execute()
        
        vid_id = response.get("id")
        return jsonify({"success": True, "url": f"https://youtu.be/{vid_id}"})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
