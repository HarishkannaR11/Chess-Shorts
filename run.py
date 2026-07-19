import argparse
import asyncio
import os
import shutil
import logging

from pipeline.flash import generate_flash
from pipeline.story import generate_story
from pipeline.series import generate_series

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("run")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", type=str, choices=["flash", "story", "series"], default="story")
    args = parser.parse_args()

    output_base_dir = "outputs"
    os.makedirs(output_base_dir, exist_ok=True)
    
    # Run the appropriate pipeline generator
    if args.format == "flash":
        result = await generate_flash(output_base_dir=output_base_dir)
    elif args.format == "story":
        result = await generate_story(output_base_dir=output_base_dir)
    elif args.format == "series":
        result = await generate_series(output_base_dir=output_base_dir)
    
    # Check if final.mp4 was generated
    final_video = result.get("video_path") if isinstance(result, dict) else os.path.join(result, "final.mp4")
    if final_video and os.path.exists(final_video):
        latest_video = os.path.join(output_base_dir, "latest.mp4")
        shutil.copy(final_video, latest_video)
        logger.info(f"Successfully copied final video to {latest_video}")
    else:
        logger.error(f"Generation failed: {final_video} not found.")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
