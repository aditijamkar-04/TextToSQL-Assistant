import os
import requests


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


def generate_ai_response(prompt, max_tokens=1200):
    """Generate text using the Groq hosted AI API."""

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv(
        "GROQ_MODEL",
        "openai/gpt-oss-20b",
    ).strip()

    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured.")

    response = requests.post(
        GROQ_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a careful SQL assistant. "
                        "Follow the supplied database schema "
                        "and return only the requested output."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0,
            "max_completion_tokens": max_tokens,
        },
        timeout=90,
    )

    response.raise_for_status()

    data = response.json()
    answer = data["choices"][0]["message"]["content"]

    if not answer or not answer.strip():
        raise ValueError("Groq returned an empty response.")

    return answer.strip()
