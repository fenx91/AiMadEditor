"""Small Gemini HTTP client used by script planning."""

import json
import os
import urllib.request

from fastapi import HTTPException


def get_gemini_api_key():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        return api_key
    env_path = "/home/fenxy/my_new_agent/.env"
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as file:
                for line in file:
                    if line.strip().startswith("GOOGLE_API_KEY="):
                        return line.strip().split("GOOGLE_API_KEY=", 1)[1].strip()
        except Exception as exc:
            print(f"Error reading env file: {exc}")
    return None


def call_gemini(prompt: str, response_json: bool = False) -> str:
    api_key = get_gemini_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="Google API key not found. Please set GOOGLE_API_KEY environment variable or configure it in /home/fenxy/my_new_agent/.env")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    if response_json:
        payload["generationConfig"] = {"responseMimeType": "application/json"}
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            response_data = json.loads(response.read().decode("utf-8"))
        return response_data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gemini API call failed: {exc}") from exc
