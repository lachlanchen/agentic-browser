# npm Publishing

AgInTi Browser is published as `@lazyingart/aginti-browser`.

## Install

```bash
npm install -g @lazyingart/aginti-browser
python3 -m pip install websocket-client
aginti-browser service start
```

The npm command is a Node wrapper around the Python CLI. It keeps the existing
AgInTi Browser service, tmux, Chrome/CDP, Xephyr, and headless scripts intact.

## Token Source

The publish helper follows the same convention used by AAPS and AgInTi Flow:

- Local env file: `.env`
- Explicit env file: `AGINTI_BROWSER_NPM_ENV=/path/to/.env`
- Accepted token keys: `NPM_TOKEN` or `NODE_AUTH_TOKEN`
- Optional registry key: `NPM_CONFIG_REGISTRY`

The helper creates a temporary npm config, runs npm, and deletes that config.
It must not print npm tokens.

## Validate

```bash
npm run check
npm test
npm pack --dry-run
```

For a local install smoke test:

```bash
npm pack
rm -rf /tmp/aginti-browser-npm-test
npm install --prefix /tmp/aginti-browser-npm-test ./lazyingart-aginti-browser-*.tgz
/tmp/aginti-browser-npm-test/node_modules/.bin/aginti-browser --help
/tmp/aginti-browser-npm-test/node_modules/.bin/agentic-browser --help
rm -f ./lazyingart-aginti-browser-*.tgz
```

## Trusted Publishing

Prefer GitHub Actions trusted publishing for repeat releases. This is the same
method used by `../AgenticApp`: npm trusts a specific GitHub workflow through
OIDC, so GitHub can publish without a local OTP or long-lived publish token.

Trusted publishing is already configured for this package. Future releases can
use the helper script:

```bash
npm run release:npm -- 0.1.1
npm run release:npm -- patch
```

The helper requires a clean working tree, bumps `package.json`, runs `npm test`
and `npm pack --dry-run`, commits, tags, pushes, and triggers the GitHub Actions
publish workflow. It does not require local npm login, OTP, browser
confirmation, or npm tokens.

Trusted Publisher settings on npm:

- Package: `@lazyingart/aginti-browser`
- Publisher: GitHub Actions
- Repository: `lachlanchen/aginti-browser`
- Workflow filename: `npm-publish.yml`
- Environment: blank, unless a GitHub deployment environment is added later

Equivalent setup command:

```bash
npm install -g npm@^11.10.0
npm trust github @lazyingart/aginti-browser --repo lachlanchen/aginti-browser --file npm-publish.yml
```

After npm trust is configured, publish from GitHub manually if needed:

```bash
gh workflow run npm-publish.yml --repo lachlanchen/aginti-browser
```

or publish by creating a GitHub release.

## Local Token Publish

Use the LazyingArt npm token from a trusted env file:

```bash
AGINTI_BROWSER_NPM_ENV=/home/lachlan/ProjectsLFS/Agent/AgInTiFlow/.env npm run publish:env:whoami
AGINTI_BROWSER_NPM_ENV=/home/lachlan/ProjectsLFS/Agent/AgInTiFlow/.env npm run publish:env
```

The AAPS env file can be used the same way when it has a valid LazyingArt npm
token:

```bash
AGINTI_BROWSER_NPM_ENV=/home/lachlan/ProjectsLFS/AAPS/.env npm run publish:env:whoami
AGINTI_BROWSER_NPM_ENV=/home/lachlan/ProjectsLFS/AAPS/.env npm run publish:env
```

After publishing:

```bash
npm view @lazyingart/aginti-browser version
rm -rf /tmp/aginti-browser-published-test
npm install --prefix /tmp/aginti-browser-published-test @lazyingart/aginti-browser
/tmp/aginti-browser-published-test/node_modules/.bin/aginti-browser --help
```
