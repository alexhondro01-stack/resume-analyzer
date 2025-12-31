from crewai import Agent, Task, Crew, Process, LLM
import tools
import os
from pathlib import Path
from dotenv import load_dotenv

# --- ROBUST ENVIRONMENT LOADING ---
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)

# FIX: Disable telemetry and signals for compatibility
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
            api_key = os.getenv("GOOGLE_API_KEY")
            return LLM(
                model="gemini/gemini-2.5-flash",
                api_key=api_key,
                temperature=0.1
            )
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            return LLM(
                model="gpt-4.1-nano",
                api_key=api_key,
                temperature=0.1
            )

    def analyze(self):
        """Step 1: Identify gaps and success likelihood."""
        resume_content = tools.extract_text(self.resume_path)
        
        matcher_agent = Agent(
            role='Senior Recruitment Strategist',
            goal='Identify missing high-impact keywords and evaluate success likelihood.',
            backstory='Expert at ATS optimization and identifying professional qualification gaps.',
            llm=self.llm,
            verbose=True,
            allow_delegation=False
        )

        match_task = Task(
            description=(
                f"TARGET JOB DESCRIPTION:\n{self.jd_text}\n\n"
                f"USER RESUME CONTENT:\n{resume_content}\n\n"
                "INSTRUCTIONS:\n"
                "1. Identify the 'Must-Have' Keywords from the JD missing in the resume.\n"
                "2. Provide an Overall Success Score (XX/100).\n"
                "3. List specific changes needed categorized by 'Requirements' and 'Qualifications'.\n"
                "Categorize gaps as [HIGH], [MEDIUM], or [LOW] priority."
            ),
            expected_output="A structured report including a Score/100, missing keywords, and recommended changes.",
            agent=matcher_agent
        )

        crew = Crew(agents=[matcher_agent], tasks=[match_task], process=Process.sequential)
        return crew.kickoff()

    def optimize(self, selected_fixes):
        """Step 2: Rewrite resume and summarize transformations."""
        resume_content = tools.extract_text(self.resume_path)

        customizer_agent = Agent(
            role='Resume Optimizer',
            goal='Inject missing keywords naturally and summarize changes.',
            backstory='Expert at blending technical keywords into professional experience bullet points.',
            llm=self.llm,
            verbose=True,
            allow_delegation=False
        )

        rewrite_task = Task(
            description=(
                f"ORIGINAL RESUME:\n{resume_content}\n\n"
                f"FIXES TO APPLY:\n{selected_fixes}\n\n"
                "INSTRUCTIONS:\n"
                "1. Rewrite the resume incorporating these keywords naturally. Start with 'REVISED RESUME'.\n"
                "2. After the resume text, add a section called 'TRANSFORMATION LOG' where you list exactly which "
                "sections were updated and how the new keywords were integrated."
            ),
            expected_output="The full revised resume followed by a detailed TRANSFORMATION LOG.",
            agent=customizer_agent
        )

        crew = Crew(agents=[customizer_agent], tasks=[rewrite_task], process=Process.sequential)
        return crew.kickoff()