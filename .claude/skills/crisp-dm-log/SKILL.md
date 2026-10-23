---
name: crisp-dm-log
description: Use at the start of work on a component (to write business/data understanding) and at the end of every work session (to log what was done, eval results and next steps) in docs/crisp_dm.md.
---

# Updating docs/crisp_dm.md

`docs/crisp_dm.md` has a component status table and one section per CRISP-DM phase,
each with a `### Log`. Append entries; don't rewrite history.

## Entry format

```markdown
- YYYY-MM-DD — <component> — <what was done / learned, 1–3 sentences>. [→ D-NNN] [→ results/<timestamp>.json]
```
Use today's actual date. Link decisions and eval result files when relevant.

## Before building a component
Add to **Business Understanding**: what question the component answers for the user and
its success criterion (from AGENTS.md metrics).
Add to **Data Understanding**: what data it consumes, what you saw in a real sample
(formats, quirks, edge cases, class balance), open questions.

## At the end of a session
Put each item in the phase it belongs to:
- parsing/cleaning/gold labeling/splits → **Data Preparation**
- prompts, baseline config, rules, thresholds → **Modeling**
- eval run: metric values (with commit + model), comparison to baseline/previous run,
  one-line takeaway → **Evaluation**
- UI/pipeline/tracing → **Deployment**

Then update the **Component status** table row (✓ / date / key metric value).

## Rules
- Facts, not plans: what changed and what was measured. Plans go in a final
  "next:" clause of the entry.
- Numbers in Evaluation must come from a results JSON, never typed from memory.
- Keep entries short; detailed reasoning belongs in `docs/decisions.md` or
  `docs/error_analysis.md` — link there.
