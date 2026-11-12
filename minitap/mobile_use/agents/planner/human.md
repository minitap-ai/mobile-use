Here is your input.

---

**Action (plan or replan)**: {{ action }}

**Initial Goal**: {{ initial_goal }}
{% if p2_checklist_text %}
**Goal checklist (every requirement must hold at the end)**:
{{ p2_checklist_text }}
{% endif %}{% if p2_calendar %}
{{ p2_calendar }}
{% endif %}
{% if action == "replan" %}
Relevant only if action is replan:

**Previous Plan**: {{ previous_plan }}
**Agent Thoughts**: {{ agent_thoughts }}
{% endif %}
