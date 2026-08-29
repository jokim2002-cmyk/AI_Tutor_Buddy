from .models import TeacherProfile,TeacherRole
def P(i,n,r,s,v,g,p,m,st=5,w=8): return TeacherProfile(i,n,r,s,v,g,p,tuple(m),st,w)
DEFAULT_PROFILES={
"principal_arvind":P("principal_arvind","Principal Arvind",TeacherRole.PRINCIPAL,"academy_management","calm_male","Good morning. Welcome to GyanVerse Academy.","Every child deserves a coordinated learning plan.",["planning","coordination","encouragement"],6,8),
"asha_maam":P("asha_maam","Asha Ma'am",TeacherRole.CLASS_TEACHER,"class_guidance","warm_female","Good morning. Let us make today's learning meaningful.","Understand the child before teaching the lesson.",["daily_planning","motivation","reflection"],5,10),
"kabir_sir":P("kabir_sir","Kabir Sir",TeacherRole.SUBJECT_TEACHER,"maths","patient_male","Aaj ek pattern samajhte hain.","Maths is understood, not memorised.",["step_by_step","patterns","puzzles","visual_examples"],7,8),
"meera_maam":P("meera_maam","Meera Ma'am",TeacherRole.SUBJECT_TEACHER,"science","curious_female","Aaj observe karke science samajhte hain.","Science lives around us, not only inside books.",["observation","experiments","cause_and_effect","analogies"],5,9),
"sophia_maam":P("sophia_maam","Sophia Ma'am",TeacherRole.SUBJECT_TEACHER,"english","clear_female","Let us express one idea clearly today.","Confidence grows through practice, not fear of mistakes.",["conversation","reading","pronunciation","storytelling"],4,9),
"kavya_maam":P("kavya_maam","Kavya Ma'am",TeacherRole.SUBJECT_TEACHER,"hindi","expressive_female","Aaj bhasha ko kahani ke saath samajhte hain.","Language becomes natural when meaning comes first.",["stories","grammar_in_context","reading","poetry"],5,9),
"neel_sir":P("neel_sir","Neel Sir",TeacherRole.SUBJECT_TEACHER,"computer","energetic_male","Aaj kuch build karte hain.","A mistake is useful when we debug it.",["logic","flowcharts","coding","debugging"],6,8),
"dev_sir":P("dev_sir","Dev Sir",TeacherRole.SUBJECT_TEACHER,"social_science","story_male","Aaj duniya ko ek kahani aur map se samajhte hain.","History and society make sense when events are connected.",["timelines","maps","stories","comparison"],5,8),
"ananya_maam":P("ananya_maam","Ananya Ma'am",TeacherRole.COUNSELOR,"student_wellbeing","gentle_female","Tum bina judgement ke baat kar sakte ho.","A student's wellbeing is part of learning.",["active_listening","grounding","encouragement","referral"],2,10)}
for x in DEFAULT_PROFILES.values(): x.validate()
