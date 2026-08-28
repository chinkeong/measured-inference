# WRITING — who writes the prose, how they are briefed, and how the output is checked

`templates/REPORT-SPEC.md` says what published prose must BE (the two-voice
law). This file says how it gets WRITTEN: which model, how it is invoked, what
a brief must contain, and what must be verified before the result is committed.

Read this before writing or rewriting any published section. Everything here
was learned by getting it wrong on this campaign; the failure is cited beside
each rule, because a rule without its failure is just a preference.

---

## 1. Prefer Opus 4.6 for prose. Do not block on it.

**Published prose should be written by Claude Opus 4.6 whenever it is
available.** This is the person's standing preference and it is about voice:
4.6 produces the page's register more reliably than the model orchestrating
the campaign, which drifts toward the changelog tone this page has already been
corrected for three times.

**If Opus 4.6 is not available, write it anyway.** An unavailable model is not
a reason to leave a measurement unpublished or a defect uncorrected. Write it
in the campaign model, note in the commit message that 4.6 was unavailable, and
queue a voice pass for when it returns. **A correct paragraph in the wrong
voice beats a missing paragraph.** Never stop and wait; never ask.

The orchestrating model still owns everything that is not prose: which numbers
are true, which conditions travel with them, what the defect is, and whether
the result may be published at all. **4.6 is the writer, not the adjudicator.**

## 2. Invoke it as a PowerShell argument array. Never through cmd.

```powershell
$prompt = @"
Read the brief at $sp\<name>-brief.md and carry it out completely.
...
"@
& claude --dangerously-skip-permissions --model claude-opus-4-6 -p $prompt 2>&1 |
    Out-File $log -Encoding utf8 -Append
```

**Never `cmd /c "claude -p \"...\""`.** The quoting collapses on the way
through, the instance starts, receives nothing, replies asking what you would
like it to read, and **exits 0**. A success-shaped failure: exit code clean,
log present, no work done. Observed 2026-08-27.

Write the brief to a FILE and pass its path. A long prompt inlined into the
command line is the same trap with a longer fuse.

## 3. One writer per file at a time.

Two writing processes editing one file will both win and both lose.
`index.html` moved 669,876 -> 666,671 -> 668,246 -> 671,463 bytes on 2026-08-27
while a timed-out writer was still running and a hand-edit landed on top of it.
The file settled sound only because it was checked; nothing warned.

If a pass is queued behind another, **queue it — do not parallelise it.**
Different files may be written in parallel; the same file may not.

## 4. What a brief must contain

A brief that omits any of these produces prose that has to be thrown away.

1. **The file to edit and the exact boundaries of the section.** Anchor ids,
   or the first and last markup of the block.
2. **Every fact, with its conditions**, in a list. The writer must never have
   to go and find a number, because a writer that goes looking is a writer that
   guesses.
3. **`Invent nothing.`** Stated literally. And: if a needed figure is not in
   the brief, leave the claim out and say so in the report.
4. **Whether numbers may move.** For a voice pass the answer is always no, and
   it must be said: *"This is a voice and structure pass, not a fact pass. Do
   not change a single number."*
5. **What to read first** for voice — the specific neighbouring sections, by id.
6. **The house markup**: which classes carry which meaning, entity conventions,
   line endings, and `zero <script> tags`.
7. **`Do NOT touch the GPU`**, whenever a measurement is or might be running.
8. **A report to print**, itemised. Ask what changed, ask for confirmation no
   number moved, and ask for the tag balance. The report is not the
   verification — it is a statement to be checked against.

## 5. Verify the artefact, never the exit code

**A writer that exits 0 has not necessarily written anything.** Record the byte
count before, and confirm it changed after. Then, independently of anything the
writer said about its own work:

- tags balanced for `p div table tr td th pre span b code em strong section a li`
- `<script>` count is still zero
- every anchor id the contents list links to still exists
- **every number re-checked against the committed artefact it came from**

That last one is not ceremony. On 2026-08-28 a section drafted in a hurry
published a second-half throughput of 52.5 t/s where the artefact said 54.2,
and a Wilson interval upper bound of 97.6 where it was 97.5. Both were caught
by reading the artefact, not by reading the prose.

**Treat the writer's self-report as a claim, not as evidence.** One 4.6 report
on this campaign lost count of its own tags mid-sentence and corrected itself
twice inside the answer; the underlying edit was fine, which is exactly why the
report could not be what established that.

## 6. The writer may not decide what is true

The writer rewrites prose. It does not:

- decide whether a result is publishable,
- choose which noise floor a claim is tested against,
- soften a retraction,
- resolve a conflict between two measurements.

Those are adjudications and they belong to `methodology/REASONING.md`. If a
writer's output changes what the page CLAIMS rather than how it reads, the pass
failed and is rejected whole — not patched.

## 7. Fix the prose where it is generated

If the prose is emitted by a generator, rewriting the output is not a fix: the
next run puts the old text back. Rewrite the generator.

The two agentic reports published identical figure captions naming
`UD-IQ4_XS at 4.223 bits per weight` under both the 4-bit AND the 2-bit run,
because five plot modules baked the conditions into caption strings instead of
taking them from the run. Every caption in the 2-bit report described a file
that run never loaded. Editing the two HTML files would have hidden that until
the next regeneration.

**Conditions in generated prose come from the run, or they are a defect.**
