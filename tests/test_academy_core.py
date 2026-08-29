import unittest
from academy_core import Academy
class T(unittest.TestCase):
 def setUp(self): self.a=Academy()
 def test_identity(self): self.assertEqual(self.a.identity.product_name,"GyanVerse Academy")
 def test_math(self): self.assertEqual(self.a.route(subject="fractions").teacher_id,"kabir_sir")
 def test_science(self): self.assertEqual(self.a.route(student_message="science experiment").teacher_id,"meera_maam")
 def test_counselor(self): self.assertEqual(self.a.route(student_message="I feel stressed").teacher_id,"ananya_maam")
 def test_default(self): self.assertEqual(self.a.route(subject="unknown").teacher_id,"asha_maam")
 def test_profiles(self):
  for p in self.a.list_teachers(): p.validate()
 def test_prompt(self):
  x=self.a.teacher_prompt(self.a.route(subject="maths")); self.assertIn("Never shame",x); self.assertIn("Check understanding",x)
if __name__=='__main__': unittest.main()
