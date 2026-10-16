# Family Release and Verification

Start with `git status --short`, the current branch, and `git diff` so existing changes are preserved. Identify whether the task concerns the add-on repository, the wizard add-on, the downloadable Family build ZIP, profile settings, or live Kodi. These can require different version numbers and publication steps.

`repo_generator.py` packages add-ons and writes `repo/zips/addons.xml` plus its MD5. `update_and_generate.py` can remove and regenerate `repo/zips`; `update_versions.py` updates version references. Do not run these as read-only checks. Inspect their source and back up generated artifacts when their mutation is intended. The feed is `repo/plugin.program.NikeFlixFamilyWizard/resources/text/builds.txt`; compare its version and URL with the exact archive actually hosted.

For a release candidate, inspect ZIP entry paths with `System.IO.Compression.ZipFile` or Python `zipfile`; require top-level `addons/`, `media/`, `userdata/` and no unintended wrapper directory. Enumerate all five profiles and audit credentials, private databases, caches, logs, and backups. Parse changed `addon.xml` and generated `addons.xml`; verify the checksum and add-on ZIP versions. Run focused available tests or create coverage for confirmed fixes. Publish only intended files to the correct GitHub remote, then read back the served index, checksum, feed, and build ZIP. Finally test install/upgrade, profile switching, Trakt per profile, TMDb Helper, and logs in Kodi.

If a layer cannot be tested, state which one and why. A committed file, local generator output, or wizard popup version alone does not prove the five-profile published build works.
