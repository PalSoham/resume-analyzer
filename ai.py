import os
import json
import re
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)

SYSTEM_PROMPT = """
You are a senior technical recruiter and resume strategist
with 20 years of experience hiring for top-tier engineering,
product, and design teams.

You give honest, actionable, recruiter-grade analysis.

You are direct and specific — never vague.
You flag real issues.
You do not flatter.
"""

ANALYSIS_PROMPT = """
Analyze the following resume for the target role: "{role}"

Evaluate with the eye of a technical recruiter who has
10 seconds to decide yes or no.

Return a single JSON object with EXACTLY these keys:

{{
  "ats_score": <integer 0–100>,
  "recruiter_impression": "<2–3 sentence honest gut reaction a recruiter would have>",
  "strengths": ["<specific strength>", ...],
  "weaknesses": ["<specific weakness>", ...],
  "skills_present": ["<skill>", ...],
  "missing_skills": ["<skill critical for {role} but absent>", ...],
  "keyword_relevance": "<short assessment of how well resume keywords match {role} job postings>",
  "experience_evaluation": "<evaluation of depth, relevance, and progression of experience>",
  "project_quality": "<assessment of listed projects — specificity, impact, complexity>",
  "measurable_impact": "<does the resume show numbers and outcomes, or just responsibilities?>",
  "resume_formatting_feedback": "<feedback on structure, length, layout, scannability>",
  "summary_quality": "<assessment of the resume summary/objective if present, or note its absence>",
  "action_plan": ["<concrete improvement step>", ...],
  "interview_questions": ["<likely interview question based on resume gaps>", ...]
}}

Rules:
- Return ONLY valid JSON
- Do NOT wrap JSON in markdown
- Do NOT explain anything outside JSON
- Be role-specific
- missing_skills must be critical for {role}
- action_plan must be concrete and prioritized
- ats_score should reflect keyword density, formatting, and role alignment

Resume:
{resume}
"""


def _extract_json(text: str) -> dict:
    """Extract JSON safely from Gemini response."""

    text = text.strip()

    # Remove markdown fences if Gemini adds them
    text = re.sub(r"```json", "", text)
    text = re.sub(r"```", "", text)

    start = text.find("{")
    end = text.rfind("}") + 1

    if start == -1 or end == 0:
        raise ValueError("No JSON object found")

    json_text = text[start:end]

    return json.loads(json_text)


def analyze_resume(resume_text: str, role: str) -> dict:

    prompt = ANALYSIS_PROMPT.format(
        role=role,
        resume=resume_text
    )

    try:

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{SYSTEM_PROMPT}\n\n{prompt}"
        )

        content = response.text.strip()

        return _extract_json(content)

    except json.JSONDecodeError as e:

        return {
            "error": f"Failed to parse AI JSON: {str(e)}"
        }

    except Exception as e:

        return {
            "error": f"Analysis failed: {str(e)}"
        }