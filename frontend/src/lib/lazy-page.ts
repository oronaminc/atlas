import { type ComponentType, lazy } from "react";

/** React.lazy wrapper that resolves either a default export or a named one
 *  (most pages export `export function FooPage`, /graph uses default). */
export function lazyPage<M extends Record<string, unknown>>(
  importer: () => Promise<M>,
  exportName?: keyof M,
) {
  return lazy(async () => {
    const mod = await importer();
    const Comp = (exportName ? mod[exportName] : mod["default"]) as ComponentType | undefined;
    if (!Comp) throw new Error(`lazyPage: export ${String(exportName ?? "default")} not found`);
    return { default: Comp };
  });
}
