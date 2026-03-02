from django.conf import settings
import json
import re
from typing import Optional, List

import requests


OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

FALLBACK_FREE_MODELS = [
    "openai/gpt-oss-20b:free",
    "google/gemma-3-4b-it:free",
    "qwen/qwen3-4b:free",
    "nvidia/nemotron-nano-9b-v2:free",
]


def _extract_retry_seconds(error_text: str) -> Optional[int]:
    match = re.search(r"retry in\s+(\d+(?:\.\d+)?)s", error_text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return max(1, int(float(match.group(1))))
    except (TypeError, ValueError):
        return None


def _normalize_ai_error(error_text: str) -> str:
    lowered = error_text.lower()
    retry_secs = _extract_retry_seconds(error_text)

    if "quota exceeded" in lowered or "429" in lowered or "rate limit" in lowered:
        if retry_secs:
            return f"Error: AI quota exceeded. Please enable OpenRouter credits or retry after {retry_secs}s."
        return "Error: AI quota exceeded. Please enable OpenRouter credits for this API key."

    if "invalid api key" in lowered or "unauthorized" in lowered or "401" in lowered:
        return "Error: Invalid OpenRouter API key. Please update OPENROUTER_API_KEY in server/.env."

    if "missing authentication header" in lowered or "no auth credentials found" in lowered:
        return "Error: OpenRouter auth header missing. Verify OPENROUTER_API_KEY is set correctly and restart backend."

    if "permission denied" in lowered or "insufficient permissions" in lowered or "forbidden" in lowered:
        return "Error: OpenRouter access denied for this key/project."

    if "no endpoints found matching your data policy" in lowered:
        return "Error: OpenRouter data policy blocks free models. Update privacy settings at https://openrouter.ai/settings/privacy."

    if ("not found" in lowered and "model" in lowered) or ("no endpoints found" in lowered):
        return "Error: OpenRouter model unavailable. Try another free model in OPENROUTER_MODEL."

    return f"Error: {error_text}"


def _fallback_resume_parse(text: str, error_message: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line and line.strip()]
    full_name = "Candidate"
    for line in lines[:6]:
        if len(line) <= 60 and not re.search(r"\d", line):
            full_name = line
            break

    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    phone_match = re.search(r"(?:\+?\d[\d\-\s()]{7,}\d)", text)

    return {
        "full_name": full_name,
        "email": email_match.group(0) if email_match else "",
        "phone": phone_match.group(0) if phone_match else "",
        "summary": f"{error_message} Basic resume details were extracted without AI.",
        "skills": [],
        "experience": [],
        "education": []
    }


def _safe_json_loads(value: str):
    try:
        return json.loads(value)
    except Exception:
        return None


def _resolve_candidate_models() -> List[str]:
    configured = (getattr(settings, "OPENROUTER_MODEL", "") or "").strip()
    models = [configured] if configured else []
    for model_name in FALLBACK_FREE_MODELS:
        if model_name not in models:
            models.append(model_name)
    return models


def _build_headers(api_key: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Optional but recommended by OpenRouter.
    site_url = (getattr(settings, "OPENROUTER_SITE_URL", "") or "").strip()
    app_name = (getattr(settings, "OPENROUTER_APP_NAME", "") or "").strip()
    if site_url:
        headers["HTTP-Referer"] = site_url
    if app_name:
        headers["X-Title"] = app_name

    return headers


def _normalize_api_key(raw_key: Optional[str]) -> Optional[str]:
    if raw_key is None:
        return None

    key = str(raw_key).strip()
    if not key:
        return None

    # Support values copied as: OPENROUTER_API_KEY="sk-or-..."
    key = key.strip('"').strip("'").strip()

    # Support values copied with Bearer prefix.
    if key.lower().startswith("bearer "):
        key = key[7:].strip()

    return key or None


def _extract_content(data: dict) -> Optional[str]:
    choices = data.get("choices") or []
    if not choices:
        return None
    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        joined = "".join(text_parts).strip()
        return joined or None

    return None


def get_ai_response(prompt: str, system_instruction: str = "") -> str:
    api_key = _normalize_api_key(
        getattr(settings, "OPENROUTER_API_KEY", None)
        or getattr(settings, "GEMINI_API_KEY", None)
    )
    if not api_key:
        return "Error: OPENROUTER_API_KEY is missing/empty in server/.env."

    headers = _build_headers(api_key)
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    last_error = "Unknown AI error."

    for model_name in _resolve_candidate_models():
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.2,
        }

        try:
            response = requests.post(
                OPENROUTER_CHAT_URL,
                headers=headers,
                json=payload,
                timeout=90,
            )
        except requests.RequestException as e:
            last_error = f"Network error while contacting OpenRouter: {str(e)}"
            continue

        # Retry with next free model if configured model is unavailable.
        if response.status_code in (400, 404):
            try:
                err_data = response.json()
                err_text = (
                    err_data.get("error", {}).get("message")
                    or err_data.get("message")
                    or response.text
                )
            except Exception:
                err_text = response.text

            lowered = err_text.lower()
            if "model" in lowered and ("not found" in lowered or "unavailable" in lowered or "no endpoints found" in lowered):
                last_error = err_text
                continue

            return _normalize_ai_error(err_text)

        if response.status_code != 200:
            try:
                err_data = response.json()
                err_text = (
                    err_data.get("error", {}).get("message")
                    or err_data.get("message")
                    or response.text
                )
            except Exception:
                err_text = response.text
            return _normalize_ai_error(err_text)

        try:
            data = response.json()
        except Exception:
            return "Error: Invalid response format from OpenRouter."

        content = _extract_content(data)
        if content:
            return content

        return "Error: Empty response from OpenRouter model."

    return _normalize_ai_error(last_error)


def parse_resume_ai(text):
    system_instruction = "You are an expert HR recruitment tool. Extract structured information from the following resume text. Output ONLY valid JSON."
    prompt = f"""
    Extract the following details from the resume text:
    - full_name
    - email
    - phone
    - summary
    - skills (list of strings)
    - experience (list of objects with: title, company, duration, description)
    - education (list of objects with: degree, institution, year)

    Resume Text:
    {text}
    """
    response_text = get_ai_response(prompt, system_instruction)

    if response_text.startswith("Error:"):
        print(f"AI Error: {response_text}")
        return _fallback_resume_parse(text, response_text)

    json_match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if json_match:
        parsed = _safe_json_loads(json_match.group(1))
        if parsed:
            return parsed

    json_match = re.search(r"(\{.*\})", response_text, re.DOTALL)
    if json_match:
        parsed = _safe_json_loads(json_match.group(1))
        if parsed:
            return parsed

    return _fallback_resume_parse(text, "Error: AI returned unstructured output.")


def polish_summary_ai(summary):
    system_instruction = "You are a professional resume writer."
    prompt = f"Rewrite this professional summary to be more impactful and HR-friendly:\n\n{summary}"
    return get_ai_response(prompt, system_instruction)


def match_job_ai(resume_data, job_description):
    system_instruction = "You are an AI recruitment agent. Compare the candidate's resume with the job description."
    prompt = f"""
    Candidate Info: {json.dumps(resume_data)}
    Job Description: {job_description}

    Provide:
    1. Score (0 to 100)
    2. Missing Skills (list of strings)
    3. Brief Explanation (max 3 sentences)

    Output ONLY valid JSON.
    """
    response_text = get_ai_response(prompt, system_instruction)

    json_match = re.search(r"(?:```json)?\s*(\{.*?\})\s*(?:```)?", response_text, re.DOTALL)
    if json_match:
        data = _safe_json_loads(json_match.group(1))
        if isinstance(data, dict):
            return {
                "score": data.get("score", 0),
                "missing_skills": data.get("missing_skills", []),
                "explanation": data.get("explanation", ""),
            }
    return {"score": 0, "missing_skills": [], "explanation": "AI processing failed."}


def generate_jd_ai(job_title, extra_info=""):
    system_instruction = "You are an expert HR manager."
    prompt = f"Write a comprehensive Job Description for the role: {job_title}. Extra info: {extra_info}. Include a list of required skills."
    return get_ai_response(prompt, system_instruction)


def generate_interview_questions_ai(resume_data, job_description):
    system_instruction = "You are a professional interviewer."
    prompt = f"""
    Resume: {json.dumps(resume_data)}
    Job: {job_description}

    Generate 5 tailored interview questions for this candidate for this specific role.
    Output ONLY valid JSON as a list of strings: ["Q1", "Q2", ...]
    """
    response_text = get_ai_response(prompt, system_instruction)
    json_match = re.search(r"(?:```json)?\s*(\[.*?\])\s*(?:```)?", response_text, re.DOTALL)
    if json_match:
        parsed = _safe_json_loads(json_match.group(1))
        if isinstance(parsed, list):
            return parsed
    return ["Tell me about yourself.", "What are your strengths?", "Where do you see yourself in 5 years?"]
