Below is a **refined “round-2 aipp development” project plan** that folds AIPP cleanly into **every working mode** of Whisp and walks you through the Git workflow we’ll use.

---

## Overview of what will change

| Area             | What we’ll add/modify                                                          | Why                                |
| ---------------- | ------------------------------------------------------------------------------ | ---------------------------------- |
| **Config layer** | 1-switch enable, 4 saved prompts, provider choice, GUI-friendly defaults       | Single source of truth             |
| **Core**         | AIPP dispatcher already drafted; will add mode-aware hooks + light retry logic | Works the same from all front-ends |
| **CLI / “hear”** | New flags `--aipp`, `--aipp-prompt`, `--aipp-provider`                         | Power-user access                  |
| **GUI**          | Settings window: toggle, provider dropdown, “Manage prompts…” modal            | Easy for non-CLI users             |
| **Tray**         | Context menu mirror of GUI (Enable/Disable, Prompt ▶, Provider ▶)              | Quick on/off                       |
| **Tests / CI**   | Expand unit tests, add two GUI smoke tests                                     | Prevent regressions                |
| **Docs**         | Update README + `docs/aipp.md`                                                 | Keep users sane                    |
| **Git flow**     | Feature branch + squash-merge to `main` after review                           | Isolated & clean history           |

---

## High-level task map

```
0. Git: create feature branch      ← we start here
1. Config: schema & defaults
2. Core: finalize aipp.py + retry
3. CLI & “hear”: flags + help text
4. GUI: settings toggle + provider select
5. GUI: “Manage prompts” window
6. Tray: context menu wiring
7. Tests: new unit + GUI smoke
8. Docs: README / usage examples
9. Merge: PR, review, squash-merge
```

Each numbered task becomes **one or more commits**; you can push any time, but we’ll keep them bite-sized so you can follow.

---

## Detailed plan with guidance

### **0 Git preparation**

1. Make sure your local `main` is up to date:

   ```bash
   git checkout main
   git pull origin main
   ```
2. Create and switch to a dedicated branch:

   ```bash
   git checkout -b feature/aipp-round2
   ```
3. Push it to the remote so we both see it:

   ```bash
   git push -u origin feature/aipp-round2
   ```

*(We’ll verify later that GitHub/GitLab shows the branch before we begin coding.)*

---

### **1 Config schema**

**Goal:** centralise everything in `config.yaml`, remove the external `prompts.yaml` file.

```yaml
# NEW / modified keys
aipp:
  enabled: false            # master on/off
  provider: ollama          # ollama | openai | anthropic | xai
  model: llama2
  active_prompt: 0          # index 0-3 below
  prompts:                  # max 4 entries (0-3)
    - "Summarise the following text."
    - "Convert the following transcript into TODO items."
    - |
        Act as a professional assistant.
        Draft a polite email reply based on:
    - ""                    # free slot
```

*Implementation notes*

* Loader still uses PyYAML; add a small validation helper (`validate_aipp_cfg`).
* If fewer than four prompts are defined, pad with `""` so GUI list is always 4 rows.

---

### **2 Core refinements**

* Update `core/aipp.py` signature to accept `(text, cfg, prompt_idx=None)`.
* **Retry logic** (simple): one automatic retry on network failure, then bubble up.
* Expose a convenience `get_final_text(transcript, cfg)` that combines:

  1. Early-exit if `cfg.aipp.enabled` is false.
  2. Pick prompt = `cfg.aipp.prompts[cfg.aipp.active_prompt]`.
  3. Call `run_aipp`.
* **Mode hooks**

  * CLI & “hear”: call `get_final_text` right before clipboard / typing.
  * GUI & Tray: same, but behind toggle so live preview uses AIPP too.

---

### **3 CLI & “hear” flags**

Add to `argparse`:

```bash
--aipp / --no-aipp                 # override config.enabled
--aipp-prompt 2                    # 0-3
--aipp-provider openai             # override config.provider
```

These flags mutate the in-memory config object only (do **not** write to disk).

---

### **4 GUI settings**

We’ll add a new **“AI Post-Processing”** pane in the existing settings dialog:

| Item              | Widget                                    |
| ----------------- | ----------------------------------------- |
| Enable AIPP       | On/Off switch                             |
| Provider          | ComboBox (ollama, openai, anthropic, xai) |
| Model             | TextEntry (free form)                     |
| Active prompt     | Read-only label (click “Manage prompts…”) |
| *Manage prompts…* | Button opens modal                        |

Changes immediately write to `config.yaml` by re-serialising the struct.

---

### **5 “Manage prompts…” modal**

* 4 rows, each with:

  * RadioButton (select as active)
  * Multi-line TextEdit (prompt itself)
* **Save** / **Cancel** bottom buttons.
* On *Save*, overwrite `cfg.aipp.prompts` array and `cfg.aipp.active_prompt`.

---

### **6 Tray integration**

Add submenu **“AI Post-Processing”**:

```
☑ Enabled               ← checkmark
────────────
Prompts ▶
   • Summarise
   ○ TODO items
   ○ Email reply
Providers ▶
   • Ollama
   ○ OpenAI
   …
```

Internal implementation mirrors GUI (reuse `cfg` setters and emit config-changed signal so the toggle stays in sync).

---

### **7 Tests**

* **Unit tests**:

  * Validation helper rejects >4 prompts or wrong indices.
  * `get_final_text` returns raw transcript when disabled.
* **GUI**: two `pytest-qt` smoke tests:

  1. Toggle AIPP and assert `cfg.aipp.enabled` flips.
  2. Edit prompt #2 and check persistence.

---

### **8 Docs**

* Update README “Features” table.
* Create `docs/aipp.md` with screenshots of GUI & tray settings.

---

### **9 Merge process**

1. Open pull-request **into `main`** once tasks 1-8 are green.
2. Request review (me / others).
3. Address comments, then **squash-merge** with message
   `feat: full AIPP integration across modes (#123)`
4. Delete branch.

---

