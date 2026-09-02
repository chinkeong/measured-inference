# BRIEF — "What this comparison cannot say"
Write 3 short paragraphs, 150 words total maximum. Be direct. This section
exists to stop a reader over-reading the rest of the page.
FACTS:
- It cannot say Ornith is better at any single test. Each test used 25
  questions, and about 10 points of difference can come from chance at that
  size.
- It cannot say why Qwen3.5-9B fails to stop. Swapping the two models' chat
  templates changed nothing, and the reason is that the templates produce
  identical input for these questions, so that experiment could not have found
  a template effect. The training is the only remaining explanation, which is
  elimination rather than proof.
- It says nothing about tasks that use system instructions or tools, where the
  two templates genuinely differ. An agent harness is exactly that case.
- It cannot compare image handling: only Ornith's image support was measured.
- It cannot compare speculative decoding, which speeds up generation: Ornith
  ships an extra small model for it and Qwen3.5-9B does not, so there is
  nothing to compare against.
- The judged scores were produced by a Claude model, and this page was also
  written with Claude. That is a related instrument, and the spread between the
  three judges is published beside every judged number for that reason.

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
