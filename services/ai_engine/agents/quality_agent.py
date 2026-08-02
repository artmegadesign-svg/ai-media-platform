class QualityAgent:

    def check(self, content: str) -> dict:

        issues = []
        score = 100

        if not content:
            issues.append("Empty content")
            score -= 50

        if len(content) < 200:
            issues.append("Content too short")
            score -= 20


        required_sections = [
            "HOOK",
            "INSIGHT",
            "VALUE",
            "CONCLUSION"
        ]


        upper_content = content.upper()

        for section in required_sections:
            if section not in upper_content:
                issues.append(
                    f"Missing section: {section}"
                )
                score -= 10


        if score < 0:
            score = 0


        return {
            "score": score,
            "approved": len(issues) == 0,
            "issues": issues
        }
