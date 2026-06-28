import os
import json
import logging
from typing import Dict, Any
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

logger = logging.getLogger(__name__)

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def generate_script(puzzle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a YouTube Shorts story script based on the provided game data.
    """
    logger.info("Generating script for champion game.")
    
    player = puzzle.get('player', 'Magnus Carlsen')
    opponent = puzzle.get('opponent', 'Unknown')
    event = puzzle.get('event', 'World Championship')
    year = puzzle.get('year', '2023')
    
    prompt = f"""You are creating a viral chess YouTube Short script.
Speak like a passionate sports commentator.
This is for TEXT-TO-SPEECH so write naturally spoken sentences only.
No chess notation. No coordinates. No symbols.

Script must flow like this:
- Hook: One shocking statement (spoken in 3 seconds)
- Setup: Who is playing, what is at stake (10 seconds)  
- Tension: The position looks equal but... (5 seconds)
- Reveal: The brilliant move and why it works (8 seconds)
- Lesson: What we learn from this genius (2 seconds)
- CTA: Follow for more champion moments (2 seconds)

Total spoken time: exactly 30 seconds when read at normal pace.
Count words: 30 seconds = approximately 75-80 words total.
Keep it to 75 words maximum.

Return ONLY JSON:
{{
  "hook": "max 10 words",
  "setup": "max 20 words",  
  "tension": "max 15 words",
  "reveal": "max 20 words",
  "lesson": "max 10 words",
  "cta": "Follow for daily champion chess moments",
  "full_script": "all sections joined as one flowing paragraph, 75 words max",
  "title": "under 60 chars with {player} name",
  "description": "2 sentences",
  "tags": ["chess", "{player.lower().split()[0]}", "tactics", "chesshorts", "grandmaster"]
}}

Game Context:
{player} vs {opponent} at {event} {year}.
"""
    
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response received from Groq API.")
            
        script_data = json.loads(content)
        return script_data
        
    except Exception as e:
        logger.error(f"Error generating script: {e}")
        raise
