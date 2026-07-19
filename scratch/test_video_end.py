import asyncio
import os
import shutil
import chess
from pipeline.story import generate_story
from pipeline.board import generate_frames
import cv2

def verify_video(video_path):
    print(f"Verifying {video_path}")
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Total video frames: {total_frames}")
    # Read the last frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 2)
    ret, frame = cap.read()
    if ret:
        cv2.imwrite("scratch/last_frame.jpg", frame)
        print("Saved last frame to scratch/last_frame.jpg")
    else:
        print("Failed to read last frame")
    cap.release()

if __name__ == "__main__":
    pass
