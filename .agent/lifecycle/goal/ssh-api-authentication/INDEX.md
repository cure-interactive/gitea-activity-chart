# SSH API Authentication

Status: Complete

## Outcome

Make SSH agent or PuTTY/Pageant key authentication the default for Gitea
activity requests while preserving explicitly selected token authentication.

## Acceptance

- SSH agent/Pageant is the default authentication mode.
- Windows users may select an exact `.ppk` key and have Pageant load it.
- Linux and macOS users may use a key already loaded in `ssh-agent`.
- Token authentication remains available as an explicit mode.
- Configuration, UI, and user documentation describe both modes.
- Static and focused behavioral validation pass.

## Coordination

The checkout uses a GitHub remote and exposes no safely usable repository issue
service in the current environment, so this file is the PAF lifecycle fallback.

## Validation

- Both repository Python entry points compile successfully.
- Focused runtime checks passed for HTTP-signature construction, token fallback,
  OpenSSH public-key selection, and GUI authentication-mode state changes.
- `git diff --check` passed.
- A real signed request was not sent because no test Gitea account or test key
  was placed in scope.
