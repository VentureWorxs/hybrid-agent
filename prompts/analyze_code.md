# Code Analysis Prompt

Use this prompt when delegating sensitive code analysis to Ollama.

---

Analyze the following {language} code using the `ollama_analyze_code` tool. This code is proprietary and must stay local — do not send it to any external API.

Focus: {focus}

After receiving the analysis, synthesize the findings and highlight the top issues that need immediate attention.

Code:
```{language}
{code}
```
