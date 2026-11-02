"""
Unit tests for Clue's Interview Modes, Prompt Conditioning, and Code Triggers
"""

import unittest
from clue.core.interview_modes import (
    InterviewMode,
    build_copilot_prompt,
    has_explicit_code_request,
)


class TestInterviewModes(unittest.TestCase):

    def test_explicit_code_request_detection(self):
        # Should detect code intent
        self.assertTrue(has_explicit_code_request("Write code for 3Sum"))
        self.assertTrue(has_explicit_code_request("Can you implement this in C++?"))
        self.assertTrue(has_explicit_code_request("Give me the code for binary search"))
        self.assertTrue(has_explicit_code_request("Write a function to detect cycle"))

        # Should NOT trigger code for conceptual / behavioral questions
        self.assertFalse(has_explicit_code_request("What is TCP?"))
        self.assertFalse(has_explicit_code_request("How does virtual memory work?"))
        self.assertFalse(has_explicit_code_request("Tell me about a time you handled conflict"))
        self.assertFalse(has_explicit_code_request("Explain the trade-offs between SQL and NoSQL"))

    def test_prompt_generation_without_code(self):
        prompt = build_copilot_prompt(
            mode=InterviewMode.CODING_INTERVIEW,
            user_query="What is the difference between TCP and UDP?",
            force_code=False,
        )
        self.assertIn("NO CODE REQUESTED", prompt)
        self.assertIn("Do NOT include any code blocks", prompt)
        self.assertIn("ZERO RUBBISH", prompt)

    def test_prompt_generation_with_code(self):
        prompt = build_copilot_prompt(
            mode=InterviewMode.CODING_INTERVIEW,
            user_query="Write C++ code for Two Sum",
            force_code=True,
        )
        self.assertIn("The user/interviewer wants the code", prompt)
        self.assertIn("CODE SOLUTION", prompt)
        # Verify code simplicity, short variable names, and minimal data structures
        self.assertIn("SHORT VARIABLE NAMES", prompt)
        self.assertIn("NO UNNECESSARY DATA STRUCTURES", prompt)
        self.assertIn("EASY TO READ & TYPE LIVE", prompt)

    def test_coding_interview_system_prompt_rules(self):
        from clue.core.interview_modes import MODE_SYSTEM_PROMPTS
        prompt = MODE_SYSTEM_PROMPTS[InterviewMode.CODING_INTERVIEW]
        self.assertIn("SHORT VARIABLE NAMES", prompt)
        self.assertIn("NO UNNECESSARY DATA STRUCTURES", prompt)
        self.assertIn("EASY TO UNDERSTAND, READ & WRITE", prompt)



if __name__ == "__main__":
    unittest.main()
