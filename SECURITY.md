# Security and private data

Summit is a local, single-user application. Run it on loopback using the supplied
launchers. It has no remote-user authentication and must not be exposed through
a public server, port forwarding, or a tunnel. Making its source public does not
require running your own instance publicly.

Provider credentials belong only in the ignored local Settings files or your
environment. Use your own restricted provider credentials. Do not commit real
lead/client exports, logs, databases, browser captures, local assistant settings,
private keys, or compiled Python files. Do not force-add ignored files.

Before publishing or pushing, install [Gitleaks](https://github.com/gitleaks/gitleaks)
and run from the repository root:

```bash
python scripts/check_public_release.py --history
```

This checks tracked working files, staged contents, and all reachable Git refs.
It fails if the scanner is unavailable. The GitHub workflow repeats this gate,
but a workflow runs after a push: run the local check before sending any data.
Enable GitHub secret scanning and push protection as additional safeguards.

Ignored files can still exist in older commits. A normal cleanup commit does not
remove them from history. Keep any repository containing previous private data
private. Publish a reviewed clean repository with fresh history, or follow
[GitHub's sensitive-data removal procedure](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
before changing the existing repository's visibility. Rotate any credential
that was committed; history removal cannot invalidate copies already obtained.

To create a separate clean local repository from reviewed source, first stage
intended new source files and untrack private/generated files, then run:

```bash
python scripts/create_public_release.py ../Lead-Machine-public
```

The destination must not exist. The script copies only tracked working files,
creates one fresh commit with a no-reply identity, verifies it, and configures
no remote. Publish that new directory to a new GitHub repository. Keep the
original private repository private and do not merge its history into the new one.

Use a GitHub no-reply author email for future commits if you do not want your
personal email published. Audit branches, tags, releases, attachments, issues,
and pull requests separately when reusing an existing GitHub repository.

Discovery and monitoring intentionally send the requested URLs, search terms,
and configured credentials to their selected providers. AI features send the
selected business content and prompts to the configured AI provider. Review
those inputs before using the features with confidential material.

Scraping validates redirect targets and pins connections to checked public IPs.
Browser scraping blocks submissions, WebSockets, downloads, and service workers;
sites requiring login, cookies, or POST-based APIs may not render completely.
Preview quality checks load only bundled files from the generated package, so
external fonts/images must be bundled for accurate screenshots. Optional pa11y
and Lighthouse browser passes are disabled because they lack this enforced
network and local-file boundary. Static HTML checks remain available.

Do not post credentials or private customer data in a public security report.
Use GitHub private vulnerability reporting when the repository owner has enabled
it. Secret scanners, dependency advisories, and code review cannot establish that
software has no unknown vulnerabilities.
