# BRIEF — "Where the two models are the same"
Write 2 short paragraphs, 120 words total maximum. The point of this section is
that sameness is useful news, not an absence of news.
FACTS:
- Identical on every structural field: 33 layers, context length 262,144
  tokens, embedding width 4096, 16 attention heads, 4 key-value heads, head
  size 256, and the same memory cost per token.
- So any measurement of memory use, of how much fits on the card, or of how
  fast the card can move the weights, applies to both models without repeating
  it.
- Practical consequence: a person who has already sized a machine for one of
  these models does not need to size it again for the other.
- The one full-size setup measured: the 8-bit file with the full 262,144-token
  context, image support loaded and the draft model loaded, used 20,336
  megabytes of a 24,122 megabyte budget, leaving 3,786 megabytes spare.
- The models' chat templates differ in text but produce identical input for
  every one of the 175 test questions, because those questions carry no system
  message.

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
