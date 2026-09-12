# Gitea Activity Chart

Desktop app for querying Gitea activity and visualizing activity counts over time.

The authenticated account can load every user visible through Gitea user
search, choose one from an editable selector, and fetch that user's activity.
The current account appears first as `Me`, and manually entered usernames are
also accepted. Typing filters the visible-user dropdown. Repeated views of the
same server, authenticated viewer, user, date range, and activity filter reuse
a persistent `activity-cache.json` file. Overlapping date ranges reuse saved
days and fetch only missing dates; a range including today refreshes today's
count. The machine-local cache is ignored by Git and never stores tokens or
SSH keys.

Missing days are fetched with up to six concurrent workers. SSH-authenticated
requests include a signed unique request ID, which satisfies Gitea's replay
protection without imposing the former one-request-per-second delay. Per-day
feed pagination and filtering remain unchanged, so the faster path returns the
same activity counts.

## Requirements

- Python 3.10+
- Network access to a Gitea instance
- A Gitea account with an SSH key, plus Pageant on Windows or `ssh-agent` on Linux/macOS
- Alternatively, a Gitea token with read access
- Dependencies from `requirements.txt`

## Install

```bash
python setup.py --venv
```

Or manually:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On Linux or macOS, activate the virtual environment with `source .venv/bin/activate`.

## Configure

On first run, the app creates `config.json` from `config-default.json`.

Set at minimum:

- `gitea.base_url`
- `gitea.auth_method` (defaults to `ssh-agent`)

For SSH authentication:

- On Windows, load a key in Pageant or the Windows OpenSSH agent. Select a
  `.ppk` file to require an exact Pageant key, or an OpenSSH `.pub` file (or its
  adjacent private-key path) to require an exact key already loaded in the
  OpenSSH agent. When a
  `.ppk` is selected, the app starts Pageant when needed and requires that exact
  key for Gitea's SSH-key HTTP-signature authentication. The selected key path
  is session-only and is not saved to `config.json`.
- On Linux and macOS, load a key in `ssh-agent`. Optionally select its `.pub`
  file (or adjacent private-key path) to require that exact loaded key.
- The public SSH key must be registered with the Gitea account.

For token authentication, select `token`, then configure `gitea.token_env` or
provide a token through the UI/config. An environment variable such as
`GITEA_TOKEN` is recommended instead of storing the token in `config.json`.

Git SSH connectivity and Gitea API authentication are separate. This app signs
HTTPS API requests with the SSH key; it does not read activity through Git.

The visible-user selector uses Gitea's normal user-search permissions. It does
not request the administrator-only instance-wide user list, so private users
hidden from the authenticated account are not exposed.

The activity log opens in a separate window so it does not compete with the
trend chart and contribution heatmap for vertical space.

The heatmap scales its cells to the available panel, wraps longer histories
into calendar bands, labels their date ranges and months, and shows the exact
date and activity count when a cell is hovered. A logarithmic intensity scale
keeps ordinary active days distinguishable when a few days have large peaks.

The primary `Activity` tab contains user selection, query controls, charts, and
activity actions. The second `Configuration` tab contains server connection,
authentication, key selection, and configuration saving.

`Clear Data` clears only the displayed chart. `Clear Cache` removes every
saved and in-memory activity cache entry after confirmation while leaving the
current chart visible.

## Run

```bash
python gitea-activity-chart.py
```

On Windows, double-clicking `gitea-activity-chart.py` also works when the `.py`
file association points at a Python installation without this app's packages.
The script checks the project `.venv` first, then installed Python 3 versions,
and relaunches with the first interpreter containing all required dependencies.
If none is available, it displays a persistent error with the install command.
