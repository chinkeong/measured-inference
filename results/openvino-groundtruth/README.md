# OpenVINO requantisation: measured, not derived

`scripts/lib/openvino_quant.py` was written by reading llama.cpp source. This
directory holds the run that checked it. One build, one 12-second bench, and
the table stops being a claim about source and starts being a record of what
the backend did to 600 tensors.

    run_utc     2026-08-29
    host        WSL2 Ubuntu on the campaign machine
    llama.cpp   d7bd3bf, ggml/src/ggml-openvino/ present
    OpenVINO    2026.3.1 runtime
    build       -DGGML_OPENVINO=ON -DGGML_CUDA=OFF -DOpenVINO_DIR=$HOME/ov/runtime/cmake
    device      GGML_OPENVINO_DEVICE=CPU  ("OpenVINO: using device CPU")
    model       gemma-4-E2B-it-Q6_K.gguf, file type Q6_K, n_layer 35, n_embd 1536
    command     llama-bench -m MODEL -ngl 99 -p 8 -n 4 -r 1 -v

`run-full.log` is the whole run. `requant.log` is the 600 per-tensor records
plus the header lines that fix the conditions.

## The patch that made it visible

The per-tensor logging exists upstream and is commented out. Fifteen lines at
`ggml/src/ggml-openvino/ggml-openvino.cpp:324,332-340,345-349` were uncommented
and retagged from `GGML_LOG_DEBUG` to `GGML_LOG_INFO` with `REQUANT` / `KEPT` /
`SHARED` prefixes so they survive a normal log level and can be counted. The
patch is not in this repository; it is a local change to a llama.cpp checkout,
and the recipe above reproduces it.

## What the run found

    REQUANT  316      every one of them to Q8_0_C
    SHARED   284      passed through, type unchanged
    KEPT       0
    total    600

The 316 are 35 layers times nine weight classes -- `attn_q`, `attn_k`,
`attn_v`, `attn_output`, `ffn_gate`, `ffn_up`, `ffn_down`, `inp_gate`, `proj`
-- plus `token_embd.weight` once. The 284 are 35 layers times eight norm and
scale classes, plus four model-level tensors including `output_norm.weight`.

## What it proves

1. **The rewrite is real and it is silent.** 316 tensors changed representation
   at load. An unpatched build prints not one word about it.
2. **The non-NPU rows of the table are correct.** Q6_K became Q8_0_C, and
   `token_embd.weight` became Q8_0_C, exactly as
   `ggml-openvino-extra.cpp:252-273` says.
3. **`Q8_0_C` is channel-wise, and now that is measured.** The logged
   `block_size` is the row width in every single record -- 1536, 2048, 256,
   4096, 6144, 12288 -- and never 32. This is the load-bearing claim in
   `openvino_quant.py`, because it is what makes Q6_K to Q8_0_C *more bits at
   coarser scale granularity* rather than an upgrade, and it is now read off a
   run rather than inferred from `weights_per_block = tensor->ne[0]`.
4. **The scale is fp16.** Not from this run but from the source it exercises:
   `ggml-quants.cpp:94,134,179,239,294,363,442` all take scales as
   `ov::element_type_traits<ov::element::f16>::value_type`. `SCALE_BITS = 16`
   is no longer an assumption.

## What it does not prove

Say this plainly wherever these numbers are used.

* **Nothing about the NPU.** The `Q4_0_128` collapse and the F16
  `token_embd.weight` special case are the two rules that make a quant ladder
  degenerate, and both are NPU-only. They stay derived-from-source until
  someone runs Lunar Lake or equivalent. This run cannot speak to them.
* **Nothing about the GPU device.**
* **`KEPT` is untested, not disproven.** Zero KEPT records is what a pure-Q6_K
  file *should* produce: every quantised tensor in it is eligible for rewrite,
  so the `default: return nullopt` branch had nothing to catch. A Q4_K_M or
  Q8_0 file is needed to exercise it.
* **`output.weight` is untested here.** Gemma ties it to `token_embd.weight`,
  so it never reached the buffer path. The table's "output.weight -> Q8_0_C,
  always" row was not exercised by this model.

## Reproducing it

Two things cost real time and are worth writing down.

`llama-cli` in this build produces **no output at all** for a model run and
exits 0. It is not a working witness; do not debug the backend through it.
Use `llama-bench`.

`llama-bench` **suppresses ggml log output unless you pass `-v`**. Without it
the run completes, reports tokens per second, prints `backend OPENVINO`, and
shows zero requantisation records -- which reads exactly like a backend that
never engaged. It engaged. Pass `-v`.

The second witness for rule 4 remains `GGML_OPENVINO_DUMP_IR=1`: it writes the
IR that actually ran, and the constant types in it answer the same question
without depending on any log line or on this patch.
