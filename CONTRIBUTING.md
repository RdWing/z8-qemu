# Contributing

Describe the firmware fingerprint, emulator commit, model options and operation
sequence needed to reproduce a result. Distinguish native firmware behavior,
functional hardware models and synthetic inputs. Register retention alone
does not establish completion; indicator rendering does not establish autofocus.

Use Z8 filenames and symbols. Preserve existing copyright notices, SPDX
identifiers, attribution and licenses. Add `Copyright (C) 2026 RdWing` for
RdWing’s modifications alongside prior notices, using the file’s comment style.

Run the source and affected contract checks. Keep firmware and runtime outputs
outside tracked source. Refresh the source manifest for intentional edits.
A source or contract pass does not replace an end-to-end camera run.

Before publishing, run `python tools/audit_privacy.py --history` from a full
clone. It checks tracked content and reachable history for common private paths,
credentials and payload files, without printing matched secret values. Review
prose and GitHub metadata separately; a pattern check cannot establish that
every finding is suitable for publication. Keep private notes, source images,
cards, captures, logs and keys outside Git. Do not paste local diagnostics into
PRs without reviewing them. Deleting a file or editing a PR does not remove
older Git objects, provider edit history, caches or downstream copies.

Desktop packaging copies only tools named in `source-manifest.json`, verifies
their fingerprints and privacy patterns, and rejects symlinked or non-source
inputs. Unlisted local files are excluded even if they sit beside runtime tools.
