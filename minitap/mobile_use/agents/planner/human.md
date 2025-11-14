Here is your input.

---

**Action (plan or replan)**: {{ action }}

**Initial Goal**: {{ initial_goal }}

{% if action == "replan" %}
Relevant only if action is replan:

**Previous Plan**: {{ previous_plan }}
**Agent Thoughts**: {{ agent_thoughts }}
{% endif %}
