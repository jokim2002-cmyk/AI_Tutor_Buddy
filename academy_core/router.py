import re
ALIASES={"maths":("math","maths","mathematics","ganit","fraction","algebra","geometry"),"science":("science","physics","chemistry","biology","experiment"),"english":("english","grammar","pronunciation","essay","sentence"),"hindi":("hindi","vyakaran","kavita"),"computer":("computer","coding","python","programming","software"),"social_science":("history","geography","civics","social science","sst")}
def select_teacher(profiles,subject="",student_message=""):
 text=f"{subject} {student_message}".lower()
 if any(w in text for w in ("sad","afraid","scared","stress","anxious","panic","dar lag","dukhi")): return profiles["ananya_maam"]
 for canonical,aliases in ALIASES.items():
  if any(a in text for a in aliases):
   for p in profiles.values():
    if p.subject==canonical:return p
 return profiles["asha_maam"]
