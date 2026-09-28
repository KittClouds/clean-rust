#!/usr/bin/env sh
# Fetches the pinned ONNX Runtime DLLs described by manifest.json and refuses anything else.
# Usage: sh fetch.sh [local .whl]   (needs curl or a local wheel, unzip, sha256sum)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
url="https://files.pythonhosted.org/packages/3c/dd/c57c529dbc6dd55eca24b12cfbeab1b6a690de72083824eca689085f55b0/onnxruntime-1.30.0-cp313-cp313-win_amd64.whl"
wheel_name="onnxruntime-1.30.0-cp313-cp313-win_amd64.whl"
if (cd "$here" && sha256sum --status -c SHA256SUMS --ignore-missing 2>/dev/null) \
   && [ -f "$here/onnxruntime.dll" ] && [ -f "$here/onnxruntime_providers_shared.dll" ]; then
  echo "onnxruntime 1.30.0: all files present and verified"; exit 0
fi
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
wheel="${1:-}"
if [ -z "$wheel" ]; then wheel="$tmp/$wheel_name"; curl -fsSL -o "$wheel" "$url"; fi
cp "$wheel" "$tmp/$wheel_name" 2>/dev/null || true
(cd "$tmp" && grep " $wheel_name\$" "$here/SHA256SUMS" | sha256sum -c -) || { echo "wheel hash mismatch" >&2; exit 1; }
unzip -q -j -o "$tmp/$wheel_name" onnxruntime/capi/onnxruntime.dll onnxruntime/capi/onnxruntime_providers_shared.dll -d "$tmp/out"
(cd "$tmp/out" && grep "dll\$" "$here/SHA256SUMS" | sha256sum -c -) || { echo "extracted DLL hash mismatch" >&2; exit 1; }
mv -f "$tmp/out/"*.dll "$here/"
echo "onnxruntime 1.30.0: fetched and verified"
