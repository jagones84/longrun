/* Longrun WebUI — one vocabulary for "what is this file".
   v1011 (operator): *"there doesnt exist standard way to display each file type?
   … for code also search how to be displayed in ide, with correct colors different
   for objects etcetera and so on for other extension files"*.

   The editor dock and the preview window must not each own a table that drifts:
   the file opened from My Artifacts has to be coloured exactly like the same file
   opened in the dock. This module is that single table — viewer family, language
   name, and the CodeMirror extension that paints it.

   Languages: CodeMirror 6 Lezer for javascript/python/json/markdown/html/css/yaml
   (the packages the main bundle already carries) and the vendored legacy stream
   parsers (vendor/langs.js) for everything else — shell, go, rust, c/cpp, java,
   sql, xml, toml, dockerfile, diff, ruby, lua, … So a `.rs` or `.sql` file is not
   "plain text with a monospace font" any more. */
import {
  StreamLanguage, javascript, python, json, markdown, html, css, yaml,
} from "./vendor/codemirror.js";
import {
  c, cpp, java, csharp, kotlin, objectiveC, dart, scala,
  shell, go, rust, toml, dockerFile, diff, lua, ruby, perl, powerShell, r, swift,
  standardSQL, mySQL, pgSQL, xml, sass, stylus, properties, cmake, nginx, protobuf,
  julia, haskell, erlang, clojure, groovy, elm, crystal, d, fortran, pascal,
  verilog, vhdl, tcl, vb, stex,
} from "./vendor/langs.js";

/* JAG-232/JAG-526: NO "svg" — the raw route refuses `image/svg+xml` on purpose
   (a served SVG runs its embedded JS at this origin), so an SVG is XML: text. */
export const IMG_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "ico", "bmp", "avif"]);

/* Extension → CodeMirror language name (`null` = plain text). Names are the
   switch keys in `langExt`, so adding an extension never needs new paint code. */
export const EXT_LANG = {
  js: "javascript", mjs: "javascript", cjs: "javascript", jsx: "javascript",
  ts: "javascript", tsx: "javascript",
  py: "python", pyi: "python",
  json: "json", jsonl: "json", ndjson: "json", geojson: "json", ipynb: "json",
  md: "markdown", markdown: "markdown", mdx: "markdown",
  html: "html", htm: "html", xhtml: "html", vue: "html", svelte: "html", hbs: "html",
  css: "css", scss: "css", less: "css",
  yml: "yaml", yaml: "yaml",
  xml: "xml", svg: "xml", xsl: "xml", xsd: "xml", plist: "xml",
  c: "c", h: "c",
  cpp: "cpp", cxx: "cpp", cc: "cpp", hpp: "cpp", hxx: "cpp",
  cs: "csharp", java: "java", kt: "kotlin", kts: "kotlin", scala: "scala",
  mm: "objectivec", dart: "dart",
  sh: "shell", bash: "shell", zsh: "shell", fish: "shell", bat: "shell", cmd: "shell",
  ps1: "powershell", psm1: "powershell",
  sql: "sql", rs: "rust", go: "go", rb: "ruby", rake: "ruby", gemspec: "ruby",
  pl: "perl", pm: "perl", lua: "lua", r: "r", swift: "swift",
  toml: "toml", ini: "properties", cfg: "properties", conf: "properties",
  env: "properties", properties: "properties",
  dockerfile: "dockerfile", diff: "diff", patch: "diff",
  sass: "sass", styl: "stylus", stylus: "stylus",
  tex: "stex", latex: "stex", ltx: "stex",
  cmake: "cmake", nginx: "nginx", proto: "protobuf",
  jl: "julia", hs: "haskell", erl: "erlang", hrl: "erlang",
  clj: "clojure", cljs: "clojure", cljc: "clojure", edn: "clojure",
  groovy: "groovy", gradle: "groovy", elm: "elm", cr: "crystal", d: "d",
  f: "fortran", f77: "fortran", f90: "fortran", f95: "fortran",
  pas: "pascal", vhd: "vhdl", vhdl: "vhdl", sv: "verilog", svh: "verilog",
  tcl: "tcl", vb: "vb", bas: "vb",
};

export function extOf(p) {
  const m = /\.([a-z0-9]+)$/i.exec(String(p || ""));
  return m ? m[1].toLowerCase() : "";
}

/* The editor dock's families. The preview window has richer families (video,
   audio, csv table) and owns those in index.html — this one must not change the
   dock's behaviour. */
export function viewerFor(p) {
  const e = extOf(p);
  if (IMG_EXT.has(e)) return "image";
  if (e === "pdf") return "pdf";
  // EV-45: a workbook is DATA, not a blob — the dock renders a table.
  if (e === "xlsx" || e === "xlsm") return "sheet";
  if (e === "md" || e === "markdown") return "markdown";
  if (e === "html" || e === "htm") return "html";
  return "code";
}

export function langOf(p) { return EXT_LANG[extOf(p)] || null; }

/* CodeMirror 6 exposes the stream-parser wrapper as `StreamLanguage.define`
   (there is no `.of`); a wrong factory here is invisible until a `.sh` opens, so
   `v1011` A3 pins this call. */
const STREAM = m => StreamLanguage.define(m);

export function langExt(name) {
  switch (name) {
    case "javascript": return javascript();
    case "python": return python();
    case "json": return json();
    case "markdown": return markdown();
    case "html": return html();
    case "css": return css();
    case "yaml": return yaml();
    case "c": return STREAM(c);
    case "cpp": return STREAM(cpp);
    case "java": return STREAM(java);
    case "csharp": return STREAM(csharp);
    case "kotlin": return STREAM(kotlin);
    case "objectivec": return STREAM(objectiveC);
    case "dart": return STREAM(dart);
    case "scala": return STREAM(scala);
    case "shell": return STREAM(shell);
    case "powershell": return STREAM(powerShell);
    case "go": return STREAM(go);
    case "rust": return STREAM(rust);
    case "toml": return STREAM(toml);
    case "dockerfile": return STREAM(dockerFile);
    case "diff": return STREAM(diff);
    case "lua": return STREAM(lua);
    case "ruby": return STREAM(ruby);
    case "perl": return STREAM(perl);
    case "r": return STREAM(r);
    case "swift": return STREAM(swift);
    case "sql": return STREAM(standardSQL);
    case "mysql": return STREAM(mySQL);
    case "pgsql": return STREAM(pgSQL);
    case "xml": return STREAM(xml);
    case "sass": return STREAM(sass);
    case "stylus": return STREAM(stylus);
    case "properties": return STREAM(properties);
    case "cmake": return STREAM(cmake);
    case "nginx": return STREAM(nginx);
    case "protobuf": return STREAM(protobuf);
    case "julia": return STREAM(julia);
    case "haskell": return STREAM(haskell);
    case "erlang": return STREAM(erlang);
    case "clojure": return STREAM(clojure);
    case "groovy": return STREAM(groovy);
    case "elm": return STREAM(elm);
    case "crystal": return STREAM(crystal);
    case "d": return STREAM(d);
    case "fortran": return STREAM(fortran);
    case "pascal": return STREAM(pascal);
    case "verilog": return STREAM(verilog);
    case "vhdl": return STREAM(vhdl);
    case "tcl": return STREAM(tcl);
    case "vb": return STREAM(vb);
    case "stex": return STREAM(stex);
    default: return null;
  }
}
