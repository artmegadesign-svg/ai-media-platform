class MockProvider:
    def chat(self, system: str, user: str) -> str:
        return f"""HOOK:
The future is arriving faster than most people expect.

INSIGHT:
AI is not just automating jobs — it's reshaping entire industries and redefining what work means.

VALUE:
Companies that adopt AI early gain massive efficiency advantages, while others fall behind.

CONCLUSION:
Adaptation is no longer optional — it's survival.
"""
