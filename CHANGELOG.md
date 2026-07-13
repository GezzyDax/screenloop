# Changelog

## [2.0.3](https://github.com/GezzyDax/screenloop/compare/v2.0.2...v2.0.3) (2026-07-13)


### Bug Fixes

* **docker:** switch backend/node to Alpine, drop excess capabilities, scan all images ([029e500](https://github.com/GezzyDax/screenloop/commit/029e500e08d58ba85108edeee1238d44b64b35de))
* **nodes:** forward node websocket through nginx and harden the agent ([21bda3b](https://github.com/GezzyDax/screenloop/commit/21bda3b3a5174a7b6a61fbbeb55536225f873c75))

## [2.0.2](https://github.com/GezzyDax/screenloop/compare/v2.0.1...v2.0.2) (2026-07-13)


### Bug Fixes

* **install:** preserve --node flags across sudo re-exec ([5afbc28](https://github.com/GezzyDax/screenloop/commit/5afbc286eeb36dd73c3aa56f1fb2986c9ae53208))
* **ui:** correct layout glitches in Settings, TVs, and Users views ([a1c90c2](https://github.com/GezzyDax/screenloop/commit/a1c90c26faa9beea37a0520836a36043a4894b75))

## [2.0.1](https://github.com/GezzyDax/screenloop/compare/v2.0.0...v2.0.1) (2026-07-13)


### Bug Fixes

* **ci:** check out real PR head, not the synthetic merge commit ([e8085a0](https://github.com/GezzyDax/screenloop/commit/e8085a0ada66fced488ea5c67096ebd44d3e4228))

## [2.0.0](https://github.com/GezzyDax/screenloop/compare/v1.5.1...v2.0.0) (2026-07-13)


### ⚠ BREAKING CHANGES

* the legacy server-rendered UI and dlna_push.py CLI are removed as of 2.0. Use /api/v1 and the Vue UI going forward.

### Features

* **auth:** self-service passwords, session management and audit scoping ([987e060](https://github.com/GezzyDax/screenloop/commit/987e060d2e879d4ea3c43290492771b81b6b8e09))
* **docker:** multi-stage python deps and build cache mounts ([f148d4e](https://github.com/GezzyDax/screenloop/commit/f148d4e809728ffa284b1f4cc0164ff2e5b7965c))
* **install:** version rollback and optional API docs ([aa4907f](https://github.com/GezzyDax/screenloop/commit/aa4907f1431520a69192445620b14bec2bfffc0a))
* node mode, UI redesign, security hardening and production tooling ([#40](https://github.com/GezzyDax/screenloop/issues/40)) ([7c49aad](https://github.com/GezzyDax/screenloop/commit/7c49aada4c19ce90e73360b06bc723e2bb49ffb6))
* **nodes:** node agent with local streaming, media cache and offline autoplay ([4ef1cbd](https://github.com/GezzyDax/screenloop/commit/4ef1cbd4f6ed8379dd4dbcdaaece9de43bfb2e0f))
* **nodes:** node registry, enrollment and websocket transport ([ba2b381](https://github.com/GezzyDax/screenloop/commit/ba2b381ebadce091eecd52da322f77fb33f74747))
* **nodes:** nodes admin screen, TV node assignment and node docs ([8200054](https://github.com/GezzyDax/screenloop/commit/8200054b36e3b7de097476a9f2b6a1422e694030))
* **ui:** client-side routing with vue-router ([9dbb760](https://github.com/GezzyDax/screenloop/commit/9dbb760051ea5e6449ccb0516bee2b78eff97575))
* **ui:** dark theme, login language switch and mobile table layout ([32b2889](https://github.com/GezzyDax/screenloop/commit/32b288908f3cd6335f22409d73397692745618fb))
* **ui:** localized statuses, search, pagination and honest empty states ([0f3fd55](https://github.com/GezzyDax/screenloop/commit/0f3fd5528870d294a4c21fb0699b4d10bdb2d5d8))
* **ui:** playlist drag and drop, upload progress and duplicate warning ([1336dbf](https://github.com/GezzyDax/screenloop/commit/1336dbfacb814c7283bb7c808d910a7a7152a2cf))
* **ui:** profile screen, session expiry handling and safer user admin ([658c1bd](https://github.com/GezzyDax/screenloop/commit/658c1bdcbf207ad14734b1868f8cb239609fa0c5))
* **ui:** redesign frontend with a compact, flat design system ([c42db38](https://github.com/GezzyDax/screenloop/commit/c42db3838d98cb754ec988246dea9199dbdd9be4))
* **ui:** toast notifications, confirm dialogs and per-action pending ([3c57564](https://github.com/GezzyDax/screenloop/commit/3c57564214c76607c620949bf526db2b5437e446))


### Bug Fixes

* **deps:** patch starlette and python-multipart vulnerabilities, pin valid trivy action ([5c19246](https://github.com/GezzyDax/screenloop/commit/5c19246508d5101242bf5671420f64fb1953bc3b))
* **deps:** patch vite and esbuild vulnerabilities via npm audit fix ([7802211](https://github.com/GezzyDax/screenloop/commit/78022116a3017a2ac6dc9dc561720627c0a7c57f))
* **install:** unquote HTTP/UI port before printing install summary ([95fbc56](https://github.com/GezzyDax/screenloop/commit/95fbc56c0e48109c8d58183803e9e24aefbcd99c))
* **security:** refuse to start with placeholder or documented secrets ([1ad9c2c](https://github.com/GezzyDax/screenloop/commit/1ad9c2c4c1b2ceb697ee6006a365dcf522d7736b))
* **transcode:** add ffmpeg/ffprobe timeouts and atomic output writes ([9969c8b](https://github.com/GezzyDax/screenloop/commit/9969c8be6b862cc3d9ac01b90964f9cebfebfab8))
* **ui:** SSE reconnect with backoff instead of permanent polling downgrade ([f673b16](https://github.com/GezzyDax/screenloop/commit/f673b16857055727a945719e55004b6b887a2921))


### Reverts

* undo squashed merge from PR [#40](https://github.com/GezzyDax/screenloop/issues/40) ([#44](https://github.com/GezzyDax/screenloop/issues/44)) ([bdc1470](https://github.com/GezzyDax/screenloop/commit/bdc1470c9163586670fff5b37051cf830245e0a8))


### Documentation

* document 2.0 upgrade path ([fb2bfa9](https://github.com/GezzyDax/screenloop/commit/fb2bfa962f9c4964677e94114f8e78f598451345))

## [1.5.1](https://github.com/GezzyDax/screenloop/compare/v1.5.0...v1.5.1) (2026-07-10)


### Bug Fixes

* **docker:** run UI as non-root with healthcheck and gate on backend health ([241a413](https://github.com/GezzyDax/screenloop/commit/241a41395ccfb2b65a25dac00ee6082d41d9b991))
* **install:** tighten .env handling and docker installer consent ([1a4580d](https://github.com/GezzyDax/screenloop/commit/1a4580d4c6c1436acc38af2f0346245c7b136cd3))
* **security:** bind stream tokens to the TV address and stop logging them ([48229c0](https://github.com/GezzyDax/screenloop/commit/48229c022388c4e821e7b52db35acb4943364946))
* **security:** harden rate-limit memory, audit retention and probes ([b029d0c](https://github.com/GezzyDax/screenloop/commit/b029d0ccc8d50b2c9467a0a257c27afa28fd8be8))
* **security:** refuse to start with placeholder or documented secrets ([f580102](https://github.com/GezzyDax/screenloop/commit/f580102bf445d4e26b01d66e03e10e822a350105))
* **transcode:** add ffmpeg/ffprobe timeouts and atomic output writes ([cc2a02b](https://github.com/GezzyDax/screenloop/commit/cc2a02bd0544e7afb713a0fb226a982dbc2041b1))
* **web:** enforce upload limits while streaming to disk ([2fbca88](https://github.com/GezzyDax/screenloop/commit/2fbca88416574a0fe69ae5a363bd548a6c07b264))

## [1.5.0](https://github.com/GezzyDax/screenloop/compare/v1.4.0...v1.5.0) (2026-06-16)


### Features

* polish web ui usability ([3a43392](https://github.com/GezzyDax/screenloop/commit/3a43392c04effe0bf7374d73675e14503633ff37))

## [1.4.0](https://github.com/GezzyDax/screenloop/compare/v1.3.0...v1.4.0) (2026-06-16)


### Features

* unify web ui screens ([e044d3f](https://github.com/GezzyDax/screenloop/commit/e044d3fda8761ba11830acfe3d8a7ed8a8c06d56))

## [1.3.0](https://github.com/GezzyDax/screenloop/compare/v1.2.3...v1.3.0) (2026-06-15)


### Features

* improve tv dashboard usability ([13a2cad](https://github.com/GezzyDax/screenloop/commit/13a2cada383628df9b8aa68c0ee8f24d95af6e5f))

## [1.2.3](https://github.com/GezzyDax/screenloop/compare/v1.2.2...v1.2.3) (2026-06-15)


### Bug Fixes

* remove frontend upload body limit ([9710506](https://github.com/GezzyDax/screenloop/commit/9710506ab9a776b35046bf59a3114b163956f7cd))

## [1.2.2](https://github.com/GezzyDax/screenloop/compare/v1.2.1...v1.2.2) (2026-06-15)


### Bug Fixes

* allow operator media upload and 8-char passwords ([1d2f673](https://github.com/GezzyDax/screenloop/commit/1d2f673e08ab510935857c2fc258679d62d6315f))

## [1.2.1](https://github.com/GezzyDax/screenloop/compare/v1.2.0...v1.2.1) (2026-05-26)


### Bug Fixes

* clear stale online status on ping loss ([d1e6cb7](https://github.com/GezzyDax/screenloop/commit/d1e6cb7b443011ea285f9dd1bece059b8830858c))
* prevent early lg stopped auto advance ([27cf452](https://github.com/GezzyDax/screenloop/commit/27cf45269fabbf4a0f6a9cad8ae4bc1afa8f9737))
* smooth lg stopped status after restart ([3de1f2b](https://github.com/GezzyDax/screenloop/commit/3de1f2b5b8444653fec4561d452c44031003e032))

## [1.2.0](https://github.com/GezzyDax/screenloop/compare/v1.1.0...v1.2.0) (2026-05-14)


### Features

* improve TV management and health checks ([7a8215d](https://github.com/GezzyDax/screenloop/commit/7a8215d98da0d2bddadbe646f5904e83ca0e0039))

## [1.1.0](https://github.com/GezzyDax/screenloop/compare/v1.0.3...v1.1.0) (2026-05-13)


### Features

* add playback transition telemetry ([6f0f85b](https://github.com/GezzyDax/screenloop/commit/6f0f85b024cede9a86a180b92b11b17b9f29fd88))

## [1.0.3](https://github.com/GezzyDax/screenloop/compare/v1.0.2...v1.0.3) (2026-05-12)


### Bug Fixes

* preload lg next stream on playback sync ([c8e42b5](https://github.com/GezzyDax/screenloop/commit/c8e42b5bafbe99b2e852e117cd1ca86acfdb6d89))

## [1.0.2](https://github.com/GezzyDax/screenloop/compare/v1.0.1...v1.0.2) (2026-05-12)


### Bug Fixes

* smooth lg playback transitions ([2f33f12](https://github.com/GezzyDax/screenloop/commit/2f33f12ecbf883aa944066c9c357b62b648f334e))

## [1.0.1](https://github.com/GezzyDax/screenloop/compare/v1.0.0...v1.0.1) (2026-05-12)


### Bug Fixes

* advance lg playback after media duration ([31e0c09](https://github.com/GezzyDax/screenloop/commit/31e0c09d5d2c9ba5480cdf3bab2277766efc8171))
* retry deployment downloads ([66e05c4](https://github.com/GezzyDax/screenloop/commit/66e05c495bc7a352007df3b3a376a6f1a9c3307c))

## [1.0.0](https://github.com/GezzyDax/screenloop/compare/v0.3.0...v1.0.0) (2026-05-05)


### ⚠ BREAKING CHANGES

* Screenloop now supports the Vue web UI as the only web control panel. Legacy Jinja routes and templates were removed; the backend remains API, stream, health, and OpenAPI only.

### Features

* add admin diagnostics page ([6f060b5](https://github.com/GezzyDax/screenloop/commit/6f060b5ab30f8f12125781445b5e4ffac5ba0655))
* add compressed transcode mode ([9d4d2ad](https://github.com/GezzyDax/screenloop/commit/9d4d2ade4fae94ca46c8d62498afdecbcbc3bf1a))
* add live status polling ([7d981c9](https://github.com/GezzyDax/screenloop/commit/7d981c9123263a58649804591ed2876597aa3359))
* add separate vue frontend ([1ff90d5](https://github.com/GezzyDax/screenloop/commit/1ff90d5e59c12c0d757d10d4ef6fef0777734ce7))
* add tv details panel ([e2657c1](https://github.com/GezzyDax/screenloop/commit/e2657c15cd11a0e08a584fb9eac400db96496fce))
* add version footer and stop deleted TVs ([4e68efd](https://github.com/GezzyDax/screenloop/commit/4e68efd44a899e56d7bbe1b34bcd5d23fb68ec3a))
* add vue security settings page ([cdbfb6e](https://github.com/GezzyDax/screenloop/commit/cdbfb6ebed579ccca5ffd941a240c2e5b411df72))
* add vue user management ([6e1ab3d](https://github.com/GezzyDax/screenloop/commit/6e1ab3d022eb8572dfb679272c65649189eafecd))
* expand vue control panel ([21ae5b3](https://github.com/GezzyDax/screenloop/commit/21ae5b32363508bab131fde4d3cf408134cfe209))
* improve tv status visibility ([f0f27fb](https://github.com/GezzyDax/screenloop/commit/f0f27fbe482d08f6f4ee5196c33616dc48b6a7e4))
* remove legacy server-rendered panel ([39f0cd5](https://github.com/GezzyDax/screenloop/commit/39f0cd55ffc1307fc2009cb6c705f0a1cdff193c))
* show tv playback diagnostics ([583c66f](https://github.com/GezzyDax/screenloop/commit/583c66fd4e0a0b3839673e776bdef1266ba24933))
* stream live status with sse ([6dd9f06](https://github.com/GezzyDax/screenloop/commit/6dd9f06a3fb011d66db5ac811cfbb0c1e48f2eaa))


### Bug Fixes

* advance playlist on stream replay ([1ff6510](https://github.com/GezzyDax/screenloop/commit/1ff65100bdf4b69c14e92d38fd8aa4f1a9479f8a))
* allow public stream url for tv playback ([6785669](https://github.com/GezzyDax/screenloop/commit/678566909db05c00faeb2319d1a3f11110ecc6a9))
* avoid sse session write pressure ([671c064](https://github.com/GezzyDax/screenloop/commit/671c064174b326c539c5a8d8ef34373cc73fd981))
* clarify container diagnostics probes ([0e14547](https://github.com/GezzyDax/screenloop/commit/0e14547afbde5175fee7f1888e32912c07139286))
* detect stream end from byte ranges ([ab6fee9](https://github.com/GezzyDax/screenloop/commit/ab6fee90b455cf13351947aaa79714b5a6bc2787))
* explain docker shim update failures ([864a2d2](https://github.com/GezzyDax/screenloop/commit/864a2d2bcce30d1f8cfcd965137334b762b278cb))
* harden sse live updates ([f1c8f12](https://github.com/GezzyDax/screenloop/commit/f1c8f129e7baca6b06f299e66cd5ac3ed3080d5a))
* import os for container diagnostics ([5f9f85c](https://github.com/GezzyDax/screenloop/commit/5f9f85c62ae04da57c1ef4c61b2c63aca920b3b8))
* make compressed transcodes smaller ([ac8d498](https://github.com/GezzyDax/screenloop/commit/ac8d498ee6a6b2fccaa5d710445842b6a82ce0b7))
* reexec updated updater ([c854f0a](https://github.com/GezzyDax/screenloop/commit/c854f0a289809256c974e602dc75c468b4c1ac9c))
* sanitize tv stream urls ([6161e6d](https://github.com/GezzyDax/screenloop/commit/6161e6d74e95c0558ca3b949b7ffc5da5747f861))

## [0.3.0](https://github.com/GezzyDax/screenloop/compare/v0.2.0...v0.3.0) (2026-04-30)


### Features

* add per-video silent transcoding ([24ceb7e](https://github.com/GezzyDax/screenloop/commit/24ceb7e96806dc9418f8a1eb4aed62be89c972cc))

## [0.2.0](https://github.com/GezzyDax/screenloop/compare/v0.1.0...v0.2.0) (2026-04-29)


### Features

* add installer and TV config management ([25d825f](https://github.com/GezzyDax/screenloop/commit/25d825f2599df2e181cd463119ee89ce9ec4e1d7))
