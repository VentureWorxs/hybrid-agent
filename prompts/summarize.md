# Summarization Prompt

Use this prompt when delegating bulk summarization to Ollama.

---

I need summaries of the following content. This is internal material and must not leave this machine — use the `ollama_summarize` tool for each item.

For each item, focus on:
- Key decisions or conclusions
- Open questions or action items
- Important facts, numbers, or names

Limit each summary to approximately {max_words} words.

Content:
{content}
