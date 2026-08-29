from dataclasses import dataclass
from enum import Enum
from typing import Tuple
class TeacherRole(str,Enum):
 PRINCIPAL="principal"; CLASS_TEACHER="class_teacher"; SUBJECT_TEACHER="subject_teacher"; COUNSELOR="counselor"
@dataclass(frozen=True)
class TeacherProfile:
 teacher_id:str; name:str; role:TeacherRole; subject:str; voice_key:str; greeting:str; philosophy:str; teaching_methods:Tuple[str,...]; strictness:int=5; warmth:int=8
 def validate(self):
  if not self.teacher_id.strip() or not self.name.strip(): raise ValueError("teacher_id and name are required")
  if not 0<=self.strictness<=10 or not 0<=self.warmth<=10: raise ValueError("strictness and warmth must be 0..10")
  if not self.teaching_methods: raise ValueError("at least one teaching method is required")
