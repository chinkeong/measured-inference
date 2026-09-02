# BRIEF — "The recipes"
Write 3 short paragraphs, 170 words maximum. A reader must be able to act on
this without reading anything else on the page.
FACTS:
- Recommended setup for quality: the 8-bit file, all layers on the graphics
  card, the full 262,144-token context, image support loaded, speculative
  decoding off. It produces 78.60 tokens per second, faster than a person reads.
- That setup uses 20,336 megabytes of a 24,122 megabyte budget, with image
  support and the small helper model both loaded, leaving 3,786 megabytes free.
- Why 8-bit and not smaller: the 8-bit file disagrees with the original
  unshrunk model on 2.4 percent of words. The 4-bit file disagrees on 14.1
  percent, and the 2-bit file on 24.0 percent. Smaller files are faster but
  they answer differently.
- Faster setup: the 4-bit file with speculative decoding turned on reaches
  148.03 tokens per second, 1.238 times faster than the same file without it.
- Important warning about the faster setup: turning speculative decoding on
  changes the answer. It is not the same answer produced faster. This was
  checked by running the same question twice with the setting on and twice with
  it off; the repeats matched each other exactly, so the difference is the
  setting and not chance.

RULES THAT BIND YOU
- You have NO file access and need none. Do not attempt to write or save any
  file. Do not mention files, permissions or saving. Print the prose only.
- Invent nothing. Every number you may use is listed below. If a claim needs a
  figure that is not here, leave the claim out.
- This is a WRITING pass, not a fact pass. Do not change a number, unit or
  condition.
- Plain international English. Short sentences. Common vocabulary. No metaphor,
  no idiom, no wordplay. Written for two readers at once: a non-expert setting
  up a machine at home or in a small lab, and a reader whose first language is
  not English.
- Banned: "sweet spot", "free lunch", "rule of thumb", "under the hood",
  "game changer", "punches above its weight".
- Every number carries its unit and its plain meaning in the same sentence.
- Do NOT open with a caveat, a table or a command. Open with the point.
- Do NOT hedge with "it is worth noting", "interestingly", "notably".
- No headings, no bullets, no markup, no horizontal rules. Prose only.
- Do NOT touch the GPU.
OUTPUT: the paragraphs and nothing else. No preamble, no sign-off.
