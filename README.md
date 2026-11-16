# Timberborn Tools

Tools for managing Timberborn mod translations and data updates.

## Version 3.1

V3.1 introduces single-version tracking with backward compatibility.

### Key Changes in V3.1
- **Single-version tracking**: Only the latest game version is tracked per mod
- **Smart version merging**: Automatically merges unique keys from older versions
- **Backward compatible**: Migrates from multi-version format automatically
- **Simplified data files**: One TOML file per mod (no version suffix)

### Version Selection Logic
- Always uses the latest version found in the mod
- Merges unique keys from older versions for compatibility
- When keys conflict, always prioritizes the newest version
- Supports version formats: `version-1.0`, `version-0.6.1`, `version-0.7`, etc.

## Version 3

V3 focuses on mod data preparation for cloud-based translation workflows.

### Key Changes in V3
- **No translation**: Translation handled by cloud workflow
- **No git operations**: Publishing handled by cloud workflow  
- **New TOML format**: Supports change detection with `new` field
- **Simplified workflow**: Focus on data preparation only

### Features
- Fetch new mods from Steam Workshop
- Download mods via SteamCMD
- Update TOML data files with change detection
- Prepare data for cloud translation workflow

### Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure `config.toml` (copy from `config.toml.example`)

3. Run:
   ```bash
   python main.py
   ```

### TOML Format

Change detection signals retranslation via `new` field:

```toml
name = "Metal Staircase Mod"

["KnatteTobbert.MetalStaircase.DisplayName"]
raw = "Metal Stairs"
new = "Metal Staircase"  # Cloud workflow translates and removes this
enUS = "Metal Stairs"
zhCN = "金属楼梯"
```

### Workflow

1. Tool discovers and downloads mods from Steam Workshop
2. Tool updates TOML files with change detection (adds `new` field where needed)
3. Cloud workflow detects entries with `new` field
4. Cloud workflow performs translation
5. Cloud workflow updates `raw` and language fields, removes `new` field

### Cache Release

Downloaded mods are cached under `steamcmd/steamapps/workshop/content/<game_id>`. After the TOML data is written, a cached mod is only needed again when Steam publishes an update. Directories whose last Steam update is older than `cache_release_days` (default 30, set under `[workshop]`; `0` disables) are deleted at the end of each run. Released mods stay tracked and are downloaded again only when Steam reports a newer update. Per-mod state (`time_updated`, `released`) is kept in `mod_state.json` in the working directory. With `--skip-download` only the recorded state is used, and mods without a record are never released.
