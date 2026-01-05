from crewai import Agent, Task, Crew, Process, LLM
import tools
import os
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment is loaded
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)

# Suppress telemetry
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"

class ResumeCrew:
    def __init__(self, resume_path, jd_text, provider="OpenAI"):
        self.resume_path = resume_path
        self.jd_text = jd_text
        self.provider = provider
        self.llm = self._setup_llm()

    def _setup_llm(self):
        """Configures the LLM using the native CrewAI LLM class."""
        if self.provider == "Gemini":
            api_key = os.getenv("GOOGLE_API_KEY", "").strip().strip("'").strip('"')
            return LLM(
                model="gemini/gemini-2.5-flash",
                api_key=api_key if api_key else None,
                temperature=0.1
            )
        else:
            api_key = os.getenv("OPENAI_API_KEY", "").strip().strip("'").strip('"')
            return LLM(
                model="gpt-4.1-nano",
                api_key=api_key if api_key else None,
                temperature=0.1
            )

    def analyze(self):
        """Analyzes the resume against the JD with a focus on matches and gaps."""
        resume_content = tools.extract_text(self.resume_path)
        
        matcher_agent = Agent(
            role='Senior Recruitment Strategist',
            goal='Provide a balanced view of candidate matches and missing requirements, identifying what is missing vs what can be repurposed.',
            backstory=(
                'You are an expert recruiter. You excel at identifying both the strengths '
                'that make a candidate a good fit and the critical gaps. You have a keen eye for '
                'transferable skills and can spot when a candidate has the right experience but '
                'is simply using the wrong terminology.'
            ),
            llm=self.llm,
            verbose=True,
            allow_delegation=False
        )

        match_task = Task(
            description=(
                f"TARGET JOB DESCRIPTION:\n{self.jd_text}\n\n"
                f"USER RESUME CONTENT:\n{resume_content}\n\n"
                "INSTRUCTIONS:\n"
                "Provide a report in the following EXACT format:\n"
                "1. Overall Score: [Score]/100\n\n"
                "2. SECTION: MATCHES\n"
                "List top 5 skills or experiences the candidate ALREADY has that match the JD.\n\n"
                "3. SECTION: JOB REQUIREMENTS GAPS\n"
                "For each missing keyword/tool, indicate if it is:\n"
                "- [MISSING]: Completely absent from the resume.\n"
                "- [REPURPOSE]: The candidate has related experience that can be reworded to match this.\n"
                "Format: - [MISSING/REPURPOSE][PRIORITY] Keyword/Skill\n"
                "Priorities: [HIGH], [MEDIUM], or [LOW].\n\n"
                "4. SECTION: QUALIFICATION GAPS\n"
                "For each missing experience or degree, indicate if it is:\n"
                "- [MISSING]: Completely absent.\n"
                "- [REPURPOSE]: Can be mapped from other experience.\n"
                "Format: - [MISSING/REPURPOSE][PRIORITY] Qualification/Experience"
            ),
            expected_output="A structured report with Score, Matches, and Gaps categorized by Missing vs Repurpose.",
            agent=matcher_agent
        )

        crew = Crew(agents=[matcher_agent], tasks=[match_task], process=Process.sequential)
        return crew.kickoff()

    def optimize(self, selected_fixes):
        """Rewrites the resume to integrate selected improvements."""
        resume_content = tools.extract_text(self.resume_path)

        customizer_agent = Agent(
            role='Senior Resume Optimization Specialist',
            goal='Rewrite the resume to maximize interview chances by highlighting impact, clarity, and ATS alignment without fabricating facts.',
            backstory=(
                "You are a Resume Optimization Agent specializing in tailoring resumes for competitive roles. "
                "Your job is to take an existing resume and user-provided context to provide clear, actionable improvements.\n\n"
                "Core Responsibilities:\n"
                "- Highlight Impact: Ensure bullet points emphasize measurable outcomes (metrics, KPIs, efficiency gains).\n"
                "- Clarity & Conciseness: Improve phrasing to be professional, concise, and results-driven. Remove fluff.\n"
                "- ATS Optimization: Seamlessly integrate the specific keywords provided in the 'FIXES TO APPLY' list.\n"
                "- Career Narrative: Ensure the resume tells a clear story of growth and professional maturity.\n"
                "- Tone & Style: Maintain a confident, professional, and achievement-oriented tone.\n\n"
                "Constraints:\n"
                "- Do not invent false experiences. Only reframe and strengthen what the candidate provides or specific context they have added for missing skills.\n"
                "- Ensure the final output is tailored for hiring managers and recruiters."
            ),
            llm=self.llm,
            verbose=True,
            allow_delegation=False
        )

        rewrite_task = Task(
            description=(
                f"ORIGINAL RESUME:\n{resume_content}\n\n"
                f"FIXES TO APPLY (includes user context for missing items):\n{selected_fixes}\n\n"
                "INSTRUCTIONS:\n"
                "1. Rewrite the resume incorporating the selected fixes. \n"
                "   - For 'REPURPOSE' items: Rephrase existing bullet points to match the new keywords/skills.\n"
                "   - For 'MISSING' items: Use the user-provided context to create NEW, high-impact bullet points in the appropriate section.\n"
                "2. Apply the 'Core Responsibilities' from your backstory (Impact, Clarity, ATS).\n"
                "3. Start the response with 'REVISED RESUME'.\n"
                "4. After the resume text, add a section called 'TRANSFORMATION LOG' explaining key changes and how specific gaps were addressed."
            ),
            expected_output="The full revised resume followed by a detailed TRANSFORMATION LOG.",
            agent=customizer_agent
        )

        crew = Crew(agents=[customizer_agent], tasks=[rewrite_task], process=Process.sequential)
        return crew.kickoff()