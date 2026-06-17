// Bundle monaco locally instead of loading it from the jsdelivr CDN so the
// editor works in air-gapped/internal deployments.
// Import the editor *core API* only — NOT the `monaco-editor` barrel, which
// pulls in every bundled language grammar (abap/pgsql/solidity/...). We only
// use plaintext, so the grammars are dead weight.
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import { loader } from "@monaco-editor/react";

self.MonacoEnvironment = {
  // Only plaintext is used (PromQL/LogQL have no built-in language), so the
  // base editor worker is sufficient.
  getWorker: () => new editorWorker(),
};

loader.config({ monaco });
