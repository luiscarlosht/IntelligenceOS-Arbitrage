# M78 dependency trust: reviewed bytecode-free wheel profile

Recommendation: **B — use independently verified pinned wheels without bytecode**.
This is a separately reviewed profile change, not permission to install or run M78.
The existing sandbox and its 401-file inventory are not used as trust inputs.

| Approach | Security and provenance | Complexity / operations |
|---|---|---|
| A: reproduce all 401 historical files | Must authenticate package bytes plus 193 generated pyc files. Requires the original Python patch version, logical source paths, timestamps/invalidation mode and optimization recipe, then independent reproduction. No authenticated historical record or recipe has been recovered. | High; preserves incidental generated files, ties deployment to compilation details and retains a blocker with no runtime benefit. |
| B: bytecode-free pinned wheel files | Authenticate two complete wheel archives against independently reviewed release digests; verify each RECORD entry; retain exact source and dependency file hashes. Reject bytecode and unapproved content. | Lower; deterministic raw extraction, no dependency resolution, installation hooks, compiler recipe or pip-generated metadata. No arbitrary historical file count. |

B preserves verification strength: **every file is still authenticated and compared
exactly**, with missing/extra/drifting files refused. Only the obsolete count and
compiled-cache requirement change. Runtime Python already runs with -B,
PYTHONDONTWRITEBYTECODE and read-only code/dependency binds; these remain unchanged.

## Trust anchors and limits

The following values were checked against official PyPI release-file metadata,
independently of the old sandbox. They are committed in `wheel_profile.py` and
`runtime-wheels.txt`; archive hashes are checked before parsing contents.

| Wheel | SHA-256 | Independent metadata origin |
|---|---|---|
| openpyxl-3.1.5-py2.py3-none-any.whl | `5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2` | [PyPI openpyxl 3.1.5](https://pypi.org/project/openpyxl/3.1.5/) |
| et_xmlfile-2.0.0-py3-none-any.whl | `7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa` | [PyPI et-xmlfile 2.0.0](https://pypi.org/project/et-xmlfile/2.0.0/) |

**Neither release has PyPI publisher attestations.** These pins authenticate bytes
against the official index over verified TLS, not a signed publisher build or an
independently reproduced upstream source build. The reviewer must explicitly accept
that trust anchor, check the release metadata through a separately authenticated
review session, and retain approval of the pins. A second download from PyPI is
reproducibility evidence, not an independent publisher attestation. If policy requires
signed upstream provenance, STOP: this PR cannot manufacture it or bypass that gate.
Wheel RECORD verifies internal consistency only after archive authentication; it
cannot independently establish archive trust. See the [wheel specification](https://packaging.python.org/en/latest/specifications/binary-distribution-format/).

## Precise acquisition procedure — trusted development/review machines only

No command in this section is a DigitalOcean deployment command. Use a new private
review directory, a reviewed Python 3.12 interpreter and acquisition tools, and the
reviewed repository/tool revision. Record exact tool versions and OS. Do not use
production credentials, runtime installations, the existing sandbox or pip caches.

1. A reviewer independently opens the two official release pages above over verified
   TLS and checks exact filenames, versions, SHA-256 values, yanked status and the
   absence of publisher attestations. Retain reviewer identity, review date, origins,
   approval and metadata snapshots in a private provenance archive. Do not derive
   approved pins from downloaded wheel contents or accept a mismatching digest.
2. On the acquisition machine, save original release JSON and download only the two
   approved binary artifacts. `REVIEW` must identify a newly created private directory;
   commands refuse HTTP/TLS failures. Use a reviewed checkout as the working directory:

```sh
REVIEW=$(mktemp -d /tmp/m78-wheel-review.XXXXXXXX)
mkdir "$REVIEW/wheelhouse"
curl --fail --show-error --silent --proto '=https' --tlsv1.2 \
  https://pypi.org/pypi/openpyxl/3.1.5/json -o "$REVIEW/openpyxl-3.1.5.json"
curl --fail --show-error --silent --proto '=https' --tlsv1.2 \
  https://pypi.org/pypi/et-xmlfile/2.0.0/json -o "$REVIEW/et-xmlfile-2.0.0.json"
python3.12 -m pip --isolated download --no-cache-dir --no-deps \
  --index-url https://pypi.org/simple --only-binary=:all: --require-hashes \
  -r ops/m78_sandbox/runtime-wheels.txt --dest "$REVIEW/wheelhouse"
```

3. Verify the saved JSON against the reviewed pins, not against newly computed wheel
   digests. Run this from the reviewed checkout on that acquisition machine:

```sh
python3.12 -I - "$REVIEW" <<'PY'
import json, pathlib, sys
review = pathlib.Path(sys.argv[1])
expected = {
    'openpyxl-3.1.5.json': ('openpyxl-3.1.5-py2.py3-none-any.whl',
        '5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2'),
    'et-xmlfile-2.0.0.json': ('et_xmlfile-2.0.0-py3-none-any.whl',
        '7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa'),
}
for record, (name, digest) in expected.items():
    data = json.loads((review / record).read_bytes())
    matches = [item for item in data['urls'] if item['filename'] == name]
    if len(matches) != 1 or matches[0]['digests']['sha256'] != digest or matches[0]['yanked']:
        raise SystemExit('Release metadata mismatch: stop review')
    if not matches[0]['url'].startswith('https://files.pythonhosted.org/'):
        raise SystemExit('Unexpected artifact origin: stop review')
print('Saved release metadata matches the independently reviewed pins')
PY
```

Preserve original JSON, wheel archives, reviewed lock file, tool revision and review
attestation. This metadata script is a consistency check; it does not replace the
independent review in step 1. Offline hosts cannot revalidate later index revocation
or yanking: repeat the review before adoption. Never use --trusted-host, disable TLS,
use source distributions, permit dependency resolution or accept replacement hashes.

## Offline reconstruction and independent reproduction

Transfer that exact wheelhouse, pinned records and reviewed tools to an offline review
machine, separate from DigitalOcean. Verify transfer hashes against the original
approved pins. The builder itself has **no network calls, package installation,
imports of dependency code, builds or compilation**. It uses stdlib ZIP parsing with
bounded extraction and exclusive output; it retains raw wheel bytes, including
METADATA/WHEEL/RECORD/licenses. It does not generate INSTALLER, REQUESTED, direct_url
or pyc files. It accepts only the two pinned purelib wheels and their expected package
and version roots. All RECORD hashes/sizes/coverage and required metadata must pass.
Paths, duplicates, symlinks, special bits, scripts/.data roots, .pth hooks, native
extensions and all bytecode/cache paths are refused.

Use the original independently verified source revision exactly; the newer tool
revision is recorded separately:

```sh
SOURCE=aa549e23a84d46edc4817833d7c8cf16badc927b
python3.12 -B ops/m78_sandbox/inventory.py --repo . \
  --source-commit "$SOURCE" --wheelhouse "$REVIEW/wheelhouse" \
  --bundle-output "$REVIEW/bundle-A" --output "$REVIEW/manifest-A.json"
python3.12 -B ops/m78_sandbox/inventory.py --repo . \
  --source-commit "$SOURCE" --wheelhouse "$REVIEW/wheelhouse" \
  --bundle-output "$REVIEW/bundle-B" --output "$REVIEW/manifest-B.json"
cmp "$REVIEW/manifest-A.json" "$REVIEW/manifest-B.json"
diff --recursive --brief "$REVIEW/bundle-A" "$REVIEW/bundle-B"
sha256sum "$REVIEW/manifest-A.json"
```

Do not reuse output paths. Repeat the build on a second independently controlled
clean offline machine with the same approved inputs and compare manifest bytes and
all bundle path/digest maps. Directory timestamps are not payload provenance; file
bytes and sorted JSON must reproduce exactly. Retain both build reports, environment
records, manifest digest and reviewer approval. A local repeat alone is not independent
reproduction. CI exercises deterministic reconstruction twice, exact source hashes,
bytecode absence, exclusive output, and isolated dependency imports; CI is development
evidence, not the operator's independent adoption review.

The builder reads committed Git blobs, verifies Git consistency and ignores worktree
edits, inherited Git settings and replacement objects. It exports exactly 126 app
Python files plus ops/m78_offline.py. Dependency paths/count derive from the complete
approved wheel contents; no files may be silently omitted or padded to match 401.
A mismatch or partial output is preserved for review, never automatically repaired.

## Manifest and installation boundary

The manifest now has four mandatory fields: `profile` =
`m78-wheels-no-bytecode-v1`, `source_commit`, exact `wheels` pins, and the complete
`files` path-to-SHA-256 mapping. Duplicate keys, unknown profiles, old flat manifests,
wrong pins, unsafe paths, missing required package metadata, or any bytecode fail
closed. Legacy migration/record functions remain historical regression coverage;
they are not a fallback in the fresh install CLI.

Before any host change, independently approve the exact source commit, tool revision,
wheel pins/provenance, reproduced bundle, manifest digest and server action. Separate
approval is still required to place tools/bundle/manifest on DigitalOcean and to run
installation or the synthetic transient unit. Existing root ownership, ACL, symlink,
hardlink, mount, account, exact-inventory and no-overwrite checks are retained.
The [deployment procedure](M78_DIGITALOCEAN_PROCEDURE.md) uses the new manifest with
the same fixed isolated destination and read-only preflight defaults.

The owner reports that the direct-host audit at main 24fb4d1 passed metadata checks:
volume mounted read/write, UID 997/GID 986 idle, isolated destination absent, no audit
issues. This does not authenticate package artifacts or test namespaces. Overall
readiness remains **FAIL**, target security **NOT_TESTED** until the separately
approved target checks pass. Production evidence staging and execution require
further explicit authorization. No DigitalOcean changes, M78 production execution,
Amazon calls, registry changes, service restarts or reboot were performed by this work.
