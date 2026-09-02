# BRIEF — "Speed"
Write 2 short paragraphs, 110 words total maximum.
FACTS:
- Measured in one session with the two models alternating, so a slow moment on
  the machine could not be mistaken for a property of one model.
- Qwen3.5-9B 84.17 tokens per second; Ornith-1.5-9B 83.80. Ratio 0.9956.
- With the settings the model makers recommend, which include a penalty that
  discourages repetition: Qwen3.5-9B 78.52, Ornith 78.77. Ratio 1.0032.
- Those recommended settings cost about 0.70 milliseconds on every token. That
  is the cost of the extra sampling work, not of the model.
- Both models repeated themselves when run with the simplest setting, which is
  always taking the most likely next word. The repetition comes from the shared
  base model; neither model's training introduced it.
- 84 tokens per second is faster than a person reads.

RULES THAT BIND YOU
- You have NO file access and need none. Do not attempt to write, create or save
  any file. Do not mention files, permissions, or saving. Print the prose only.
- Invent nothing. Every number you may use is listed below. If a claim needs a
  figure that is not here, leave the claim out.
- This is a WRITING pass, not a fact pass. Do not change a single number, unit
  or condition.
- Plain international English. Short sentences. Common vocabulary. No metaphor,
  no idiom, no wordplay, no cultural reference. Written for two readers at
  once: a non-expert setting up a machine at home or in a small lab, and a
  reader whose first language is not English.
- Banned outright: "sweet spot", "free lunch", "rule of thumb", "punches above
  its weight", "dark horse", "under the hood", "game changer".
- Every number carries its unit and its plain meaning in the same sentence.
- Do NOT open with a caveat, a table, or a command. Open with the point.
- Do NOT hedge with "it is worth noting", "interestingly", "it should be said".
- No headings, no bullet lists, no markup, no horizontal rules. Prose only.
- Do NOT touch the GPU. Do not run anything.
OUTPUT: the paragraphs and nothing else. No preamble. No sign-off.
