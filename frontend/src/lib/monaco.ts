// Bundle monaco locally instead of loading it from the jsdelivr CDN so the
// editor works in air-gapped/internal deployments.
import * as monaco from "monaco-editor";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import { loader } from "@monaco-editor/react";

self.MonacoEnvironment = {
  // Only plaintext is used (PromQL/LogQL have no built-in language), so the
  // base editor worker is sufficient.
  getWorker: () => new editorWorker(),
};

loader.config({ monaco });
