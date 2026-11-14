#!/usr/bin/env bash
# Rebuild the vendored WebUI editor libs (CodeMirror 6 + marked + DOMPurify).
# One-off build; needs node >= 18, npm and network access. The generated files
# under ./vendor are committed, so this is only run to bump the libraries.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/vendor"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
mkdir -p "$OUT"
cd "$BUILD"
printf '{"private":true,"type":"module"}\n' > package.json

npm install --no-audit --no-fund \
  @codemirror/state @codemirror/view @codemirror/commands @codemirror/language \
  @codemirror/search @codemirror/autocomplete \
  @codemirror/lang-javascript @codemirror/lang-python @codemirror/lang-json \
  @codemirror/lang-markdown @codemirror/lang-html @codemirror/lang-css \
  @codemirror/lang-yaml @codemirror/theme-one-dark \
  @codemirror/legacy-modes marked dompurify esbuild

cat > cm-entry.js <<'EOF'
export { EditorState, Compartment } from "@codemirror/state";
export { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, drawSelection, dropCursor, rectangularSelection, crosshairCursor, highlightSpecialChars } from "@codemirror/view";
export { defaultKeymap, history, historyKeymap, indentWithTab, undo, redo } from "@codemirror/commands";
export { syntaxHighlighting, defaultHighlightStyle, bracketMatching, indentOnInput, foldGutter, foldKeymap, LanguageSupport, StreamLanguage } from "@codemirror/language";
export { searchKeymap, highlightSelectionMatches, openSearchPanel } from "@codemirror/search";
export { autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
export { javascript } from "@codemirror/lang-javascript";
export { python } from "@codemirror/lang-python";
export { json } from "@codemirror/lang-json";
export { markdown } from "@codemirror/lang-markdown";
export { html } from "@codemirror/lang-html";
export { css } from "@codemirror/lang-css";
export { yaml } from "@codemirror/lang-yaml";
export { oneDark } from "@codemirror/theme-one-dark";
EOF

cat > marked-entry.js <<'EOF'
import { marked } from "marked";
window.marked = marked;
EOF

cat > purify-entry.js <<'EOF'
import DOMPurify from "dompurify";
window.DOMPurify = DOMPurify;
EOF

# v1011: the read-only preview must colour the same extensions the editor opens,
# and the main bundle only carries seven Lezer languages. The legacy stream
# parsers are plain functions (no CodeMirror runtime import), so they are built
# as their OWN module: filetypes.js wraps them with `StreamLanguage.define(...)`
# from the existing bundle, and no second copy of the editor runtime is shipped.
cat > langs-entry.js <<'EOF'
export { c, cpp, java, csharp, kotlin, objectiveC, dart, scala } from "@codemirror/legacy-modes/mode/clike";
export { shell } from "@codemirror/legacy-modes/mode/shell";
export { go } from "@codemirror/legacy-modes/mode/go";
export { rust } from "@codemirror/legacy-modes/mode/rust";
export { toml } from "@codemirror/legacy-modes/mode/toml";
export { dockerFile } from "@codemirror/legacy-modes/mode/dockerfile";
export { diff } from "@codemirror/legacy-modes/mode/diff";
export { lua } from "@codemirror/legacy-modes/mode/lua";
export { ruby } from "@codemirror/legacy-modes/mode/ruby";
export { perl } from "@codemirror/legacy-modes/mode/perl";
export { powerShell } from "@codemirror/legacy-modes/mode/powershell";
export { r } from "@codemirror/legacy-modes/mode/r";
export { swift } from "@codemirror/legacy-modes/mode/swift";
export { standardSQL, mySQL, pgSQL } from "@codemirror/legacy-modes/mode/sql";
export { xml } from "@codemirror/legacy-modes/mode/xml";
export { sass } from "@codemirror/legacy-modes/mode/sass";
export { stylus } from "@codemirror/legacy-modes/mode/stylus";
export { properties } from "@codemirror/legacy-modes/mode/properties";
export { cmake } from "@codemirror/legacy-modes/mode/cmake";
export { nginx } from "@codemirror/legacy-modes/mode/nginx";
export { protobuf } from "@codemirror/legacy-modes/mode/protobuf";
export { julia } from "@codemirror/legacy-modes/mode/julia";
export { haskell } from "@codemirror/legacy-modes/mode/haskell";
export { erlang } from "@codemirror/legacy-modes/mode/erlang";
export { clojure } from "@codemirror/legacy-modes/mode/clojure";
export { groovy } from "@codemirror/legacy-modes/mode/groovy";
export { elm } from "@codemirror/legacy-modes/mode/elm";
export { crystal } from "@codemirror/legacy-modes/mode/crystal";
export { d } from "@codemirror/legacy-modes/mode/d";
export { fortran } from "@codemirror/legacy-modes/mode/fortran";
export { pascal } from "@codemirror/legacy-modes/mode/pascal";
export { verilog } from "@codemirror/legacy-modes/mode/verilog";
export { vhdl } from "@codemirror/legacy-modes/mode/vhdl";
export { tcl } from "@codemirror/legacy-modes/mode/tcl";
export { vb } from "@codemirror/legacy-modes/mode/vb";
export { stex } from "@codemirror/legacy-modes/mode/stex";
EOF

npx esbuild cm-entry.js --bundle --format=esm --minify --outfile="$OUT/codemirror.js"
npx esbuild langs-entry.js --bundle --format=esm --minify --outfile="$OUT/langs.js"
npx esbuild marked-entry.js --bundle --format=iife --minify --outfile="$OUT/marked.min.js"
npx esbuild purify-entry.js --bundle --format=iife --minify --outfile="$OUT/purify.min.js"
ls -l "$OUT"
