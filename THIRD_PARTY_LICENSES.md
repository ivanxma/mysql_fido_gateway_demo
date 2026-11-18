# Third-party licenses and notices

Audit date: 2026-11-18. This document records the dependencies inspected for
the 0.3.0 prototype/tutorial release. The original project code, templates,
JavaScript, and documentation are MIT licensed by ivanxma; this does not
relicense dependency software. See [LICENSE](LICENSE) and the personal-project
[disclaimer](DISCLAIMER.md).

## What is distributed

The project wheel contains its original Python modules and frontend assets,
its license/disclaimer, this inventory, and copies of upstream license texts.
The starter ZIP includes the project wheel and editable application files.
It does not bundle MySQL Connector/Python, Flask, their dependencies, the
MySQL server, Python, Caddy, Chrome, or a physical authenticator. pip obtains
Python dependencies separately. Copied license texts identify upstream terms;
their inclusion does not mean the upstream implementation is vendored.

## Runtime dependencies

Versions below are the audited environment, not a lock for every transitive
dependency. MySQL Connector/Python, cbor2, and Flask are explicitly pinned by
the project; dependencies resolved by Flask can differ on another platform
or installation date. Recheck the actual artifacts when redistributing them.

| Component | Audited version | Upstream license | Role / source |
| --- | --- | --- | --- |
| MySQL Connector/Python Community | 26.10.0 | GPLv2 with the Universal FOSS Exception 1.0 and additional permissions in its license manual | MySQL transport; [official source](https://github.com/mysql/mysql-connector-python), [licensing](https://dev.mysql.com/doc/dev/connector-python/latest/license.html) |
| cbor2 | 5.9.0 | MIT | Credential encoding; [source](https://github.com/agronholm/cbor2) |
| Flask | 3.1.3 | BSD-3-Clause | Optional Flask frontend/runtime; [source](https://github.com/pallets/flask) |
| Werkzeug | 3.1.9 | BSD-3-Clause | Flask dependency; [source](https://github.com/pallets/werkzeug) |
| Jinja2 | 3.1.6 | BSD-3-Clause | Template rendering; [source](https://github.com/pallets/jinja) |
| MarkupSafe | 3.0.4 | BSD-3-Clause | Template escaping; [source](https://github.com/pallets/markupsafe) |
| itsdangerous | 2.2.0 | BSD-3-Clause | Flask cookie signing; [source](https://github.com/pallets/itsdangerous) |
| click | 8.5.1 | BSD-3-Clause | Flask command-line dependency; [source](https://github.com/pallets/click) |
| blinker | 1.9.0 | MIT | Flask signals; [source](https://github.com/pallets-eco/blinker) |

Unmodified texts, with upstream copyright notices, are in
[`licenses/third-party/`](licenses/third-party/). File names include package
versions. Connector/Python's complete 26.10.0 license manual is preserved,
including its own bundled-component notices; its short package metadata
license label alone is not the full set of terms.

### MySQL Connector/Python requires separate attention

Connector/Python Community is not MIT licensed. Its GPLv2 terms, additional
permissions, and [Universal FOSS Exception](https://oss.oracle.com/licenses/universal-foss-exception/)
remain applicable. The exception describes interoperability with other FOSS
distributed with complete corresponding source; it does not relicense the
connector or give a general permission for all proprietary combinations.

The MIT license selected here covers this project's original work. Preserve
upstream notices and evaluate source/distribution obligations for the actual
combination being redistributed. If you redistribute connector binaries,
resolve the GPL source obligations for that exact version; an inventory or
an upstream hyperlink is not a substitute for satisfying those obligations.
Commercial MySQL/connector agreements, if used, must be reviewed separately.
This inventory is not an Oracle endorsement, legal opinion, or compatibility
certification.

## Optional tests

| Component | Audited version | License | Source |
| --- | --- | --- | --- |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | [source](https://github.com/pyca/cryptography) |
| cffi | 2.1.1 | MIT-0 | [source](https://github.com/python-cffi/cffi) |
| pycparser | 3.12 | BSD-3-Clause | [source](https://github.com/eliben/pycparser) |

These support synthetic cryptographic tests. Their inspected license files
are also copied under `licenses/third-party/`; they are not required by the
normal application install. Platform-specific wheels may include native
components (for example, cryptography's OpenSSL); use the notices and source
requirements of the particular upstream wheel if redistributing it.

## External software and development tools

Python, pip, and setuptools are installation/build tools obtained separately.
Caddy is an external HTTPS proxy, not bundled by this project. A compatible
MySQL server, browser, and authenticator are independently obtained and
licensed products. Their use is not licensed by this project's MIT grant.

Video/UI verification used separately installed Playwright, Pillow,
imageio-ffmpeg/FFmpeg, and Chrome. Their tool binaries are not included in the
project wheel or starter. Recheck and preserve their actual licenses if
adding those tools to a redistributed bundle; this release does not grant
rights to redistribute them.

No Oracle source implementation is copied into this project's adapter.
References to protocol documentation and dependency APIs do not turn this
personal project into an Oracle-authored or supported product.
