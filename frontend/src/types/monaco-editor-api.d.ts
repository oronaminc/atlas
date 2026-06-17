// The editor *core API* entry (no language grammars) has no subpath in
// monaco-editor's package `exports`, so `moduleResolution: bundler` can't see
// its types. Re-export the full monaco-editor type surface (types only — no
// runtime weight) so `@/lib/monaco` keeps full typing while loading core only.
declare module "monaco-editor/esm/vs/editor/editor.api" {
  export * from "monaco-editor";
}
