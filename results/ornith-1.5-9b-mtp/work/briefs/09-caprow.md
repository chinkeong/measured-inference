# Brief — section 9 troubleshooting, one table row rewritten

Print ONLY the single `<tr>...</tr>` line to stdout. No preamble, no fence.

## The row as it stands

```
<tr><td>Answers run to the length limit and stop mid-sentence</td><td>Greedy decoding degenerates into repetition on this model</td><td>Use the model card's sampler, which includes a repetition penalty. Raising the cap alone does not help: one prompt truncated at 16,384 <em>and</em> at 32,768.</td></tr>
```

## Why it must change

Section 8 of the same page now tells a reader running GPQA-length work to
**start at a 66,935-token cap and expect about 10 % truncation**. That advice is
for the model card's sampler. This row's advice — "raising the cap alone does
not help" — is for GREEDY decoding, where the model degenerates into repetition
and no cap rescues it. Both are true and they read as contradictory.

The row must make its own scope visible so the two do not collide. Two distinct
mechanisms:

- **Greedy decoding**: degenerates into repetition. One prompt truncated at
  16,384 and again at 32,768. A larger cap does not help; the sampler is the fix.
- **The card's sampler**: no repetition loop, but long reasoning genuinely runs
  long. On GPQA Diamond 43 of 198 answers exceeded a 30,000-token cap. Here a
  larger cap DOES help, and section 8 gives the number.

## Constraints

- Keep the three-cell shape: symptom, cause, fix. Keep `<em>` on the existing
  *and* if it survives.
- Both mechanisms must be distinguishable by a reader who reads only this row.
- Do not restate section 8's figures beyond what is needed to point at it; the
  row may reference section 8 as `<a href="#bench">section 8</a>`.
- Every figure already in the row is measured and must survive unchanged:
  16,384 and 32,768. You may add 43 of 198 and 30,000 from section 8.
- Register: `methodology/VOICE.md`. No `we`/`our`/`us`, no boosters or hedges,
  no `vs`/`versus`/`compared to`, British forms, spaced em dash never `--`,
  no comma inside a `-c <digits>` literal, plain space before spelled-out nouns
  (`30,000 tokens`, not `30,000&nbsp;tokens`), `&nbsp;` before symbol units
  (`21.7&nbsp;%`).
- The fix cell states an imperative naming the artefact or value.
