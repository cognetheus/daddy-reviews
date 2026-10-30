"use strict";
/**
 * R7.02: TypeScript 6 compiler API, read-only virtual source tree.
 *
 * All project source comes from a bounded Python-verified snapshot via stdin.
 * The compiler host will read ONLY that input or TypeScript's own lib .d.ts
 * files. It does not execute project code, hooks, package installs, or scripts.
 */
const ts = require("typescript");
const fs = require("node:fs");
const path = require("node:path");

const MAX_INPUT = 7_000_000;
const MAX_RESULTS = 500;
const result = {format: "daddy-reviews-ts-semantic-v1", status: "unavailable",
                compiler_version: ts.version, target: null, references: [],
                warnings: [], limitations: [
                  "TypeScript symbol identity is not runtime call reachability.",
                  "Project sources are loaded from a bounded read-only virtual host.",
                  "This R7.02 adapter handles one root tsconfig; nested projects and config extends abstain."
                ]};
function finish(status, reason) {
  result.status = status;
  if (reason) result.warnings.push(reason);
  process.stdout.write(JSON.stringify(result));
}
function validRelative(s) {
  return typeof s === "string" && s.length > 0 && s.length < 1024 &&
    !s.includes("\\") && !s.includes("\0") && !s.includes("\n") &&
    !s.startsWith("/") && s.split("/").every(x => x && x !== "." && x !== "..");
}
function safeLocation(node) {
  const sf = node.getSourceFile();
  const rel = path.relative(project, path.resolve(sf.fileName)).replace(/\\/g, "/");
  if (!validRelative(rel) || !sourceNames.has(rel)) return null;
  const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
  return {path: rel, line};
}
function canonicalSymbol(checker, symbol) {
  if (!symbol) return null;
  const visited = new Set();
  while ((symbol.flags & ts.SymbolFlags.Alias) !== 0) {
    if (visited.has(symbol)) return null;
    visited.add(symbol);
    const underlying = checker.getAliasedSymbol(symbol);
    if (!underlying || underlying === symbol) return null;
    symbol = underlying;
  }
  return symbol;
}
function symbolMatches(checker, candidate, target) {
  return canonicalSymbol(checker, candidate) === target;
}
function traverse(node, visitor) {
  visitor(node);
  ts.forEachChild(node, child => traverse(child, visitor));
}
function isDeclaration(node) {
  return ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node) ||
    ts.isVariableDeclaration(node) || ts.isMethodDeclaration(node) ||
    ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node) ||
    ts.isEnumDeclaration(node);
}
function invocationName(node) {
  if (ts.isIdentifier(node) && ts.isTypeReferenceNode(node.parent) &&
      node.parent.typeName === node) return "type_reference";
  if (ts.isIdentifier(node) && ts.isExpressionWithTypeArguments(node.parent) &&
      node.parent.expression === node) return "heritage_reference";
  if (ts.isIdentifier(node) && ts.isCallExpression(node.parent) &&
      node.parent.expression === node) return "direct_call";
  if (ts.isIdentifier(node) && ts.isNewExpression(node.parent) &&
      node.parent.expression === node) return "constructor_call";
  if (ts.isIdentifier(node) && ts.isPropertyAccessExpression(node.parent) &&
      node.parent.name === node) {
    const access = node.parent;
    if (ts.isCallExpression(access.parent) && access.parent.expression === access)
      return "member_call";
    return "property_reference";
  }
  return null;
}
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => {
  input += chunk;
  if (Buffer.byteLength(input, "utf8") > MAX_INPUT) {
    finish("incomplete", "Compiler input exceeds bounded budget");
    process.exit(0);
  }
});
process.stdin.on("end", () => {
  try { run(JSON.parse(input)); }
  catch (_error) { finish("incomplete", "Compiler adapter failed to process bounded source snapshot"); }
});
let project, sourceNames;
function run(req) {
  if (!req || typeof req !== "object" || typeof req.root !== "string" ||
      !path.isAbsolute(req.root) || !Array.isArray(req.sources) ||
      !req.target || !validRelative(req.target.path) ||
      typeof req.target.symbol !== "string" ||
      !/^[A-Za-z_$][\w$]*$/.test(req.target.symbol)) {
    return finish("invalid", "Invalid semantic compiler request");
  }
  project = path.resolve(req.root);
  result.target = {path: req.target.path, symbol: req.target.symbol};
  sourceNames = new Set();
  const virtual = new Map();
  let bytes = 0;
  for (const entry of req.sources) {
    if (!entry || !validRelative(entry.path) || typeof entry.text !== "string" ||
        sourceNames.has(entry.path)) return finish("invalid", "Duplicate or unsafe source record");
    sourceNames.add(entry.path);
    bytes += Buffer.byteLength(entry.text, "utf8");
    if (bytes > 5_000_000 || sourceNames.size > 800)
      return finish("incomplete", "Source indexing budget exceeded");
    virtual.set(path.resolve(project, entry.path), entry.text);
  }
  if (!sourceNames.has(req.target.path)) return finish("unresolved", "Target is not in source snapshot");
  if (sourceNames.size === 0) return finish("unresolved", "No indexed TS/JS sources");
  const ownLib = path.dirname(require.resolve("typescript"));
  const libAllow = file => {
    const name = path.basename(file);
    return path.dirname(file) === ownLib && /^lib(?:\.[\w.-]+)?\.d\.ts$/.test(name);
  };
  const real = ts.createCompilerHost({}, true);
  const read = filename => {
    const normalized = path.resolve(filename);
    if (virtual.has(normalized)) return virtual.get(normalized);
    if (libAllow(normalized)) return fs.readFileSync(normalized, "utf8");
    return undefined;
  };
  const present = filename => {
    const normalized = path.resolve(filename);
    return virtual.has(normalized) || (libAllow(normalized) && fs.existsSync(normalized));
  };
  const folder = filename => {
    const normalized = path.resolve(filename);
    if (normalized === ownLib) return true;
    if (normalized === project) return true;
    for (const file of virtual.keys()) {
      if (file.startsWith(normalized + path.sep)) return true;
    }
    return false;
  };
  const cfg = virtual.get(path.resolve(project, "tsconfig.json")) ||
              virtual.get(path.resolve(project, "jsconfig.json"));
  let options = {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
    moduleResolution: ts.ModuleResolutionKind.Node10,
    allowJs: true, checkJs: false, jsx: ts.JsxEmit.Preserve,
    noEmit: true, skipLibCheck: true, ignoreDeprecations: "6.0"
  };
  if (cfg !== undefined) {
    const parsed = ts.parseConfigFileTextToJson("tsconfig.json", cfg);
    if (parsed.error || !parsed.config || typeof parsed.config !== "object")
      return finish("incomplete", "Root TS/JS config could not be parsed");
    if (parsed.config.extends || parsed.config.references) {
      return finish("incomplete", "Extended or referenced tsconfig needs a separate project-aware adapter");
    }
    const converted = ts.convertCompilerOptionsFromJson(
      parsed.config.compilerOptions || {}, project, "tsconfig.json");
    if (converted.errors.length) return finish("incomplete", "Invalid compiler options in root config");
    options = {...options, ...converted.options, noEmit: true,
               allowJs: true, skipLibCheck: true, types: [], typeRoots: [],
               noResolve: false, noLib: false};
    if (options.plugins?.length) return finish("incomplete", "Compiler plugin execution is not supported");
  }
  const host = {...real};
  host.getCurrentDirectory = () => project;
  host.fileExists = present;
  host.readFile = read;
  host.directoryExists = folder;
  host.getDirectories = () => [];
  host.realpath = filename => path.resolve(filename);
  host.getSourceFile = (filename, languageVersion, onError) => {
    try {
      const data = read(filename);
      if (data === undefined) return undefined;
      return ts.createSourceFile(filename, data, languageVersion, true);
    } catch (_error) {
      if (onError) onError("Source unavailable");
      return undefined;
    }
  };
  host.writeFile = () => { throw new Error("Compiler output prohibited"); };
  const roots = [...virtual.keys()].filter(x => /\.(ts|tsx|js|jsx|mts|cts)$/.test(x));
  const program = ts.createProgram(roots, options, host);
  const checker = program.getTypeChecker();
  const targetSF = program.getSourceFile(path.resolve(project, req.target.path));
  if (!targetSF) return finish("unresolved", "Target source was not loaded by compiler");
  const declarations = new Set();
  traverse(targetSF, node => {
    if (isDeclaration(node) && node.name &&
        ts.isIdentifier(node.name) && node.name.text === req.target.symbol) {
      const resolved = canonicalSymbol(checker, checker.getSymbolAtLocation(node.name));
      if (resolved) declarations.add(resolved);
    }
  });
  if (declarations.size === 0) return finish("unresolved", "No compiler-resolved target declaration");
  if (declarations.size !== 1) return finish("ambiguous", "Multiple unrelated target declarations");
  const target = [...declarations][0];
  const location = (target.declarations || []).map(d => safeLocation(d)).find(Boolean);
  if (!location) return finish("unresolved", "Target declaration is not inside provided snapshot");
  result.target.definition = location;
  const refs = [];
  const seen = new Set();
  let budgetExceeded = false;
  for (const sf of program.getSourceFiles()) {
    const rel = path.relative(project, path.resolve(sf.fileName)).replace(/\\/g, "/");
    if (!validRelative(rel) || !sourceNames.has(rel) || rel === req.target.path) continue;
    traverse(sf, node => {
      if (budgetExceeded || !ts.isIdentifier(node)) return;
      const relationship = invocationName(node);
      if (!relationship) return;
      const symbol = checker.getSymbolAtLocation(node);
      if (!symbolMatches(checker, symbol, target)) return;
      const loc = safeLocation(node);
      if (!loc) return;
      const key = loc.path + ":" + loc.line + ":" + relationship;
      if (seen.has(key)) return;
      seen.add(key);
      refs.push({...loc, relationship});
      if (refs.length >= MAX_RESULTS) budgetExceeded = true;
    });
  }
  refs.sort((a,b) => a.path.localeCompare(b.path) || a.line-b.line ||
            a.relationship.localeCompare(b.relationship));
  result.references = refs;
  if (budgetExceeded) result.warnings.push("Reference output budget reached; index is incomplete");
  const diagnostics = program.getSyntacticDiagnostics().concat(program.getOptionsDiagnostics());
  const unresolvedImports = program.getSemanticDiagnostics().filter(d =>
    [2304, 2305, 2307, 2792, 7016].includes(d.code));
  if (diagnostics.length) result.warnings.push(
    "Compiler reported " + diagnostics.length + " syntax/configuration diagnostic(s); review results cautiously");
  if (unresolvedImports.length) result.warnings.push(
    "Compiler reported " + unresolvedImports.length +
    " unresolved name/import diagnostic(s); results may omit consumers");
  result.status = (budgetExceeded || diagnostics.length || unresolvedImports.length) ?
    "partial" : "complete";
  finish(result.status, null);
}
