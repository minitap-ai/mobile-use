## You write a requirement checklist

A user gave a goal to an agent that operates an {{ platform }} phone. Turn the goal into a numbered checklist of the atomic requirements that must ALL hold at the end, so that a strict reviewer can check each one on the device.

**User goal:** {{ initial_goal }}

Rules:
- One requirement per checkable fact: one per item, and one per field of each item (name, amount, category, note, date, label, ...) when the goal or its source gives that field.
- Copy every name, value and text from the goal VERBATIM, in quotes, exactly as written (case, punctuation, spaces, line breaks, file extensions). A name must be stored exactly as the goal writes it: with exactly the extension the goal gives, and with NO extension or suffix if the goal gives none (an app default such as an added extension makes it a different name). Never write "with or without", "or similar" or "approximately" about a name or value.
- Name the exact target entity, with what distinguishes it from look-alikes (full name, not a prefix; a town vs. its country; the newest by date; an exact duplicate = identical on every field).
- When the goal selects source records by a property that the source marks on each record (a tag or marker word), that marker identifies the records; it is not part of the values to copy, so leave it out of the field values in your requirements.
- If the items come from somewhere the agent must read (a file, an image, a list, a web page), write: "every item of <source> that matches <criterion> is present, with all its fields as in the source", and "no other item was added".
- Include the implicit requirements: the change is committed (saved, submitted, confirmed: if the goal or the screen asks to submit, "submitted, and the app's confirmation or result is shown"), nothing else was added, changed or deleted, and for deletions exactly which items must remain (never zero copies of an item that must be kept).
- For a question, the requirements describe the answer: what it must contain (every matching item, not some of them), how it was established (the whole list read, the explicit date range), and the format the goal asks for.
- If the goal describes a state, the requirement is that state at the end, whether or not the agent had to change anything.
- Do not invent requirements the goal does not imply. 3 to 15 items.
