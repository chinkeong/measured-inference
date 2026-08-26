# Where the limit actually is, and which layer can move it

Everything below is measured on one machine — RTX 3090 (24 GB, 936 GB/s spec),
i5-13600KF (6P+8E, 20 threads), Windows 11, llama.cpp build 10502 — and the
tier rule holds throughout: **in-band GPU board power only.** The power supply,
CPU, system memory, drives and display are excluded and unmeasured. Nothing
here may be called system power.

---

## The one finding everything else hangs off

**Speculative decoding moves this workload off the memory roofline and onto the
power limit.** Three independent measurements agree, which is why it is worth
stating first:

| evidence | reading |
|---|---|
| decode measured at **99.16 t/s** | the plain-decode ceiling is 936 GB/s ÷ 14.25 GB = **65.7 t/s**. The observed rate EXCEEDS it, so one-weight-pass-per-token cannot explain it |
| MTP mean accepted length **3.55** | real traffic = 99.16/3.55 × 14.25 GB = **398 GB/s = 43% of roofline** |
| memory controller measured **~60% busy**, SM 86–95% | agrees with 43%; the memory system is idle enough to be nobody's constraint |
| `sw_power_cap` **Active on every throttle sample**, thermal never | the SM clock sags 1620–1695 while the memory clock stays pinned at 9501 |

And the counter-case, from the same week:

| drafter off, 45.2 t/s | traffic = 644 GB/s = **69% of roofline** → bandwidth-bound |

**So the answer to "what is this limited by" is not a property of the chip. It
is a property of whether the model ships a draft head.** Same silicon, same
file, same flags — one setting moves the bottleneck from the memory system to
power delivery.

---

## Hardware / silicon

| lever | measured effect | verdict |
|---|---|---|
| wider memory bus | traffic is 43% of the existing bus with speculation on | **buys nothing** for speculating workloads; buys a lot without one |
| more compute | SM already 86–95% busy and clock-clipped by the power cap | **would be clipped**, not realised |
| power delivery / efficiency | `sw_power_cap` active 100% of throttle samples, thermal 0% | **the binding constraint** |
| memory **capacity** | the entire quant ladder exists because 24 GB is the ceiling; 2.595 bpw fits where 4.223 does not | **the constraint that decides what runs at all** |
| PCIe width | 59–314 MB/s observed on Gen4 ×16 | **null** — not a constraint, recorded so nobody spends on it |
| storage | ~100–133 KB/s steady state, pages-in = 0 | **null** in steady state; matters only at load |

The uncomfortable one: **capacity, not bandwidth, is what a local-inference part
is short of.** Every quality result in this campaign is a consequence of making
the file small enough to fit, and each rung down costs measurable accuracy.

## Firmware / power management

| lever | measured effect |
|---|---|
| 350 → **300 W** cap | −5.0% throughput, −11.2% board power, **−6.5% J/token** |
| 350 → **250 W** cap | −12.8% throughput, −24.8% board power, **−13.7% J/token** |

**Capping improves efficiency at both levels** — throughput falls more slowly
than power does, so the stock 350 W sits past the efficiency knee.

**A caveat that is itself a finding, and a gap I have not closed.** Those
numbers were measured on synthetic decode whose mean draw is **305 W against a
350 W limit** — a workload that never reaches the cap. Agentic coding sits
**at** the cap, throttled on essentially every sample. The published cap curve
therefore describes a regime this workload is not in, and it should not be
assumed to transfer. Re-measuring the cap sweep under a capped workload is the
open item.

**An unexploited firmware lever, visible in the telemetry.** The memory clock
holds 9501 MHz while the SM clock is pulled down to 1620–1695 by the power cap
— during a phase where the memory system is 57% idle. Power is being spent
holding a clock the workload is not using. A phase-aware policy that traded
memory clock for SM clock during speculative verify would be spending the same
watts on the resource that is actually saturated. Unmeasured; llama.cpp cannot
express it and the driver does not expose it.

## Software / runtime

| lever | measured effect |
|---|---|
| **speculation (MTP)** | 45.2 → 99.2 t/s, **2.2×**. The largest single lever anywhere in this table |
| **quantisation format** | `Q2_0` decodes **30% faster than `IQ2_S`** at 70 MiB *less* memory. Not bandwidth — IQ formats use codebook lookups that cost compute per weight |
| KV precision `q4_0` vs `f16` | **no measurable retrieval cost** to 119,435 tokens against 3,600 distractors; saves cache memory outright |
| `--load-mode none` | **12.2 GB** less resident host RAM, 4 s slower load, **0 throughput cost** |
| `ngram-mod` drafter | 1.10–1.48× depending on content; **worse than MTP** everywhere except prose. Matters only for files with no MTP layers |

The format result is the one a designer should read twice: **two files of the
same size and the same bit-width differ by 30% in speed because of how
expensive their weights are to unpack.** Dequantisation cost is a first-class
design variable, not an implementation detail.

## Settings / what a user actually sets

| setting | effect | note |
|---|---|---|
| drafter on | **2.2× throughput** | free where the model ships MTP layers |
| power cap 300 W | −5% speed, −6.5% J/token | efficiency win; see the caveat above |
| KV `q8_0`/`q4_0` | large memory saving, no measured quality cost | |
| context size | memory only — decode is flat across resident windows | |
| sampler | **not a speed lever**: greedy 0.77% CV vs recommended 5.68% | changes *variance*, and the published bands were all greedy |

---

## What would move the needle most, in order

1. **Ship a draft head.** 2.2× on the same silicon, and it changes which
   resource is scarce. Nothing else in this table is close.
2. **Cheap-to-unpack quantisation.** 30% between two same-size formats, paid in
   compute at exactly the moment compute is power-clipped.
3. **Memory capacity.** Decides what runs; bandwidth does not, once (1) holds.
4. **Power efficiency at the operating point.** The part is power-limited on
   real work, so watts-per-useful-token is the figure of merit, not peak TFLOPs
   and not peak GB/s.

## What is NOT measured here, stated so it is not mistaken for a result

Wall power (no meter — board power only). CPU hardware counters: IPC, cache
behaviour and memory-controller traffic on the host side are all unmeasured;
only aggregate utilisation, syscall and context-switch rates were sampled. GPU
internals below the NVML level — L2 hit rate, occupancy, warp stalls — need
Nsight and were not collected. One machine, one GPU vendor, one runtime. And
the power-cap curve does not yet cover the capped regime this workload sits in.
