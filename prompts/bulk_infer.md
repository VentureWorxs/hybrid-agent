# Bulk Inference Prompt

Use this prompt for high-volume, cost-sensitive, or privacy-sensitive inference tasks.

---

Process the following items using the `ollama_infer` tool to keep costs low and data local.

Task: {task_description}

For each item, apply the following instructions:
{instructions}

Return results in {output_format} format.

Items:
{items}
