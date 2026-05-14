# Changelog

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
