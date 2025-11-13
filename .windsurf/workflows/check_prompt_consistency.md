---
description: Prompt-Schema Consistency Check
auto_execution_mode: 3
---

Review the agent's prompt and structured output schema for misalignment. Specifically:

1. **Locate the files:**
   Based on the information given my the user about WHAT to check, locate :
   - Agent prompt: likely a .md or .jinja file.
   - Output schema: likely the .with_structured_output code snippet located in the same file that calls the prompt.

If the user did not give you information, or you do not find the relevant files, ask the user to clarify its request.

2. **Check for misalignment between:**

   - How the prompt describes the output structure (wording, examples)
   - What the Pydantic schema actually expects (field names, types, nesting)

3. **Common issues to look for:**

   - Ambiguous wording
   - Examples (chain of thoughts) showing different structure than schema requires
   - Missing mention of required nested objects or field names
   - Prompt describes flat structure when schema expects nested objects

4. **Fix approach:**

   - Update prompt wording to explicitly match schema structure
   - Use clear language
   - Ensure examples align with actual schema expectations
   - Don't modify schema unless business logic is wrong

5. **Validation:**
   - Confirm prompt explicitly describes object structure matching Pydantic models
   - Verify field names mentioned in prompt match schema exactly
   - Check that nesting levels are clearly communicated

Report any misalignments found and suggest minimal prompt edits to fix them.
