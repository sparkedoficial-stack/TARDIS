# First experiment: causal prompt chaining

**Date:** 2026-09-23  
**Owner:** Spark  
**Code:** `experiments/causal_prompt_chaining/run.py`  
**Compiler under test:** `AutonomousCoder._validate_syntax` (live GODWORKS stack, no LLM)

## Hypothesis

If `AutonomousCoder` records prompt-tag → generated-code → compile-outcome edges and uses that graph to rewrite the next prompt, then the number of **failed compile iterations** on held-out synthetic refactor tasks falls by **at least 30%** versus untracked prompting (uniform random tag each try).

Formal claim on the primary metric \(F\) (failed attempts until first compile success, censored at \(K=8\)):

\[
\frac{\mathbb{E}[F_{\text{control}}] - \mathbb{E}[F_{\text{causal}}]}{\mathbb{E}[F_{\text{control}}]} \ge 0.30
\]

with a two-sided 95% Wald interval on the mean difference excluding zero (\(z \ge 1.96\)).

## Method

1. **World.** Four discrete prompt tags (`fix_imports`, `fix_parens`, `fix_indent`, `fix_quotes`). Each task has one hidden required tag. Code is valid Python iff the chosen tag matches; otherwise it is a real syntax-broken snippet whose error class is produced by `ast.parse` via the live coder.
2. **Observation noise.** With probability \(0.15\), the learner sees a wrong error class (models noisy compiler logs). The code itself is never noisy.
3. **Warm-up (train, \(N=48\)).** Random tags; the causal graph records outcomes. The control policy does not use this data.
4. **Test (\(N=80\) held-out tasks, same hidden-tag family, different ids).** Max \(K=8\) attempts per task.
   - **Control (untracked):** each attempt samples a tag uniformly. History is ignored.
   - **Treatment (causal):** first tag is random (same action space); later tags are `CausalPromptGraph.suggest_tag` (Laplace-smoothed success minus error-class association, avoiding repeats).
5. **Seeds.** Master seed `42`. Control RNG `seed+11`, treatment RNG `seed+13`, warm-up RNG `seed`. Split construction uses `seed` / `seed+1`.
6. **Run.** `python -m experiments.causal_prompt_chaining.run --seed 42`  
   pytest: `pytest tests/test_causal_prompt_chaining_experiment.py -q`

This is a **mechanism** experiment: it asks whether causal chaining helps when prompt tags actually cause compile classes. It does not call Groq or Temporal Brain.

## Expected result

- Control mean failed attempts near \(3\) (geometric with \(p=1/4\), censored at 8).
- Treatment mean well below that after warm-up, because error class identifies the missing tag.
- Relative reduction \(\ge 0.30\) and \(z \ge 1.96\).
- Identical seed → bit-identical trial lists.

If the hypothesis is **not** supported, the report still writes JSON; pytest fails only on irreproducibility or a broken compiler loop, not on a negative scientific result (except the dedicated `test_hypothesis_direction` which documents the pre-registered claim).

## Analysis

Primary: mean failed attempts, 95% CI (normal approximation), relative reduction, Wald \(z\) on the unpaired mean difference.  
Secondary: solve rate before the cap.  
Artifact: `data/experiments/causal_prompt_chaining_seed42.json`.

## Limitations

- Synthetic 1-to-1 tag→error map is much cleaner than real LLM patches (multi-fault files, semantic bugs that parse, API failures).
- Untracked baseline is random tags, not “repeat the same prompt,” which is a weaker/stronger control depending on the live coder’s retry policy.
- Warm-up is exploration on the same world family; transfer to novel error types is untested.
- Independence of tasks is by construction; live evolution log is temporally dependent.
- 15% label noise is arbitrary. Bare `invalid syntax` is mapped to `ImportSyntax` because CPython does not mention `import` in that message.
- Graph is not yet used to rewrite the cloud `user_prompt` inside `evolve_code` (observe-only hook). A later experiment must A/B live evolutions.
- Wald \(z\) is a first-experiment approximation, not a permutation test.
