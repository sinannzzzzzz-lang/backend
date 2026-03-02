import google.generativeai as genai
from django.conf import settings
import json
import re

def get_gemini_response(prompt, system_instruction=""):
    try:
        if not settings.GEMINI_API_KEY:
            return "Error: GEMINI_API_KEY is not set in .env file."
            
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=system_instruction)
        response = model.generate_content(prompt)
        if not response.text:
            return "Error: Empty response from AI model."
        return response.text
    except Exception as e:
        return f"Error: {str(e)}"

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
    response_text = get_gemini_response(prompt, system_instruction)
    
    if response_text.startswith("Error:"):
        print(f"AI Error: {response_text}")
        return {
            "full_name": "Error Parsing Resume",
            "summary": response_text,
            "skills": [],
            "experience": [],
            "education": []
        }
    
    # Extract JSON between ```json and ``` if present
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    
    # Fallback: find any {}
    json_match = re.search(r'(\{.*\})', response_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
        
    return {}

def polish_summary_ai(summary):
    system_instruction = "You are a professional resume writer."
    prompt = f"Rewrite this professional summary to be more impactful and HR-friendly:\n\n{summary}"
    return get_gemini_response(prompt, system_instruction)

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
    response_text = get_gemini_response(prompt, system_instruction)
    
    json_match = re.search(r'(?:```json)?\s*(\{.*?\})\s*(?:```)?', response_text, re.DOTALL)
    if json_match:
        data = json.loads(json_match.group(1))
        return {
            'score': data.get('score', 0),
            'missing_skills': data.get('missing_skills', []),
            'explanation': data.get('explanation', '')
        }
    return {'score': 0, 'missing_skills': [], 'explanation': 'AI processing failed.'}

def generate_jd_ai(job_title, extra_info=""):
    system_instruction = "You are an expert HR manager."
    prompt = f"Write a comprehensive Job Description for the role: {job_title}. Extra info: {extra_info}. Include a list of required skills."
    return get_gemini_response(prompt, system_instruction)

def generate_interview_questions_ai(resume_data, job_description):
    system_instruction = "You are a professional interviewer."
    prompt = f"""
    Resume: {json.dumps(resume_data)}
    Job: {job_description}
    
    Generate 5 tailored interview questions for this candidate for this specific role.
    Output ONLY valid JSON as a list of strings: ["Q1", "Q2", ...]
    """
    response_text = get_gemini_response(prompt, system_instruction)
    json_match = re.search(r'(?:```json)?\s*(\[.*?\])\s*(?:```)?', response_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    return ["Tell me about yourself.", "What are your strengths?", "Where do you see yourself in 5 years?"]
