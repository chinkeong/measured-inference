# BRIEF — section 1 "What is being compared"
Write 2 short paragraphs, 90 words total maximum.
FACTS (all measured on one RTX 3090, 24 GB, Ubuntu):
- Two models are compared: Qwen3.5-9B (the base model, used as the fixed
  reference point) and Ornith-1.5-9B (built from it by further training).
- Both are the same 8-bit file format, both 9.11 GiB, both 33 layers.
- They have the same internal shape: same layer count, same context length of
  262,144 tokens, same attention head counts, same memory cost per token.
- Because the shape is identical, anything that differs comes from the training,
  not the design.
- Every number on this page was measured on the same machine, most of them with
  both models running in one alternating session.

RULES THAT BIND YOU
- Invent nothing. Every number you may use is listed below. If a claim needs a
  figure that is not here, leave the claim out.
- This is a WRITING pass, not a fact pass. Do not change a single number, unit
  or condition.
- Plain international English. Short sentences. Common vocabulary. No metaphor,
  no idiom, no wordplay, no cultural reference. Written for two readers at
  once: a non-expert setting up a machine at home or in a small lab, and a
  reader whose first language is not English.
- Banned outright: "sweet spot", "free lunch", "rule of thumb", "punches above
  its weight", "dark horse", "under the hood", "game changer", ""at the end of
  the day". Write what you mean instead.
- Every number carries its unit and its plain meaning in the same sentence.
- Do NOT open with a caveat, a table, or a command. Open with the point.
- Do NOT hedge with "it is worth noting", "interestingly", "it should be said".
- No headings, no bullet lists, no markup of any kind. Prose paragraphs only.
- Do NOT touch the GPU. Do not run anything. You are writing text.
PRINT ONLY THE PARAGRAPHS. No preamble, no sign-off, no commentary.
