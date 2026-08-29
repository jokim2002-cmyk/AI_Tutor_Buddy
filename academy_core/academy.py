from dataclasses import dataclass
from .profiles import DEFAULT_PROFILES
from .router import select_teacher
@dataclass(frozen=True)
class AcademyIdentity:
 project_name:str="AI Tutor Buddy"; product_name:str="GyanVerse Academy"; motto:str="We don't build chatbots. We build teachers."; mission:str="Every child deserves a teacher who understands them before teaching them."
class Academy:
 def __init__(self,profiles=None):
  self.identity=AcademyIdentity(); self.profiles=dict(profiles or DEFAULT_PROFILES); self._validate()
 def _validate(self):
  if "principal_arvind" not in self.profiles or "asha_maam" not in self.profiles: raise ValueError("principal and class teacher are required")
  for p in self.profiles.values(): p.validate()
 def route(self,subject="",student_message=""): return select_teacher(self.profiles,subject,student_message)
 def list_teachers(self): return tuple(self.profiles.values())
 def teacher_prompt(self,p):
  return f"You are {p.name} at {self.identity.product_name}. Role: {p.role.value}. Subject: {p.subject}. Philosophy: {p.philosophy}. Methods: {', '.join(p.teaching_methods)}. Never shame, insult, label, or humiliate a student. Do not guess when unsure. Check understanding before moving forward. Guide with reasoning and hints before revealing a final answer. Use age-appropriate language."
