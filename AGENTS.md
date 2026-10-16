# NikeFlix Family Repository Guide

This repository owns the NikeFlix Family repository add-on and wizard. Family is intended to provide five configured profiles with common presentation and add-on defaults, while each person's Trakt account, watch state, credentials, and databases remain separate. Read `docs/nikeflix/INDEX.md` before changing add-ons, settings, profiles, wizard feeds, generated files, or build archives. Read any nearer `AGENTS.md` if one is later added.

## Connected locations

- This checkout: `A:\Development\Version Control\Github\repository.NikeFlixFamily`.
- GitHub: `https://github.com/TanDMoss/repository.NikeFlixFamily`.
- Regular checkout: `A:\Development\Version Control\Github\repository.NikeFlix`, GitHub: `https://github.com/TanDMoss/repository.NikeFlix`.
- Live Kodi: `C:\Users\tan\AppData\Roaming\Kodi`.
- NikeFlix prompt and knowledge space: `A:\Productivity\Notes\Obsidian\Vaults\Tech Vault\Tech Vault\Chosen-Agents\NikeFlix`.

GitHub and this checkout own source; Kodi is a live runtime; the build-feed URL and downloadable archive are separate publication surfaces. Recheck each before claiming a version or fix is live.

## Edition and profile boundaries

The Family wizard ID is `plugin.program.NikeFlixFamilyWizard`; repository add-on ID is `repository.NikeFlixFamily`. Profile 1 is the Kodi master profile under `userdata`; Users 2-5 are recorded by `userdata/profiles.xml`. Use that XML as the current name/path authority. Merge shared settings by key, retaining destination-specific Trakt tokens, account IDs, watched/progress state, debrid/API credentials, device authorization, and databases. Back up every destination before a merge and compare protected values before/after without printing them. Keep TMDb Helper enabled when fixing its integration unless Tanner changes that requirement.

## Work sequence

1. Read `docs/nikeflix/INDEX.md`, inspect `git status`, branch, and remote. Preserve unrelated worktree changes.
2. Locate source under `repo/`, the wizard feed at `repo/plugin.program.NikeFlixFamilyWizard/resources/text/builds.txt`, generated index/checksum under `repo/zips/`, and the intended Family build ZIP.
3. Stop Kodi and back up affected files before live profile changes. Stage ZIP extraction under the Kodi home and inspect top-level `addons/`, `media/`, `userdata/` before applying anything.
4. Inspect `repo_generator.py`, `update_versions.py`, and `update_and_generate.py` before invoking them. The generator rewrites repository artifacts; `update_and_generate.py` can remove `repo/zips`.
5. Validate all five profile contracts, XML, ZIP entries, add-on versions, generated index/checksum, feed version and URL, GitHub publication, the served build ZIP, and Kodi profile-switch/runtime behaviour as separate proof levels.

Do not suppress a Trakt 401 popup by wiping an account or disabling an unrelated add-on. Diagnose the caller and authentication state. A passing local check does not prove that the published ZIP or running Kodi is fixed. Add focused regression protection for a confirmed bug, or record the exact manual/runtime proof boundary.
