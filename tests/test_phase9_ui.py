import unittest
from gyanverse_ui_helpers import StudentProfile, command_help, safe_text

class Phase9UITests(unittest.TestCase):
    def test_default_profile(self):
        p=StudentProfile()
        self.assertEqual(p.grade,7)
        self.assertEqual(p.board,"CBSE")
    def test_help_is_student_friendly(self):
        text=command_help()
        self.assertIn("Homework",text)
        self.assertIn("Revision",text)
    def test_safe_text_fallback(self):
        self.assertEqual(safe_text(""),"No information available yet.")
        self.assertEqual(safe_text(" Ready "),"Ready")

if __name__ == "__main__": unittest.main()
